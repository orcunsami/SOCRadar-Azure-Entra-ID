#!/usr/bin/env bash
# =============================================================================
# SOCRadar Entra ID Integration — Test Environment Setup
# Creates test users, security group, and grants admin consent.
#
# Prerequisites:
#   - Azure CLI logged in with User Administrator + Cloud App Admin + Groups Admin
#   - OR logged in as Global Admin
# =============================================================================
set -euo pipefail

TENANT_DOMAIN="SOCRadarCyberIntelligenceIn.onmicrosoft.com"
APP_ID="b0afca82-a991-4fea-ad87-94ec348b2e68"
TEST_PASSWORD='SoCr@dar!Test2026#xQ'
GROUP_NAME="SOCRadar-Quarantine-Test"

echo "============================================================"
echo "  SOCRadar Entra ID — Test Environment Setup"
echo "============================================================"

# ---- Pre-flight ----
echo ""
echo "[1/5] Pre-flight checks..."
SIGNED_IN=$(az ad signed-in-user show --query userPrincipalName -o tsv 2>&1) || { echo "ERROR: Not logged in. Run: az login"; exit 1; }
echo "  Signed in as: $SIGNED_IN"

# ---- Admin Consent ----
echo ""
echo "[2/5] Granting admin consent for app registration..."
if az ad app permission admin-consent --id "$APP_ID" 2>/dev/null; then
    echo "  Admin consent granted."
else
    echo "  WARN: Admin consent failed — you may need Global Admin or Cloud App Admin role."
    echo "  Ask burak goger to run: az ad app permission admin-consent --id $APP_ID"
fi

# ---- Create Test Users ----
echo ""
echo "[3/5] Creating test users..."

create_user() {
    local DISPLAY="$1" MAIL_NICK="$2" UPN="$3"
    echo -n "  $UPN ... "
    if az ad user show --id "$UPN" &>/dev/null 2>&1; then
        USER_ID=$(az ad user show --id "$UPN" --query id -o tsv)
        echo "exists (id: ${USER_ID:0:8}...)"
    else
        USER_ID=$(az rest --method POST \
            --url "https://graph.microsoft.com/v1.0/users" \
            --headers "Content-Type=application/json" \
            --body "{
                \"accountEnabled\": true,
                \"displayName\": \"$DISPLAY\",
                \"mailNickname\": \"$MAIL_NICK\",
                \"userPrincipalName\": \"$UPN\",
                \"passwordProfile\": {
                    \"forceChangePasswordNextSignIn\": false,
                    \"password\": \"$TEST_PASSWORD\"
                }
            }" --query id -o tsv 2>&1) && echo "created (id: ${USER_ID:0:8}...)" || echo "FAILED: $USER_ID"
    fi
    echo "$USER_ID"
}

TEST1_ID=$(create_user "SOCRadar Test User 1" "socradar.test1" "socradar.test1@$TENANT_DOMAIN")
TEST2_ID=$(create_user "SOCRadar Test User 2" "socradar.test2" "socradar.test2@$TENANT_DOMAIN")
TEST3_ID=$(create_user "SOCRadar Test User 3" "socradar.test3" "socradar.test3@$TENANT_DOMAIN")

# ---- Create Security Group ----
echo ""
echo "[4/5] Creating security group..."
echo -n "  $GROUP_NAME ... "
GROUP_ID=$(az rest --method GET \
    --url "https://graph.microsoft.com/v1.0/groups?\$filter=displayName eq '$GROUP_NAME'&\$select=id" \
    --query "value[0].id" -o tsv 2>/dev/null)

if [ -n "$GROUP_ID" ] && [ "$GROUP_ID" != "null" ]; then
    echo "exists (id: ${GROUP_ID:0:8}...)"
else
    GROUP_ID=$(az rest --method POST \
        --url "https://graph.microsoft.com/v1.0/groups" \
        --headers "Content-Type=application/json" \
        --body "{
            \"displayName\": \"$GROUP_NAME\",
            \"description\": \"Quarantine group for SOCRadar Entra ID integration testing\",
            \"mailEnabled\": false,
            \"mailNickname\": \"socradar-quarantine-test\",
            \"securityEnabled\": true,
            \"groupTypes\": []
        }" --query id -o tsv 2>&1) && echo "created (id: ${GROUP_ID:0:8}...)" || echo "FAILED: $GROUP_ID"
fi

# Add test3 to group (for remove test)
if [ -n "$TEST3_ID" ] && [ -n "$GROUP_ID" ]; then
    echo -n "  Adding test3 to group ... "
    az rest --method POST \
        --url "https://graph.microsoft.com/v1.0/groups/$GROUP_ID/members/\$ref" \
        --headers "Content-Type=application/json" \
        --body "{\"@odata.id\": \"https://graph.microsoft.com/v1.0/directoryObjects/$TEST3_ID\"}" \
        2>/dev/null && echo "ok" || echo "already member or failed"
fi

# ---- Save Config ----
echo ""
echo "[5/5] Saving test config..."

cat > "$(dirname "$0")/test_env.config" << EOF
# Auto-generated test environment config
# $(date -u +%Y-%m-%dT%H:%M:%SZ)

TENANT_DOMAIN=$TENANT_DOMAIN
APP_ID=$APP_ID
TEST_PASSWORD=$TEST_PASSWORD

TEST1_UPN=socradar.test1@$TENANT_DOMAIN
TEST1_ID=$TEST1_ID
TEST2_UPN=socradar.test2@$TENANT_DOMAIN
TEST2_ID=$TEST2_ID
TEST3_UPN=socradar.test3@$TENANT_DOMAIN
TEST3_ID=$TEST3_ID

GROUP_NAME=$GROUP_NAME
GROUP_ID=$GROUP_ID
EOF

echo "  Saved: scripts/test_env.config"

echo ""
echo "============================================================"
echo "  TEST ENVIRONMENT READY"
echo "============================================================"
echo ""
echo "  Users:"
echo "    test1: socradar.test1@$TENANT_DOMAIN (normal active)"
echo "    test2: socradar.test2@$TENANT_DOMAIN (will be disabled)"
echo "    test3: socradar.test3@$TENANT_DOMAIN (in quarantine group)"
echo ""
echo "  Group: $GROUP_NAME ($GROUP_ID)"
echo "  Password: $TEST_PASSWORD"
echo ""
echo "  Next: python3 scripts/test_actions.py"
echo "============================================================"
