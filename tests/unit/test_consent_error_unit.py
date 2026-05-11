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


class TestGetGraphTokenWithFIC(unittest.TestCase):
    TENANT = "01a14909-test"
    CLIENT = "b0afca82-test"

    def setUp(self):
        entra_id._graph_credential = None

    def _mock_fic_credential(self, token_value=None, error=None):
        mock_cred = MagicMock()
        if error:
            mock_cred.get_token.side_effect = error
        else:
            tok = MagicMock()
            tok.token = token_value
            mock_cred.get_token.return_value = tok
        return mock_cred

    def test_consent_code_raises_consent_revoked(self):
        mock_cred = self._mock_fic_credential(
            error=entra_id.ClientAuthenticationError("AADSTS700016: App not found")
        )
        with patch("actions.entra_id._build_graph_credential", return_value=mock_cred):
            with self.assertRaises(entra_id.ConsentRevokedError) as ctx:
                entra_id.get_graph_token(self.TENANT, self.CLIENT)
        self.assertEqual(ctx.exception.aadsts_code, "AADSTS700016")

    def test_non_consent_error_raises_runtime_error(self):
        mock_cred = self._mock_fic_credential(
            error=entra_id.ClientAuthenticationError("Service unavailable")
        )
        with patch("actions.entra_id._build_graph_credential", return_value=mock_cred):
            with self.assertRaises(RuntimeError) as ctx:
                entra_id.get_graph_token(self.TENANT, self.CLIENT)
        self.assertNotIsInstance(ctx.exception, entra_id.ConsentRevokedError)

    def test_successful_token_acquisition(self):
        mock_cred = self._mock_fic_credential(token_value="eyJ0eXAi...fake")
        with patch("actions.entra_id._build_graph_credential", return_value=mock_cred):
            token = entra_id.get_graph_token(self.TENANT, self.CLIENT)
        self.assertEqual(token, "eyJ0eXAi...fake")


if __name__ == "__main__":
    unittest.main()
