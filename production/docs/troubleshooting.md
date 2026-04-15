# Troubleshooting

Operational runbook for SOCRadar Entra ID Integration. Each section: **Symptom → Diagnosis → Fix.**

Scan the symptom first. If none match, the last section lists how to collect diagnostic info before contacting support.

---

## 1. Function runs but no records appear in Log Analytics

**Symptom**: App Insights shows the timer fires and the function exits in ~30s, but no SOCRadar_*_CL tables appear or remain empty.

**Diagnosis**:
- Custom tables in Log Analytics take 5–15 minutes to appear on first write.
- Confirm the function actually called LAW: App Insights → Transaction search → filter `[LAW]`. Look for `POST https://{workspace-id}.ods.opinsights.azure.com/api/logs`.
- If 403/401 on LAW POST: wrong `WORKSPACE_KEY` app setting.
- If 200 and still no data: custom tables are indexed by log name. Make sure Sentinel/LAW isn't filtering to a different workspace than your queries.

**Fix**:
- Wait 15 minutes after first ingest.
- Verify app setting `WORKSPACE_ID` matches the workspace GUID and `WORKSPACE_KEY` is the Primary key (Settings → Agents → Primary/Secondary).
- KQL sanity check: `search "SOCRadar" | take 10` across the workspace.

---

## 2. Token acquisition fails — `[ENTRA] Failed to acquire Graph token`

**Symptom**: App Insights traces contain `[ENTRA] Failed to acquire Graph token: AADSTS...`.

**Diagnosis**: read the AADSTS code.

| AADSTS code | Meaning | Fix |
|-------------|---------|-----|
| `AADSTS7000215` | Invalid client secret | Secret expired or wrong. Generate new secret, update `ENTRA_CLIENT_SECRET` app setting, restart Function App. |
| `AADSTS700016` | App not found in tenant | App registration deleted, or wrong `ENTRA_TENANT_ID`. Verify `appId` exists via `az ad app show --id <appId>`. |
| `AADSTS7000112` | App disabled | Enable the app registration in the Entra admin portal. |
| `AADSTS65001` / `AADSTS700022` | Admin has not consented | Admin must click the consent URL: `https://login.microsoftonline.com/{tenant}/adminconsent?client_id={appId}`. |
| `AADSTS50020` | User account not in tenant | Wrong tenant. Check `ENTRA_TENANT_ID`. |
| other | Transient or new error | Retry in 5 min, then open support ticket with the full trace. |

Since the 2026-04 refactor, consent-related AADSTS codes are written as `event_type=consent_revoked` rows to `SOCRadar_EntraID_Audit_CL`. Query for them:

```kql
SOCRadar_EntraID_Audit_CL
| where event_type_s == "consent_revoked"
| project TimeGenerated, tenant_id_s, aadsts_code_s, details_s
| order by TimeGenerated desc
```

---

## 3. Graph API returns 429 (throttling)

**Symptom**: App Insights traces contain `[ENTRA] 429 throttled on <METHOD> <resource> — sleeping <n>s (attempt x/3)`.

**Diagnosis**: Microsoft Graph throttles calls per app-per-tenant. Reference: [Graph throttling guidance](https://learn.microsoft.com/en-us/graph/throttling).

**Fix**:
- First occurrence: integration auto-retries with `Retry-After` up to 3 times, capped at 30s per sleep. Usually self-heals.
- Sustained 429s mean the polling interval is too aggressive for the workload. Lower the SOCRadar polling frequency (`POLLING_INTERVAL_HOURS` parameter in ARM → 12 or 24h instead of 6).
- If thousands of leaks per run, split by source (run Botnet on one schedule, PII on another) — future enhancement; open a ticket if you hit this.

---

## 4. Entra actions skipped — `[ENTRA] EnableUserLookup=false`

**Symptom**: Log shows "User.Read.All is optional, but Entra lookup and all Entra-targeted actions will be skipped".

**Diagnosis**: `ENABLE_USER_LOOKUP` app setting is `false`. This is intentional for **data-ingest-only mode** (fetch SOCRadar leaks, write to LAW, skip Entra).

**Fix**: Set `ENABLE_USER_LOOKUP=true` in Function App configuration → Save → Restart. Entra credentials (`ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID`, `ENTRA_CLIENT_SECRET`) must be populated.

---

## 5. Action returns 403 Forbidden

**Symptom**: `[ENTRA] <action> <user> → HTTP 403` or `Authorization_RequestDenied`.

**Diagnosis**: The Graph permission for that action is not granted to the service principal.

| Toggle | Required permission |
|--------|---------------------|
| `EnableUserLookup` | `User.Read.All` |
| `EnableRevokeSession` | `User.RevokeSessions.All` |
| `EnableAddToGroup` / `EnableRemoveFromGroup` | `GroupMember.ReadWrite.All` |
| `EnablePasswordChange` | `User-PasswordProfile.ReadWrite.All` |
| `EnableDisableAccount` / `EnableEnableAccount` | `User.EnableDisableAccount.All` |
| `EnableConfirmRisky` | `IdentityRiskyUser.ReadWrite.All` + P1/P2 license |
| `EnableForceMfaReregistration` | `UserAuthenticationMethod.ReadWrite.All` + Privileged Authentication Administrator role |

**Fix**:
1. Entra admin center → App registrations → your app → API permissions
2. Add the missing permission (Application type, not Delegated)
3. **Grant admin consent** for the tenant
4. For `ConfirmRisky`: verify the tenant has Entra ID P1 or P2 license
5. For `ForceMfaReregistration`: also assign Privileged Authentication Administrator directory role to the service principal

---

## 6. Force MFA re-registration skipped — `force_mfa_rereg_no_permission`

**Symptom**: LAW records show `actions_taken` contains `force_mfa_rereg_no_permission` and `mfa_methods_deleted=0`.

**Diagnosis**: `EnableForceMfaReregistration=true` is set, but `UserAuthenticationMethod.ReadWrite.All` is not granted OR the service principal lacks the Privileged Authentication Administrator role.

**Fix**:
1. Grant `UserAuthenticationMethod.ReadWrite.All` application permission + admin consent.
2. Assign the SP to Privileged Authentication Administrator role in Entra admin center → Roles & admins.
3. Wait 5 minutes for propagation, re-trigger the function manually.

---

## 7. Checkpoint stuck / same leaks processed repeatedly

**Symptom**: Same leaked identities appear in LAW every run. Checkpoint not advancing.

**Diagnosis**:
- Function App's UAMI does not have Storage Table Data Contributor on the storage account.
- Table `EntraIDState` corrupted or deleted.

**Fix**:
- Verify UAMI role assignment: `az role assignment list --assignee <UAMI-principal-id> --scope /subscriptions/.../storageAccounts/<name>`.
- Missing → ARM redeploy restores it.
- Table deleted → ARM redeploy recreates, but checkpoint resets to earliest lookback.

---

## 8. `ENTRA_CLIENT_SECRET` expired or about to expire

**Symptom**: Consent-revoked-like AADSTS7000215 errors appear suddenly across all runs.

**Diagnosis**: Client secrets have a max 2-year lifetime. Check expiry: `az ad app credential list --id <appId> --query "[].endDateTime"`.

**Fix**:
1. Create new secret: `az ad app credential reset --id <appId> --years 2 --append`.
2. Update Function App setting `ENTRA_CLIENT_SECRET`.
3. Restart Function App.
4. Remove old secret after confirming new one works.

Long-term: consider migrating to Federated Identity Credential + Managed Identity (planned as G1).

---

## 9. Deploy-to-Azure button downloads old code

**Symptom**: Customer deploys via ARM, but refactored features (EnableUserLookup, EnableForceMfaReregistration) are missing from their Function App.

**Diagnosis**: ARM template's `WEBSITE_RUN_FROM_PACKAGE` points to a stale GitHub release URL, OR the customer's deployment pinned an older version.

**Fix**:
- Verify ARM template:
  ```
  grep WEBSITE_RUN_FROM_PACKAGE production/azuredeploy.json
  ```
  Should show the latest release tag (currently v1.1.0 or later).
- Customer can force re-pull by re-running ARM deployment (idempotent) or by running `func azure functionapp publish <FA_NAME> --python --remote-build` from a clone at master.
- From 2026-04 onward, auto-release workflow builds zip on every tag push. Admins can pin to `.../releases/latest/download/FunctionApp.zip` for always-current.

---

## 10. ROPC password validation returns `mfa_blocked` or `invalid`

**Symptom**: `[ENTRA:ROPC] <user> → mfa_blocked` or `invalid`.

**Diagnosis**:
- `mfa_blocked`: user has MFA enabled. ROPC cannot complete. This is actually a good signal — the compromised password alone is not sufficient to sign in.
- `invalid`: password doesn't work. Leak may be stale, or user has already rotated password.

**Fix**: Neither is a bug. Both outcomes are expected.
- If you want to validate passwords without MFA in the way: impossible by design (MS doesn't allow ROPC + MFA bypass).
- Consider turning off `ENABLE_ROPC` (Microsoft discourages it in production anyway). Rely on Force MFA re-registration or Confirm Risky instead.

---

## 11. UAMI not found at startup

**Symptom**: Function fails to start with `ManagedIdentityCredential: failed to retrieve token`.

**Diagnosis**:
- Function App does not have a UAMI assigned, OR
- `AZURE_CLIENT_ID` app setting doesn't match the UAMI's client ID.

**Fix**:
- Portal → Function App → Identity → User assigned → confirm UAMI `SOCRadar-EntraID-MI` is listed.
- Portal → Function App → Configuration → `AZURE_CLIENT_ID` must equal the UAMI's **Client ID** (not object ID).
- ARM redeploy fixes both.

---

## 12. How to collect diagnostic info for support

Before opening a ticket, collect:

```bash
# 1. Recent traces (last hour)
az monitor app-insights query \
  --app <AI_APP_ID> \
  --analytics-query "traces | where timestamp > ago(1h) | order by timestamp desc | take 100"

# 2. Last 5 function executions
az monitor app-insights query \
  --app <AI_APP_ID> \
  --analytics-query "requests | where timestamp > ago(1d) | order by timestamp desc | take 5"

# 3. Current app settings (redact secrets!)
az functionapp config appsettings list \
  --name <FA_NAME> --resource-group <RG> \
  --query "[?name!='ENTRA_CLIENT_SECRET' && name!='SOCRADAR_API_KEY' && name!='WORKSPACE_KEY'].{name:name, value:value}" -o table

# 4. Lifecycle events
# In Log Analytics, run:
SOCRadar_EntraID_Audit_CL
| where TimeGenerated > ago(7d)
| project TimeGenerated, event_type_s, tenant_id_s, aadsts_code_s, details_s
| order by TimeGenerated desc
```

Attach all four to the support ticket.
