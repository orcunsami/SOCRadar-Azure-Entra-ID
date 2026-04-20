#!/usr/bin/env bash
# =============================================================================
# SOCRadar Entra ID Integration — Full Deployment Script
# Deploys ARM template + Function App + Workbooks with 5-month lookback
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PRODUCTION_DIR="$SCRIPT_DIR/../production"
ARM_TEMPLATE="$PRODUCTION_DIR/azuredeploy.json"
WORKBOOKS_DIR="$PRODUCTION_DIR/Workbooks"

# ---- Load config from deploy.config or environment ----
CONFIG_FILE="${SCRIPT_DIR}/deploy.config"
if [[ -f "$CONFIG_FILE" ]]; then
    echo "[*] Loading config from $CONFIG_FILE"
    # shellcheck source=/dev/null
    source "$CONFIG_FILE"
else
    echo "[!] No deploy.config found. Using environment variables."
    echo "    Copy deploy.config.example to deploy.config and fill in values."
fi

# ---- Required variables ----
: "${RESOURCE_GROUP:?RESOURCE_GROUP is required}"
: "${LOCATION:?LOCATION is required (e.g. northeurope)}"
: "${WORKSPACE_NAME:?WORKSPACE_NAME is required}"
: "${SOCRADAR_API_KEY:?SOCRADAR_API_KEY is required}"
: "${SOCRADAR_COMPANY_ID:?SOCRADAR_COMPANY_ID is required}"
# Entra ID identifiers (NO secret — auth is secretless via UAMI + FIC)
: "${ENTRA_TENANT_ID:?ENTRA_TENANT_ID is required}"
: "${ENTRA_CLIENT_ID:?ENTRA_CLIENT_ID is required}"

# ---- Optional variables with defaults ----
WORKSPACE_LOCATION="${WORKSPACE_LOCATION:-$LOCATION}"
WORKSPACE_RESOURCE_GROUP="${WORKSPACE_RESOURCE_GROUP:-}"
SECURITY_GROUP_ID="${SECURITY_GROUP_ID:-}"

# Source toggles
ENABLE_BOTNET="${ENABLE_BOTNET:-true}"
ENABLE_PII="${ENABLE_PII:-true}"
ENABLE_VIP="${ENABLE_VIP:-false}"

# Action toggles
ENABLE_USER_LOOKUP="${ENABLE_USER_LOOKUP:-true}"
ENABLE_REVOKE_SESSION="${ENABLE_REVOKE_SESSION:-true}"
ENABLE_ADD_TO_GROUP="${ENABLE_ADD_TO_GROUP:-true}"
ENABLE_REMOVE_FROM_GROUP="${ENABLE_REMOVE_FROM_GROUP:-false}"
ENABLE_PASSWORD_CHANGE="${ENABLE_PASSWORD_CHANGE:-false}"
ENABLE_DISABLE_ACCOUNT="${ENABLE_DISABLE_ACCOUNT:-false}"
ENABLE_ENABLE_ACCOUNT="${ENABLE_ENABLE_ACCOUNT:-false}"
ENABLE_CONFIRM_RISKY="${ENABLE_CONFIRM_RISKY:-false}"
ENABLE_FORCE_MFA_REREGISTRATION="${ENABLE_FORCE_MFA_REREGISTRATION:-false}"
ENABLE_ROPC="${ENABLE_ROPC:-false}"
ENABLE_CREATE_INCIDENT="${ENABLE_CREATE_INCIDENT:-false}"
ENABLE_RESOLVE_ALARM="${ENABLE_RESOLVE_ALARM:-false}"
ENABLE_LOG_PLAINTEXT="${ENABLE_LOG_PLAINTEXT:-false}"

# Schedule & lookback
POLLING_INTERVAL_HOURS="${POLLING_INTERVAL_HOURS:-6}"
# 5 months = ~150 days = 216000 minutes
INITIAL_LOOKBACK_MINUTES="${INITIAL_LOOKBACK_MINUTES:-216000}"

echo "============================================================"
echo "  SOCRadar Entra ID Integration — Full Deployment"
echo "============================================================"
echo ""
echo "  Resource Group:       $RESOURCE_GROUP"
echo "  Location:             $LOCATION"
echo "  Workspace:            $WORKSPACE_NAME"
echo "  Company ID:           $SOCRADAR_COMPANY_ID"
echo "  Lookback:             $INITIAL_LOOKBACK_MINUTES min (~$((INITIAL_LOOKBACK_MINUTES / 1440)) days)"
echo "  Polling:              Every $POLLING_INTERVAL_HOURS hours"
echo ""
echo "  Sources:  Botnet=$ENABLE_BOTNET  PII=$ENABLE_PII  VIP=$ENABLE_VIP"
echo "  Lookup:   UserLookup=$ENABLE_USER_LOOKUP"
echo "  Actions:  Revoke=$ENABLE_REVOKE_SESSION  Group=$ENABLE_ADD_TO_GROUP"
echo "            RemoveGroup=$ENABLE_REMOVE_FROM_GROUP  PwChange=$ENABLE_PASSWORD_CHANGE"
echo "            Disable=$ENABLE_DISABLE_ACCOUNT  Enable=$ENABLE_ENABLE_ACCOUNT"
echo "            Risky=$ENABLE_CONFIRM_RISKY  ROPC=$ENABLE_ROPC"
echo "            Incident=$ENABLE_CREATE_INCIDENT  ResolveAlarm=$ENABLE_RESOLVE_ALARM"
echo ""

# ---- Pre-flight checks ----
echo "[1/6] Pre-flight checks..."

if ! command -v az &>/dev/null; then
    echo "ERROR: Azure CLI (az) not found. Install: https://aka.ms/installazurecli"
    exit 1
fi

# Check login
if ! az account show &>/dev/null 2>&1; then
    echo "ERROR: Not logged in. Run: az login"
    exit 1
fi

SUBSCRIPTION=$(az account show --query id -o tsv)
echo "  Subscription: $SUBSCRIPTION"

# Verify workspace exists
echo "  Verifying workspace '$WORKSPACE_NAME'..."
WS_RG="${WORKSPACE_RESOURCE_GROUP:-$RESOURCE_GROUP}"
if ! az monitor log-analytics workspace show \
    --resource-group "$WS_RG" \
    --workspace-name "$WORKSPACE_NAME" &>/dev/null 2>&1; then
    echo "ERROR: Workspace '$WORKSPACE_NAME' not found in RG '$WS_RG'"
    exit 1
fi
echo "  Workspace verified."

# ---- Create Resource Group if needed ----
echo ""
echo "[2/6] Resource Group..."
if az group show --name "$RESOURCE_GROUP" &>/dev/null 2>&1; then
    echo "  Resource group '$RESOURCE_GROUP' exists."
else
    echo "  Creating resource group '$RESOURCE_GROUP' in '$LOCATION'..."
    az group create --name "$RESOURCE_GROUP" --location "$LOCATION" -o none
    echo "  Created."
fi

# ---- Deploy ARM template ----
echo ""
echo "[3/6] Deploying ARM template..."
echo "  Template: $ARM_TEMPLATE"
echo "  Initial lookback: $INITIAL_LOOKBACK_MINUTES minutes (~$((INITIAL_LOOKBACK_MINUTES / 1440)) days / ~$((INITIAL_LOOKBACK_MINUTES / 43200)) months)"

DEPLOYMENT_NAME="socradar-entraid-$(date +%Y%m%d-%H%M%S)"

DEPLOY_OUTPUT=$(az deployment group create \
    --resource-group "$RESOURCE_GROUP" \
    --name "$DEPLOYMENT_NAME" \
    --template-file "$ARM_TEMPLATE" \
    --parameters \
        WorkspaceName="$WORKSPACE_NAME" \
        WorkspaceLocation="$WORKSPACE_LOCATION" \
        WorkspaceResourceGroup="$WORKSPACE_RESOURCE_GROUP" \
        SocradarApiKey="$SOCRADAR_API_KEY" \
        SocradarCompanyId="$SOCRADAR_COMPANY_ID" \
        EntraIdTenantId="$ENTRA_TENANT_ID" \
        EntraIdClientId="$ENTRA_CLIENT_ID" \
        SecurityGroupId="$SECURITY_GROUP_ID" \
        EnableBotnetSource="$ENABLE_BOTNET" \
        EnablePiiSource="$ENABLE_PII" \
        EnableVipSource="$ENABLE_VIP" \
        EnableUserLookup="$ENABLE_USER_LOOKUP" \
        EnableRevokeSession="$ENABLE_REVOKE_SESSION" \
        EnableAddToGroup="$ENABLE_ADD_TO_GROUP" \
        EnableRemoveFromGroup="$ENABLE_REMOVE_FROM_GROUP" \
        EnablePasswordChange="$ENABLE_PASSWORD_CHANGE" \
        EnableDisableAccount="$ENABLE_DISABLE_ACCOUNT" \
        EnableEnableAccount="$ENABLE_ENABLE_ACCOUNT" \
        EnableConfirmRisky="$ENABLE_CONFIRM_RISKY" \
        EnableForceMfaReregistration="$ENABLE_FORCE_MFA_REREGISTRATION" \
        EnableROPC="$ENABLE_ROPC" \
        EnableCreateIncident="$ENABLE_CREATE_INCIDENT" \
        EnableResolveAlarm="$ENABLE_RESOLVE_ALARM" \
        EnableLogPlaintextPassword="$ENABLE_LOG_PLAINTEXT" \
        PollingIntervalHours="$POLLING_INTERVAL_HOURS" \
        InitialLookbackMinutes="$INITIAL_LOOKBACK_MINUTES" \
        InitialStartDate="${INITIAL_START_DATE:-}" \
    --query "properties.outputs" -o json 2>&1)

echo "$DEPLOY_OUTPUT" | python3 -m json.tool 2>/dev/null || echo "$DEPLOY_OUTPUT"

FUNCTION_APP_NAME=$(echo "$DEPLOY_OUTPUT" | python3 -c "import sys,json; print(json.load(sys.stdin)['functionAppName']['value'])" 2>/dev/null || echo "")
STORAGE_ACCOUNT=$(echo "$DEPLOY_OUTPUT" | python3 -c "import sys,json; print(json.load(sys.stdin)['storageAccountName']['value'])" 2>/dev/null || echo "")
POLLING_SCHEDULE=$(echo "$DEPLOY_OUTPUT" | python3 -c "import sys,json; print(json.load(sys.stdin)['pollingSchedule']['value'])" 2>/dev/null || echo "")

echo ""
echo "  Function App:     $FUNCTION_APP_NAME"
echo "  Storage Account:  $STORAGE_ACCOUNT"
echo "  Polling Schedule: $POLLING_SCHEDULE"

# ---- Wait for Function App to be ready ----
echo ""
echo "[4/6] Waiting for Function App to be ready..."
for i in {1..12}; do
    STATE=$(az functionapp show --name "$FUNCTION_APP_NAME" --resource-group "$RESOURCE_GROUP" --query "state" -o tsv 2>/dev/null || echo "unknown")
    if [[ "$STATE" == "Running" ]]; then
        echo "  Function App is running."
        break
    fi
    echo "  State: $STATE (attempt $i/12, waiting 10s...)"
    sleep 10
done

# ---- Deploy Workbooks ----
echo ""
echo "[5/6] Deploying Workbooks..."

WORKSPACE_ID=$(az monitor log-analytics workspace show \
    --resource-group "$WS_RG" \
    --workspace-name "$WORKSPACE_NAME" \
    --query "id" -o tsv)

deploy_workbook() {
    local wb_file="$1"
    local wb_name="$2"
    local wb_display="$3"

    if [[ ! -f "$wb_file" ]]; then
        echo "  SKIP: $wb_file not found"
        return 1
    fi

    local wb_id
    wb_id=$(python3 -c "import uuid; print(str(uuid.uuid5(uuid.NAMESPACE_DNS, '$wb_name')))")
    local wb_resource_id="/subscriptions/$SUBSCRIPTION/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Insights/workbooks/$wb_id"

    local serialized
    serialized=$(python3 -c "
import json, sys
with open('$wb_file') as f:
    data = json.load(f)
# Replace placeholder resource IDs
raw = json.dumps(data)
raw = raw.replace('{Subscription}', '$SUBSCRIPTION')
raw = raw.replace('{ResourceGroup}', '$WS_RG')
raw = raw.replace('{Workspace}', '$WORKSPACE_NAME')
print(raw)
")

    az workbook create \
        --resource-group "$RESOURCE_GROUP" \
        --name "$wb_id" \
        --display-name "$wb_display" \
        --category "sentinel" \
        --kind "shared" \
        --source-id "$WORKSPACE_ID" \
        --serialized-data "$serialized" \
        -o none 2>/dev/null && echo "  OK: $wb_display" || echo "  WARN: $wb_display (may already exist, updating...)" && \
    az workbook update \
        --resource-group "$RESOURCE_GROUP" \
        --name "$wb_id" \
        --display-name "$wb_display" \
        --category "sentinel" \
        --kind "shared" \
        --source-id "$WORKSPACE_ID" \
        --serialized-data "$serialized" \
        -o none 2>/dev/null || true
}

deploy_workbook "$WORKBOOKS_DIR/SOCRadar-EntraID-Botnet-Workbook.json"   "socradar-entraid-botnet"   "SOCRadar Entra ID — Botnet Data"
deploy_workbook "$WORKBOOKS_DIR/SOCRadar-EntraID-PII-Workbook.json"      "socradar-entraid-pii"      "SOCRadar Entra ID — PII Exposure"
deploy_workbook "$WORKBOOKS_DIR/SOCRadar-EntraID-VIP-Workbook.json"      "socradar-entraid-vip"      "SOCRadar Entra ID — VIP Protection"
deploy_workbook "$WORKBOOKS_DIR/SOCRadar-EntraID-Combined-Workbook.json" "socradar-entraid-combined" "SOCRadar Entra ID — Combined Dashboard"

# ---- Update FIC (Federated Identity Credential) ----
echo ""
echo "[6/7] Updating Federated Identity Credential..."

UAMI_PRINCIPAL=$(az identity show --name "SOCRadar-EntraID-MI" --resource-group "$RESOURCE_GROUP" --query "principalId" -o tsv 2>/dev/null || echo "")
TENANT_ID_VAL=$(az account show --query tenantId -o tsv)

if [[ -z "$UAMI_PRINCIPAL" ]]; then
    echo "  WARN: Could not get UAMI principal ID — FIC not updated"
else
    EXISTING_FIC=$(az ad app federated-credential list --id "$ENTRA_CLIENT_ID" --query "[?name=='uami-federation'].subject | [0]" -o tsv 2>/dev/null || echo "")

    if [[ "$EXISTING_FIC" == "$UAMI_PRINCIPAL" ]]; then
        echo "  FIC already matches UAMI ($UAMI_PRINCIPAL) — no update needed"
    else
        if [[ -n "$EXISTING_FIC" ]]; then
            echo "  Deleting old FIC (subject=$EXISTING_FIC)..."
            az ad app federated-credential delete --id "$ENTRA_CLIENT_ID" --federated-credential-id "uami-federation" 2>/dev/null || true
        fi
        echo "  Creating FIC: UAMI $UAMI_PRINCIPAL → App Registration $ENTRA_CLIENT_ID"
        az ad app federated-credential create \
            --id "$ENTRA_CLIENT_ID" \
            --parameters "{
                \"name\": \"uami-federation\",
                \"issuer\": \"https://login.microsoftonline.com/$TENANT_ID_VAL/v2.0\",
                \"subject\": \"$UAMI_PRINCIPAL\",
                \"audiences\": [\"api://AzureADTokenExchange\"],
                \"description\": \"UAMI to App Registration federation for secretless Graph access\"
            }" -o none 2>/dev/null && echo "  FIC created successfully" || echo "  WARN: FIC creation failed — may need admin privileges"
    fi
fi

# ---- Verify Deployment ----
echo ""
echo "[7/7] Verifying deployment..."

# Check function app
echo "  Function App:"
az functionapp show --name "$FUNCTION_APP_NAME" --resource-group "$RESOURCE_GROUP" \
    --query "{name:name, state:state, runtime:siteConfig.linuxFxVersion, location:location}" -o table 2>/dev/null || echo "  WARN: Could not query function app"

# Check table storage
echo ""
echo "  Table Storage:"
az storage table list --account-name "$STORAGE_ACCOUNT" --auth-mode login -o table 2>/dev/null || echo "  WARN: Could not query table storage (role may still be propagating)"

# Check app settings count
echo ""
SETTINGS_COUNT=$(az functionapp config appsettings list --name "$FUNCTION_APP_NAME" --resource-group "$RESOURCE_GROUP" --query "length(@)" -o tsv 2>/dev/null || echo "?")
echo "  App Settings: $SETTINGS_COUNT configured"

echo ""
echo "============================================================"
echo "  DEPLOYMENT COMPLETE"
echo "============================================================"
echo ""
echo "  Function App:     $FUNCTION_APP_NAME"
echo "  Storage Account:  $STORAGE_ACCOUNT"
echo "  Schedule:         $POLLING_SCHEDULE"
echo "  Lookback:         $INITIAL_LOOKBACK_MINUTES min (~$((INITIAL_LOOKBACK_MINUTES / 1440)) days)"
echo ""
echo "  The function will trigger on startup and begin fetching"
echo "  ~5 months of SOCRadar data. Monitor via:"
echo ""
echo "    az functionapp log tail --name $FUNCTION_APP_NAME --resource-group $RESOURCE_GROUP"
echo ""
echo "  LAW Tables (visible after first run):"
echo "    SOCRadar_Botnet_CL"
echo "    SOCRadar_PII_CL"
echo "    SOCRadar_VIP_CL"
echo "    SOCRadar_EntraID_Audit_CL"
echo ""
echo "  Workbooks: Open Microsoft Sentinel > Workbooks > My Workbooks"
echo "============================================================"
