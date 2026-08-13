#!/usr/bin/env bash
# =============================================================================
# SOCRadar Entra ID — E2E Test Runner
# Wrapper for e2e_test.py with common configurations
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

usage() {
    echo "Usage: $0 [full|dry-run|unit|quick]"
    echo ""
    echo "  full     Full E2E with live API calls and LAW writes (5-month lookback)"
    echo "  dry-run  API connectivity only, no writes"
    echo "  unit     Unit tests only (no API calls needed)"
    echo "  quick    Quick API check with 7-day lookback"
    echo ""
    exit 0
}

MODE="${1:-full}"

case "$MODE" in
    full)
        echo "Running FULL E2E test (5-month lookback)..."
        python3 "$SCRIPT_DIR/e2e_test.py" --lookback-days 150
        ;;
    dry-run)
        echo "Running DRY-RUN test..."
        python3 "$SCRIPT_DIR/e2e_test.py" --dry-run --lookback-days 150
        ;;
    unit)
        echo "Running UNIT tests only..."
        python3 "$SCRIPT_DIR/e2e_test.py" --dry-run --lookback-days 1 --source botnet
        ;;
    quick)
        echo "Running QUICK test (7-day lookback)..."
        python3 "$SCRIPT_DIR/e2e_test.py" --lookback-days 7
        ;;
    help|-h|--help)
        usage
        ;;
    *)
        echo "Unknown mode: $MODE"
        usage
        ;;
esac
