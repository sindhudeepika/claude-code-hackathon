# ADR-002: Target Architecture — Azure UK South

**Status:** Accepted  
**Date:** 2026-04-28  
**Deciders:** Architecture Lead, SRE Lead, Head of Security

---

## Context

Three workloads to migrate to Azure. Constraints: UK South region only, PII residency enforced,
lift-and-shift Phase 1 (containerise-as-is). This ADR records the Azure service selections and
the alternatives we scored and rejected.

---

## Architecture Overview

```
┌─────────────────────────────────────── Azure UK South ──────────────────────────────────────────┐
│                                                                                                   │
│   ┌─────────────────────────────── VNet: vnet-contoso-prod ──────────────────────────────────┐   │
│   │                                                                                            │   │
│   │  ┌──────────────────────┐         ┌──────────────────────────────────────────────────┐   │   │
│   │  │   Subnet: app-tier   │         │            Subnet: data-tier                      │   │   │
│   │  │                      │         │                                                    │   │   │
│   │  │  ┌────────────────┐  │         │  ┌─────────────────────┐  ┌──────────────────┐  │   │   │
│   │  │  │ Container App  │──┼────────▶│  │ PostgreSQL Flexible  │  │ Azure Cache for  │  │   │   │
│   │  │  │   (webapp)     │  │         │  │ Server (reporting-db)│  │ Redis            │  │   │   │
│   │  │  └────────────────┘  │         │  │ Private endpoint     │  │ Private endpoint │  │   │   │
│   │  │                      │         │  └─────────────────────┘  └──────────────────┘  │   │   │
│   │  │  ┌────────────────┐  │         │                                                    │   │   │
│   │  │  │ Container App  │──┼────────▶│  ┌─────────────────────┐  ┌──────────────────┐  │   │   │
│   │  │  │ Job (batch)    │  │         │  │ Azure Blob Storage   │  │ Azure Key Vault  │  │   │   │
│   │  │  └────────────────┘  │         │  │ (feed files + reports│  │ (all secrets)    │  │   │   │
│   │  │                      │         │  │ Private endpoint     │  │ Private endpoint │  │   │   │
│   │  └──────────────────────┘         │  └─────────────────────┘  └──────────────────┘  │   │   │
│   │                                    └──────────────────────────────────────────────────┘   │   │
│   └────────────────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                                   │
│   ┌────────────────────────────────────────────────────────────────────────────────────────────┐  │
│   │  Azure Container Registry (Premium)  │  Azure Monitor + Log Analytics  │  Managed Identity │  │
│   └────────────────────────────────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────────────────────────────────┘

Internet ──▶ Azure Front Door (WAF) ──▶ Container Apps Environment (with managed ingress)
```

---

## Service Selections

### Web Application

**Decision:** Azure Container Apps

**Alternatives scored:**

| Option | Cost | Complexity | Fit for workload | Score |
|---|---|---|---|---|
| Azure Container Apps | Low | Low | High — managed ingress, scale-to-zero, no K8s ops | **Recommended** |
| Azure Kubernetes Service (AKS) | Medium | High | Over-engineered for one monolith | Rejected |
| Azure App Service (Container) | Low | Low | No sidecar support, limited networking options | Rejected |
| Azure Container Instances | Low | Low | No autoscaling, no ingress management | Rejected |

AKS is the right answer when running a microservices estate. We have one containerised monolith
moving to Container Apps, which provides autoscaling, managed TLS, revision-based deployments,
and VNet integration with no Kubernetes control-plane overhead.

### Batch Reconciliation Job

**Decision:** Azure Container App Jobs (scheduled, cron trigger)

Rationale: The batch job is already containerised. Container App Jobs provides cron scheduling,
structured logging, and retry semantics with no additional infrastructure. Azure Batch (the
PaaS compute service) would be appropriate for HPC or parallel workloads; our job is sequential
and runs in under 10 minutes.

**Alternative rejected:** Azure Batch — appropriate for parallel compute farms, not for a single
sequential reconciliation script.

### Reporting Database

**Decision:** Azure Database for PostgreSQL Flexible Server, Zone-redundant HA, UK South

Rationale: Direct functional equivalent to the on-prem PostgreSQL instance. Zone-redundant HA
provides <120s automatic failover. PCI-DSS scope requires encryption at rest (enabled by
default) and in transit (TLS 1.2 minimum, enforced). Private endpoint ensures data never
transits public internet.

**Tier:** General Purpose, 4 vCores, 16 GB RAM — matches on-prem VM sizing. Phase 2 will
right-size based on observed Azure metrics.

**Alternative rejected:** Azure SQL Database — would require schema and query migration; no
benefit in Phase 1 and adds re-architecture risk.

### Cache

**Decision:** Azure Cache for Redis, Standard C1, UK South, with private endpoint

Direct equivalent to the on-prem Redis instance. The keepalive cron (discovery finding #4) is
eliminated — Azure Cache for Redis does not require external keepalive pings to maintain
connection state.

### Secrets

**Decision:** Azure Key Vault, with Managed Identity access for all workloads

All secrets (DB passwords, storage keys, external service credentials) are stored in Key Vault.
Workloads authenticate via Managed Identity — no secrets in environment variables, no secrets
in IaC. On-prem used a plaintext `config.ini` (discovery finding #4); that pattern is
eliminated entirely.

### Container Registry

**Decision:** Azure Container Registry (Premium SKU)

Premium required for: private endpoint support, geo-replication readiness for Phase 3, content
trust. All workload images are built and stored here; the Dockerfiles use a non-root user and
multi-stage builds.

---

## Compliance and Residency

### UK South Data Residency

All `azurerm_*` resources are deployed to `uksouth`. Private endpoints on PostgreSQL, Redis,
Blob Storage, and Key Vault ensure that data-plane traffic is confined to the VNet and never
transits Azure's public backbone.

The Terraform locals enforce this:
```hcl
locals {
  location = "uksouth"
}
```

No resource accepts a `location` override that would route data out of UK South.

### PII Handling

PII fields (defined in `workloads/reporting-db/schema.sql` column comments):
- `customers.email`
- `customers.phone`
- `accounts.account_number`
- `accounts.sort_code`

Rules enforced in code:
- Web app logs redact PII fields before writing to stdout.
- Batch job does not log PII fields.
- No PII field is included in API responses without the `X-PII-Scope: internal` request header
  (used by internal tooling only, blocked at the Container Apps ingress for external traffic).

### PCI-DSS (Reporting Database)

- Encryption at rest: enabled by default on PostgreSQL Flexible Server.
- Encryption in transit: TLS 1.2 minimum enforced via `ssl_enforcement_enabled = true`.
- Network isolation: private endpoint; `public_network_access_enabled = false`.
- Audit logging: PostgreSQL audit extension (`pgaudit`) enabled via server parameter.
- Backup retention: 7 days point-in-time restore.

---

## What We Deliberately Did Not Do

- **Multi-region active-active.** UK South is the single region. DR is handled by
  zone-redundant HA within UK South. Active-active is a Phase 3 decision.
- **Microservices decomposition.** The web app monolith moves as-is. Phase 2 may extract the
  auth integration and reporting query layer as separate services.
- **Azure Front Door WAF (Phase 1).** The ingress path goes directly to Container Apps managed
  ingress in Phase 1. Front Door is on the Phase 2 roadmap for WAF, rate limiting, and CDN.
- **Connection pooling.** PgBouncer is not deployed in Phase 1. Current query volume is within
  Flexible Server connection limits; this will be revisited when Phase 2 metrics are available.
- **Azure Service Bus for batch triggers.** The batch job retains its cron trigger in Phase 1.
  Event-driven triggering (e.g., trigger on feed file arrival in Blob Storage) is Phase 2.
