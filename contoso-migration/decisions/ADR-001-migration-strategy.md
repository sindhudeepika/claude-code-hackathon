# ADR-001: Migration Strategy — Lift-and-Shift First, Optimise Second

**Status:** Accepted  
**Date:** 2026-04-28  
**Deciders:** Architecture Lead, CFO Office, CTO, Head of Compliance, SRE Lead

---

## The Decision Memo

**To:** CFO, CTO, Head of Compliance, SRE Lead  
**From:** Architecture  
**Subject:** How we move Contoso Financial to Azure — and why we're doing it in two phases

---

### The Problem

We have three workloads to migrate: a customer portal (web app), a nightly batch reconciliation
job, and a shared reporting database. The CFO signed the Azure contract and needs on-prem data
centre costs eliminated by Q3 2026. The CTO has approved the migration on the condition that we
arrive at a cloud-native architecture, not a "lift-and-shift forever" outcome.

We cannot satisfy both stakeholders in one phase. Attempting to do so risks missing the Q3 cost
deadline (re-architecture takes longer than containerisation) and producing a half-finished
cloud-native design that nobody is confident in.

---

### The Recommendation

**Phase 1 (this document):** Lift-and-shift. Containerise the three workloads as they stand,
deploy to Azure UK South equivalents (Container Apps, PostgreSQL Flexible Server, Azure Batch),
and shut down the on-prem environment by Q3 2026.

**Phase 2 (H2 2026 roadmap):** Cloud-native optimisation. Event-driven batch triggers, connection
pooling, read replicas for the reporting database, Application Insights instrumentation.

Phase 1 gives the CFO the cost win. Phase 2 gives the CTO the cloud-native architecture. Neither
phase compromises the other.

---

### Why Not Refactor on the Way In?

Three reasons:

1. **Timeline risk is asymmetric.** A containerise-and-deploy takes 6–8 weeks with confidence.
   A refactor-on-the-way-in takes 16–24 weeks with high uncertainty. Missing Q3 means two more
   quarters of data centre costs plus a CFO conversation nobody wants.

2. **Unknown unknowns.** Discovery surfaced five undocumented dependencies (see
   [discovery/current-state.md](../discovery/current-state.md)). We do not yet know what we do
   not know. Lift-and-shift lets us run the workloads in Azure and observe their actual behaviour
   before redesigning them.

3. **Risk concentration.** Combining migration risk with re-architecture risk in a single
   programme creates compounding failure modes. Separating them means Phase 1 failures are
   containable.

---

### Risks We Are Accepting

| Risk | Owner | Mitigation |
|---|---|---|
| Lifted workloads are not cost-optimal in cloud | CTO Office | Accepted for Phase 1; Phase 2 roadmap addresses |
| Container Apps scaling behaviour differs from on-prem | SRE | Load test before cutover; documented in cutover runbook |
| On-prem auth service IP hardcoded in webapp | Dev | Discovery finding #1; must be resolved before Phase 1 cutover |
| NFS mount path hardcoded in batch job | Dev | Discovery finding #3; Azure File Share or Blob Storage substitution required |
| Plaintext DB password in batch config file | Security | Discovery finding #4; replaced with Managed Identity in Phase 1 |
| PostgreSQL connection pool not configured | Platform | Known sub-optimal; acceptable in Phase 1 with current transaction volumes |
| Reporting DB has direct external queries from five teams | Architecture | Private endpoint enforces UK South residency; query routing unchanged in Phase 1 |

Risks not listed here are out of scope for this ADR.

---

### What We Are Deliberately Not Doing in Phase 1

- **Not decomposing the web app into microservices.** The monolith moves as a monolith.
- **Not replacing the nightly batch trigger with event-driven processing.** Cron stays.
- **Not implementing connection pooling (PgBouncer/Pgpool).** On-prem load levels are within
  managed service capacity.
- **Not migrating the on-prem auth service.** The webapp will use a stub during Phase 1 and the
  auth service will be decommissioned in Phase 2 when Azure AD B2C replaces it.
- **Not deploying multi-region.** UK South is the single region for both Phase 1 and Phase 2.
  Active-active multi-region is a Phase 3 discussion.

---

### Rollback Plan (Outline)

Full rehearsed runbook is a Phase 1 deliverable (Challenge 8, currently partial).

At a high level:
1. On-prem environment remains live until 30 days post-cutover.
2. DNS cutover is the activation gate — revert DNS to roll back instantly.
3. PostgreSQL Flexible Server has point-in-time restore enabled; restore target is the
   pre-migration snapshot.
4. Batch job has a manual trigger; if the Azure Batch job fails silently, the on-prem cron can
   be re-enabled within 15 minutes.

Rollback trigger criteria:
- Any validation suite test failing in production for >30 minutes
- Batch reconciliation mismatch rate >0.1% (vs. historical baseline of 0.003%)
- Web app p99 latency >3x on-prem baseline for >10 minutes

---

## Context

### Current State

The three workloads run on a co-located data centre in Slough. The infrastructure lease expires
Q4 2026; Azure is the contracted replacement. Compliance has confirmed UK South satisfies
UK GDPR data residency requirements. PCI-DSS scope applies to the reporting database (accounts
and transaction data).

### Constraints

- Data must remain in Azure UK South at all times (UK GDPR + Contoso Financial data policy).
- PII (customer name, email, phone, account number, sort code) must not be accessible outside
  the VNet private endpoint boundary.
- Phase 1 cutover must complete before Q3 2026 to avoid data centre lease renewal.

---

## Consequences

**Positive:**
- Q3 cost deadline is achievable with high confidence.
- Phase 1 produces a fully observable Azure baseline for Phase 2 redesign.
- Validation suite (The Proof) runs against local Docker Compose stack today and against Azure
  post-cutover — same tests, different environment.

**Negative:**
- Phase 1 Azure bill will be higher than a cloud-native equivalent (no scale-to-zero on the DB,
  no serverless batch trigger). This is accepted and budgeted.
- Two migration phases means two sets of cutover communications to the business.
