---
exp: 0114
title: Fresh deployment baştan sona protokolü — sıfırdan kanıt
date: 2026-04-28
severity: medium
project: entra-id
---

# Senaryo
Demo öncesi tüm akışın baştan sona yeniden deploy edilebildiğini kanıtlama.
Yeni RG + yeni workspace + yeni Function App + yeni FIC. End-to-end repeatability.

# Adımlar (kanıtlandı)

## 1. Pre-flight (önemli kararlar)
- **Yeni RG ismi:** `socradar-entraid-fresh-{timestamp}` (soft-delete trap'ten kaçın)
- **Yeni workspace ismi:** `entraid-fresh-ws-{timestamp}` (14 gün soft-delete)
- **App Registration:** AYNI (b0afca82-...) — granted permissions korunur
- **API key:** AYNI Function App'te olan, preprod+prod ikisinde de geçerli (EXP-0113)

## 2. deploy.sh pre-requirements
Script gereksinimi: workspace ÖNCEDEN var olmalı (verifyWorkspace adımı).
Bu yüzden:
```bash
az group create --name "$NEW_RG" --location northeurope
az monitor log-analytics workspace create --resource-group "$NEW_RG" \
  --workspace-name "$NEW_WS" --location northeurope
# THEN deploy.sh
```

## 3. POLLING_SCHEDULE quoting bug
deploy.config'te `POLLING_SCHEDULE=0 */30 * * * *` UNQUOTED ise bash `*/30` glob expand eder.
**Çözüm:** her zaman quote et: `POLLING_SCHEDULE="0 0 */6 * * *"`

## 4. Workbook deployment script bug
`scripts/deploy.sh` workbook deploy adımında `az workbook` (legacy) kullanıyor.
Tümü "may already exist" warning verir (asıl error gizlenir).

**Çözüm:** ARM deploy bittikten sonra ayrıca `bash scripts/deploy_workbooks.sh` çalıştır
(bu fixed versiyon `az monitor app-insights workbook` kullanır).

## 5. FIC re-create (deploy.sh otomatik)
Yeni UAMI yeni principalId getirir. deploy.sh `[6/7]` adımı eski FIC'i siler, yeni UAMI ile
yeni FIC create eder. Bu adım deploy.sh'da otomatik (EXP-0106 önlemi).

```
Deleting old FIC (subject=<old_principal>)...
Creating FIC: UAMI <new_clientId> → App Registration <app_clientId>
```

## 6. Function cold start (5-15 dk)
WEBSITE_RUN_FROM_PACKAGE değişimi sonrası HTTP 503 normal.
- Linux Consumption: ZIP download + extract + venv setup
- triggerFirstRun deployment script ARM tarafından çağrılır (paralel)
- Sonuç: function ilk run'ı otomatik gerçekleşir (kullanıcı tetiklemeye gerek yok)

## 7. Sentinel onboarding (opsiyonel, ENABLE_CREATE_INCIDENT için)
ARM template'de YOK. Script bitince manuel:
```bash
az rest --method PUT \
  --url ".../onboardingStates/default?api-version=2024-03-01" \
  --body '{"properties":{"customerManagedKey":false}}'
```

# Kanıt — Apr 28, 2026 fresh deployment
- **RG:** `socradar-entraid-fresh-364439`
- **Function App:** `socradar-entraid-uv7db2bxk5e2g`
- **Workspace:** `entraid-fresh-ws-364439`
- **Workbooks:** 4 deployed (Botnet, PII, VIP, Combined)
- **Resources:** 7 (workspace + UAMI + AI + storage + plan + function + deployment script)
- **FIC:** new UAMI ea776907 → app b0afca82 ✓
- **Deploy süresi:** ~10 dk (RG create + ARM + workbook + FIC + verify)

# Kontrol listesi (her fresh deploy için)
- [ ] Yeni RG + workspace ismi seç (timestamp suffix)
- [ ] deploy.config doldur, **POLLING_SCHEDULE quoted**
- [ ] RG + workspace pre-create
- [ ] `bash scripts/deploy.sh` (ARM + Function + FIC)
- [ ] **Ayrıca** `bash scripts/deploy_workbooks.sh` (fixed versiyon)
- [ ] Sentinel onboard (`az rest PUT onboardingStates/default`)
- [ ] Function HTTP 200 bekle (5-15 dk)
- [ ] Audit ilk run'ı bekle (run_on_startup veya 6h timer)
- [ ] LAW tablolarını verify et
