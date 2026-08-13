#!/usr/bin/env python3
"""
Unit tests for run-summary accounting.

The identity these pin down: on a finished run, every record falls into
exactly one bucket and the buckets add up to total_records. A summary that
cannot account for its own input is hiding something (a dropped record, a
silently skipped path). A truncated run is the one legitimate exception.

Needs the azure packages (function_app imports azure.functions), same as CI.
"""

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "production" / "FunctionApp"))

import function_app  # noqa: E402

BUCKETS = ("found", "not_found", "domain_filtered", "no_address",
           "lookup_disabled", "no_token", "lookup_failed", "errors")


def _accounted(audit):
    return sum(audit[b] for b in BUCKETS)


class AccountingTests(unittest.TestCase):

    def _run(self, employees, conf_extra=None, tenants=None, lookup=None,
             start_time=None):
        conf = {
            "enable_user_lookup": True,
            "storage_account_name": "teststorage",
            "verified_domains": [],
            "enable_ropc": False,
            "enable_revoke_session": False,
            "enable_add_to_group": False,
            "enable_remove_from_group": False,
            "enable_disable_account": False,
            "enable_enable_account": False,
            "enable_password_change": False,
            "enable_confirm_risky": False,
            "enable_force_mfa_reregistration": False,
            "enable_create_incident": False,
            "enable_resolve_alarm": False,
            "security_group_id": "",
        }
        conf.update(conf_extra or {})
        written = []
        patches = [
            patch.object(function_app.src_botnet, "fetch", return_value=employees),
            patch.object(function_app.law, "write_records",
                         side_effect=lambda c, s, r: written.extend(r)),
            patch.object(function_app.cp, "load", return_value={}),
            patch.object(function_app.cp, "save"),
        ]
        if lookup is not None:
            patches.append(patch.object(function_app.entra, "lookup_user",
                                        side_effect=lookup))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return function_app._process_source(
            source_name="botnet", conf=conf, credential=None,
            tenant_headers_map=dict(tenants or {}),
            function_start_time=start_time or time.time()), written

    def test_every_skip_path_lands_in_exactly_one_bucket(self):
        employees = [
            {"name": "no address"},                                # no_address
            {"email": "out@other.com"},                            # domain_filtered
            {"email": "hit@corp.com"},                             # found
            {"email": "miss@corp.com"},                            # not_found
        ]
        lookup = lambda email, headers: (
            ({"id": "u1", "accountEnabled": True}, 200)
            if email.startswith("hit") else (None, 404))
        audit, written = self._run(
            employees,
            conf_extra={"verified_domains": ["corp.com"]},
            tenants={"t1": {"Authorization": "Bearer x"}},
            lookup=lookup)
        self.assertEqual(audit["no_address"], 1)
        self.assertEqual(audit["domain_filtered"], 1)
        self.assertEqual(audit["found"], 1)
        self.assertEqual(audit["not_found"], 1)
        self.assertEqual(_accounted(audit), audit["total"])
        self.assertEqual(len(written), 4, "every record must reach the table")

    def test_lookup_disabled_and_no_token_are_counted(self):
        audit, _ = self._run([{"email": "a@x.com"}, {"email": "b@x.com"}],
                             conf_extra={"enable_user_lookup": False})
        self.assertEqual(audit["lookup_disabled"], 2)
        self.assertEqual(_accounted(audit), audit["total"])

        audit, _ = self._run([{"email": "a@x.com"}], tenants={})
        self.assertEqual(audit["no_token"], 1)
        self.assertEqual(_accounted(audit), audit["total"])

    def test_a_permission_denied_lookup_is_lookup_failed_not_error(self):
        audit, written = self._run(
            [{"email": "p@x.com"}],
            tenants={"t1": {"Authorization": "Bearer x"}},
            lookup=lambda email, headers: (None, 403))
        self.assertEqual(audit["lookup_failed"], 1)
        self.assertEqual(audit["errors"], 0)
        self.assertEqual(written[0]["entra_status"], "lookup_permission_denied")
        self.assertEqual(_accounted(audit), audit["total"])

    def test_a_truncated_run_says_so_and_accounts_for_less(self):
        # A start time far in the past exhausts the budget on the first record.
        audit, written = self._run(
            [{"email": "a@x.com"}, {"email": "b@x.com"}],
            conf_extra={"enable_user_lookup": False},
            start_time=time.time() - function_app.TIME_BUDGET_SECONDS - 5)
        self.assertTrue(audit["truncated"])
        self.assertEqual(written, [])
        self.assertLess(_accounted(audit), audit["total"])

    def test_a_finished_run_reports_truncated_false(self):
        audit, _ = self._run([{"email": "a@x.com"}],
                             conf_extra={"enable_user_lookup": False})
        self.assertFalse(audit["truncated"])


if __name__ == "__main__":
    unittest.main()
