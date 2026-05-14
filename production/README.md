# SOCRadar Entra ID Integration for Microsoft Sentinel

Pulls leaked employee credentials from SOCRadar (Botnet, PII Exposure, VIP Protection) and takes automated remediation actions in Microsoft Entra ID. All findings are written to Microsoft Sentinel custom tables.

## Deploy

[![Deploy to Azure](https://aka.ms/deploytoazurebutton)](https://portal.azure.com/#create/Microsoft.Template/uri/https%3A%2F%2Fraw.githubusercontent.com%2Forcunsami%2FSOCRadar-Azure-Entra-ID%2Fv1.0.0%2Fproduction%2Fazuredeploy.json)

1. Click **Deploy to Azure** above
2. Fill the form (see [Parameters](#parameters))
3. Click **Review + create** → **Create**
4. When deployment completes, grant admin consent for the App Registration:
   - Open the Azure portal → **Microsoft Entra ID** → **App registrations**
   - Open the newly created **SOCRadar Entra ID Integration** App Registration
   - **API permissions** → **Grant admin consent for [your tenant]** → confirm

That's it. The Function App starts polling SOCRadar on its next timer cycle (default: every 6 hours).

> **Tip:** If the user performing the deployment holds the **Cloud Application Administrator** role, set `GrantAdminConsent=true` in the form. ARM will grant consent automatically and step 4 is skipped — fully zero-touch deployment.

## First-time onboarding (clean seamless integration)

This section walks a customer through the integration end to end the first time. Allow ~60 minutes.

### Step 0 — Pre-deploy checklist

Before clicking **Deploy to Azure**, confirm:

- [ ] An Azure subscription where you have **Owner** or **Contributor**.
- [ ] A Microsoft Sentinel workspace already onboarded (`Microsoft.SecurityInsights` solution + `onboardingStates/default` on the Log Analytics workspace). If you don't have one, create it first.
- [ ] You are signed in as one of: **Cloud Application Administrator**, **Application Administrator**, or **Global Administrator** — only required for the greenfield path; the reuse path needs no AAD role at all.
- [ ] You have received from SOCRadar: `SocradarApiKey`, `SocradarCompanyId`, and (for the reuse path) the `EntraIdClientId` of SOCRadar's pre-consented App Registration.
- [ ] You know the list of Entra ID **tenant IDs** to monitor (single tenant: just yours; MSSP/holding: a comma-separated list).
- [ ] You know which **verified domains** are attached to those tenants (e.g. `acme.com,acme.io,acme.onmicrosoft.com`) — optional but recommended; without it every leaked email touches Microsoft Graph.

### Step 1 — Pick a deployment path

You have two paths. **Reuse is the recommended one for most customers.**

| Path | When to pick | What you need | Manual steps after deploy |
|------|--------------|---------------|---------------------------|
| **A) Reuse SOCRadar's App Registration** | You don't want to create a new App Registration in your own tenant. You want SOCRadar to operationally own the App Reg + permissions. | `EntraIdClientId` from SOCRadar. Set `CreateAppRegistration=false` + `SkipFicCreation=true` in the form. | One: grant admin consent for SOCRadar's App in your tenant (single portal click), and run the `socradar-entraid-fic.sh` helper script once (added below). |
| **B) Greenfield — create a new App Registration** | You want full operational ownership in your own tenant, and the deploying user has **Application Administrator** role (or higher). | Leave `CreateAppRegistration=true` (default) + leave `EntraIdClientId` blank. | One: grant admin consent (or set `GrantAdminConsent=true` if the deploying user has Cloud Application Administrator role — zero-touch). |

### Step 2 — Multi-tenant + multi-domain configuration (when applicable)

For an MSSP or a holding company that monitors several Entra ID tenants from a single deployment:

```
EntraIdTenantIds        = 11111111-...,22222222-...,33333333-...
EntraIdVerifiedDomains  = acme.com,acme.io,acme.onmicrosoft.com,acme-uk.com,acme.de
EntraIdClientId         = <SOCRadar reuse App Reg, OR leave blank for greenfield>
```

The same App Registration is consented in every tenant in `EntraIdTenantIds`. The verified-domain allowlist is **one list across all those tenants** — every email whose domain matches any entry is forwarded to Microsoft Graph (which then tries each tenant in order, first match wins). Emails outside the allowlist are written to Log Analytics with `entra_status="skipped_domain_allowlist"` and **never reach Microsoft Graph** (saves API quota, removes audit noise).

Leave `EntraIdVerifiedDomains` empty to query every record returned by SOCRadar — the v1.0 behavior before the feature was added.

### Step 3 — Click Deploy and fill the form

Click the **Deploy to Azure** button at the top of this README. Fill the parameters following the table in the [Parameters](#parameters) section.

### Step 4 — Reuse-path post-deploy (skip if greenfield)

If you picked Path A (reuse) and set `SkipFicCreation=true`, the deployment script that creates the Federated Identity Credential is skipped on purpose. After the ARM deploy completes with `Succeeded`:

1. Download `scripts/socradar-entraid-fic.sh` from this repository.
2. Open Azure Cloud Shell (Bash).
3. Run:
   ```bash
   bash socradar-entraid-fic.sh <YOUR_RESOURCE_GROUP_NAME>
   ```

The script:
- Reads the User-Assigned Managed Identity's `principalId` from the resource group.
- Adds the Federated Identity Credential to SOCRadar's App Registration (requires you to be signed in as an **owner** of that App Reg — SOCRadar will add you as an owner before delivery if needed).
- Restarts the Function App and triggers the first poll.

It is idempotent — re-running is safe.

### Step 5 — Verify in Log Analytics

Allow ~5 minutes after the first run, then open **Log Analytics workspace → Logs**:

**Was the first run logged?**

```kql
SOCRadar_EntraID_Audit_CL
| where TimeGenerated > ago(30m)
| order by TimeGenerated desc
| project TimeGenerated, source, total_records, found_count, not_found_count, error_count, duration_sec, actions_taken
```

Expected: 3 rows (one per source: botnet, pii, vip). `error_count=0` for each. `total_records` reflects the SOCRadar API result count for your company.

**Were any of your users matched and actioned?**

```kql
union SOCRadar_Botnet_CL, SOCRadar_PII_CL, SOCRadar_VIP_CL
| where TimeGenerated > ago(30m)
| where entra_status == "found"
| project TimeGenerated, source=Type, email, actions_taken, entra_tenant_id
| order by TimeGenerated desc
```

Expected (when SOCRadar has real findings for you): one row per matched user, `actions_taken` populated, `entra_tenant_id` showing which tenant matched.

**Was the domain allowlist working?** (only if `EntraIdVerifiedDomains` was set)

```kql
union SOCRadar_Botnet_CL, SOCRadar_PII_CL, SOCRadar_VIP_CL
| where TimeGenerated > ago(30m)
| summarize Count=count() by entra_status
```

Expected: zero rows with `entra_status="skipped_domain_allowlist"` if every SOCRadar finding's email is on one of your verified domains. A non-zero count means SOCRadar surfaced a cross-domain email that was excluded from Graph lookup (audit only, no action taken) — that's the filter working as designed.

### Step 6 — Visual confirmation in workbooks

Open **Microsoft Sentinel → Workbooks → My workbooks** in the deployment's workspace. Four workbook templates land in the workspace:

- SOCRadar Entra ID — Botnet
- SOCRadar Entra ID — PII
- SOCRadar Entra ID — VIP
- SOCRadar Entra ID — Combined Dashboard (start here)

Each one carries a **TenantId** filter dropdown (active when `EntraIdTenantIds` lists multiple tenants), a top-line "compromised user count", a per-source status pie, and a recent-records table.

### Step 7 — Validate the integration with a controlled test (recommended)

To prove the integration end-to-end with controlled data — including the actions (revoke session, etc.) — use the **[Customer Acceptance Test runbook](../to-Radargoger/CUSTOMER-TEST-RUNBOOK.md)** (also shipped with the Standalone delivery bundle). The runbook walks 3-each test users × 3 sources (botnet/PII/VIP) and is what SOCRadar uses internally to validate new customer onboardings.

### Step 8 — Tune the integration

After the first successful run, decide which extra actions to enable and re-deploy (or update App Settings live):

- `EnableForceMfaReregistration` — invalidates MFA methods, forces re-enrolment. **High user impact.** Validate with one test user first.
- `EnableDisableAccount` — full lockout. **Highest user impact.** Combine with a recovery procedure.
- `EnableAddToGroup` + `SecurityGroupId` — segregate matched users into a quarantine group with restricted Conditional Access.
- `EnableCreateIncident` — create Microsoft Sentinel incidents for SOC triage.
- `EnableResolveAlarm` — automatically resolve the SOCRadar alarm on remediation success.

All actions are toggled independently. Defaults are conservative — only `EnableRevokeSession` is on by default.

### Troubleshooting first-run issues

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Audit `total_records=0` | Initial lookback too short or SOCRadar has no recent findings | Bump `InitialLookbackMinutes` (e.g. `86400` for 60 days) and re-run |
| Every record `entra_status="skipped_no_token"` | UAMI Federated Identity Credential missing or wrong subject | Run `socradar-entraid-fic.sh` (reuse path) or check that the addFic deployment script succeeded (greenfield path) |
| Every record `entra_status="lookup_permission_denied"` | Admin consent not granted on the App Registration | Microsoft Entra ID → App registrations → your App Reg → **API permissions** → **Grant admin consent** |
| Some records `entra_status="not_found"` | UPN mismatch — SOCRadar leaked email differs from the Entra UPN of the same user | This is expected for accounts that don't actually exist in your tenant; for true matches, verify the UPN format SOCRadar surfaces |
| Function App "Running" but no Log Analytics rows after 15 minutes | Custom-table first-write latency or a deployment-time DCR mismatch | Check the Function App **Log stream** for ingestion errors; verify `DCR_IMMUTABLE_ID` and `DCR_ENDPOINT` App Settings are populated |

Full troubleshooting (with diagnosis recipes for `AADSTS70001`, `AADSTS700016`, lifecycle events, empty TenantId dropdowns, etc.) lives in [`docs/troubleshooting.md`](docs/troubleshooting.md).

## Required Permissions

The deployment is **script-free for any user who holds an admin role on Microsoft Entra ID**. The exact post-deploy experience depends on the role the deployer has — pick the highest one available, and use the **Deploy form switches** column to set the form values.

### Microsoft Entra ID role on the customer tenant

| Role on the deployer | Post-deploy experience | Deploy form switches |
|----------------------|------------------------|----------------------|
| **Cloud Application Administrator** (or Global Admin) | 🟢 **Zero post-deploy steps.** ARM creates the App Registration, federated credential, and grants admin consent inline. | `CreateAppRegistration=true` *(default)* · `GrantAdminConsent=true` |
| **Application Administrator** | 🟡 **One post-deploy click.** ARM creates the App Registration + federated credential. Deployer (or another admin) clicks **Grant admin consent** once in the portal. | `CreateAppRegistration=true` *(default)* · `GrantAdminConsent=false` *(default)* |
| **No Entra ID admin role at all** | 🔴 **Fallback only.** SOCRadar pre-creates the App Registration in its own tenant; the customer runs a Cloud Shell helper to attach the federated credential and grants consent on the consent screen. Use only if no IT user in the customer org can be assigned an Entra ID admin role. | `CreateAppRegistration=false` · `EntraIdClientId=<SOCRadar-provided>` · `SkipFicCreation=true` |

> Cloud Application Administrator is the **least-privileged** Entra role that supports zero-touch. Application Administrator is one step below — it can create App Registrations but cannot grant tenant-wide admin consent, which is why one manual portal click remains.

### Azure RBAC on the deployment subscription / resource group

| Role | Required for | Notes |
|------|--------------|-------|
| **Contributor** (or Owner) on the target RG/subscription | Creating Function App, Storage, DCR, Log Analytics workspace (if new), Sentinel onboarding | If the workspace already exists in a different RG, deployer needs **Contributor** on that RG too |
| **Microsoft Sentinel Contributor** on the workspace | Onboarding Sentinel + writing custom table schema | Skipped if the workspace already has Sentinel onboarded |

> Owner is **not** required; Contributor is enough. The User Assigned Managed Identity that the integration runs as is granted least-privilege roles (DCR Monitoring Metrics Publisher, Storage Table Data Contributor) automatically by the template.

### Pre-deploy info you must have on hand

Before clicking **Deploy to Azure**, gather:

- `SocradarApiKey` and `SocradarCompanyId` — from SOCRadar account team.
- The **Tenant ID(s)** to monitor — copy from Azure Portal → Microsoft Entra ID → Overview.
- The **verified domains** attached to those tenants (e.g. `acme.com,acme.io`) — Microsoft Entra ID → Overview → "Primary domain" + Custom Domain Names blade. Optional but recommended.
- The Log Analytics workspace name (existing or to-be-created) and its region.

If a customer cannot satisfy these prerequisites, contact SOCRadar — the fallback (no-AAD-admin) path can be arranged but is not the recommended onboarding flow.

## Capabilities

What this integration does for you, end to end:

### 1. Continuous monitoring of leaked employee credentials
- **Three SOCRadar dark-web sources** polled on a configurable timer (default every 6 hours): Botnet Data (info-stealer logs), PII Exposure (data-breach surfacing), VIP Protection (executive / high-value).
- **Initial backfill** of up to 365 days (`InitialLookbackMinutes` parameter) so the first run captures the existing exposure picture, not just new findings.
- **Checkpoint-based resume** — heavy backlogs that exceed the function timeout are drained across multiple cycles; nothing is lost.

### 2. Identity scoping for relevance
- **Multi-tenant lookup** — query several Entra ID tenants from a single deployment (`EntraIdTenantIds` CSV). MSSP / holding-company / M&A use case. First-match-wins across tenants; the matched tenant is recorded on every Log Analytics record so downstream KQL can pivot per tenant.
- **Verified-domain allowlist** (`EntraIdVerifiedDomains` CSV) — scopes Microsoft Graph lookups to records whose email domain matches one of the customer's verified domains. Cross-domain SOCRadar matches (e.g. an employee's personal Gmail caught in a third-party breach) are written to the audit table with `entra_status="skipped_domain_allowlist"` and never touch Microsoft Graph — saves API quota and removes audit noise.
- **Configurable polling cadence** (`PollingIntervalHours`, default 6) and lookback window.

### 3. Eleven independently togglable remediation actions
When a leaked identity is found in Entra ID, any combination of the following can run automatically:

| Action | Toggle parameter | Graph permission required |
|--------|-----------------|---------------------------|
| Revoke all active sessions | `EnableRevokeSession` *(default true)* | `User.RevokeSessions.All` |
| Force password change at next sign-in | `EnablePasswordChange` | `User-PasswordProfile.ReadWrite.All` |
| Disable account (block sign-in) | `EnableDisableAccount` | `User.EnableDisableAccount.All` |
| Re-enable account | `EnableEnableAccount` | `User.EnableDisableAccount.All` |
| Force MFA re-registration (deletes auth methods) | `EnableForceMfaReregistration` | `UserAuthenticationMethod.ReadWrite.All` |
| Add to quarantine security group | `EnableAddToGroup` + `SecurityGroupId` | `GroupMember.ReadWrite.All` |
| Remove from group | `EnableRemoveFromGroup` + `SecurityGroupId` | `GroupMember.ReadWrite.All` |
| Mark as Confirmed Compromised in Identity Protection | `EnableConfirmRisky` | `IdentityRiskyUser.ReadWrite.All` (P1/P2 license) |
| ROPC password validation (advanced) | `EnableROPC` | optional |
| Create Microsoft Sentinel incident | `EnableCreateIncident` | Sentinel Contributor on workspace |
| Resolve SOCRadar alarm on success | `EnableResolveAlarm` | n/a (SOCRadar API) |

Defaults are conservative: only **Revoke session** is on. High-impact actions (account disable, password reset, MFA re-registration) start off — flip them on after validating with the [Customer Acceptance Test runbook](../to-Radargoger/CUSTOMER-TEST-RUNBOOK.md).

### 4. Outputs in Microsoft Sentinel
- **Four custom Log Analytics tables** via DCR-based Logs Ingestion API (HTTP Data Collector deprecation already handled):
  - `SOCRadar_Botnet_CL`, `SOCRadar_PII_CL`, `SOCRadar_VIP_CL` — per-source matches
  - `SOCRadar_EntraID_Audit_CL` — per-run summary (counts, duration, errors)
- **Four Sentinel workbooks** — Botnet, PII, VIP, plus a Combined Operational Dashboard. All workbooks carry a `TenantId` filter dropdown for multi-tenant deployments.
- **Per-record status enum**: `found`, `not_found`, `lookup_permission_denied`, `skipped_no_token`, `skipped_user_lookup_disabled`, `skipped_domain_allowlist`, `compromised` (ROPC), `no_email`. Surfaces directly in workbook tiles.

### 5. Operational resilience
- **Secretless authentication** — Workload Identity Federation (UAMI → Federated Credential → App Registration). No client secrets, no key rotation, no expiring credentials.
- **Per-tenant 403 dropout** — if a tenant returns three consecutive 403s during a run (admin consent missing or revoked), it is dropped from the lookup map for the remainder of that run. Healthy tenants continue.
- **Per-source + per-employee time budget** — guarantees graceful exit within the 10-minute Linux Consumption hard timeout.
- **Pagination resume** — `MAX_PAGES_PER_RUN` exits cleanly, checkpoint records the last drained page, next run resumes.
- **Application Insights** — every poll and Graph call is traced; the `[AUDIT]` log line carries the per-source summary for quick triage.
- **Pre-Graph domain filter** prevents wasted quota on records that don't belong to the customer's tenant domain.

### 6. Lifecycle events
The integration emits structured lifecycle events to `SOCRadar_EntraID_Audit_CL` when configuration drifts (e.g. `consent_revoked` when a tenant suddenly returns 403). These are queryable for alerting:

```kql
SOCRadar_EntraID_Audit_CL
| where TimeGenerated > ago(24h)
| where source startswith "lifecycle:"
```

## Parameters

### Required

| Parameter | Description |
|-----------|-------------|
| `WorkspaceName` | Name of the Log Analytics workspace to create (or reuse) |
| `SocradarApiKey` | Your SOCRadar Platform API key |
| `SocradarCompanyId` | Your SOCRadar Company ID |

### Sources (what to monitor)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `EnableBotnetSource` | `true` | Botnet Data v2 — credentials from botnet logs |
| `EnablePiiSource` | `true` | PII Exposure v2 — credentials from data breaches |
| `EnableVipSource` | `false` | VIP Protection v2 — VIP user exposures |

### Actions (what to do when a match is found in Entra ID)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `EnableUserLookup` | `true` | Look up leaked identity in Entra ID before taking action |
| `EnableRevokeSession` | `true` | Revoke all active sign-in sessions |
| `EnableAddToGroup` | `false` | Add user to a quarantine security group (requires `SecurityGroupId`) |
| `EnableRemoveFromGroup` | `false` | Remove user from a security group |
| `EnablePasswordChange` | `false` | Force password change at next sign-in |
| `EnableDisableAccount` | `false` | Disable the user account (high impact) |
| `EnableEnableAccount` | `false` | Re-enable previously disabled accounts |
| `EnableForceMfaReregistration` | `false` | Delete all non-password MFA methods to force re-registration (high impact) |
| `EnableConfirmRisky` | `false` | Mark user as confirmed compromised in Identity Protection (requires Entra ID P1/P2) |
| `EnableResolveAlarm` | `false` | Mark the SOCRadar alarm as RESOLVED when remediation succeeds |

### Polling

| Parameter | Default | Description |
|-----------|---------|-------------|
| `PollingIntervalHours` | `6` | How often the Function App polls SOCRadar |
| `InitialLookbackMinutes` | `43200` | Lookback window for the first run (default: 30 days). Set higher (e.g. `129600` = 90 days) for initial backlog import. |
| `MaxPagesPerRun` | `50` | Pagination cap per run |
| `RunOnStartup` | `true` | Run an immediate poll after deployment instead of waiting for the first timer cycle |

### Advanced (optional)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `EntraIdTenantId` | (current subscription tenant) | Target Microsoft Entra ID tenant ID. Leave empty to auto-detect. |
| `EntraIdTenantIds` | (empty) | Comma-separated tenant IDs for multi-tenant monitoring (MSSP / holding scenarios). When set, overrides `EntraIdTenantId`. |
| `EntraIdVerifiedDomains` | (empty) | Optional comma-separated allowlist of verified domains attached to the tenant (e.g. `acme.com,acme.io,acme.onmicrosoft.com`). When set, only emails on these domains are looked up in Microsoft Graph; others land in LAW with `entra_status=skipped_domain_allowlist`. Leave empty to query every record (v1.0 behavior). Exact match, case-insensitive, no subdomain wildcards. |
| `WorkspaceLocation` | (deployment region) | Region for the Log Analytics workspace |
| `WorkspaceResourceGroup` | (current RG) | Resource group of the workspace (for cross-RG deployments) |
| `HostingPlanSku` | `Y1` | App Service Plan SKU. `Y1` = Consumption (best-effort timer). `B1` = Basic with Always-On (recommended for production reliability). `EP1` = Elastic Premium. |
| `SocradarBaseUrl` | `https://platform.socradar.com` | SOCRadar Platform base URL |

## What Gets Deployed

| Resource | Purpose |
|----------|---------|
| Function App (Python 3.11) | Polls SOCRadar, performs Entra ID actions, writes to LAW |
| App Service Plan | Hosting plan for the Function App |
| User-Assigned Managed Identity | Secretless auth (Workload Identity Federation) |
| Storage Account | Function App runtime + checkpoint table |
| Application Insights | Function App telemetry |
| App Registration (Entra ID) | Microsoft Graph permissions (created automatically) |
| Federated Identity Credential | Binds the UAMI to the App Registration (no client secret) |
| Log Analytics workspace + Sentinel onboarding | Destination for findings |
| 4 custom LAW tables | `SOCRadar_Botnet_CL`, `SOCRadar_PII_CL`, `SOCRadar_VIP_CL`, `SOCRadar_EntraID_Audit_CL` |
| Data Collection Rule (DCR) | DCR-based Logs Ingestion API |
| 4 Sentinel workbooks | Dashboards for Botnet, PII, VIP, Combined |
| Role assignments | Function App → LAW (write), UAMI → DCR (publish) |

## Microsoft Graph Permissions

The App Registration receives only the Graph Application permissions required by the actions you enable. Each permission is granted at deployment time (when `GrantAdminConsent=true`) or after deployment via the portal click.

| Permission | Required For |
|------------|-------------|
| `User.Read.All` | `EnableUserLookup` |
| `User.RevokeSessions.All` | `EnableRevokeSession` |
| `GroupMember.ReadWrite.All` | `EnableAddToGroup`, `EnableRemoveFromGroup` |
| `User.EnableDisableAccount.All` | `EnableDisableAccount`, `EnableEnableAccount` |
| `User-PasswordProfile.ReadWrite.All` | `EnablePasswordChange` |
| `IdentityRiskyUser.ReadWrite.All` | `EnableConfirmRisky` |
| `UserAuthenticationMethod.ReadWrite.All` | `EnableForceMfaReregistration` |

If an action is disabled, its permission is still requested on the App Registration but is unused at runtime. To minimize the permission set, you can manually remove unused permissions from the App Registration after deployment.

## Sentinel Workbooks

Four workbooks are deployed automatically:

- **Botnet Protection Dashboard** — credentials harvested by botnets
- **PII Protection Dashboard** — credentials exposed in data breaches
- **VIP Protection Dashboard** — VIP user exposures
- **Combined Dashboard** — single pane covering all three sources, with tenant-level breakdown

Open them in **Microsoft Sentinel** → **Workbooks** → tab "My Workbooks".

## Verification

After deployment, query the audit table to confirm the Function App is running:

```kql
SOCRadar_EntraID_Audit_CL
| where TimeGenerated > ago(2h)
| project TimeGenerated, source, total_records, found_count, error_count, duration_sec
| order by TimeGenerated desc
```

For matched users and the actions taken:

```kql
union SOCRadar_Botnet_CL, SOCRadar_PII_CL, SOCRadar_VIP_CL
| where TimeGenerated > ago(2h)
| where entra_status == "found"
| project TimeGenerated, source, email, actions_taken, entra_tenant_id
| order by TimeGenerated desc
```

## Notes

- **Password handling**: Passwords are sanitized immediately on fetch. By default only `password_present` (bool) and `password_masked` are written to Log Analytics. Set `EnableLogPlaintextPassword=true` only if you have a compelling reason (not recommended).
- **Checkpoint**: Each source stores its last processed date in Azure Table Storage. Subsequent runs only fetch records after that date — no duplicates.
- **Workspace soft-delete**: If you delete and recreate a workspace with the same name within 14 days, old data reappears. Use a different name or wait 14 days.
- **Network requirements**: Outbound HTTPS access from the Function App to `platform.socradar.com` and `graph.microsoft.com`. If your network uses a proxy or firewall, whitelist these domains.
