#!/usr/bin/env python3
"""
Unit tests for address-less findings.

A record without an email/user (common for VIP: the finding names a person,
not an account) used to be dropped on the floor — never written to Log
Analytics, never counted. It must land in the table as skipped_no_address
and be counted in the run summary.

Needs the azure packages (function_app imports azure.functions), same as CI.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "production" / "FunctionApp"))

import function_app  # noqa: E402


def _conf():
    return {
        "enable_user_lookup": False,
        "storage_account_name": "teststorage",
        "verified_domains": [],
    }


class NoAddressTests(unittest.TestCase):

    def _run(self, employees):
        written = []
        with patch.object(function_app.src_botnet, "fetch", return_value=employees), \
             patch.object(function_app.law, "write_records",
                          side_effect=lambda conf, src, recs: written.extend(recs)), \
             patch.object(function_app.cp, "load", return_value={}), \
             patch.object(function_app.cp, "save"):
            audit = function_app._process_source(
                source_name="botnet", conf=_conf(), credential=None,
                tenant_headers_map={}, function_start_time=__import__("time").time())
        return audit, written

    def test_a_record_without_an_address_is_written_and_counted(self):
        audit, written = self._run([
            {"name": "A VIP Person", "severity": "HIGH"},
            {"email": "someone@example.com"},
        ])
        self.assertEqual(audit["no_address"], 1)
        statuses = [r.get("entra_status") for r in written]
        self.assertIn("skipped_no_address", statuses)
        self.assertEqual(len(written), 2, "both records must reach the table")

    def test_the_no_address_record_carries_empty_action_fields(self):
        _, written = self._run([{"name": "A VIP Person"}])
        rec = written[0]
        self.assertEqual(rec["entra_status"], "skipped_no_address")
        self.assertEqual(rec["entra_tenant_id"], "")
        self.assertEqual(rec["actions_taken"], [])
        self.assertNotIn("_checkpoint_update", rec)

    def test_an_addressed_record_still_takes_the_normal_path(self):
        audit, written = self._run([{"email": "someone@example.com"}])
        self.assertEqual(audit["no_address"], 0)
        self.assertEqual(written[0]["entra_status"], "skipped_user_lookup_disabled")


if __name__ == "__main__":
    unittest.main()
