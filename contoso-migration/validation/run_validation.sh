#!/usr/bin/env bash
# Contoso Financial — Migration Validation Runner
# Runs the full validation suite against the Docker Compose stack.
# Exit code 0 = migration succeeded. Any non-zero = migration is NOT complete.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_DIR="$(dirname "$SCRIPT_DIR")"

# Colours
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

step() { echo -e "\n${YELLOW}▶ $1${NC}"; }
pass() { echo -e "${GREEN}✓ $1${NC}"; }
fail() { echo -e "${RED}✗ $1${NC}"; }

step "Checking Docker Compose stack is running..."
if ! docker compose -f "$COMPOSE_DIR/docker-compose.yml" ps --services --filter "status=running" | grep -q "webapp"; then
  fail "Webapp container is not running. Run: docker compose up -d"
  exit 1
fi
pass "Docker Compose stack is up"

step "Waiting for webapp health check..."
for i in $(seq 1 30); do
  if curl -sf http://localhost:3000/health > /dev/null 2>&1; then
    pass "Webapp is healthy"
    break
  fi
  if [ $i -eq 30 ]; then
    fail "Webapp did not become healthy within 30 seconds"
    exit 1
  fi
  sleep 1
done

step "Installing Python dependencies..."
pip install -q -r "$SCRIPT_DIR/requirements.txt"

step "Running smoke tests..."
pytest "$SCRIPT_DIR" -v -m smoke --tb=short -q
pass "Smoke tests passed"

step "Running contract tests..."
pytest "$SCRIPT_DIR" -v -m contract --tb=short -q
pass "Contract tests passed"

step "Running discovery-finding tests (migration blocker checks)..."
pytest "$SCRIPT_DIR" -v -m discovery --tb=short
pass "Discovery finding tests passed — all five on-prem blockers resolved"

step "Running data integrity tests..."
pytest "$SCRIPT_DIR" -v -m integrity --tb=short
pass "Data integrity tests passed"

echo -e "\n${GREEN}════════════════════════════════════════${NC}"
echo -e "${GREEN}  MIGRATION VALIDATION: PASSED${NC}"
echo -e "${GREEN}  All checks green. Migration succeeded.${NC}"
echo -e "${GREEN}════════════════════════════════════════${NC}\n"
