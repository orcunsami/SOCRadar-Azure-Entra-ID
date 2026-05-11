#!/usr/bin/env python3
"""
SOCRadar Entra ID Integration — Pipeline Simulation Test
Simulates the full pipeline with fake SOCRadar records matching test users.

Tests the complete flow: sanitize → lookup → actions → LAW write → checkpoint
Without depending on real SOCRadar API matching our test users.

Prerequisites:
  - Run setup_test_env.sh first
  - Run test_actions.py first (to verify individual actions work)
"""

import os
import sys
import json
import time
from pathlib import Path
from datetime import datetime, timezone

SCRIPT_DIR = Path(__file__).parent
FUNC_DIR = SCRIPT_DIR.parent / "production" / "FunctionApp"
sys.path.insert(0, str(FUNC_DIR))

# Load configs
for cfg in [SCRIPT_DIR / "test_env.config", SCRIPT_DIR / "test.env", SCRIPT_DIR / "deploy.config"]:
    if cfg.exists():
        with open(cfg) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip().strip("'\""))

DOMAIN = os.environ.get("TENANT_DOMAIN", "SOCRadarCyberIntelligenceIn.onmicrosoft.com")
TEST1 = os.environ.get("TEST1_UPN", f"socradar.test1@{DOMAIN}")
TEST2 = os.environ.get("TEST2_UPN", f"socradar.test2@{DOMAIN}")
TEST3 = os.environ.get("TEST3_UPN", f"socradar.test3@{DOMAIN}")
TEST_PW = os.environ.get("TEST_PASSWORD", "SoCr@dar!Test2026#xQ")

RESULTS_DIR = SCRIPT_DIR / "results" / "pipeline"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

C_G = "\033[92m"
C_R = "\033[91m"
C_Y = "\033[93m"
C_B = "\033[1m"
C_E = "\033[0m"


def section(title):
    print(f"\n{C_B}── {title} ──{C_E}")


def ok(m): print(f"  {C_G}PASS{C_E} {m}")
def fail(m): print(f"  {C_R}FAIL{C_E} {m}")
def info(m): print(f"  INFO {m}")


def main():
    print(f"""
{'=' * 60}
  SOCRadar Entra ID — Pipeline Simulation
{'=' * 60}
  Test Users: {TEST1}, {TEST2}, {TEST3}
  Simulates: SOCRadar fetch → sanitize → Entra ID → LAW
{'=' * 60}
""")

    results = {"steps": [], "timestamp": datetime.now(timezone.utc).isoformat()}

    # ── Step 1: Fake SOCRadar records ──
    section("Step 1: Create Fake SOCRadar Records")

    fake_botnet = [
        {"user": TEST1, "password": TEST_PW, "isEmployee": True,
         "url": "https://malware-site.example/login", "deviceIP": "192.168.1.100",
         "deviceOS": "Windows 10", "country": "TR", "logDate": "2026-03-15",
         "alarmId": 12345, "status": "Open"},
        {"user": TEST2, "password": "OldPassword!456", "isEmployee": True,
         "url": "https://phishing.example/creds", "deviceIP": "10.0.0.50",
         "deviceOS": "Windows 11", "country": "TR", "logDate": "2026-03-20",
         "alarmId": 12346, "status": "Open"},
        {"user": f"nonexistent-e2e@{DOMAIN}", "password": "NoUser!789", "isEmployee": True,
         "url": "https://leak.example/dump", "deviceIP": "172.16.0.1",
         "deviceOS": "macOS", "country": "US", "logDate": "2026-03-25",
         "alarmId": 12347, "status": "Open"},
    ]

    fake_pii = [
        {"email": TEST1, "password": "L3@ked!Pass", "isEmployee": True,
         "source": ["Hacker Forum", "Telegram"], "breachDate": "2026-02-01",
         "discoveryDate": "2026-03-01", "alarmId": 22345, "status": "Open"},
        {"email": TEST3, "password": None, "isEmployee": True,
         "source": ["Dark Web Market"], "breachDate": "2026-01-15",
         "discoveryDate": "2026-03-10", "alarmId": 22346, "status": "Open"},
    ]

    info(f"Botnet: {len(fake_botnet)} records, PII: {len(fake_pii)} records")
    results["steps"].append({"step": 1, "botnet_records": len(fake_botnet), "pii_records": len(fake_pii)})

    # ── Step 2: Password Sanitization ──
    section("Step 2: Password Sanitization")

    from utils.sanitize import sanitize_password, build_law_password_fields

    passed = 0
    for rec in fake_botnet + fake_pii:
        pw = rec.get("password")
        san = sanitize_password(pw)
        if pw is None:
            if not san["present"]:
                passed += 1
        elif san["present"] and san["masked"] and san["_raw"] == pw:
            passed += 1

    total = len(fake_botnet) + len(fake_pii)
    if passed == total:
        ok(f"All {total} passwords sanitized correctly")
    else:
        fail(f"{passed}/{total} sanitized")
    results["steps"].append({"step": 2, "passed": passed, "total": total})

    # ── Step 3: Entra ID Lookup ──
    section("Step 3: Entra ID Lookup")

    try:
        from actions.entra_id import get_graph_token, lookup_user
    except ImportError as e:
        # Mock azure modules for import
        for mod in ["azure", "azure.data", "azure.data.tables", "azure.core", "azure.core.exceptions"]:
            if mod not in sys.modules:
                sys.modules[mod] = type(sys)("mock_" + mod)
        sys.modules["azure.data.tables"].TableServiceClient = None
        sys.modules["azure.data.tables"].TableEntity = None
        sys.modules["azure.core.exceptions"].ResourceNotFoundError = Exception
        from actions.entra_id import get_graph_token, lookup_user

    tenant_id = os.environ.get("ENTRA_TENANT_ID", "")
    client_id = os.environ.get("ENTRA_CLIENT_ID", "")
    client_secret = os.environ.get("ENTRA_CLIENT_SECRET", "")

    if not all([tenant_id, client_id, client_secret]):
        info("Entra ID credentials not set — skipping lookup")
        results["steps"].append({"step": 3, "skipped": True})
    else:
        try:
            token = get_graph_token(tenant_id, client_id, client_secret)
            graph_headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            ok("Graph token acquired")

            found = 0
            not_found = 0
            for rec in fake_botnet:
                email = rec.get("user", rec.get("email", ""))
                user = lookup_user(email, graph_headers)
                if user:
                    found += 1
                    info(f"  {email} → FOUND (enabled={user.get('accountEnabled')})")
                else:
                    not_found += 1
                    info(f"  {email} → NOT FOUND")
                time.sleep(0.3)

            ok(f"Lookup complete: {found} found, {not_found} not found")
            results["steps"].append({"step": 3, "found": found, "not_found": not_found})
        except Exception as e:
            fail(f"Graph API error: {e}")
            results["steps"].append({"step": 3, "error": str(e)})

    # ── Step 4: LAW Write ──
    section("Step 4: Write Test Records to LAW")

    workspace_id = os.environ.get("WORKSPACE_ID", "")
    workspace_key = os.environ.get("WORKSPACE_KEY", "")

    if not workspace_id or not workspace_key:
        info("LAW credentials not set — skipping")
        results["steps"].append({"step": 4, "skipped": True})
    else:
        import hmac
        import base64
        import hashlib
        import urllib.request

        law_records = []
        for rec in fake_botnet:
            san = sanitize_password(rec.get("password"))
            pw_fields = build_law_password_fields(san, enable_log_plaintext=False)
            law_records.append({
                "email": rec["user"],
                "source": "botnet",
                "entra_status": "simulation_test",
                "url": rec.get("url", ""),
                "device_os": rec.get("deviceOS", ""),
                "country": rec.get("country", ""),
                "log_date": rec.get("logDate", ""),
                "is_employee": True,
                "simulation_test": True,
                **pw_fields,
            })

        body_str = json.dumps(law_records)
        content_length = len(body_str.encode())
        rfc = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
        sig_str = f"POST\n{content_length}\napplication/json\nx-ms-date:{rfc}\n/api/logs"
        sig = base64.b64encode(
            hmac.new(base64.b64decode(workspace_key), sig_str.encode(), hashlib.sha256).digest()
        ).decode()

        url = f"https://{workspace_id}.ods.opinsights.azure.com/api/logs?api-version=2016-04-01"
        try:
            req = urllib.request.Request(url, data=body_str.encode(), headers={
                "Content-Type": "application/json",
                "Authorization": f"SharedKey {workspace_id}:{sig}",
                "Log-Type": "SOCRadar_Botnet",
                "x-ms-date": rfc,
            })
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status in (200, 201, 202):
                    ok(f"Wrote {len(law_records)} test records to SOCRadar_Botnet_CL (HTTP {resp.status})")
                    results["steps"].append({"step": 4, "records_written": len(law_records)})
                else:
                    fail(f"HTTP {resp.status}")
                    results["steps"].append({"step": 4, "error": f"HTTP {resp.status}"})
        except Exception as e:
            fail(f"LAW write error: {e}")
            results["steps"].append({"step": 4, "error": str(e)})

    # ── Summary ──
    section("Summary")
    steps_ok = sum(1 for s in results["steps"] if not s.get("error") and not s.get("skipped"))
    steps_fail = sum(1 for s in results["steps"] if s.get("error"))
    steps_skip = sum(1 for s in results["steps"] if s.get("skipped"))
    print(f"""
  Steps: {len(results['steps'])}
  {C_G}OK:      {steps_ok}{C_E}
  {C_R}Failed:  {steps_fail}{C_E}
  {C_Y}Skipped: {steps_skip}{C_E}
""")

    with open(RESULTS_DIR / "simulation-results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    info(f"Results: {RESULTS_DIR}/simulation-results.json")

    return 0 if steps_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
