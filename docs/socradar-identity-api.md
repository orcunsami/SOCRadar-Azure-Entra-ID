# SOCRadar Identity Access Intelligence API

**Base URL:** `https://platform.socradar.com/api/identity/intelligence/`
**Auth:** `Api-Key: YOUR_SECRET_TOKEN` header
**Rate Limit:** 1 req/sec, 1 credit/request
**Not:** Pay-Per-Use API — ayrı API key gerekiyor

---

## Endpoint Listesi

| Method | Endpoint | Açıklama |
|--------|----------|----------|
| GET | `/query` | Info Stealer arama (domain/email/username/url) |
| GET | `/query_details/credentials/download` | Credential dosyası indir |
| GET | `/query_details/info_file/download` | Info dosyası indir |
| GET | `/breach/query` | Breach arama |
| GET | `/breaches/download` | Breach verisi indir |
| GET | `/file-tree` | Info stealer dosya ağacı |
| GET | `/stealer_logs_on_sale/query` | Satılık stealer log arama |
| GET | `/stealer_logs_on_sale/download` | Satılık stealer log indir |
| GET | `/stealer_logs_on_sale/decompose_content` | İçeriği ayrıştır (domain, IP, hash) |
| GET | `/stealer_logs_on_sale/full_content` | Tam içerik getir |

---

## GET /query — Info Stealer Arama

Birincil endpoint. Domain, email, username veya URL bazlı stealer log araması.

**Query Params:**
| Param | Type | Req | Açıklama |
|-------|------|-----|----------|
| query | string | ✅ | Arama terimi (örn: sirket.com) |
| query_type | enum | ✅ | `domain` / `email` / `username` / `url` |
| log_start_date | date | ✅ | YYYY-MM-DD |
| log_end_date | date | ✅ | YYYY-MM-DD |
| is_employee | boolean | | Sadece çalışanlar |
| has_machine_info | boolean | | Makine bilgisi olan kayıtlar |
| include_subdomains | boolean | | Subdomain'leri dahil et (default: true) |
| filter_by_keyword | string | | Keyword filtre |
| filter_countries | string | | Ülke filtresi |
| filter_stealer_families | string | | Stealer ailesi filtresi |
| offset | integer | | Sayfalama (default: 0) |
| checkpoint | date | | YYYY-MM-DD (önceki response'dan) |
| stealer_content_id | string | | Spesifik stealer ID |

**Response (200):**
```json
{
  "data": {
    "checkpoint": "2025-05-15",
    "offset": 1,
    "result": [
      {
        "country": "KE",
        "id": "9cBpHmNYL2Wk...",
        "insert_date": "2025-05-25 11:29:41",
        "log_date": "2025-05-25 11:48:03",
        "password": "1****6",
        "url": "https://demo.softpanda.io/index.php/account/login",
        "username": "cus****r@test.com"
      }
    ]
  },
  "is_success": true,
  "message": "Success",
  "response_code": 200
}
```

**Sayfalama:** `checkpoint` değeri bir sonraki request'e geçilir.

---

## GET /query_details/credentials/download

Spesifik bir credential için ham dosyayı indir.

**Query Params:**
| Param | Type | Req |
|-------|------|-----|
| credential_id | string | ✅ |
| domain_keyword | string | |

**Response:** `text/csv` — plain text credential dosyası

---

## GET /query_details/info_file/download

Info stealer'ın sistem bilgisi dosyasını indir.

**Query Params:** `credential_id` (required)
**Response:** `text/csv`

---

## GET /breach/query — Breach Arama

**Query Params:**
| Param | Type | Req |
|-------|------|-----|
| q | string | ✅ | Domain
| start_date | date | ✅ | YYYY-MM-DD |
| end_date | date | ✅ | YYYY-MM-DD |
| page_number | integer | | default: 1 |

**Response (200):**
```json
{
  "data": {
    "breach_data_set": [
      {
        "breach_domain": "Other",
        "id": "00-9v4Ab...",
        "insert_date": "2025-06-02",
        "leak_date": "2025-06-02",
        "leaks": {
          "password": "1****6",
          "username": "pdo****r@test.com"
        },
        "source": "Telegram",
        "tag": ""
      }
    ],
    "current_page": "1",
    "has_next_page": false,
    "is_free_mail_provider": false,
    "keyword_type": "domain",
    "record_per_page": "25"
  }
}
```

---

## GET /breaches/download

**Query Params:** `breach_id` (required), `keyword`
**Response:** `text/csv`

---

## GET /file-tree

Info stealer'ın dosya ağacı yapısını getir.

**Query Params:** `credential_id` (required)
**Response:** JSON string (file tree)

---

## GET /stealer_logs_on_sale/query — Satılık Log Arama

Dark market'te satışta olan stealer log'larını ara.

**Query Params:**
| Param | Type | Req |
|-------|------|-----|
| q | string | ✅ | Domain |
| company_id | integer | | |
| start_date / end_date | date | | |
| filter_countries | string | | |
| filter_stealer_families | string | | |
| limit | integer | | default: 50 |
| checkpoint | string | | Sayfalama |

**Response (200):**
```json
{
  "data": {
    "checkpoint": "",
    "data": [
      {
        "content_id": "KqK0f11zfrGb...",
        "content_link": "http://...onion",
        "country": "GH",
        "date": "2025.05.27",
        "files": "archive.zip",
        "id": "29039105",
        "insert_date": "2025-05-29",
        "price": "10.00",
        "size": "6.30Mb",
        "stealer": "lumma",
        "tags": ["russian_market", "black market", ...]
      }
    ]
  }
}
```

---

## GET /stealer_logs_on_sale/decompose_content

Log içeriğini ayrıştır: domain, IP, hash, email vb.

**Query Params:** `content_id` (required), `content_insert_date` (required, YYYY-MM-DD)

**Response:**
```json
{
  "data": {
    "domains": ["test.vip", "puma.com", ...],
    "ipv4s": ["192.168.100.1", ...],
    "emails": [],
    "hashes": [],
    "urls": [],
    "cves": [],
    "bitcoin_addresses": [],
    ...
  }
}
```

---

## GET /stealer_logs_on_sale/full_content

Log'un tam içeriğini getir.

**Query Params:** `content_id` (required), `content_insert_date` (required)

**Response:**
```json
{
  "data": {
    "content": {
      "country": null,
      "date": "2025.04.12",
      "files": "archive.zip",
      "id": "28173362",
      "links": ["test.com", "login.live.com", ...],
      "price": "10.00",
      "stealer": "lumma",
      "vendor": "Vendor [Diamond]"
    }
  }
}
```

---

## Entra ID Entegrasyonu İçin Hangi Endpoint?

Entra ID Logic App için birincil kullanım:

1. **`/query`** (query_type=email, is_employee=true) → Çalışan credential'larını çek
2. Sonuçları Entra ID'de doğrula (Graph API)
3. Validation sonucuna göre aksiyon al

Alternatif olarak SOCRadar'ın `/breach/query` endpoint'i de kullanılabilir (daha basit, sadece breach verisi).
