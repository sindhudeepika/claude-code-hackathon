# CLAUDE.md — Contoso Financial Cloud Migration

## Project
Migrating three Contoso Financial workloads (customer portal, nightly batch, reporting DB) from
on-prem to Azure UK South. Strategy: lift-and-shift first (Phase 1), cloud-native optimise second
(Phase 2). See [ADR-001](contoso-migration/decisions/ADR-001-migration-strategy.md).

All solution code lives in `contoso-migration/`. The three submission files (this file,
`README.md`, `presentation.html`) remain at the repo root.

---

## Three-Level CLAUDE.md Structure

| Level | File | Purpose |
|---|---|---|
| Project | this file (repo root) | Shared conventions for the whole migration |
| Webapp | `contoso-migration/workloads/webapp/CLAUDE.md` | Node.js/Express app, Container Apps target |
| Batch | `contoso-migration/workloads/batch/CLAUDE.md` | Python reconciliation, Azure Batch target |
| Database | `contoso-migration/workloads/reporting-db/CLAUDE.md` | PostgreSQL schema, Flexible Server target |
| Infrastructure | `contoso-migration/infrastructure/CLAUDE.md` | Terraform/Azure, secrets rules, naming |

---

## Custom Slash Commands

These live in `.claude/commands/` and are available project-wide.

- `/extract-dependency` — Scans a workload directory for hardcoded on-prem dependencies
  (RFC1918 IPs, local filesystem paths, plaintext credentials) and emits a structured finding
  report matching the format in `contoso-migration/discovery/current-state.md`.

- `/validate-migration` — Runs the full pytest validation suite against the live Docker Compose
  stack and formats the output as a pass/fail table per test module.

- `/check-secrets` — Scans all `*.tf` files for plaintext secret patterns and reports any
  findings before a Terraform plan is run. Complements the PreToolUse hook.

- `/cutover-checklist` — Generates a pre-cutover checklist from the ADRs and the current
  validation suite status. Use before any environment promotion.

---

## Hooks

### PreToolUse — Block plaintext secrets in IaC
**File:** `contoso-migration/.claude/settings.json`

Intercepts every `Edit` or `Write` tool call targeting a `*.tf` file. If the proposed content
contains a plaintext secret pattern (e.g., `password = "..."`, `secret_key = "..."`), the hook
rejects the call with a structured error explaining what to use instead (Key Vault reference).

**Why this is a hook, not a prompt:** A prompt-level instruction ("prefer Key Vault") can be
overridden by context drift or a long conversation. This hook is a hard stop — it fires
deterministically on every IaC file write, regardless of what the rest of the conversation says.
The preference ("prefer Key Vault for X") lives in `contoso-migration/infrastructure/CLAUDE.md`.
The hard block lives here. See [ADR-001](contoso-migration/decisions/ADR-001-migration-strategy.md)
for the compliance rationale.

### PostToolUse — Log IaC changes
After any Bash tool call that runs `terraform plan`, a PostToolUse hook appends a timestamped
summary to `.claude/iac-change-log.md`. This is lightweight observability for the migration
journey, not a guardrail.

---

## Plan Mode

Use Plan Mode for any of these before executing:
- Changes to `infrastructure/` (Terraform module restructuring, new resources)
- Changes to `docker-compose.yml`
- Any step that matches the cutover runbook in ADR-001
- Anything described as "destructive" in a workload `CLAUDE.md`

Direct execution is fine for: editing app source code, adding tests, updating documentation.

---

## Azure Naming Convention

```
{resource-type-abbr}-contoso-{workload}-{env}
```

Examples:
- `app-contoso-webapp-prod` — Container App
- `psql-contoso-reporting-prod` — PostgreSQL Flexible Server
- `kv-contoso-shared-prod` — Key Vault
- `rg-contoso-migration-prod` — Resource Group

Region abbreviation: `uksouth` (never `uk-south` or `uks`).

---

## Security Invariants

These apply everywhere in the project. If you are about to violate one, stop and check with the
human first.

1. **No plaintext secrets in any file committed to git.** Secrets go in Azure Key Vault (prod) or
   Docker Compose environment variables (local dev only, never committed with real values).

2. **PII fields are tagged in schema comments.** PII fields: `customers.email`,
   `customers.phone`, `accounts.account_number`, `accounts.sort_code`. Never log raw PII —
   redact before logging.

3. **All data services must use private endpoints in Terraform.** PostgreSQL, Redis, and Blob
   Storage must never have `public_network_access_enabled = true` in any `azurerm_*` resource.

4. **UK South only.** Every `azurerm_*` resource must have `location = var.location` where
   `location` defaults to `"uksouth"`. Never hardcode a different region.

---

## Workload Boundaries

The three workloads are intentionally isolated. Claude should not:
- Import webapp modules from the batch job or vice versa
- Write Terraform resources for the webapp inside `infrastructure/modules/database/`
- Apply webapp-specific logic (e.g., Express middleware) to the batch job

When editing across workload boundaries, use Plan Mode.

---

## Testing

```bash
# Full validation suite
cd validation && pytest -v --tb=short

# Smoke tests only
pytest -v -m smoke

# Discovery-finding tests (migration blocker checks)
pytest -v -m discovery

# Single module
pytest -v validation/test_data_integrity.py
```

The validation suite is the definition of "migration succeeded." If any test fails, the migration
is not complete. Do not mark a cutover task done unless the suite is green.

---

## Common Commands

```bash
# Start local Azure stand-in stack (from contoso-migration/)
cd contoso-migration
docker compose up -d

# Check web app health
curl http://localhost:3000/health

# View webapp logs
docker compose logs -f webapp

# Run batch job manually
docker compose run --rm batch python reconcile.py

# Connect to local Postgres
docker compose exec postgres psql -U contoso -d contoso

# Run validation suite
cd contoso-migration/validation && pip install -r requirements.txt && pytest -v --tb=short

# Terraform
cd contoso-migration/infrastructure
terraform init
terraform plan -var-file=environments/dev.tfvars
terraform apply -var-file=environments/dev.tfvars
```
