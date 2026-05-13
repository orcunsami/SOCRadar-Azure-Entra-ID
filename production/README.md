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

## Who Can Deploy

The user clicking **Deploy to Azure** must have:

| Role | Greenfield (CreateAppRegistration=true) | Auto-consent (GrantAdminConsent=true) |
|------|------------------------------------------|----------------------------------------|
| **Application Administrator** | ✓ | — (consent step manual) |
| **Cloud Application Administrator** | ✓ | ✓ (zero-touch) |
| **Global Administrator** | ✓ | ✓ |
| Standard user | ✗ | ✗ |

The user must also have **Owner** or **Contributor** role on the target Azure subscription/resource group.

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
