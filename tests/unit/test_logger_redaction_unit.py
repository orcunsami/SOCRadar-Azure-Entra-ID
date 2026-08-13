#!/usr/bin/env python3
"""
Unit tests for SourceLogger secret redaction.

The two regressions these pin down:
  * a secret arriving as a %s ARGUMENT used to bypass redaction entirely
    (only the format string was scrubbed);
  * the apiKey spellings and the JSON form `"apiKey": "..."` were not
    covered at all.
"""

import logging
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "production" / "FunctionApp"))

from utils import logger as logmod  # noqa: E402


class RedactionTests(unittest.TestCase):

    def _capture(self, msg, *args):
        log = logmod.get_logger("botnet")
        with self.assertLogs("socradar.entra.botnet", level="INFO") as cm:
            log.info(msg, *args)
        return "\n".join(cm.output)

    def test_a_secret_in_a_format_argument_is_redacted(self):
        out = self._capture("remote response: %s", "password=SuperSecret123")
        self.assertNotIn("SuperSecret123", out)
        self.assertIn("password=your_password", out)

    def test_an_api_key_is_redacted_in_both_spellings(self):
        for text in ('apiKey=abcdef123456', 'api_key: abcdef123456',
                     '"apiKey": "abcdef123456"', "API-KEY = 'abcdef123456'"):
            out = self._capture("config row: %s", text)
            self.assertNotIn("abcdef123456", out, text)

    def test_a_delimiter_inside_the_value_does_not_split_the_redaction(self):
        out = self._capture("remote response: %s", "password=ab,cd-tail&next=1")
        self.assertNotIn("cd-tail", out)
        out = self._capture("header dump: %s", "Authorization: Bearer abc.def.ghi")
        self.assertNotIn("abc.def.ghi", out)

    def test_the_format_string_itself_is_still_redacted(self):
        out = self._capture("token=eyJhbGciOi.direct")
        self.assertNotIn("eyJhbGciOi", out)
        self.assertIn("token=your_token", out)

    def test_a_failed_render_keeps_the_line_and_redacts_it(self):
        # %d with a string argument cannot render; the line must survive
        # (with the args repr appended) and still be scrubbed.
        out = self._capture("count=%d", "secret=hidden123")
        self.assertNotIn("hidden123", out)

    def test_a_plain_line_passes_through_untouched(self):
        out = self._capture("Fetched 3 pages, 120 records")
        self.assertIn("Fetched 3 pages, 120 records", out)
        self.assertIn("[BOTNET]", out)

    def test_audit_summary_reports_the_no_address_count(self):
        with self.assertLogs("socradar.entra.audit", level="INFO") as cm:
            logmod.audit_summary(source="vip", total=5, employees=5, found=1,
                                 not_found=1, actions=0, errors=0,
                                 duration_sec=1.0, no_address=3)
        self.assertIn("no_address=3", "\n".join(cm.output))


if __name__ == "__main__":
    unittest.main()
