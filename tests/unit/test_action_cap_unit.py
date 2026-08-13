#!/usr/bin/env python3
"""
Unit tests for the per-run action ceiling.

The defect these pin down: without a ceiling, a feed that suddenly returns
thousands of records turns into thousands of account mutations in one run.
With it, matches past the ceiling are recorded without actions, the run says
`capped`, and the held checkpoint gives the remainder their turn next run —
where the ledger keeps the already-acted from being repeated.

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


class ActionCapTests(unittest.TestCase):

    def _conf(self, cap):
        return {
            "enable_user_lookup": True,
            "enable_revoke_session": True,
            "entra_max_actions_per_run": cap,
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

    def _run(self, cap, n_emps, ledger=None, chk=None):
        employees = [{"email": f"u{i}@x.com"} for i in range(n_emps)]
        employees[-1]["_checkpoint_update"] = {"last_start_date": "2026-08-13"}
        revoke = Mock(return_value=True)
        written, saved = [], []
        with patch.object(function_app.src_botnet, "fetch", return_value=employees), \
             patch.object(function_app.law, "write_records",
                          side_effect=lambda c, s, r: (written.extend(r), True)[1]), \
             patch.object(function_app.law, "write_lifecycle_event"), \
             patch.object(function_app.cp, "load", return_value=dict(chk or {})), \
             patch.object(function_app.cp, "save",
                          side_effect=lambda a, c, s, d: saved.append(d)), \
             patch.object(function_app.act_ledger, "build",
                          return_value=ledger or action_ledger.InMemoryActionLedger()), \
             patch.object(function_app.entra, "lookup_user",
                          return_value=({"id": "u1", "accountEnabled": True}, 200)), \
             patch.object(function_app.entra, "revoke_sessions", revoke):
            audit = function_app._process_source(
                source_name="botnet", conf=self._conf(cap), credential=None,
                tenant_headers_map={"t1": {"Authorization": "Bearer x"}},
                function_start_time=time.time())
        return audit, written, revoke, saved

    def test_the_ceiling_stops_actions_but_not_records(self):
        audit, written, revoke, _ = self._run(cap=2, n_emps=5)
        self.assertEqual(revoke.call_count, 2)
        self.assertEqual(audit["actions"], 2)
        self.assertTrue(audit["capped"])
        self.assertEqual(len(written), 5, "capped matches are still recorded")
        capped_rows = [r for r in written
                       if r["actions_taken"] == ["skipped_capped"]]
        self.assertEqual(len(capped_rows), 3)
        for r in capped_rows:
            self.assertEqual(r["entra_status"], "found")

    def test_a_capped_run_holds_the_window(self):
        audit, _, _, saved = self._run(cap=2, n_emps=5)
        self.assertTrue(audit["held"])
        self.assertNotIn("last_start_date", saved[0])
        self.assertEqual(saved[0]["consecutive_holds"], 1)

    def test_an_uncapped_run_neither_caps_nor_holds(self):
        audit, _, revoke, saved = self._run(cap=50, n_emps=3)
        self.assertEqual(revoke.call_count, 3)
        self.assertFalse(audit["capped"])
        self.assertFalse(audit["held"])
        self.assertEqual(saved[0]["last_start_date"], "2026-08-13")

    def test_a_zero_ceiling_closes_the_gate_without_holding(self):
        # 0 is what a broken setting parses to (fail-closed). It must stop
        # every action, but holding on it would never converge — the window
        # advances and the deliberate/broken zero is visible in `capped`.
        audit, written, revoke, saved = self._run(cap=0, n_emps=2)
        self.assertEqual(revoke.call_count, 0)
        self.assertTrue(audit["capped"])
        self.assertFalse(audit["held"])
        self.assertEqual(saved[0]["last_start_date"], "2026-08-13")

    def test_the_reread_gives_the_remainder_their_turn(self):
        # Run 1: cap 2 of 3 → two acted, one capped, window held.
        led = action_ledger.InMemoryActionLedger()
        chk = {"last_start_date": "2026-08-01"}
        with patch.object(function_app.cp, "load", return_value=dict(chk)):
            pass  # window id comes from cp.load inside _run via chk param
        audit1, _, revoke1, _ = self._run(cap=2, n_emps=3, ledger=led, chk=chk)
        self.assertEqual(revoke1.call_count, 2)
        # Run 2, same window: the two already-acted are skipped by the
        # ledger, the third gets its action; nothing is repeated.
        audit2, written2, revoke2, _ = self._run(cap=2, n_emps=3, ledger=led, chk=chk)
        self.assertEqual(revoke2.call_count, 1)
        statuses = [r["actions_taken"] for r in written2]
        self.assertEqual(statuses.count(["revoke_session_skipped_duplicate"]), 2)
        self.assertIn(["revoke_session"], statuses)
        self.assertFalse(audit2["capped"], "the re-read finished under the ceiling")


if __name__ == "__main__":
    unittest.main()
