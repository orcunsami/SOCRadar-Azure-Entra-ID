# Multi-Tenant Setup

The SOCRadar Entra ID Integration can monitor leaked credentials across
**multiple Entra ID tenants from a single Function App deployment**. This is
useful for holding companies, M&A scenarios, or any organisation that has
more than one Microsoft Entra directory in its estate.

This document walks through the one-time setup. The runtime behaviour is
documented in the root [README](../../README.md).

---

## Auth model in one picture

```
   Subscription tenant (where you deploy the Function App)
   ┌─────────────────────────────────────────────────────────┐
   │   User-Assigned Managed Identity (UAMI)                 │
   │              │                                          │
   │              │ Federated Identity Credential (1 FIC)    │
   │              ▼                                          │
   │   Primary Entra Tenant                                  │
   │   ┌────────────────────────────────┐                    │
   │   │ App Registration (multi-tenant)│                    │
   │   │ signInAudience =               │                    │
   │   │   AzureADMultipleOrgs          │                    │
   │   │ + Graph application perms      │                    │
   │   └────────────────┬───────────────┘                    │
   └────────────────────┼────────────────────────────────────┘
                        │ admin consent in each additional tenant
                        ▼
         ┌──────────────────────────────────────┐
         │  Service Principal (auto-created)    │  ← Tenant B
         │  Service Principal (auto-created)    │  ← Tenant C
         │  Service Principal (auto-created)    │  ← Tenant D
         └──────────────────────────────────────┘
```

Only the **primary** tenant has a Federated Identity Credential on the app.
The additional tenants don't need one — once the same multi-tenant app is
consented, a service principal representing the app appears there, and the
UAMI's token (signed by the subscription tenant) is accepted by every
service principal for the same app.

**This means one FIC unlocks N tenants.** You do not multiply the
[20-FIC-per-app limit](https://learn.microsoft.com/en-us/entra/workload-id/workload-identity-federation-considerations#general-federated-identity-credential-considerations)
by the number of customer tenants.

---

## Prerequisites

- One Entra ID tenant where you have **App registrations administrator** or
  higher privileges. This is the "primary" tenant — typically your
  subscription tenant.
- Tenant admin contact for every additional Entra tenant you want to
  monitor. They need to click an admin-consent link.
- The same Microsoft Graph application permissions you'd grant for a
  single-tenant install (see the table in the main README).

---

## Step 1 — Create or reconfigure the App Registration

1. Sign in to the **primary** Entra tenant.
2. Microsoft Entra ID → App registrations → either **New registration** or
   open your existing SOCRadar app.
3. **Authentication** blade →
   **Supported account types** → choose
   **Accounts in any organizational directory (Any Microsoft Entra ID
   tenant — Multitenant)**.
4. **API permissions** → add the same Graph application permissions as the
   single-tenant install:
   - `User.Read.All`
   - `User.RevokeSessions.All`
   - `GroupMember.ReadWrite.All`
   - `User.EnableDisableAccount.All`
   - `User-PasswordProfile.ReadWrite.All`
   - `IdentityRiskyUser.ReadWrite.All`
   - `UserAuthenticationMethod.ReadWrite.All`
5. Click **Grant admin consent for {primary tenant}**.
6. Copy the **Application (client) ID** — you'll feed this to the ARM
   template as `EntraIdClientId`.

The Federated Identity Credential will be created by the deployment script
(or by the ARM template, depending on how you deploy). Its issuer is the
**subscription tenant**, and its subject is the UAMI's `principalId`. You
do not need to add any further FICs.

---

## Step 2 — Get admin consent in every additional tenant

For each additional tenant whose users you want to monitor, send the
tenant's admin this URL:

```
https://login.microsoftonline.com/{TENANT_ID}/adminconsent?client_id={APP_CLIENT_ID}
```

Replace `{TENANT_ID}` with the additional tenant's Directory ID and
`{APP_CLIENT_ID}` with the App Registration client ID from step 1.

When the admin clicks **Accept**, Azure creates a service principal for
your app in their tenant — without modifying any password or secret. The
consent page lists every Graph permission the app requests; the admin can
audit them before accepting.

**Sanity check**: in the additional tenant, navigate to **Enterprise
applications** → **All applications** → search for the app name. If the SP
is listed, consent succeeded.

---

## Step 3 — Configure the Function App

Pass every tenant you want to monitor (primary first) as a comma-separated
list to the ARM template parameter `EntraIdTenantIds`:

```bash
az deployment group create \
  --resource-group my-socradar-rg \
  --template-uri https://raw.githubusercontent.com/orcunsami/SOCRadar-Azure-Entra-ID/master/production/azuredeploy.json \
  --parameters \
    WorkspaceName="my-sentinel-ws" \
    WorkspaceLocation="northeurope" \
    SocradarApiKey="<key>" \
    SocradarCompanyId="<id>" \
    EntraIdTenantIds="00000000-0000-0000-0000-aaaaaaaaaaaa,00000000-0000-0000-0000-bbbbbbbbbbbb" \
    EntraIdClientId="<client-id>"
```

The Function App reads this via the `ENTRA_TENANT_IDS` app setting. At
runtime, every leaked credential is looked up against each tenant in
order; the first tenant whose Graph returns a user wins, and all
remediation actions (revoke sessions, disable account, etc.) run against
that tenant.

Legacy single-tenant deployments using `EntraIdTenantId` continue to work
unchanged — when `EntraIdTenantIds` is empty, the integration falls back
to the single legacy ID.

---

## What ends up in Log Analytics

Every leaked credential record in `SOCRadar_Botnet_CL`, `SOCRadar_PII_CL`
and `SOCRadar_VIP_CL` now includes an `entra_tenant_id` column that
identifies which tenant the user was found in. The bundled workbooks
include a `TenantId` dropdown and a `Tenant Breakdown` panel that
summarises records per tenant.

For ad-hoc analysis:

```kql
SOCRadar_Botnet_CL
| where entra_status == "found"
| summarize records=count() by entra_tenant_id
| order by records desc
```

---

## Limits and gotchas

| Concern | Details |
|---------|---------|
| **20 FIC per app** | Not a concern — we use ONE FIC. Adding more tenants does not add FICs. |
| **Graph throttling** | Throttling is evaluated per app per tenant. Heavy load is unlikely to trip a single tenant, but if a customer has 5000+ users across multiple tenants, watch for 429s. |
| **Same email in multiple tenants** | First match wins (tenants are tried in `EntraIdTenantIds` order). The losing tenants are not touched. |
| **Per-tenant consent revocation** | If a tenant admin revokes consent, the integration logs a `consent_revoked` lifecycle event for that tenant and stops querying it for the rest of the run. Other tenants keep working. |
| **Adding a tenant later** | Append the new tenant ID to the CSV, redeploy (ARM template merges app settings). The admin still has to click the consent link. |
| **Removing a tenant** | Remove the tenant ID from the CSV and redeploy. The service principal in the removed tenant is left in place — the tenant's admin can delete it from Enterprise Applications if desired. |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| User found in primary tenant only, never in additional tenants | Consent missing in additional tenant | Send the admin the consent URL again; verify the SP appears in Enterprise Applications. |
| `consent_revoked` lifecycle event in `SOCRadar_EntraID_Audit_CL` | Admin revoked the app's consent in that tenant | Re-consent. |
| Token acquisition fails with `AADSTS700016` (app not found) | Multi-tenant app is single-tenant in the additional tenant's directory | Verify the App Registration's `signInAudience` is `AzureADMultipleOrgs` in the **primary** tenant. |
| `AADSTS70001` (app disabled in tenant) | The additional tenant disabled the service principal | Tenant admin re-enables in Enterprise Applications. |
| Workbook's `TenantId` dropdown is empty | No records with `entra_tenant_id` yet (first run) | Wait for the first poll cycle to complete, or query the source tables directly. |

For deeper diagnostics see [troubleshooting.md](./troubleshooting.md).
