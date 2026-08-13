#!/usr/bin/env python3
"""SOCRadar Identity Intelligence API Test

Tests the info stealer search query endpoint.
Separate pay-per-use API — requires SOCRADAR_IDENTITY_API_KEY.
"""

import json
import time
import os
import urllib.request
import urllib.error
from pathlib import Path

# Load .env
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip().strip("'\"")

API_KEY = os.environ.get("SOCRADAR_IDENTITY_API_KEY", "")
DOMAIN = os.environ.get("MONITORED_DOMAIN", "test.com")
BASE_URL = "https://platform.socradar.com/api/identity/intelligence"

if not API_KEY:
    print("ERROR: SOCRADAR_IDENTITY_API_KEY not set")
    exit(1)


def test_query(domain, query_type="domain", is_employee=None, limit=25):
    params = (
        f"query={domain}&query_type={query_type}"
        f"&log_start_date=2025-01-01&log_end_date=2026-12-31"
    )
    if is_employee is not None:
        params += f"&is_employee={'true' if is_employee else 'false'}"

    url = f"{BASE_URL}/query?{params}"

    start = time.time()
    try:
        req = urllib.request.Request(url, headers={"Api-Key": API_KEY})
        with urllib.request.urlopen(req, timeout=30) as resp:
            status = resp.status
            raw = resp.read()
            elapsed = time.time() - start
            body = json.loads(raw)

            data = body.get("data", {})
            results = data.get("result", [])

            return {
                "endpoint": "/identity/intelligence/query",
                "domain": domain,
                "query_type": query_type,
                "is_employee": is_employee,
                "status": status,
                "is_success": body.get("is_success"),
                "elapsed_seconds": round(elapsed, 2),
                "checkpoint": data.get("checkpoint"),
                "offset": data.get("offset"),
                "result_count": len(results),
                "sample": results[:3],
                "error": None,
            }
    except urllib.error.HTTPError as e:
        elapsed = time.time() - start
        error_body = e.read().decode("utf-8", errors="replace")[:500]
        try:
            error_json = json.loads(error_body)
        except json.JSONDecodeError:
            error_json = error_body
        return {
            "endpoint": "/identity/intelligence/query",
            "domain": domain,
            "status": e.code,
            "elapsed_seconds": round(elapsed, 2),
            "error": str(e),
            "error_body": error_json,
        }
    except Exception as e:
        return {"endpoint": "/identity/intelligence/query", "status": 0, "error": str(e)}


def test_breach_query(domain):
    url = (
        f"{BASE_URL}/breach/query"
        f"?q={domain}&start_date=2025-01-01&end_date=2026-12-31"
    )

    start = time.time()
    try:
        req = urllib.request.Request(url, headers={"Api-Key": API_KEY})
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            elapsed = time.time() - start
            body = json.loads(raw)
            data = body.get("data", {})
            breach_set = data.get("breach_data_set", [])

            return {
                "endpoint": "/identity/intelligence/breach/query",
                "domain": domain,
                "status": resp.status,
                "is_success": body.get("is_success"),
                "elapsed_seconds": round(elapsed, 2),
                "has_next_page": data.get("has_next_page"),
                "current_page": data.get("current_page"),
                "record_per_page": data.get("record_per_page"),
                "result_count": len(breach_set),
                "sample": breach_set[:3],
                "error": None,
            }
    except urllib.error.HTTPError as e:
        elapsed = time.time() - start
        return {
            "endpoint": "/identity/intelligence/breach/query",
            "status": e.code,
            "elapsed_seconds": round(elapsed, 2),
            "error": str(e),
            "error_body": e.read().decode("utf-8", errors="replace")[:500],
        }
    except Exception as e:
        return {"endpoint": "/identity/intelligence/breach/query", "status": 0, "error": str(e)}


def main():
    print(f"Identity Intelligence API Test — domain: {DOMAIN}")
    print("=" * 60)

    results = []

    # Test 1: Stealer query (all)
    print("\n[1/4] Stealer query (all)...")
    r = test_query(DOMAIN)
    results.append(r)
    if r.get("error"):
        print(f"  ERROR {r['status']}: {r['error']}")
    else:
        print(f"  Status: {r['status']}, Results: {r['result_count']}, Time: {r['elapsed_seconds']}s")
        print(f"  Checkpoint: {r['checkpoint']}, Offset: {r['offset']}")

    # Test 2: Stealer query (employees only)
    print("\n[2/4] Stealer query (is_employee=true)...")
    r = test_query(DOMAIN, is_employee=True)
    results.append(r)
    if r.get("error"):
        print(f"  ERROR {r['status']}: {r['error']}")
    else:
        print(f"  Status: {r['status']}, Results: {r['result_count']}, Time: {r['elapsed_seconds']}s")

    # Test 3: Breach query
    print("\n[3/4] Breach query...")
    r = test_breach_query(DOMAIN)
    results.append(r)
    if r.get("error"):
        print(f"  ERROR {r['status']}: {r['error']}")
    else:
        print(f"  Status: {r['status']}, Results: {r['result_count']}, Time: {r['elapsed_seconds']}s")
        print(f"  has_next_page: {r.get('has_next_page')}")

    # Test 4: Wrong key
    print("\n[4/4] Wrong API key...")
    old_key = API_KEY
    os.environ["SOCRADAR_IDENTITY_API_KEY"] = "invalid_key_test"
    r_bad = test_query("test.com")
    results.append(r_bad)
    os.environ["SOCRADAR_IDENTITY_API_KEY"] = old_key
    print(f"  Status: {r_bad['status']} (expected 401/402)")

    # Save
    output = {"api": "Identity Intelligence", "domain": DOMAIN, "results": results}
    out_path = Path(__file__).parent / "results" / "identity_response.json"
    out_path.parent.mkdir(exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nSaved: {out_path}")

    # Summary
    ok = sum(1 for r in results if r.get("is_success"))
    print(f"\n{'=' * 60}")
    print(f"SUMMARY: {ok}/{len(results)} successful")


if __name__ == "__main__":
    main()
