#!/usr/bin/env python3
"""
Unit tests for _graph_request retry wrapper.
Validates 429 + Retry-After handling without network.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "production" / "FunctionApp"))

from actions import entra_id  # noqa: E402


def _mk_resp(status, headers=None, json_body=None):
    m = Mock()
    m.status_code = status
    m.headers = headers or {}
    m.json.return_value = json_body or {}
    m.text = ""
    return m


class TestGraphRequestRetry(unittest.TestCase):
    HEADERS = {"Authorization": "Bearer x"}
    URL = "https://graph.microsoft.com/v1.0/users/foo@bar.com"

    def test_happy_path_no_retry(self):
        """200 on first try — no retry, no sleep."""
        resp = _mk_resp(200, json_body={"id": "u1"})
        with patch("actions.entra_id.requests.request", return_value=resp) as mock_req, \
             patch("actions.entra_id.time.sleep") as mock_sleep:
            out = entra_id._graph_request("GET", self.URL, self.HEADERS)
        self.assertEqual(out.status_code, 200)
        self.assertEqual(mock_req.call_count, 1)
        mock_sleep.assert_not_called()

    def test_429_retry_with_retry_after(self):
        """429 with Retry-After: 5 → sleep 5s → retry → 200."""
        responses = [
            _mk_resp(429, headers={"Retry-After": "5"}),
            _mk_resp(200, json_body={"id": "u1"}),
        ]
        with patch("actions.entra_id.requests.request", side_effect=responses) as mock_req, \
             patch("actions.entra_id.time.sleep") as mock_sleep:
            out = entra_id._graph_request("GET", self.URL, self.HEADERS)
        self.assertEqual(out.status_code, 200)
        self.assertEqual(mock_req.call_count, 2)
        mock_sleep.assert_called_once_with(5)

    def test_429_max_retries_exhausted(self):
        """429 repeats past max_retries → return 429 to caller."""
        responses = [_mk_resp(429, headers={"Retry-After": "1"}) for _ in range(5)]
        with patch("actions.entra_id.requests.request", side_effect=responses) as mock_req, \
             patch("actions.entra_id.time.sleep"):
            out = entra_id._graph_request("GET", self.URL, self.HEADERS, max_retries=3)
        self.assertEqual(out.status_code, 429)
        self.assertEqual(mock_req.call_count, 4)  # 1 initial + 3 retries

    def test_retry_after_capped_at_30(self):
        """Retry-After: 120 is capped at 30s to avoid hanging function host."""
        responses = [
            _mk_resp(429, headers={"Retry-After": "120"}),
            _mk_resp(200),
        ]
        with patch("actions.entra_id.requests.request", side_effect=responses), \
             patch("actions.entra_id.time.sleep") as mock_sleep:
            entra_id._graph_request("GET", self.URL, self.HEADERS)
        mock_sleep.assert_called_once_with(30)

    def test_retry_after_invalid_defaults_to_2(self):
        """Malformed Retry-After → default 2s."""
        responses = [
            _mk_resp(429, headers={"Retry-After": "not-a-number"}),
            _mk_resp(200),
        ]
        with patch("actions.entra_id.requests.request", side_effect=responses), \
             patch("actions.entra_id.time.sleep") as mock_sleep:
            entra_id._graph_request("GET", self.URL, self.HEADERS)
        mock_sleep.assert_called_once_with(2)

    def test_retry_after_missing_defaults_to_2(self):
        """No Retry-After header → default 2s."""
        responses = [_mk_resp(429, headers={}), _mk_resp(200)]
        with patch("actions.entra_id.requests.request", side_effect=responses), \
             patch("actions.entra_id.time.sleep") as mock_sleep:
            entra_id._graph_request("GET", self.URL, self.HEADERS)
        mock_sleep.assert_called_once_with(2)

    def test_post_with_json_body(self):
        """POST with json argument passes through to requests.request."""
        resp = _mk_resp(204)
        with patch("actions.entra_id.requests.request", return_value=resp) as mock_req:
            entra_id._graph_request("POST", self.URL, self.HEADERS, json={"foo": "bar"})
        kwargs = mock_req.call_args.kwargs
        self.assertEqual(kwargs.get("json"), {"foo": "bar"})

    def test_non_retry_status_returns_immediately(self):
        """403 / 500 / other → no retry, return immediately."""
        resp = _mk_resp(403)
        with patch("actions.entra_id.requests.request", return_value=resp) as mock_req, \
             patch("actions.entra_id.time.sleep") as mock_sleep:
            out = entra_id._graph_request("GET", self.URL, self.HEADERS)
        self.assertEqual(out.status_code, 403)
        self.assertEqual(mock_req.call_count, 1)
        mock_sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
