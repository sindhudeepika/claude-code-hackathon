# CLAUDE.md — reporting-db (contoso-migration/workloads/reporting-db)

## What This Is
PostgreSQL 16 schema for Contoso Financial's reporting database. Five internal teams query this
directly (BI, Risk, Finance, Compliance, Ops). Target: Azure Database for PostgreSQL Flexible
Server, UK South, zone-redundant HA.

## PII Fields
These columns are PII and must never appear in logs, API responses without the internal scope
header, or exported reports sent outside the VNet:
- `customers.email`
- `customers.phone`
- `accounts.account_number`
- `accounts.sort_code`

## Schema Change Rules
Schema changes require Plan Mode before execution. Rules:
1. All changes must be backwards-compatible until all five query clients are updated.
   - Adding a nullable column: safe
   - Adding a NOT NULL column without a default: NOT safe (use a default, then backfill)
   - Renaming a column: NOT safe (add new column + trigger, deprecate old column in Phase 2)
   - Dropping a column: requires confirming all five clients no longer reference it
2. All PII columns must have a comment tagging them as `-- PII`.
3. Indexes on PII columns should be created CONCURRENTLY in production to avoid locking.

## Destructive Operations
`DROP TABLE`, `TRUNCATE`, column drops: always require explicit confirmation from the human
before Claude executes. These are irreversible in production.

## Running Locally
```bash
# Schema is applied automatically by Docker Compose via docker-entrypoint-initdb.d/
docker compose up -d
docker compose exec postgres psql -U contoso -d contoso -f /docker-entrypoint-initdb.d/seed.sql
```
