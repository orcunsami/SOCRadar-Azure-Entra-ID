#!/usr/bin/env python3
"""
Unit tests for fail-closed config parsing.

An unrecognised boolean used to fall through to the DEFAULT, so
"ENABLE_REVOKE_SESSION=disabled" left an action armed whose default is on.
Unknown now reads as off; a non-numeric ceiling can be told to become 0.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "production" / "FunctionApp"))

from utils import config  # noqa: E402


class BoolTests(unittest.TestCase):

    def test_recognised_values_parse(self):
        cases = {"true": True, "1": True, "yes": True, "on": True,
                 "false": False, "0": False, "no": False, "off": False,
                 "TRUE": True, " False ": False}
        for raw, want in cases.items():
            with patch.dict("os.environ", {"K": raw}):
                self.assertIs(config._bool("K", default=True), want, raw)

    def test_an_unrecognised_value_reads_as_false_not_default(self):
        for raw in ("disabled", "enable", "none", "evet"):
            with patch.dict("os.environ", {"K": raw}):
                self.assertIs(config._bool("K", default=True), False, raw)

    def test_an_unset_value_keeps_the_default(self):
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("K_UNSET", None)
            self.assertIs(config._bool("K_UNSET", default=True), True)
            self.assertIs(config._bool("K_UNSET", default=False), False)

    def test_the_unrecognised_value_is_logged_as_an_error(self):
        with patch.dict("os.environ", {"K": "disabled"}):
            with self.assertLogs("socradar.entra.config", level="ERROR"):
                config._bool("K", default=True)


class IntTests(unittest.TestCase):

    def test_a_valid_number_parses(self):
        with patch.dict("os.environ", {"K": "42"}):
            self.assertEqual(config._int("K", 7), 42)

    def test_unset_keeps_the_default(self):
        import os
        os.environ.pop("K_UNSET", None)
        self.assertEqual(config._int("K_UNSET", 7), 7)

    def test_garbage_falls_back_to_the_default_and_logs(self):
        with patch.dict("os.environ", {"K": "abc"}):
            with self.assertLogs("socradar.entra.config", level="ERROR"):
                self.assertEqual(config._int("K", 7), 7)

    def test_a_ceiling_can_close_on_garbage(self):
        # A broken limit must not silently restore the default ceiling.
        with patch.dict("os.environ", {"K": "5O"}):  # letter O typo
            with self.assertLogs("socradar.entra.config", level="ERROR"):
                self.assertEqual(config._int("K", 50, on_invalid=0), 0)


if __name__ == "__main__":
    unittest.main()
