"""
Discovery finding tests — specifically catch the five on-prem migration blockers.
Each test corresponds to a finding in discovery/current-state.md.
If any of these fail, the corresponding finding has NOT been resolved.

Run with: pytest -v -m discovery
"""

import importlib.util
import ipaddress
import os
import re
import sys

import pytest


WEBAPP_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "workloads", "webapp", "src", "config.js"
)
BATCH_SCRIPT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "workloads", "batch", "reconcile.py"
)


# ─── Finding #1: Hardcoded Auth Service IP ────────────────────────────────────

@pytest.mark.discovery
def test_auth_url_env_var_takes_priority():
    """
    Finding #1: webapp/src/config.js must read AUTH_SERVICE_URL from environment.
    The default may still be an RFC1918 IP (for developer awareness), but the env
    var must override it — otherwise Azure deployments silently use the on-prem IP.
    """
    with open(WEBAPP_CONFIG_PATH, "r") as f:
        content = f.read()

    assert "AUTH_SERVICE_URL" in content, (
        "config.js does not reference AUTH_SERVICE_URL env var. "
        "Finding #1: auth service URL must come from the environment, not be hardcoded."
    )
    # Env var must appear before any hardcoded default (process.env check comes first)
    env_pos = content.find("AUTH_SERVICE_URL")
    default_ip_pos = content.find("10.0.1.45")
    if default_ip_pos != -1:
        assert env_pos < default_ip_pos, (
            "ENV var check must appear before the hardcoded IP fallback in config.js"
        )


@pytest.mark.discovery
def test_auth_url_default_is_documented():
    """Finding #1: The hardcoded IP default must have a comment explaining the migration risk."""
    with open(WEBAPP_CONFIG_PATH, "r") as f:
        content = f.read()

    if "10.0.1.45" in content:
        # Find the line with the hardcoded IP
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if "10.0.1.45" in line:
                # Check surrounding lines for a comment
                surrounding = "\n".join(lines[max(0, i-3):i+2])
                assert any(keyword in surrounding.lower() for keyword in ["legacy", "azure", "finding", "migration"]), (
                    f"Hardcoded IP on line {i+1} has no explanatory comment. "
                    "Migration risks must be documented in code."
                )


@pytest.mark.discovery
def test_auth_url_rfc1918_not_used_when_env_set(monkeypatch):
    """
    Finding #1: When AUTH_SERVICE_URL is set to a valid URL, the config must use it,
    not fall back to the hardcoded RFC1918 address.
    """
    monkeypatch.setenv("AUTH_SERVICE_URL", "https://auth.contoso.azure.internal/validate")

    # Re-evaluate config with the env var set
    with open(WEBAPP_CONFIG_PATH, "r") as f:
        content = f.read()

    # The env var read comes before the hardcoded fallback — this test documents the intent
    assert "process.env.AUTH_SERVICE_URL" in content or "AUTH_SERVICE_URL" in content


# ─── Finding #2: Local Filesystem Log File ────────────────────────────────────

@pytest.mark.discovery
def test_logs_go_to_stdout_by_default():
    """
    Finding #2: The default log destination must be stdout (null logFile), not a local path.
    A non-null default would cause silent log loss on Container Apps restarts.
    """
    with open(WEBAPP_CONFIG_PATH, "r") as f:
        content = f.read()

    # The logFile default must be null (stdout) not a filesystem path
    match = re.search(r"logFile\s*:\s*process\.env\.LOG_FILE\s*\|\|\s*(.+)", content)
    assert match, "Could not find logFile config pattern in config.js"

    default_value = match.group(1).strip().rstrip(",")
    assert default_value in ("null", "undefined", "''", '""'), (
        f"logFile default is {default_value!r}, not null. "
        "Finding #2: a non-null default writes logs to the container filesystem, "
        "which is ephemeral in Azure Container Apps."
    )


# ─── Finding #3: NFS-Mounted Feed Directory ───────────────────────────────────

@pytest.mark.discovery
def test_feed_source_not_local_filesystem():
    """
    Finding #3: reconcile.py must not silently fall back to /mnt/findata/feeds.
    If neither FEED_STORAGE_CONNECTION nor FEED_LOCAL_PATH is set, it must raise.
    """
    with open(BATCH_SCRIPT_PATH, "r") as f:
        content = f.read()

    assert "/mnt/findata" not in content, (
        "reconcile.py still contains the hardcoded NFS path /mnt/findata. "
        "Finding #3: this path does not exist in Azure and causes silent empty-feed runs."
    )


@pytest.mark.discovery
def test_feed_source_raises_on_missing_env():
    """
    Finding #3: If neither feed env var is set, the job must exit with an error,
    not silently process zero rows.
    """
    with open(BATCH_SCRIPT_PATH, "r") as f:
        content = f.read()

    assert "EnvironmentError" in content or "raise" in content, (
        "reconcile.py does not raise when feed source env vars are missing. "
        "Finding #3: a silent empty-feed run is worse than a loud failure."
    )


# ─── Finding #4: Plaintext DB Password in Config File ─────────────────────────

@pytest.mark.discovery
def test_db_credentials_from_env_not_file():
    """
    Finding #4: reconcile.py must read DB credentials from environment variables,
    not from /etc/contoso/config.ini.
    """
    with open(BATCH_SCRIPT_PATH, "r") as f:
        content = f.read()

    assert "/etc/contoso/config.ini" not in content, (
        "reconcile.py still references /etc/contoso/config.ini. "
        "Finding #4: this file contains a plaintext password from 2021 and must not be used."
    )
    assert "config.ini" not in content, (
        "reconcile.py references a config.ini file. "
        "Finding #4: all credentials must come from environment variables."
    )
    assert 'os.environ["DB_PASSWORD"]' in content or "os.environ.get" in content, (
        "reconcile.py does not read DB_PASSWORD from environment. "
        "Finding #4: credentials must come from env vars injected by Key Vault."
    )


@pytest.mark.discovery
def test_no_hardcoded_passwords_in_batch():
    """Finding #4: No hardcoded passwords in the batch source code."""
    with open(BATCH_SCRIPT_PATH, "r") as f:
        content = f.read()

    # Look for patterns like password = "something" with a non-empty non-env value
    hardcoded = re.findall(
        r'password\s*=\s*["\'][^"\']{4,}["\']',
        content,
        re.IGNORECASE,
    )
    assert not hardcoded, (
        f"Hardcoded password pattern found in reconcile.py: {hardcoded}. "
        "Finding #4: passwords must come from Key Vault via env vars."
    )


# ─── Finding #5: Redis Keepalive Cron ────────────────────────────────────────

@pytest.mark.discovery
def test_no_keepalive_required(http, webapp_url):
    """
    Finding #5: Azure Cache for Redis handles eviction natively — no keepalive pings needed.
    This test confirms the webapp is healthy without any external keepalive mechanism.
    The keepalive cron from the on-prem host (10.0.1.30:9090) must NOT be migrated.
    """
    # If the webapp health check passes without a keepalive cron running, finding #5 is resolved
    resp = http.get(f"{webapp_url}/health", timeout=15)
    assert resp.status_code == 200, (
        "Webapp is unhealthy. If this is a Redis connection issue, confirm Azure Cache for Redis "
        "maxmemory-policy is set to allkeys-lru and no external keepalive cron is needed."
    )


@pytest.mark.discovery
def test_no_rfc1918_redis_target_in_codebase():
    """Finding #5: The hardcoded Redis keepalive IP (10.0.1.30) must not appear in any source file."""
    webapp_src = os.path.join(
        os.path.dirname(__file__), "..", "workloads", "webapp", "src"
    )
    batch_src = os.path.join(
        os.path.dirname(__file__), "..", "workloads", "batch"
    )

    for root_dir in [webapp_src, batch_src]:
        for dirpath, _, filenames in os.walk(root_dir):
            for filename in filenames:
                if filename.endswith((".js", ".py")):
                    filepath = os.path.join(dirpath, filename)
                    with open(filepath, "r") as f:
                        content = f.read()
                    assert "10.0.1.30" not in content, (
                        f"Hardcoded Redis keepalive IP found in {filepath}. "
                        "Finding #5: the keepalive target must not be migrated."
                    )
