#!/usr/bin/env bash
# Hit all 3 SOCRadar endpoints in both environments and save responses.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
START_DATE="${1:-2024-01-01}"
PAGE_SIZE="${2:-10}"

echo "============================================================"
echo "  SOCRadar API Discovery — 3 sources × 2 envs = 6 calls"
echo "  startDate: $START_DATE  | limit: $PAGE_SIZE"
echo "============================================================"
echo ""

for env in preprod platform; do
    for source in botnet pii vip; do
        bash "$SCRIPT_DIR/test_endpoint.sh" "$env" "$source" "$START_DATE" "$PAGE_SIZE" || echo "  WARN: $env/$source failed"
    done
done

echo "============================================================"
echo "  Done. Responses saved to: $SCRIPT_DIR/responses/"
echo "  Analyze with: python3 $SCRIPT_DIR/analyze_response.py"
echo "============================================================"
