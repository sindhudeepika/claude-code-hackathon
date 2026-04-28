"""
Contoso Financial — Challenge 9: The Survey
============================================
Parallel workload discovery using Claude Sonnet 4.6 on Amazon Bedrock.

Three subagents analyze each workload independently and in parallel.
A coordinator then synthesises the three reports into a single cross-workload
discovery document — surfacing coupling that single-pass human analysis misses.

Architecture:
  coordinator
    ├── subagent: webapp       (reads workloads/webapp/src/*)
    ├── subagent: batch        (reads workloads/batch/*)
    └── subagent: reporting-db (reads workloads/reporting-db/*)
  coordinator synthesises → agents/survey-report.md

Key design principle: each subagent receives its context EXPLICITLY in its prompt.
Subagents do not share state — the coordinator passes only what each needs to know.

Usage:
    python survey.py
    python survey.py --profile bootcamp --output survey-report.md
    python survey.py --model anthropic.claude-haiku-4-5-20251001-v1:0  # faster/cheaper
"""

import argparse
import concurrent.futures
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError, NoCredentialsError, ProfileNotFound

# ─── Paths ────────────────────────────────────────────────────────────────────
AGENTS_DIR  = Path(__file__).parent
REPO_ROOT   = AGENTS_DIR.parent

# ─── Bedrock defaults ─────────────────────────────────────────────────────────
DEFAULT_PROFILE = "bootcamp"
DEFAULT_REGION  = "us-east-1"
DEFAULT_MODEL   = "us.anthropic.claude-sonnet-4-6"
FALLBACK_MODEL  = "anthropic.claude-3-sonnet-20240229-v1:0"

# ─── Workload definitions ──────────────────────────────────────────────────────
# Each entry declares which files the subagent will receive as context.
# Context is passed EXPLICITLY — subagents share nothing with each other.
WORKLOADS = {
    "webapp": {
        "name": "Customer Portal (webapp)",
        "description": (
            "Node.js 18 / Express 4 customer-facing web application. "
            "Reads customer and transaction data from PostgreSQL. "
            "Uses Redis for session caching."
        ),
        "files": [
            "workloads/webapp/src/config.js",
            "workloads/webapp/src/index.js",
            "workloads/webapp/src/db.js",
            "workloads/webapp/src/routes/health.js",
            "workloads/webapp/src/routes/customers.js",
            "workloads/webapp/src/routes/transactions.js",
            "workloads/webapp/package.json",
            "workloads/webapp/Dockerfile",
        ],
        "other_workloads": "batch (Python reconciliation job), reporting-db (PostgreSQL schema)",
    },
    "batch": {
        "name": "Nightly Batch Reconciliation",
        "description": (
            "Python 3.11 job that runs at 02:00 UTC. "
            "Reads a daily CSV feed from storage, reconciles against the transactions table, "
            "writes a reconciliation_reports row. Runs as Azure Container App Job."
        ),
        "files": [
            "workloads/batch/reconcile.py",
            "workloads/batch/requirements.txt",
            "workloads/batch/Dockerfile",
            "workloads/batch/sample_feed.csv",
        ],
        "other_workloads": "webapp (Node.js customer portal), reporting-db (PostgreSQL schema)",
    },
    "reporting-db": {
        "name": "Reporting Database",
        "description": (
            "PostgreSQL 16 schema. Five internal teams (BI, Risk, Finance, Compliance, Ops) "
            "query this database directly. Contains PII and PCI-scoped account data. "
            "Target: Azure Database for PostgreSQL Flexible Server, UK South."
        ),
        "files": [
            "workloads/reporting-db/schema.sql",
            "workloads/reporting-db/seed.sql",
        ],
        "other_workloads": "webapp (reads customers/accounts/transactions), batch (writes reconciliation_reports)",
    },
}

# ─── Prompts ──────────────────────────────────────────────────────────────────

SUBAGENT_SYSTEM = """\
You are a cloud migration architect performing a structured analysis of a single workload
for migration from on-premises infrastructure to Microsoft Azure UK South.

You are one of three independent subagents. You have been given the source files for your
assigned workload only. You do not have access to the other workloads' files — only their
names and descriptions, which are provided for cross-reference.

Your analysis must be precise, evidence-based, and grounded in what you can see in the
provided files. Do not speculate beyond what the code shows.

You MUST return a single valid JSON object and nothing else — no markdown fences, no
explanatory text before or after. The coordinator will parse your output directly."""

SUBAGENT_PROMPT = """\
Analyse the following workload for Azure cloud migration.

WORKLOAD KEY:   {workload_key}
WORKLOAD NAME:  {workload_name}
DESCRIPTION:    {workload_description}

OTHER WORKLOADS IN THIS MIGRATION (context only — you do not have their files):
{other_workloads}

═══════════════════════════════════════════
SOURCE FILES
═══════════════════════════════════════════
{file_contents}
═══════════════════════════════════════════

Return a JSON object with EXACTLY this schema (no extra fields):

{{
  "workload": "{workload_key}",
  "name": "{workload_name}",
  "cloud_readiness_score": <integer 1-10, where 10 = fully cloud-native ready>,
  "readiness_rationale": "<one sentence explaining the score>",
  "summary": "<2-3 sentences on overall migration readiness>",
  "migration_risk": "<low | medium | high>",
  "hard_dependencies": [
    {{
      "type": "<ip | filesystem | credential | service | port>",
      "value": "<the actual hardcoded value or path found in code>",
      "file": "<filename>",
      "breaks_in_azure": <true | false>,
      "description": "<why this matters for migration>"
    }}
  ],
  "soft_dependencies": [
    {{
      "assumption": "<what the code assumes about the environment>",
      "description": "<why this may not hold in Azure>"
    }}
  ],
  "pii_surface": [
    "<field or pattern name that contains PII or PCI-scoped data>"
  ],
  "cross_workload_coupling": [
    {{
      "coupled_to": "<webapp | batch | reporting-db>",
      "coupling_type": "<database | api | filesystem | queue | shared-credential>",
      "description": "<what the coupling is and which table/endpoint/file>",
      "migration_implication": "<what must be coordinated between the two workloads>"
    }}
  ],
  "phase1_blockers": [
    "<thing that MUST be resolved before lift-and-shift can proceed>"
  ],
  "phase2_optimisations": [
    "<cloud-native improvement that should be done after lift-and-shift>"
  ],
  "recommendations": [
    "<specific, actionable recommendation with the file/line it applies to>"
  ]
}}"""

COORDINATOR_SYSTEM = """\
You are the migration coordinator for Contoso Financial's Azure UK South migration.
You have received independent structured analysis reports from three subagents — one per workload.

Each subagent worked in isolation. Your job is to synthesise their findings and identify
things that no single subagent could see: cross-workload coupling, shared risks, migration
ordering constraints, and gaps in the human-written discovery document.

Write in the style of a technical architecture review document. Be specific, cite the
subagent findings, and be honest about what is uncertain."""

COORDINATOR_PROMPT = """\
You have received the following independent subagent reports for the three Contoso Financial workloads:

═══════════════════════════════════════════
SUBAGENT REPORTS
═══════════════════════════════════════════
{subagent_reports}
═══════════════════════════════════════════

HUMAN-WRITTEN DISCOVERY DOCUMENT (for comparison):
{human_discovery}
═══════════════════════════════════════════

Synthesise these reports into a cross-workload survey document with the following sections:

## Executive Summary
2-3 sentences. Overall migration readiness, highest risk, recommended first step.

## Cross-Workload Coupling Found
Table with columns: From | To | Coupling Type | Description | Migration Implication
Include ONLY couplings that span two or more workloads. Flag any the human-written
discovery document missed.

## Migration Risk Heatmap
Table with columns: Workload | Cloud Readiness Score | Risk Level | Top Blocker

## Recommended Migration Order
Numbered list. Which workload should be migrated first and why. Justify based on
dependencies found in the subagent reports.

## What the Human Discovery Missed
Bullet list of findings the subagents surfaced that are NOT in the human-written
discovery document. If the subagents found nothing new, say so explicitly.

## Phase 1 Blockers (Consolidated)
De-duplicated list across all three workloads. Group by theme (credential, networking, filesystem, etc.).

## Phase 2 Optimisation Roadmap
Grouped by theme. What to tackle after the lift-and-shift is stable.

## Coordinator Confidence Note
One paragraph. Where is this analysis solid? Where might it be wrong because the subagents
only saw source code, not runtime behaviour?"""


# ─── Bedrock helpers ──────────────────────────────────────────────────────────

def make_bedrock_client(profile: str, region: str):
    from botocore.config import Config
    session = boto3.Session(profile_name=profile, region_name=region)
    return session.client(
        "bedrock-runtime",
        config=Config(read_timeout=300, connect_timeout=10, retries={"max_attempts": 2}),
    )


def call_claude(client, prompt: str, system: str, model: str, max_tokens: int = 4096) -> str:
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": prompt}],
    }
    response = client.invoke_model(
        modelId=model,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(body),
    )
    result = json.loads(response["body"].read())
    return result["content"][0]["text"]


# ─── File loading ─────────────────────────────────────────────────────────────

def load_workload_files(workload_key: str) -> str:
    spec = WORKLOADS[workload_key]
    parts = []
    for rel_path in spec["files"]:
        full_path = REPO_ROOT / rel_path
        if full_path.exists():
            content = full_path.read_text(encoding="utf-8")
            parts.append(f"### {rel_path}\n```\n{content}\n```")
        else:
            parts.append(f"### {rel_path}\n[FILE NOT FOUND]")
    return "\n\n".join(parts)


def load_human_discovery() -> str:
    path = REPO_ROOT / "discovery" / "current-state.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return "[Human discovery document not found]"


# ─── Subagent ─────────────────────────────────────────────────────────────────

def run_subagent(workload_key: str, client, model: str) -> dict:
    """
    Runs one subagent for the given workload.
    Context is passed EXPLICITLY in the prompt — this subagent has no shared state.
    """
    spec = WORKLOADS[workload_key]
    print(f"  [subagent:{workload_key}] Reading files...")
    file_contents = load_workload_files(workload_key)

    prompt = SUBAGENT_PROMPT.format(
        workload_key=workload_key,
        workload_name=spec["name"],
        workload_description=spec["description"],
        other_workloads=spec["other_workloads"],
        file_contents=file_contents,
    )

    print(f"  [subagent:{workload_key}] Calling Claude on Bedrock...")
    raw = call_claude(client, prompt, SUBAGENT_SYSTEM, model, max_tokens=3000)

    # Strip markdown fences if the model wrapped the JSON
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        result = json.loads(raw)
        print(f"  [subagent:{workload_key}] Done — risk={result.get('migration_risk','?')}, "
              f"score={result.get('cloud_readiness_score','?')}/10")
        return result
    except json.JSONDecodeError as e:
        print(f"  [subagent:{workload_key}] WARNING: JSON parse failed ({e}). Returning raw text.")
        return {"workload": workload_key, "raw": raw, "parse_error": str(e)}


# ─── Coordinator ──────────────────────────────────────────────────────────────

def run_coordinator(subagent_results: list[dict], client, model: str) -> str:
    subagent_reports = "\n\n".join(
        f"### {r.get('workload', 'unknown').upper()} SUBAGENT REPORT\n"
        + json.dumps(r, indent=2)
        for r in subagent_results
    )
    human_discovery = load_human_discovery()

    prompt = COORDINATOR_PROMPT.format(
        subagent_reports=subagent_reports,
        human_discovery=human_discovery,
    )

    print("\n  [coordinator] Synthesising cross-workload report...")
    return call_claude(client, prompt, COORDINATOR_SYSTEM, model, max_tokens=4096)


# ─── Report writer ────────────────────────────────────────────────────────────

def write_report(synthesis: str, subagent_results: list[dict], output_path: Path, model: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    header = f"""# Contoso Financial — Agentic Survey Report
*Generated: {ts}*
*Model: {model}*
*Subagents: {len(subagent_results)} (webapp, batch, reporting-db) — run in parallel*

---

{synthesis}

---

## Raw Subagent Outputs

<details>
<summary>Click to expand raw subagent JSON (coordinator input)</summary>

```json
{json.dumps(subagent_results, indent=2)}
```

</details>
"""
    output_path.write_text(header, encoding="utf-8")
    print(f"\n  Report written to: {output_path}")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Contoso Financial — Agentic Survey (Challenge 9)")
    parser.add_argument("--profile", default=DEFAULT_PROFILE, help="AWS profile name")
    parser.add_argument("--region",  default=DEFAULT_REGION,  help="AWS region")
    parser.add_argument("--model",   default=DEFAULT_MODEL,   help="Bedrock model ID")
    parser.add_argument("--output",  default="survey-report.md", help="Output file name")
    args = parser.parse_args()

    output_path = AGENTS_DIR / args.output

    print("=" * 60)
    print("  Contoso Financial — The Survey (Challenge 9)")
    print("  Coordinator + 3 parallel subagents via Amazon Bedrock")
    print("=" * 60)
    print(f"  Profile : {args.profile}")
    print(f"  Region  : {args.region}")
    print(f"  Model   : {args.model}")
    print(f"  Output  : {output_path}")
    print()

    # Initialise Bedrock client
    try:
        client = make_bedrock_client(args.profile, args.region)
        # Warm-up check — validate credentials using the bedrock (not bedrock-runtime) client
        session = boto3.Session(profile_name=args.profile, region_name=args.region)
        bedrock_mgmt = session.client("bedrock")
        bedrock_mgmt.list_foundation_models(byProvider="Anthropic")
        print("  Bedrock connection: OK\n")
    except ProfileNotFound:
        print(f"ERROR: AWS profile '{args.profile}' not found.")
        print("  Available profiles: " + ", ".join(boto3.Session().available_profiles))
        sys.exit(1)
    except NoCredentialsError:
        print("ERROR: No AWS credentials found. Check your profile configuration.")
        sys.exit(1)
    except ClientError as e:
        print(f"ERROR: Bedrock client error: {e}")
        sys.exit(1)

    # ── Phase 1: Run 3 subagents in PARALLEL ──────────────────────────────────
    print("Phase 1: Running subagents in parallel...\n")
    workload_keys = list(WORKLOADS.keys())
    subagent_results = []
    errors = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(run_subagent, key, client, args.model): key
            for key in workload_keys
        }
        for future in concurrent.futures.as_completed(futures):
            key = futures[future]
            try:
                result = future.result()
                subagent_results.append(result)
            except Exception as e:
                print(f"  [subagent:{key}] FAILED: {e}")
                errors.append({"workload": key, "error": str(e)})

    if not subagent_results:
        print("\nERROR: All subagents failed. Cannot proceed with coordinator.")
        sys.exit(1)

    if errors:
        print(f"\nWARNING: {len(errors)} subagent(s) failed. Coordinator will work with partial data.")

    # Sort results consistently for the coordinator
    order = {k: i for i, k in enumerate(workload_keys)}
    subagent_results.sort(key=lambda r: order.get(r.get("workload", ""), 99))

    # ── Phase 2: Coordinator synthesises ─────────────────────────────────────
    print("\nPhase 2: Coordinator synthesising cross-workload report...")
    synthesis = run_coordinator(subagent_results, client, args.model)

    # ── Phase 3: Write report ─────────────────────────────────────────────────
    write_report(synthesis, subagent_results, output_path, args.model)

    print("\n" + "=" * 60)
    print("  Survey complete.")
    print(f"  Open: {output_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
