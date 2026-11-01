"""CreateWorkspace defaults to false: a misspelled WorkspaceName fails before anything is created
instead of silently creating a second, empty workspace. Creating one is the opt-in (true).
Checked in the committed JSON and in the bicep source it is built from."""

import json
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


class CreateWorkspaceDefault(unittest.TestCase):

    def test_json_default_is_false(self):
        doc = json.loads((REPO / "production" / "azuredeploy.json").read_text())
        self.assertIs(doc["parameters"]["CreateWorkspace"]["defaultValue"], False)

    def test_bicep_default_is_false(self):
        text = (REPO / "production" / "azuredeploy.bicep").read_text()
        self.assertRegex(text, r"param CreateWorkspace bool = false\b")


if __name__ == "__main__":
    unittest.main()
