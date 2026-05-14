# Changelog

All notable changes to the SOCRadar Entra ID Integration for Microsoft Sentinel
are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.1.0] — 2026-05-14

### Added

- **`EntraIdVerifiedDomains` parameter** — optional comma-separated allowlist
  of Microsoft Entra ID verified domains attached to the customer tenant
  (e.g. `acme.com,acme.io,acme.onmicrosoft.com`). When set, only records
  whose email domain matches one of these is forwarded to Microsoft Graph;
  others are written to LAW with `entra_status="skipped_domain_allowlist"`
  (audit only, no action). Saves Graph API quota and reduces audit noise
  on cross-domain SOCRadar matches. Leaving the parameter empty preserves
  v1.0 behavior (every record is looked up).
- **`domain_filtered` field** on the per-source audit summary line for
  visibility into how many records were filtered out of Graph lookups by
  the allowlist.

### Notes

- Case-insensitive exact match, no subdomain wildcards — list every
  domain explicitly (e.g. `mail.acme.com` does not match `acme.com`).
- One allowlist applies to every tenant in a multi-tenant
  (`EntraIdTenantIds`) deployment. Per-tenant allowlists may follow in a
  later release if needed.
- Backward compatible — empty `EntraIdVerifiedDomains` is the default and
  behaves identically to v1.0.

---

## [1.0.0] — 2026-05-12

Initial public release.

### Added

- **Three SOCRadar source pollers** — Botnet Data v2, PII Exposure v2, and VIP
  Protection v2. Configurable via `EnableBotnetSource`, `EnablePiiSource`,
  `EnableVipSource` ARM parameters.
- **Microsoft Entra ID lookup** via Microsoft Graph for every leaked
  credential, with secretless authentication using User-Assigned Managed
  Identity + Federated Identity Credential against the customer App
  Registration.
- **Multi-tenant lookup** from a single Function App deployment.
  `EntraIdTenantIds` accepts a comma-separated list of tenant IDs; each
  leaked credential is tried against every configured tenant in order,
  first match wins, and the matched tenant is recorded as
  `entra_tenant_id` on every Log Analytics record. Falls back to the
  legacy `EntraIdTenantId` (single tenant) when the CSV is empty.
- **Seven configurable remediation actions** in Entra ID — revoke sessions,
  add to quarantine group, remove from group, force password change,
  disable account, enable account, force MFA re-registration, confirm
  compromised in Identity Protection. All independently toggleable; only
  the Microsoft Graph permissions needed for the enabled actions have
  to be consented.
- **DCR-based Logs Ingestion** to four Sentinel custom tables —
  `SOCRadar_Botnet_CL`, `SOCRadar_PII_CL`, `SOCRadar_VIP_CL`,
  `SOCRadar_EntraID_Audit_CL`. Replaces the deprecated HTTP Data
  Collector API.
- **Four workbooks** — Botnet Data, PII Exposure, VIP Protection, and a
  combined operational dashboard. Each includes a `TenantId` dropdown
  parameter that filters every panel and a "Tenant Breakdown" panel
  summarising records per tenant.
- **SOCRadar alarm auto-resolve** — toggleable via `EnableResolveAlarm`.
- **Microsoft Sentinel incident creation** — toggleable via
  `EnableCreateIncident` for severity-tagged incidents on confirmed
  compromises.
- **Per-tenant 403 dropout** — if a tenant returns three consecutive 403s
  during a run (admin consent missing or revoked), it is removed from
  the lookup map for the remainder of that run. Healthy tenants
  continue to function.
- **Pagination resume with no-data-loss** — heavy backlogs are drained
  across multiple timer cycles. The `MAX_PAGES_PER_RUN` cap exits the
  fetcher gracefully and the checkpoint records the last drained page;
  the next run resumes from there.
- **Per-source + per-employee time budget** — guarantees the function
  exits cleanly within the 10 minute Linux Consumption hard timeout.
- **Documentation**:
  - `README.md` — Quick Deploy with single-tenant and multi-tenant
    examples.
  - `production/README.md` — full parameter reference.
  - `production/docs/multi-tenant-setup.md` — onboarding flow for
    holding companies / M&A scenarios, including the admin consent URL
    pattern and per-tenant SP verification.
  - `production/docs/troubleshooting.md` — diagnosis recipes for
    `AADSTS70001`, `AADSTS700016`, `consent_revoked` lifecycle events,
    empty workbook TenantId dropdown, etc.
- **Idempotent release workflow** — if the `vX.Y.Z` tag is pushed after
  a manual release was created, the workflow uploads the freshly built
  `FunctionApp.zip` with `--clobber` instead of failing.

### Notes

- Customer-facing app version: **1.0.0**.
- Content Hub Solution version: **3.0.0** (Microsoft V3 tool minimum —
  a separate namespace from the app version).
- `FunctionApp.zip` bundles production code + Python dependencies for
  Linux x86_64 (`manylinux2014`). Available at
  `https://github.com/orcunsami/SOCRadar-Azure-Entra-ID/releases/download/v1.0.0/FunctionApp.zip`.

[1.0.0]: https://github.com/orcunsami/SOCRadar-Azure-Entra-ID/releases/tag/v1.0.0
