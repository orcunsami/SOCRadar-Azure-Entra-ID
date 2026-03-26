"""
Identity Intelligence fetcher.
Uses checkpoint (date string) + offset pagination.
Returns masked passwords — ROPC NOT possible with this source.
Requires separate Identity API key (pay-per-use).
"""

import time
import logging
import requests

from utils.logger import get_logger
from utils.sanitize import sanitize_password, build_law_password_fields

logger = get_logger("identity")

BASE_URL = "https://platform.socradar.com/api/identity/intelligence/query"
PAGE_SIZE = 25


def fetch(conf: dict, checkpoint: dict) -> list:
    """
    Fetch all Identity Intelligence records since last checkpoint.

    Checkpoint fields used:
        checkpoint_date : str  — date string passed to API
        offset          : int  — offset within the checkpoint window
    """
    api_key = conf["socradar_identity_api_key"]
    domain = conf.get("monitored_domain", "")
    enable_log_plaintext = conf.get("enable_log_plaintext_password", False)

    checkpoint_date = checkpoint.get("checkpoint_date", "")
    current_offset = int(checkpoint.get("offset", 0))

    all_records = []
    new_checkpoint_date = checkpoint_date
    new_offset = current_offset

    logger.info(
        f"Starting fetch. domain={domain} checkpoint_date={checkpoint_date!r} offset={current_offset}"
    )

    page = 0
    while True:
        params = {
            "domain": domain,
            "limit": PAGE_SIZE,
            "offset": new_offset,
        }
        if new_checkpoint_date:
            params["checkpoint"] = new_checkpoint_date

        headers = {
            "Api-Key": api_key,
            "Content-Type": "application/json",
        }

        try:
            resp = requests.get(BASE_URL, headers=headers, params=params, timeout=30)
        except requests.RequestException as e:
            logger.error(f"Request failed: {e}")
            break

        if resp.status_code != 200:
            logger.error(f"API error {resp.status_code}: {resp.text[:200]}")
            break

        data = resp.json()
        if not data.get("is_success"):
            logger.error(f"API returned is_success=false: {data.get('message', 'unknown')}")
            break

        payload = data.get("data", {})
        records = payload.get("data", [])
        next_checkpoint = payload.get("checkpoint", new_checkpoint_date)
        next_offset = payload.get("next_offset", None)

        if not records:
            logger.info("No more records.")
            break

        page += 1
        for rec in records:
            pw_raw = rec.get("password")
            sanitized = sanitize_password(pw_raw)
            pw_fields = build_law_password_fields(sanitized, enable_log_plaintext)
            # sanitized["_raw"] stays available only briefly; not stored in rec
            del sanitized["_raw"]

            entry = {
                "email":       rec.get("email", ""),
                "url":         rec.get("url", ""),
                "country":     rec.get("country", ""),
                "log_date":    rec.get("logDate") or rec.get("log_date", ""),
                "source_type": rec.get("sourceType", ""),
                "source":      "identity",
                "is_employee": True,   # Identity is domain-scoped, all are employees
                **pw_fields,
            }
            all_records.append(entry)

        logger.info(f"Page {page}: {len(records)} records fetched")

        # Update checkpoint for next iteration
        if next_checkpoint:
            new_checkpoint_date = next_checkpoint
        if next_offset is not None:
            new_offset = next_offset
        else:
            # No more pages in this checkpoint window
            new_offset = 0
            break

        time.sleep(1)  # rate limit

    logger.info(f"Fetch complete. total={len(all_records)}")

    # Attach checkpoint update to last record so function_app.py can save it
    if all_records:
        all_records[-1]["_checkpoint_update"] = {
            "checkpoint_date": new_checkpoint_date,
            "offset": new_offset,
        }
    elif new_checkpoint_date:
        # No records but checkpoint changed — save with sentinel record
        all_records.append({
            "_checkpoint_update": {
                "checkpoint_date": new_checkpoint_date,
                "offset": 0,
            }
        })

    return all_records
