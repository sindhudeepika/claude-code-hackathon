"""
Shared fixtures for the Contoso Financial migration validation suite.
Runs against the Docker Compose local stack by default.
Set WEBAPP_URL / DB_* env vars to target a different environment.
"""

import os
import psycopg2
import psycopg2.extras
import pytest
import requests


WEBAPP_URL = os.environ.get("WEBAPP_URL", "http://localhost:3000")

DB_CONFIG = {
    "host":     os.environ.get("DB_HOST", "localhost"),
    "port":     int(os.environ.get("DB_PORT", "5432")),
    "dbname":   os.environ.get("DB_NAME", "contoso"),
    "user":     os.environ.get("DB_USER", "contoso"),
    "password": os.environ.get("DB_PASSWORD", "dev-only-local"),
}


@pytest.fixture(scope="session")
def webapp_url():
    return WEBAPP_URL


@pytest.fixture(scope="session")
def webapp_available(webapp_url):
    """Skip webapp tests if Contoso webapp isn't running (e.g., another service is on the port)."""
    try:
        resp = requests.get(f"{webapp_url}/health", timeout=3)
        body = resp.json()
        if "status" not in body:
            pytest.skip(f"Contoso webapp not detected at {webapp_url} — /health returned unexpected body")
    except requests.exceptions.JSONDecodeError:
        pytest.skip(f"Contoso webapp not detected at {webapp_url} — /health returned non-JSON (wrong service?)")
    except requests.exceptions.ConnectionError:
        pytest.skip(f"Contoso webapp not running at {webapp_url}")
    except requests.exceptions.Timeout:
        pytest.skip(f"Contoso webapp timed out at {webapp_url}")


@pytest.fixture(scope="session")
def http():
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    yield session
    session.close()


@pytest.fixture(scope="session")
def db_conn():
    try:
        conn = psycopg2.connect(**DB_CONFIG, connect_timeout=5)
        conn.autocommit = False
        yield conn
        conn.close()
    except psycopg2.OperationalError as e:
        pytest.skip(f"Database not available (is Docker running?): {e}")


@pytest.fixture(scope="session")
def db_cursor(db_conn):
    with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        yield cur


@pytest.fixture()
def rollback_after_test(db_conn):
    """Roll back any DB writes made by a test, keeping the suite idempotent.
    Not autouse — only applied in test modules that write to the DB."""
    yield
    db_conn.rollback()


def pytest_configure(config):
    config.addinivalue_line("markers", "smoke: fast connectivity and health checks")
    config.addinivalue_line("markers", "contract: API response shape and schema tests")
    config.addinivalue_line("markers", "integrity: data integrity end-to-end tests")
    config.addinivalue_line("markers", "discovery: tests that specifically catch the five on-prem migration blockers")
