#!/bin/bash
# Run all SOCRadar API tests
# Results saved to tests/results/*.json

cd "$(dirname "$0")"

echo "========================================"
echo " SOCRadar Entra ID — API Tests"
echo "========================================"

PASS=0
FAIL=0

for test in botnet/test_botnet.py pii/test_pii.py vip/test_vip.py test_alarm_resolve.py test_identity_intelligence.py; do
    echo ""
    echo "--- Running $test ---"
    if python3 "$test"; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
    fi
    echo ""
    sleep 1  # rate limit
done

echo ""
echo "--- Edge-case + date-filter tests per source ---"
for src in botnet pii vip; do
    edge="$src/test_${src}_edge_cases.py"
    if [ -f "$edge" ]; then
        echo ""
        echo "--- Running $edge ---"
        if python3 "$edge"; then
            PASS=$((PASS + 1))
        else
            FAIL=$((FAIL + 1))
        fi
        sleep 1
    fi
done

echo "========================================"
echo " DONE: $PASS passed, $FAIL failed"
echo "========================================"
echo ""
echo "Per-source results:"
ls -la botnet/results/*.json pii/results/*.json vip/results/*.json results/*.json 2>/dev/null
