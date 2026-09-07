# SOCRadar Entra ID Integration for Microsoft Sentinel

[![Deploy to Azure](https://aka.ms/deploytoazurebutton)](https://portal.azure.com/#create/Microsoft.Template/uri/https%3A%2F%2Fraw.githubusercontent.com%2Forcunsami%2FSOCRadar-Azure-Entra-ID%2Fmaster%2Fproduction%2Fazuredeploy.json)
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

### Reusing an App Registration you already consented

Put its client ID in `EntraIdClientId` and the deployment stops creating a new
one. Set **`SkipFicCreation=true`** as well. The federated credential is added
by the deployment's own managed identity, and that identity owns only an App
Registration it created itself — against yours it gets *Insufficient
privileges*, and that failure fails the whole deployment.

Then an owner of the App Registration adds the credential once:

```bash
RG=<resource group>            # the one you deployed into
APP=<EntraIdClientId>
TENANT=$(az account show --query tenantId -o tsv)
PRINCIPAL=$(az identity show -g "$RG" -n SOCRadar-EntraID-MI --query principalId -o tsv)

az ad app federated-credential create --id "$APP" --parameters "{
  \"name\": \"socradar-entraid-$RG-uami\",
  \"issuer\": \"https://login.microsoftonline.com/$TENANT/v2.0\",
  \"subject\": \"$PRINCIPAL\",
  \"audiences\": [\"api://AzureADTokenExchange\"]
}"
```

Restart the Function App afterwards. Being an owner of the App Registration is
enough here; no directory admin role is needed.

## Deploy

Click **Deploy to Azure** at the top. Fill the form. Click **Review + create** → **Create**. Function App starts polling on its next timer cycle (default: every 6 hours).

## How the code gets there

The template creates the Function App empty (`WEBSITE_RUN_FROM_PACKAGE=1`) and a deployment
script downloads `PackageUri`, verifies it is a readable zip, uploads it to the storage account
this template creates, and points the app at that blob with a read-only token. Azure stopped
accepting the creation of a Linux consumption Function App whose `WEBSITE_RUN_FROM_PACKAGE` is
a URL that redirects, and a GitHub release download URL always redirects.

One consequence worth knowing: **an installation keeps the package it was installed with.** The
release URL is read once, at install time; a later release does not reach an existing
installation. Redeploy to pick it up. Before September 2026 the app read that URL on every cold
start, so a new release arrived on its own.

If the deployment fails at `triggerFirstRun`, the message says which step: an unreachable
package URL, a download that is not a readable zip, a package that never reached the container
the app reloads from, or an app that indexed no function within the poll window. The script
retries the settings read until its role assignment is effective, retries the upload up to
six times, and restarts the app once the package is staged -- writing the pointer alone was
measured not to make the host reload it. If the deployment fails, the diagnostic container
and its storage account stay in the resource group for 26 hours -- the documented ceiling --
so the log can still be read the next morning; delete them once you are done. A successful
deployment leaves neither behind.

It reports success only when both readings agree: the package pointer names a blob in the
`function-releases` container **and** the app has indexed a function. The count alone is not
enough -- an app whose package was staged somewhere else keeps reporting a function to Azure
Resource Manager while its host answers 503 from the next restart onwards.

A redeploy rewrites the package pointer, so it has to push again. If every attempt fails there,
the deployment reports a failure **and the app is left with no code** -- it does not keep
serving the package it had. Recovery does not need a rebuild: the previous package is still in
the `function-releases` container of the app's storage account, and pointing
`WEBSITE_RUN_FROM_PACKAGE` back at that blob brings the app back while you retry.
Rotating the storage account keys invalidates the read token inside that pointer, so the app
loses its code at the next restart -- issue a new token for the same blob and write the
pointer back.

One red row in **Resource group -> Deployments** is not ours and is harmless:
`Failure-Anomalies-Alert-Rule-Deployment-*`. Azure creates it by itself when the
Application Insights component appears, and it fails on a subscription that has
not registered the `Microsoft.AlertsManagement` provider (measured 7 Sep 2026).
Nothing in this template refers to it and the integration works without it;
register that provider if you want the smart-detection alert.

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
