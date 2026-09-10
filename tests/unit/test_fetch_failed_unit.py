#!/usr/bin/env python3
"""A SOCRadar fetch that does not finish must not read as "0 records, 0 errors".

Measured on 8 Sep 2026 (EXP-AZURE-0214): the botnet source got HTTP 401 and the pii
source HTTP 502 on page 1. Both logged the error and returned nothing, and the run
wrote an audit row with total=0 errors=0 for each. A customer with a wrong API key saw
a green deployment, a green run and an audit table full of zeros.

Two things have to hold now:
  - the source marks the returned list when it stopped on an HTTP error, a transport
    error or is_success=false (any status, any source)
  - the caller counts that as an error, so error_count>0 lands in the audit row and the
    checkpoint holds (errors>0 is already a hold condition)

Needs the azure packages (function_app imports azure.functions), same as CI.
"""

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "production" / "FunctionApp"))

import function_app  # noqa: E402
from sources import botnet, pii, vip  # noqa: E402

CONF = {
    "socradar_api_key": "k", "socradar_company_id": "1",
    "socradar_base_url": "https://example.invalid",
    "initial_lookback_days": 1, "initial_start_date": "",
    "enable_log_plaintext_password": False,
}


def _resp(status, body=None, text="err"):
    r = MagicMock()
    r.status_code = status
    r.text = text
    r.json.return_value = body if body is not None else {}
    return r


class SourceMarksFailedFetch(unittest.TestCase):

    def _fetch(self, module, resp=None, exc=None):
        with patch.object(module.requests, "get",
                          side_effect=exc if exc else None,
                          return_value=resp):
            return module.fetch(CONF, {})

    def test_http_401_is_marked_in_every_source(self):
        for module in (botnet, pii, vip):
            records = self._fetch(module, resp=_resp(401))
            self.assertTrue(records, "%s: an empty list hides the failure" % module.__name__)
            self.assertTrue(records[-1].get("_fetch_failed"), module.__name__)

    def test_http_502_and_is_success_false_are_marked(self):
        self.assertTrue(self._fetch(botnet, resp=_resp(502))[-1].get("_fetch_failed"))
        self.assertTrue(self._fetch(botnet, resp=_resp(200, {"is_success": False}))[-1].get("_fetch_failed"))

    def test_transport_error_is_marked(self):
        records = self._fetch(botnet, exc=botnet.requests.RequestException("boom"))
        self.assertTrue(records[-1].get("_fetch_failed"))

    def test_vip_404_is_marked(self):
        self.assertTrue(self._fetch(vip, resp=_resp(404))[-1].get("_fetch_failed"))

    def test_clean_empty_page_is_not_marked(self):
        body = {"is_success": True, "data": {"data": [], "total_data_count": 0}}
        records = self._fetch(botnet, resp=_resp(200, body))
        self.assertFalse(any(r.get("_fetch_failed") for r in records))

    def test_failed_fetch_does_not_advance_the_checkpoint(self):
        records = self._fetch(botnet, resp=_resp(401))
        cp_update = records[-1]["_checkpoint_update"]
        self.assertNotEqual(cp_update["last_start_date"], time.strftime("%Y-%m-%d"),
                            "a window nobody read must not be retired")


class CallerCountsFailedFetch(unittest.TestCase):

    def _run(self, employees):
        saved, self.written = [], []
        patches = [
            patch.object(function_app.src_botnet, "fetch", return_value=employees),
            patch.object(function_app.law, "write_records",
                         side_effect=lambda c, s, r: self.written.extend(r) or True),
            patch.object(function_app.law, "write_lifecycle_event"),
            patch.object(function_app.cp, "load", return_value={}),
            patch.object(function_app.cp, "save", side_effect=lambda *a: saved.append(a[-1])),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        conf = dict(CONF, verified_domains=[], entra_max_actions_per_run=50,
                    storage_account_name="st", enable_user_lookup=False)
        return function_app._process_source(
            source_name="botnet", conf=conf, credential=None,
            tenant_headers_map={}, function_start_time=time.time()), saved

    def test_marked_fetch_counts_one_error_and_holds_the_checkpoint(self):
        marker = {"_checkpoint_update": {"last_start_date": "2026-09-01", "last_page": 0},
                  "_empty_marker": True, "_fetch_failed": True}
        audit, saved = self._run([marker])
        self.assertEqual(audit["total"], 0)
        self.assertEqual(audit["errors"], 1, "0 records / 0 errors was the lie in EXP-0214")
        self.assertTrue(saved and saved[-1].get("consecutive_holds") == 1,
                        "checkpoint must be held, not advanced: %r" % saved)

    def test_unmarked_empty_run_stays_clean(self):
        marker = {"_checkpoint_update": {"last_start_date": "2026-09-01", "last_page": 0},
                  "_empty_marker": True}
        audit, saved = self._run([marker])
        self.assertEqual(audit["errors"], 0)
        self.assertEqual(saved[-1].get("consecutive_holds"), 0)

    def test_marker_key_never_reaches_a_record(self):
        emp = {"email": "a@corp.com", "_fetch_failed": True,
               "_checkpoint_update": {"last_start_date": "2026-09-01", "last_page": 0}}
        audit, _ = self._run([emp])
        self.assertEqual(audit["errors"], 1)
        self.assertTrue(self.written and "_fetch_failed" not in self.written[0])


if __name__ == "__main__":
    unittest.main()
