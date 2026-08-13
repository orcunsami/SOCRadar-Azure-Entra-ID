# Troubleshooting

Operational runbook for SOCRadar Entra ID Integration. Each section: **Symptom → Diagnosis → Fix.**

Scan the symptom first. If none match, the last section lists how to collect diagnostic info before contacting support.

---

## 1. Function runs but no records appear in Log Analytics

**Symptom**: App Insights shows the timer fires and the function exits in ~20s, but no `SOCRadar_*_CL` tables appear or remain empty.

**Diagnosis (v1.5.0+ — DCR-based ingestion)**:
- Custom tables in Log Analytics take 5–15 minutes to appear on first write.
- Confirm the function actually called the Logs Ingestion API: App Insights → Traces → filter `[LAW]`. Look for `LogsIngestionClient initialized for https://<dcr-name>.<region>.ingest.monitor.azure.com`.
- If 403/401 on DCR upload: UAMI is missing the **Monitoring Metrics Publisher** role on the DCR. Check via Azure Portal → Data Collection Rule → **Access control (IAM)** → look for the UAMI under role assignments.
- If 200 and still no data: check `DCR_IMMUTABLE_ID` and `DCR_ENDPOINT` app settings (Function App → Configuration); verify the table exists in Azure Portal → Log Analytics workspace → **Tables**.

**Fix**:
- Wait 15 minutes after first ingest.
- Verify app settings: `DCR_IMMUTABLE_ID` (looks like `dcr-xxxxxxxxxxxxxxxx`), `DCR_ENDPOINT` (looks like `https://socradar-ei-dcr-...ingest.monitor.azure.com`), `WORKSPACE_ID` (workspace customerId).
- KQL sanity check: `SOCRadar_EntraID_Audit_CL | take 10` (audit table writes even when sources return 0 records).

**Note on legacy `WORKSPACE_KEY`**: pre-v1.5.0 versions used HMAC-SHA256 with workspace primary key. Microsoft is deprecating that API on Sep 14, 2026. v1.5.0+ uses DCR-based OAuth authentication via UAMI — no shared key needed.

---

## 2. Token acquisition fails — `[ENTRA] Failed to acquire Graph token`

**Symptom**: App Insights traces contain `[ENTRA] Failed to acquire Graph token: AADSTS...`.

**Diagnosis**: read the AADSTS code.

| AADSTS code | Meaning | Fix |
|-------------|---------|-----|
| `AADSTS7000215` | Invalid client credential | FIC misconfiguration. Verify: (1) FIC exists on app registration linking to UAMI, (2) AZURE_CLIENT_ID matches the UAMI's client ID, (3) ENTRA_CLIENT_ID matches the app registration's client ID. |
| `AADSTS700016` | App not found in tenant | App registration deleted, or wrong `ENTRA_TENANT_ID`. Verify the appId exists in Azure Portal → Microsoft Entra ID → App registrations → search by appId. |
| `AADSTS7000112` | App disabled | Enable the app registration in the Entra admin portal. |
| `AADSTS65001` / `AADSTS700022` | Admin has not consented | Admin must click the consent URL: `https://login.microsoftonline.com/{tenant}/adminconsent?client_id={appId}`. |
| `AADSTS50020` | User account not in tenant | Wrong tenant. Check `ENTRA_TENANT_ID`. |
| other | Transient or new error | Retry in 5 min, then open support ticket with the full trace. |

Since the 2026-04 refactor, token acquisition failures are written to `SOCRadar_EntraID_Audit_CL` as lifecycle events. Consent-specific codes get `event_type=consent_revoked`; all other failures (including `AADSTS7000215` which is a credential issue, not consent) get `event_type=token_acquisition_failed`. Check both:

```kql
SOCRadar_EntraID_Audit_CL
| where event_type in ("consent_revoked", "token_acquisition_failed")
| project TimeGenerated, event_type, tenant_id, aadsts_code, details
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

**Fix**: Set `ENABLE_USER_LOOKUP=true` in Function App configuration → Save → Restart. `ENTRA_TENANT_ID` and `ENTRA_CLIENT_ID` must be populated (no secret — auth is secretless via UAMI + FIC).

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
- Verify UAMI role assignment in Azure Portal → Storage account → **Access control (IAM)** → role assignments — look for `SOCRadar-EntraID-MI` with **Storage Table Data Contributor**.
- Missing → ARM redeploy restores it.
- Table deleted → ARM redeploy recreates, but checkpoint resets to earliest lookback.

---

## 8. FIC / Workload Identity Federation errors

**Symptom**: AADSTS7000215 or `token_acquisition_failed` errors appear.

**Diagnosis**: The Federated Identity Credential (FIC) linking the UAMI to the App Registration may be misconfigured.

**Fix**:
1. Verify FIC exists: Azure Portal → Microsoft Entra ID → App registrations → open the App Registration → **Certificates & secrets** → **Federated credentials** tab. You should see at least one credential linking the UAMI.
2. Verify `AZURE_CLIENT_ID` app setting matches the UAMI's client ID (Function App → Configuration; UAMI → Overview → Client ID).
3. Verify `ENTRA_CLIENT_ID` app setting matches the App Registration's Application (client) ID.
4. Verify `ENTRA_TENANT_ID` app setting matches the tenant ID (Azure Portal → Microsoft Entra ID → Overview).
5. If FIC is missing, add it via **Certificates & secrets** → **Federated credentials** → **Add credential** → scenario **Managed identity** → select the UAMI → save.

No secret rotation needed — auth is fully secretless via Managed Identity.

---

## 9. Deploy-to-Azure button downloads old code

**Symptom**: Customer deploys via ARM, but refactored features (EnableUserLookup, EnableForceMfaReregistration) are missing from their Function App.

**Diagnosis**: ARM template's `WEBSITE_RUN_FROM_PACKAGE` points to a stale GitHub release URL, OR the customer's deployment pinned an older version.

**Fix**:
- Verify ARM template:
  ```
  grep WEBSITE_RUN_FROM_PACKAGE production/azuredeploy.json
  ```
  Should show the latest release tag.
- Customer can force re-pull by re-running ARM deployment (idempotent) or by running `func azure functionapp publish <FA_NAME> --python --remote-build` from a clone at master.
- From 2026-04 onward, auto-release workflow builds zip on every tag push. **Always pin to the versioned URL** (`.../releases/download/vX.Y.Z/FunctionApp.zip`) — Azure does not follow the 302 redirect on `releases/latest/download/...`, so a `latest` URL will leave `WEBSITE_RUN_FROM_PACKAGE` broken at runtime (`Container 'FunctionApp.zip' not found`).

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

Before opening a ticket, collect (all via Azure Portal):

**1. Recent traces (Azure Portal → Application Insights → Logs):**
```kql
traces
| where timestamp > ago(1h)
| order by timestamp desc
| take 100
```

**2. Last 5 function executions (Azure Portal → Application Insights → Logs):**
```kql
requests
| where timestamp > ago(1d)
| order by timestamp desc
| take 5
```

**3. Current app settings:** Azure Portal → Function App → **Configuration** → **Application settings**. Screenshot the list (redact `SOCRADAR_API_KEY` before sharing).

**4. Lifecycle events (Azure Portal → Log Analytics workspace → Logs):**
```kql
SOCRadar_EntraID_Audit_CL
| where TimeGenerated > ago(7d)
| project TimeGenerated, event_type, tenant_id, aadsts_code, details
| order by TimeGenerated desc
```

---

## 13. Multi-tenant errors

This integration can monitor multiple Entra ID tenants from a single
deployment (see [multi-tenant-setup.md](./multi-tenant-setup.md)). The
following errors are specific to that mode.

### "Users in tenant X are always reported as not_found"

The admin in tenant X has not consented the multi-tenant App Registration.
Send them:

```
https://login.microsoftonline.com/{TENANT_X_ID}/adminconsent?client_id={APP_CLIENT_ID}
```

After they click **Accept**, a service principal for the app appears in
tenant X's **Enterprise applications**. Subsequent runs find users there.

### `AADSTS700016` "Application not found in the directory"

Same as above — the admin in that tenant has not consented. If consent
succeeded but the error persists, verify the App Registration's
`signInAudience` in the **primary** tenant is `AzureADMultipleOrgs`. A
single-tenant app cannot be consented elsewhere.

### `AADSTS70001` "Application disabled in tenant"

A tenant admin disabled the service principal in their Enterprise
applications. Ask them to re-enable it.

### `consent_revoked` event repeating for one tenant

That tenant's admin revoked the app's consent. The integration logs the
event once per run and stops trying that tenant for the rest of the run,
but the next run starts fresh. Re-consent the app or remove that tenant ID
from `EntraIdTenantIds` to stop the noise.

### Workbook `TenantId` dropdown is empty

The dropdown is query-driven — it populates from distinct `entra_tenant_id`
values in the source tables. If no record has been written yet (fresh
deployment), the dropdown is empty. Wait for the first poll cycle to
complete, or query a source table directly to verify ingestion is
happening.

### Same user found in multiple tenants

The integration takes a "first match wins" approach: tenants are tried in
the order given in `EntraIdTenantIds`, and only the first tenant where the
user is found is acted upon. Reorder the CSV to change priority.

---

## 14. Records with `entra_status="skipped_domain_allowlist"`

**Symptom**: Records appear in `SOCRadar_Botnet_CL`, `SOCRadar_PII_CL`, or
`SOCRadar_VIP_CL` with `entra_status="skipped_domain_allowlist"`,
`actions_taken=[]`, and `entra_tenant_id=""`. No Microsoft Graph call
was made for them.

**This is not an error** — it is the verified-domain allowlist filter
working as designed. When `EntraIdVerifiedDomains` is set, only records
whose email domain matches the allowlist proceed to the multi-tenant
Graph lookup loop; everything else is recorded for audit and skipped.

**Diagnosis**:

```kql
union SOCRadar_Botnet_CL, SOCRadar_PII_CL, SOCRadar_VIP_CL
| where TimeGenerated > ago(24h)
| where entra_status == "skipped_domain_allowlist"
| extend domain = tostring(split(email, "@")[1])
| summarize records=count() by domain
| order by records desc
```

**Fix (only if the records SHOULD have been looked up)**:

- If the surfaced domain belongs to a verified domain you forgot to list,
  add it to `EntraIdVerifiedDomains` (comma-separated). Match is
  case-insensitive but exact — `mail.acme.com` does not match `acme.com`.
- If you want to disable filtering entirely, set
  `EntraIdVerifiedDomains=""` (empty string). Every record SOCRadar
  returns will then reach Microsoft Graph (pre-feature behavior).

To apply a change without re-deploying:

1. Azure Portal → Function App → **Configuration** → edit
   `ENTRA_ID_VERIFIED_DOMAINS` → **Save**.
2. **Overview** → **Restart**.
3. Wait for the next timer cycle (or trigger manually via the SCM
   `/admin/functions/socradar_entra_id_import` endpoint).

---

Attach all four to the support ticket.
