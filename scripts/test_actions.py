#!/usr/bin/env python3
"""
SOCRadar Entra ID Integration — Action-Level Tests
Tests each Entra ID action independently against test users.

Prerequisites:
  - Run setup_test_env.sh first
  - test_env.config must exist with test user IDs

Usage:
    python3 test_actions.py              # All tests
    python3 test_actions.py --test 2     # Single test
    python3 test_actions.py --skip-ropc  # Skip ROPC (MFA may block)
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
import urllib.parse
from pathlib import Path
from datetime import datetime, timezone

SCRIPT_DIR = Path(__file__).parent
RESULTS_DIR = SCRIPT_DIR / "results" / "actions"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Load config
# ---------------------------------------------------------------------------

for cfg in [SCRIPT_DIR / "test_env.config", SCRIPT_DIR / "test.env", SCRIPT_DIR / "deploy.config"]:
    if cfg.exists():
        with open(cfg) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip().strip("'\""))

TENANT_ID = os.environ.get("ENTRA_TENANT_ID", "01a14909-9a97-4ded-9af3-7ea42ea99b2f")
CLIENT_ID = os.environ.get("ENTRA_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("ENTRA_CLIENT_SECRET", "")
DOMAIN = os.environ.get("TENANT_DOMAIN", "SOCRadarCyberIntelligenceIn.onmicrosoft.com")

TEST1_UPN = os.environ.get("TEST1_UPN", f"socradar.test1@{DOMAIN}")
TEST2_UPN = os.environ.get("TEST2_UPN", f"socradar.test2@{DOMAIN}")
TEST3_UPN = os.environ.get("TEST3_UPN", f"socradar.test3@{DOMAIN}")
TEST1_ID = os.environ.get("TEST1_ID", "")
TEST2_ID = os.environ.get("TEST2_ID", "")
TEST3_ID = os.environ.get("TEST3_ID", "")
GROUP_ID = os.environ.get("GROUP_ID", "")
TEST_PASSWORD = os.environ.get("TEST_PASSWORD", "")

SOCRADAR_API_KEY = os.environ.get("SOCRADAR_API_KEY", "")
SOCRADAR_COMPANY_ID = os.environ.get("SOCRADAR_COMPANY_ID", "330")
WORKSPACE_ID = os.environ.get("WORKSPACE_ID", "")
WORKSPACE_KEY = os.environ.get("WORKSPACE_KEY", "")

GRAPH = "https://graph.microsoft.com/v1.0"
GRAPH_BETA = "https://graph.microsoft.com/beta"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class C:
    G = "\033[92m"; R = "\033[91m"; Y = "\033[93m"; B = "\033[1m"; E = "\033[0m"

def ok(m):   print(f"  {C.G}PASS{C.E} {m}")
def fail(m): print(f"  {C.R}FAIL{C.E} {m}")
def info(m): print(f"  INFO {m}")
def section(n, title): print(f"\n{C.B}── Test {n}: {title} ──{C.E}")

test_results = []


def save_pair(name, request_info, response_info):
    """Save request/response pair to JSON files."""
    with open(RESULTS_DIR / f"{name}-request.json", "w") as f:
        json.dump(request_info, f, indent=2, default=str)
    with open(RESULTS_DIR / f"{name}-response.json", "w") as f:
        json.dump(response_info, f, indent=2, default=str)


def graph_get(url, headers, name):
    req_info = {"method": "GET", "url": url, "timestamp": datetime.now(timezone.utc).isoformat()}
    start = time.time()
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read())
            resp_info = {"status": resp.status, "elapsed": round(time.time() - start, 3), "body": body}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")[:500]
        try: body = json.loads(raw)
        except: body = raw
        resp_info = {"status": e.code, "elapsed": round(time.time() - start, 3), "body": body}
    except Exception as e:
        resp_info = {"status": 0, "error": str(e)}
    save_pair(name, req_info, resp_info)
    return resp_info


def graph_post(url, headers, body_data, name, method="POST"):
    payload = json.dumps(body_data).encode("utf-8") if body_data else b""
    req_info = {"method": method, "url": url, "body": body_data, "timestamp": datetime.now(timezone.utc).isoformat()}
    start = time.time()
    try:
        h = {**headers, "Content-Type": "application/json"}
        req = urllib.request.Request(url, data=payload, headers=h, method=method)
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            body = json.loads(raw) if raw else {}
            resp_info = {"status": resp.status, "elapsed": round(time.time() - start, 3), "body": body}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")[:500]
        try: body = json.loads(raw)
        except: body = raw
        resp_info = {"status": e.code, "elapsed": round(time.time() - start, 3), "body": body}
    except Exception as e:
        resp_info = {"status": 0, "error": str(e)}
    save_pair(name, req_info, resp_info)
    return resp_info


def graph_patch(url, headers, body_data, name):
    return graph_post(url, headers, body_data, name, method="PATCH")


def graph_delete(url, headers, name):
    req_info = {"method": "DELETE", "url": url, "timestamp": datetime.now(timezone.utc).isoformat()}
    start = time.time()
    try:
        req = urllib.request.Request(url, headers=headers, method="DELETE")
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp_info = {"status": resp.status, "elapsed": round(time.time() - start, 3)}
    except urllib.error.HTTPError as e:
        resp_info = {"status": e.code, "elapsed": round(time.time() - start, 3)}
    except Exception as e:
        resp_info = {"status": 0, "error": str(e)}
    save_pair(name, req_info, resp_info)
    return resp_info


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_01_graph_token():
    section(1, "Graph Token Acquisition")
    url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "https://graph.microsoft.com/.default",
    }).encode()

    req_info = {"method": "POST", "url": url, "timestamp": datetime.now(timezone.utc).isoformat()}
    start = time.time()
    try:
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read())
            elapsed = round(time.time() - start, 3)
            resp_info = {"status": resp.status, "elapsed": elapsed,
                         "has_token": "access_token" in body,
                         "expires_in": body.get("expires_in")}
    except Exception as e:
        resp_info = {"status": 0, "error": str(e)}
        elapsed = round(time.time() - start, 3)

    save_pair("01-graph-token", req_info, resp_info)

    if resp_info.get("has_token"):
        ok(f"Token acquired ({elapsed}s, expires_in={resp_info.get('expires_in')})")
        test_results.append({"test": 1, "name": "graph_token", "passed": True})
        return body["access_token"]
    else:
        fail(f"Token failed: {resp_info}")
        test_results.append({"test": 1, "name": "graph_token", "passed": False})
        return None


def test_02_user_lookup(headers):
    section(2, "User Lookup")
    passed = 0

    # Existing user
    r = graph_get(f"{GRAPH}/users/{TEST1_UPN}?$select=id,userPrincipalName,accountEnabled,displayName", headers, "02-lookup-found")
    if r.get("status") == 200:
        ok(f"Found: {r['body'].get('displayName')} (enabled={r['body'].get('accountEnabled')})")
        passed += 1
    else:
        fail(f"Lookup {TEST1_UPN}: HTTP {r.get('status')}")

    # Non-existent user
    r = graph_get(f"{GRAPH}/users/nonexistent-e2e-test@{DOMAIN}", headers, "02-lookup-notfound")
    if r.get("status") == 404:
        ok("Non-existent user returns 404")
        passed += 1
    else:
        fail(f"Expected 404, got {r.get('status')}")

    test_results.append({"test": 2, "name": "user_lookup", "passed": passed == 2, "details": f"{passed}/2"})


def test_03_revoke_sessions(headers):
    section(3, "Revoke Sessions")
    r = graph_post(f"{GRAPH}/users/{TEST1_ID}/revokeSignInSessions", headers, None, "03-revoke-sessions")
    if r.get("status") in (200, 204):
        ok(f"Sessions revoked for test1 (HTTP {r['status']})")
        test_results.append({"test": 3, "name": "revoke_sessions", "passed": True})
    else:
        fail(f"HTTP {r.get('status')}: {r.get('body', '')}")
        test_results.append({"test": 3, "name": "revoke_sessions", "passed": False})


def test_04_add_to_group(headers):
    section(4, "Add to Group")
    body = {"@odata.id": f"{GRAPH}/directoryObjects/{TEST1_ID}"}
    r = graph_post(f"{GRAPH}/groups/{GROUP_ID}/members/$ref", headers, body, "04-add-to-group")
    if r.get("status") in (204, 400):  # 400 = already member
        ok(f"Add to group: HTTP {r['status']}")
        test_results.append({"test": 4, "name": "add_to_group", "passed": True})
    else:
        fail(f"HTTP {r.get('status')}")
        test_results.append({"test": 4, "name": "add_to_group", "passed": False})


def test_05_remove_from_group(headers):
    section(5, "Remove from Group")
    r = graph_delete(f"{GRAPH}/groups/{GROUP_ID}/members/{TEST3_ID}/$ref", headers, "05-remove-from-group")
    if r.get("status") in (204, 404):  # 404 = not a member
        ok(f"Remove from group: HTTP {r['status']}")
        test_results.append({"test": 5, "name": "remove_from_group", "passed": True})
    else:
        fail(f"HTTP {r.get('status')}")
        test_results.append({"test": 5, "name": "remove_from_group", "passed": False})


def test_06_disable_account(headers):
    section(6, "Disable Account")
    r = graph_patch(f"{GRAPH}/users/{TEST2_ID}", headers, {"accountEnabled": False}, "06-disable-account")
    if r.get("status") == 204:
        ok("Account disabled for test2")
        # Verify
        v = graph_get(f"{GRAPH}/users/{TEST2_ID}?$select=accountEnabled", headers, "06-disable-verify")
        if v.get("body", {}).get("accountEnabled") is False:
            ok("Verified: accountEnabled=false")
        test_results.append({"test": 6, "name": "disable_account", "passed": True})
    else:
        fail(f"HTTP {r.get('status')}")
        test_results.append({"test": 6, "name": "disable_account", "passed": False})


def test_07_enable_account(headers):
    section(7, "Enable Account (re-enable)")
    r = graph_patch(f"{GRAPH}/users/{TEST2_ID}", headers, {"accountEnabled": True}, "07-enable-account")
    if r.get("status") == 204:
        ok("Account re-enabled for test2")
        v = graph_get(f"{GRAPH}/users/{TEST2_ID}?$select=accountEnabled", headers, "07-enable-verify")
        if v.get("body", {}).get("accountEnabled") is True:
            ok("Verified: accountEnabled=true")
        test_results.append({"test": 7, "name": "enable_account", "passed": True})
    else:
        fail(f"HTTP {r.get('status')}")
        test_results.append({"test": 7, "name": "enable_account", "passed": False})


def test_08_password_change(headers):
    section(8, "Force Password Change")
    body = {"passwordProfile": {"forceChangePasswordNextSignIn": True, "forceChangePasswordNextSignInWithMfa": False}}
    r = graph_patch(f"{GRAPH}/users/{TEST1_ID}", headers, body, "08-password-change")
    if r.get("status") == 204:
        ok("Password change forced for test1")
        test_results.append({"test": 8, "name": "force_password_change", "passed": True})
    else:
        fail(f"HTTP {r.get('status')}")
        test_results.append({"test": 8, "name": "force_password_change", "passed": False})

    # Reset the flag so test user remains usable
    reset_body = {"passwordProfile": {"forceChangePasswordNextSignIn": False}}
    graph_patch(f"{GRAPH}/users/{TEST1_ID}", headers, reset_body, "08-password-change-reset")


def test_09_ropc(skip=False):
    section(9, "ROPC Password Validation")
    if skip:
        info("Skipped (--skip-ropc)")
        test_results.append({"test": 9, "name": "ropc", "passed": None, "skipped": True})
        return

    if not TEST_PASSWORD:
        info("Skipped — TEST_PASSWORD not set")
        test_results.append({"test": 9, "name": "ropc", "passed": None, "skipped": True})
        return

    url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    passed = 0

    # Correct password
    data = urllib.parse.urlencode({
        "grant_type": "password", "client_id": CLIENT_ID,
        "username": TEST1_UPN, "password": TEST_PASSWORD,
        "scope": "https://graph.microsoft.com/.default",
    }).encode()
    req_info = {"method": "POST", "url": url, "username": TEST1_UPN, "timestamp": datetime.now(timezone.utc).isoformat()}
    start = time.time()
    try:
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read())
            resp_info = {"status": resp.status, "has_token": "access_token" in body, "result": "valid"}
            ok("ROPC valid password → token acquired")
            passed += 1
    except urllib.error.HTTPError as e:
        raw = e.read().decode()[:500]
        if "AADSTS50076" in raw or "AADSTS50079" in raw:
            resp_info = {"status": e.code, "result": "mfa_blocked"}
            ok("ROPC → mfa_blocked (expected if MFA enabled)")
            passed += 1
        elif "AADSTS65001" in raw:
            resp_info = {"status": e.code, "result": "consent_required"}
            info("ROPC → consent required (enable 'Allow public client flows' on app)")
        else:
            resp_info = {"status": e.code, "result": "error", "body": raw[:200]}
            fail(f"ROPC valid password: HTTP {e.code}")
    save_pair("09-ropc-valid", req_info, resp_info)

    # Wrong password
    data2 = urllib.parse.urlencode({
        "grant_type": "password", "client_id": CLIENT_ID,
        "username": TEST1_UPN, "password": "WrongPassword!123",
        "scope": "https://graph.microsoft.com/.default",
    }).encode()
    try:
        req2 = urllib.request.Request(url, data=data2, headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req2, timeout=15) as resp2:
            resp_info2 = {"status": resp2.status, "result": "unexpected_success"}
            fail("ROPC wrong password should fail but got 200")
    except urllib.error.HTTPError as e2:
        raw2 = e2.read().decode()[:500]
        if "AADSTS50126" in raw2:
            resp_info2 = {"status": e2.code, "result": "invalid"}
            ok("ROPC wrong password → invalid (expected)")
            passed += 1
        else:
            resp_info2 = {"status": e2.code, "result": "other_error", "body": raw2[:200]}
            info(f"ROPC wrong password: HTTP {e2.code}")
    save_pair("09-ropc-invalid", {"method": "POST", "url": url}, resp_info2)

    test_results.append({"test": 9, "name": "ropc", "passed": passed >= 1, "details": f"{passed}/2"})


def test_10_confirm_compromised(headers):
    section(10, "Confirm Compromised (Identity Protection)")
    body = {"userIds": [TEST1_ID]}
    r = graph_post(f"{GRAPH_BETA}/riskyUsers/confirmCompromised", headers, body, "10-confirm-compromised")
    if r.get("status") == 204:
        ok("User confirmed compromised in Identity Protection")
        test_results.append({"test": 10, "name": "confirm_compromised", "passed": True})
    elif r.get("status") == 403:
        info("403 — requires IdentityRiskyUser.ReadWrite.All + P1/P2 license")
        test_results.append({"test": 10, "name": "confirm_compromised", "passed": None, "skipped": "license"})
    else:
        fail(f"HTTP {r.get('status')}")
        test_results.append({"test": 10, "name": "confirm_compromised", "passed": False})


def test_11_law_write():
    section(11, "LAW Test Write")
    if not WORKSPACE_ID or not WORKSPACE_KEY:
        info("Skipped — WORKSPACE_ID/KEY not set")
        test_results.append({"test": 11, "name": "law_write", "passed": None, "skipped": True})
        return

    record = [{
        "email": TEST1_UPN, "source": "action_test", "entra_status": "found",
        "actions_taken": "revoke_session,add_to_group,disable_account",
        "test_run": True, "timestamp": datetime.now(timezone.utc).isoformat(),
    }]
    body_str = json.dumps(record)
    content_length = len(body_str.encode())
    rfc = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
    sig_str = f"POST\n{content_length}\napplication/json\nx-ms-date:{rfc}\n/api/logs"
    sig = base64.b64encode(hmac.new(base64.b64decode(WORKSPACE_KEY), sig_str.encode(), hashlib.sha256).digest()).decode()

    url = f"https://{WORKSPACE_ID}.ods.opinsights.azure.com/api/logs?api-version=2016-04-01"
    req_info = {"method": "POST", "url": url, "log_type": "SOCRadar_ActionTest", "timestamp": datetime.now(timezone.utc).isoformat()}
    start = time.time()
    try:
        req = urllib.request.Request(url, data=body_str.encode(), headers={
            "Content-Type": "application/json", "Authorization": f"SharedKey {WORKSPACE_ID}:{sig}",
            "Log-Type": "SOCRadar_ActionTest", "x-ms-date": rfc,
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp_info = {"status": resp.status, "elapsed": round(time.time() - start, 3)}
            ok(f"LAW write: SOCRadar_ActionTest_CL (HTTP {resp.status})")
            test_results.append({"test": 11, "name": "law_write", "passed": True})
    except Exception as e:
        resp_info = {"status": 0, "error": str(e)}
        fail(f"LAW write error: {e}")
        test_results.append({"test": 11, "name": "law_write", "passed": False})
    save_pair("11-law-write", req_info, resp_info)


def test_12_alarm_resolve():
    section(12, "SOCRadar Alarm Resolve")
    if not SOCRADAR_API_KEY:
        info("Skipped — SOCRADAR_API_KEY not set")
        test_results.append({"test": 12, "name": "alarm_resolve", "passed": None, "skipped": True})
        return

    # Use a non-existent alarm ID to test the API call (won't actually resolve anything)
    url = f"https://platform.socradar.com/api/company/{SOCRADAR_COMPANY_ID}/alarms/status/change"
    body = {"alarm_ids": [999999999], "status": 2, "comments": "E2E test — ignore"}
    req_info = {"method": "POST", "url": url, "body": body, "timestamp": datetime.now(timezone.utc).isoformat()}
    start = time.time()
    try:
        payload = json.dumps(body).encode()
        req = urllib.request.Request(url, data=payload, headers={
            "API-Key": SOCRADAR_API_KEY, "Content-Type": "application/json"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            resp_body = json.loads(raw)
            resp_info = {"status": resp.status, "elapsed": round(time.time() - start, 3), "body": resp_body}
            ok(f"Alarm API reachable (HTTP {resp.status})")
            test_results.append({"test": 12, "name": "alarm_resolve", "passed": True})
    except urllib.error.HTTPError as e:
        resp_info = {"status": e.code, "elapsed": round(time.time() - start, 3)}
        info(f"HTTP {e.code} (may be expected for non-existent alarm)")
        test_results.append({"test": 12, "name": "alarm_resolve", "passed": e.code in (200, 400)})
    except Exception as e:
        resp_info = {"status": 0, "error": str(e)}
        fail(f"Error: {e}")
        test_results.append({"test": 12, "name": "alarm_resolve", "passed": False})
    save_pair("12-alarm-resolve", req_info, resp_info)


def test_13_force_mfa_reregistration(headers, skip=True):
    section(13, "Force MFA Re-registration (DESTRUCTIVE)")
    if skip:
        info("Skipped — use --run-destructive to execute (will delete test user's MFA methods)")
        test_results.append({"test": 13, "name": "force_mfa_reregistration", "passed": None, "skipped": "destructive"})
        return

    # GET methods first
    list_url = f"{GRAPH}/users/{TEST1_ID}/authentication/methods"
    req_info = {"method": "GET", "url": list_url, "timestamp": datetime.now(timezone.utc).isoformat()}
    try:
        req = urllib.request.Request(list_url, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
            methods = data.get("value", [])
            resp_info = {"status": resp.status, "method_count": len(methods)}
    except urllib.error.HTTPError as e:
        resp_info = {"status": e.code, "error": str(e)}
        save_pair("13-force-mfa-list", req_info, resp_info)
        if e.code in (401, 403):
            info(f"HTTP {e.code} — requires UserAuthenticationMethod.ReadWrite.All")
            test_results.append({"test": 13, "name": "force_mfa_reregistration", "passed": None, "skipped": "permission"})
        else:
            fail(f"List methods HTTP {e.code}")
            test_results.append({"test": 13, "name": "force_mfa_reregistration", "passed": False})
        return
    except Exception as e:
        fail(f"List error: {e}")
        test_results.append({"test": 13, "name": "force_mfa_reregistration", "passed": False})
        return
    save_pair("13-force-mfa-list", req_info, resp_info)

    PASSWORD_METHOD_ID = "28c10230-6103-485e-b985-444c60001490"
    TYPE_MAP = {
        "microsoft.graph.microsoftAuthenticatorAuthenticationMethod": "microsoftAuthenticatorMethods",
        "microsoft.graph.phoneAuthenticationMethod":                   "phoneMethods",
        "microsoft.graph.fido2AuthenticationMethod":                   "fido2Methods",
        "microsoft.graph.softwareOathAuthenticationMethod":            "softwareOathMethods",
        "microsoft.graph.windowsHelloForBusinessAuthenticationMethod": "windowsHelloForBusinessMethods",
        "microsoft.graph.emailAuthenticationMethod":                   "emailMethods",
        "microsoft.graph.temporaryAccessPassAuthenticationMethod":     "temporaryAccessPassMethods",
    }

    deleted = 0
    skipped = 0
    errors = []
    for m in methods:
        mid = m.get("id")
        odata = m.get("@odata.type", "").lstrip("#")
        if mid == PASSWORD_METHOD_ID:
            skipped += 1
            continue
        endpoint = TYPE_MAP.get(odata)
        if not endpoint:
            errors.append(f"unknown: {odata}")
            continue
        r = graph_delete(f"{GRAPH}/users/{TEST1_ID}/authentication/{endpoint}/{mid}", headers, f"13-delete-{endpoint}")
        if r.get("status") == 204:
            deleted += 1
        else:
            errors.append(f"{endpoint}: HTTP {r.get('status')}")

    info(f"deleted={deleted} skipped={skipped} errors={len(errors)}")
    passed = deleted > 0 or (len(methods) == 1 and skipped == 1)  # only password or nothing to delete = still OK
    if passed:
        ok(f"Force MFA re-registration: {deleted} method(s) deleted")
    else:
        fail(f"Force MFA re-registration failed: {errors}")
    test_results.append({"test": 13, "name": "force_mfa_reregistration", "passed": passed, "deleted": deleted, "skipped_password": skipped})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="SOCRadar Entra ID Action Tests")
    parser.add_argument("--test", type=int, help="Run single test by number (1-13)")
    parser.add_argument("--skip-ropc", action="store_true", help="Skip ROPC tests")
    parser.add_argument("--run-destructive", action="store_true", help="Run destructive tests (test 13 force_mfa_reregistration)")
    args = parser.parse_args()

    print(f"""
{'=' * 60}
  SOCRadar Entra ID — Action-Level Tests
{'=' * 60}
  Tenant:    {TENANT_ID[:8]}...
  Client:    {CLIENT_ID[:8]}...
  Test1:     {TEST1_UPN}
  Test2:     {TEST2_UPN}
  Test3:     {TEST3_UPN}
  Group:     {GROUP_ID[:8]}... ({os.environ.get('GROUP_NAME', '?')})
{'=' * 60}
""")

    if not CLIENT_ID or not CLIENT_SECRET:
        fail("ENTRA_CLIENT_ID/SECRET not set")
        return 1

    # Test 1: Get token (required for all other tests)
    token = test_01_graph_token()
    if not token:
        fail("Cannot proceed without Graph token")
        return 1

    headers = {"Authorization": f"Bearer {token}"}

    tests = {
        2: lambda: test_02_user_lookup(headers),
        3: lambda: test_03_revoke_sessions(headers),
        4: lambda: test_04_add_to_group(headers),
        5: lambda: test_05_remove_from_group(headers),
        6: lambda: test_06_disable_account(headers),
        7: lambda: test_07_enable_account(headers),
        8: lambda: test_08_password_change(headers),
        9: lambda: test_09_ropc(skip=args.skip_ropc),
        10: lambda: test_10_confirm_compromised(headers),
        11: lambda: test_11_law_write(),
        12: lambda: test_12_alarm_resolve(),
        13: lambda: test_13_force_mfa_reregistration(headers, skip=not args.run_destructive),
    }

    if args.test:
        if args.test == 1:
            pass  # already ran
        elif args.test in tests:
            tests[args.test]()
        else:
            fail(f"Unknown test: {args.test}")
    else:
        for t in sorted(tests.keys()):
            tests[t]()
            time.sleep(0.5)

    # Summary
    print(f"\n{'=' * 60}")
    total = len(test_results)
    passed = sum(1 for r in test_results if r.get("passed") is True)
    failed = sum(1 for r in test_results if r.get("passed") is False)
    skipped = sum(1 for r in test_results if r.get("passed") is None)
    print(f"  Tests: {total}  |  {C.G}Passed: {passed}{C.E}  |  {C.R}Failed: {failed}{C.E}  |  {C.Y}Skipped: {skipped}{C.E}")
    print(f"{'=' * 60}")

    # Save summary
    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total": total, "passed": passed, "failed": failed, "skipped": skipped,
        "results": test_results,
    }
    with open(RESULTS_DIR / "test-actions-summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    info(f"Results: {RESULTS_DIR}/")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
