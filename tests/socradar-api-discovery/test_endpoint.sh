#!/usr/bin/env bash
# Hit a single SOCRadar endpoint and save the raw response.
# Usage: test_endpoint.sh <env> <source> <startDate> [pageSize]
#   env: preprod | platform
#   source: botnet | pii | vip
set -euo pipefail

ENV="${1:-preprod}"
SOURCE="${2:-botnet}"
START_DATE="${3:-2024-01-01}"
PAGE_SIZE="${4:-10}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RESPONSES_DIR="$SCRIPT_DIR/responses"

# Load API key from deploy.config
DEPLOY_CONFIG="$SCRIPT_DIR/../../scripts/deploy.config"
if [[ -f "$DEPLOY_CONFIG" ]]; then
    API_KEY=$(grep '^SOCRADAR_API_KEY=' "$DEPLOY_CONFIG" | cut -d= -f2-)
    COMPANY_ID=$(grep '^SOCRADAR_COMPANY_ID=' "$DEPLOY_CONFIG" | cut -d= -f2-)
else
    API_KEY="${SOCRADAR_API_KEY:?Set SOCRADAR_API_KEY}"
    COMPANY_ID="${SOCRADAR_COMPANY_ID:-132}"
fi

case "$ENV" in
    preprod)  BASE="https://preprod.socradar.com" ;;
    platform) BASE="https://platform.socradar.com" ;;
    *) echo "ERROR: env must be preprod|platform"; exit 1 ;;
esac

case "$SOURCE" in
    botnet) PATH_TMPL="/api/company/$COMPANY_ID/dark-web-monitoring/botnet-data/v2" ;;
    pii)    PATH_TMPL="/api/company/$COMPANY_ID/dark-web-monitoring/pii-exposure/v2" ;;
    vip)    PATH_TMPL="/api/company/$COMPANY_ID/vip-protection/v2" ;;
    *) echo "ERROR: source must be botnet|pii|vip"; exit 1 ;;
esac

URL="${BASE}${PATH_TMPL}?page=1&limit=${PAGE_SIZE}&startDate=${START_DATE}"
OUT="${RESPONSES_DIR}/${SOURCE}_${ENV}.json"

echo "[$ENV/$SOURCE] GET $URL"
HTTP_CODE=$(curl -s -o "$OUT" -w "%{http_code}" \
    -H "API-Key: $API_KEY" \
    -H "Content-Type: application/json" \
    "$URL")
echo "  HTTP $HTTP_CODE  →  $OUT"

# Summary
if [[ "$HTTP_CODE" == "200" ]]; then
    python3 -c "
import json
d = json.load(open('$OUT'))
data_obj = d.get('data', {}) or {}
records = data_obj.get('data', [])
print(f'  is_success: {d.get(\"is_success\")}  total_data_count: {data_obj.get(\"total_data_count\", \"N/A\")}  records_returned: {len(records)}')
if records:
    print(f'  first_record_keys: {sorted(records[0].keys())[:15]}')
"
fi
echo ""
