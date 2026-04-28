---
exp: 0107
title: az workbook command kaldırıldı, app-insights workbook kullan
date: 2026-04-28
severity: medium
project: entra-id
---

# Sorun
`scripts/deploy_workbooks.sh` 4 workbook deploy etmeye çalıştı, hepsi FAILED.
Hata `2>/dev/null` ile gizlenmişti.

# Kök neden
`az workbook create/update` komutu artık tanınmıyor (Azure CLI extension değişikliği):
> ERROR: 'workbook' is misspelled or not recognized by the system.

# Çözüm
`az monitor app-insights workbook create/update` kullan.
Extension: `application-insights` (zaten kurulu olabilir).

# Düzeltme yerleri
- scripts/deploy_workbooks.sh — komut + stderr loglama
- 2>/dev/null → 2>/tmp/wb_err (debug için)

# Doğrulama
```bash
az monitor app-insights workbook create --resource-group RG --name UUID \
  --display-name "..." --category sentinel --kind shared \
  --source-id WORKSPACE_ID --serialized-data "$json"
```
