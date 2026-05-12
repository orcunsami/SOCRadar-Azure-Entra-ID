#!/usr/bin/env python3
"""Multi-tenant lookup regression tests for `_process_source`.

The integration supports N customer tenants per deployment. For each leaked
credential, lookup_user is tried against each tenant in order; first match
wins, all subsequent actions run against that tenant's headers. Tenants that
return 3 consecutive 403s are dropped from the lookup map for the rest of the
run (admin consent missing — no point retrying).

These tests exercise the orchestration logic in function_app._process_source
with heavily mocked SDK + source/action modules. The intent is to lock in
behaviour, not to test Graph or the source fetchers themselves.
"""

import os
import sys
import time
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

# Stub azure SDK modules before function_app imports — function_app imports
# azure.functions + azure.identity, neither needed for orchestration tests.
sys.modules.setdefault("azure", MagicMock())
sys.modules.setdefault("azure.functions", MagicMock())
sys.modules.setdefault("azure.identity", MagicMock())
sys.modules.setdefault("azure.data", MagicMock())
sys.modules.setdefault("azure.data.tables", MagicMock())
sys.modules.setdefault("azure.core", MagicMock())
sys.modules.setdefault("azure.core.exceptions", MagicMock())
sys.modules.setdefault("azure.monitor", MagicMock())
sys.modules.setdefault("azure.monitor.ingestion", MagicMock())

# Add FunctionApp to sys.path
PROD_DIR = Path(__file__).parent.parent.parent / "production" / "FunctionApp"
sys.path.insert(0, str(PROD_DIR))


def _base_conf(tenant_ids=None, tenant_id=""):
    """Minimal conf dict good enough for _process_source."""
    return {
        "tenant_ids": tenant_ids or [],
        "tenant_id": tenant_id,
        "client_id": "test-client",
        "storage_account_name": "stor",
        "enable_user_lookup": True,
        "enable_ropc": False,
        "enable_revoke_session": True,
        "enable_add_to_group": False,
        "enable_remove_from_group": False,
        "enable_password_change": False,
        "enable_disable_account": False,
        "enable_enable_account": False,
        "enable_confirm_risky": False,
        "enable_force_mfa_reregistration": False,
        "enable_create_incident": False,
        "enable_resolve_alarm": False,
        "security_group_id": "",
        "enable_log_plaintext_password": False,
        "dcr_immutable_id": "imm",
        "dcr_endpoint": "https://dce.example",
    }


def _emp(email, is_employee=True):
    return {"email": email, "user": email, "isEmployee": is_employee,
            "is_employee": is_employee, "source": "botnet"}


def _hdr(tenant):
    return {"Authorization": f"Bearer fake-token-{tenant}", "Content-Type": "application/json"}


class TestResolveTenants(unittest.TestCase):
    """Pure-config layer test: tenant_ids vs legacy tenant_id resolution."""

    def setUp(self):
        if "utils.config" in sys.modules:
            del sys.modules["utils.config"]
        from utils import config
        self.cfg = config

    def test_tenant_ids_precedence(self):
        conf = {"tenant_ids": ["a", "b"], "tenant_id": "legacy"}
        self.assertEqual(self.cfg.resolve_tenants(conf), ["a", "b"])

    def test_legacy_tenant_id_fallback(self):
        conf = {"tenant_ids": [], "tenant_id": "legacy"}
        self.assertEqual(self.cfg.resolve_tenants(conf), ["legacy"])

    def test_neither_returns_empty(self):
        conf = {"tenant_ids": [], "tenant_id": ""}
        self.assertEqual(self.cfg.resolve_tenants(conf), [])


class TestProcessSourceMultiTenant(unittest.TestCase):
    """Multi-tenant lookup loop tests at the _process_source level."""

    def setUp(self):
        if "function_app" in sys.modules:
            del sys.modules["function_app"]

    def _run(self, employees, tenant_headers_map, lookup_table):
        """Invoke _process_source with mocks.

        lookup_table: dict {(email, tenant_id): (user_info_or_None, http_status_or_None)}
        """
        from function_app import _process_source

        def fake_lookup(email, headers):
            # find which tenant this header belongs to
            for tid, hdr in tenant_headers_map.items():
                if hdr is headers:
                    return lookup_table.get((email, tid), (None, 404))
            return (None, 404)

        # Source fetcher returns the employees list with last record carrying
        # an _empty_marker-free checkpoint update (avoid touching storage).
        if employees:
            employees[-1]["_checkpoint_update"] = {"last_start_date": "2025-05-11", "last_page": 0}

        with patch("function_app.src_botnet") as mock_botnet, \
             patch("function_app.entra.lookup_user", side_effect=fake_lookup) as mock_lookup, \
             patch("function_app.entra.revoke_sessions", return_value=True) as mock_revoke, \
             patch("function_app.cp.load", return_value={}), \
             patch("function_app.cp.save"), \
             patch("function_app.law.write_records"), \
             patch("function_app.law.write_audit"), \
             patch("function_app.law.write_lifecycle_event"), \
             patch("function_app.audit_summary"):
            mock_botnet.fetch.return_value = employees
            result = _process_source(
                source_name="botnet",
                conf=_base_conf(),
                credential=MagicMock(),
                tenant_headers_map=tenant_headers_map,
                function_start_time=time.time(),  # fresh start, time budget not tripped
            )
            return result, mock_lookup, mock_revoke

    def test_two_tenant_first_match(self):
        """User in Tenant A, not in Tenant B → action runs against A."""
        emps = [_emp("alice@a.com")]
        headers_map = {"tenant-a": _hdr("a"), "tenant-b": _hdr("b")}
        lookups = {
            ("alice@a.com", "tenant-a"): ({"id": "uid-alice", "accountEnabled": True}, 200),
            ("alice@a.com", "tenant-b"): (None, 404),
        }
        result, mock_lookup, mock_revoke = self._run(emps, headers_map, lookups)

        self.assertEqual(result["found"], 1)
        self.assertEqual(result["not_found"], 0)
        self.assertEqual(emps[0]["entra_status"], "found")
        self.assertEqual(emps[0]["entra_tenant_id"], "tenant-a")
        # Lookup called once (first match wins, no need for B)
        self.assertEqual(mock_lookup.call_count, 1)
        # Action ran against tenant-a headers
        mock_revoke.assert_called_once_with("uid-alice", headers_map["tenant-a"])

    def test_two_tenant_second_match(self):
        """User not in Tenant A, found in Tenant B → action runs against B."""
        emps = [_emp("bob@b.com")]
        headers_map = {"tenant-a": _hdr("a"), "tenant-b": _hdr("b")}
        lookups = {
            ("bob@b.com", "tenant-a"): (None, 404),
            ("bob@b.com", "tenant-b"): ({"id": "uid-bob", "accountEnabled": True}, 200),
        }
        result, mock_lookup, mock_revoke = self._run(emps, headers_map, lookups)

        self.assertEqual(result["found"], 1)
        self.assertEqual(emps[0]["entra_status"], "found")
        self.assertEqual(emps[0]["entra_tenant_id"], "tenant-b")
        self.assertEqual(mock_lookup.call_count, 2)
        mock_revoke.assert_called_once_with("uid-bob", headers_map["tenant-b"])

    def test_user_not_found_anywhere(self):
        """User in neither tenant → not_found, entra_tenant_id empty."""
        emps = [_emp("ghost@nowhere.com")]
        headers_map = {"tenant-a": _hdr("a"), "tenant-b": _hdr("b")}
        lookups = {
            ("ghost@nowhere.com", "tenant-a"): (None, 404),
            ("ghost@nowhere.com", "tenant-b"): (None, 404),
        }
        result, mock_lookup, mock_revoke = self._run(emps, headers_map, lookups)

        self.assertEqual(result["found"], 0)
        self.assertEqual(result["not_found"], 1)
        self.assertEqual(emps[0]["entra_status"], "not_found")
        self.assertEqual(emps[0]["entra_tenant_id"], "")
        self.assertEqual(mock_lookup.call_count, 2)
        mock_revoke.assert_not_called()

    def test_single_tenant_backward_compat(self):
        """One-tenant map (legacy mode) — behaves identically to single-tenant."""
        emps = [_emp("legacy@old.com")]
        headers_map = {"tenant-legacy": _hdr("legacy")}
        lookups = {
            ("legacy@old.com", "tenant-legacy"): ({"id": "uid-legacy", "accountEnabled": True}, 200),
        }
        result, mock_lookup, mock_revoke = self._run(emps, headers_map, lookups)

        self.assertEqual(result["found"], 1)
        self.assertEqual(emps[0]["entra_tenant_id"], "tenant-legacy")
        mock_revoke.assert_called_once_with("uid-legacy", headers_map["tenant-legacy"])

    def test_no_tenants_available(self):
        """Empty tenant_headers_map (all tokens failed) → skipped_no_token."""
        emps = [_emp("alice@a.com")]
        result, mock_lookup, mock_revoke = self._run(emps, {}, {})

        self.assertEqual(result["found"], 0)
        self.assertEqual(result["not_found"], 0)
        self.assertEqual(emps[0]["entra_status"], "skipped_no_token")
        self.assertEqual(emps[0]["entra_tenant_id"], "")
        mock_lookup.assert_not_called()

    def test_tenant_drops_after_three_403s(self):
        """Tenant A 403s consecutively for 3 emails → dropped on the 3rd; future
        lookups for new emails skip it. Tenant B continues to work."""
        emps = [_emp(f"u{i}@x.com") for i in range(4)]
        headers_map = {"tenant-bad": _hdr("bad"), "tenant-good": _hdr("good")}
        # All 4 emails: A always 403, B always 404 (not found)
        lookups = {}
        for i in range(4):
            lookups[(f"u{i}@x.com", "tenant-bad")] = (None, 403)
            lookups[(f"u{i}@x.com", "tenant-good")] = (None, 404)

        result, mock_lookup, _ = self._run(emps, headers_map, lookups)

        # First 3 emails: both tenants tried (6 calls).
        # 3rd email triggers dropout of tenant-bad.
        # 4th email: only tenant-good tried (1 call).
        # Total: 6 + 1 = 7 calls.
        self.assertEqual(mock_lookup.call_count, 7)
        # All emails: not_found in any tenant
        self.assertEqual(result["not_found"], 4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
