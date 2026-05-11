#!/usr/bin/env bash
# =============================================================================
# SOCRadar Entra ID — Clean Reset
# Deletes all deployed resources for a fresh start
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/deploy.config"

if [[ -f "$CONFIG_FILE" ]]; then
    source "$CONFIG_FILE"
fi

: "${RESOURCE_GROUP:?RESOURCE_GROUP is required}"

echo "============================================================"
echo "  SOCRadar Entra ID — Clean Reset"
echo "============================================================"
echo ""
echo "  This will delete ALL resources in: $RESOURCE_GROUP"
echo ""

# List what will be deleted
echo "  Resources in $RESOURCE_GROUP:"
az resource list --resource-group "$RESOURCE_GROUP" --query "[].{Name:name, Type:type}" -o table 2>/dev/null || echo "  (could not list resources)"

echo ""
read -r -p "  Are you sure? Type 'yes' to confirm: " CONFIRM
if [[ "$CONFIRM" != "yes" ]]; then
    echo "  Aborted."
    exit 0
fi

echo ""
echo "  Deleting resource group '$RESOURCE_GROUP'..."
az group delete --name "$RESOURCE_GROUP" --yes --no-wait

echo ""
echo "  Resource group deletion initiated (async)."
echo "  Monitor: az group show --name $RESOURCE_GROUP"
echo "============================================================"
