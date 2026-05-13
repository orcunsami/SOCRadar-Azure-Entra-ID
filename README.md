# SOCRadar Entra ID Integration for Microsoft Sentinel

[![Deploy to Azure](https://aka.ms/deploytoazurebutton)](https://portal.azure.com/#create/Microsoft.Template/uri/https%3A%2F%2Fraw.githubusercontent.com%2Forcunsami%2FSOCRadar-Azure-Entra-ID%2Fv1.0.0%2Fproduction%2Fazuredeploy.json)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

Automated remediation for **leaked employee credentials** detected by SOCRadar — pulls Botnet, PII Exposure, and VIP Protection alerts, looks up matching users in Microsoft Entra ID, and takes configurable response actions (revoke sessions, force MFA re-registration, disable account, add to quarantine group, etc.). All findings are written to Microsoft Sentinel custom tables for triage.

## How It Works

```
SOCRadar Platform (Botnet / PII / VIP)
         │
         ▼  every 6 hours (configurable)
  Azure Function App (Python, timer trigger)
         │
   ┌─────┴─────┐
   │           │
Microsoft   Microsoft Sentinel
 Entra ID   (Log Analytics)
   │           │
   │           └── 4 Workbooks: Botnet / PII / VIP / Combined
   │
   └── Actions: revoke session, disable account, force MFA,
                add to quarantine group, password change, etc.
                (each action is independently configurable)
```

## Deploy

Click **Deploy to Azure** above. Fill the form. Click **Create**. When deployment completes:

1. Open the Azure portal → **Microsoft Entra ID** → **App registrations**
2. Open the newly created **SOCRadar Entra ID Integration** App Registration
3. **API permissions** → **Grant admin consent for [your tenant]** → confirm

That's the final step. The Function App starts polling on its next timer cycle.

> **Cloud Application Administrator?** Set `GrantAdminConsent=true` in the form and consent is granted automatically — fully zero-touch deployment.

## Documentation

- **[Deployment guide + parameter reference](production/README.md)** — what each form field means, what gets deployed, who can deploy, verification queries

## Sources Monitored

| Source | What it detects |
|--------|-----------------|
| **Botnet Data** | Employee credentials harvested by botnets (info-stealer malware logs) |
| **PII Exposure** | Employee credentials surfacing in data breaches |
| **VIP Protection** | Exposures of executives and high-value users |

## Actions Available

When a leaked identity is found in Entra ID, the Function App can take any combination of:

- **Revoke session** — invalidates all active sign-in tokens
- **Force password change** — flags account for password reset at next sign-in
- **Disable account** — blocks sign-in entirely
- **Force MFA re-registration** — deletes all non-password authentication methods, forcing the user to re-enroll
- **Add to quarantine group** — segregates the user into a restricted security group
- **Mark as confirmed compromised** — feeds Identity Protection (Entra ID P1/P2)
- **Resolve SOCRadar alarm** — closes the alarm on the SOCRadar Platform after successful remediation

Each action is independently togglable in the deployment parameters. High-impact actions (account disable, MFA reset, password reset) are **off by default**.

## Security

- **Secretless authentication** — uses Workload Identity Federation (UAMI + Federated Identity Credential). No client secrets, no password rotation, no expiring keys.
- **Least-privilege** — only the Microsoft Graph permissions for enabled actions are requested. Disabled actions = no permission required at runtime.
- **Password handling** — passwords are sanitized at fetch time. Only `password_masked` and `password_present` are written to Log Analytics by default.

## Multi-Tenant (MSSP / Holdings)

For monitoring multiple Entra directories from a single deployment, set `EntraIdTenantIds` to a comma-separated list of tenant IDs. The primary tenant (first in the list) hosts the multi-tenant App Registration; secondary tenants grant admin consent to the same App Registration in their own portals.

See **[production/README.md](production/README.md)** for details.

## Support

- **Issues**: open a GitHub issue
- **SOCRadar Platform questions**: contact your SOCRadar account manager
