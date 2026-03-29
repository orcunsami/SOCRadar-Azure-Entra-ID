"""
VIP Protection v2 fetcher.
UNVERIFIED: endpoint not in official API documentation.
No password field in responses. Entra ID actions limited to lookup + incident.
"""

import time
import logging
import requests
from datetime import datetime, timezone

from utils.logger import get_logger
from utils.checkpoint import get_start_date

logger = get_logger("vip")

BASE_URL = "https://platform.socradar.com/api/company/{company_id}/vip-protection/v2"
PAGE_SIZE = 100


def fetch(conf: dict, checkpoint: dict) -> list:
    """
    Fetch VIP Protection v2 records.
    WARNING: This endpoint is UNVERIFIED — not in official API docs.
    Verified working in live tests (2026-03-26) but may change without notice.
    """
    api_key = conf["socradar_api_key"]
    company_id = conf["socradar_company_id"]
    initial_lookback = conf.get("initial_lookback_minutes", 600)

    url = BASE_URL.format(company_id=company_id)
    headers = {"API-Key": api_key, "Content-Type": "application/json"}

    start_date = get_start_date(checkpoint, initial_lookback)
    logger.info("[VIP] Starting fetch. start_date=%s, page=1", start_date)
    logger.warning("VIP endpoint is UNVERIFIED — not in official API documentation")

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

        if resp.status_code == 404:
            logger.error("VIP endpoint returned 404 — endpoint may not exist for this company")
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
            total_pages = max(1, -(-total_data_count // PAGE_SIZE))
            logger.info(f"Total records={total_data_count}, pages={total_pages}")

        for rec in records_raw:
            related = rec.get("relatedAlarm", {}) or {}
            entry = {
                "email":          rec.get("vipName", rec.get("email", "")),
                "keyword":        rec.get("keyword", ""),
                "vip_name":       rec.get("vipName", ""),
                "status":         rec.get("status", ""),
                "discovery_date": rec.get("discoveryDate", ""),
                "source_name":    rec.get("source", ""),
                "is_employee":    True,
                "source":         "vip",
                "alarm_id":       rec.get("alarmId") or related.get("alarmId"),
                # No password field in VIP responses
                "password_present": False,
                "password_masked":  None,
                "is_plaintext":     False,
            }
            all_records.append(entry)

        logger.fetch_page(
            page=page,
            total_pages=total_pages,
            records=len(records_raw),
            employees=len(records_raw)
        )

        if not records_raw:
            break

        page += 1
        time.sleep(1)

    logger.fetch_done(total=total_data_count or 0, employees=len(all_records))

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if all_records:
        all_records[-1]["_checkpoint_update"] = {
            "last_start_date": today_str,
            "last_page": 0,
        }

    return all_records
