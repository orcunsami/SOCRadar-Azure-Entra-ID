"""Every message that stops the triggerFirstRun deploymentScript goes to stderr.

The portal's error banner shows only what the script wrote to stderr. A failure
message on stdout ends up in the script's Logs tab and the banner reads "the
script failed without returning any errors". Checked in the committed JSON and in
the bicep source it is built from.
"""

import json
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TEMPLATE = REPO / "production" / "azuredeploy.json"
BICEP = REPO / "production" / "azuredeploy.bicep"


def _script_from_json():
    doc = json.loads(TEMPLATE.read_text())
    res = doc["resources"]
    res = list(res.values()) if isinstance(res, dict) else res
    node = [r for r in res if r.get("type") == "Microsoft.Resources/deploymentScripts"
            and "triggerFirstRun" in json.dumps(r["name"])][0]
    return node["properties"]["scriptContent"]


def _script_from_bicep():
    text = BICEP.read_text()
    start = text.index("scriptContent: 'set -e")
    return text[start:text.index("\n", start)]


class ScriptMessagesToStderr(unittest.TestCase):

    def _check(self, script, label):
        script = script.replace("\\'", "'")  # bicep escapes its single quotes
        exits = [m.start() for m in re.finditer(r"exit 1", script)]
        self.assertGreaterEqual(len(exits), 7, "%s: the key, download, zip, settings, storage, pointer and index failures must be found" % label)
        for pos in exits:
            before = script[max(0, pos - 220):pos]
            stmt = before.rsplit("echo ", 1)[-1] if "echo " in before else ""
            self.assertRegex(stmt, r"""^(?:'[^']+'|"[^"]+")\s*>&2\s*;?\s*$""",
                             "%s: exit 1 not preceded by an echo to stderr: ...%s" % (label, before[-90:].replace("\n", " ")))

    def test_json(self):
        self._check(_script_from_json(), "azuredeploy.json")

    def test_bicep(self):
        self._check(_script_from_bicep(), "azuredeploy.bicep")

    def test_bicep_and_json_carry_the_same_key_check(self):
        """The bicep is the source and the JSON is what the Deploy button serves. A hand edit of
        one without the other ships a key check nobody wrote; the build must reproduce it."""
        def block(script):
            script = re.sub(r"\\(.)", lambda m: {"n": "\n", "'": "'", "\\": "\\"}.get(m.group(1), m.group(0)), script) if "\\'" in script else script
            return re.sub(r"\s+", " ", script[script.index("# key check"):script.index("# end key check")]).strip()
        self.assertEqual(block(_script_from_bicep()), block(_script_from_json()),
                         "production/azuredeploy.bicep and azuredeploy.json carry different key checks")


if __name__ == "__main__":
    unittest.main()

