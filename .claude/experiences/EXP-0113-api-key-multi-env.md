---
exp: 0113
title: SOCRadar API key — preprod ve prod aynı key, farklı veri
date: 2026-04-28
severity: low
project: entra-id
---

# Bulgu
Function App'teki SOCRADAR_API_KEY (`5559...dfcce8`) **hem preprod hem prod**
ortamlarında aynı company ID için (132) HTTP 200 dönüyor.

| Ortam | URL | Company 132 PII | Sonuç |
|---|---|---|---|
| preprod | preprod.socradar.com | testradar2/3 (sentetik) | 200 ✓ |
| **prod** | **platform.socradar.com** | **gerçek alarmlar** (joh.bakolor@... gibi) | **200 ✓** |
| prod | platform.socradar.com | company 330 | **401** (key yetkili değil) |

# Sonuçlar
1. **API key per-tenant değil, per-company.** Aynı key birden fazla ortamda farklı verilere
   erişebilir, yeter ki o company ID'ye yetkilendirilmiş olsun.
2. **Demo → Prod switch sadece BASE_URL değiştir**, key+company aynı kalabilir.
3. **Yanlış company ID = 401**, yanlış URL = 404 (eski endpoint path) veya 401 (yeni endpoint).

# CLAUDE.md'de eski test key
`cd7f92376d044c03b074c91071b3c12a69b743f511ed4ddf8f88eb1d76694669` → bu eski/dev key,
production'da artık geçersiz (401). CLAUDE.md güncelleneceği zaman bu temizlenmeli.

# Production switch komutu
```bash
az functionapp config appsettings set --name $SITE --resource-group $RG \
  --settings SOCRADAR_BASE_URL=https://platform.socradar.com
az functionapp restart --name $SITE --resource-group $RG
```

API key + Company ID değişmez. Sadece base URL değişir.

# Smoke test (her ortam için)
```bash
KEY="..."
COMPANY="..."
URL="https://platform.socradar.com"  # veya preprod
curl -s -m 10 -H "API-Key: $KEY" \
  "${URL}/api/company/${COMPANY}/dark-web-monitoring/pii-exposure/v2?limit=1" \
  -w "HTTP %{http_code}\n" -o /dev/null
# 200 = OK, 401 = wrong key/company, 404 = wrong path
```
