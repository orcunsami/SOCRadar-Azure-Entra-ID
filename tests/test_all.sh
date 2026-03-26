#!/bin/bash
# Run all SOCRadar API tests
# Results saved to tests/results/*.json

cd "$(dirname "$0")"

echo "========================================"
echo " SOCRadar Entra ID — API Tests"
echo "========================================"

PASS=0
FAIL=0

for test in test_botnet_data.py test_pii_exposure.py test_vip_protection.py test_identity_intelligence.py; do
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

echo "========================================"
echo " DONE: $PASS passed, $FAIL failed"
echo "========================================"
echo ""
echo "Results:"
ls -la results/*.json 2>/dev/null
