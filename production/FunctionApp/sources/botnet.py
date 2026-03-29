"""
Botnet Data v2 fetcher.
Uses page + limit pagination with YYYY-MM-DD startDate (date string, not epoch).
Plaintext passwords expected — sanitized immediately.
Client-side isEmployee filter (server-side not available).
"""

import time
import logging
import requests
from datetime import datetime, timezone

from utils.logger import get_logger
from utils.sanitize import sanitize_password, build_law_password_fields
from utils.checkpoint import get_start_date

logger = get_logger("botnet")

BASE_URL = "https://platform.socradar.com/api/company/{company_id}/dark-web-monitoring/botnet-data/v2"
PAGE_SIZE = 100


def fetch(conf: dict, checkpoint: dict) -> list:
    """
    Fetch Botnet Data v2 records.
    Filters to isEmployee=true on client side.
    Returns sanitized records (plaintext password never stored).
    """
    api_key = conf["socradar_api_key"]
    company_id = conf["socradar_company_id"]
    enable_log_plaintext = conf.get("enable_log_plaintext_password", False)
    initial_lookback = conf.get("initial_lookback_minutes", 600)

    url = BASE_URL.format(company_id=company_id)
    headers = {"API-Key": api_key, "Content-Type": "application/json"}

    start_date = get_start_date(checkpoint, initial_lookback)
    logger.info("[BOTNET] Starting fetch. start_date=%s, page=1", start_date)

    all_records = []
    page = 1
    total_pages = 1
    total_data_count = None

    while page <= total_pages:
        params = {
            "page": page,
            "limit": PAGE_SIZE,
            "startDate": start_date,
        }

        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
        except requests.RequestException as e:
            logger.error(f"Request failed on page {page}: {e}")
            break

        if resp.status_code != 200:
            logger.error(f"API error {resp.status_code} on page {page}: {resp.text[:200]}")
            break

        data = resp.json()
        if not data.get("is_success"):
            logger.error(f"API returned is_success=false: {data.get('message', 'unknown')}")
            break

        payload = data.get("data", {})
        records_raw = payload.get("data", [])

        if total_data_count is None:
            total_data_count = payload.get("total_data_count", 0)
            total_pages = max(1, -(-total_data_count // PAGE_SIZE))  # ceiling division
            logger.info(f"Total records={total_data_count}, pages={total_pages}")

        employees_this_page = 0
        skipped_this_page = 0

        for rec in records_raw:
            # Client-side employee filter
            if not rec.get("isEmployee", False):
                skipped_this_page += 1
                continue

            pw_raw = rec.get("password")
            sanitized = sanitize_password(pw_raw)
            pw_fields = build_law_password_fields(sanitized, enable_log_plaintext)
            _raw = sanitized.pop("_raw", None)  # keep for ROPC only

            related = rec.get("relatedAlarm", {}) or {}
            entry = {
                "email":       rec.get("user", rec.get("email", "")),
                "url":         rec.get("url", ""),
                "device_ip":   rec.get("deviceIP", ""),
                "device_os":   rec.get("deviceOS", ""),
                "country":     rec.get("country", ""),
                "log_date":    rec.get("logDate", ""),
                "is_employee": True,
                "source":      "botnet",
                "alarm_id":    rec.get("alarmId") or related.get("alarmId"),
                **pw_fields,
            }

            # Preserve _raw for ROPC — caller must del after use
            if _raw:
                entry["sanitized"] = {"is_plaintext": sanitized["is_plaintext"], "_raw": _raw}

            all_records.append(entry)
            employees_this_page += 1

        logger.fetch_page(
            page=page,
            total_pages=total_pages,
            records=len(records_raw),
            employees=employees_this_page,
            skipped=skipped_this_page
        )

        if not records_raw:
            break

        page += 1
        time.sleep(1)  # rate limit: 1 req/sec

    logger.fetch_done(total=total_data_count or 0, employees=len(all_records))

    # Attach checkpoint update — next run starts from today
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if all_records:
        all_records[-1]["_checkpoint_update"] = {
            "last_start_date": today_str,
            "last_page": 0,
        }

    return all_records
