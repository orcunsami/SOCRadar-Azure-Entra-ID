#!/usr/bin/env python3
"""
Reusing an App Registration must finish clean (decision 8 Sep 2026): the
deployment leaves the credential step to an owner instead of failing on it.

The deploy button serves the JSON, people edit the bicep, and the output the
customer copies must name the credential the way the script does - three
places that drift apart silently, so all three are pinned here.
"""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = json.loads((ROOT / "production" / "azuredeploy.json").read_text())
SOURCE = (ROOT / "production" / "azuredeploy.bicep").read_text()


class SkipFicDefault(unittest.TestCase):

    def test_built_template_defaults_to_skipping_the_script(self):
        self.assertIs(TEMPLATE["parameters"]["SkipFicCreation"]["defaultValue"], True)

    def test_source_says_the_same(self):
        self.assertIn("param SkipFicCreation bool = true", SOURCE)

    def test_the_default_is_not_described_as_the_failing_branch(self):
        desc = TEMPLATE["parameters"]["SkipFicCreation"]["metadata"]["description"]
        self.assertNotIn("default false", desc.lower())
        self.assertNotIn("shows Failed", desc)

    def test_output_command_names_the_credential_like_the_script(self):
        cmd = TEMPLATE["outputs"]["ficCommandToRun"]["value"]
        self.assertIn("resourceGroup().name", cmd)
        self.assertIn("socradar-entraid-", cmd)
        self.assertIn("-uami", cmd)
        self.assertNotIn("socradar-entraid-uami", cmd)

    def test_next_step_splits_on_the_parameter(self):
        self.assertIn("parameters('SkipFicCreation')", TEMPLATE["outputs"]["nextStep"]["value"])


if __name__ == "__main__":
    unittest.main()
