#!/usr/bin/env bash
# =============================================================================
# SOCRadar Entra ID — Post-Deployment Validation
# Verifies all deployed resources are healthy and configured correctly
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/deploy.config"

if [[ -f "$CONFIG_FILE" ]]; then
    source "$CONFIG_FILE"
fi

: "${RESOURCE_GROUP:?RESOURCE_GROUP is required}"
: "${WORKSPACE_NAME:?WORKSPACE_NAME is required}"
WORKSPACE_RESOURCE_GROUP="${WORKSPACE_RESOURCE_GROUP:-$RESOURCE_GROUP}"

PASS=0
FAIL=0
WARN=0

pass() { echo "  ✓ $1"; PASS=$((PASS + 1)); }
fail() { echo "  ✗ $1"; FAIL=$((FAIL + 1)); }
warn() { echo "  ! $1"; WARN=$((WARN + 1)); }

echo "============================================================"
echo "  SOCRadar Entra ID — Post-Deployment Validation"
echo "============================================================"
echo ""

# ---- 1. Azure CLI & Login ----
echo "[1/8] Azure CLI..."
if command -v az &>/dev/null; then
    AZ_VERSION=$(az version --query '"azure-cli"' -o tsv 2>/dev/null || echo "?")
    pass "Azure CLI installed (v$AZ_VERSION)"
else
    fail "Azure CLI not found"
fi

if az account show &>/dev/null 2>&1; then
    SUB=$(az account show --query "{name:name, id:id}" -o tsv 2>/dev/null)
    pass "Logged in: $SUB"
else
    fail "Not logged in to Azure"
fi

# ---- 2. Resource Group ----
echo ""
echo "[2/8] Resource Group..."
if az group show --name "$RESOURCE_GROUP" &>/dev/null 2>&1; then
    LOCATION=$(az group show --name "$RESOURCE_GROUP" --query location -o tsv)
    pass "Resource group exists: $RESOURCE_GROUP ($LOCATION)"
else
    fail "Resource group not found: $RESOURCE_GROUP"
fi

# ---- 3. Function App ----
echo ""
echo "[3/8] Function App..."
FA_NAME=$(az functionapp list --resource-group "$RESOURCE_GROUP" --query "[?contains(name, 'socradar-entraid')].name" -o tsv 2>/dev/null | head -1)

if [[ -n "$FA_NAME" ]]; then
    pass "Function App found: $FA_NAME"

    FA_STATE=$(az functionapp show --name "$FA_NAME" --resource-group "$RESOURCE_GROUP" --query "state" -o tsv 2>/dev/null)
    if [[ "$FA_STATE" == "Running" ]]; then
        pass "State: Running"
    else
        fail "State: $FA_STATE (expected Running)"
    fi

    FA_RUNTIME=$(az functionapp show --name "$FA_NAME" --resource-group "$RESOURCE_GROUP" --query "siteConfig.linuxFxVersion" -o tsv 2>/dev/null)
    if [[ "$FA_RUNTIME" == "Python|3.11" ]]; then
        pass "Runtime: $FA_RUNTIME"
    else
        warn "Runtime: $FA_RUNTIME (expected Python|3.11)"
    fi

    # Check key app settings
    echo ""
    echo "  App Settings check:"
    REQUIRED_SETTINGS=("SOCRADAR_API_KEY" "SOCRADAR_COMPANY_ID" "ENTRA_TENANT_ID" "ENTRA_CLIENT_ID" "WORKSPACE_ID" "WORKSPACE_KEY" "STORAGE_ACCOUNT_NAME" "POLLING_SCHEDULE" "INITIAL_LOOKBACK_MINUTES" "AZURE_CLIENT_ID")

    SETTINGS_JSON=$(az functionapp config appsettings list --name "$FA_NAME" --resource-group "$RESOURCE_GROUP" -o json 2>/dev/null || echo "[]")

    for setting in "${REQUIRED_SETTINGS[@]}"; do
        HAS_IT=$(echo "$SETTINGS_JSON" | python3 -c "import sys,json; items=json.load(sys.stdin); print('yes' if any(i['name']=='$setting' for i in items) else 'no')" 2>/dev/null || echo "?")
        if [[ "$HAS_IT" == "yes" ]]; then
            pass "  $setting: set"
        else
            fail "  $setting: MISSING"
        fi
    done

    # Check INITIAL_LOOKBACK_MINUTES value
    LOOKBACK_VAL=$(echo "$SETTINGS_JSON" | python3 -c "import sys,json; items=json.load(sys.stdin); vals=[i['value'] for i in items if i['name']=='INITIAL_LOOKBACK_MINUTES']; print(vals[0] if vals else '?')" 2>/dev/null || echo "?")
    if [[ "$LOOKBACK_VAL" == "216000" ]]; then
        pass "  Lookback: $LOOKBACK_VAL min (~150 days, ~5 months)"
    elif [[ "$LOOKBACK_VAL" != "?" ]]; then
        warn "  Lookback: $LOOKBACK_VAL min (expected 216000 for 5 months)"
    fi

    # Check source toggles
    echo ""
    echo "  Source toggles:"
    for toggle in "ENABLE_BOTNET_SOURCE" "ENABLE_PII_SOURCE" "ENABLE_VIP_SOURCE"; do
        VAL=$(echo "$SETTINGS_JSON" | python3 -c "import sys,json; items=json.load(sys.stdin); vals=[i['value'] for i in items if i['name']=='$toggle']; print(vals[0] if vals else '?')" 2>/dev/null || echo "?")
        echo "    $toggle = $VAL"
    done

    # Check action toggles
    echo ""
    echo "  Action toggles:"
    for toggle in "ENABLE_USER_LOOKUP" "ENABLE_REVOKE_SESSION" "ENABLE_ADD_TO_GROUP" "ENABLE_REMOVE_FROM_GROUP" "ENABLE_PASSWORD_CHANGE" "ENABLE_DISABLE_ACCOUNT" "ENABLE_ENABLE_ACCOUNT" "ENABLE_CONFIRM_RISKY" "ENABLE_FORCE_MFA_REREGISTRATION" "ENABLE_ROPC" "ENABLE_CREATE_INCIDENT" "ENABLE_RESOLVE_ALARM"; do
        VAL=$(echo "$SETTINGS_JSON" | python3 -c "import sys,json; items=json.load(sys.stdin); vals=[i['value'] for i in items if i['name']=='$toggle']; print(vals[0] if vals else '?')" 2>/dev/null || echo "?")
        echo "    $toggle = $VAL"
    done
else
    fail "No Function App found matching 'socradar-entraid' in $RESOURCE_GROUP"
fi

# ---- 4. Storage Account & Table ----
echo ""
echo "[4/8] Storage Account & Checkpoint Table..."
SA_NAME=$(az storage account list --resource-group "$RESOURCE_GROUP" --query "[?contains(name, 'srentraid')].name" -o tsv 2>/dev/null | head -1)

if [[ -n "$SA_NAME" ]]; then
    pass "Storage account found: $SA_NAME"

    TABLES=$(az storage table list --account-name "$SA_NAME" --auth-mode login -o tsv 2>/dev/null || echo "")
    if echo "$TABLES" | grep -q "EntraIDState"; then
        pass "EntraIDState table exists"
    else
        warn "EntraIDState table not found (will be created on first run)"
    fi
else
    fail "No storage account found matching 'srentraid'"
fi

# ---- 5. Managed Identity & Role Assignments ----
echo ""
echo "[5/8] Managed Identity..."
MI_ID=$(az identity show --name "SOCRadar-EntraID-MI" --resource-group "$RESOURCE_GROUP" --query "principalId" -o tsv 2>/dev/null || echo "")

if [[ -n "$MI_ID" ]]; then
    pass "Managed Identity found (principalId: ${MI_ID:0:8}...)"

    # Check role assignments
    ROLES=$(az role assignment list --assignee "$MI_ID" --query "[].roleDefinitionName" -o tsv 2>/dev/null || echo "")
    if echo "$ROLES" | grep -q "Storage Table Data Contributor"; then
        pass "Role: Storage Table Data Contributor"
    else
        warn "Missing role: Storage Table Data Contributor"
    fi
    if echo "$ROLES" | grep -q "Website Contributor"; then
        pass "Role: Website Contributor"
    else
        warn "Missing role: Website Contributor"
    fi
else
    fail "Managed Identity 'SOCRadar-EntraID-MI' not found"
fi

# ---- 6. Application Insights ----
echo ""
echo "[6/8] Application Insights..."
AI_NAME=$(az monitor app-insights component list --resource-group "$RESOURCE_GROUP" --query "[?contains(name, 'socradar-entraid')].name" -o tsv 2>/dev/null | head -1)

if [[ -n "$AI_NAME" ]]; then
    pass "App Insights found: $AI_NAME"
else
    warn "App Insights not found (monitoring may not be configured)"
fi

# ---- 7. Log Analytics Workspace ----
echo ""
echo "[7/8] Log Analytics Workspace..."
if az monitor log-analytics workspace show \
    --resource-group "$WORKSPACE_RESOURCE_GROUP" \
    --workspace-name "$WORKSPACE_NAME" &>/dev/null 2>&1; then
    WS_ID=$(az monitor log-analytics workspace show \
        --resource-group "$WORKSPACE_RESOURCE_GROUP" \
        --workspace-name "$WORKSPACE_NAME" \
        --query "customerId" -o tsv)
    pass "Workspace: $WORKSPACE_NAME (ID: ${WS_ID:0:8}...)"

    # Check if custom tables have data
    echo ""
    echo "  Custom tables (may take 5-15 min after first run to appear):"
    for TABLE in "SOCRadar_Botnet_CL" "SOCRadar_PII_CL" "SOCRadar_VIP_CL" "SOCRadar_EntraID_Audit_CL"; do
        COUNT=$(az monitor log-analytics query \
            --workspace "$WS_ID" \
            --analytics-query "$TABLE | count" \
            --query "[0].Count" -o tsv 2>/dev/null || echo "?")
        if [[ "$COUNT" == "?" ]] || [[ "$COUNT" == "" ]]; then
            echo "    $TABLE: no data yet"
        elif [[ "$COUNT" == "0" ]]; then
            echo "    $TABLE: 0 records"
        else
            pass "$TABLE: $COUNT records"
        fi
    done
else
    fail "Workspace '$WORKSPACE_NAME' not found"
fi

# ---- 8. Workbooks ----
echo ""
echo "[8/8] Workbooks..."
WB_COUNT=$(az workbook list --resource-group "$RESOURCE_GROUP" --category "sentinel" --query "length([?contains(displayName, 'SOCRadar')])" -o tsv 2>/dev/null || echo "0")

if [[ "$WB_COUNT" -gt 0 ]]; then
    pass "$WB_COUNT SOCRadar workbook(s) deployed"
    az workbook list --resource-group "$RESOURCE_GROUP" --category "sentinel" \
        --query "[?contains(displayName, 'SOCRadar')].displayName" -o tsv 2>/dev/null | while read -r wb; do
        echo "    - $wb"
    done
else
    warn "No SOCRadar workbooks found (deploy with: ./deploy_workbooks.sh)"
fi

# ---- 9. Function App Logs (last run) ----
echo ""
echo "[BONUS] Recent Function App Activity..."
if [[ -n "$FA_NAME" ]]; then
    LAST_RUN=$(az functionapp function list --name "$FA_NAME" --resource-group "$RESOURCE_GROUP" --query "[0].name" -o tsv 2>/dev/null || echo "?")
    echo "  Function: $LAST_RUN"
    echo "  View live logs:"
    echo "    az functionapp log tail --name $FA_NAME --resource-group $RESOURCE_GROUP"
fi

# ---- Summary ----
echo ""
echo "============================================================"
echo "  VALIDATION SUMMARY"
echo "============================================================"
echo ""
echo "  Passed:  $PASS"
echo "  Failed:  $FAIL"
echo "  Warnings: $WARN"
echo ""

if [[ $FAIL -eq 0 ]]; then
    echo "  Result: ALL CHECKS PASSED"
else
    echo "  Result: $FAIL FAILED — review errors above"
fi
echo "============================================================"

exit "$FAIL"
