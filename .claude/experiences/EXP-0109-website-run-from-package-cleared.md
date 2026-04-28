---
exp: 0109
title: WEBSITE_RUN_FROM_PACKAGE settings update sırasında silinebiliyor
date: 2026-04-28
severity: HIGH
project: entra-id
---

# Olay
- Function App stop/start cycle sonrası timer trigger çalışmadı
- Manuel `/admin/functions/{name}` POST → HTTP 202 ama execute olmadı
- Audit'te 30+ dk yeni run yok

# Kök neden
**WEBSITE_RUN_FROM_PACKAGE app setting BOŞ**.
Önceki session'da `az functionapp config appsettings set --settings MAX_PAGES_PER_RUN=1` çalıştırdığımda
veya başka bir tek-key set işleminde mevcut ayar kayboldu.

ARM template başlangıçta `https://github.com/orcunsami/SOCRadar-Azure-Entra-ID/releases/latest/download/FunctionApp.zip`
set ediyor. Ama `az functionapp config appsettings set` komutu bazen mevcut diğer ayarları override edebiliyor
(özellikle çoklu --settings ile).

# Belirti
- Function App: Running
- Function code: yüklü görünüyor (`az functionapp function show` OK)
- Manuel trigger: 202 Accepted
- Ama execute hiç olmuyor → audit yok

# Çözüm
```bash
az functionapp config appsettings set --name $SITE --resource-group $RG \
  --settings "WEBSITE_RUN_FROM_PACKAGE=https://github.com/orcunsami/SOCRadar-Azure-Entra-ID/releases/latest/download/FunctionApp.zip"

az functionapp restart --name $SITE --resource-group $RG
# 5-10 dk cold start (package re-download)
```

# Önlem
Her `appsettings set` öncesi `appsettings list` ile mevcut WEBSITE_RUN_FROM_PACKAGE
değerini doğrula. Veya redundant set yap (her zaman bu key'i de gönder).

# Doğrulama komutu (her deploy sonrası ZORUNLU)
```bash
az functionapp config appsettings list --name $SITE --resource-group $RG \
  --query "[?name=='WEBSITE_RUN_FROM_PACKAGE'].value | [0]" -o tsv
# BOŞ DEĞİL olmalı, /releases/ içermeli
```
