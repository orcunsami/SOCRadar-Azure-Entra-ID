---
id: EXP-0093
title: Stale checkpoint causes empty fetch after redeploy
severity: high
date: 2026-04-07
tags: [checkpoint, table-storage, deploy, testing]
---

# Eski Checkpoint Yeni Deploy'da Boş Veri Döndürür

## Problem
Eski deploy'dan kalan checkpoint `last_start_date=2026-04-07` diyor.
Yeni deploy preprod'dan eski test verilerini (2025) çekmeli ama checkpoint "bugünden başla" diyor → 0 kayıt.

## Çözüm
Deploy sonrası checkpoint'leri temizle:
```bash
STORAGE_KEY=$(az storage account keys list --account-name <name> --resource-group <rg> --query "[0].value" -o tsv)
az storage entity delete --table-name EntraIDState --partition-key botnet --row-key checkpoint --account-name <name> --account-key "$STORAGE_KEY"
az storage entity delete --table-name EntraIDState --partition-key pii --row-key checkpoint --account-name <name> --account-key "$STORAGE_KEY"
```

## Not
`--auth-mode login` çalışmıyor (Storage Table Data Contributor rolü user'da yok), `--account-key` kullan.
`InitialStartDate` parametresi sadece checkpoint yokken devreye girer — checkpoint varsa her zaman checkpoint'ten devam eder.
