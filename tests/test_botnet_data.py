#!/usr/bin/env python3
"""SOCRadar Botnet Data v2 API Test

Tests the dark web monitoring botnet data endpoint.
Uses platform API key (SOCRADAR_API_KEY).
"""

import json
import time
import os
import urllib.request
import urllib.error
from pathlib import Path

env_path = Path(__file__).parent / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                key = key.strip()
                if key not in os.environ:
                    os.environ[key] = value.strip().strip("'\"")

API_KEY = os.environ.get("SOCRADAR_API_KEY", "")
COMPANY_ID = os.environ.get("SOCRADAR_COMPANY_ID", "330")
BASE_URL = os.environ.get("SOCRADAR_BASE_URL", "https://platform.socradar.com") + "/api"

if not API_KEY:
    print("ERROR: SOCRADAR_API_KEY not set")
    exit(1)


def fetch_botnet(page=1, limit=10, start_date=None):
    url = f"{BASE_URL}/company/{COMPANY_ID}/dark-web-monitoring/botnet-data/v2?page={page}&limit={limit}"
    if start_date:
        url += f"&startDate={start_date}"

    start = time.time()
    try:
        req = urllib.request.Request(url, headers={"API-Key": API_KEY, "User-Agent": "SOCRadar-Test/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            elapsed = time.time() - start
            body = json.loads(raw)
            data = body.get("data", {})
            items = data.get("data", [])
            total = data.get("total_data_count", 0)

            return {
                "endpoint": f"/company/{COMPANY_ID}/dark-web-monitoring/botnet-data/v2",
                "page": page,
                "limit": limit,
                "start_date": start_date,
                "status": resp.status,
                "is_success": body.get("is_success"),
                "elapsed_seconds": round(elapsed, 2),
                "response_size_bytes": len(raw),
                "total_data_count": total,
                "page_count": len(items),
                "sample": items[:3],
                "fields": list(items[0].keys()) if items else [],
                "password_masked": all("*" in str(i.get("password", "")) for i in items) if items else None,
                "employee_count": sum(1 for i in items if i.get("isEmployee")),
                "error": None,
            }
    except urllib.error.HTTPError as e:
        elapsed = time.time() - start
        return {
            "endpoint": "botnet-data/v2",
            "page": page,
            "status": e.code,
            "elapsed_seconds": round(elapsed, 2),
            "error": str(e),
            "error_body": e.read().decode("utf-8", errors="replace")[:500],
        }
    except Exception as e:
        return {"endpoint": "botnet-data/v2", "status": 0, "error": str(e)}


def main():
    print(f"Botnet Data v2 API Test — company: {COMPANY_ID}")
    print("=" * 60)

    results = []

    # Test 1: Page 1
    print("\n[1/4] Page 1, limit=10...")
    r = fetch_botnet(page=1, limit=10)
    results.append(r)
    if r.get("error"):
        print(f"  ERROR {r['status']}: {r['error']}")
    else:
        print(f"  Status: {r['status']}, Total: {r['total_data_count']:,}, Page items: {r['page_count']}")
        print(f"  Fields: {r['fields']}")
        print(f"  Password masked: {r['password_masked']}")
        print(f"  Employees in page: {r['employee_count']}/{r['page_count']}")

    # Test 2: Page 2 (pagination check)
    print("\n[2/4] Page 2, limit=5...")
    r = fetch_botnet(page=2, limit=5)
    results.append(r)
    if r.get("error"):
        print(f"  ERROR: {r['error']}")
    else:
        print(f"  Status: {r['status']}, Page items: {r['page_count']}")

    # Test 3: With startDate filter
    print("\n[3/4] With startDate=2026-03-01...")
    r = fetch_botnet(page=1, limit=10, start_date="2026-03-01")
    results.append(r)
    if r.get("error"):
        print(f"  ERROR: {r['error']}")
    else:
        print(f"  Status: {r['status']}, Total (filtered): {r['total_data_count']:,}, Page items: {r['page_count']}")

    # Test 4: Wrong key
    print("\n[4/4] Wrong API key...")
    old_key = os.environ["SOCRADAR_API_KEY"]
    os.environ["SOCRADAR_API_KEY"] = "invalid"
    # Need to use the variable directly since we read at top
    url = f"{BASE_URL}/company/{COMPANY_ID}/dark-web-monitoring/botnet-data/v2?page=1&limit=1"
    start = time.time()
    try:
        req = urllib.request.Request(url, headers={"API-Key": "invalid_key_test"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            results.append({"status": resp.status, "error": "Expected error but got 200"})
    except urllib.error.HTTPError as e:
        results.append({"status": e.code, "error": None, "expected": "401/403"})
        print(f"  Status: {e.code} (expected 401/403)")
    except Exception as e:
        results.append({"status": 0, "error": str(e)})
        print(f"  Error: {e}")
    os.environ["SOCRADAR_API_KEY"] = old_key

    # Save
    output = {"api": "Botnet Data v2", "company_id": COMPANY_ID, "results": results}
    out_path = Path(__file__).parent / "results" / "botnet_response.json"
    out_path.parent.mkdir(exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nSaved: {out_path}")

    ok = sum(1 for r in results if r.get("is_success"))
    print(f"\n{'=' * 60}")
    print(f"SUMMARY: {ok}/{len(results)} successful")


if __name__ == "__main__":
    main()
