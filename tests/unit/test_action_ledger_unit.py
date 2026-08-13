#!/usr/bin/env python3
"""
Unit tests for the action idempotency ledger.

The defect these pin down: the checkpoint hold makes re-reading a window
normal, and without a ledger every re-read repeats every action — the same
person gets revoke_session (or an unrecoverable MFA reset) applied on every
retry. Within one window an action runs once; a NEW window acts again by
design, because a new window is a new finding.

Needs the azure packages (function_app imports azure.functions), same as CI.
"""

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "production" / "FunctionApp"))

import function_app  # noqa: E402
from actions import action_ledger  # noqa: E402


class RowKeyTests(unittest.TestCase):

    def test_key_is_deterministic_and_case_insensitive_on_email(self):
        a = action_ledger._row_key("A@X.com", "revoke_session", "2026-08-13")
        b = action_ledger._row_key("a@x.com", "revoke_session", "2026-08-13")
        self.assertEqual(a, b)

    def test_key_separates_action_and_window(self):
        base = action_ledger._row_key("a@x.com", "revoke_session", "w1")
        self.assertNotEqual(base, action_ledger._row_key("a@x.com", "disable_account", "w1"))
        self.assertNotEqual(base, action_ledger._row_key("a@x.com", "revoke_session", "w2"))

    def test_raw_email_never_appears_in_the_key(self):
        key = action_ledger._row_key("person@corp.com", "revoke_session", "w1")
        self.assertNotIn("person", key)


class InMemoryLedgerTests(unittest.TestCase):

    def test_record_then_check(self):
        led = action_ledger.InMemoryActionLedger()
        self.assertFalse(led.already_applied("botnet", "a@x.com", "revoke_session", "w1"))
        led.record("botnet", "a@x.com", "revoke_session", "w1")
        self.assertTrue(led.already_applied("botnet", "a@x.com", "revoke_session", "w1"))
        self.assertFalse(led.already_applied("pii", "a@x.com", "revoke_session", "w1"),
                         "sources are separate partitions")


class ProcessSourceLedgerTests(unittest.TestCase):
    """The integration that matters: a re-read of the SAME window must not
    repeat an action; a NEW window must."""

    def _conf(self):
        return {
            "enable_user_lookup": True,
            "enable_revoke_session": True,
            "enable_ropc": False,
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
            "storage_account_name": "teststorage",
            "verified_domains": [],
        }

    def _run(self, ledger, chk, revoke_ok=True):
        revoke = Mock(return_value=revoke_ok)
        written = []
        with patch.object(function_app.src_botnet, "fetch",
                          return_value=[{"email": "a@x.com"}]), \
             patch.object(function_app.law, "write_records",
                          side_effect=lambda c, s, r: (written.extend(r), True)[1]), \
             patch.object(function_app.cp, "load", return_value=dict(chk)), \
             patch.object(function_app.cp, "save"), \
             patch.object(function_app.act_ledger, "build", return_value=ledger), \
             patch.object(function_app.entra, "lookup_user",
                          return_value=({"id": "u1", "accountEnabled": True}, 200)), \
             patch.object(function_app.entra, "revoke_sessions", revoke):
            audit = function_app._process_source(
                source_name="botnet", conf=self._conf(), credential=None,
                tenant_headers_map={"t1": {"Authorization": "Bearer x"}},
                function_start_time=time.time())
        return audit, written, revoke

    def test_same_window_reread_does_not_repeat_the_action(self):
        led = action_ledger.InMemoryActionLedger()
        chk = {"last_start_date": "2026-08-01"}
        audit1, written1, revoke1 = self._run(led, chk)
        self.assertEqual(revoke1.call_count, 1)
        self.assertIn("revoke_session", written1[0]["actions_taken"])
        self.assertEqual(audit1["actions"], 1)

        audit2, written2, revoke2 = self._run(led, chk)
        self.assertEqual(revoke2.call_count, 0, "the re-read must not act again")
        self.assertIn("revoke_session_skipped_duplicate", written2[0]["actions_taken"])
        self.assertEqual(audit2["actions"], 0)

    def test_a_new_window_acts_again(self):
        led = action_ledger.InMemoryActionLedger()
        self._run(led, {"last_start_date": "2026-08-01"})
        _, written, revoke = self._run(led, {"last_start_date": "2026-08-10"})
        self.assertEqual(revoke.call_count, 1)
        self.assertIn("revoke_session", written[0]["actions_taken"])

    def test_a_failed_action_is_not_recorded_and_retries(self):
        led = action_ledger.InMemoryActionLedger()
        chk = {"last_start_date": "2026-08-01"}
        _, written1, _ = self._run(led, chk, revoke_ok=False)
        self.assertIn("revoke_session_failed", written1[0]["actions_taken"])

        _, written2, revoke2 = self._run(led, chk, revoke_ok=True)
        self.assertEqual(revoke2.call_count, 1, "a failure must be retried")
        self.assertIn("revoke_session", written2[0]["actions_taken"])


if __name__ == "__main__":
    unittest.main()
