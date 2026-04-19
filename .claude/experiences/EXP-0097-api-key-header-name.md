---
id: EXP-0097
title: SOCRadar API header API-Key (not X-Api-Key)
severity: medium
date: 2026-04-19
tags: [socradar, api, header, preprod, bug]
---

# SOCRadar API Header: `API-Key` (Not `X-Api-Key`)

## Problem
Preprod API'ye curl ile test ederken `X-Api-Key` header'ı kullandım → "API Key is missing!" veya 0 record döndü. Saatlerce "preprod'da veri yok" sandım.

## Sebep
Kod `API-Key` header'ı kullanıyor (`sources/botnet.py:41`, `sources/pii.py:40`). Ben curl'de `X-Api-Key` denedim. Farklı header name = API key algılanmıyor.

## Doğru
```bash
# DOĞRU
curl -H "API-Key: xxx" https://preprod.socradar.com/api/company/132/dark-web-monitoring/botnet-data/v2

# YANLIŞ
curl -H "X-Api-Key: xxx" ...
```

## Not
- Production kod `API-Key` kullanıyor — doğru çalışıyor
- Sorun sadece manuel curl test sırasında ortaya çıktı
- Koda bakmadan header name tahmin etme — her zaman source code'dan doğrula
