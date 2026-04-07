#!/usr/bin/env bash
# =============================================================================
# SOCRadar Entra ID — Workbook Deployment Script
# Deploys all 4 workbooks to Sentinel workspace
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKBOOKS_DIR="$SCRIPT_DIR/../production/Workbooks"

# Load config
CONFIG_FILE="${SCRIPT_DIR}/deploy.config"
if [[ -f "$CONFIG_FILE" ]]; then
    source "$CONFIG_FILE"
fi

: "${RESOURCE_GROUP:?RESOURCE_GROUP is required}"
: "${WORKSPACE_NAME:?WORKSPACE_NAME is required}"
WORKSPACE_RESOURCE_GROUP="${WORKSPACE_RESOURCE_GROUP:-$RESOURCE_GROUP}"

echo "============================================================"
echo "  SOCRadar Entra ID — Workbook Deployment"
echo "============================================================"
echo ""

# Get subscription and workspace ID
SUBSCRIPTION=$(az account show --query id -o tsv)
WORKSPACE_ID=$(az monitor log-analytics workspace show \
    --resource-group "$WORKSPACE_RESOURCE_GROUP" \
    --workspace-name "$WORKSPACE_NAME" \
    --query "id" -o tsv)

echo "  Subscription:  $SUBSCRIPTION"
echo "  Workspace:     $WORKSPACE_NAME"
echo "  Workspace ID:  $WORKSPACE_ID"
echo ""

WORKBOOKS=(
    "SOCRadar-EntraID-Botnet-Workbook.json|socradar-entraid-botnet|SOCRadar Entra ID — Botnet Data"
    "SOCRadar-EntraID-PII-Workbook.json|socradar-entraid-pii|SOCRadar Entra ID — PII Exposure"
    "SOCRadar-EntraID-VIP-Workbook.json|socradar-entraid-vip|SOCRadar Entra ID — VIP Protection"
    "SOCRadar-EntraID-Combined-Workbook.json|socradar-entraid-combined|SOCRadar Entra ID — Combined Dashboard"
)

DEPLOYED=0
FAILED=0

for wb_entry in "${WORKBOOKS[@]}"; do
    IFS='|' read -r wb_file wb_slug wb_display <<< "$wb_entry"
    wb_path="$WORKBOOKS_DIR/$wb_file"

    if [[ ! -f "$wb_path" ]]; then
        echo "  SKIP: $wb_file (not found)"
        continue
    fi

    # Deterministic UUID from slug
    wb_id=$(python3 -c "import uuid; print(str(uuid.uuid5(uuid.NAMESPACE_DNS, '$wb_slug')))")

    echo -n "  Deploying: $wb_display ... "

    # Replace placeholders in workbook JSON
    serialized=$(python3 -c "
import json
with open('$wb_path') as f:
    data = json.load(f)
raw = json.dumps(data)
raw = raw.replace('{Subscription}', '$SUBSCRIPTION')
raw = raw.replace('{ResourceGroup}', '$WORKSPACE_RESOURCE_GROUP')
raw = raw.replace('{Workspace}', '$WORKSPACE_NAME')
print(raw)
")

    # Try create, fall back to update
    if az workbook create \
        --resource-group "$RESOURCE_GROUP" \
        --name "$wb_id" \
        --display-name "$wb_display" \
        --category "sentinel" \
        --kind "shared" \
        --source-id "$WORKSPACE_ID" \
        --serialized-data "$serialized" \
        -o none 2>/dev/null; then
        echo "CREATED"
        DEPLOYED=$((DEPLOYED + 1))
    elif az workbook update \
        --resource-group "$RESOURCE_GROUP" \
        --name "$wb_id" \
        --display-name "$wb_display" \
        --category "sentinel" \
        --kind "shared" \
        --source-id "$WORKSPACE_ID" \
        --serialized-data "$serialized" \
        -o none 2>/dev/null; then
        echo "UPDATED"
        DEPLOYED=$((DEPLOYED + 1))
    else
        echo "FAILED"
        FAILED=$((FAILED + 1))
    fi
done

echo ""
echo "============================================================"
echo "  Workbooks: $DEPLOYED deployed, $FAILED failed"
echo ""
echo "  View in: Microsoft Sentinel > Workbooks > My Workbooks"
echo "============================================================"
