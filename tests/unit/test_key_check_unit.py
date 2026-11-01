"""A rejected SOCRadar API key fails the deployment instead of a green deploy that imports nothing.

The deploymentScript asks the SOCRadar API for one botnet page with the key. Only a 401 stops
the deployment; a timeout, a 403 or a 5xx continues (the key is not known to be bad). The key
reaches curl on stdin, never on argv, and arrives as a secure environment value. The same
wiring must exist in the bicep source, which is what the JSON is built from.
"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TEMPLATE = REPO / "production" / "azuredeploy.json"
BICEP = REPO / "production" / "azuredeploy.bicep"
KEY = "KEY-SECRET-0123456789"

SHIM = """#!/bin/bash
echo "$@" >> "$FAKE_ARGV"
cat > "$FAKE_STDIN"
[ "$FAKE_CODE" = 000 ] && { printf 000; exit 7; }
printf %s "$FAKE_CODE"
"""


def _node():
    doc = json.loads(TEMPLATE.read_text())
    res = doc["resources"]
    res = list(res.values()) if isinstance(res, dict) else res
    return [r for r in res if r.get("type") == "Microsoft.Resources/deploymentScripts"
            and "triggerFirstRun" in json.dumps(r["name"])][0]["properties"]


PROPS = _node()
SCRIPT = PROPS["scriptContent"]
ENV = {e["name"]: e for e in PROPS["environmentVariables"]}
BLOCK = SCRIPT[SCRIPT.index("# key check"):SCRIPT.index("# end key check")]


def run(code, key=KEY, company="132", base="https://platform.socradar.com"):
    with tempfile.TemporaryDirectory() as tmp:
        shim = os.path.join(tmp, "curl")
        Path(shim).write_text(SHIM)
        os.chmod(shim, 0o755)
        env = dict(os.environ, PATH=tmp + os.pathsep + os.environ["PATH"], FAKE_CODE=code,
                   FAKE_ARGV=os.path.join(tmp, "argv"), FAKE_STDIN=os.path.join(tmp, "stdin"),
                   SOCRADAR_API_KEY=key, COMPANY_ID=company, BASE_URL=base)
        r = subprocess.run(["bash", "-c", "set -e\n" + BLOCK + "\necho REACHED_NEXT_STEP"], env=env,
                           capture_output=True, text=True)
        argv = Path(env["FAKE_ARGV"]).read_text() if os.path.exists(env["FAKE_ARGV"]) else None
        stdin = Path(env["FAKE_STDIN"]).read_text() if os.path.exists(env["FAKE_STDIN"]) else None
        return r, argv, stdin


class KeyCheck(unittest.TestCase):

    def test_wiring(self):
        self.assertIn("secureValue", ENV["SOCRADAR_API_KEY"])
        self.assertNotIn("value", ENV["SOCRADAR_API_KEY"])
        self.assertIn("SocradarApiKey", ENV["SOCRADAR_API_KEY"]["secureValue"])
        self.assertIn("SocradarCompanyId", ENV["COMPANY_ID"]["value"])
        self.assertIn("SocradarBaseUrl", ENV["BASE_URL"]["value"])
        self.assertNotIn("set -x", SCRIPT, "xtrace would print the key")
        self.assertLess(SCRIPT.index("# key check"), SCRIPT.index("PACKAGE_URL"),
                        "the key check must run before the package is downloaded")

    def test_bicep_has_the_same_wiring(self):
        text = BICEP.read_text()
        self.assertIn("secureValue: SocradarApiKey", text)
        self.assertIn("value: SocradarCompanyId", text)
        self.assertIn("value: SocradarBaseUrl", text)
        self.assertIn("# key check", text)

    def test_good_key_continues_and_stays_off_argv(self):
        r, argv, stdin = run("200")
        self.assertEqual(r.returncode, 0)
        self.assertIn("REACHED_NEXT_STEP", r.stdout)
        self.assertNotIn(KEY, argv)
        self.assertIn(KEY, stdin)
        self.assertIn("/api/company/132/dark-web-monitoring/botnet-data/v2", argv)

    def test_401_stops_on_stderr_without_the_key(self):
        r, _, _ = run("401")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("REACHED_NEXT_STEP", r.stdout)
        self.assertIn("rejected", r.stderr)
        self.assertNotIn(KEY, r.stdout + r.stderr)

    def test_other_answers_do_not_stop_the_deployment(self):
        for code in ("500", "403", "000"):
            r, _, _ = run(code)
            self.assertEqual(r.returncode, 0, "HTTP %s must not stop the deployment" % code)
            self.assertIn("REACHED_NEXT_STEP", r.stdout)

    def test_nothing_to_check_means_no_call(self):
        for kw in (dict(key=""), dict(company=""), dict(base="")):
            r, argv, _ = run("401", **kw)
            self.assertEqual(r.returncode, 0)
            self.assertIsNone(argv, "curl must not be called: %r" % kw)


if __name__ == "__main__":
    unittest.main()
