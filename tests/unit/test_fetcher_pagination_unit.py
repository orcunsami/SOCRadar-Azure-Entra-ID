#!/usr/bin/env python3
"""Pagination resume regression tests.

Repros the heavy-backlog bug (EXP-0122): when MAX_PAGES_PER_RUN < total_pages,
Run #1 paginates and saves last_page>0. Run #2 must continue from last_page+1,
NOT skip ahead by advancing last_start_date to today.

The bug was: total_pages init=1 → on resume page=101 > total_pages=1 → loop
never executes → finished_all = True erroneously → checkpoint advances date.

Fix: total_pages = page initial value, so the first iteration always runs
and the API response updates total_pages to the real value.
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

# Stub azure modules before fetcher imports — fetchers transitively import
# utils.checkpoint which imports azure.data.tables. We only need get_start_date.
sys.modules.setdefault("azure", MagicMock())
sys.modules.setdefault("azure.data", MagicMock())
sys.modules.setdefault("azure.data.tables", MagicMock())
sys.modules.setdefault("azure.core", MagicMock())
sys.modules.setdefault("azure.core.exceptions", MagicMock())

# Add FunctionApp to sys.path
PROD_DIR = Path(__file__).parent.parent.parent / "production" / "FunctionApp"
sys.path.insert(0, str(PROD_DIR))


def _mock_resp(total_records, page_records):
    """Build a successful SOCRadar API response."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "is_success": True,
        "data": {
            "total_data_count": total_records,
            "data": page_records,
        },
    }
    return resp


def _emp(email):
    """Minimal botnet record (isEmployee=true)."""
    return {"user": email, "isEmployee": True, "password": "***", "deviceIP": "1.2.3.4"}


class TestBotnetResume(unittest.TestCase):
    """Botnet fetcher: pagination resume should not advance date prematurely."""

    def setUp(self):
        os.environ["MAX_PAGES_PER_RUN"] = "100"
        # Reimport to pick up env var
        if "sources.botnet" in sys.modules:
            del sys.modules["sources.botnet"]

    def test_resume_from_partial_state_does_not_advance_date(self):
        """Run #2: checkpoint says last_page=100, total=1264 pages remaining.
        Fetcher must continue pagination, not declare 'finished'."""
        from sources import botnet  # noqa: E402

        conf = {
            "socradar_api_key": "test",
            "socradar_company_id": "132",
            "socradar_base_url": "https://test.socradar.com",
            "initial_lookback_minutes": 525600,
            "initial_start_date": "2025-05-11",
            "enable_log_plaintext_password": False,
        }
        # Checkpoint state from a previous run that hit MAX_PAGES_PER_RUN
        checkpoint = {"last_page": 100, "last_start_date": "2025-05-11"}

        page_records = [_emp(f"user{i}@test.com") for i in range(100)]

        with patch("sources.botnet.requests.get") as mock_get, \
             patch("sources.botnet.time.sleep"):
            # 126,400 total records → 1264 pages
            mock_get.return_value = _mock_resp(126400, page_records)
            result = botnet.fetch(conf, checkpoint)

        # Last item carries _checkpoint_update
        cp_update = result[-1].get("_checkpoint_update")
        self.assertIsNotNone(cp_update, "Last record must carry _checkpoint_update")
        # Must NOT advance date — backlog not drained
        self.assertEqual(
            cp_update["last_start_date"], "2025-05-11",
            "Bug repro: fetcher advanced date even though backlog is not drained",
        )
        # Must have advanced page past 100
        self.assertGreater(
            cp_update["last_page"], 100,
            "Fetcher did not progress past resume_page=100",
        )

    def test_fresh_start_paginates_correctly(self):
        """Run #1: no checkpoint, MAX_PAGES_PER_RUN=100, total=1264 pages.
        Fetcher must stop at page 100, save last_page=100, NOT advance date."""
        from sources import botnet  # noqa: E402

        conf = {
            "socradar_api_key": "test",
            "socradar_company_id": "132",
            "socradar_base_url": "https://test.socradar.com",
            "initial_lookback_minutes": 525600,
            "initial_start_date": "2025-05-11",
            "enable_log_plaintext_password": False,
        }
        checkpoint = {}  # fresh
        page_records = [_emp(f"user{i}@test.com") for i in range(100)]

        with patch("sources.botnet.requests.get") as mock_get, \
             patch("sources.botnet.time.sleep"):
            mock_get.return_value = _mock_resp(126400, page_records)
            result = botnet.fetch(conf, checkpoint)

        cp_update = result[-1].get("_checkpoint_update")
        self.assertEqual(cp_update["last_start_date"], "2025-05-11")
        self.assertEqual(cp_update["last_page"], 100)
        # 100 pages × 100 records/page = 10000 employees (all isEmployee=True in mock)
        # +1 for last record having _checkpoint_update extracted
        self.assertEqual(len(result), 10000)

    def test_drained_backlog_advances_date(self):
        """Genuine drain: total_pages=50, MAX_PAGES_PER_RUN=100, no resume.
        Fetcher must drain all 50 pages, advance date to today, last_page=0."""
        from sources import botnet  # noqa: E402

        conf = {
            "socradar_api_key": "test",
            "socradar_company_id": "132",
            "socradar_base_url": "https://test.socradar.com",
            "initial_lookback_minutes": 525600,
            "initial_start_date": "2025-05-11",
            "enable_log_plaintext_password": False,
        }
        checkpoint = {}
        page_records = [_emp(f"user{i}@test.com") for i in range(100)]

        with patch("sources.botnet.requests.get") as mock_get, \
             patch("sources.botnet.time.sleep"):
            mock_get.return_value = _mock_resp(5000, page_records)  # 50 pages
            result = botnet.fetch(conf, checkpoint)

        cp_update = result[-1].get("_checkpoint_update")
        # Date advances to today because we drained all 50 pages
        self.assertNotEqual(
            cp_update["last_start_date"], "2025-05-11",
            "Date should advance to today after draining all pages",
        )
        self.assertEqual(cp_update["last_page"], 0, "last_page resets to 0 after drain")


class TestPIIResume(unittest.TestCase):
    def setUp(self):
        if "sources.pii" in sys.modules:
            del sys.modules["sources.pii"]

    def test_resume_from_partial_state_does_not_advance_date(self):
        from sources import pii  # noqa: E402

        conf = {
            "socradar_api_key": "test",
            "socradar_company_id": "132",
            "socradar_base_url": "https://test.socradar.com",
            "initial_lookback_minutes": 525600,
            "initial_start_date": "2025-05-11",
            "enable_log_plaintext_password": False,
        }
        checkpoint = {"last_page": 50, "last_start_date": "2025-05-11"}
        page_records = [_emp(f"u{i}@t.com") for i in range(100)]

        with patch("sources.pii.requests.get") as mock_get, \
             patch("sources.pii.time.sleep"):
            mock_get.return_value = _mock_resp(20000, page_records)  # 200 pages
            result = pii.fetch(conf, checkpoint)

        cp_update = result[-1].get("_checkpoint_update")
        self.assertEqual(cp_update["last_start_date"], "2025-05-11")
        self.assertGreater(cp_update["last_page"], 50)


class TestVIPResume(unittest.TestCase):
    def setUp(self):
        if "sources.vip" in sys.modules:
            del sys.modules["sources.vip"]

    def test_resume_from_partial_state_does_not_advance_date(self):
        from sources import vip  # noqa: E402

        conf = {
            "socradar_api_key": "test",
            "socradar_company_id": "132",
            "socradar_base_url": "https://test.socradar.com",
            "initial_lookback_minutes": 525600,
            "initial_start_date": "2025-05-11",
            "enable_log_plaintext_password": False,
        }
        checkpoint = {"last_page": 25, "last_start_date": "2025-05-11"}
        page_records = [_emp(f"u{i}@t.com") for i in range(100)]

        with patch("sources.vip.requests.get") as mock_get, \
             patch("sources.vip.time.sleep"):
            # 20000 records = 200 pages. Starting from page 26, MAX=100 means
            # we hit page 125 and stop — backlog NOT drained.
            mock_get.return_value = _mock_resp(20000, page_records)
            result = vip.fetch(conf, checkpoint)

        cp_update = result[-1].get("_checkpoint_update")
        self.assertEqual(cp_update["last_start_date"], "2025-05-11")
        self.assertGreater(cp_update["last_page"], 25)


if __name__ == "__main__":
    unittest.main(verbosity=2)
