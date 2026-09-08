# SOCRadar Entra ID Integration for Microsoft Sentinel

Pulls leaked employee credentials from SOCRadar (Botnet, PII Exposure, VIP Protection) and takes automated remediation actions in Microsoft Entra ID. All findings are written to Microsoft Sentinel custom tables.

## Deploy

[![Deploy to Azure](https://aka.ms/deploytoazurebutton)](https://portal.azure.com/#create/Microsoft.Template/uri/https%3A%2F%2Fraw.githubusercontent.com%2Forcunsami%2FSOCRadar-Azure-Entra-ID%2Fmaster%2Fproduction%2Fazuredeploy.json)

1. Click **Deploy to Azure** above
2. Fill the form (see [Parameters](#parameters))
3. Click **Review + create** → **Create**
4. When deployment completes, grant admin consent for the App Registration:
   - Open the Azure portal → **Microsoft Entra ID** → **App registrations**
   - Open the newly created **SOCRadar Entra ID Integration** App Registration
   - **API permissions** → **Grant admin consent for [your tenant]** → confirm

That's it. The Function App starts polling SOCRadar on its next timer cycle (default: every 6 hours).

> **Tip:** If the user performing the deployment holds the **Cloud Application Administrator** role, set `GrantAdminConsent=true` in the form. ARM will grant consent automatically and step 4 is skipped — fully zero-touch deployment.

## Required Permissions

| Deployer's Entra ID role | Post-deploy experience | Form switches |
|--------------------------|------------------------|---------------|
| **Cloud App Admin** (or Global Admin) | 🟢 Zero steps — App Reg + FIC + admin consent all inline | `GrantAdminConsent=true` |
| **Application Admin** | 🟡 One click — admin consent button in App Registrations | defaults |
| **No admin role** | 🔴 Fallback only — contact SOCRadar | reuse path |

Azure side: **Contributor** (not Owner) on the target subscription / resource group is enough. For an existing workspace in another RG, the deployer also needs Contributor on that RG.

## Capabilities

- **3 SOCRadar sources** — Botnet Data, PII Exposure, VIP Protection. Configurable polling (default 6h) + initial lookback (default 30 days, max 365).
- **Multi-tenant + multi-domain** — `EntraIdTenantIds` CSV queries N tenants from one deployment; optional `EntraIdVerifiedDomains` CSV gates Graph lookups to in-scope domains only (cross-domain matches land in LAW with `entra_status="skipped_domain_allowlist"`, no Graph call).
- **11 togglable remediation actions** — revoke session (default on), force password change, disable/enable account, force MFA re-registration, add/remove from quarantine group, mark confirmed compromised, create Sentinel incident, resolve SOCRadar alarm, ROPC validation. High-impact actions default off.
- **4 LAW tables** via DCR-based ingestion (`SOCRadar_Botnet_CL`, `SOCRadar_PII_CL`, `SOCRadar_VIP_CL`, `SOCRadar_EntraID_Audit_CL`) + **4 Sentinel workbooks** with multi-tenant filter.
- **Secretless auth** — Workload Identity Federation (UAMI → FIC → App Reg). No client secrets, no key rotation.
- **Resilience** — per-tenant 403 dropout, per-employee + per-source time budgets, pagination resume across function timeouts, App Insights tracing, lifecycle events on `consent_revoked`.

For a controlled customer acceptance test with 9 test users × 3 sources, see [CUSTOMER-TEST-RUNBOOK.md](../to-Radargoger/CUSTOMER-TEST-RUNBOOK.md) (shipped with the Standalone delivery bundle).

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
| `CreateWorkspace` | `true` | Create a new Log Analytics workspace with `WorkspaceName`. Set `false` to attach to an existing workspace instead. Only applies when `WorkspaceResourceGroup` is empty. The workspace resource states no workspace-level settings, so leaving this `true` by mistake against an existing workspace never touches its pricing tier, retention or daily cap. |
| `HostingPlanSku` | `Y1` | App Service Plan SKU. `Y1` = Consumption (best-effort timer). `B1` = Basic with Always-On (recommended for production reliability). `EP1` = Elastic Premium. |
| `SkipFicCreation` | `true` | Reuse path only (`EntraIdClientId` set). `true`: the deployment leaves the App Registration alone and you add the federated credential afterwards with the `ficCommandToRun` output. That step is required, not optional - without the credential the Function App cannot get a Graph token. `false`: a deployment script adds it, which needs the deployment identity to hold `Application.ReadWrite.OwnedBy` on top of ownership. Ownership alone is not enough - measured 8 Sep 2026, three attempts, `Insufficient privileges`. |
| `SocradarBaseUrl` | `https://platform.socradar.com` | SOCRadar Platform base URL |

### Reusing an existing App Registration

If your tenant already has a consented SOCRadar App Registration, pass its client ID and
do not create a second one - a duplicate means asking your IT or security team for admin
consent again, and it leaves the tenant with two registrations that drift apart:

```bash
CreateAppRegistration=false
EntraIdClientId=<existing app id>
```

Then add the federated credential for the identity this deployment created. Whoever does
this needs to be an **owner of that App Registration** - that path is the one we measured.
Application Administrator and Cloud Application Administrator also cover it per the
Microsoft Graph documentation, though we did not test those. The person running the
deployment is not always one of them, so check before you start.

The exact command, with the identity's principal ID already filled in, is in the
deployment's `ficCommandToRun` output. If you would rather click than paste, the portal
path is: Microsoft Entra ID -> App registrations -> your app -> Certificates & secrets ->
Federated credentials -> Add credential -> scenario **Managed identity**, then pick the
`SOCRadar-EntraID-MI` identity from this deployment's resource group. Wizard labels move
around between tenants; if there is no managed-identity scenario, choose **Other issuer**
and type the three values instead - issuer `https://login.microsoftonline.com/<your tenant
id>/v2.0`, subject the `managedIdentityPrincipalId` output, audience
`api://AzureADTokenExchange`. The CLI command sends exactly those three.

Confirm it landed before you rely on the integration:

```bash
az ad app federated-credential list --id <existing app id> --query "[].name" -o tsv
```

## The workspace has to exist before you deploy

If you point the deployment at a workspace it does not create — `CreateWorkspace=false`,
or any `WorkspaceResourceGroup` — that workspace has to be there first. A wrong
`WorkspaceName` fails the deployment in its first step, `precheck-workspace-exists`,
and creates nothing. It used to create the storage account, the App Service Plan,
Application Insights, the identity and the Function App before failing, and leave them
standing.

Note that `WorkspaceResourceGroup` and `CreateWorkspace=true` together mean *use the
existing workspace in that resource group* — the template never creates a workspace
outside its own resource group. That combination now fails early and cleanly if the
workspace is not there.

## Existing installations

Deployments made before this template stopped stating workspace-level settings wrote a
pricing tier, retention and log-access mode on every deploy, and a template overwrites
every field it states. If the target workspace was on a **commitment tier**, that reset it
to `PerGB2018` (pay-as-you-go).

Check the current tier:

```bash
az monitor log-analytics workspace show -g <resource-group> -n <workspace> \
  --query "{sku:sku.name, lastSkuUpdate:sku.lastSkuUpdate}" -o json
```

If `lastSkuUpdate` lines up with when you deployed this integration and the tier isn't the
one you picked, reset your commitment tier from **Log Analytics workspaces > Usage and
estimated costs > Pricing tier**. The current template states no workspace-level settings at
all, so redeploying or upgrading an existing install — even with `CreateWorkspace=true` left
at its default by mistake — cannot change its pricing tier, retention or daily cap.

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
| project TimeGenerated, source, total_records, found_count, not_found_count,
          domain_filtered, no_address_count, lookup_disabled_count,
          no_token_count, lookup_failed_count, error_count,
          truncated, capped, duration_sec
| order by TimeGenerated desc
```

Every record a **finished** run handled falls into exactly one of those
buckets, and together with `error_count` they add up to `total_records`.
A run that reports `truncated` legitimately accounts for less — the tail is
read again next run. If the parts do not close on a finished run, the summary
is hiding something:

```kql
SOCRadar_EntraID_Audit_CL
| where TimeGenerated > ago(7d) and not(truncated) and isnotempty(total_records)
| extend accounted = found_count + not_found_count + domain_filtered
                   + no_address_count + lookup_disabled_count + no_token_count
                   + lookup_failed_count + error_count
| where accounted != total_records
| project TimeGenerated, source, total_records, accounted
```

Anything that went wrong recently — each of these also means the window was
held and will be read again (`import_window_abandoned` in the same table says
a window was given up after too many holds):

```kql
SOCRadar_EntraID_Audit_CL
| where TimeGenerated > ago(1d)
        and (error_count > 0 or truncated or capped or lookup_failed_count > 0)
| project TimeGenerated, source, error_count, lookup_failed_count, truncated, capped
```

For matched users and the actions taken (`*_skipped_duplicate` means a re-read
window found the action already applied; `skipped_capped` means the per-run
action ceiling was reached and the account gets its turn on the re-read):

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
- **A failed `Failure-Anomalies-Alert-Rule-Deployment` is Azure's, not ours**: after a
  successful install the resource group's deployment history may show one. Azure creates
  that smart detection rule by itself when Application Insights appears, and it fails with
  `MissingSubscriptionRegistration` on a subscription that has not registered the
  `Microsoft.AlertsManagement` provider (measured 7 Sep 2026, present even in a healthy
  production resource group). Nothing in this template refers to it and the integration
  works without it. Register that provider if you want the alert:
  `az provider register --namespace Microsoft.AlertsManagement`.
