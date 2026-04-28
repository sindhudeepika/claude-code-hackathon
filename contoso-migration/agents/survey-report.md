# Contoso Financial — Agentic Survey Report
*Generated: 2026-04-28 10:35 UTC*
*Model: us.anthropic.claude-sonnet-4-6*
*Subagents: 3 (webapp, batch, reporting-db) — run in parallel*

---

# Contoso Financial Azure UK South Migration — Cross-Workload Architecture Review

**Document Type:** Technical Architecture Review — Migration Coordinator Synthesis
**Date:** 2026-04-28
**Input Sources:** Subagent reports (webapp, batch, reporting-db); Human discovery document (2026-04-28)
**Status:** Draft for SRE and Compliance sign-off

---

## Executive Summary

All three workloads are architecturally cloud-ready in structure, but are tightly coupled through a shared PostgreSQL database that no single workload owns, creating a sequencing constraint that the human discovery document acknowledges only partially and the subagents each saw only from their own perspective. The highest single risk is the absence of a formally agreed, simultaneous cutover plan for all three workloads: migrating any one in isolation will create a split-brain state where live financial transactions are written to one database tier while the reconciliation job or customer portal reads from another. The recommended first step is to complete the reporting-db migration and validate the Azure PostgreSQL instance end-to-end — including extension allowlisting, private endpoint, role creation, and a full pg_dump/restore test — before any application-layer workload is touched.

---

## Cross-Workload Coupling Found

| From | To | Coupling Type | Description | Migration Implication | Discovery Doc? |
|---|---|---|---|---|---|
| webapp | reporting-db | Database (read) | webapp reads `customers`, `accounts`, and `transactions` tables from the `contoso` database; schema is owned by reporting-db | reporting-db schema must be fully migrated and validated on Azure PostgreSQL before webapp cutover; any schema drift breaks webapp queries | **Partial** — discovery notes TCP:5432 dependency but does not name the schema owner or the shared database name |
| batch | reporting-db | Database (read + write) | batch reads `transactions` and writes `reconciliation_reports`; also issues `UPDATE transactions SET status='reconciled'` — write access to a table the webapp also reads | reporting-db must be migrated before batch can run; batch must be paused during any reporting-db read-only migration window | **Partial** — discovery notes TCP:5432 but does not identify the UPDATE write-back to `transactions` |
| webapp | batch | Shared database state | No direct API or queue coupling; both workloads share the `transactions` table — batch mutates `status`, webapp surfaces it to customers | Both workloads must be cut over to Azure simultaneously or customers will see stale reconciliation status; split-brain cutover is a data-correctness risk, not merely a connectivity risk | **MISSED** — discovery lists both as having PostgreSQL dependencies but does not identify the shared mutable state risk |
| webapp | auth service (`10.0.1.45`) | HTTP (synchronous, hard blocking) | Every authenticated webapp request calls the on-prem auth service; failure = 500 on all authenticated routes | Auth service must be reachable from Azure via Site-to-Site VPN before webapp cutover, or replaced with Azure AD B2C | Documented (Finding #1) |
| webapp | Redis (`10.0.1.30`) | TCP session cache | webapp uses Redis for session caching; Azure Cache for Redis requires TLS on port 6380, not plain TCP 6379 | `REDIS_TLS=true` and `REDIS_PORT=6380` must be set; TLS configuration is a hard runtime break, not a soft degradation | **Partially missed** — discovery documents the keepalive cron (Finding #5) but does not identify the TLS port change as a hard runtime blocker for the webapp itself |
| batch | Azure Blob Storage | Object storage (feed ingestion) | batch reads daily payment feed from Blob container `feeds`, filename pattern `YYYYMMDD_transactions.csv`; container name is hardcoded | Blob account must be provisioned with correct container name before first Azure run; naming deviation causes silent zero-row processing | Documented (Finding #3) |
| reporting-db | all five internal teams | Direct TCP:5432 (query clients) | BI, Risk, Finance, Compliance, Ops connect directly; no connection pooler is configured | VPN/ExpressRoute or private endpoint must be validated reachable from all five team client networks; PgBouncer must be configured before concurrent access causes connection exhaustion | **Partially missed** — discovery lists the five teams as consumers but does not identify connection-pool exhaustion or the VPN/private endpoint gap |

---

## Migration Risk Heatmap

| Workload | Cloud Readiness Score | Risk Level | Top Blocker |
|---|---|---|---|
| reporting-db | 7 / 10 | **Medium** | pgaudit/pgcrypto extensions must be allowlisted in `azure.extensions` before schema apply; combined with PCI/GDPR plaintext storage requiring a compliance sign-off before data lands in Azure |
| webapp | 7 / 10 | **Medium** | Hardcoded auth service URL (`10.0.1.45`) is a hard runtime blocker for all authenticated routes; Redis TLS port change will break sessions silently if not pre-configured |
| batch | 8 / 10 | **Low** | NFS dependency already resolved in code; main Phase 1 risk is `DB_SSLMODE` defaulting to `prefer` rather than `require`, which may allow unencrypted connections to Azure PostgreSQL in a financial production workload |

> **Note on scores:** The batch workload scores highest because its on-prem-specific dependencies (NFS mount, config file) were already removed from the codebase before this review. The webapp and reporting-db score identically at 7 but for different reasons: webapp has hard runtime blockers in application configuration; reporting-db has compliance and infrastructure provisioning gaps rather than code defects.

---

## Recommended Migration Order

1. **reporting-db — migrate first.**
   All three workloads depend on this schema. The batch job cannot write reconciliation reports without it; the webapp cannot serve customer data without it. Migrating reporting-db first establishes the authoritative Azure PostgreSQL instance, allows end-to-end connectivity testing from all consumers, and gives the Compliance team time to review plaintext PCI data residency before any application traffic flows. This step includes: IaC provisioning with `azure.extensions = pgcrypto,pgaudit`, private endpoint and VNet integration, pg_dump/restore from on-premises PostgreSQL (version to be confirmed — discovery states 14, reporting-db subagent targets 16; this discrepancy must be resolved before migration), role and permission creation, and a full read/write smoke test from a jump host in UK South.

2. **batch — migrate second, in the same change window as reporting-db cutover.**
   The batch job has the lowest cloud readiness risk and its dependencies are almost entirely resolved. Critically, it writes to `transactions.status` and `reconciliation_reports`, which the webapp reads. If batch remains on-premises pointing at the on-premises PostgreSQL while reporting-db has been migrated to Azure, the Azure database will receive no reconciliation updates and the on-premises database will receive none of the new customer activity written by the webapp. Therefore, batch must be cut over in the same coordinated window as reporting-db, not as a separate migration event. The Container App Job cron schedule (`0 2 * * *` UTC), retry limit (0), and `FEED_STORAGE_CONNECTION` must all be validated before the first nightly run in Azure.

3. **webapp — migrate last, in the same coordinated cutover window.**
   The webapp is the only customer-facing workload and the only one with a 24/7 availability requirement (confirmed in the discovery document: "None — 24/7"). It should be migrated last so that the database and batch infrastructure are proven stable before live customer traffic is redirected. However, "last" does not mean "in a separate window": because batch mutates `transactions.status` and the webapp surfaces this to customers, both application-layer workloads must be pointed at the Azure PostgreSQL instance simultaneously. The recommended approach is a single coordinated cutover window during the 02:00–04:00 UTC nightly batch window, during which: (a) reporting-db is already live on Azure, (b) batch is cut over and its first Azure run is validated, (c) webapp is redeployed with Azure environment variables, and (d) the on-premises app01 webapp is taken offline.

> **Sequencing constraint summary:** reporting-db is a hard prerequisite for both application workloads. The application workloads (webapp and batch) must be cut over simultaneously within a single maintenance window to avoid split-brain state on `transactions`.

---

## What the Human Discovery Missed

- **Shared mutable `transactions` table state between webapp and batch.** The discovery document correctly identifies that both workloads connect to PostgreSQL, but does not identify that the batch job issues `UPDATE transactions SET status='reconciled'` — a write to a table the webapp reads to display transaction status to customers. A cutover that migrates webapp and batch in separate windows would leave customers seeing stale reconciliation status, or worse, the on-premises and Azure databases diverging in `transactions.status` values. *(Source: batch subagent — cross_workload_coupling; webapp subagent — cross_workload_coupling.)*

- **Redis TLS port change (6379 → 6380) as a hard webapp runtime blocker.** The discovery document identifies the keepalive cron job on `10.0.1.30` (Finding #5) but focuses on the cron as the problem. The subagent analysis identified that Azure Cache for Redis mandates TLS on port 6380, meaning the webapp itself — not just the cron — requires `REDIS_TLS=true` and `REDIS_PORT=6380` to be explicitly set or session caching will fail with a connection refused error at startup. This is a separate and more severe issue than the keepalive cron. *(Source: webapp subagent — soft_dependencies.)*

- **`DB_SSL` defaults to `false` in the webapp and `DB_SSLMODE` defaults to `prefer` in the batch job.** Neither default is safe for Azure Database for PostgreSQL Flexible Server, which enforces TLS. The discovery document does not mention SSL/TLS connection requirements for either application workload. Both must have their SSL environment variables explicitly set before cutover or connections will be refused at runtime. *(Source: webapp subagent — phase1_blockers; batch subagent — soft_dependencies.)*

- **`x-pii-scope: internal` header bypass in the webapp is trivially spoofable from the internet.** The webapp grants fully unredacted PII (email, phone, account_number, sort_code, balance) to any HTTP request carrying `x-pii-scope: internal`. There is no gateway, IP restriction, or signed-token enforcement of this header. In the on-premises environment this may be mitigated by network perimeter controls; in Azure with a public Container Apps ingress, any external caller can include this header. This is a data protection risk that must be addressed before go-live and is not mentioned in the discovery document. *(Source: webapp subagent — soft_dependencies, pii_surface.)*

- **`customers.uk_postcode` is returned unredacted in the `/api/customers/:id` response despite being a PII field.** The discovery document does not enumerate the webapp's PII surface at the API layer. UK postcodes are linkable to individuals and are personal data under UK GDPR. *(Source: webapp subagent — pii_surface, recommendations.)*

- **No GDPR Article 17 (right to erasure) mechanism exists in the database schema.** The `customers` table has no `deleted_at` column, erasure log, or pseudonymisation procedure. The `ON DELETE RESTRICT` foreign key constraints on `accounts.customer_id` and `transactions.account_id` will block any attempt to delete a customer record. This is a compliance gap that must be resolved before migrated data is live in Azure UK South. *(Source: reporting-db subagent — recommendations.)*

- **PostgreSQL version discrepancy between discovery document and migration target.** The discovery document states the on-premises reporting database runs PostgreSQL 14. The reporting-db subagent targets Azure Database for PostgreSQL Flexible Server running PostgreSQL 16. A pg_dump from PostgreSQL 14 into a PostgreSQL 16 instance requires explicit validation, particularly for extension versions (pgaudit, pgcrypto) and any implicit type casts or operator differences. This gap is not acknowledged in the discovery document. *(Source: reporting-db subagent — phase1_blockers.)*

- **Connection pool exhaustion risk across all three workloads sharing a single Azure PostgreSQL Flexible Server.** With the webapp holding a pool of 10 connections per replica, the batch job connecting during its run window, and five internal teams querying directly, total connections against a single Flexible Server SKU may exceed the per-SKU limit. Neither the discovery document nor any single subagent has the full picture; this risk only becomes visible when all three workloads' connection requirements are summed. *(Source: webapp subagent — soft_dependencies; reporting-db subagent — soft_dependencies; batch subagent — cross_workload_coupling.)*

- **The hardcoded Blob container name `feeds` in `reconcile.py` creates an environment-separation risk.** If dev, staging, and production all use the same storage account, or if the container name differs from the assumed convention, the batch job fails silently with zero rows processed — the same failure mode as the original NFS fallback. This is not mentioned in the discovery document. *(Source: batch subagent — soft_dependencies.)*

- **The `sample_feed.csv` containing realistic-format UK sort codes and account numbers is baked into the production Docker image.** This file should not be present in production containers and should not be committed to shared repositories in its current form. *(Source: batch subagent — hard_dependencies; reporting-db subagent — recommendations.)*

---

## Phase 1 Blockers (Consolidated)

Blockers are listed in order of which workload they gate. All must be resolved before the coordinated cutover window opens.

### Networking and Connectivity

- **\[reporting-db\]** Azure Database for PostgreSQL Flexible Server must be deployed into a VNet with private DNS zone and private endpoint. VPN or ExpressRoute connectivity from all five internal team client networks must be confirmed reachable before go-live. No firewall or network access control is currently defined in the IaC.
- **\[webapp\]** `AUTH_SERVICE_URL` must be set to a reachable endpoint (on-prem auth service via Site-to-Site VPN, or a replacement service) in the Azure Container Apps environment. The default value `http://10.0.1.45:8080/auth/validate` is non-routable in Azure and will cause 100% authentication failure.
- **\[webapp\]** `REDIS_TLS=true` and `REDIS_PORT=6380` must be set in the Container Apps environment. Azure Cache for Redis does not accept plain TCP on port 6379.

### SSL / TLS Configuration

- **\[webapp\]** `DB_SSL=true` must be set in the Container Apps environment. Azure Database for PostgreSQL Flexible Server enforces TLS; the webapp defaults to `false`.
- **\[batch\]** `DB_SSLMODE=require` must be set in the Container App Job environment. The default `prefer` may permit an unencrypted connection and is insufficient for a production financial workload.

### Database Provisioning and Schema

- **\[reporting-db\]** `azure.extensions = pgcrypto,pgaudit` must be set as a server parameter at provisioning time (via IaC) before `schema.sql` is applied. `CREATE EXTENSION` commands will fail with permission denied without this pre-configuration.
- **\[reporting-db\]** The on-premises PostgreSQL version must be confirmed (discovery states 14; migration target is 16). A pg_upgrade validation path must be documented and tested before the pg_dump/restore migration proceeds.
- **\[reporting-db / webapp / batch\]** The webapp and batch cutover must be sequenced to the same window as reporting-db cutover to prevent split-brain state on the shared `transactions` table. A formal cutover runbook must be produced and signed off by the SRE Lead before the change window opens.
- **\[batch\]** The `reconciliation_reports` and `transactions` tables must exist and be accessible on the Azure PostgreSQL instance before the batch job's first Azure run. Schema migration is a hard prerequisite.

### Credential and Secret Management

- **\[webapp\]** The hardcoded fallback DB password `dev-only-not-for-prod` in `config.js` must be removed and the application must throw a startup error if `DB_PASSWORD` is unset, preventing silent deployment with known-default credentials.
- **\[batch\]** `FEED_STORAGE_CONNECTION` must be set in the Container App Job environment pointing at the Azure Blob Storage account. The 'feeds' container must exist and contain files matching the `YYYYMMDD_transactions.csv` pattern before the first run.
- **\[batch\]** `DB_HOST`, `DB_NAME`, `DB_USER`, and `DB_PASSWORD` must be populated with Azure PostgreSQL connection details in the Container App Job secret configuration.
- **\[reporting-db\]** The on-premises `batch_user` password (`C0nt0s0B@tch2021!`, known to ex-employees) must

---

## Raw Subagent Outputs

<details>
<summary>Click to expand raw subagent JSON (coordinator input)</summary>

```json
[
  {
    "workload": "webapp",
    "name": "Customer Portal (webapp)",
    "cloud_readiness_score": 7,
    "readiness_rationale": "The app is containerised with a secure Dockerfile and uses environment variables for most config, but a hardcoded on-premises auth service IP and legacy file-logging path must be resolved before Azure deployment.",
    "summary": "The Customer Portal is largely cloud-ready: it is fully containerised with a multi-stage Dockerfile, uses environment-variable-driven configuration, logs to stdout, handles SIGTERM gracefully, and exposes a health endpoint. Two hard blockers exist \u2014 the default auth service URL points to a non-routable on-prem IP (10.0.1.45) and optional file-based logging would fail in a stateless container environment. Once those are addressed, a lift-and-shift to Azure Container Apps is low-risk.",
    "migration_risk": "medium",
    "hard_dependencies": [
      {
        "type": "ip",
        "value": "http://10.0.1.45:8080/auth/validate",
        "file": "workloads/webapp/src/config.js",
        "breaks_in_azure": true,
        "description": "Default auth service URL points to a private on-premises IP that is not routable from Azure. If AUTH_SERVICE_URL is not explicitly set in the Azure Container Apps environment, every authentication call will fail, breaking the entire portal."
      },
      {
        "type": "credential",
        "value": "dev-only-not-for-prod",
        "file": "workloads/webapp/src/config.js",
        "breaks_in_azure": false,
        "description": "Hardcoded fallback database password in config. While overridden by environment variable in production, the default value is a security risk if DB_PASSWORD is accidentally omitted from the Azure secret store; it should be removed so the app fails fast rather than connecting with a known default."
      },
      {
        "type": "filesystem",
        "value": "process.env.LOG_FILE (file path written via fs.createWriteStream)",
        "file": "workloads/webapp/src/index.js",
        "breaks_in_azure": true,
        "description": "If LOG_FILE is set, the app writes logs to a local file path. Azure Container Apps containers are ephemeral and have no persistent local filesystem; log data would be lost on restart and the path may not be writable. Cloud deployments must use stdout-only logging."
      }
    ],
    "soft_dependencies": [
      {
        "assumption": "Redis is available at a known host/port with optional password",
        "description": "The redis client is initialised from REDIS_HOST/REDIS_PORT/REDIS_PASSWORD env vars. In Azure, Azure Cache for Redis requires TLS (port 6380) and a connection string/access key; REDIS_TLS must be set to 'true' and the correct host/port/password injected, otherwise session caching will fail silently or connection will be refused."
      },
      {
        "assumption": "PostgreSQL is accessible on the internal network without SSL by default",
        "description": "DB_SSL defaults to false. Azure Database for PostgreSQL Flexible Server enforces SSL/TLS connections by default; DB_SSL must be set to 'true' in Azure or connections will be rejected, potentially causing application startup failure."
      },
      {
        "assumption": "PII access control is handled by a caller-supplied HTTP header (x-pii-scope: internal)",
        "description": "The customers/:id route grants full unredacted PII to any request that includes the x-pii-scope: internal header. In Azure there is no gateway or network policy shown that prevents external callers from sending this header, meaning PII redaction can be trivially bypassed."
      },
      {
        "assumption": "Node.js native --test runner is used with a glob pattern (src/**/*.test.js)",
        "description": "The test script uses a shell glob that may not expand correctly in all CI environments (e.g. Azure DevOps hosted agents running on Windows). A test framework such as Jest or explicit file listing would be more portable."
      },
      {
        "assumption": "DB connection pool size of 10 is sufficient",
        "description": "Azure Database for PostgreSQL Flexible Server has per-SKU connection limits; with multiple container replicas each holding a pool of 10, total connections may exceed the server limit. PgBouncer or a lower pool ceiling per replica should be considered."
      }
    ],
    "pii_surface": [
      "customers.email (stored in DB, partially redacted in API responses, config.piiFields)",
      "customers.phone (stored in DB, partially redacted in API responses, config.piiFields)",
      "customers.account_number (listed in piiFields, present in accounts join)",
      "customers.sort_code (listed in piiFields, present in accounts join)",
      "customers.uk_postcode (returned in /api/customers/:id response, not redacted)",
      "accounts.balance (returned in /api/customers/:id response as financial data)",
      "transactions.amount (returned in /api/customers/:id/transactions)",
      "transactions.external_ref (returned in transaction listing, may contain payment reference data)",
      "x-pii-scope header bypass (internal scope returns fully unredacted customer PII)"
    ],
    "cross_workload_coupling": [
      {
        "coupled_to": "reporting-db",
        "coupling_type": "database",
        "description": "The webapp reads from the customers, accounts, and transactions tables. The reporting-db workload describes the PostgreSQL schema that defines these tables. Both workloads share the same database (named 'contoso' by default in config.js).",
        "migration_implication": "The reporting-db schema migration must be completed and validated before the webapp is cut over to Azure Database for PostgreSQL. Schema changes (column additions, type changes) in reporting-db will directly affect webapp query results. Both workloads must target the same Azure PostgreSQL Flexible Server instance or a replication strategy must be defined."
      },
      {
        "coupled_to": "batch",
        "coupling_type": "database",
        "description": "The batch Python reconciliation job almost certainly reads and writes the same transactions and accounts tables that the webapp queries. There is no API or queue coupling visible in the webapp code, indicating the coupling is purely at the database layer.",
        "migration_implication": "Migration timing must be coordinated so the batch job and webapp are not split across on-prem and Azure databases during cutover. Connection pool limits on Azure PostgreSQL must account for both workloads connecting simultaneously."
      }
    ],
    "phase1_blockers": [
      "AUTH_SERVICE_URL must be explicitly set in the Azure Container Apps environment to a reachable endpoint before deployment; the default on-prem IP 10.0.1.45 is not routable in Azure (config.js).",
      "DB_SSL must be set to 'true' in Azure environment variables to satisfy Azure Database for PostgreSQL Flexible Server TLS requirements (config.js).",
      "REDIS_TLS must be set to 'true' and REDIS_PORT set to 6380 for Azure Cache for Redis connectivity (config.js).",
      "The hardcoded default DB password fallback ('dev-only-not-for-prod') must be removed or the app must enforce a startup failure when DB_PASSWORD is not set, to prevent accidental use of the default credential (config.js).",
      "LOG_FILE must not be set in the Azure Container Apps environment; confirm no deployment pipeline injects this variable, and remove file-logging code path or gate it with an explicit guard (index.js).",
      "The reporting-db schema migration must be completed on Azure PostgreSQL before the webapp is pointed at the Azure database, as the webapp depends on the customers, accounts, and transactions tables."
    ],
    "phase2_optimisations": [
      "Replace the legacy on-prem auth service HTTP call with Azure AD B2C OIDC token validation (noted as Phase 2 in config.js comments), eliminating the external auth service dependency entirely.",
      "Implement Azure Key Vault references for all secrets (DB_PASSWORD, REDIS_PASSWORD) via Azure Container Apps managed identity, removing secrets from environment variable injection.",
      "Add PgBouncer or configure Azure Database for PostgreSQL connection pooling to manage the per-replica pool-of-10 at scale across multiple container replicas.",
      "Protect the x-pii-scope: internal header at the Azure API Management or Container Apps ingress layer so it cannot be spoofed by external callers (customers.js route).",
      "Integrate structured JSON logs (already emitted to stdout) with Azure Monitor / Log Analytics workspace using a Diagnostic Setting on the Container Apps environment, and add a PII scrubbing filter for the fields listed in config.piiFields.",
      "Add Redis health check to the /health endpoint (currently only database is checked) so Azure Container Apps liveness/readiness probes can detect Redis connectivity failures (health.js).",
      "Upgrade package.json description and engines field to reflect Node.js 20 (the Dockerfile uses node:20-alpine but package.json states 'Node.js 16 app' and engines requires >=18).",
      "Consider Azure Container Apps scale rules tied to HTTP request queue depth to replace manual scaling, leveraging the stateless, SIGTERM-aware design already in index.js."
    ],
    "recommendations": [
      "config.js line 18 \u2014 Remove the fallback value 'dev-only-not-for-prod' for DB_PASSWORD and throw an error at startup if the variable is unset: this prevents silent deployment with default credentials in Azure.",
      "config.js line 24 \u2014 Remove the default value 'http://10.0.1.45:8080/auth/validate' for authServiceUrl and throw at startup if AUTH_SERVICE_URL is not set, making the misconfiguration immediately visible rather than causing runtime 503s.",
      "config.js line 28 / index.js lines 16-22 \u2014 Remove the file-logging code path entirely (or add an explicit Azure-environment guard), as it cannot work safely in Azure Container Apps and risks hiding log output from Azure Monitor.",
      "config.js line 22 \u2014 Add DB_SSL=true and DB_PORT=5432 to the Azure Container Apps environment secrets/variables and document this as a required configuration item in the runbook.",
      "config.js line 26-27 \u2014 Set REDIS_TLS=true and REDIS_PORT=6379\u21926380 in the Azure deployment environment for Azure Cache for Redis; document the Azure Cache for Redis access key as the value for REDIS_PASSWORD.",
      "routes/customers.js line 44 \u2014 The x-pii-scope: internal header bypass for PII redaction must be protected at the ingress/APIM layer in Azure; add a comment and open a security work item to enforce this before go-live.",
      "routes/customers.js \u2014 customers.uk_postcode is returned unredacted in the /:id response but is a PII field for UK residents; add it to the redactPii function or explicitly document the intentional exposure.",
      "db.js \u2014 Parameterise DB pool max via DB_POOL_MAX and set it to a value that, multiplied by the maximum Container Apps replica count, stays below the Azure PostgreSQL SKU connection limit; document the calculation in the runbook.",
      "Dockerfile \u2014 The image is already production-ready (non-root user, multi-stage, HEALTHCHECK) but should pin the base image digest (e.g. node:20-alpine@sha256:...) to prevent supply-chain drift in the Azure Container Registry.",
      "package.json \u2014 Update the description field from 'on-prem Node.js 16 app' to reflect Node.js 20, and align the engines field to '>=20.0.0' to match the Dockerfile base image."
    ]
  },
  {
    "workload": "batch",
    "name": "Nightly Batch Reconciliation",
    "cloud_readiness_score": 8,
    "readiness_rationale": "The code has already removed the on-prem NFS dependency and added Azure Blob Storage support via environment variables, making it largely cloud-ready with only credential management and observability hardening remaining.",
    "summary": "The Nightly Batch Reconciliation job is well-prepared for Azure migration: the NFS feed source has been replaced with Azure Blob Storage, configuration is fully environment-variable driven, and the container is non-root. The main outstanding concerns are that database credentials are passed as plain environment variables rather than via Azure Key Vault or Managed Identity, and the DB_SSLMODE defaults to 'prefer' rather than 'require', which is insufficient for a production financial workload in Azure. Cross-workload database coupling with reporting-db and the transactions table must be coordinated during migration.",
    "migration_risk": "low",
    "hard_dependencies": [
      {
        "type": "credential",
        "value": "FEED_STORAGE_CONNECTION (connection string)",
        "file": "reconcile.py",
        "breaks_in_azure": false,
        "description": "Azure Blob Storage is accessed via a connection string environment variable. This works in Azure but should be replaced with Managed Identity to avoid storing a long-lived secret."
      },
      {
        "type": "credential",
        "value": "DB_PASSWORD (plain env var)",
        "file": "reconcile.py",
        "breaks_in_azure": false,
        "description": "Database password is injected as a plain environment variable. In Azure Container App Jobs this works but exposes the credential; it should be sourced from Azure Key Vault via a secret reference."
      },
      {
        "type": "filesystem",
        "value": "FEED_LOCAL_PATH (local directory path fallback)",
        "file": "reconcile.py",
        "breaks_in_azure": false,
        "description": "A local filesystem fallback path is supported for dev only; it must not be used in Azure production and no persistent local volume is available in Container App Jobs by default."
      },
      {
        "type": "filesystem",
        "value": "sample_feed.csv (COPY sample_feed.csv ./)",
        "file": "Dockerfile",
        "breaks_in_azure": false,
        "description": "A sample CSV is baked into the production image. This is a minor hygiene issue; it does not break functionality but should be excluded from the production image build."
      }
    ],
    "soft_dependencies": [
      {
        "assumption": "DB_SSLMODE defaults to 'prefer' if not set",
        "description": "reconcile.py line 36 defaults DB_SSLMODE to 'prefer', which may allow an unencrypted connection. Azure Database for PostgreSQL Flexible Server enforces SSL by default and this should be explicitly set to 'require' or 'verify-full' in the Container App Job environment configuration."
      },
      {
        "assumption": "Blob container named 'feeds' exists and contains files named YYYYMMDD_transactions.csv",
        "description": "_load_from_blob hardcodes the container name 'feeds' and a fixed filename pattern. If the storage account is shared or naming conventions differ in Azure, the job will fail silently with a blob-not-found error."
      },
      {
        "assumption": "The transactions and reconciliation_reports tables exist and are accessible at DB_HOST",
        "description": "The job assumes the PostgreSQL schema (reporting-db workload) has already been provisioned and migrated before this job runs. If the reporting-db migration lags, the job will fail at runtime."
      },
      {
        "assumption": "Cron schedule at 02:00 UTC is configured externally in the Container App Job",
        "description": "The Python code itself has no scheduling logic; the 02:00 UTC trigger must be configured as a cron expression on the Azure Container App Job resource. This must be explicitly set during infrastructure provisioning."
      },
      {
        "assumption": "sys.exit(2) on mismatch rate >0.1% is handled by the job orchestrator as a failure",
        "description": "Azure Container App Jobs treat any non-zero exit code as a job failure and can trigger alerts/retries. The retry policy must be set to 0 retries for this job to avoid re-running a reconciliation that has already written a report row."
      }
    ],
    "pii_surface": [
      "sort_code (sample_feed.csv \u2014 UK bank sort code)",
      "account_number (sample_feed.csv \u2014 UK bank account number)",
      "external_ref (transactions table \u2014 may link to individual customer payment records)",
      "unmatched_refs (written to reconciliation_reports.unmatched_refs \u2014 may contain customer-linked payment references)",
      "description field in CSV (e.g. 'BACS CREDIT - EMPLOYER PAYROLL' \u2014 may imply employment relationship)"
    ],
    "cross_workload_coupling": [
      {
        "coupled_to": "reporting-db",
        "coupling_type": "database",
        "description": "The batch job reads from the 'transactions' table and writes to the 'reconciliation_reports' table, both of which are owned by the reporting-db PostgreSQL schema workload.",
        "migration_implication": "reporting-db must be fully provisioned and schema-migrated in Azure before the batch job can run. DB_HOST, DB_NAME, DB_USER, and DB_PASSWORD must be coordinated between the two workloads at deployment time."
      },
      {
        "coupled_to": "reporting-db",
        "coupling_type": "database",
        "description": "The batch job issues UPDATE statements on transactions.status = 'reconciled', meaning it has write access to the core transactions table, not just read access.",
        "migration_implication": "Database user permissions must be carefully scoped in Azure: the batch job's DB_USER must have UPDATE on transactions and INSERT on reconciliation_reports. Any row-level security or schema changes in reporting-db directly affect batch job correctness."
      },
      {
        "coupled_to": "webapp",
        "coupling_type": "database",
        "description": "The webapp (Node.js customer portal) likely reads transaction status from the same transactions table that the batch job updates. A reconciliation run changes status to 'reconciled', which the portal may surface to customers.",
        "migration_implication": "The migration cutover timing of batch and webapp must be coordinated so that both workloads are pointing to the same Azure PostgreSQL instance simultaneously, avoiding split-brain where one workload still targets on-prem."
      }
    ],
    "phase1_blockers": [
      "Azure Blob Storage account must be provisioned with a 'feeds' container and FEED_STORAGE_CONNECTION must be set in the Container App Job environment before first run.",
      "reporting-db (PostgreSQL) must be migrated to Azure Database for PostgreSQL Flexible Server and the transactions and reconciliation_reports tables must exist before the batch job can execute.",
      "DB_HOST, DB_NAME, DB_USER, DB_PASSWORD must be populated with Azure PostgreSQL connection details in the Container App Job secrets/environment configuration.",
      "Azure Container App Job must be created with cron schedule '0 2 * * *' (UTC) and max retries set to 0 to prevent duplicate reconciliation report rows.",
      "DB_SSLMODE must be explicitly set to 'require' in the Container App Job environment to meet Azure PostgreSQL SSL enforcement requirements."
    ],
    "phase2_optimisations": [
      "Replace FEED_STORAGE_CONNECTION string with Managed Identity authentication to Azure Blob Storage using DefaultAzureCredential, eliminating the long-lived connection string secret (reconcile.py _load_from_blob).",
      "Replace DB_PASSWORD plain environment variable with Azure Key Vault secret reference in the Container App Job configuration, and consider passwordless authentication via Managed Identity to Azure Database for PostgreSQL.",
      "Add Azure Application Insights structured logging/tracing by integrating opencensus-ext-azure or azure-monitor-opentelemetry-exporter so reconciliation metrics (matched, unmatched, mismatch rate) are surfaced as custom metrics and alertable in Azure Monitor.",
      "Parameterise the Blob container name 'feeds' as an environment variable (FEED_CONTAINER_NAME) rather than hardcoding it in _load_from_blob, to support environment separation (dev/staging/prod) without code changes.",
      "Remove sample_feed.csv from the production Docker image by using a multi-stage build or a .dockerignore entry, reducing image surface area and avoiding accidental use of test data in production.",
      "Implement idempotency in write_report by adding a UNIQUE constraint on reconciliation_reports(report_date) and using INSERT ... ON CONFLICT DO NOTHING, protecting against duplicate runs caused by manual re-triggers."
    ],
    "recommendations": [
      "reconcile.py line 36: Change DB_SSLMODE default from 'prefer' to 'require' \u2014 os.environ.get('DB_SSLMODE', 'require') \u2014 to enforce encrypted connections to Azure Database for PostgreSQL.",
      "reconcile.py _load_from_blob: Extract hardcoded container name 'feeds' to an environment variable FEED_CONTAINER_NAME to allow environment-specific overrides without rebuilding the image.",
      "reconcile.py main(): Add explicit logging of the Container App Job execution ID (available via CONTAINER_APP_JOB_EXECUTION_NAME env var in Azure) to correlate log entries across runs in Log Analytics.",
      "Dockerfile: Add a .dockerignore or multi-stage build step to exclude sample_feed.csv from the production image to avoid test data shipping to production.",
      "requirements.txt: Pin azure-storage-blob to 12.19.0 (already done) but also consider adding azure-identity to support Managed Identity authentication as a phase 2 improvement without a code-freeze.",
      "Container App Job infrastructure: Set max_execution_count / replica_completion_count to 1 and retryLimit to 0 to prevent the job from re-running after a sys.exit(2) mismatch alert, which would write a second reconciliation_reports row for the same date."
    ]
  },
  {
    "workload": "reporting-db",
    "name": "Reporting Database",
    "cloud_readiness_score": 7,
    "readiness_rationale": "The schema is clean, standards-compliant PostgreSQL 16 with no proprietary extensions beyond pgcrypto and pgaudit (both supported on Azure Database for PostgreSQL Flexible Server), but PII/PCI data is stored in plaintext and audit configuration, network access controls, and row-level security are absent from the provided files.",
    "summary": "The reporting database is structurally well-suited for migration to Azure Database for PostgreSQL Flexible Server UK South: it uses only supported extensions (pgcrypto, pgaudit), standard SQL types, and has no hardcoded connection strings or filesystem paths. The primary migration risks are compliance-related \u2014 PII fields (email, phone, account_number, sort_code) and PCI-scoped account data are stored unencrypted at the column level, and there is no evidence of row-level security, column masking, or role-based access separation for the five consumer teams. Coordination with the webapp and batch workloads is required to sequence the migration without breaking live reads and reconciliation writes.",
    "migration_risk": "medium",
    "hard_dependencies": [
      {
        "type": "service",
        "value": "pgaudit",
        "file": "workloads/reporting-db/schema.sql",
        "breaks_in_azure": false,
        "description": "pgaudit extension is used for audit logging. Azure Database for PostgreSQL Flexible Server supports pgaudit natively but it must be explicitly enabled via the server parameter 'pgaudit.log' in the Azure portal or Bicep/Terraform; it is not on by default and the extension must be allowlisted before CREATE EXTENSION succeeds."
      },
      {
        "type": "service",
        "value": "pgcrypto",
        "file": "workloads/reporting-db/schema.sql",
        "breaks_in_azure": false,
        "description": "pgcrypto is used for gen_random_uuid(). Azure Database for PostgreSQL Flexible Server supports pgcrypto and it must be added to the allowed_extensions server parameter before the schema can be applied."
      }
    ],
    "soft_dependencies": [
      {
        "assumption": "Five internal teams (BI, Risk, Finance, Compliance, Ops) connect directly to the database, implying the database is reachable over a corporate network without additional authentication layers.",
        "description": "In Azure, the Flexible Server should be deployed inside a VNet with private endpoint or VNet integration. Direct team access will require either VPN/ExpressRoute connectivity to UK South or Azure Bastion/jump host provisioning; existing connection strings and firewall rules will not carry over."
      },
      {
        "assumption": "The schema assumes default PostgreSQL superuser or owner privileges for DDL execution (CREATE EXTENSION, CREATE TABLE, CREATE TRIGGER).",
        "description": "Azure Database for PostgreSQL Flexible Server does not grant superuser; the azure_pg_admin role is used instead. Extension creation requires the server parameter 'azure.extensions' to be pre-configured. Scripts assuming unrestricted superuser may fail without adjustment."
      },
      {
        "assumption": "Seed data uses fixed UUIDs and ON CONFLICT DO NOTHING, implying a shared mutable dev/test database rather than ephemeral environments.",
        "description": "In Azure, dev/test environments should use separate Flexible Server instances or point-in-time restore clones; shared seed state assumptions may cause test data pollution if the same instance is reused across environments."
      },
      {
        "assumption": "The reconciliation_reports table uses a SERIAL (integer sequence) primary key rather than UUID, implying sequential insert ordering is meaningful.",
        "description": "Under Azure high-availability failover (synchronous standby promotion), sequence gaps may occur. If the batch workload or any consumer depends on gapless sequential IDs, this needs to be documented and accepted."
      },
      {
        "assumption": "No connection pooling configuration is present in the schema files, implying each team connects directly with potentially long-lived sessions.",
        "description": "Azure Database for PostgreSQL Flexible Server has a maximum connection limit tied to the SKU. With five teams querying concurrently plus webapp and batch connections, PgBouncer (built into Flexible Server) should be explicitly configured to avoid connection exhaustion."
      }
    ],
    "pii_surface": [
      "customers.email (VARCHAR 255, tagged PII, stored plaintext)",
      "customers.phone (VARCHAR 20, tagged PII, stored plaintext)",
      "customers.first_name (VARCHAR 100, personal data, untagged but identifiable)",
      "customers.last_name (VARCHAR 100, personal data, untagged but identifiable)",
      "customers.uk_postcode (VARCHAR 10, partial address, linkable to individual)",
      "accounts.account_number (VARCHAR 20, tagged PII, PCI-scoped, stored plaintext)",
      "accounts.sort_code (VARCHAR 10, tagged PII, PCI-scoped, stored plaintext)",
      "accounts.balance (NUMERIC 15,2, financial data, PCI-scoped)",
      "seed.sql: real-format UK phone numbers (+447700900001\u20135), realistic sort codes and account numbers present in plaintext in seed file"
    ],
    "cross_workload_coupling": [
      {
        "coupled_to": "webapp",
        "coupling_type": "database",
        "description": "The webapp workload reads from the customers, accounts, and transactions tables in this database. The schema defines these tables as the authoritative source; any schema change (column rename, type change, index drop) directly impacts webapp query compatibility.",
        "migration_implication": "The webapp and reporting-db must be migrated in a coordinated cutover window, or a read replica must be maintained during transition. Schema changes must be backward-compatible until both workloads are live on Azure."
      },
      {
        "coupled_to": "batch",
        "coupling_type": "database",
        "description": "The batch workload writes to the reconciliation_reports table (INSERT with report_date, status, totals, unmatched_refs). The table definition including the SERIAL primary key, UNIQUE constraint on report_date, and the TEXT[] unmatched_refs column must remain stable for batch writes to succeed.",
        "migration_implication": "Batch must be migrated concurrently with or immediately after reporting-db. During any migration window where reporting-db is in read-only or restricted mode, batch reconciliation jobs must be paused or queued to avoid failed inserts and partial report states."
      }
    ],
    "phase1_blockers": [
      "Azure Database for PostgreSQL Flexible Server requires pgaudit and pgcrypto to be listed in the 'azure.extensions' server parameter before CREATE EXTENSION commands in schema.sql will succeed \u2014 this parameter must be set at provisioning time via IaC.",
      "No network access control or private endpoint configuration is defined: the Flexible Server must be deployed into a VNet with private DNS zone and either VPN/ExpressRoute or private endpoint must be confirmed reachable from all five internal team client networks and from the webapp and batch workloads before cutover.",
      "PCI DSS and UK GDPR compliance review must confirm that plaintext storage of account_number, sort_code, email, and phone in Azure UK South is acceptable under the organisation's data classification policy, or column-level encryption must be implemented before migration.",
      "Migration sequencing with webapp (reads) and batch (writes to reconciliation_reports) must be formally agreed: a cutover plan must specify the exact window during which all three workloads are simultaneously cut over to prevent split-brain data inconsistency.",
      "The existing on-premises PostgreSQL version must be confirmed as 16.x; if it is an earlier version a pg_upgrade path must be validated before Azure Flexible Server (PostgreSQL 16) is targeted."
    ],
    "phase2_optimisations": [
      "Enable Azure Database for PostgreSQL Flexible Server built-in PgBouncer connection pooler and configure pool_mode=transaction for the high-concurrency read workload from five internal teams plus webapp.",
      "Implement PostgreSQL Row-Level Security (RLS) policies on customers, accounts, and transactions tables to enforce least-privilege access per consumer team role, replacing any assumed application-layer filtering.",
      "Use Azure Key Vault-backed column encryption (pgcrypto encrypt/decrypt with keys stored in Key Vault) for account_number, sort_code, email, and phone fields to satisfy PCI DSS column-level encryption requirements.",
      "Configure pgaudit.log = 'read,write,ddl' and route audit logs to Azure Monitor Log Analytics workspace with a UK South Log Analytics workspace to satisfy compliance team audit trail requirements.",
      "Add a read replica (Azure Flexible Server read replica) in UK South to offload BI and Compliance team reporting queries from the primary instance, reducing contention during reconciliation batch write windows.",
      "Replace SERIAL primary key on reconciliation_reports with UUID (gen_random_uuid()) for consistency with other tables and to avoid sequence-gap concerns under HA failover.",
      "Implement Azure Defender for PostgreSQL (Microsoft Defender for Cloud) to detect anomalous query patterns against PII/PCI tables.",
      "Add created_at/updated_at or partition pruning to the transactions table using declarative range partitioning on transaction_date to support efficient archival and improve BI query performance at scale.",
      "Store seed.sql with anonymised/synthetic data only in source control; rotate any seed values that resemble real sort codes or phone number formats used in production."
    ],
    "recommendations": [
      "schema.sql: Add 'azure.extensions' parameter configuration to the IaC provisioning template listing 'pgcrypto,pgaudit' before applying schema.sql, otherwise CREATE EXTENSION commands on lines 4-5 will fail with permission denied.",
      "schema.sql line 4-5: Validate pgaudit version compatibility between on-premises PostgreSQL 16 and the specific minor version available on Azure Flexible Server UK South to avoid extension version mismatch during restore.",
      "schema.sql: Define explicit database roles (e.g., role_bi_readonly, role_finance_readonly, role_batch_writer) with GRANT statements scoped per table before migration, replacing assumed superuser connections from all five teams.",
      "schema.sql: Add CHECK constraint or domain type validation on sort_code and account_number columns if format validation is not enforced at the application layer, to prevent dirty data entry from multiple consumer teams.",
      "seed.sql: Replace all realistic-format UK phone numbers, sort codes, and account numbers with clearly synthetic values (e.g., sort code '00-00-00', phone '07700 000000') to ensure the seed file is safe to commit to shared repositories and deploy to non-production Azure environments.",
      "schema.sql: Consider adding a partial index on transactions(status) WHERE status IN ('pending', 'disputed') to optimise the high-frequency status-based queries expected from Risk and Compliance teams, which was not present in the original index set.",
      "schema.sql: The customers table has no soft-delete or GDPR right-to-erasure mechanism; add a deleted_at TIMESTAMPTZ column or a separate erasure_log table before migration to support UK GDPR Article 17 compliance on Azure.",
      "schema.sql: The ON DELETE RESTRICT on accounts.customer_id and transactions.account_id is correct for data integrity but will block GDPR erasure requests; document a compensating erasure procedure (e.g., pseudonymisation via pgcrypto) as part of the migration runbook.",
      "General: Produce a formal data migration runbook that includes: (1) dump with pg_dump --no-owner --no-acl from on-premises, (2) pre-flight extension allowlist on Flexible Server, (3) restore, (4) role and RLS creation, (5) connectivity validation from all five teams, (6) coordinated webapp and batch cutover, (7) pgaudit log verification."
    ]
  }
]
```

</details>
