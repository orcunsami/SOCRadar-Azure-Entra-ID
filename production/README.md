# SOCRadar Entra ID Integration

Pulls leaked employee credentials from SOCRadar and takes automated remediation actions in Microsoft Entra ID.

## Sources

| Source | Description | Key Required |
|--------|-------------|--------------|
| Botnet Data v2 | Employee credentials from botnet logs | Platform key |
| PII Exposure v2 | Employee credentials from data breaches | Platform key |
| VIP Protection v2 | VIP user exposures | Platform key — ⚠️ UNVERIFIED endpoint |

## Deployment

[![Deploy to Azure](https://aka.ms/deploytoazurebutton)](https://portal.azure.com/#create/Microsoft.Template/uri/https%3A%2F%2Fraw.githubusercontent.com%2Forcunsami%2FSOCRadar-Azure-Entra-ID%2Fmaster%2Fproduction%2Fazuredeploy.json)

Or via CLI:

```bash
az deployment group create \
  --resource-group YOUR-RG \
  --template-file production/azuredeploy.json \
  --parameters \
    WorkspaceName="your-workspace-name" \
    WorkspaceLocation="northeurope" \
    SocradarApiKey="your-platform-key" \
    SocradarCompanyId="your-company-id" \
    EntraIdTenantId="your-tenant-id" \
    EntraIdClientId="your-app-client-id" \
    EntraIdClientSecret="your-app-secret" \
    SecurityGroupId="your-security-group-object-id"
```

## Entra ID App Registration

Create an App Registration with only the Microsoft Graph Application permissions required by the features you enable (admin consent required).

| Permission | Required For |
|------------|-------------|
| `User.Read.All` | `EnableUserLookup=true` (look up users in Entra ID before taking action) |
| `User.RevokeSessions.All` | `EnableRevokeSession=true` |
| `GroupMember.ReadWrite.All` | `EnableAddToGroup=true` or `EnableRemoveFromGroup=true` |
| `User-PasswordProfile.ReadWrite.All` | `EnablePasswordChange=true` |
| `User.EnableDisableAccount.All` | `EnableDisableAccount=true` or `EnableEnableAccount=true` |
| `IdentityRiskyUser.ReadWrite.All` | `EnableConfirmRisky` (requires P1/P2 license) |

`User.ReadWrite.All` is not required for the current action model and should not be granted unless you intentionally add a broader capability.

For ROPC password validation (`EnableROPC=true`): enable **Allow public client flows** on the App Registration.

## Least-Privilege Model

The deployment is designed so that each Entra action is configurable independently.

- If `EnableUserLookup=false`, the app still fetches SOCRadar data and writes to Log Analytics, but it skips Entra user matching and all Entra-targeted actions.
- If an action is disabled, the corresponding Microsoft Graph permission does not need to be granted.
- High-impact actions such as account disable, account re-enable, password reset, and risky-user confirmation are disabled by default.

## Parameters

### Required

| Parameter | Description |
|-----------|-------------|
| `WorkspaceName` | Log Analytics workspace name |
| `WorkspaceLocation` | Workspace region |
| `SocradarApiKey` | SOCRadar platform API key |
| `SocradarCompanyId` | SOCRadar company ID |
| `EntraIdTenantId` | Microsoft Entra tenant ID |
| `EntraIdClientId` | App Registration client ID |
| `EntraIdClientSecret` | App Registration client secret |

### Sources

| Parameter | Default | Description |
|-----------|---------|-------------|
| `EnableBotnetSource` | `true` | Botnet Data v2 |
| `EnablePiiSource` | `true` | PII Exposure v2 |
| `EnableVipSource` | `false` | VIP Protection v2 (UNVERIFIED endpoint) |

### Actions

| Parameter | Default | Description |
|-----------|---------|-------------|
| `EnableUserLookup` | `true` | Look up leaked identities in Entra ID before taking action. Requires `User.Read.All`. If `false`, the app runs in data-ingest mode and skips Entra actions. |
| `EnableRevokeSession` | `true` | Revoke all sign-in sessions. Requires `User.RevokeSessions.All`. |
| `EnableAddToGroup` | `true` | Add user to a security group. Requires `GroupMember.ReadWrite.All`. |
| `EnableRemoveFromGroup` | `false` | Remove user from security group. Requires `GroupMember.ReadWrite.All`. |
| `SecurityGroupId` | `""` | Security group object ID (required if `EnableAddToGroup` or `EnableRemoveFromGroup`) |
| `EnableDisableAccount` | `false` | Disable the account. Requires `User.EnableDisableAccount.All`. |
| `EnableEnableAccount` | `false` | Re-enable a previously disabled account. Requires `User.EnableDisableAccount.All`. |
| `EnablePasswordChange` | `false` | Force password change on next sign-in. Requires `User-PasswordProfile.ReadWrite.All`. |
| `EnableConfirmRisky` | `false` | Mark user as confirmed compromised in Identity Protection. Requires `IdentityRiskyUser.ReadWrite.All` and P1/P2 licensing. |
| `EnableCreateIncident` | `false` | Create Microsoft Sentinel incident |
| `EnableROPC` | `false` | Validate password via ROPC (only for plaintext passwords) |
| `EnableResolveAlarm` | `false` | Resolve the SOCRadar alarm when a matched user is found in Entra ID |

### Other

| Parameter | Default | Description |
|-----------|---------|-------------|
| `PollingIntervalHours` | `6` | Polling interval in hours |
| `InitialLookbackMinutes` | `43200` | Lookback window for first run (minutes) |
| `InitialStartDate` | `""` | Optional first-run start date in `YYYY-MM-DD` format |
| `EnableLogPlaintextPassword` | `false` | Write plaintext passwords to Log Analytics (customer decision) |
| `WorkspaceResourceGroup` | `""` | Workspace resource group (for cross-RG deployments) |

## Log Analytics Tables

| Table | Source |
|-------|--------|
| `SOCRadar_Botnet_CL` | Botnet Data v2 |
| `SOCRadar_PII_CL` | PII Exposure v2 |
| `SOCRadar_VIP_CL` | VIP Protection v2 |
| `SOCRadar_EntraID_Audit_CL` | Audit log (all sources) |

## Workbooks

Four workbooks are included in `Workbooks/`:

- `SOCRadar-EntraID-Botnet-Workbook.json`
- `SOCRadar-EntraID-PII-Workbook.json`
- `SOCRadar-EntraID-VIP-Workbook.json` ⚠️ UNVERIFIED
- `SOCRadar-EntraID-Combined-Workbook.json`

Import via Azure Portal → Microsoft Sentinel → Workbooks → Add workbook → Edit → Advanced editor.

Or deploy all at once via CLI:

```bash
cd scripts
bash deploy_workbooks.sh
```

## Scripts

Deployment and testing scripts are in `scripts/`:

| Script | Description |
|--------|-------------|
| `deploy.sh` | Full ARM deployment + workbooks + role propagation wait |
| `deploy.config.example` | Configuration template (copy to `deploy.config` and fill in) |
| `deploy_workbooks.sh` | Deploy/update Sentinel workbooks only |
| `validate.sh` | Post-deployment health check (8-point validation) |
| `e2e_test.py` | Comprehensive E2E test suite (9 test categories) |
| `e2e_test.sh` | Test runner wrapper (full/dry-run/unit/quick modes) |
| `reset.sh` | Delete all deployed resources (with confirmation) |

### Quick Start

```bash
cd scripts

# 1. Configure
cp deploy.config.example deploy.config
# Edit deploy.config with your credentials

# 2. Deploy (5-month lookback by default)
bash deploy.sh

# 3. Validate
bash validate.sh

# 4. Test
python3 e2e_test.py --dry-run          # connectivity only
python3 e2e_test.py                     # full E2E with writes
python3 e2e_test.py --source botnet     # single source
```

## Notes

- **Password handling**: Passwords are sanitized immediately on fetch. By default only `password_present` (bool) and `password_masked` are logged. Set `EnableLogPlaintextPassword=true` to write plaintext passwords to LAW (customer decision — not recommended).
- **ROPC**: Microsoft discourages ROPC for production use. It is disabled by default and only works with accounts that do not have MFA enforced.
- **VIP endpoint**: Not in official SOCRadar API documentation. Verified working but may change without notice. Disabled by default.
- **Checkpoint**: Each source stores its last processed date in Azure Table Storage. Subsequent runs only fetch new records from that date forward.
