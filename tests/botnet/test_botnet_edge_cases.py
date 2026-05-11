#!/usr/bin/env python3
"""SOCRadar Botnet Data v2 — Edge Case + Date Filter Tests

Tests:
  1. Default fetch (no date) — total_data_count
  2. startDate = today (no past data)
  3. startDate = 1970-01-01 (all data)
  4. startDate = 7 days ago
  5. startDate = 30 days ago
  6. startDate = invalid string
  7. Empty company / wrong company ID
  8. Invalid API key → expect 401/403
  9. Very large page number (beyond total) → expect empty
  10. limit=0 / negative limit → edge
  11. Header User-Agent missing → does preprod 403?
  12. isEmployee true vs false counts

Output: tests/botnet/results/edge_cases.json with per-test response summary.
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

TESTS_DIR = Path(__file__).parent
RESULTS_DIR = TESTS_DIR / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# Load .env from deploy.config or tests/.env
for cfg in [TESTS_DIR.parent / ".env", TESTS_DIR.parent.parent / "scripts" / "deploy.config"]:
    if cfg.exists():
        with open(cfg) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    if k not in os.environ:
                        os.environ[k] = v.strip().strip('"').strip("'")

API_KEY = os.environ.get("SOCRADAR_API_KEY", "")
COMPANY_ID = os.environ.get("SOCRADAR_COMPANY_ID", "132")
BASE = os.environ.get("SOCRADAR_BASE_URL", "https://preprod.socradar.com") + "/api"

if not API_KEY:
    print("ERROR: SOCRADAR_API_KEY not set"); sys.exit(1)


def fetch(api_key, company_id, page=1, limit=10, start_date=None, user_agent="SOCRadar-Test/1.0"):
    """Returns dict: status, is_success, total_data_count, page_count, employees, error."""
    url = f"{BASE}/company/{company_id}/dark-web-monitoring/botnet-data/v2?page={page}&limit={limit}"
    if start_date is not None:
        url += f"&startDate={start_date}"
    headers = {"API-Key": api_key, "Content-Type": "application/json"}
    if user_agent:
        headers["User-Agent"] = user_agent
    t0 = time.time()
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            d = json.loads(raw)
            data = d.get("data", {}) or {}
            recs = data.get("data", []) or []
            return {
                "status": resp.status,
                "elapsed_sec": round(time.time() - t0, 2),
                "is_success": d.get("is_success"),
                "total_data_count": data.get("total_data_count"),
                "page_count": len(recs),
                "employees_in_page": sum(1 for r in recs if r.get("isEmployee") is True),
                "non_employees_in_page": sum(1 for r in recs if r.get("isEmployee") is False),
                "error": None,
            }
    except urllib.error.HTTPError as e:
        return {"status": e.code, "elapsed_sec": round(time.time() - t0, 2),
                "is_success": False, "error": str(e), "body": e.read().decode("utf-8", errors="replace")[:200]}
    except Exception as e:
        return {"status": 0, "elapsed_sec": round(time.time() - t0, 2), "is_success": False, "error": str(e)}


def main():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    month_ago = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    year_ago = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%d")

    cases = [
        ("01_default_no_date", lambda: fetch(API_KEY, COMPANY_ID, limit=1)),
        ("02_today_only", lambda: fetch(API_KEY, COMPANY_ID, limit=1, start_date=today)),
        ("03_epoch_all_history", lambda: fetch(API_KEY, COMPANY_ID, limit=1, start_date="1970-01-01")),
        ("04_last_7_days", lambda: fetch(API_KEY, COMPANY_ID, limit=10, start_date=week_ago)),
        ("05_last_30_days", lambda: fetch(API_KEY, COMPANY_ID, limit=10, start_date=month_ago)),
        ("06_last_365_days", lambda: fetch(API_KEY, COMPANY_ID, limit=10, start_date=year_ago)),
        ("07_invalid_date_string", lambda: fetch(API_KEY, COMPANY_ID, limit=1, start_date="not-a-date")),
        ("08_wrong_company_id", lambda: fetch(API_KEY, "99999999", limit=1)),
        ("09_invalid_api_key", lambda: fetch("xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", COMPANY_ID, limit=1)),
        ("10_page_too_large", lambda: fetch(API_KEY, COMPANY_ID, page=99999, limit=1)),
        ("11_no_user_agent", lambda: fetch(API_KEY, COMPANY_ID, limit=1, user_agent=None)),
        ("12_python_default_ua", lambda: fetch(API_KEY, COMPANY_ID, limit=1, user_agent="Python-urllib/3.11")),
    ]

    results = {"endpoint": "botnet-data/v2", "company_id": COMPANY_ID, "tested_at": datetime.now(timezone.utc).isoformat(), "cases": {}}
    for name, fn in cases:
        print(f"  → {name}")
        r = fn()
        results["cases"][name] = r
        time.sleep(0.5)

    out = RESULTS_DIR / "edge_cases.json"
    with open(out, "w") as f:
        json.dump(results, f, indent=2, default=str)

    # Print summary
    print()
    print(f"{'Case':<26} {'Status':<8} {'Total':<10} {'Page':<6} {'Emp':<5} {'NonEmp':<8} {'Elapsed':<8}")
    print("-" * 80)
    for name, r in results["cases"].items():
        print(f"{name:<26} {str(r.get('status')):<8} {str(r.get('total_data_count','-')):<10} {str(r.get('page_count','-')):<6} {str(r.get('employees_in_page','-')):<5} {str(r.get('non_employees_in_page','-')):<8} {r.get('elapsed_sec','-')}s")
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
