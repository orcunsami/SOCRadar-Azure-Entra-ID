#!/usr/bin/env python3
"""
Unit tests for ConsentRevokedError classification in get_graph_token.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "production" / "FunctionApp"))

if "msal" not in sys.modules:
    msal_stub = type(sys)("msal")
    msal_stub.ConfidentialClientApplication = MagicMock
    msal_stub.PublicClientApplication = MagicMock
    sys.modules["msal"] = msal_stub

from actions import entra_id  # noqa: E402


class TestClassifyTokenError(unittest.TestCase):
    def test_consent_code_aadsts700016_matched(self):
        self.assertEqual(
            entra_id._classify_token_error("AADSTS700016: Application ABC not found in directory"),
            "AADSTS700016"
        )

    def test_consent_code_aadsts65001_matched(self):
        self.assertEqual(
            entra_id._classify_token_error("AADSTS65001: user or admin has not consented"),
            "AADSTS65001"
        )

    def test_non_consent_error_returns_none(self):
        # AADSTS50126 is invalid-credentials, not consent
        self.assertIsNone(
            entra_id._classify_token_error("AADSTS50126: invalid username or password")
        )

    def test_invalid_client_secret_is_not_consent(self):
        # AADSTS7000215 = "Invalid client secret provided". It's a credential
        # rotation issue, not consent. Must NOT be classified as consent_revoked
        # to avoid misleading operators.
        self.assertIsNone(
            entra_id._classify_token_error(
                "AADSTS7000215: Invalid client secret provided. Ensure the secret "
                "being sent in the request is the client secret value, not the client "
                "secret ID, for a secret added to app 'xxx'."
            )
        )

    def test_empty_description(self):
        self.assertIsNone(entra_id._classify_token_error(""))
        self.assertIsNone(entra_id._classify_token_error(None))


class TestGetGraphTokenRaisesConsentRevoked(unittest.TestCase):
    TENANT = "01a14909-9a97-4ded-9af3-7ea42ea99b2f"
    CLIENT_ID = "b0afca82-a991-4fea-ad87-94ec348b2e68"
    SECRET = "dummy-secret"

    def _mock_msal_with_result(self, result: dict):
        mock_app = MagicMock()
        mock_app.acquire_token_for_client.return_value = result
        return mock_app

    def test_consent_code_raises_consent_revoked(self):
        mock_app = self._mock_msal_with_result({
            "error": "invalid_client",
            "error_description": "AADSTS700016: Application not found in directory /01a14909"
        })
        with patch("actions.entra_id.ConfidentialClientApplication", return_value=mock_app):
            with self.assertRaises(entra_id.ConsentRevokedError) as ctx:
                entra_id.get_graph_token(self.TENANT, self.CLIENT_ID, self.SECRET)
        self.assertEqual(ctx.exception.tenant_id, self.TENANT)
        self.assertEqual(ctx.exception.aadsts_code, "AADSTS700016")

    def test_non_consent_error_raises_runtime_error(self):
        mock_app = self._mock_msal_with_result({
            "error": "temporarily_unavailable",
            "error_description": "Service unavailable, please retry"
        })
        with patch("actions.entra_id.ConfidentialClientApplication", return_value=mock_app):
            with self.assertRaises(RuntimeError) as ctx:
                entra_id.get_graph_token(self.TENANT, self.CLIENT_ID, self.SECRET)
        # Must be the generic RuntimeError, NOT ConsentRevokedError
        self.assertNotIsInstance(ctx.exception, entra_id.ConsentRevokedError)

    def test_successful_token_acquisition(self):
        mock_app = self._mock_msal_with_result({
            "access_token": "eyJ0eXAi...fake",
            "token_type": "Bearer",
            "expires_in": 3599,
        })
        with patch("actions.entra_id.ConfidentialClientApplication", return_value=mock_app):
            token = entra_id.get_graph_token(self.TENANT, self.CLIENT_ID, self.SECRET)
        self.assertEqual(token, "eyJ0eXAi...fake")


if __name__ == "__main__":
    unittest.main()
