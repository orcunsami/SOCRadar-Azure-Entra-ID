# Recorded Future Identity Solution — Analiz

**Kaynak:** https://github.com/Azure/Azure-Sentinel/tree/master/Solutions/Recorded%20Future%20Identity
**Tarih:** Mar 2026
**Amaç:** SOCRadar Entra ID entegrasyonu için referans

---

## Mimari

%100 Logic App (Consumption). Function App yok.

```
RF API  ←→  Custom Connector (RFI-CustomConnector-0-2-0)
                      |
          Logic App (Alert Importer)
           /           |           \
      azuread      azureadip    azuresentinel (opsiyonel)
   (Graph API)  (Identity Prot.)       |
       |                          LAW (opsiyonel)
  user lookup
  group add
```

---

## Playbook'lar

### Mevcut (v4.x — Playbook Alert Based)

| Playbook | Bağlantılar | Amaç |
|----------|-------------|------|
| RFI-CustomConnector-0-2-0 | — | RF API custom connector |
| RFI-Playbook-Alert-Importer | RF + azuread + azureadip | Base: alert ingest + Entra ID remediation |
| RFI-Playbook-Alert-Importer-LAW | + azureloganalyticsdatacollector | + Log Analytics'e kaydet |
| RFI-Playbook-Alert-Importer-LAW-Sentinel | + azuresentinel | + Sentinel incident aç |

**Trigger:** Recurrence 15 dakika (startTime offset yok — bizim 3dk pattern'imizden farklı)

### Eski (v3.0 — Identity API Based, Modüler)

5 ayrı Logic App: search-workforce-user, search-external-user, add-to-group, confirm-risky, lookup-and-save

---

## Workflow (En Tam Playbook: LAW-Sentinel)

1. RF API `/playbook-alerts/search` — lookback_days + priorities filter
2. For Each alert:
   - UPN hesapla (`entra_id_domain` parametresiyle domain mapping)
   - Entra ID'de kullanıcı var mı? → `GET /v1.0/users/{upn}`
   - Güvenlik grubuna ekle → `POST /v1.0/groups/{group_id}/members/$ref`
   - Risky olarak işaretle → `POST /beta/riskyUsers/confirmCompromised`
   - Detaylı lookup → RF API `/playbook-alerts/{id}`
   - LAW'a kaydet (opsiyonel)
   - Sentinel incident aç (opsiyonel)
   - RF'ye güncelle → `/playbook-alerts/update` (actions taken)

---

## Entra ID Connectors

### azuread (Microsoft Graph)
- **İzin:** `Group.ReadWrite.All`, `User.ReadWrite.All`, `Directory.ReadWrite.All`
- **Auth:** OAuth (Service Principal veya Managed Identity)
- **Calls:**
  - `GET /v1.0/users/{upn}` — kullanıcı var mı?
  - `POST /v1.0/groups/{group_id}/members/$ref` — gruba ekle

### azureadip (Azure AD Identity Protection)
- **İzin:** `IdentityRiskyUser.ReadWrite.All`
- **Auth:** OAuth (Security Administrator role)
- **Call:** `POST /beta/riskyUsers/confirmCompromised`
- **Gereksinim:** Entra ID P1 veya P2 lisans!

### Domain Mapping
`entra_id_domain` parametresi: `leak@sirket.com` → `leak@sirket.onmicrosoft.com`

---

## RF Identity API (Custom Connector)

**Host:** `api.recordedfuture.com`
**Base Path:** `/gw/azure-identity`
**Auth:** `X-RFToken` header

| Endpoint | Method | Açıklama |
|----------|--------|----------|
| `/playbook-alerts/search` | POST | Novel identity exposure alert'lerini ara (mevcut) |
| `/playbook-alerts/{id}` | GET | Alert detayı |
| `/playbook-alerts/update` | PUT | Alert status güncelle (actions taken) |
| `/credentials/lookup` | POST | Credential lookup (v3.0) |
| `/credentials/search` | POST | Domain bazlı credential ara (v3.0) |

---

## ARM Template Pattern'leri

- `contentVersion: 1.0.0.0` (playbook), `0.2.0.0` (custom connector)
- Location: `[resourceGroup().location]` — cross-region handling YOK (bizden basit)
- Custom connector: `Microsoft.Web/customApis` (inline Swagger)
- API Connection'lar: ayrı top-level ARM resource
- `expressionEvaluationOptions`, cross-RG: YOK (daha basit deployment)
- Recurrence: 15dk, **startTime parametresi yok** (bizim 3dk delayed start pattern'imizden farklı)

---

## Content Hub Package

- Data file version: `3.1.2`, `Is1PConnector: false`, `TemplateSpec: true`
- Package: 120KB mainTemplate, 5 resources (4 contentTemplates + 1 contentPackage)
- Workbook yok, Hunting Query yok — sadece playbook'lar
- **Not:** Data file'da developer'ın local path var (bizim de aynı sorunla karşılaşmıştık)

---

## RF vs SOCRadar Karşılaştırma (Özet)

| | RF Identity | SOCRadar (Hedef) |
|--|-------------|-----------------|
| Data kaynağı | RF Playbook Alerts API | SOCRadar Identity Intelligence API |
| Mimari | Logic App only | TBD (Logic App muhtemelen) |
| Entra ID bağlantısı | azuread + azureadip connector | azuread + azureadip (benzer olacak) |
| Password validation | Yok | Var (SOCRadar platform feature) |
| Incident oluşturma | Opsiyonel | TBD |
| Custom Connector | Var (RF API için) | Var (SOCRadar API için) veya direkt HTTP |
| Cross-RG | Yok | Var (bizim standard) |
| Workbook | Yok | Muhtemelen var |
