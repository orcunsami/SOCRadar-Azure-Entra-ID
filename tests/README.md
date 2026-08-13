# SOCRadar Entra ID — Tests

Per-source organization for SOCRadar API tests + Microsoft Entra ID actions + alarm management.

## Layout

```
tests/
├── botnet/                                # SOCRadar Botnet Data v2 endpoint
│   ├── test_botnet.py                     # Basic fetch + invalid key + auth tests
│   ├── test_botnet.sh                     # bash wrapper
│   ├── test_botnet_edge_cases.py          # date filter, edge cases, header tests
│   └── results/
│       ├── botnet_response.json           # latest basic test response (sanitized sample)
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

Captured responses under `results/` are sanitized samples: identifiers,
addresses and credential values are synthetic; only the response shape is real.

## Quick usage

```bash
# Run a single source
python3 botnet/test_botnet.py
python3 pii/test_pii_edge_cases.py
python3 vip/test_vip_edge_cases.py

# Run everything
bash test_all.sh
```

## Env: which environment is queried?

`tests/.env` (default, gitignored) and `scripts/deploy.config` may carry different
`SOCRADAR_BASE_URL` values:

- `https://platform.socradar.com` → **production** (real data)
- `https://preprod.socradar.com` → **preprod** (simulated test data, 126k+ Botnet)

Tests load `tests/.env` first. To override:

```bash
SOCRADAR_BASE_URL="https://preprod.socradar.com" python3 botnet/test_botnet_edge_cases.py
```

## Edge case results (preprod test company, 2026-05-11)

| Test | Botnet | PII | VIP |
|------|--------|-----|-----|
| 01_default_no_date (total_data_count) | 126,335 | 32 | 0 |
| 02_today_only (`startDate=today`) | 0 | 0 | 0 |
| 03_epoch_all_history (`startDate=1970-01-01`) | 126,335 | 32 | 0 |
| 04_last_7_days | 0 | 0 | 0 |
| 05_last_30_days | 0 | 0 | 0 |
| 06_last_365_days | 126,312 | 2 | 0 |
| 07_invalid_date_string | total=None (silently ignored) | total=None | total=None |
| 08_wrong_company_id | HTTP 401 ✓ | HTTP 401 ✓ | HTTP 401 ✓ |
| 09_invalid_api_key | HTTP 401 ✓ | HTTP 401 ✓ | HTTP 401 ✓ |
| 10_page_too_large | total=126335, page_count=0 ✓ | total=32, page=0 ✓ | 0/0 |
| 11_no_user_agent | **HTTP 403** ❌ | **HTTP 403** ❌ | **HTTP 403** ❌ |
| 12_python_default_ua | **HTTP 403** ❌ | **HTTP 403** ❌ | **HTTP 403** ❌ |

### Key observations

1. **`startDate` parameter**: format `YYYY-MM-DD`. An invalid string is silently
   ignored by the API (`total=None`, no validation error).
2. **Preprod Cloudflare 403**: requests without a User-Agent header, or with the
   Python default UA (`Python-urllib/x.x`), get 403. Fix: explicit
   `User-Agent: SOCRadar-EntraID/1.0`.
3. **Production (platform.socradar.com)** Cloudflare is more lenient — 200 even
   without a UA. Send an explicit UA anyway.
4. **`isEmployee` filter**: nearly all of the 126k preprod Botnet records are
   `isEmployee=false` (random names). The Function App filters `isEmployee=true`
   client-side, so very few records reach Log Analytics.
5. **Lookback depth**: most preprod Botnet data is 30-365 days old.
   `INITIAL_LOOKBACK_MINUTES=86400` (= 60 days) misses most Botnet records.

### Why the function app showed 2/1/1

The demo deploy used `INITIAL_LOOKBACK_MINUTES=86400` (60 days). On the first run:

| Source | API total | Employees within 60 days | Written to LAW |
|--------|-----------|---------------------------|----------------|
| Botnet | 126,335 (all time) | 0 (no preprod data in last 30d) | 1 (empty-run marker) |
| PII | 32 | 2 (test users) | 2 (found) |
| VIP | 0 | 0 | 1 (empty-run marker) |

The Function App code is correct — that is what the preprod data contains. To see
more data, redeploy with `InitialLookbackMinutes=525600` (365 days) and reset the
checkpoint (Botnet then returns 126,312 records, mostly non-employee).

## test_alarm_resolve / test_identity_intelligence

Not source-specific — Microsoft Entra ID actions and SOCRadar Identity
Intelligence (separate API key) tests. They live at the `tests/` root.

```bash
python3 test_alarm_resolve.py        # POST /alarm/{id}/resolve
python3 test_identity_intelligence.py  # Identity Intelligence API
```

## Unit tests (no network)

```bash
python3 -m unittest discover unit/
```

Consent error mapping, force MFA fallback, Graph request retry — plus a repo
hygiene guard (`test_repo_is_anonymous_unit.py`) that fails if internal
identifiers, real-looking credentials or non-English text land in tracked files.
