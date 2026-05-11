# SOCRadar Entra ID — Tests

Per-source organization for SOCRadar API tests + Microsoft Entra ID actions + alarm management.

## Yapı

```
tests/
├── botnet/                                # SOCRadar Botnet Data v2 endpoint
│   ├── test_botnet.py                     # Basic fetch + invalid key + auth tests
│   ├── test_botnet.sh                     # bash wrapper
│   ├── test_botnet_edge_cases.py          # date filter, edge cases, header tests
│   └── results/
│       ├── botnet_response.json           # latest basic test response
│       └── edge_cases.json                # latest edge-case matrix
├── pii/                                   # SOCRadar PII Exposure v2 endpoint
│   ├── test_pii.py
│   ├── test_pii.sh
│   ├── test_pii_edge_cases.py
│   └── results/
├── vip/                                   # SOCRadar VIP Protection v2 endpoint
│   ├── test_vip.py
│   ├── test_vip.sh
│   ├── test_vip_edge_cases.py
│   └── results/
├── unit/                                  # Pure-Python unit tests (no API calls)
│   ├── test_consent_error_unit.py
│   ├── test_force_mfa_unit.py
│   └── test_graph_request_unit.py
├── historical-data/                       # Lookback-depth exploration
├── socradar-api-discovery/                # API schema reverse-engineering
├── results/                               # Non-source-specific responses
│   ├── alarm_resolve_response.json
│   └── identity_response.json
├── test_alarm_resolve.py                  # POST /alarm/{id}/resolve test
├── test_identity_intelligence.py          # SOCRadar Identity Intelligence (separate API key)
├── test_all.sh                            # Run-all wrapper
└── README.md                              # this file
```

## Hızlı kullanım

```bash
# Run a single source
python3 botnet/test_botnet.py
python3 pii/test_pii_edge_cases.py
python3 vip/test_vip_edge_cases.py

# Run everything
bash test_all.sh
```

## Env: hangi environment'a sorgulanıyor?

`tests/.env` (default) ve `scripts/deploy.config` farklı `SOCRADAR_BASE_URL` değerleri içerebilir:

- `https://platform.socradar.com` → **production** (gerçek müşteri data'sı)
- `https://preprod.socradar.com` → **preprod** (testradar* simüle data, 126k+ Botnet)

Tests `tests/.env`'i öncelikle yükler. **Override** etmek için:

```bash
SOCRADAR_BASE_URL="https://preprod.socradar.com" python3 botnet/test_botnet_edge_cases.py
```

## Edge case test sonuçları (preprod, company 132, 2026-05-11)

| Test | Botnet | PII | VIP |
|------|--------|-----|-----|
| 01_default_no_date (total_data_count) | 126,335 | 32 | 0 |
| 02_today_only (`startDate=today`) | 0 | 0 | 0 |
| 03_epoch_all_history (`startDate=1970-01-01`) | 126,335 | 32 | 0 |
| 04_last_7_days | 0 | 0 | 0 |
| 05_last_30_days | 0 | 0 | 0 |
| 06_last_365_days | 126,312 | 2 | 0 |
| 07_invalid_date_string | total=None (siliently ignored) | total=None | total=None |
| 08_wrong_company_id | HTTP 401 ✓ | HTTP 401 ✓ | HTTP 401 ✓ |
| 09_invalid_api_key | HTTP 401 ✓ | HTTP 401 ✓ | HTTP 401 ✓ |
| 10_page_too_large | total=126335, page_count=0 ✓ | total=32, page=0 ✓ | 0/0 |
| 11_no_user_agent | **HTTP 403** ❌ | **HTTP 403** ❌ | **HTTP 403** ❌ |
| 12_python_default_ua | **HTTP 403** ❌ | **HTTP 403** ❌ | **HTTP 403** ❌ |

### Önemli gözlemler

1. **`startDate` parameter**: format `YYYY-MM-DD`. Geçersiz string verince API silently `total=None` döndürür (validation atlanır).
2. **Preprod Cloudflare 403**: Header'da User-Agent yok ise veya Python default UA (`Python-urllib/x.x`) ise 403. Çözüm: explicit `User-Agent: SOCRadar-EntraID/1.0` (EXP-0091).
3. **Production (platform.socradar.com)** Cloudflare daha gevşek — UA olmadan da 200 dönüyor. Ama daha güvenli olmak için yine de explicit UA gönder.
4. **`isEmployee` filter**: Botnet'te 126k'nın **neredeyse tamamı `isEmployee=false`** (random isimler). Function App client-side `isEmployee=true` filtreliyor → çok az record LAW'a yazılır.
5. **Lookback derinliği**: Preprod Botnet datasının çoğu 30-365 gün arası. `INITIAL_LOOKBACK_MINUTES=86400` (= 60 gün) çoğu Botnet record'unu kapsamaz.

### Niye function app'te 2/1/1 gördük?

Demo deploy'da `INITIAL_LOOKBACK_MINUTES=86400` (60 gün). Function App'in 1. run'ında:

| Source | API total | İçinde employee (60 gün) | LAW'a yazılan |
|--------|-----------|---------------------------|---------------|
| Botnet | 126,335 (all time) | 0 (preprod last 30d data yok) | 1 (boş çalıştı marker) |
| PII | 32 | 2 (testradar2, testradar3) | 2 (found) |
| VIP | 0 | 0 | 1 (boş çalıştı marker) |

Function App **kodu doğru** — preprod data'sı bu. Production'da müşteri muhtemelen daha güncel data + daha fazla employee match alacak. Daha fazla data görmek için `InitialLookbackMinutes=525600` (365 gün) parametresiyle redeploy + checkpoint reset gerek (Botnet için 126,312 record gelir, çoğu non-employee).

## test_alarm_resolve / test_identity_intelligence

Source-spesifik değil — Microsoft Entra ID actions ve SOCRadar Identity Intelligence (ayrı API key) testleri. `tests/` root'unda kaldı.

```bash
python3 test_alarm_resolve.py        # POST /alarm/{id}/resolve
python3 test_identity_intelligence.py  # Identity Intelligence API
```

## Unit tests (no network)

```bash
python3 -m unittest discover unit/
```

23 unit test (consent error mapping, force MFA fallback, Graph request retry).
