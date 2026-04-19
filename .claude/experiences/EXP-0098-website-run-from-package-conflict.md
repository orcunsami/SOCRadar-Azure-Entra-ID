---
id: EXP-0098
title: WEBSITE_RUN_FROM_PACKAGE URL blocks func publish
severity: medium
date: 2026-04-19
tags: [arm-template, func-publish, deployment, website-run-from-package]
---

# WEBSITE_RUN_FROM_PACKAGE URL vs func publish Çakışması

## Problem
ARM template `WEBSITE_RUN_FROM_PACKAGE` app setting'i bir GitHub release URL'sine point ediyor:
```json
"value": "https://github.com/.../releases/download/v1.3.0/FunctionApp.zip"
```

ARM deploy sonrası `func azure functionapp publish --remote-build` çalıştırınca:
```
Error: Run-From-Zip is set to a remote URL using WEBSITE_RUN_FROM_PACKAGE.
Deployment is not supported in this configuration.
```

## Sebep
Azure, URL'den zip çekerken func publish'in kendi zip'ini yüklemesine izin vermiyor. İkisi çakışıyor.

## Çözüm
func publish yapmadan önce `WEBSITE_RUN_FROM_PACKAGE` değerini `1` yap:
```bash
# 1 = "son yüklenen zip'i kullan" (URL değil)
az rest --method PUT ... --body '{"properties":{"WEBSITE_RUN_FROM_PACKAGE":"1"}}'
# Sonra:
func azure functionapp publish ... --remote-build
```

## Not
- ARM redeploy yapınca URL geri gelir — her func publish öncesi 1'e çekmek lazım
- Production'da func publish kullanılmaz (ARM + release zip yeterli)
- Test sırasında sık karşılaşılıyor
