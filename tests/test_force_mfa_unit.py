#!/usr/bin/env python3
"""
Unit tests for force_mfa_reregistration using unittest.mock.
No network, no real credentials. Safe for CI.

Run: python3 -m unittest tests/test_force_mfa_unit.py
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

# Make the production module importable
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "production" / "FunctionApp"))

# msal is a transitive dependency — stub it out so import succeeds without install
if "msal" not in sys.modules:
    msal_stub = type(sys)("msal")
    msal_stub.ConfidentialClientApplication = object
    msal_stub.PublicClientApplication = object
    sys.modules["msal"] = msal_stub

from actions import entra_id  # noqa: E402

PASSWORD_METHOD = {
    "id": entra_id.PASSWORD_METHOD_ID,
    "@odata.type": "#microsoft.graph.passwordAuthenticationMethod",
}
AUTHENTICATOR_METHOD = {
    "id": "auth-1",
    "@odata.type": "#microsoft.graph.microsoftAuthenticatorAuthenticationMethod",
}
PHONE_METHOD = {
    "id": "phone-1",
    "@odata.type": "#microsoft.graph.phoneAuthenticationMethod",
}
UNKNOWN_METHOD = {
    "id": "unknown-1",
    "@odata.type": "#microsoft.graph.someNewUnknownAuthenticationMethod",
}


def _mock_response(status_code, json_body=None, text=""):
    m = Mock()
    m.status_code = status_code
    m.json.return_value = json_body or {}
    m.text = text
    return m


class TestForceMfaReregistration(unittest.TestCase):
    USER_ID = "12345678-aaaa-bbbb-cccc-dddddddddddd"
    HEADERS = {"Authorization": "Bearer test-token"}

    def test_happy_path_two_methods_deleted_password_skipped(self):
        """User has authenticator + phone + password → 2 DELETE, 1 skip."""
        list_resp = _mock_response(200, {"value": [AUTHENTICATOR_METHOD, PHONE_METHOD, PASSWORD_METHOD]})
        del_resp = _mock_response(204)
        # _graph_request is called once for list, then once per non-password method
        side_effect = [list_resp, del_resp, del_resp]

        with patch("actions.entra_id._graph_request", side_effect=side_effect) as mock_req:
            result = entra_id.force_mfa_reregistration(self.USER_ID, self.HEADERS)

        self.assertEqual(result["methods_deleted"], 2)
        self.assertEqual(result["methods_skipped"], 1)
        self.assertEqual(result["errors"], [])
        self.assertFalse(result["permission_denied"])
        # 1 list + 2 deletes
        self.assertEqual(mock_req.call_count, 3)

    def test_permission_denied_on_list(self):
        """GET /authentication/methods returns 403 → permission_denied, no deletes."""
        list_resp = _mock_response(403, text="Insufficient privileges")

        with patch("actions.entra_id._graph_request", return_value=list_resp) as mock_req:
            result = entra_id.force_mfa_reregistration(self.USER_ID, self.HEADERS)

        self.assertTrue(result["permission_denied"])
        self.assertEqual(result["methods_deleted"], 0)
        # Only the list call was made — no delete calls
        self.assertEqual(mock_req.call_count, 1)
        self.assertTrue(any("403" in e for e in result["errors"]))

    def test_permission_denied_on_delete(self):
        """First DELETE returns 401 → bail out, permission_denied True."""
        list_resp = _mock_response(200, {"value": [AUTHENTICATOR_METHOD, PHONE_METHOD]})
        del_resp = _mock_response(401)
        side_effect = [list_resp, del_resp]  # bails out on first 401 delete

        with patch("actions.entra_id._graph_request", side_effect=side_effect) as mock_req:
            result = entra_id.force_mfa_reregistration(self.USER_ID, self.HEADERS)

        self.assertTrue(result["permission_denied"])
        self.assertEqual(result["methods_deleted"], 0)
        # 1 list + 1 delete (bailed out)
        self.assertEqual(mock_req.call_count, 2)

    def test_unknown_odata_type_continues(self):
        """Unknown method type logs error but doesn't block other deletes."""
        list_resp = _mock_response(200, {"value": [UNKNOWN_METHOD, AUTHENTICATOR_METHOD]})
        del_resp = _mock_response(204)
        # Unknown is skipped without a delete call; only known method is deleted
        side_effect = [list_resp, del_resp]

        with patch("actions.entra_id._graph_request", side_effect=side_effect) as mock_req:
            result = entra_id.force_mfa_reregistration(self.USER_ID, self.HEADERS)

        self.assertEqual(result["methods_deleted"], 1)
        self.assertFalse(result["permission_denied"])
        self.assertTrue(any("unknown method type" in e for e in result["errors"]))
        self.assertEqual(mock_req.call_count, 2)

    def test_partial_failure_continues(self):
        """DELETE 500 on one method doesn't stop others."""
        list_resp = _mock_response(200, {"value": [AUTHENTICATOR_METHOD, PHONE_METHOD]})
        side_effect = [list_resp, _mock_response(500, text="internal"), _mock_response(204)]

        with patch("actions.entra_id._graph_request", side_effect=side_effect):
            result = entra_id.force_mfa_reregistration(self.USER_ID, self.HEADERS)

        self.assertEqual(result["methods_deleted"], 1)
        self.assertFalse(result["permission_denied"])
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("500", result["errors"][0])

    def test_only_password_method(self):
        """User has only password → 0 deleted, 1 skipped, no errors."""
        list_resp = _mock_response(200, {"value": [PASSWORD_METHOD]})

        with patch("actions.entra_id._graph_request", return_value=list_resp) as mock_req:
            result = entra_id.force_mfa_reregistration(self.USER_ID, self.HEADERS)

        self.assertEqual(result["methods_deleted"], 0)
        self.assertEqual(result["methods_skipped"], 1)
        self.assertEqual(result["errors"], [])
        # Only the list call — no delete calls
        self.assertEqual(mock_req.call_count, 1)

    def test_list_network_error(self):
        """Network exception on list → captured as error string, permission_denied False."""
        import requests
        with patch("actions.entra_id._graph_request", side_effect=requests.RequestException("connection reset")):
            result = entra_id.force_mfa_reregistration(self.USER_ID, self.HEADERS)

        self.assertFalse(result["permission_denied"])
        self.assertEqual(result["methods_deleted"], 0)
        self.assertTrue(any("request error" in e for e in result["errors"]))


if __name__ == "__main__":
    unittest.main()
