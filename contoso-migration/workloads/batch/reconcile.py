"""
Contoso Financial — Nightly Batch Reconciliation Job

Reads a daily transaction feed (CSV) from storage, reconciles against the transactions table,
and writes a reconciliation report. Designed to run as an Azure Container App Job (cron).

On-prem used an NFS mount for feed files (see discovery finding #3).
In Azure, FEED_STORAGE_CONNECTION must be set to an Azure Blob Storage connection string.
"""

import csv
import io
import logging
import os
import sys
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import psycopg2
import psycopg2.extras

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format='{"timestamp": "%(asctime)s", "level": "%(levelname)s", "message": "%(message)s"}',
    datefmt='%Y-%m-%dT%H:%M:%SZ',
)
log = logging.getLogger(__name__)


def get_db_connection():
    """Connect using env vars only. Legacy config file path removed — see discovery finding #4."""
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", "5432")),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        sslmode=os.environ.get("DB_SSLMODE", "require"),
        connect_timeout=10,
    )


def load_feed(feed_date: date) -> list[dict]:
    """
    Load the daily transaction feed. In Azure, reads from Blob Storage via
    FEED_STORAGE_CONNECTION. In local dev (Docker Compose), reads from FEED_LOCAL_PATH.

    Legacy NFS fallback intentionally removed — see discovery finding #3.
    """
    feed_storage = os.environ.get("FEED_STORAGE_CONNECTION")
    feed_local = os.environ.get("FEED_LOCAL_PATH")

    if not feed_storage and not feed_local:
        raise EnvironmentError(
            "Neither FEED_STORAGE_CONNECTION nor FEED_LOCAL_PATH is set. "
            "In Azure, set FEED_STORAGE_CONNECTION. In local dev, set FEED_LOCAL_PATH. "
            "The on-prem NFS fallback has been removed (discovery finding #3)."
        )

    filename = f"{feed_date.strftime('%Y%m%d')}_transactions.csv"

    if feed_storage:
        log.info(f"Loading feed from Azure Blob Storage: {filename}")
        return _load_from_blob(feed_storage, filename)
    else:
        path = os.path.join(feed_local, filename)
        log.info(f"Loading feed from local path: {path}")
        return _load_from_file(path)


def _load_from_blob(connection_string: str, filename: str) -> list[dict]:
    from azure.storage.blob import BlobServiceClient
    client = BlobServiceClient.from_connection_string(connection_string)
    blob = client.get_blob_client(container="feeds", blob=filename)
    data = blob.download_blob().readall().decode("utf-8")
    return list(csv.DictReader(io.StringIO(data)))


def _load_from_file(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def reconcile(conn, feed_rows: list[dict], report_date: date) -> dict:
    matched = []
    unmatched = []
    invalid = []

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        for row in feed_rows:
            external_ref = row.get("external_ref", "").strip()
            if not external_ref:
                invalid.append({"row": row, "reason": "missing external_ref"})
                continue

            try:
                feed_amount = Decimal(row.get("amount", "0"))
            except InvalidOperation:
                invalid.append({"row": row, "reason": f"invalid amount: {row.get('amount')}"})
                continue

            cur.execute(
                "SELECT id, amount, status FROM transactions WHERE external_ref = %s",
                (external_ref,),
            )
            db_row = cur.fetchone()

            if db_row is None:
                unmatched.append({"external_ref": external_ref, "reason": "not_found_in_db"})
            elif abs(Decimal(str(db_row["amount"])) - feed_amount) > Decimal("0.005"):
                unmatched.append({
                    "external_ref": external_ref,
                    "reason": "amount_mismatch",
                    "feed_amount": str(feed_amount),
                    "db_amount": str(db_row["amount"]),
                })
            else:
                matched.append(external_ref)
                cur.execute(
                    "UPDATE transactions SET status = 'reconciled' WHERE external_ref = %s",
                    (external_ref,),
                )

    return {
        "report_date": report_date.isoformat(),
        "total_processed": len(feed_rows),
        "total_matched": len(matched),
        "total_unmatched": len(unmatched),
        "total_invalid": len(invalid),
        "unmatched_refs": [u["external_ref"] for u in unmatched],
        "invalid_rows": len(invalid),
    }


def write_report(conn, report: dict) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO reconciliation_reports
               (report_date, status, total_processed, total_matched, total_unmatched,
                total_invalid, unmatched_refs, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
               RETURNING id""",
            (
                report["report_date"],
                "completed",
                report["total_processed"],
                report["total_matched"],
                report["total_unmatched"],
                report["total_invalid"],
                report["unmatched_refs"],
            ),
        )
        report_id = cur.fetchone()[0]
    conn.commit()
    return report_id


def main():
    report_date = date.fromisoformat(os.environ.get("REPORT_DATE") or date.today().isoformat())
    log.info(f"Starting reconciliation for {report_date}")

    feed_rows = load_feed(report_date)
    log.info(f"Loaded {len(feed_rows)} rows from feed")

    if len(feed_rows) == 0:
        log.error("Feed is empty — aborting. This may indicate a missing feed file.")
        sys.exit(1)

    conn = get_db_connection()
    try:
        report = reconcile(conn, feed_rows, report_date)
        report_id = write_report(conn, report)

        mismatch_rate = report["total_unmatched"] / max(report["total_processed"], 1)
        log.info(f"Reconciliation complete: report_id={report_id}", )
        log.info(f"Matched={report['total_matched']} Unmatched={report['total_unmatched']} "
                 f"Invalid={report['total_invalid']} MismatchRate={mismatch_rate:.4%}")

        # Alert threshold: >0.1% mismatch triggers a non-zero exit for ops alerting
        if mismatch_rate > 0.001:
            log.error(f"Mismatch rate {mismatch_rate:.4%} exceeds 0.1% threshold")
            sys.exit(2)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
