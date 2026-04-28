---
exp: 0115
title: GitHub release zip dependencies içermiyor → func publish remote-build zorunlu
date: 2026-04-28
severity: HIGH
project: entra-id
---

# Olay (Apr 28, fresh deploy)
- ARM template deploy → 7 resource Succeeded
- Function App: state=Running ama HTTP 503 (15+ dk)
- triggerFirstRun deployment script: Succeeded (ama function tetiklenemedi)
- Manuel `/admin/functions/{name}` POST → 503

# Kök neden
**v1.4.0 GitHub release zip = SOURCE-ONLY, dependencies YOK** (26 KB).

WEBSITE_RUN_FROM_PACKAGE = github URL ile Linux Consumption:
1. ZIP indirilir
2. /home/site/wwwroot'a extract edilir
3. Python source dosyaları orada (function_app.py, actions/, sources/, ...)
4. Ama `requirements.txt`'deki dependencies yüklenmemiş
5. Function host worker boot olamıyor → host runtime ServiceUnavailable

Linux Consumption Plan **WEBSITE_RUN_FROM_PACKAGE = URL** modunda Oryx build çalıştırmaz.
Dependencies için ya zip içinde olmaları gerek (lokal pip install --target) ya da
`func publish --remote-build` ile SCM Oryx tetiklenmeli.

# Çözüm
```bash
cd production/FunctionApp
# Geçici settings
az functionapp config appsettings set --name $SITE --resource-group $RG \
  --settings "WEBSITE_RUN_FROM_PACKAGE=1" "SCM_DO_BUILD_DURING_DEPLOYMENT=1" "ENABLE_ORYX_BUILD=1"

# func publish remote-build
func azure functionapp publish "$SITE" --python --build remote
# Beklenen:
#   "Performing remote build for functions project."
#   "Running pip install..."
#   "Deployment successful."
#   "Remote build succeeded!"

# Sonra restart (sync triggers BadRequest dönerse)
az functionapp restart --name $SITE --resource-group $RG

# 1-2 dk sonra HTTP 200
curl -s -o /dev/null -w "%{http_code}" "https://${SITE}.azurewebsites.net/"
```

# Production önerileri

## Seçenek A — GitHub release zip'i deps dahil oluştur (CI değiştir)
`.github/workflows/release.yml`:
```yaml
- name: Install deps locally
  run: |
    pip install --target=production/FunctionApp/.python_packages/lib/site-packages \
                --no-deps -r production/FunctionApp/requirements.txt
- name: Zip
  run: cd production/FunctionApp && zip -r FunctionApp.zip .
```

Sonra WEBSITE_RUN_FROM_PACKAGE=URL çalışır, Oryx gerekmez.

## Seçenek B — func publish kullan (manuel deploy)
ARM template'i sadece infrastructure için kullan. Function code'unu `func publish`
ile ayrıca deploy et. Customer onboarding'de bu adım dokümante edilmeli.

## Şu anki durum (recommended)
- **ARM template** infra deploy eder
- **GitHub release zip** source code ships (dev deneme + customer)
- Customer onboarding doc: "ARM deploy sonrası `func publish --remote-build` çalıştır"
- Veya: GitHub Actions'a deps dahil release oluşturma adımı eklenmeli (Tier 1 issue)

# Apr 28 fresh deploy kanıtı
- RG: `socradar-entraid-fresh-364439`
- Function: `socradar-entraid-uv7db2bxk5e2g`
- Sequence: ARM (Succeeded) → 503 15dk → `func publish --build remote` → restart → 200 → manuel trigger → audit yazıldı
- Audit'te 2 run: pii + botnet (ikisi de execute oldu, total=0 çünkü API checkpoint dedup)

# Action items
1. CI workflow'a deps inclusion ekle (Tier 1)
2. Customer README'de `func publish` adımı eklensin
3. ARM template'e SCM_DO_BUILD_DURING_DEPLOYMENT=1 + ENABLE_ORYX_BUILD=1 default settings olarak eklensin
