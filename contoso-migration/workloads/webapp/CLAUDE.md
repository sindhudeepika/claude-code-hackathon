# CLAUDE.md — webapp (contoso-migration/workloads/webapp)

## What This Is
Node.js 18 / Express 4 customer portal. On-prem target was a bare VM; Azure target is
Azure Container Apps. The app must behave identically in both environments given the right
environment variables.

## Migration Status
Phase 1 lift-and-shift. The following are **not yet resolved** (Phase 2):
- Auth service is still on-prem; `AUTH_SERVICE_URL` must point there via VPN for Phase 1.
- No connection pooling middleware (PgBouncer). Acceptable at current transaction volumes.

## Config Rules
All config comes from environment variables via `src/config.js`. Never hardcode values in
source files. The `DB_PASSWORD` and `REDIS_PASSWORD` come from Azure Key Vault secret
references injected by the Container Apps environment.

## PII Rules
PII fields: `email`, `phone`, `account_number`, `sort_code`. Rules:
- Never log these fields raw. Redact before any `console.log` / `console.error` call.
- API responses redact PII unless the request carries `X-PII-Scope: internal`.
- The `X-PII-Scope: internal` header is blocked by Container Apps ingress for external traffic.

## Route Conventions
- All routes return JSON.
- Error responses: `{ "error": "<message>" }` with appropriate HTTP status.
- Health check at `GET /health` must always return 200 with `{ status: "ok" }` when the DB is
  reachable. Container Apps uses this for liveness and readiness probes.
- No business logic in route files — queries go in route files for simplicity at this scale,
  but keep them thin.

## Destructive Operations
Adding a DB migration (new column, index, constraint) requires Plan Mode before execution.
The reporting database has five live query clients; schema changes must be backwards-compatible
until all clients are updated.

## Running Locally
```bash
# From contoso-migration/
docker compose up -d
# App is at http://localhost:3000
curl http://localhost:3000/health
```
