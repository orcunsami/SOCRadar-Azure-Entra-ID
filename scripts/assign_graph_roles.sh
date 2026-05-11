#!/usr/bin/env bash
# =============================================================================
# Assign Microsoft Graph application roles to the UAMI service principal.
# Run ONCE after ARM deployment. Requires admin privileges.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/deploy.config"
if [[ -f "$CONFIG_FILE" ]]; then
    echo "[*] Loading config from $CONFIG_FILE"
    source "$CONFIG_FILE"
fi

: "${RESOURCE_GROUP:?RESOURCE_GROUP is required}"

UAMI_NAME="SOCRadar-EntraID-MI"

echo "============================================================"
echo "  Assign Graph Roles to Managed Identity"
echo "============================================================"

# Get UAMI principal ID
MI_PRINCIPAL_ID=$(az identity show \
    --name "$UAMI_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query "principalId" -o tsv 2>/dev/null)

if [[ -z "$MI_PRINCIPAL_ID" ]]; then
    echo "ERROR: UAMI '$UAMI_NAME' not found in RG '$RESOURCE_GROUP'"
    exit 1
fi
echo "  UAMI principal: $MI_PRINCIPAL_ID"

# Microsoft Graph well-known service principal
GRAPH_APP_ID="00000003-0000-0000-c000-000000000000"
GRAPH_SP_ID=$(az ad sp show --id "$GRAPH_APP_ID" --query "id" -o tsv)
echo "  Graph SP:        $GRAPH_SP_ID"

# Roles to assign — only the ones matching enabled toggles
# Customer should uncomment/add roles matching their enabled features
ROLES=(
    "User.Read.All"
    "User.RevokeSessions.All"
    "GroupMember.ReadWrite.All"
    "User-PasswordProfile.ReadWrite.All"
    "User.EnableDisableAccount.All"
    "IdentityRiskyUser.ReadWrite.All"
    "UserAuthenticationMethod.ReadWrite.All"
)

echo ""
echo "  Assigning ${#ROLES[@]} Graph roles..."
echo ""

for ROLE_VALUE in "${ROLES[@]}"; do
    ROLE_ID=$(az ad sp show --id "$GRAPH_APP_ID" \
        --query "appRoles[?value=='$ROLE_VALUE'].id | [0]" -o tsv 2>/dev/null)

    if [[ -z "$ROLE_ID" ]]; then
        echo "  SKIP: $ROLE_VALUE (role not found in Graph SP)"
        continue
    fi

    # Check if already assigned
    EXISTING=$(az rest --method GET \
        --url "https://graph.microsoft.com/v1.0/servicePrincipals/$GRAPH_SP_ID/appRoleAssignedTo?\$filter=principalId eq $MI_PRINCIPAL_ID and appRoleId eq $ROLE_ID" \
        --query "value | length(@)" -o tsv 2>/dev/null || echo "0")

    if [[ "$EXISTING" -gt 0 ]]; then
        echo "  OK:   $ROLE_VALUE (already assigned)"
        continue
    fi

    az rest --method POST \
        --url "https://graph.microsoft.com/v1.0/servicePrincipals/$GRAPH_SP_ID/appRoleAssignedTo" \
        --body "{
            \"principalId\": \"$MI_PRINCIPAL_ID\",
            \"resourceId\": \"$GRAPH_SP_ID\",
            \"appRoleId\": \"$ROLE_ID\"
        }" -o none 2>/dev/null && echo "  DONE: $ROLE_VALUE" || echo "  FAIL: $ROLE_VALUE (need admin privileges)"
done

echo ""
echo "============================================================"
echo "  Graph role assignment complete."
echo "  Verify: az rest --method GET --url"
echo "    'https://graph.microsoft.com/v1.0/servicePrincipals/${MI_PRINCIPAL_ID}/appRoleAssignments'"
echo "============================================================"
