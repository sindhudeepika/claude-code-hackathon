# Discovery: Contoso Financial On-Prem Current State

**Date:** 2026-04-28  
**Method:** Code inspection, config file review, stakeholder interviews (roles played with Claude)  
**Status:** Complete — five migration blockers identified

---

## Workload Inventory

| Workload | On-prem host | Stack | Owner | Nightly downtime window |
|---|---|---|---|---|
| Customer portal (webapp) | `app01.internal:3000` | Node.js 16, Express 4, PostgreSQL client | Digital team | None — 24/7 |
| Batch reconciliation | `batch01.internal` | Python 3.9, cron via `/etc/cron.d/` | Finance ops | 02:00–04:00 UTC |
| Reporting database | `db01.internal:5432` | PostgreSQL 14, 5 direct-query clients | BI, Risk, Finance, Compliance, Ops | None — always-on |

---

## Finding #1 — Hardcoded Auth Service IP (Migration Blocker)

**Workload:** webapp  
**File:** `workloads/webapp/src/config.js`  
**Line:** `authServiceUrl: process.env.AUTH_SERVICE_URL || 'http://10.0.1.45:8080/auth/validate'`

The webapp validates session tokens by calling an internal auth service at a hardcoded RFC1918
IP. This IP is not routable in Azure. If `AUTH_SERVICE_URL` is not set as an environment
variable, every authenticated request silently falls through to an error path.

**On-prem behaviour:** Works. `10.0.1.45` is a physical host on the same LAN.  
**Azure behaviour:** Silent failure. TCP connections to `10.0.1.45` time out. Session validation
returns 500 after the default 30-second timeout, degrading every authenticated user session.

**Resolution (Phase 1):** Set `AUTH_SERVICE_URL` in the Container App environment to point at
the on-prem auth service via Site-to-Site VPN (temporary). Phase 2: replace with Azure AD B2C.  
**Validation test:** `test_discovery_findings.py::test_auth_url_not_rfc1918`

---

## Finding #2 — Local Filesystem Log File (Silent Data Loss Risk)

**Workload:** webapp  
**File:** `workloads/webapp/src/config.js`  
**Default:** `logFile: process.env.LOG_FILE || null` (null = stdout, safe)

The original on-prem app wrote logs to `/var/log/contoso/app.log` on the host filesystem.
The containerised version sets `LOG_FILE` to `null` by default (forcing stdout), but the
on-prem configuration management still sets `LOG_FILE=/var/log/contoso/app.log` via Ansible.
If that environment variable is accidentally carried into the Azure Container App, logs will
be written to the container's ephemeral filesystem and lost on restart.

**On-prem behaviour:** Works. `/var/log/contoso/app.log` is on a persistent host volume.  
**Azure behaviour:** Logs written to ephemeral container filesystem. Container restarts (which
Container Apps performs for health check failures and scaling events) silently discard all logs.

**Resolution (Phase 1):** Do not set `LOG_FILE` in the Container App environment. Confirm
`LOG_FILE` is absent from the deployment manifest before cutover.  
**Validation test:** `test_discovery_findings.py::test_logs_go_to_stdout`

---

## Finding #3 — NFS-Mounted Feed Directory (Migration Blocker)

**Workload:** batch  
**File:** `workloads/batch/reconcile.py`  
**Line:** `FEED_SOURCE = os.environ.get('FEED_STORAGE_CONNECTION') or '/mnt/findata/feeds'`

The nightly batch job reads the payment processor daily feed from an NFS share mounted at
`/mnt/findata/feeds`. Azure Container App Jobs do not support NFS mounts. If
`FEED_STORAGE_CONNECTION` is not set, the job falls back to the local path, finds nothing,
and exits successfully with zero rows processed — a silent wrong-result failure.

**On-prem behaviour:** Works. NFS mount is permanent and maintained by the infra team.  
**Azure behaviour:** `/mnt/findata/feeds` does not exist. The job reads zero records, produces
a reconciliation report with `total_processed = 0`, and marks itself succeeded. Finance ops
does not notice until the next business day when GL entries are missing.

**Resolution (Phase 1):** Payment processor feed is uploaded to Azure Blob Storage. Set
`FEED_STORAGE_CONNECTION` to the Blob Storage SAS URL or Managed Identity connection string.
The batch job code already handles both paths; only the environment variable needs setting.  
**Validation test:** `test_discovery_findings.py::test_feed_source_not_local_filesystem`

---

## Finding #4 — Plaintext DB Password in Config File (Security Blocker)

**Workload:** batch  
**File:** `/etc/contoso/config.ini` (on-prem host, not in repo)

The batch job reads its database connection string from a config file at
`/etc/contoso/config.ini`. The file contains:

```ini
[database]
host = db01.internal
port = 5432
name = contoso
user = batch_user
password = C0nt0s0B@tch2021!
```

This file is managed by Ansible and not tracked in git. However, the same password has been
in use since the system was commissioned in 2021. Three people who have since left the company
had access to this host and its Ansible variables.

**On-prem behaviour:** Works. File is on a locked-down host; access is SSH-key restricted.  
**Azure behaviour:** Container App Jobs do not have persistent filesystems. The config file
would need to be baked into the container image or injected at runtime — both approaches are
insecure.

**Resolution (Phase 1):** Remove config file dependency entirely. The batch job uses
`os.environ.get('DB_PASSWORD')` as its primary path; Key Vault secret reference is used to
inject this at runtime via Managed Identity. The Ansible password must also be rotated.  
**Validation test:** `test_discovery_findings.py::test_db_credentials_from_env_not_file`

---

## Finding #5 — Redis Keepalive Cron Hitting Hardcoded IP (Migration Blocker)

**Workload:** webapp host (cron job, not in the app itself)  
**File:** `/etc/cron.d/contoso-keepalive` on `app01.internal`

A cron job runs every 5 minutes and pings `http://10.0.1.30:9090/cache/warm` to prevent the
on-prem Redis cache from evicting hot session keys. The cache warm endpoint is served by a
small Flask app co-located with Redis.

This cron job is not documented anywhere. It was discovered during OS-level config inspection.

**On-prem behaviour:** Works. Prevents session key eviction under low overnight traffic.  
**Azure behaviour:** `10.0.1.30` is not routable. The keepalive calls time out silently. More
importantly, Azure Cache for Redis does not require external keepalive pings — it handles key
TTL and eviction natively via its configuration. The Flask cache-warm app does not exist in
Azure.

**Resolution (Phase 1):** Do not migrate the keepalive cron. Confirm that Redis session key TTL
is configured in the webapp itself (not relying on external pinging). Set Redis `maxmemory-policy`
to `allkeys-lru` in the Azure Cache for Redis instance.  
**Validation test:** `test_discovery_findings.py::test_no_keepalive_required`

---

## Cross-Workload Dependencies

| From | To | Type | Notes |
|---|---|---|---|
| webapp | PostgreSQL | TCP:5432 | Session store + customer data reads |
| webapp | Redis | TCP:6379 | Session cache |
| webapp | Auth service (`10.0.1.45:8080`) | HTTP | Finding #1 — migration blocker |
| batch | PostgreSQL | TCP:5432 | Transaction reads + reconciliation writes |
| batch | Feed storage (`/mnt/findata/feeds`) | NFS | Finding #3 — migration blocker |
| batch | `/etc/contoso/config.ini` | File | Finding #4 — security blocker |
| reporting queries | PostgreSQL | TCP:5432 | 5 direct-query clients from BI, Risk, Finance, Compliance, Ops |

---

## Stakeholder Interview Highlights

**CFO Office:** "The lease renewal is October. If we're still on-prem in November, that's
another £480k. There is no scenario where we extend."

**CTO:** "I'm not signing off on running a Node.js 16 monolith on Container Apps in 2027 and
calling it cloud-native. The lift-and-shift is fine as a bridge, but I want a roadmap."

**SRE Lead:** "The batch job has never missed a night in four years. I don't care what we
migrate to, I care that it keeps not missing nights. I want runbooks I can follow at 3am."

**Head of Compliance:** "Everything that touches account data stays in UK South. I don't care
about the architecture, I care about the residency. And I want to see the private endpoint
configuration before I sign anything."

These inputs directly shaped the decisions in ADR-001 and ADR-002.
