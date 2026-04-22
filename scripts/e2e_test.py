#!/usr/bin/env python3
"""
SOCRadar Entra ID Integration — End-to-End Test Suite

Tests the full pipeline: SOCRadar API → Entra ID → Log Analytics → Checkpoint
Can run against live APIs (with real credentials) or in dry-run mode.

Usage:
    # Full E2E with live APIs
    python3 e2e_test.py

    # Dry-run (API connectivity only, no writes)
    python3 e2e_test.py --dry-run

    # Single source
    python3 e2e_test.py --source botnet

    # Custom lookback (days)
    python3 e2e_test.py --lookback-days 150
"""

import os
import sys
import json
import time
import hmac
import base64
import hashlib
import argparse
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timezone, timedelta

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "deploy.config"
ENV_FILE = SCRIPT_DIR / "test.env"
RESULTS_DIR = SCRIPT_DIR / "results"

SOCRADAR_BASE = "https://platform.socradar.com/api"
GRAPH_BASE = "https://graph.microsoft.com/v1.0"
LAW_URL = "https://{workspace_id}.ods.opinsights.azure.com/api/logs?api-version=2016-04-01"

# Load config
for cfg_path in [ENV_FILE, CONFIG_FILE]:
    if cfg_path.exists():
        with open(cfg_path) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip().strip("'\""))

API_KEY = os.environ.get("SOCRADAR_API_KEY", "")
COMPANY_ID = os.environ.get("SOCRADAR_COMPANY_ID", "330")
TENANT_ID = os.environ.get("ENTRA_TENANT_ID", "")
CLIENT_ID = os.environ.get("ENTRA_CLIENT_ID", "")
# CLIENT_SECRET removed — Graph auth is secretless (FIC). Tests use az CLI token.
WORKSPACE_ID = os.environ.get("WORKSPACE_ID", "")
WORKSPACE_KEY = os.environ.get("WORKSPACE_KEY", "")
SECURITY_GROUP_ID = os.environ.get("SECURITY_GROUP_ID", "")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    END = "\033[0m"

def ok(msg):
    print(f"  {Colors.GREEN}PASS{Colors.END} {msg}")

def fail(msg):
    print(f"  {Colors.RED}FAIL{Colors.END} {msg}")

def warn(msg):
    print(f"  {Colors.YELLOW}WARN{Colors.END} {msg}")

def info(msg):
    print(f"  {Colors.CYAN}INFO{Colors.END} {msg}")

def section(title):
    print(f"\n{Colors.BOLD}{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}{Colors.END}")


def http_get(url, headers, timeout=30):
    """Simple GET returning (status, body_dict, elapsed_ms)."""
    start = time.time()
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw), int((time.time() - start) * 1000)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:500]
        return e.code, {"error": body}, int((time.time() - start) * 1000)
    except Exception as e:
        return 0, {"error": str(e)}, int((time.time() - start) * 1000)


def http_post(url, headers, data=None, json_data=None, timeout=30):
    """Simple POST returning (status, body_dict, elapsed_ms)."""
    start = time.time()
    if json_data is not None:
        payload = json.dumps(json_data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif data is not None:
        payload = urllib.parse.urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    else:
        payload = b""

    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                body = {"raw": raw.decode("utf-8", errors="replace")[:500]}
            return resp.status, body, int((time.time() - start) * 1000)
    except urllib.error.HTTPError as e:
        body_raw = e.read().decode("utf-8", errors="replace")[:500]
        try:
            body = json.loads(body_raw)
        except json.JSONDecodeError:
            body = {"error": body_raw}
        return e.code, body, int((time.time() - start) * 1000)
    except Exception as e:
        return 0, {"error": str(e)}, int((time.time() - start) * 1000)


import urllib.parse  # for POST encoding

# ---------------------------------------------------------------------------
# Test: SOCRadar API Connectivity
# ---------------------------------------------------------------------------

def test_socradar_api_connectivity():
    section("TEST 1: SOCRadar API Connectivity")
    results = {"test": "socradar_connectivity", "passed": 0, "failed": 0, "details": []}

    if not API_KEY:
        fail("SOCRADAR_API_KEY not set")
        results["failed"] += 1
        return results

    # Test with valid key
    url = f"{SOCRADAR_BASE}/company/{COMPANY_ID}/dark-web-monitoring/botnet-data/v2?page=1&limit=1"
    status, body, ms = http_get(url, {"API-Key": API_KEY})
    if status == 200 and body.get("is_success"):
        ok(f"API reachable (HTTP 200, {ms}ms)")
        results["passed"] += 1
    else:
        fail(f"API returned HTTP {status} ({ms}ms)")
        results["failed"] += 1

    # Test with invalid key
    status, body, ms = http_get(url, {"API-Key": "invalid_test_key"})
    if status in (401, 403):
        ok(f"Invalid key rejected (HTTP {status})")
        results["passed"] += 1
    else:
        warn(f"Invalid key returned unexpected HTTP {status}")
        results["failed"] += 1

    return results


# ---------------------------------------------------------------------------
# Test: SOCRadar Source Endpoints (Botnet, PII, VIP)
# ---------------------------------------------------------------------------

def test_socradar_source(source_name, endpoint_path, start_date):
    section(f"TEST 2: SOCRadar {source_name.upper()} Source")
    results = {"test": f"socradar_{source_name}", "passed": 0, "failed": 0, "details": []}

    if not API_KEY:
        fail("SOCRADAR_API_KEY not set — skipping")
        results["failed"] += 1
        return results

    url = f"{SOCRADAR_BASE}/company/{COMPANY_ID}/{endpoint_path}?page=1&limit=100&startDate={start_date}"
    headers = {"API-Key": API_KEY}

    info(f"Fetching {source_name} from {start_date} (page=1, limit=100)...")
    status, body, ms = http_get(url, headers)

    if status == 404 and source_name == "vip":
        warn(f"VIP endpoint returned 404 — UNVERIFIED endpoint may not exist for company {COMPANY_ID}")
        results["details"].append({"status": 404, "note": "unverified_endpoint"})
        return results

    if status != 200:
        fail(f"HTTP {status} ({ms}ms)")
        results["failed"] += 1
        return results

    if not body.get("is_success"):
        fail(f"is_success=false: {body.get('message', 'unknown')}")
        results["failed"] += 1
        return results

    ok(f"API success (HTTP 200, {ms}ms)")
    results["passed"] += 1

    payload = body.get("data", {})
    records = payload.get("data", [])
    total = payload.get("total_data_count", 0)

    info(f"Total records: {total:,}")
    info(f"Page records: {len(records)}")

    if total > 0:
        ok(f"Data available: {total:,} records since {start_date}")
        results["passed"] += 1
    else:
        warn(f"No data since {start_date}")

    # Check fields
    if records:
        fields = list(records[0].keys())
        info(f"Fields: {fields}")
        results["details"].append({"fields": fields, "total": total, "sample_count": len(records)})

        # Employee filter check
        employee_count = sum(1 for r in records if r.get("isEmployee", False))
        info(f"Employees in page: {employee_count}/{len(records)}")

        # Password check (botnet/pii only)
        if source_name in ("botnet", "pii"):
            pw_count = sum(1 for r in records if r.get("password"))
            pw_masked = sum(1 for r in records if r.get("password") and "****" in str(r.get("password", "")))
            pw_plaintext = pw_count - pw_masked
            info(f"Passwords: {pw_count} total ({pw_masked} masked, {pw_plaintext} plaintext)")

    # Pagination test
    if total > 100:
        info("Testing pagination (page 2)...")
        url2 = f"{SOCRADAR_BASE}/company/{COMPANY_ID}/{endpoint_path}?page=2&limit=100&startDate={start_date}"
        status2, body2, ms2 = http_get(url2, headers)
        if status2 == 200 and body2.get("is_success"):
            p2_records = body2.get("data", {}).get("data", [])
            ok(f"Pagination works: page 2 has {len(p2_records)} records ({ms2}ms)")
            results["passed"] += 1
        else:
            fail(f"Pagination failed: HTTP {status2}")
            results["failed"] += 1
        time.sleep(1)

    results["details"].append({"total_data_count": total})
    return results


# ---------------------------------------------------------------------------
# Test: Microsoft Graph API (Entra ID)
# ---------------------------------------------------------------------------

def test_entra_id_graph():
    section("TEST 3: Microsoft Entra ID (Graph API)")
    results = {"test": "entra_id_graph", "passed": 0, "failed": 0, "details": []}

    # Acquire token via az CLI (secretless)
    info("Acquiring Graph API token via az CLI...")
    import subprocess
    try:
        az_result = subprocess.run(
            ["az", "account", "get-access-token", "--resource", "https://graph.microsoft.com", "--query", "accessToken", "-o", "tsv"],
            capture_output=True, text=True, timeout=15
        )
        token = az_result.stdout.strip()
        if not token or len(token) < 50:
            warn(f"az CLI token failed: {az_result.stderr.strip()[:200]}")
            results["details"].append({"skipped": True, "reason": "az_cli_no_token"})
            return results
    except Exception as e:
        warn(f"az CLI error: {e}")
        results["details"].append({"skipped": True, "reason": str(e)})
        return results

    ok("Graph token acquired via az CLI")
    results["passed"] += 1

    graph_headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Test: List users (verify permissions)
    info("Testing User.Read.All permission...")
    status, body, ms = http_get(f"{GRAPH_BASE}/users?$top=1&$select=id,userPrincipalName,accountEnabled", graph_headers)
    if status == 200 and "value" in body:
        users = body["value"]
        ok(f"User.Read.All works ({ms}ms, got {len(users)} user)")
        results["passed"] += 1
        if users:
            info(f"Sample: {users[0].get('userPrincipalName', '?')}")
            results["details"].append({"sample_user": users[0].get("userPrincipalName")})
    elif status == 403:
        fail(f"User.Read.All denied (HTTP 403) — check app permissions")
        results["failed"] += 1
    else:
        fail(f"User list failed: HTTP {status}")
        results["failed"] += 1

    # Test: Lookup a specific user (the first user found)
    if status == 200 and body.get("value"):
        test_upn = body["value"][0].get("userPrincipalName", "")
        if test_upn:
            info(f"Testing user lookup: {test_upn}...")
            status, body, ms = http_get(f"{GRAPH_BASE}/users/{test_upn}", graph_headers)
            if status == 200:
                ok(f"User lookup works ({ms}ms)")
                results["passed"] += 1
                uid = body.get("id", "")
                enabled = body.get("accountEnabled", True)
                info(f"User ID: {uid[:8]}..., Enabled: {enabled}")
            else:
                fail(f"User lookup failed: HTTP {status}")
                results["failed"] += 1

    # Test: Lookup non-existent user
    info("Testing non-existent user lookup...")
    status, body, ms = http_get(f"{GRAPH_BASE}/users/nonexistent-test-user-12345@invalid.example.com", graph_headers)
    if status == 404:
        ok(f"Non-existent user returns 404 ({ms}ms)")
        results["passed"] += 1
    else:
        warn(f"Non-existent user returned HTTP {status} (expected 404)")

    # Test: Security group (if configured)
    if SECURITY_GROUP_ID:
        info(f"Testing security group access: {SECURITY_GROUP_ID[:8]}...")
        status, body, ms = http_get(f"{GRAPH_BASE}/groups/{SECURITY_GROUP_ID}?$select=id,displayName,membershipRule", graph_headers)
        if status == 200:
            ok(f"Security group accessible: {body.get('displayName', '?')} ({ms}ms)")
            results["passed"] += 1
        else:
            fail(f"Security group access failed: HTTP {status}")
            results["failed"] += 1
    else:
        info("SECURITY_GROUP_ID not set — skipping group test")

    return results


# ---------------------------------------------------------------------------
# Test: Log Analytics Workspace (LAW) Write
# ---------------------------------------------------------------------------

def test_law_write(dry_run=False):
    section("TEST 4: Log Analytics Workspace (Write)")
    results = {"test": "law_write", "passed": 0, "failed": 0, "details": []}

    if not WORKSPACE_ID or not WORKSPACE_KEY:
        warn("WORKSPACE_ID/KEY not set — skipping LAW write test")
        results["details"].append({"skipped": True, "reason": "no_credentials"})
        return results

    # Build test record
    test_record = {
        "email": "e2e-test@example.com",
        "source": "e2e_test",
        "entra_status": "test",
        "password_present": False,
        "is_plaintext": False,
        "actions_taken": "none",
        "test_timestamp": datetime.now(timezone.utc).isoformat(),
        "test_run": True,
    }

    body_str = json.dumps([test_record])
    content_length = len(body_str.encode("utf-8"))
    rfc1123_date = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")

    # Build HMAC signature
    string_to_hash = f"POST\n{content_length}\napplication/json\nx-ms-date:{rfc1123_date}\n/api/logs"
    decoded_key = base64.b64decode(WORKSPACE_KEY)
    encoded_hash = base64.b64encode(
        hmac.new(decoded_key, string_to_hash.encode("utf-8"), digestmod=hashlib.sha256).digest()
    ).decode("utf-8")
    signature = f"SharedKey {WORKSPACE_ID}:{encoded_hash}"

    ok("HMAC signature built successfully")
    results["passed"] += 1

    if dry_run:
        info("DRY RUN: Skipping actual LAW write")
        results["details"].append({"dry_run": True})
        return results

    # Actually write to a test table
    url = LAW_URL.format(workspace_id=WORKSPACE_ID)
    headers = {
        "Content-Type": "application/json",
        "Authorization": signature,
        "Log-Type": "SOCRadar_E2ETest",
        "x-ms-date": rfc1123_date,
    }
    req = urllib.request.Request(url, data=body_str.encode("utf-8"), headers=headers, method="POST")

    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            ms = int((time.time() - start) * 1000)
            if resp.status in (200, 201, 202):
                ok(f"LAW write success: SOCRadar_E2ETest_CL (HTTP {resp.status}, {ms}ms)")
                results["passed"] += 1
            else:
                fail(f"LAW write unexpected status: HTTP {resp.status}")
                results["failed"] += 1
    except urllib.error.HTTPError as e:
        ms = int((time.time() - start) * 1000)
        fail(f"LAW write failed: HTTP {e.code} ({ms}ms)")
        info(f"Body: {e.read().decode('utf-8', errors='replace')[:200]}")
        results["failed"] += 1
    except Exception as e:
        fail(f"LAW write error: {e}")
        results["failed"] += 1

    # Test audit table write
    audit_record = {
        "source": "e2e_test",
        "total_records": 1,
        "employee_records": 1,
        "found_count": 0,
        "not_found_count": 0,
        "actions_taken": 0,
        "error_count": 0,
        "duration_sec": 0.1,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    body_str2 = json.dumps([audit_record])
    content_length2 = len(body_str2.encode("utf-8"))
    rfc1123_date2 = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
    string_to_hash2 = f"POST\n{content_length2}\napplication/json\nx-ms-date:{rfc1123_date2}\n/api/logs"
    encoded_hash2 = base64.b64encode(
        hmac.new(decoded_key, string_to_hash2.encode("utf-8"), digestmod=hashlib.sha256).digest()
    ).decode("utf-8")
    signature2 = f"SharedKey {WORKSPACE_ID}:{encoded_hash2}"

    headers2 = {
        "Content-Type": "application/json",
        "Authorization": signature2,
        "Log-Type": "SOCRadar_EntraID_Audit",
        "x-ms-date": rfc1123_date2,
    }
    req2 = urllib.request.Request(url, data=body_str2.encode("utf-8"), headers=headers2, method="POST")

    start2 = time.time()
    try:
        with urllib.request.urlopen(req2, timeout=30) as resp2:
            ms2 = int((time.time() - start2) * 1000)
            if resp2.status in (200, 201, 202):
                ok(f"Audit table write success: SOCRadar_EntraID_Audit_CL (HTTP {resp2.status}, {ms2}ms)")
                results["passed"] += 1
            else:
                fail(f"Audit write unexpected: HTTP {resp2.status}")
                results["failed"] += 1
    except urllib.error.HTTPError as e2:
        fail(f"Audit write failed: HTTP {e2.code}")
        results["failed"] += 1
    except Exception as e2:
        fail(f"Audit write error: {e2}")
        results["failed"] += 1

    return results


# ---------------------------------------------------------------------------
# Test: Password Sanitization (unit test)
# ---------------------------------------------------------------------------

def test_password_sanitization():
    section("TEST 5: Password Sanitization (Unit)")
    results = {"test": "password_sanitization", "passed": 0, "failed": 0}

    # Add FunctionApp to path for imports
    func_app_dir = SCRIPT_DIR.parent / "production" / "FunctionApp"
    sys.path.insert(0, str(func_app_dir))

    try:
        from utils.sanitize import sanitize_password, build_law_password_fields
    except ImportError as e:
        fail(f"Could not import sanitize module: {e}")
        results["failed"] += 1
        return results

    # Test 1: Empty password
    r = sanitize_password(None)
    if not r["present"] and r["_raw"] is None:
        ok("Empty password handled correctly")
        results["passed"] += 1
    else:
        fail(f"Empty password: expected present=False, got {r}")
        results["failed"] += 1

    # Test 2: Plaintext password
    r = sanitize_password("MySecret123!")
    if r["present"] and r["is_plaintext"] and r["masked"] == "M***!" and r["_raw"] == "MySecret123!":
        ok("Plaintext password sanitized correctly")
        results["passed"] += 1
    else:
        fail(f"Plaintext: got masked={r['masked']}, is_plaintext={r['is_plaintext']}")
        results["failed"] += 1

    # Test 3: Already masked password
    r = sanitize_password("a****3")
    if r["present"] and not r["is_plaintext"] and r["masked"] == "a****3":
        ok("Masked password preserved correctly")
        results["passed"] += 1
    else:
        fail(f"Masked: got is_plaintext={r['is_plaintext']}, masked={r['masked']}")
        results["failed"] += 1

    # Test 4: Single character
    r = sanitize_password("x")
    if r["present"] and r["masked"] == "***":
        ok("Single char password masked to '***'")
        results["passed"] += 1
    else:
        fail(f"Single char: masked={r['masked']}")
        results["failed"] += 1

    # Test 5: build_law_password_fields (plaintext disabled)
    sanitized = sanitize_password("SecretPW")
    fields = build_law_password_fields(sanitized, enable_log_plaintext=False)
    if "password" not in fields and fields["password_present"] and fields["is_plaintext"]:
        ok("LAW fields: plaintext stripped when disabled")
        results["passed"] += 1
    else:
        fail(f"LAW fields with plaintext disabled: {fields}")
        results["failed"] += 1

    # Test 6: build_law_password_fields (plaintext enabled)
    fields2 = build_law_password_fields(sanitized, enable_log_plaintext=True)
    if fields2.get("password") == "SecretPW":
        ok("LAW fields: plaintext included when enabled")
        results["passed"] += 1
    else:
        fail(f"LAW fields with plaintext enabled: {fields2}")
        results["failed"] += 1

    return results


# ---------------------------------------------------------------------------
# Test: Config Loader (unit test)
# ---------------------------------------------------------------------------

def test_config_loader():
    section("TEST 6: Config Loader (Unit)")
    results = {"test": "config_loader", "passed": 0, "failed": 0}

    func_app_dir = SCRIPT_DIR.parent / "production" / "FunctionApp"
    sys.path.insert(0, str(func_app_dir))

    try:
        from utils.config import _bool, _int, _get
    except ImportError as e:
        fail(f"Could not import config module: {e}")
        results["failed"] += 1
        return results

    # Test _bool
    os.environ["_TEST_BOOL_TRUE"] = "true"
    os.environ["_TEST_BOOL_FALSE"] = "false"
    os.environ["_TEST_BOOL_ONE"] = "1"
    os.environ["_TEST_BOOL_YES"] = "yes"

    if _bool("_TEST_BOOL_TRUE") is True:
        ok("_bool('true') = True")
        results["passed"] += 1
    else:
        fail("_bool('true') != True")
        results["failed"] += 1

    if _bool("_TEST_BOOL_FALSE") is False:
        ok("_bool('false') = False")
        results["passed"] += 1
    else:
        fail("_bool('false') != False")
        results["failed"] += 1

    if _bool("_TEST_BOOL_ONE") is True and _bool("_TEST_BOOL_YES") is True:
        ok("_bool('1') and _bool('yes') = True")
        results["passed"] += 1
    else:
        fail("_bool('1'/'yes') not True")
        results["failed"] += 1

    if _bool("_NONEXISTENT", default=True) is True:
        ok("_bool default works")
        results["passed"] += 1
    else:
        fail("_bool default broken")
        results["failed"] += 1

    # Test _int
    os.environ["_TEST_INT"] = "42"
    if _int("_TEST_INT") == 42:
        ok("_int('42') = 42")
        results["passed"] += 1
    else:
        fail(f"_int('42') = {_int('_TEST_INT')}")
        results["failed"] += 1

    if _int("_NONEXISTENT", default=99) == 99:
        ok("_int default works")
        results["passed"] += 1
    else:
        fail("_int default broken")
        results["failed"] += 1

    # Cleanup
    for k in ["_TEST_BOOL_TRUE", "_TEST_BOOL_FALSE", "_TEST_BOOL_ONE", "_TEST_BOOL_YES", "_TEST_INT"]:
        os.environ.pop(k, None)

    return results


# ---------------------------------------------------------------------------
# Test: Logger & Redaction (unit test)
# ---------------------------------------------------------------------------

def test_logger_redaction():
    section("TEST 7: Logger Password Redaction (Unit)")
    results = {"test": "logger_redaction", "passed": 0, "failed": 0}

    func_app_dir = SCRIPT_DIR.parent / "production" / "FunctionApp"
    sys.path.insert(0, str(func_app_dir))

    try:
        from utils.logger import _redact
    except ImportError as e:
        fail(f"Could not import logger module: {e}")
        results["failed"] += 1
        return results

    # Test password redaction
    test_cases = [
        ("password=Secret123", "password=***REDACTED***"),
        ("token=abc123def", "token=***REDACTED***"),
        ("credential=test", "credential=***REDACTED***"),
        ("no sensitive data here", "no sensitive data here"),
        ("user password=MyPass! logged in", "user password=***REDACTED*** logged in"),
    ]

    for input_str, expected in test_cases:
        result = _redact(input_str)
        if result == expected:
            ok(f"Redact: '{input_str[:30]}...' → correct")
            results["passed"] += 1
        else:
            fail(f"Redact: '{input_str[:30]}...' → got '{result}', expected '{expected}'")
            results["failed"] += 1

    return results


# ---------------------------------------------------------------------------
# Test: Checkpoint Logic (unit test)
# ---------------------------------------------------------------------------

def test_checkpoint_logic():
    section("TEST 8: Checkpoint Date Logic (Unit)")
    results = {"test": "checkpoint_logic", "passed": 0, "failed": 0}

    func_app_dir = SCRIPT_DIR.parent / "production" / "FunctionApp"
    sys.path.insert(0, str(func_app_dir))

    # checkpoint.py imports azure.data.tables at module level which may not be
    # installed in the test environment. Mock the azure modules before importing.
    _mocked = []
    for mod in ["azure", "azure.data", "azure.data.tables", "azure.core", "azure.core.exceptions"]:
        if mod not in sys.modules:
            sys.modules[mod] = type(sys)("mock_" + mod)
            _mocked.append(mod)
    if _mocked:
        sys.modules["azure.data.tables"].TableServiceClient = None
        sys.modules["azure.data.tables"].TableEntity = None
        sys.modules["azure.core.exceptions"].ResourceNotFoundError = Exception

    try:
        from utils.checkpoint import get_start_date
    except ImportError as e:
        fail(f"Could not import checkpoint module: {e}")
        results["failed"] += 1
        return results

    # Test 1: With existing checkpoint
    chk = {"last_start_date": "2025-12-01"}
    result = get_start_date(chk, initial_lookback_minutes=600)
    if result == "2025-12-01":
        ok("Existing checkpoint date used correctly")
        results["passed"] += 1
    else:
        fail(f"Expected '2025-12-01', got '{result}'")
        results["failed"] += 1

    # Test 2: Empty checkpoint, 5-month lookback
    chk_empty = {}
    result = get_start_date(chk_empty, initial_lookback_minutes=216000)
    expected_date = (datetime.now(timezone.utc) - timedelta(minutes=216000)).strftime("%Y-%m-%d")
    if result == expected_date:
        ok(f"5-month lookback calculated: {result}")
        results["passed"] += 1
    else:
        fail(f"Expected '{expected_date}', got '{result}'")
        results["failed"] += 1

    # Test 3: Default lookback (600 min = 10 hours)
    result = get_start_date({}, initial_lookback_minutes=600)
    expected = (datetime.now(timezone.utc) - timedelta(minutes=600)).strftime("%Y-%m-%d")
    if result == expected:
        ok(f"Default lookback (10h): {result}")
        results["passed"] += 1
    else:
        fail(f"Expected '{expected}', got '{result}'")
        results["failed"] += 1

    return results


# ---------------------------------------------------------------------------
# Test: Full Pipeline Simulation
# ---------------------------------------------------------------------------

def test_full_pipeline(start_date, dry_run=False):
    section("TEST 9: Full Pipeline Simulation")
    results = {"test": "full_pipeline", "passed": 0, "failed": 0, "details": []}

    if not API_KEY:
        warn("No SOCRadar API key — skipping pipeline test")
        return results

    info(f"Simulating full pipeline with start_date={start_date}")

    # Step 1: Fetch botnet data
    info("[1/5] Fetching botnet data...")
    url = f"{SOCRADAR_BASE}/company/{COMPANY_ID}/dark-web-monitoring/botnet-data/v2?page=1&limit=10&startDate={start_date}"
    status, body, ms = http_get(url, {"API-Key": API_KEY})

    if status != 200 or not body.get("is_success"):
        fail(f"Botnet fetch failed: HTTP {status}")
        results["failed"] += 1
        return results

    records = body.get("data", {}).get("data", [])
    total = body.get("data", {}).get("total_data_count", 0)
    ok(f"Fetched {len(records)} records (total={total:,}, {ms}ms)")
    results["passed"] += 1

    if not records:
        info("No records to process — pipeline test complete (no data)")
        return results

    # Step 2: Filter employees
    employees = [r for r in records if r.get("isEmployee", False)]
    info(f"[2/5] Employee filter: {len(employees)}/{len(records)}")

    if not employees:
        info("No employees found — pipeline test complete (no employees)")
        results["passed"] += 1
        return results

    # Step 3: Entra ID lookup (via az CLI token)
    info("[3/5] Entra ID lookup...")
    try:
        az_r = subprocess.run(
            ["az", "account", "get-access-token", "--resource", "https://graph.microsoft.com", "--query", "accessToken", "-o", "tsv"],
            capture_output=True, text=True, timeout=15
        )
        e2e_token = az_r.stdout.strip()
    except Exception:
        e2e_token = ""

    if e2e_token and len(e2e_token) > 50:
        graph_headers = {"Authorization": f"Bearer {e2e_token}", "Content-Type": "application/json"}

        found = 0
        not_found = 0
        for emp in employees[:5]:  # test first 5 only
            email = emp.get("user", emp.get("email", ""))
            if not email:
                continue
            s, b, m = http_get(f"{GRAPH_BASE}/users/{email}", graph_headers)
            if s == 200:
                found += 1
            elif s == 404:
                not_found += 1
            time.sleep(0.2)

        ok(f"Entra lookup: {found} found, {not_found} not found (of {min(5, len(employees))})")
        results["passed"] += 1
        results["details"].append({"entra_found": found, "entra_not_found": not_found})
    else:
        info("[3/5] az CLI token not available — skipping Entra lookup")

    # Step 4: Password sanitization
    info("[4/5] Password sanitization...")
    func_app_dir = SCRIPT_DIR.parent / "production" / "FunctionApp"
    sys.path.insert(0, str(func_app_dir))
    try:
        from utils.sanitize import sanitize_password
        pw_stats = {"present": 0, "plaintext": 0, "masked": 0}
        for emp in employees:
            pw = emp.get("password")
            s = sanitize_password(pw)
            if s["present"]:
                pw_stats["present"] += 1
                if s["is_plaintext"]:
                    pw_stats["plaintext"] += 1
                else:
                    pw_stats["masked"] += 1
        ok(f"Sanitized: {pw_stats['present']} passwords ({pw_stats['plaintext']} plaintext, {pw_stats['masked']} masked)")
        results["passed"] += 1
    except ImportError:
        warn("Could not import sanitize — skipping")

    # Step 5: LAW write simulation
    if WORKSPACE_ID and WORKSPACE_KEY and not dry_run:
        info("[5/5] LAW write test record...")
        test_record = {
            "email": employees[0].get("user", "test@example.com"),
            "source": "botnet",
            "entra_status": "e2e_test",
            "password_present": bool(employees[0].get("password")),
            "is_plaintext": False,
            "actions_taken": "none",
            "test_run": True,
            "pipeline_test": True,
        }

        body_str = json.dumps([test_record])
        content_length = len(body_str.encode("utf-8"))
        rfc1123_date = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
        string_to_hash = f"POST\n{content_length}\napplication/json\nx-ms-date:{rfc1123_date}\n/api/logs"
        decoded_key = base64.b64decode(WORKSPACE_KEY)
        encoded_hash = base64.b64encode(
            hmac.new(decoded_key, string_to_hash.encode("utf-8"), digestmod=hashlib.sha256).digest()
        ).decode("utf-8")

        law_headers = {
            "Content-Type": "application/json",
            "Authorization": f"SharedKey {WORKSPACE_ID}:{encoded_hash}",
            "Log-Type": "SOCRadar_Botnet",
            "x-ms-date": rfc1123_date,
        }
        law_req = urllib.request.Request(
            LAW_URL.format(workspace_id=WORKSPACE_ID),
            data=body_str.encode("utf-8"), headers=law_headers, method="POST"
        )
        try:
            with urllib.request.urlopen(law_req, timeout=30) as law_resp:
                if law_resp.status in (200, 201, 202):
                    ok(f"LAW write: SOCRadar_Botnet_CL (HTTP {law_resp.status})")
                    results["passed"] += 1
                else:
                    fail(f"LAW write: HTTP {law_resp.status}")
                    results["failed"] += 1
        except Exception as e:
            fail(f"LAW write error: {e}")
            results["failed"] += 1
    else:
        info("[5/5] LAW write skipped (dry-run or no credentials)")

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="SOCRadar Entra ID E2E Test Suite")
    parser.add_argument("--dry-run", action="store_true", help="Skip write operations")
    parser.add_argument("--source", choices=["botnet", "pii", "vip", "all"], default="all", help="Source to test")
    parser.add_argument("--lookback-days", type=int, default=150, help="Lookback days for start_date (default: 150 = ~5 months)")
    args = parser.parse_args()

    start_date = (datetime.now(timezone.utc) - timedelta(days=args.lookback_days)).strftime("%Y-%m-%d")

    print(f"""
{'=' * 60}
  SOCRadar Entra ID Integration — E2E Test Suite
{'=' * 60}
  Date:           {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}
  Dry Run:        {args.dry_run}
  Source Filter:  {args.source}
  Lookback:       {args.lookback_days} days (start_date={start_date})
  Company ID:     {COMPANY_ID}
  API Key:        {'***' + API_KEY[-4:] if len(API_KEY) > 4 else '(not set)'}
  Tenant ID:      {TENANT_ID[:8] + '...' if TENANT_ID else '(not set)'}
  Workspace ID:   {WORKSPACE_ID[:8] + '...' if WORKSPACE_ID else '(not set)'}
{'=' * 60}
""")

    all_results = []
    total_passed = 0
    total_failed = 0

    # Test 1: API connectivity
    r = test_socradar_api_connectivity()
    all_results.append(r)
    total_passed += r["passed"]
    total_failed += r["failed"]
    time.sleep(1)

    # Test 2: Source endpoints
    source_map = {
        "botnet": ("dark-web-monitoring/botnet-data/v2",),
        "pii":    ("dark-web-monitoring/pii-exposure/v2",),
        "vip":    ("vip-protection/v2",),
    }
    sources = ["botnet", "pii", "vip"] if args.source == "all" else [args.source]
    for src in sources:
        r = test_socradar_source(src, source_map[src][0], start_date)
        all_results.append(r)
        total_passed += r["passed"]
        total_failed += r["failed"]
        time.sleep(1)

    # Test 3: Entra ID Graph API
    r = test_entra_id_graph()
    all_results.append(r)
    total_passed += r["passed"]
    total_failed += r["failed"]

    # Test 4: LAW write
    r = test_law_write(dry_run=args.dry_run)
    all_results.append(r)
    total_passed += r["passed"]
    total_failed += r["failed"]

    # Test 5-8: Unit tests
    for test_fn in [test_password_sanitization, test_config_loader, test_logger_redaction, test_checkpoint_logic]:
        r = test_fn()
        all_results.append(r)
        total_passed += r["passed"]
        total_failed += r["failed"]

    # Test 9: Full pipeline
    r = test_full_pipeline(start_date, dry_run=args.dry_run)
    all_results.append(r)
    total_passed += r["passed"]
    total_failed += r["failed"]

    # Summary
    section("TEST SUMMARY")
    total = total_passed + total_failed
    print(f"""
  Total Tests:  {total}
  {Colors.GREEN}Passed:       {total_passed}{Colors.END}
  {Colors.RED}Failed:       {total_failed}{Colors.END}

  Result: {Colors.GREEN + 'ALL PASSED' + Colors.END if total_failed == 0 else Colors.RED + f'{total_failed} FAILED' + Colors.END}
""")

    # Save results
    RESULTS_DIR.mkdir(exist_ok=True)
    results_file = RESULTS_DIR / f"e2e_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dry_run": args.dry_run,
        "lookback_days": args.lookback_days,
        "start_date": start_date,
        "total_passed": total_passed,
        "total_failed": total_failed,
        "results": all_results,
    }
    with open(results_file, "w") as f:
        json.dump(output, f, indent=2, default=str)
    info(f"Results saved: {results_file}")

    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
