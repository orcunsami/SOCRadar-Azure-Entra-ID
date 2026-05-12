# SOCRadar Entra ID Integration for Microsoft Sentinel

[![Deploy to Azure](https://aka.ms/deploytoazurebutton)](https://portal.azure.com/#create/Microsoft.Template/uri/https%3A%2F%2Fraw.githubusercontent.com%2Forcunsami%2FSOCRadar-Azure-Entra-ID%2Fmaster%2Fproduction%2Fazuredeploy.json)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Release](https://img.shields.io/github/v/release/orcunsami/SOCRadar-Azure-Entra-ID)](https://github.com/orcunsami/SOCRadar-Azure-Entra-ID/releases/latest)

Automated remediation for **leaked employee credentials** detected by SOCRadar — pulls Botnet, PII Exposure, and VIP Protection alerts from the SOCRadar Platform, looks up matching users in Microsoft Entra ID, and takes configurable response actions (revoke sessions, force MFA re-registration, disable account, add to quarantine group, etc.). All findings are logged to Microsoft Sentinel custom tables for incident triage.

> **Looking for what changed?** See [CHANGELOG.md](CHANGELOG.md).

---

## 🎯 What It Does

```
SOCRadar Platform (Botnet / PII / VIP)
              │
              ▼
   Azure Function App (Python 3.11, timer trigger, every 6 hours)
              │
       ┌──────┴──────┐
       │             │
  Microsoft     Log Analytics
  Graph API     Workspace (Sentinel)
  ─────────     ────────────────────
  • Lookup     • SOCRadar_Botnet_CL
  • Revoke     • SOCRadar_PII_CL
  • Disable    • SOCRadar_VIP_CL
  • MFA wipe   • SOCRadar_EntraID_Audit_CL
  • Group add  • 4 Workbooks
  • etc.       • Sentinel incidents
```

**Secretless authentication** via Workload Identity Federation — no client secret to rotate, no password to store. The integration uses a User-Assigned Managed Identity linked to an App Registration via Federated Identity Credential.

**Modern data ingestion** via DCR-based Logs Ingestion API (Microsoft's replacement for the deprecated HTTP Data Collector API).

---

## ⚡ Quick Deploy

### Option A — One-Click (Deploy to Azure button)

Click the badge above ↑. Azure Portal opens with the ARM template. Fill in:

| Field | Where to get it |
|-------|-----------------|
| **WorkspaceName** | Your existing Log Analytics workspace name |
| **WorkspaceLocation** | Same region as your workspace (e.g. `northeurope`) |
| **SocradarApiKey** | SOCRadar Platform → Settings → API → copy the platform key |
| **SocradarCompanyId** | SOCRadar Platform → Settings → Company → company ID number |
| **EntraIdTenantIds** | One or more Entra ID Tenant IDs (comma-separated). The first ID is the "primary" tenant — where the multi-tenant App Registration and its Federated Identity Credential live. Additional IDs are tenants whose admins consent the same app (no extra FIC required). For single-tenant deployments leave empty and use `EntraIdTenantId`. See [Multi-Tenant Setup](docs/multi-tenant-setup.md). |
| **EntraIdTenantId** | Legacy single-tenant ID. Use only if `EntraIdTenantIds` is empty (backward compat). |
| **EntraIdClientId** | App Registration's Application (client) ID (see [App Registration setup](#-app-registration-setup) below). For multi-tenant, this is the same ID across every tenant. |
| **SecurityGroupId** | Optional: quarantine group's Object ID (required only if `EnableAddToGroup=true`) |

Click "Review + create" → "Create". Deployment takes ~3 minutes.

### Option B — Azure CLI

```bash
az deployment group create \
  --resource-group MY-RG \
  --template-uri https://raw.githubusercontent.com/orcunsami/SOCRadar-Azure-Entra-ID/master/production/azuredeploy.json \
  --parameters \
    WorkspaceName="my-sentinel-ws" \
    WorkspaceLocation="northeurope" \
    SocradarApiKey="<platform-key>" \
    SocradarCompanyId="<company-id>" \
    EntraIdTenantIds="<primary-tenant-id>,<secondary-tenant-id>" \
    EntraIdClientId="<app-client-id>" \
    SecurityGroupId="<group-id-or-empty>"
```

### What gets deployed (16 Azure resources)

1. User-Assigned Managed Identity (`SOCRadar-EntraID-MI`)
2. Storage Account (checkpoint table)
3. Function App (Python 3.11, Linux Consumption Y1 plan — pennies)
4. App Insights component
5. 4 Log Analytics custom tables (Botnet, PII, VIP, Audit)
6. Data Collection Rule + Data Collection Endpoint (DCR-based ingestion)
7. 3 Role assignments (Storage Table Data Contributor, Website Contributor, Monitoring Metrics Publisher)
8. Sentinel onboarding state + 4 Workbooks (deployed separately via `scripts/deploy.sh`)

---

## 🔑 App Registration Setup

The integration uses **Workload Identity Federation** — secretless auth. You need an App Registration with Graph permissions (no client secret required).

### 1. Create App Registration

Azure Portal → Microsoft Entra ID → App registrations → **New registration**
- Name: `SOCRadar Entra ID Integration`
- Supported account types:
  - **Single tenant** — if you only monitor one Entra ID directory.
  - **Multi-tenant** (`Accounts in any organizational directory`) — if you monitor multiple Entra tenants from one deployment. See [Multi-Tenant Setup](docs/multi-tenant-setup.md) before choosing this.
- Redirect URI: leave empty
- Click **Register**

Note the **Application (client) ID** — this is `EntraIdClientId` for the ARM template.

### 2. Add API Permissions

App Registration → API permissions → **Add a permission** → **Microsoft Graph** → **Application permissions** → search and add:

| Permission | Required for |
|------------|--------------|
| `User.Read.All` | `EnableUserLookup=true` (mandatory — look up leaked identities) |
| `User.RevokeSessions.All` | `EnableRevokeSession=true` |
| `GroupMember.ReadWrite.All` | `EnableAddToGroup=true` / `EnableRemoveFromGroup=true` |
| `User.EnableDisableAccount.All` | `EnableDisableAccount=true` / `EnableEnableAccount=true` |
| `User-PasswordProfile.ReadWrite.All` | `EnablePasswordChange=true` |
| `IdentityRiskyUser.ReadWrite.All` | `EnableConfirmRisky=true` (also needs **Entra ID P1/P2** license) |
| `UserAuthenticationMethod.ReadWrite.All` | `EnableForceMfaReregistration=true` (also needs **Privileged Authentication Administrator** directory role assigned to the SP) |

Click **Grant admin consent for {tenant}** — required for all Application permissions.

**Least-privilege**: grant only the permissions for the features you enable. The integration logs missing permissions but does not crash.

### 3. Federated Credential (auto-created during ARM deploy)

The ARM template's `deploy.sh` script or post-deploy step creates a Federated Identity Credential linking the UAMI's principal ID to your App Registration. This is the "secretless" part — no client secret stored anywhere.

If you deploy via the Azure Portal button (not `deploy.sh`), you'll need to add the FIC manually:

```bash
UAMI_PRINCIPAL_ID=$(az identity show --name SOCRadar-EntraID-MI --resource-group <RG> --query principalId -o tsv)
TENANT_ID=$(az account show --query tenantId -o tsv)

az ad app federated-credential create \
  --id <EntraIdClientId> \
  --parameters "{
    \"name\": \"SOCRadar-EntraID-UAMI\",
    \"issuer\": \"https://login.microsoftonline.com/$TENANT_ID/v2.0\",
    \"subject\": \"$UAMI_PRINCIPAL_ID\",
    \"audiences\": [\"api://AzureADTokenExchange\"]
  }"
```

(Future versions of the ARM template will create the FIC inline.)

---

## ✅ Post-Deployment Verification

After deploy, verify each step:

### 1. Function App is running

```bash
az functionapp show --name <FunctionAppName> --resource-group <RG> \
  --query "{state:state, runtime:siteConfig.linuxFxVersion}"
```

Expected: `state: Running, runtime: Python|3.11`

### 2. Function ran successfully

Azure Portal → Function App → Functions → `socradar_entra_id_import` → **Monitor** → Invocations.

You should see one execution within 5 minutes of deploy (triggered by `run_on_startup=True`).

### 3. Data is being written to Log Analytics

After the first execution, query the audit table (data appears within 5 minutes):

```kql
SOCRadar_EntraID_Audit_CL
| order by TimeGenerated desc
| take 10
| project TimeGenerated, source, total_records, found_count, actions_taken, error_count, duration_sec
```

### 4. Workbooks are visible

Microsoft Sentinel → Workbooks → **My workbooks** tab. You should see:
- SOCRadar Entra ID — Botnet Data
- SOCRadar Entra ID — PII Exposure
- SOCRadar Entra ID — VIP Protection
- SOCRadar Entra ID — Combined Dashboard

If not visible, run `bash scripts/deploy_workbooks.sh` from a clone of this repo.

---

## 🎛️ Feature Toggles (Configurable Actions)

All actions are disabled by default except `EnableUserLookup`, `EnableRevokeSession`, and `EnableAddToGroup`. Enable additional actions by passing them as ARM parameters or updating Function App settings:

```bash
az functionapp config appsettings set \
  --name <FA> --resource-group <RG> \
  --settings "ENABLE_DISABLE_ACCOUNT=true" "ENABLE_PASSWORD_CHANGE=true"
```

See [`production/README.md`](production/README.md#parameters) for the full parameter list and defaults.

---

## 🏋️ Heavy Backlog Tuning (initial import of months of leaked credentials)

Default settings work for steady-state daily ingestion (~tens to hundreds of new records per day per source). For an **initial deploy with a 3-6 month backlog** (potentially tens of thousands of records), you can speed up backlog ingestion:

| Setting | Default | Heavy backlog value | Effect |
|---------|---------|---------------------|--------|
| `PollingIntervalHours` | `6` | **`1`** | Function runs 6× more often → 6× faster backlog drain |
| `MaxPagesPerRun` | `50` | **`100`** | More pages per run (Function timeout is 10 min — about 24 pages fit per run for slow sources, so 100 is a soft cap; the real cap is the function timeout, which we exit gracefully before reaching) |

After the backlog is caught up (the audit table's `total_records` per run drops to your steady-state volume), restore the defaults:

```bash
az functionapp config appsettings set \
  --name <FA> --resource-group <RG> \
  --settings "POLLING_SCHEDULE=0 0 */6 * * *" "MAX_PAGES_PER_RUN=50"
az functionapp restart --name <FA> --resource-group <RG>
```

The function is **timeout-safe**: it tracks elapsed time and exits gracefully ~2 minutes before the function timeout, saving the checkpoint so the next run resumes from where it left off. No record is lost.

---

## 🔄 Re-deploying onto an Existing Workspace

The function tracks ingestion progress per source in a **checkpoint table** inside the deployed Storage Account (table name: `EntraIDState`). If you re-deploy on top of a previous installation (same Resource Group + same workspace), the old checkpoint persists. The function will resume from where the previous install left off — which is usually what you want.

But if you have **deleted and recreated the Log Analytics workspace**, or if you want the function to **re-fetch the full backlog** (e.g. for a new demo / staging environment), the stale checkpoint will make it look like there's nothing new to ingest. Symptom: function runs successfully but `total_records=0` for hours or days.

**To reset the checkpoint** (use only when you want a full re-ingest):

```bash
# Find the storage account in the deployed RG
STORAGE=$(az storage account list --resource-group <RG> --query "[?starts_with(name,'srentraid')].name | [0]" -o tsv)
KEY=$(az storage account keys list --account-name "$STORAGE" --resource-group <RG> --query "[0].value" -o tsv)

# Delete all rows in the checkpoint table
az storage entity query \
  --account-name "$STORAGE" \
  --account-key "$KEY" \
  --table-name EntraIDState \
  --query "items[].{p:PartitionKey,r:RowKey}" -o tsv | \
while IFS=$'\t' read -r pk rk; do
  az storage entity delete \
    --account-name "$STORAGE" --account-key "$KEY" \
    --table-name EntraIDState \
    --partition-key "$pk" --row-key "$rk"
done

# Restart the function to force fresh pickup
az functionapp restart --name <FunctionAppName> --resource-group <RG>
```

The next run will use `InitialLookbackMinutes` (or `InitialStartDate` if set) as if it were a first install.

> ⚠️ Resetting the checkpoint causes the next run to fetch the entire lookback window again. For a large window this can take many runs to drain — see **Heavy Backlog Tuning** above to speed it up.

---

## 📊 Microsoft Sentinel Tables

| Table | Source | Schema |
|-------|--------|--------|
| `SOCRadar_Botnet_CL` | Botnet Data v2 | email, password (masked), device, country, alarm_id, entra_status, actions_taken... |
| `SOCRadar_PII_CL` | PII Exposure v2 | email, password (masked), breach_date, source, entra_status... |
| `SOCRadar_VIP_CL` | VIP Protection v2 | vip_name, keyword, status, alarm_id... |
| `SOCRadar_EntraID_Audit_CL` | All sources | source, total_records, found_count, actions_taken, error_count, duration_sec |

All tables ingest via the modern **DCR-based Logs Ingestion API** (replaces deprecated HTTP Data Collector API — Microsoft Sentinel incident support deadline: Sep 14, 2026).

---

## 📋 Sample KQL Queries

### Compromised users found in Entra ID (last 7 days)
```kql
union SOCRadar_Botnet_CL, SOCRadar_PII_CL, SOCRadar_VIP_CL
| where TimeGenerated > ago(7d)
| where entra_status == "found"
| summarize count() by email, source, severity
| order by count_ desc
```

### Actions taken in last 24 hours
```kql
union SOCRadar_Botnet_CL, SOCRadar_PII_CL
| where TimeGenerated > ago(24h)
| where array_length(actions_taken) > 0
| project TimeGenerated, email, source, actions_taken
| order by TimeGenerated desc
```

### Audit summary (last week)
```kql
SOCRadar_EntraID_Audit_CL
| where TimeGenerated > ago(7d)
| summarize total=sum(total_records), found=sum(found_count), actions=sum(actions_taken), errors=sum(error_count) by source
```

### Token failures (security events)
```kql
SOCRadar_EntraID_Audit_CL
| where event_type in ("consent_revoked", "token_acquisition_failed")
| project TimeGenerated, event_type, tenant_id, aadsts_code, details
```

---

## 🔒 Security Notes

- **Passwords**: Sanitized immediately on receipt from SOCRadar. By default only `password_masked` (e.g. `a****b`) is stored. Set `EnableLogPlaintextPassword=true` to override (customer decision — not recommended).
- **No client secret**: Workload Identity Federation. Nothing to rotate.
- **Least-privilege role assignments**: UAMI gets exactly 3 roles (Storage table writer, Function site contributor, DCR metrics publisher).
- **ROPC**: Disabled by default. Microsoft discourages ROPC for production. Only useful for validating plaintext passwords on accounts without MFA.

---

## 📁 Repository Structure

```
production/         ← What gets deployed (ARM template + Function App + Workbooks)
scripts/            ← deploy.sh, validate.sh, e2e_test.py, etc.
tests/              ← Unit tests (CI-safe) + API discovery + integration tests
docs/               ← Architecture docs, comparison analyses, diagrams
.github/workflows/  ← CI: unit tests on push, auto-release on tag
```

For detailed parameters, scripts, and troubleshooting: see [`production/README.md`](production/README.md).

---

## 📞 Support

- Issues: https://github.com/orcunsami/SOCRadar-Azure-Entra-ID/issues
- SOCRadar Platform: https://docs.socradar.io
- Microsoft Sentinel Workbooks: Microsoft Sentinel → Workbooks → My workbooks

---

## 📄 License

Apache License 2.0 — see [LICENSE](LICENSE).
