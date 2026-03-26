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
    Fetch Identity Intelligence records for all monitored domains since last checkpoint.

    Checkpoint fields used:
        checkpoint_date : str  — date string passed to API (shared across domains)
        offset          : int  — offset within the checkpoint window (last domain's position)
    """
    api_key = conf["socradar_identity_api_key"]
    domains = conf.get("monitored_domains", [])
    enable_log_plaintext = conf.get("enable_log_plaintext_password", False)

    if not domains:
        logger.warning("[IDENTITY] No domains configured in MONITORED_DOMAINS — skipping")
        return []

    logger.info(f"[IDENTITY] Starting fetch. domains={domains}")

    all_records = []
    # Checkpoint is shared: last processed date carried forward across all domains
    shared_checkpoint_date = checkpoint.get("checkpoint_date", "")
    final_checkpoint_date = shared_checkpoint_date
    final_offset = 0

    for domain in domains:
        domain_records, last_checkpoint_date, last_offset = _fetch_domain(
            api_key=api_key,
            domain=domain,
            checkpoint_date=shared_checkpoint_date,
            offset=int(checkpoint.get("offset", 0)) if domain == domains[0] else 0,
            enable_log_plaintext=enable_log_plaintext,
        )
        all_records.extend(domain_records)
        if last_checkpoint_date:
            final_checkpoint_date = last_checkpoint_date
        final_offset = last_offset

    logger.info(f"[IDENTITY] Fetch complete. domains={len(domains)}, total={len(all_records)}")

    if all_records:
        all_records[-1]["_checkpoint_update"] = {
            "checkpoint_date": final_checkpoint_date,
            "offset": final_offset,
        }
    elif final_checkpoint_date:
        all_records.append({
            "_checkpoint_update": {
                "checkpoint_date": final_checkpoint_date,
                "offset": 0,
            }
        })

    return all_records


def _fetch_domain(api_key: str, domain: str, checkpoint_date: str, offset: int, enable_log_plaintext: bool) -> tuple:
    """Fetch all pages for a single domain. Returns (records, last_checkpoint_date, last_offset)."""
    headers = {"Api-Key": api_key, "Content-Type": "application/json"}
    new_checkpoint_date = checkpoint_date
    new_offset = offset
    domain_records = []
    page = 0

    logger.info(f"[IDENTITY] domain={domain} checkpoint_date={checkpoint_date!r} offset={offset}")

    while True:
        params = {"domain": domain, "limit": PAGE_SIZE, "offset": new_offset}
        if new_checkpoint_date:
            params["checkpoint"] = new_checkpoint_date

        try:
            resp = requests.get(BASE_URL, headers=headers, params=params, timeout=30)
        except requests.RequestException as e:
            logger.error(f"[IDENTITY] domain={domain} request failed: {e}")
            break

        if resp.status_code != 200:
            logger.error(f"[IDENTITY] domain={domain} API error {resp.status_code}: {resp.text[:200]}")
            break

        data = resp.json()
        if not data.get("is_success"):
            logger.error(f"[IDENTITY] domain={domain} is_success=false: {data.get('message', 'unknown')}")
            break

        payload = data.get("data", {})
        records = payload.get("data", [])
        next_checkpoint = payload.get("checkpoint", new_checkpoint_date)
        next_offset = payload.get("next_offset", None)

        if not records:
            logger.info(f"[IDENTITY] domain={domain} no more records")
            break

        page += 1
        for rec in records:
            pw_raw = rec.get("password")
            sanitized = sanitize_password(pw_raw)
            pw_fields = build_law_password_fields(sanitized, enable_log_plaintext)
            del sanitized["_raw"]

            entry = {
                "email":       rec.get("email", ""),
                "url":         rec.get("url", ""),
                "country":     rec.get("country", ""),
                "log_date":    rec.get("logDate") or rec.get("log_date", ""),
                "source_type": rec.get("sourceType", ""),
                "monitored_domain": domain,
                "source":      "identity",
                "is_employee": True,
                **pw_fields,
            }
            domain_records.append(entry)

        logger.info(f"[IDENTITY] domain={domain} page={page}: {len(records)} records")

        if next_checkpoint:
            new_checkpoint_date = next_checkpoint
        if next_offset is not None:
            new_offset = next_offset
        else:
            new_offset = 0
            break

        time.sleep(1)

    return domain_records, new_checkpoint_date, new_offset
