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

## Required Permissions (read this first)

| Deployer's Microsoft Entra ID role | Post-deploy experience | Form values |
|------------------------------------|------------------------|-------------|
| **Cloud Application Administrator** (or Global Admin) | 🟢 Zero post-deploy steps — App Registration, federated credential, and admin consent are all granted inline | `GrantAdminConsent=true` |
| **Application Administrator** | 🟡 One manual click after deploy: **App registrations → SOCRadar Entra ID Integration → API permissions → Grant admin consent** | `GrantAdminConsent=false` *(default)* |
| **No Entra ID admin role** | 🔴 Fallback only — contact SOCRadar for the reuse-path setup | — |

On the Azure side, the deployer needs **Contributor** (or Owner) on the target subscription / resource group. **Owner is not required.**

See [`production/README.md` → Required Permissions](production/README.md#required-permissions) for the full prerequisite list, including pre-deploy info you must gather (tenant IDs, verified domains, SOCRadar API key, etc.).

## Deploy

Click **Deploy to Azure** at the top. Fill the form. Click **Review + create** → **Create**. Function App starts polling on its next timer cycle (default: every 6 hours).

## Documentation

- **[Deployment guide + parameter reference](production/README.md)** — what each form field means, what gets deployed, who can deploy, verification queries

## Capabilities at a glance

- **3 SOCRadar dark-web sources** — Botnet Data (info-stealer malware logs), PII Exposure (data-breach surfacing), VIP Protection (executives & high-value users)
- **Identity scoping** — multi-tenant lookup (`EntraIdTenantIds` CSV, MSSP / holdings / M&A) + optional verified-domain allowlist (`EntraIdVerifiedDomains` CSV) that gates Microsoft Graph lookups to in-scope domains only
- **11 independently togglable remediation actions** — see table below
- **4 custom Log Analytics tables** via DCR-based Logs Ingestion (HTTP Data Collector deprecation already handled) + **4 Sentinel workbooks** with multi-tenant filter dropdowns
- **Secretless authentication** — Workload Identity Federation (UAMI → Federated Credential → App Registration). No client secrets, no key rotation
- **Operational resilience** — per-tenant 403 dropout, per-employee + per-source time budgets, pagination resume across function timeouts, App Insights tracing, per-record status enum (`found`, `not_found`, `lookup_permission_denied`, `skipped_domain_allowlist`, `compromised`, ...)

### Sources Monitored

| Source | What it detects |
|--------|-----------------|
| **Botnet Data** | Employee credentials harvested by botnets (info-stealer malware logs) |
| **PII Exposure** | Employee credentials surfacing in data breaches |
| **VIP Protection** | Exposures of executives and high-value users |

### Actions Available

When a leaked identity is found in Entra ID, any combination can run automatically:

| Action | Default | Impact |
|--------|---------|--------|
| **Revoke session** — invalidate all active sign-in tokens | ✓ on | Low — forces re-login |
| **Force password change** at next sign-in | off | Medium — user prompted on next login |
| **Disable account** — block sign-in entirely | off | High — full lockout |
| **Re-enable account** | off | — |
| **Force MFA re-registration** — delete non-password auth methods, force re-enrol | off | High — user must re-enrol MFA |
| **Add to quarantine group** + restricted Conditional Access policy | off | Medium |
| **Remove from group** | off | — |
| **Mark as Confirmed Compromised** — feeds Identity Protection (Entra ID P1/P2) | off | Low |
| **Create Microsoft Sentinel incident** | off | — |
| **Resolve SOCRadar alarm** on successful remediation | off | — |
| **ROPC password validation** (advanced) | off | — |

Defaults are conservative — only **Revoke session** runs out of the box. Flip the rest on after validating with the [Customer Acceptance Test runbook](../to-Radargoger/CUSTOMER-TEST-RUNBOOK.md) (shipped with the Standalone delivery bundle).

See [`production/README.md` → Capabilities](production/README.md#capabilities) for the full feature inventory including DCR schema, workbook tiles, lifecycle events, and operational guarantees.

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
