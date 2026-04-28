---
exp: 0110
title: LAW Data Collector API ile direct inject — workbook demo data hazırlama
date: 2026-04-28
severity: medium
project: entra-id
---

# Senaryo
Demo öncesi workbook'ların KQL'leri tablolar olmadığında "Failed to resolve table" hatası veriyor.
Function run yaptırıp tablo create etmek vakit alıyor (cold start, dedup).

# Çözüm: Direct Data Collector API inject
Workspace key kullanarak HMAC-SHA256 imzalı POST ile LAW'a direct yazma.
Tablo otomatik oluşur (schema infer'lanır), 5-10 dk ingest delay sonrası KQL render eder.

# Python örneği
```python
import json, requests, datetime, base64, hmac, hashlib

WS_ID = "..."  # workspace customerId
WS_KEY = "..."  # primarySharedKey

def post(table, rows):
    body = json.dumps(rows)
    rfc1123date = datetime.datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")
    string_to_hash = f"POST\n{len(body.encode('utf-8'))}\napplication/json\nx-ms-date:{rfc1123date}\n/api/logs"
    decoded_key = base64.b64decode(WS_KEY)
    encoded_hash = base64.b64encode(hmac.new(decoded_key, string_to_hash.encode("utf-8"), hashlib.sha256).digest()).decode()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"SharedKey {WS_ID}:{encoded_hash}",
        "Log-Type": table,  # NOT _CL suffix — Azure ekler
        "x-ms-date": rfc1123date
    }
    return requests.post(f"https://{WS_ID}.ods.opinsights.azure.com/api/logs?api-version=2016-04-01",
                         data=body, headers=headers, timeout=30).status_code
```

# Gotcha
- `Log-Type` header'da `_CL` suffix YOK — Azure otomatik ekler
- Field naming: string `_s`, bool `_b`, double `_d`, datetime `_t` Azure tarafından ekleniyor
- 200 OK = kabul, ama LAW'a yansıma 5-10 dk
- Boş array gönderme — 200 dönse de tablo create olmaz

# Kullanım
- Demo öncesi workbook KQL'lerin çalışmasını GARANTI etmek için
- Function debug ederken sentetik data inject
- Customer onboarding'de "first-data" delay'i atlamak için
