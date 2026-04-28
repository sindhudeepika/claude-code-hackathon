# Team SonnetSlayers — Solo

## Participants
- s.d.subramanian (PM, Architect, Developer, Tester, Platform Engineer)

## Scenario
Scenario 2: Cloud Migration — *"The Lift, the Shift, and the 4am Call"*

---

## What We Built

Contoso Financial runs three on-prem workloads that need to move to Azure UK South: a customer-facing web portal (Node.js/Express), a nightly batch reconciliation job (Python), and a shared reporting database (PostgreSQL). This repo contains everything needed to prove the migration works before anyone touches production.

The migration strategy is **lift-and-shift first, optimise second**: containerise the workloads as-is, deploy to Azure equivalents (Container Apps, PostgreSQL Flexible Server, Azure Batch), and defer cloud-native re-architecture to Phase 2. This resolves the CFO/CTO deadlock — the CFO gets the data-centre cost off the books by Q3, and cloud-native optimisation goes on the H2 roadmap. The decision is fully argued in [ADR-001](contoso-migration/decisions/ADR-001-migration-strategy.md).

The repo includes:
- **The Memo** — a one-page migration decision document with explicit risk ownership
- **The Container** — a fully containerised web app with multi-stage Dockerfile, non-root user, health check, and a `docker compose` stack where every service is named for its Azure equivalent
- **The Proof** — a pytest validation suite (smoke, contract, data-integrity, and discovery-finding tests) that defines "migration succeeded" and specifically catches the four on-prem dependencies that would cause silent failures in Azure
- **Terraform IaC** — the full target architecture in Azure UK South (Container Apps, PostgreSQL Flexible Server, Redis, Blob Storage, Key Vault, private endpoints for PII residency)
- **Discovery** — documented on-prem surprises: a hardcoded auth-service IP, a local log file, an NFS-mounted feed directory, a keepalive cron hitting a hardcoded Redis IP, and a plaintext DB password in a config file

---

## Challenges Attempted

| # | Challenge | Status | Notes |
|---|---|---|---|
| 1 | The Memo | done | [ADR-001](contoso-migration/decisions/ADR-001-migration-strategy.md) — lift-and-shift decision with risk register |
| 2 | The Discovery | done | [current-state.md](contoso-migration/discovery/current-state.md) — five on-prem dependencies surfaced |
| 3 | The Options | done | [ADR-002](contoso-migration/decisions/ADR-002-target-architecture.md) — Azure service selection with scored alternatives |
| 4 | The Container | done | Multi-stage Dockerfile, non-root user, `/health` endpoint, full `docker compose` stack |
| 5 | The Foundation | partial | Terraform modules for all four workload areas; not deployed to live cloud |
| 6 | The Proof | done | 5 test modules, including one module per discovery finding |
| 7 | The Scorecard | skipped | Would add IaC golden-set eval in Phase 2 |
| 8 | The Undo | skipped | Rollback runbook is outlined in ADR-001 but not fully rehearsed |
| 9 | The Survey | done | Coordinator + 3 parallel Bedrock subagents; see [survey-report.md](contoso-migration/agents/survey-report.md) |

---

## Key Decisions

**1. Lift-and-shift first** — The CTO wants cloud-native; the CFO wants the bill gone. Both are right but on different timescales. Lift-and-shift ships by Q3 at lower risk; cloud-native optimisation (event-driven batch, read replicas, connection pooling) is Phase 2. Full argument in [ADR-001](contoso-migration/decisions/ADR-001-migration-strategy.md).

**2. Azure Container Apps over AKS** — AKS is the right answer if we're running 30 microservices. We have one monolith and two simple jobs. Container Apps gives us scale-to-zero, managed ingress, and no Kubernetes control-plane tax. See [ADR-002](contoso-migration/decisions/ADR-002-target-architecture.md).

**3. Private endpoints everywhere** — PII (customer names, account numbers, sort codes) must stay in UK South. Private endpoints on PostgreSQL, Redis, and Blob Storage ensure traffic never transits the public internet. This is enforced in Terraform, not just in policy — so it can't be accidentally disabled by a config change.

**4. PreToolUse hook for secret detection** — A deterministic hook blocks any Claude-generated edit that writes a plaintext secret into a `.tf` file. This is a hard stop, not a prompt preference, because "prefer Key Vault" is not strong enough for PCI-scoped infrastructure. The reasoning is in [CLAUDE.md](CLAUDE.md).

**5. Managed Identity for all app-to-service auth** — No passwords in environment variables or Key Vault secrets for app-to-DB or app-to-Redis auth in the Azure target. On-prem used a plaintext password in `config.ini`; that pattern stops here.

---

## How to Run It

**Prerequisites:** Docker Desktop with Docker Compose v2, Python 3.11+, Node.js 20+

```powershell
# Clone the repo
git clone <repo-url>
cd claude-code-hackathon\contoso-migration

# Start all services (postgres=Azure PostgreSQL, redis=Azure Redis, azurite=Azure Blob)
docker compose up -d

# Verify the web app is healthy (seed data loads automatically on first start)
curl http://localhost:3000/health

# Run the full validation suite (The Proof)
cd validation
pip install -r requirements.txt
pytest -v --tb=short

# Run only smoke tests
pytest -v -m smoke

# Run only discovery-finding tests (the "did we fix the migration blockers?" tests)
pytest -v -m discovery

# Run the batch reconciliation job manually (from contoso-migration/)
cd ..
docker compose run --rm --profile batch batch python reconcile.py
```

---

## If We Had More Time

1. **The Undo (Challenge 8)** — A proper rehearsed rollback runbook, not just the outline in ADR-001. Needs at least one dry-run against the Docker Compose stack with a simulated cutover failure.
3. **The Scorecard (Challenge 7)** — An eval harness for Claude's IaC output: golden IaC snippets, known-bad patterns (open security groups, over-permissive IAM, missing tags), CI integration.
4. **Azure AD B2C integration** — Replace the hardcoded on-prem auth service (discovery finding #1) with a proper OIDC flow. Currently the webapp falls back to a passthrough stub in the Docker Compose stack.
5. **Phase 2 cloud-native optimisation** — PgBouncer for connection pooling, Azure Service Bus replacing the cron trigger for batch, Application Insights instrumentation.

---

## How We Used Claude Code

**What worked best:**
- Generated the entire legacy codebase (with intentional on-prem flaws) in one pass, then used Claude to document the flaws in `discovery/current-state.md` — the discovery doc wrote itself because the code contained the evidence.
- Three-level `CLAUDE.md` kept per-workload conventions consistent: the webapp, batch, and infrastructure directories each have their own `CLAUDE.md` with the context that matters for that module. Claude never suggested a Terraform pattern inside a Node.js file.
- The `PreToolUse` hook caught a plaintext password being written to a Terraform variable during initial IaC generation. Exactly the scenario it was designed for.
- Plan Mode for the Terraform module structure — writing the module hierarchy in Plan Mode before executing prevented a half-finished `azurerm_container_app_environment` refactor from being committed.

**Where it saved the most time:**
- The validation suite. Writing `test_discovery_findings.py` — tests that specifically catch the five on-prem dependencies — would have taken half a day manually. Claude wrote the full test file in one shot once the discovery document existed.
- The presentation. The HTML deck was generated from the ADRs and discovery doc in a single prompt.

**What surprised us:**
- The hook feedback loop. When the `PreToolUse` hook blocked a secret, Claude didn't just retry the same thing — it immediately switched to `azurerm_key_vault_secret` references and asked whether the Key Vault module should be created first. That's the behaviour you want from a guardrail.
