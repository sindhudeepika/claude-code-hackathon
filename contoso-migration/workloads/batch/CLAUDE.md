# CLAUDE.md — batch (contoso-migration/workloads/batch)

## What This Is
Python 3.11 nightly reconciliation job. Reads a daily CSV feed from storage, matches records
against the `transactions` table, writes a `reconciliation_reports` row. Runs as an Azure
Container App Job (cron schedule `0 2 * * *` UTC).

## Migration Status
Phase 1 lift-and-shift. The NFS mount fallback has been removed (finding #3). The plaintext
config.ini path has been removed (finding #4). Both are replaced by environment variables
injected via Azure Key Vault secret references.

## Required Environment Variables
| Variable | Description | Source |
|---|---|---|
| `DB_HOST` | PostgreSQL hostname | Container App env |
| `DB_NAME` | Database name | Container App env |
| `DB_USER` | DB user | Container App env |
| `DB_PASSWORD` | DB password | Key Vault secret ref |
| `FEED_STORAGE_CONNECTION` | Azure Blob Storage connection string | Key Vault secret ref |
| `REPORT_DATE` | ISO date override (optional, defaults to today) | Container App env |

## Never Do
- Read from `/etc/contoso/config.ini` or any local file for credentials.
- Fall back to `/mnt/findata/feeds` or any NFS path. The EnvironmentError in `load_feed()`
  is intentional — a silent empty-feed run is worse than a loud failure.
- Log PII fields (`sort_code`, `account_number`) even in error paths.

## Testing the Job
```bash
# From contoso-migration/
docker compose run --rm batch python reconcile.py
# Or with a specific date:
docker compose run --rm -e REPORT_DATE=2026-04-27 batch python reconcile.py
```

## Alerting
Exit code 2 means mismatch rate >0.1%. Azure Container App Jobs propagate this as a failed
execution. Wire an alert to the Container App Job failure metric in Azure Monitor.
