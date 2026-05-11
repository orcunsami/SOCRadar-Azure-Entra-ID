#!/usr/bin/env bash
# =============================================================================
# SOCRadar Entra ID Integration — Test Environment Cleanup
# Deletes test users and security group created by setup_test_env.sh
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG="$SCRIPT_DIR/test_env.config"

if [[ ! -f "$CONFIG" ]]; then
    echo "ERROR: test_env.config not found. Run setup_test_env.sh first."
    exit 1
fi

source "$CONFIG"

echo "============================================================"
echo "  SOCRadar Entra ID — Test Environment Cleanup"
echo "============================================================"
echo ""
echo "  Will delete:"
echo "    - User: $TEST1_UPN"
echo "    - User: $TEST2_UPN"
echo "    - User: $TEST3_UPN"
echo "    - Group: $GROUP_NAME"
echo ""
read -p "  Type 'yes' to confirm: " CONFIRM
if [[ "$CONFIRM" != "yes" ]]; then
    echo "Aborted."
    exit 0
fi

echo ""

# Delete users
for UPN in "$TEST1_UPN" "$TEST2_UPN" "$TEST3_UPN"; do
    echo -n "  Deleting $UPN ... "
    az ad user delete --id "$UPN" 2>/dev/null && echo "ok" || echo "not found or failed"
done

# Delete group
echo -n "  Deleting group $GROUP_NAME ... "
if [ -n "$GROUP_ID" ]; then
    az rest --method DELETE --url "https://graph.microsoft.com/v1.0/groups/$GROUP_ID" 2>/dev/null && echo "ok" || echo "not found or failed"
else
    echo "no GROUP_ID"
fi

# Remove config
rm -f "$CONFIG"
echo ""
echo "  Cleanup complete. test_env.config removed."
echo "============================================================"
