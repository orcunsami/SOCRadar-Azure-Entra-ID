#!/usr/bin/env python3
"""SOCRadar Alarm Status Change API Test

Tests the alarm resolve endpoint (POST /alarms/status/change).
Does NOT actually resolve alarms — only tests with DRY_RUN=true by default.
Set DRY_RUN=false in .env to actually resolve.
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
                os.environ[key.strip()] = value.strip().strip("'\"")

API_KEY = os.environ.get("SOCRADAR_API_KEY", "")
COMPANY_ID = os.environ.get("SOCRADAR_COMPANY_ID", "132")
BASE_URL = os.environ.get("SOCRADAR_BASE_URL", "https://platform.socradar.com") + "/api"
DRY_RUN = os.environ.get("DRY_RUN", "true").lower() == "true"

TEST_BOTNET_ALARM = os.environ.get("TEST_BOTNET_ALARM", "89151922")
TEST_PII_ALARM = os.environ.get("TEST_PII_ALARM", "89151979")
TEST_VIP_ALARM = os.environ.get("TEST_VIP_ALARM", "89151982")

if not API_KEY:
    print("ERROR: SOCRADAR_API_KEY not set")
    exit(1)

# SOCRadar alarm statuses
STATUS_RESOLVED = 2
STATUS_FALSE_POSITIVE = 9
STATUS_MITIGATED = 12


def resolve_alarm(alarm_id, status=STATUS_RESOLVED, comment=""):
    url = f"{BASE_URL}/company/{COMPANY_ID}/alarms/status/change"
    body = {
        "alarm_ids": [int(alarm_id)],
        "status": status,
    }
    if comment:
        body["comments"] = comment

    data = json.dumps(body).encode("utf-8")
    start = time.time()
    try:
        req = urllib.request.Request(
            url,
            data=data,
            headers={"API-Key": API_KEY, "Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            elapsed = time.time() - start
            raw = resp.read()
            response = json.loads(raw)
            return {
                "alarm_id": alarm_id,
                "status_sent": status,
                "http_status": resp.status,
                "is_success": response.get("is_success"),
                "message": response.get("message", ""),
                "elapsed_seconds": round(elapsed, 2),
                "response": response,
                "error": None,
            }
    except urllib.error.HTTPError as e:
        elapsed = time.time() - start
        error_body = e.read().decode("utf-8", errors="replace")[:500]
        return {
            "alarm_id": alarm_id,
            "status_sent": status,
            "http_status": e.code,
            "is_success": False,
            "elapsed_seconds": round(elapsed, 2),
            "error": str(e),
            "error_body": error_body,
        }
    except Exception as e:
        return {"alarm_id": alarm_id, "http_status": 0, "error": str(e)}


def main():
    print(f"Alarm Status Change API Test — company: {COMPANY_ID}")
    print(f"DRY_RUN: {DRY_RUN}")
    print("=" * 60)

    results = []

    # Test 1: Auth check — wrong key
    print("\n[1/4] Auth check (wrong key)...")
    old_key = os.environ.get("SOCRADAR_API_KEY")
    url = f"{BASE_URL}/company/{COMPANY_ID}/alarms/status/change"
    data = json.dumps({"alarm_ids": [1], "status": 2}).encode("utf-8")
    try:
        req = urllib.request.Request(
            url, data=data,
            headers={"API-Key": "invalid_key", "Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            results.append({"test": "auth_check", "status": resp.status, "error": "Expected error"})
            print(f"  Unexpected 200")
    except urllib.error.HTTPError as e:
        results.append({"test": "auth_check", "status": e.code, "error": None})
        print(f"  Status: {e.code} (expected 401/403)")
    except Exception as e:
        results.append({"test": "auth_check", "status": 0, "error": str(e)})
        print(f"  Error: {e}")

    # Test 2: Invalid alarm ID
    print("\n[2/4] Invalid alarm ID (999999999)...")
    r = resolve_alarm(999999999, comment="test invalid alarm")
    results.append({"test": "invalid_alarm", **r})
    print(f"  HTTP: {r['http_status']}, is_success: {r.get('is_success')}, message: {r.get('message', r.get('error', ''))}")

    if DRY_RUN:
        print("\n[3/4] SKIPPED (DRY_RUN=true) — would resolve botnet alarm", TEST_BOTNET_ALARM)
        results.append({"test": "resolve_botnet", "skipped": True, "alarm_id": TEST_BOTNET_ALARM})

        print(f"\n[4/4] SKIPPED (DRY_RUN=true) — would resolve PII alarm", TEST_PII_ALARM)
        results.append({"test": "resolve_pii", "skipped": True, "alarm_id": TEST_PII_ALARM})
    else:
        # Test 3: Resolve botnet alarm
        print(f"\n[3/4] Resolve botnet alarm {TEST_BOTNET_ALARM}...")
        r = resolve_alarm(TEST_BOTNET_ALARM, comment="E2E test — auto-resolved by Entra ID integration")
        results.append({"test": "resolve_botnet", **r})
        print(f"  HTTP: {r['http_status']}, is_success: {r.get('is_success')}, message: {r.get('message', r.get('error', ''))}")

        # Test 4: Resolve PII alarm
        print(f"\n[4/4] Resolve PII alarm {TEST_PII_ALARM}...")
        r = resolve_alarm(TEST_PII_ALARM, comment="E2E test — auto-resolved by Entra ID integration")
        results.append({"test": "resolve_pii", **r})
        print(f"  HTTP: {r['http_status']}, is_success: {r.get('is_success')}, message: {r.get('message', r.get('error', ''))}")

    # Save
    output = {"api": "Alarm Status Change", "company_id": COMPANY_ID, "dry_run": DRY_RUN, "results": results}
    out_path = Path(__file__).parent / "results" / "alarm_resolve_response.json"
    out_path.parent.mkdir(exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nSaved: {out_path}")

    ok = sum(1 for r in results if not r.get("error") and not r.get("skipped"))
    print(f"\n{'=' * 60}")
    print(f"SUMMARY: {ok}/{len(results)} successful")


if __name__ == "__main__":
    main()
