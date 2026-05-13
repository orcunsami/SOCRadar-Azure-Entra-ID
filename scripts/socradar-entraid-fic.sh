#!/bin/bash
#
# SOCRadar Entra ID Integration — Post-deploy FIC helper script
#
# Use this AFTER a reuse-path deployment (CreateAppRegistration=false +
# SkipFicCreation=true). Creates the Federated Identity Credential that
# binds the UAMI to the existing App Registration, then restarts the
# Function App and triggers the first poll.
#
# Requirements:
#   - You must be signed in via `az login` as an owner of the App Registration
#   - The App Registration must already have admin consent granted for the
#     Microsoft Graph permissions (this is the whole point of reuse path)
#
# Usage:
#   ./socradar-entraid-fic.sh <RG_NAME> [APP_ID] [TENANT_ID]
#
# Defaults (override via positional args or env vars):
#   APP_ID=b0afca82-a991-4fea-ad87-94ec348b2e68  (SOCRadar test App Reg)
#   TENANT_ID=01a14909-9a97-4ded-9af3-7ea42ea99b2f  (SOCRadar tenant)

set -e

RG="${1:?Usage: $0 <RG_NAME> [APP_ID] [TENANT_ID]}"
APP_ID="${2:-${APP_ID:-b0afca82-a991-4fea-ad87-94ec348b2e68}}"
TENANT_ID="${3:-${TENANT_ID:-01a14909-9a97-4ded-9af3-7ea42ea99b2f}}"

echo "Resource group : $RG"
echo "App Reg        : $APP_ID"
echo "Tenant ID      : $TENANT_ID"
echo ""

echo "[1/4] Reading UAMI principal ID..."
UAMI_PRINCIPAL=$(az identity show -g "$RG" -n SOCRadar-EntraID-MI --query principalId -o tsv)
echo "      UAMI principalId: $UAMI_PRINCIPAL"
echo ""

echo "[2/4] Creating Federated Identity Credential on App Reg..."
# Idempotent: if a FIC with the same subject already exists, the create
# call returns 409 Conflict. We catch that and continue.
FIC_NAME="socradar-entraid-$RG"
EXISTING=$(az ad app federated-credential list \
    --id "$APP_ID" \
    --query "[?subject=='$UAMI_PRINCIPAL'].name" -o tsv 2>/dev/null || echo "")
if [ -n "$EXISTING" ]; then
    echo "      ✓ FIC already exists for this UAMI (name: $EXISTING) — skipping"
else
    az ad app federated-credential create \
      --id "$APP_ID" \
      --parameters "{
        \"name\": \"$FIC_NAME\",
        \"issuer\": \"https://login.microsoftonline.com/$TENANT_ID/v2.0\",
        \"subject\": \"$UAMI_PRINCIPAL\",
        \"audiences\": [\"api://AzureADTokenExchange\"]
      }" >/dev/null
    echo "      ✓ FIC '$FIC_NAME' created"
fi
echo ""

echo "[3/4] Restarting Function App + waiting 30s for cold start..."
FA=$(az resource list -g "$RG" --resource-type Microsoft.Web/sites --query "[0].name" -o tsv)
az functionapp restart -g "$RG" -n "$FA" -o none
echo "      Function App : $FA — restarted"
sleep 30
echo ""

echo "[4/4] Triggering first run..."
KEY=$(az functionapp keys list -g "$RG" -n "$FA" --query masterKey -o tsv)
HTTP=$(curl -sS -X POST "https://$FA.azurewebsites.net/admin/functions/socradar_entra_id_import" \
    -H "x-functions-key: $KEY" \
    -H "Content-Type: application/json" \
    -d '{}' \
    -w "%{http_code}" -o /dev/null)
echo "      Trigger response: HTTP $HTTP"
echo ""

if [ "$HTTP" = "202" ]; then
    echo "Done. Function will run in ~30-90s. Check Log Analytics:"
    echo ""
    echo "  SOCRadar_PII_CL"
    echo "  | where TimeGenerated > ago(10m)"
    echo "  | project email, entra_status, actions_taken"
    echo ""
    echo "  SOCRadar_EntraID_Audit_CL"
    echo "  | where TimeGenerated > ago(10m)"
    echo "  | project source, total_records, found_count, error_count"
else
    echo "WARNING: Trigger returned HTTP $HTTP (expected 202). Check Function App state."
    exit 1
fi
