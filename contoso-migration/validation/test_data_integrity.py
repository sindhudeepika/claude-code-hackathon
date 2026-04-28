"""
Data integrity tests — end-to-end reconciliation correctness.
Seeds known data, runs the batch job logic directly (without Docker), verifies output.
These are the tests that prove "the batch job works after migration."
Requires a running Postgres instance (Docker Compose stack).
"""

import pytest
pytestmark = pytest.mark.usefixtures("rollback_after_test")

import csv
import io
import os
import subprocess
import sys
from datetime import date
from decimal import Decimal

import psycopg2
import psycopg2.extras
import pytest


BATCH_DIR = os.path.join(os.path.dirname(__file__), "..", "workloads", "batch")
SAMPLE_FEED = os.path.join(BATCH_DIR, "sample_feed.csv")
TEST_DATE = "2026-04-27"


@pytest.mark.integrity
def test_all_seed_transactions_are_pending(db_cursor):
    """Seed transactions start as 'pending' — reconciliation moves them to 'reconciled'."""
    db_cursor.execute(
        "SELECT COUNT(*) AS n FROM transactions WHERE transaction_date = %s AND status = 'pending'",
        (TEST_DATE,),
    )
    count = db_cursor.fetchone()["n"]
    assert count >= 10, (
        f"Expected at least 10 pending transactions for {TEST_DATE}, found {count}. "
        "Re-run seed.sql to reset."
    )


@pytest.mark.integrity
def test_sample_feed_matches_seed_external_refs(db_cursor):
    """Every external_ref in sample_feed.csv must exist in the transactions table."""
    with open(SAMPLE_FEED, newline="", encoding="utf-8") as f:
        feed_rows = list(csv.DictReader(f))

    feed_refs = {row["external_ref"].strip() for row in feed_rows}
    assert len(feed_refs) >= 10, "Sample feed should have at least 10 rows"

    db_cursor.execute(
        "SELECT external_ref FROM transactions WHERE external_ref = ANY(%s)",
        (list(feed_refs),),
    )
    db_refs = {row["external_ref"] for row in db_cursor.fetchall()}
    unmatched = feed_refs - db_refs
    assert not unmatched, (
        f"Feed contains external_refs not found in DB: {unmatched}. "
        "Seed data and sample_feed.csv are out of sync."
    )


@pytest.mark.integrity
def test_sample_feed_amounts_match_db(db_cursor):
    """Feed amounts must match DB transaction amounts within 0.5 pence rounding tolerance."""
    with open(SAMPLE_FEED, newline="", encoding="utf-8") as f:
        feed_rows = list(csv.DictReader(f))

    mismatches = []
    for row in feed_rows:
        ref = row["external_ref"].strip()
        feed_amount = abs(Decimal(row["amount"]))

        db_cursor.execute(
            "SELECT amount FROM transactions WHERE external_ref = %s",
            (ref,),
        )
        db_row = db_cursor.fetchone()
        if db_row is None:
            continue

        db_amount = abs(Decimal(str(db_row["amount"])))
        if abs(db_amount - feed_amount) > Decimal("0.005"):
            mismatches.append({
                "ref": ref,
                "feed": str(feed_amount),
                "db": str(db_amount),
            })

    assert not mismatches, f"Amount mismatches between feed and DB: {mismatches}"


@pytest.mark.integrity
def test_reconciliation_report_is_written(db_conn, db_cursor):
    """Running the reconcile script must produce a reconciliation_reports row."""
    # Delete any existing report for the test date so we can verify a new one is created
    db_cursor.execute(
        "DELETE FROM reconciliation_reports WHERE report_date = %s",
        (TEST_DATE,),
    )
    db_conn.commit()

    env = {
        **os.environ,
        "DB_HOST": os.environ.get("DB_HOST", "localhost"),
        "DB_PORT": os.environ.get("DB_PORT", "5432"),
        "DB_NAME": os.environ.get("DB_NAME", "contoso"),
        "DB_USER": os.environ.get("DB_USER", "contoso"),
        "DB_PASSWORD": os.environ.get("DB_PASSWORD", "dev-only-local"),
        "FEED_LOCAL_PATH": os.path.dirname(SAMPLE_FEED),
        "REPORT_DATE": TEST_DATE,
    }

    result = subprocess.run(
        [sys.executable, "reconcile.py"],
        cwd=BATCH_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode in (0, 2), (
        f"Batch job exited with unexpected code {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

    db_cursor.execute(
        "SELECT * FROM reconciliation_reports WHERE report_date = %s",
        (TEST_DATE,),
    )
    report = db_cursor.fetchone()
    assert report is not None, "No reconciliation_reports row written for test date"
    assert report["total_processed"] >= 10, "Fewer rows processed than expected"
    assert report["status"] == "completed"


@pytest.mark.integrity
def test_reconciled_transactions_are_updated(db_cursor):
    """After reconciliation, matched transactions must be in 'reconciled' status."""
    db_cursor.execute(
        "SELECT COUNT(*) AS n FROM transactions "
        "WHERE transaction_date = %s AND status = 'reconciled'",
        (TEST_DATE,),
    )
    count = db_cursor.fetchone()["n"]
    assert count >= 8, (
        f"Expected most transactions to be reconciled, found only {count}. "
        "Reconciliation may have failed silently."
    )


@pytest.mark.integrity
def test_zero_feed_rows_causes_nonzero_exit():
    """Batch job must exit non-zero if the feed file is empty — not silently succeed."""
    empty_feed_dir = os.path.join(os.path.dirname(__file__), "fixtures")
    os.makedirs(empty_feed_dir, exist_ok=True)

    # Write an empty feed file (header only)
    empty_feed = os.path.join(empty_feed_dir, f"20260427_transactions.csv")
    with open(empty_feed, "w") as f:
        f.write("external_ref,amount,description,transaction_date,sort_code,account_number\n")

    env = {
        **os.environ,
        "DB_HOST": os.environ.get("DB_HOST", "localhost"),
        "DB_PORT": os.environ.get("DB_PORT", "5432"),
        "DB_NAME": os.environ.get("DB_NAME", "contoso"),
        "DB_USER": os.environ.get("DB_USER", "contoso"),
        "DB_PASSWORD": os.environ.get("DB_PASSWORD", "dev-only-local"),
        "FEED_LOCAL_PATH": empty_feed_dir,
        "REPORT_DATE": "2026-04-27",
    }

    result = subprocess.run(
        [sys.executable, "reconcile.py"],
        cwd=BATCH_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode != 0, (
        "Batch job silently succeeded with an empty feed. "
        "This is discovery finding #3 — empty feed must be a loud failure, not a silent one."
    )
