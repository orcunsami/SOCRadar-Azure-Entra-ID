# SOCRadar Entra ID Integration

Pulls leaked employee credentials from SOCRadar and takes automated remediation actions in Microsoft Entra ID.

## Sources

| Source | Description | Key Required |
|--------|-------------|--------------|
| Identity Intelligence | Domain-specific credential exposure | Separate Identity key (pay-per-use) |
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
    SocradarApiKey="your-platform-key" \
    SocradarCompanyId="your-company-id" \
    MonitoredDomains="yourdomain.com,olddomain.com" \
    EntraIdTenantId="your-tenant-id" \
    EntraIdClientId="your-app-client-id" \
    EntraIdClientSecret="your-app-secret" \
    WorkspaceId="your-law-workspace-id" \
    WorkspaceKey="your-law-workspace-key"
```

## Entra ID App Registration

Create an App Registration with these Application permissions (admin consent required):

| Permission | Required For |
|------------|-------------|
| `User.Read.All` | User lookup (always required) |
| `GroupMember.ReadWrite.All` | `EnableAddToGroup=true` |
| `User.ReadWrite.All` | `EnableDisableAccount` or `EnablePasswordChange` |
| `IdentityRiskyUser.ReadWrite.All` | `EnableConfirmRisky` (requires P1/P2 license) |

For ROPC password validation (`EnableROPC=true`): enable **Allow public client flows** on the App Registration.

## Parameters

### Required

| Parameter | Description |
|-----------|-------------|
| `SocradarApiKey` | SOCRadar platform API key |
| `SocradarCompanyId` | SOCRadar company ID |
| `MonitoredDomains` | Comma-separated domains for Identity Intelligence (e.g., `contoso.com,fabrikam.com`) |
| `EntraIdTenantId` | Azure AD tenant ID |
| `EntraIdClientId` | App Registration client ID |
| `EntraIdClientSecret` | App Registration client secret |
| `WorkspaceId` | Log Analytics workspace ID |
| `WorkspaceKey` | Log Analytics workspace key |

### Sources

| Parameter | Default | Description |
|-----------|---------|-------------|
| `EnableIdentitySource` | `true` | Identity Intelligence (requires `SocradarIdentityApiKey` and `MonitoredDomains`) |
| `SocradarIdentityApiKey` | `""` | Identity Intelligence API key (separate, pay-per-use) |
| `EnableBotnetSource` | `true` | Botnet Data v2 |
| `EnablePiiSource` | `true` | PII Exposure v2 |
| `EnableVipSource` | `false` | VIP Protection v2 (UNVERIFIED endpoint) |

### Actions

| Parameter | Default | Description |
|-----------|---------|-------------|
| `EnableRevokeSession` | `true` | Revoke all sign-in sessions |
| `EnableAddToGroup` | `true` | Add user to a security group |
| `EnableRemoveFromGroup` | `false` | Remove user from security group (reverse of AddToGroup) |
| `SecurityGroupId` | `""` | Security group object ID (required if `EnableAddToGroup` or `EnableRemoveFromGroup`) |
| `EnableDisableAccount` | `false` | Disable the account |
| `EnableEnableAccount` | `false` | Re-enable a previously disabled account |
| `EnablePasswordChange` | `false` | Force password change on next sign-in |
| `EnableConfirmRisky` | `false` | Mark user as confirmed compromised in Identity Protection |
| `EnableCreateIncident` | `false` | Create Microsoft Sentinel incident |
| `EnableROPC` | `false` | Validate password via ROPC (only for plaintext passwords) |

### Other

| Parameter | Default | Description |
|-----------|---------|-------------|
| `PollingSchedule` | `0 */6 * * *` | Cron schedule (default: every 6 hours) |
| `InitialLookbackMinutes` | `600` | Lookback window for first run (minutes) |
| `EnableLogPlaintextPassword` | `false` | Write plaintext passwords to Log Analytics (customer decision) |
| `WorkspaceName` | `""` | Sentinel workspace name (required for `EnableCreateIncident`) |
| `WorkspaceLocation` | `""` | Workspace region |
| `WorkspaceResourceGroup` | `""` | Workspace resource group (for cross-RG deployments) |

## Log Analytics Tables

| Table | Source |
|-------|--------|
| `SOCRadar_Botnet_CL` | Botnet Data v2 |
| `SOCRadar_PII_CL` | PII Exposure v2 |
| `SOCRadar_Identity_CL` | Identity Intelligence |
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
