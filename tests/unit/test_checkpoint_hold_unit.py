#!/usr/bin/env python3
"""
Unit tests for checkpoint holding.

The defect these pin down: the checkpoint used to advance no matter what,
so a run that failed to write to Log Analytics, ran out of time budget, or
could not look anybody up still retired its window — the findings in it were
silently lost. A window is only retired when the run really finished with it;
a permanently broken window is abandoned loudly after MAX_CONSECUTIVE_HOLDS.

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

WINDOW = {"checkpoint_date": "2026-08-13", "page": 3}


def _emp(email=None, with_checkpoint=False):
    e = {"email": email} if email else {"name": "someone"}
    if with_checkpoint:
        e["_checkpoint_update"] = dict(WINDOW)
    return e


class HoldTests(unittest.TestCase):

    def _run(self, employees, chk=None, law_ok=True, lookup=None,
             conf_extra=None, tenants=None, start_time=None):
        conf = {
            "enable_user_lookup": False,
            "storage_account_name": "teststorage",
            "verified_domains": [],
        }
        conf.update(conf_extra or {})
        saved, events = [], []
        patches = [
            patch.object(function_app.src_botnet, "fetch", return_value=employees),
            patch.object(function_app.law, "write_records", return_value=law_ok),
            patch.object(function_app.law, "write_lifecycle_event",
                         side_effect=lambda c, **kw: events.append(kw)),
            patch.object(function_app.cp, "load", return_value=dict(chk or {})),
            patch.object(function_app.cp, "save",
                         side_effect=lambda acc, cred, src, data: saved.append(data)),
        ]
        if lookup is not None:
            patches.append(patch.object(function_app.entra, "lookup_user",
                                        side_effect=lookup))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        audit = function_app._process_source(
            source_name="botnet", conf=conf, credential=None,
            tenant_headers_map=dict(tenants or {}),
            function_start_time=start_time or time.time())
        return audit, saved, events

    def test_a_clean_run_retires_the_window(self):
        audit, saved, _ = self._run([_emp("a@x.com", with_checkpoint=True)])
        self.assertFalse(audit["held"])
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["checkpoint_date"], WINDOW["checkpoint_date"])
        self.assertEqual(saved[0]["consecutive_holds"], 0)

    def test_a_failed_law_write_holds_the_window(self):
        audit, saved, _ = self._run([_emp("a@x.com", with_checkpoint=True)],
                                    law_ok=False)
        self.assertTrue(audit["held"])
        self.assertEqual(len(saved), 1)
        self.assertNotIn("checkpoint_date", saved[0],
                         "the window must NOT advance on a failed write")
        self.assertEqual(saved[0]["consecutive_holds"], 1)

    def test_a_truncated_run_holds_the_window(self):
        audit, saved, _ = self._run(
            [_emp("a@x.com", with_checkpoint=True)],
            start_time=time.time() - function_app.TIME_BUDGET_SECONDS - 5)
        self.assertTrue(audit["truncated"])
        self.assertTrue(audit["held"])
        self.assertNotIn("checkpoint_date", saved[0])

    def test_a_permission_denied_lookup_holds_the_window(self):
        audit, saved, _ = self._run(
            [_emp("a@x.com", with_checkpoint=True)],
            conf_extra={"enable_user_lookup": True},
            tenants={"t1": {"Authorization": "Bearer x"}},
            lookup=lambda email, headers: (None, 403))
        self.assertEqual(audit["lookup_failed"], 1)
        self.assertTrue(audit["held"])
        self.assertNotIn("checkpoint_date", saved[0])

    def test_a_raising_record_holds_the_window(self):
        def boom(email, headers):
            raise RuntimeError("graph exploded")
        audit, saved, _ = self._run(
            [_emp("a@x.com", with_checkpoint=True)],
            conf_extra={"enable_user_lookup": True},
            tenants={"t1": {"Authorization": "Bearer x"}},
            lookup=boom)
        self.assertEqual(audit["errors"], 1)
        self.assertTrue(audit["held"])
        self.assertNotIn("checkpoint_date", saved[0])

    def test_holds_accumulate_across_runs(self):
        audit, saved, _ = self._run([_emp("a@x.com", with_checkpoint=True)],
                                    chk={"consecutive_holds": 2}, law_ok=False)
        self.assertEqual(saved[0]["consecutive_holds"], 3)

    def test_the_window_is_abandoned_loudly_after_max_holds(self):
        audit, saved, events = self._run(
            [_emp("a@x.com", with_checkpoint=True)],
            chk={"consecutive_holds": function_app.MAX_CONSECUTIVE_HOLDS - 1,
                 "checkpoint_date": "2026-08-01"},
            law_ok=False)
        self.assertTrue(audit["held"])
        # The window ADVANCES (abandoned), the hold counter resets, and the
        # abandonment is recorded where an operator can see it.
        self.assertEqual(saved[0]["checkpoint_date"], WINDOW["checkpoint_date"])
        self.assertEqual(saved[0]["consecutive_holds"], 0)
        self.assertEqual(events[0]["event_type"], "import_window_abandoned")

    def test_a_recovered_run_resets_the_hold_counter(self):
        audit, saved, _ = self._run([_emp("a@x.com", with_checkpoint=True)],
                                    chk={"consecutive_holds": 3}, law_ok=True)
        self.assertFalse(audit["held"])
        self.assertEqual(saved[0]["consecutive_holds"], 0)
        self.assertEqual(saved[0]["checkpoint_date"], WINDOW["checkpoint_date"])


class WriteRecordsReturnTests(unittest.TestCase):
    """write_records must aggregate batch outcomes — the hold above trusts it.
    (The HoldTests mock write_records, so its own truthfulness needs pinning.)"""

    CONF = {"dcr_immutable_id": "dcr-x", "dcr_endpoint": "https://x",
            "enable_log_plaintext_password": False}

    def _write(self, upload_results, n_records=1):
        from actions import law_writer
        calls = iter(upload_results)
        with patch.object(law_writer, "_upload",
                          side_effect=lambda *a: next(calls)):
            return law_writer.write_records(
                self.CONF, "botnet", [{"email": f"u{i}@x.com"} for i in range(n_records)])

    def test_all_batches_landing_returns_true(self):
        self.assertIs(self._write([True]), True)

    def test_one_failed_batch_returns_false(self):
        from actions import law_writer
        n = law_writer.BATCH_SIZE + 1  # forces two batches
        self.assertIs(self._write([True, False], n_records=n), False)

    def test_missing_dcr_config_returns_false(self):
        from actions import law_writer
        self.assertIs(law_writer.write_records({}, "botnet", [{"email": "a@x.com"}]), False)

    def test_unknown_source_returns_false(self):
        from actions import law_writer
        self.assertIs(law_writer.write_records(self.CONF, "nope", [{"email": "a@x.com"}]), False)


if __name__ == "__main__":
    unittest.main()
