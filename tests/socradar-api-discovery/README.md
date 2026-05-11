# SOCRadar API Discovery Tests

**Purpose:** Hit SOCRadar's 3 dark-web monitoring endpoints (Botnet, PII, VIP) on both `preprod` and `platform` environments to capture and analyze the response shape.

## Files

| File | Purpose |
|------|---------|
| `test_endpoint.sh` | Hit one endpoint, save JSON to `responses/` |
| `run_all.sh` | Run all 6 combinations (3 sources × 2 envs) |
| `analyze_response.py` | Parse `responses/*.json`, infer field schema, save sanitized to `schemas/` |
| `responses/` | Raw JSON responses (gitignored — contains real test data with emails) |
| `schemas/` | Sanitized schemas (field name + type + null %) — safe to commit |

## Usage

```bash
# Hit all 6 endpoints (uses scripts/deploy.config for credentials)
bash run_all.sh

# Or hit one endpoint
bash test_endpoint.sh preprod botnet 2024-01-01 10

# Analyze responses
python3 analyze_response.py
python3 analyze_response.py --source pii --env preprod
```

## Endpoint Specifications (May 2026)

All endpoints share the same envelope structure:

```json
{
  "is_success": true,
  "message": "Success",
  "response_code": 200,
  "data": {
    "total_data_count": <int>,
    "data": [<records>]
  }
}
```

Headers required: `API-Key: <token>`, `Content-Type: application/json`.

Query params: `page`, `limit`, `startDate=YYYY-MM-DD`.

### Botnet (16 fields per record)
- `alarmId`, `botnetId`, `notificationId` (int)
- `user` (string, may contain email)
- `password` (string, may be plaintext or masked like `a****b`)
- `url`, `discoveryDate`, `status`, `statusReason` (string)
- `isEmployee` (bool — client-side filter)
- `country`, `deviceIP`, `deviceOS`, `logDate` (**always null** per Apr/May 2026 observation)
- `history` (list of object), `relatedAlarm` (object)

### PII (12 fields per record)
- `alarmId`, `notificationId` (int)
- `email` (string)
- `password` (string, often masked like `L****Z`)
- `breachDate`, `discoveryDate`, `status`, `statusReason` (string)
- `isEmployee` (bool)
- `source` (**list OR string** — schema mixed!)
- `history`, `relatedAlarm`

### VIP (10 fields per record — NO password field)
- `alarmId`, `notificationId` (int)
- `keyword`, `vipName` (string)
- `source` (string)
- `discoveryDate`, `status`, `statusReason` (string)
- `history`, `relatedAlarm`

## Known Counts (Company 132, lookback 2024-01-01, captured May 11 2026)

| Endpoint | Preprod | Platform |
|----------|---------|----------|
| Botnet | 126,315 records | 5 |
| PII | 17 records | 13 |
| VIP | 0 records | 2 |

In preprod the PII source returns a small number of records (~17) including disposable test-user emails that map to real Entra ID accounts in the test tenant. Helpful for end-to-end action validation.

## Gotchas

1. **`source` field mixed type in PII**: Sometimes `list[string]`, sometimes `string`. Function code handles both (`sources/pii.py:96-97`).
2. **Botnet's null columns**: country, deviceIP, deviceOS, logDate are 100% null in current data. DCR/LAW schema still includes them (forward compat).
3. **`isEmployee` client-side filter**: Server returns mixed employee + non-employee records. ~48% are employees in botnet preprod.
4. **VIP is `UNVERIFIED`**: Not in official SOCRadar API docs but works on platform (returned 2 records in test).
5. **Preprod Cloudflare blocks Python urllib default User-Agent** (EXP-0091). Use `requests` library or set User-Agent header.
