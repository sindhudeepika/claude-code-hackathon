"""
Smoke tests — fast connectivity and liveness checks.
These must pass before any other test module runs.
If these fail, the migration environment is not ready.
"""

import pytest
import psycopg2

pytestmark = pytest.mark.usefixtures("webapp_available")


@pytest.mark.smoke
def test_webapp_health_returns_200(http, webapp_url):
    resp = http.get(f"{webapp_url}/health", timeout=10)
    assert resp.status_code == 200, f"Health check failed: {resp.text}"


@pytest.mark.smoke
def test_webapp_health_body_structure(http, webapp_url):
    resp = http.get(f"{webapp_url}/health", timeout=10)
    body = resp.json()
    assert body["status"] == "ok"
    assert "timestamp" in body
    assert "checks" in body
    assert body["checks"]["database"] == "ok", (
        "DB check is not 'ok' — is the Postgres container healthy?"
    )


@pytest.mark.smoke
def test_webapp_health_has_version(http, webapp_url):
    resp = http.get(f"{webapp_url}/health", timeout=10)
    body = resp.json()
    assert "version" in body


@pytest.mark.smoke
def test_database_direct_connectivity(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("SELECT 1 AS ok")
        row = cur.fetchone()
    assert row[0] == 1, "Direct DB connection failed"


@pytest.mark.smoke
def test_required_tables_exist(db_cursor):
    required_tables = ["customers", "accounts", "transactions", "reconciliation_reports"]
    db_cursor.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
    )
    existing = {row["tablename"] for row in db_cursor.fetchall()}
    missing = set(required_tables) - existing
    assert not missing, f"Missing tables after schema migration: {missing}"


@pytest.mark.smoke
def test_seed_data_loaded(db_cursor):
    db_cursor.execute("SELECT COUNT(*) AS n FROM customers")
    count = db_cursor.fetchone()["n"]
    assert count >= 5, f"Expected at least 5 seed customers, found {count}"


@pytest.mark.smoke
def test_webapp_404_returns_json(http, webapp_url):
    resp = http.get(f"{webapp_url}/nonexistent-path-xyz", timeout=10)
    assert resp.status_code == 404
    body = resp.json()
    assert "error" in body


@pytest.mark.smoke
def test_webapp_unknown_customer_returns_404(http, webapp_url):
    resp = http.get(f"{webapp_url}/api/customers/00000000-0000-0000-0000-000000000000", timeout=10)
    assert resp.status_code == 404
