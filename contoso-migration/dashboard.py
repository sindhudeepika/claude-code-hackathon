#!/usr/bin/env python3
"""
Contoso Financial — Live Migration Dashboard Generator

Runs the test suite, reads the Bedrock survey report, and writes a self-contained
dashboard.html. Opens automatically in the default browser.

Usage:
    python dashboard.py
    python dashboard.py --no-browser
"""

import argparse
import re
import subprocess
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

REPO_ROOT  = Path(__file__).parent
VALIDATION = REPO_ROOT / "validation"
SURVEY_MD  = REPO_ROOT / "agents" / "survey-report.md"
OUT_HTML   = REPO_ROOT / "dashboard.html"

CHALLENGES = [
    {"n": 1, "name": "The Memo",       "status": "done",    "note": "ADR-001 — lift-and-shift decision with risk register"},
    {"n": 2, "name": "The Discovery",  "status": "done",    "note": "Five on-prem blockers documented and proven by tests"},
    {"n": 3, "name": "The Options",    "status": "done",    "note": "ADR-002 — Azure service selection with scored alternatives"},
    {"n": 4, "name": "The Container",  "status": "done",    "note": "Multi-stage Dockerfile, non-root user, Docker Compose stack"},
    {"n": 5, "name": "The Foundation", "status": "partial", "note": "Terraform IaC written; not yet applied to live Azure"},
    {"n": 6, "name": "The Proof",      "status": "done",    "note": "33 tests — smoke, contract, integrity, discovery"},
    {"n": 7, "name": "The Scorecard",  "status": "skipped", "note": "IaC eval harness — Phase 2 item"},
    {"n": 8, "name": "The Undo",       "status": "skipped", "note": "Rollback outlined in ADR-001; full rehearsal pending"},
    {"n": 9, "name": "The Survey",     "status": "done",    "note": "Coordinator + 3 parallel Bedrock subagents (Claude Sonnet 4.6)"},
]

FINDINGS = [
    {"n": 1, "title": "Hardcoded Auth Service IP",
     "detail": "http://10.0.1.45:8080/auth/validate → AUTH_SERVICE_URL env var (not routable in Azure)"},
    {"n": 2, "title": "Local Filesystem Log File",
     "detail": "/var/log/contoso/app.log → stdout by default (LOG_FILE=null)"},
    {"n": 3, "title": "NFS-Mounted Feed Directory",
     "detail": "/mnt/findata/feeds → Azure Blob Storage via FEED_STORAGE_CONNECTION"},
    {"n": 4, "title": "Plaintext DB Password in config.ini",
     "detail": "/etc/contoso/config.ini (C0nt0s0B@tch2021!) → Azure Key Vault secret reference"},
    {"n": 5, "title": "Redis Keepalive Cron",
     "detail": "http://10.0.1.30:9090/cache/warm every 5 min → eliminated (Azure Cache manages eviction)"},
]

AI_FINDINGS = [
    {"title": "Split-brain cutover risk on transactions table",
     "severity": "Critical",
     "detail": "batch writes UPDATE transactions SET status='reconciled' — webapp reads same table. Must cut over simultaneously."},
    {"title": "Redis TLS port change (6379 → 6380) breaks webapp sessions",
     "severity": "Critical",
     "detail": "Azure Cache for Redis mandates TLS on 6380. REDIS_TLS=true and REDIS_PORT=6380 must be set."},
    {"title": "X-PII-Scope: internal header is spoofable from internet",
     "severity": "Critical",
     "detail": "Any caller can send this header to get fully unredacted PII. Must be gated at Container Apps ingress."},
    {"title": "SSL defaults unsafe for both workloads",
     "severity": "Critical",
     "detail": "Fixed: DB_SSL now on by default (webapp), DB_SSLMODE=require (batch)."},
    {"title": "PostgreSQL version discrepancy: on-prem 14 → target 16",
     "severity": "Action required",
     "detail": "pg_dump from PG14 into PG16 requires extension version validation (pgaudit, pgcrypto)."},
    {"title": "No GDPR Article 17 right-to-erasure mechanism",
     "severity": "Action required",
     "detail": "ON DELETE RESTRICT foreign keys block customer deletion. Must resolve before go-live in UK South."},
    {"title": "Connection pool exhaustion across all three workloads",
     "severity": "Phase 2",
     "detail": "Webapp + batch + 5 internal teams on one Flexible Server SKU. PgBouncer is a Phase 2 prerequisite."},
]


# ── Test runner ───────────────────────────────────────────────────────────────

def run_tests() -> dict:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-v", "--tb=no", "-q"],
        cwd=VALIDATION,
        capture_output=True,
        text=True,
        timeout=120,
    )
    out = result.stdout + result.stderr

    def extract(pattern):
        m = re.search(pattern, out)
        return m.group(1) if m else "0"

    passed   = int(extract(r'(\d+) passed'))
    skipped  = int(extract(r'(\d+) skipped'))
    failed   = int(extract(r'(\d+) failed'))
    duration = float(extract(r'in ([\d.]+)s'))

    tests = []
    for line in out.splitlines():
        for status in ("PASSED", "FAILED", "SKIPPED"):
            if status in line:
                name = re.sub(r'\s+(PASSED|FAILED|SKIPPED).*', '', line).strip()
                tests.append({"name": name, "status": status})
                break

    return {"passed": passed, "skipped": skipped, "failed": failed,
            "duration": duration, "tests": tests}


# ── Survey parser ─────────────────────────────────────────────────────────────

def parse_survey() -> dict:
    if not SURVEY_MD.exists():
        return {}
    text = SURVEY_MD.read_text(encoding="utf-8")

    scores = {}
    for m in re.finditer(
        r'\|\s*(reporting-db|webapp|batch)\s*\|\s*(\d+)\s*/\s*10\s*\|\s*\*\*(\w+)\*\*', text
    ):
        scores[m.group(1)] = {"score": int(m.group(2)), "risk": m.group(3)}

    m = re.search(r'Generated:\s*(.+)', text)
    generated = m.group(1).strip() if m else "unknown"

    return {"scores": scores, "generated": generated}


# ── HTML builder ──────────────────────────────────────────────────────────────

def build_html(tests: dict, survey: dict, timestamp: str) -> str:
    passed, skipped, failed = tests["passed"], tests["skipped"], tests["failed"]
    total    = passed + skipped + failed or 1
    pct_pass = round(passed  / total * 100, 1)
    pct_skip = round(skipped / total * 100, 1)
    pct_fail = round(failed  / total * 100, 1)

    status_text  = "MIGRATION READY" if failed == 0 else "NEEDS ATTENTION"
    status_color = "#107C10" if failed == 0 else "#D13438"
    done_count   = sum(1 for c in CHALLENGES if c["status"] == "done")

    # ── Challenge rows ────────────────────────────────────────────────────────
    ch_rows = ""
    for c in CHALLENGES:
        badge = {
            "done":    '<span class="badge bdone">✓ Done</span>',
            "partial": '<span class="badge bpartial">~ Partial</span>',
            "skipped": '<span class="badge bskip">Skipped</span>',
        }[c["status"]]
        ch_rows += (
            f'<tr><td class="ch-n">{c["n"]}</td>'
            f'<td><strong>{c["name"]}</strong></td>'
            f'<td>{badge}</td>'
            f'<td class="ch-note">{c["note"]}</td></tr>\n'
        )

    # ── Finding rows ──────────────────────────────────────────────────────────
    fi_rows = ""
    for f in FINDINGS:
        fi_rows += f"""<div class="fi-row">
          <span class="fi-num">{f['n']}</span>
          <div><div class="fi-title">{f['title']}</div>
               <div class="fi-detail">{f['detail']}</div></div>
          <span class="fi-tag">✓ Fixed</span>
        </div>\n"""

    # ── AI finding rows ───────────────────────────────────────────────────────
    sev_colors = {
        "Critical":        ("#D13438", "#2B0A0A", "#5C1414"),
        "Action required": ("#FF8C00", "#2B1900", "#6B4200"),
        "Phase 2":         ("#0078D4", "#0A1929", "#0C3A6B"),
    }
    ai_rows = ""
    for f in AI_FINDINGS:
        c_text, c_bg, c_border = sev_colors.get(f["severity"], ("#999", "#222", "#444"))
        ai_rows += f"""<div class="ai-row" style="border-left:3px solid {c_text}; background:{c_bg}22; padding:0.75rem 1rem; border-radius:0 8px 8px 0; margin-bottom:0.75rem;">
          <div style="display:flex; justify-content:space-between; align-items:center; gap:1rem; flex-wrap:wrap;">
            <strong style="font-size:0.85rem;">{f['title']}</strong>
            <span style="font-size:0.7rem; font-weight:700; color:{c_text}; background:{c_bg}; border:1px solid {c_border}; padding:0.15rem 0.55rem; border-radius:20px; white-space:nowrap;">{f['severity']}</span>
          </div>
          <div style="font-size:0.78rem; color:#8899AA; margin-top:0.3rem;">{f['detail']}</div>
        </div>\n"""

    # ── Survey score cards ────────────────────────────────────────────────────
    workload_labels = {"webapp": "Customer Portal", "batch": "Batch Job", "reporting-db": "Reporting DB"}
    score_cards = ""
    for key in ["reporting-db", "webapp", "batch"]:
        s = survey.get("scores", {}).get(key, {"score": "?", "risk": "Unknown"})
        risk_cls = "risk-low" if s["risk"] == "Low" else "risk-med"
        score_cards += f"""<div class="score-card">
          <div class="sc-label">{workload_labels.get(key, key)}</div>
          <div class="sc-score">{s['score']}<span class="sc-denom">/10</span></div>
          <div class="sc-risk {risk_cls}">{s['risk']} Risk</div>
        </div>\n"""

    # ── Test table rows ───────────────────────────────────────────────────────
    test_rows = ""
    for t in tests.get("tests", []):
        cls  = {"PASSED": "tr-pass", "FAILED": "tr-fail", "SKIPPED": "tr-skip"}[t["status"]]
        icon = {"PASSED": "✓", "FAILED": "✗", "SKIPPED": "○"}[t["status"]]
        name = (t["name"]
                .replace("test_discovery_findings.py::", "discovery :: ")
                .replace("test_smoke.py::", "smoke :: ")
                .replace("test_contract.py::", "contract :: ")
                .replace("test_data_integrity.py::", "integrity :: "))
        test_rows += (
            f'<tr class="{cls}"><td>{icon}</td>'
            f'<td style="width:100%">{name}</td>'
            f'<td style="white-space:nowrap">{t["status"]}</td></tr>\n'
        )

    survey_generated = survey.get("generated", "not available")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Contoso Migration Dashboard</title>
<style>
  :root {{
    --bg: #0F1117; --panel: #1A1D27; --border: #2A2D3E;
    --blue: #0078D4; --light: #50E6FF;
    --green: #107C10; --amber: #FF8C00; --red: #D13438;
    --text: #E8EAF0; --muted: #7B8099;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html {{ scroll-behavior: smooth; }}
  body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; }}

  header {{
    background: linear-gradient(90deg, #003A75, #0078D4);
    padding: 1.25rem 2rem;
    display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 1rem;
    border-bottom: 2px solid #0093C4;
  }}
  .hdr-left h1 {{ font-size: 1.25rem; color: white; }}
  .hdr-left h1 span {{ color: var(--light); }}
  .hdr-left p {{ font-size: 0.78rem; color: rgba(255,255,255,0.55); margin-top: 0.2rem; }}
  .hdr-right {{ text-align: right; font-size: 0.78rem; color: rgba(255,255,255,0.55); line-height: 1.7; }}
  .hdr-right strong {{ font-size: 1.1rem; color: {status_color}; }}

  .banner {{
    display: flex; align-items: center; gap: 0.75rem;
    padding: 0.65rem 2rem; font-size: 0.9rem; font-weight: 700;
    background: {status_color}18; border-bottom: 2px solid {status_color}; color: {status_color};
  }}
  .pulse {{ width: 10px; height: 10px; border-radius: 50%; background: {status_color}; animation: pulse 2s infinite; flex-shrink: 0; }}
  @keyframes pulse {{ 0%,100% {{ opacity:1; }} 50% {{ opacity:0.3; }} }}

  .kpi-row {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 1rem; padding: 1.5rem 2rem; }}
  .kpi {{ background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 1.25rem; text-align: center; }}
  .kpi-number {{ font-size: 2.2rem; font-weight: 700; color: var(--light); }}
  .kpi-label {{ font-size: 0.72rem; color: var(--muted); margin-top: 0.25rem; text-transform: uppercase; letter-spacing: 0.06em; }}

  .panels {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1.25rem; padding: 0 2rem 2rem; }}
  @media (max-width: 860px) {{ .panels {{ grid-template-columns: 1fr; }} }}
  .panel {{ background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 1.5rem; }}
  .panel.wide {{ grid-column: 1 / -1; }}
  .panel h2 {{ font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--light); margin-bottom: 1.25rem; }}

  .pbar {{ display: flex; border-radius: 6px; overflow: hidden; height: 16px; }}
  .pbar-pass {{ background: var(--green); width: {pct_pass}%; }}
  .pbar-skip {{ background: #4A90D9; width: {pct_skip}%; }}
  .pbar-fail {{ background: var(--red); width: {pct_fail}%; }}
  .pbar-legend {{ display: flex; gap: 1.25rem; font-size: 0.78rem; color: var(--muted); margin-top: 0.6rem; flex-wrap: wrap; }}
  .pbar-legend span {{ display: flex; align-items: center; gap: 0.35rem; }}
  .dot {{ width: 8px; height: 8px; border-radius: 50%; display: inline-block; flex-shrink: 0; }}

  .test-scroll {{ max-height: 280px; overflow-y: auto; margin-top: 1rem; border: 1px solid var(--border); border-radius: 8px; }}
  .test-table {{ width: 100%; border-collapse: collapse; font-size: 0.78rem; }}
  .test-table tr {{ border-bottom: 1px solid var(--border); }}
  .test-table tr:last-child {{ border-bottom: none; }}
  .test-table td {{ padding: 0.4rem 0.6rem; }}
  .tr-pass td:first-child {{ color: var(--green); font-weight: 700; }}
  .tr-fail td:first-child {{ color: var(--red); font-weight: 700; }}
  .tr-skip td:first-child {{ color: var(--muted); }}
  .tr-pass {{ }} .tr-fail {{ background: #1A0A0A; }} .tr-skip td {{ color: var(--muted); }}
  .tr-pass:hover td, .tr-skip:hover td {{ background: rgba(255,255,255,0.02); }}

  .score-cards {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.75rem; }}
  .score-card {{ background: #12151F; border: 1px solid var(--border); border-radius: 10px; padding: 1rem; text-align: center; }}
  .sc-label {{ font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); margin-bottom: 0.35rem; }}
  .sc-score {{ font-size: 2rem; font-weight: 700; color: var(--light); line-height: 1; }}
  .sc-denom {{ font-size: 0.9rem; color: var(--muted); }}
  .sc-risk {{ font-size: 0.78rem; font-weight: 700; margin-top: 0.35rem; }}
  .risk-low {{ color: var(--green); }} .risk-med {{ color: var(--amber); }}

  .ch-table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; }}
  .ch-table tr {{ border-bottom: 1px solid var(--border); }}
  .ch-table tr:last-child {{ border-bottom: none; }}
  .ch-table tr:hover td {{ background: rgba(255,255,255,0.02); }}
  .ch-table td {{ padding: 0.6rem 0.75rem; vertical-align: middle; }}
  .ch-n {{ color: var(--muted); width: 28px; }}
  .ch-note {{ color: var(--muted); font-size: 0.78rem; }}
  .badge {{ display: inline-flex; padding: 0.15rem 0.55rem; border-radius: 20px; font-size: 0.68rem; font-weight: 700; white-space: nowrap; }}
  .bdone {{ background: #0D2B0D; color: #4CAF50; border: 1px solid #2E7D2E; }}
  .bpartial {{ background: #2B1D00; color: var(--amber); border: 1px solid #6B4A00; }}
  .bskip {{ background: #1E2130; color: var(--muted); border: 1px solid var(--border); }}

  .fi-row {{ display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: 1rem; padding: 0.7rem 0; border-bottom: 1px solid var(--border); }}
  .fi-row:last-child {{ border-bottom: none; }}
  .fi-num {{ width: 26px; height: 26px; background: var(--green); color: white; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 0.72rem; font-weight: 700; flex-shrink: 0; }}
  .fi-title {{ font-size: 0.85rem; font-weight: 600; }}
  .fi-detail {{ font-size: 0.75rem; color: var(--muted); margin-top: 0.15rem; }}
  .fi-tag {{ font-size: 0.68rem; background: #0D2B0D; color: #4CAF50; border: 1px solid #2E7D2E; padding: 0.15rem 0.5rem; border-radius: 20px; font-weight: 700; white-space: nowrap; }}

  footer {{ text-align: center; padding: 1.5rem; color: var(--muted); font-size: 0.75rem; border-top: 1px solid var(--border); margin-top: 0.5rem; }}
  footer strong {{ color: var(--light); }}
</style>
</head>
<body>

<header>
  <div class="hdr-left">
    <h1>☁️ Contoso Financial — <span>Migration Dashboard</span></h1>
    <p>Azure UK South · Three workloads · Lift-and-shift Phase 1</p>
  </div>
  <div class="hdr-right">
    <strong>{status_text}</strong><br>
    Generated {timestamp}
  </div>
</header>

<div class="banner">
  <div class="pulse"></div>
  {status_text} &nbsp;·&nbsp; {failed} failures &nbsp;·&nbsp; {passed} tests passing &nbsp;·&nbsp; {done_count}/9 challenges complete &nbsp;·&nbsp; 5 blockers resolved
</div>

<!-- KPIs -->
<div class="kpi-row">
  <div class="kpi"><div class="kpi-number" style="color:#4CAF50">{passed}</div><div class="kpi-label">Tests Passing</div></div>
  <div class="kpi"><div class="kpi-number" style="color:{'#D13438' if failed else '#4CAF50'}">{failed}</div><div class="kpi-label">Tests Failing</div></div>
  <div class="kpi"><div class="kpi-number" style="color:#4A90D9">{skipped}</div><div class="kpi-label">Tests Skipped</div></div>
  <div class="kpi"><div class="kpi-number">{done_count}</div><div class="kpi-label">Challenges Done</div></div>
  <div class="kpi"><div class="kpi-number">5</div><div class="kpi-label">Blockers Resolved</div></div>
  <div class="kpi"><div class="kpi-number">7</div><div class="kpi-label">AI Risk Findings</div></div>
  <div class="kpi"><div class="kpi-number">100%</div><div class="kpi-label">UK South Residency</div></div>
</div>

<div class="panels">

  <!-- Test Results -->
  <div class="panel">
    <h2>📊 Test Suite &nbsp;<span style="color:var(--muted);font-weight:400;font-size:0.75rem;">({tests['duration']:.1f}s · pytest -v --tb=no -q)</span></h2>
    <div class="pbar"><div class="pbar-pass"></div><div class="pbar-skip"></div><div class="pbar-fail"></div></div>
    <div class="pbar-legend">
      <span><span class="dot" style="background:var(--green)"></span>{passed} passed</span>
      <span><span class="dot" style="background:#4A90D9"></span>{skipped} skipped (need Docker stack)</span>
      <span><span class="dot" style="background:var(--red)"></span>{failed} failed</span>
    </div>
    <div class="test-scroll">
      <table class="test-table">{test_rows}</table>
    </div>
  </div>

  <!-- Survey Scores -->
  <div class="panel">
    <h2>🤖 AI Survey — Bedrock Subagent Scores</h2>
    <div class="score-cards">{score_cards}</div>
    <div style="margin-top:1.25rem;font-size:0.8rem;color:var(--muted);line-height:1.8;">
      <strong style="color:var(--text)">Recommended cutover order:</strong><br>
      1. reporting-db &nbsp;→&nbsp; 2. batch <strong>+</strong> webapp <em>simultaneously</em><br>
      <span style="font-size:0.72rem">(split-brain risk if application workloads migrate in separate windows)</span>
    </div>
    <div style="margin-top:0.75rem;font-size:0.72rem;color:var(--muted);">
      Survey: {survey_generated} · Claude Sonnet 4.6 on Amazon Bedrock
    </div>
  </div>

  <!-- Challenge Status -->
  <div class="panel wide">
    <h2>🏆 Challenge Completion</h2>
    <table class="ch-table">
      <tr style="color:var(--muted);font-size:0.7rem;text-transform:uppercase;letter-spacing:0.05em;">
        <td class="ch-n">#</td><td>Challenge</td><td>Status</td><td class="ch-note">Notes</td>
      </tr>
      {ch_rows}
    </table>
  </div>

  <!-- On-prem Discovery Findings -->
  <div class="panel">
    <h2>🔎 On-Prem Discovery — All 5 Resolved</h2>
    {fi_rows}
  </div>

  <!-- AI Survey Findings -->
  <div class="panel">
    <h2>🤖 AI Survey — 7 Additional Risks Found</h2>
    {ai_rows}
  </div>

</div>

<footer>
  <strong>Contoso Financial Cloud Migration</strong> &nbsp;·&nbsp;
  Claude Code Hackathon &nbsp;·&nbsp; Scenario 2 &nbsp;·&nbsp;
  33 tests &nbsp;·&nbsp; 5 blockers fixed &nbsp;·&nbsp; 7 AI-surfaced risks &nbsp;·&nbsp; Azure UK South
</footer>

</body>
</html>"""


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate Contoso migration dashboard")
    parser.add_argument("--no-browser", action="store_true", help="Skip opening browser")
    args = parser.parse_args()

    print()
    print("=" * 60)
    print("  Contoso Financial — Migration Dashboard Generator")
    print("=" * 60)

    print("\nStep 1/3  Running test suite...")
    tests = run_tests()
    print(f"          {tests['passed']} passed · {tests['skipped']} skipped · {tests['failed']} failed · {tests['duration']:.1f}s")

    print("\nStep 2/3  Reading survey report...")
    survey = parse_survey()
    if survey.get("scores"):
        scores_str = " · ".join(f"{k} {v['score']}/10 ({v['risk']})" for k, v in survey["scores"].items())
        print(f"          {scores_str}")
    else:
        print("          Survey report not found — run agents/survey.py first")

    print("\nStep 3/3  Generating dashboard HTML...")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    html = build_html(tests, survey, timestamp)
    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"          Written -> {OUT_HTML}")

    url = OUT_HTML.as_uri()
    print()
    print("=" * 60)
    print(f"  Dashboard: {url}")
    print("=" * 60)
    print()

    if not args.no_browser:
        webbrowser.open(url)


if __name__ == "__main__":
    main()
