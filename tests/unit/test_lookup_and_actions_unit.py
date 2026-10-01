#!/usr/bin/env python3
"""
Findings from the 1 Oct 2026 audit (task_azure_0080), one test each.

  - a feed value must not steer the Graph path (email injection)
  - VIP records carry a name, not an address: the name is not an email
  - CreateIncident: a failed PUT is not "applied", a good one shows in actions_taken
  - force_mfa counts as an action only when something was deleted
  - EnableAddToGroup without a group says so instead of doing nothing silently
  - ENABLE_ADD_TO_GROUP defaults to off, as the template and README say
  - the release workflow refuses a tag that is not the tip of master

Needs the azure packages (function_app imports azure.functions), same as CI.
"""

import json
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "production" / "FunctionApp"))

import function_app  # noqa: E402
from actions import action_ledger, entra_id, sentinel  # noqa: E402
from sources import vip  # noqa: E402
from utils import config  # noqa: E402

HEADERS = {"Authorization": "Bearer x"}
EVIL = ["x@y.com/../../groups", "x@y.com?$select=id", "x@y.com#frag", "a b@y.com",
        "x@y.com\\..", "x%2F..@y.com", "no-at-sign", "a@b@c.com", "@y.com", "x@"]


def _resp(status, body=None):
    r = Mock()
    r.status_code = status
    r.json.return_value = body or {}
    r.text = ""
    return r


class LookupAddressTests(unittest.TestCase):

    def test_an_address_that_can_steer_the_path_is_never_sent_to_graph(self):
        for email in EVIL:
            with patch("actions.entra_id._graph_request") as req:
                user, status = entra_id.lookup_user(email, HEADERS)
            self.assertEqual((user, status), (None, 0), email)
            req.assert_not_called()

    def test_a_normal_address_is_percent_encoded_in_the_path(self):
        with patch("actions.entra_id._graph_request", return_value=_resp(200, {"id": "u"})) as req:
            entra_id.lookup_user("o'brien+x@y.com", HEADERS)
        url = req.call_args[0][1]
        self.assertEqual(url, entra_id.GRAPH_BASE + "/users/o%27brien%2Bx@y.com")

    def test_the_caller_skips_an_unsafe_address_without_a_lookup(self):
        emps = [{"email": "x@y.com/../../groups"}]
        emps[-1]["_checkpoint_update"] = {"last_start_date": "2026-08-13"}
        lookup = Mock(return_value=({"id": "u1"}, 200))
        audit, written, _ = _run(emps, {}, lookup=lookup)
        lookup.assert_not_called()
        self.assertEqual(written[0]["entra_status"], "skipped_no_address")
        self.assertEqual(audit["no_address"], 1)


class VipEmailTests(unittest.TestCase):

    def _fetch(self, rec):
        body = {"is_success": True, "data": {"data": [rec], "total_data_count": 1}}
        with patch.object(vip.requests, "get", return_value=_resp(200, body)), \
             patch.object(vip.time, "sleep"):
            return vip.fetch({"socradar_api_key": "k", "socradar_company_id": "1"}, {})

    def test_a_vip_name_is_not_used_as_an_email(self):
        rec = self._fetch({"vipName": "John Smith"})[0]
        self.assertEqual(rec["email"], "")
        self.assertEqual(rec["vip_name"], "John Smith")

    def test_a_real_email_field_still_wins(self):
        rec = self._fetch({"vipName": "John Smith", "email": "john@y.com"})[0]
        self.assertEqual(rec["email"], "john@y.com")


def _conf(**over):
    conf = {
        "enable_user_lookup": True, "enable_revoke_session": False,
        "entra_max_actions_per_run": 50, "enable_ropc": False,
        "enable_add_to_group": False, "enable_remove_from_group": False,
        "enable_disable_account": False, "enable_enable_account": False,
        "enable_password_change": False, "enable_confirm_risky": False,
        "enable_force_mfa_reregistration": False, "enable_create_incident": False,
        "enable_resolve_alarm": False, "security_group_id": "",
        "storage_account_name": "teststorage", "verified_domains": [],
    }
    conf.update(over)
    return conf


def _run(employees, conf_over, lookup=None, ledger=None, **patches):
    """Run _process_source with the network and storage stubbed. Returns (audit, written, ledger)."""
    written = []
    led = ledger or action_ledger.InMemoryActionLedger()
    lookup = lookup or Mock(return_value=({"id": "u1", "accountEnabled": True}, 200))
    stack = [
        patch.object(function_app.src_botnet, "fetch", return_value=employees),
        patch.object(function_app.law, "write_records",
                     side_effect=lambda c, s, r: (written.extend(r), True)[1]),
        patch.object(function_app.law, "write_lifecycle_event"),
        patch.object(function_app.cp, "load", return_value={}),
        patch.object(function_app.cp, "save"),
        patch.object(function_app.act_ledger, "build", return_value=led),
        patch.object(function_app.entra, "lookup_user", lookup),
    ]
    for target, value in patches.items():
        mod, attr = target.split("__")
        stack.append(patch.object(getattr(function_app, mod), attr, value))
    for p in stack:
        p.start()
    try:
        audit = function_app._process_source(
            source_name="botnet", conf=_conf(**conf_over), credential=object(),
            tenant_headers_map={"t1": HEADERS}, function_start_time=time.time())
    finally:
        for p in stack:
            p.stop()
    return audit, written, led


def _emp():
    e = [{"email": "a@x.com"}]
    e[-1]["_checkpoint_update"] = {"last_start_date": "2026-08-13"}
    return e


class CreateIncidentTests(unittest.TestCase):

    CONF = {"workspace_name": "w", "workspace_resource_group": "rg", "subscription_id": "s"}

    def _create(self, status):
        cred = MagicMock()
        with patch.object(sentinel.requests, "put", return_value=_resp(status)):
            return sentinel.create_incident(self.CONF, "a@x.com", "botnet", "MEDIUM", credential=cred)

    def test_create_incident_reports_whether_it_worked(self):
        self.assertIs(self._create(201), True)
        self.assertIs(self._create(200), True)
        self.assertIs(self._create(403), False)

    def test_create_incident_is_false_when_it_cannot_even_try(self):
        self.assertIs(sentinel.create_incident({}, "a@x.com", "botnet", "MEDIUM", credential=MagicMock()), False)
        self.assertIs(sentinel.create_incident(self.CONF, "a@x.com", "botnet", "MEDIUM", credential=None), False)

    def test_a_failed_incident_is_reported_failed_and_not_ledgered(self):
        audit, written, led = _run(_emp(), {"enable_create_incident": True},
                                   sent__create_incident=Mock(return_value=False))
        self.assertEqual(written[0]["actions_taken"], ["create_incident_failed"])
        self.assertFalse(led.already_applied("botnet", "a@x.com", "create_incident", "initial"))

    def test_a_created_incident_shows_in_actions_taken_and_is_ledgered(self):
        create = Mock(return_value=True)
        audit, written, led = _run(_emp(), {"enable_create_incident": True}, sent__create_incident=create)
        self.assertEqual(written[0]["actions_taken"], ["create_incident"])
        self.assertEqual(create.call_count, 1)
        self.assertTrue(led.already_applied("botnet", "a@x.com", "create_incident", "initial"))

    def test_a_ledgered_incident_is_not_created_again(self):
        led = action_ledger.InMemoryActionLedger()
        create = Mock(return_value=True)
        _run(_emp(), {"enable_create_incident": True}, ledger=led, sent__create_incident=create)
        audit, written, _ = _run(_emp(), {"enable_create_incident": True}, ledger=led,
                                 sent__create_incident=create)
        self.assertEqual(create.call_count, 1)
        self.assertEqual(written[0]["actions_taken"], ["create_incident_skipped_duplicate"])


class ActionAccountingTests(unittest.TestCase):

    def test_force_mfa_with_nothing_to_delete_is_not_an_action(self):
        result = {"permission_denied": False, "methods_deleted": 0, "methods_skipped": 1, "errors": []}
        audit, written, _ = _run(_emp(), {"enable_force_mfa_reregistration": True},
                                 entra__force_mfa_reregistration=Mock(return_value=result))
        self.assertEqual(written[0]["actions_taken"], ["force_mfa_rereg_no_methods"])
        self.assertEqual(audit["actions"], 0)

    def test_force_mfa_that_deleted_something_is_an_action(self):
        result = {"permission_denied": False, "methods_deleted": 2, "methods_skipped": 1, "errors": []}
        audit, _, _ = _run(_emp(), {"enable_force_mfa_reregistration": True},
                           entra__force_mfa_reregistration=Mock(return_value=result))
        self.assertEqual(audit["actions"], 1)

    def test_add_to_group_without_a_group_says_so(self):
        add = Mock(return_value=True)
        audit, written, _ = _run(_emp(), {"enable_add_to_group": True, "security_group_id": ""},
                                 entra__add_to_group=add)
        add.assert_not_called()
        self.assertEqual(written[0]["actions_taken"], ["add_to_group_no_group_configured"])

    def test_the_missing_group_warning_is_logged_once_per_run(self):
        emps = [{"email": "a@x.com"}, {"email": "b@x.com"}]
        emps[-1]["_checkpoint_update"] = {"last_start_date": "2026-08-13"}
        with patch.object(function_app.logger, "warning") as warn:
            audit, written, _ = _run(emps, {"enable_add_to_group": True, "security_group_id": ""})
        self.assertEqual([w["actions_taken"] for w in written],
                         [["add_to_group_no_group_configured"]] * 2)
        self.assertEqual(sum("SecurityGroupId is empty" in str(c) for c in warn.call_args_list), 1)


class DefaultsTests(unittest.TestCase):

    def test_add_to_group_is_off_unless_asked_for(self):
        env = {"SOCRADAR_API_KEY": "k", "SOCRADAR_COMPANY_ID": "1", "ENABLE_USER_LOOKUP": "false",
               "DCR_IMMUTABLE_ID": "d", "DCR_ENDPOINT": "https://e.invalid", "STORAGE_ACCOUNT_NAME": "st"}
        with patch.dict("os.environ", env, clear=True):
            self.assertIs(config.load()["enable_add_to_group"], False)


class FicIssuerTests(unittest.TestCase):
    """The federated credential trusts the tenant that issues the managed identity's token:
    the subscription's tenant, whatever EntraIdTenantId says about the directory to query."""

    @classmethod
    def setUpClass(cls):
        cls.tpl = json.loads((ROOT / "production" / "azuredeploy.json").read_text())

    def test_the_fic_script_gets_the_subscription_tenant(self):
        env = self.tpl["resources"]["addFicToExistingApp"]["properties"]["environmentVariables"]
        tenant = [e["value"] for e in env if e["name"] == "TENANT_ID"]
        self.assertEqual(tenant, ["[subscription().tenantId]"])

    def test_the_printed_fic_command_uses_the_subscription_tenant(self):
        out = self.tpl["outputs"]["ficCommandToRun"]["value"]
        self.assertIn("subscription().tenantId", out)
        self.assertNotIn("EntraIdTenantId", out)


class ReleaseGateTests(unittest.TestCase):
    """Runs the gate step's own shell script against throwaway git repos."""

    @staticmethod
    def _gate_script():
        lines = (ROOT / ".github" / "workflows" / "release.yml").read_text().splitlines()
        start = next(i for i, l in enumerate(lines) if "name: Tag must point at the tip of master" in l)
        run = next(i for i in range(start, len(lines)) if lines[i].strip() == "run: |")
        body = []
        for l in lines[run + 1:]:
            if l.strip().startswith("- name:"):
                break
            body.append(l)
        indent = min(len(l) - len(l.lstrip()) for l in body if l.strip())
        return "\n".join(l[indent:] for l in body)

    def _run_gate(self, tag_sha_index):
        import os
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            def git(*a, cwd):
                return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True,
                                      text=True).stdout.strip()
            origin = os.path.join(tmp, "origin.git")
            work = os.path.join(tmp, "work")
            git("init", "-q", "--bare", "-b", "master", origin, cwd=tmp)
            git("clone", "-q", origin, work, cwd=tmp)
            git("config", "user.email", "t@example.com", cwd=work)
            git("config", "user.name", "t", cwd=work)
            shas = []
            for n in ("old", "tip"):
                Path(work, n).write_text(n)
                git("add", n, cwd=work)
                git("commit", "-q", "-m", n, cwd=work)
                shas.append(git("rev-parse", "HEAD", cwd=work))
            git("push", "-q", "origin", "master", cwd=work)
            # actions/checkout on a tag leaves HEAD detached AT the tag commit
            git("checkout", "-q", "--detach", shas[tag_sha_index], cwd=work)
            env = dict(os.environ, GITHUB_SHA=shas[tag_sha_index], GITHUB_REF_NAME="v1.0.0")
            return subprocess.run(["bash", "-e", "-c", self._gate_script()], cwd=work,
                                  env=env, capture_output=True, text=True)

    def test_a_tag_behind_master_is_refused(self):
        r = self._run_gate(0)
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("refusing", r.stdout)

    def test_a_tag_at_the_master_tip_is_allowed(self):
        r = self._run_gate(1)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_the_gate_runs_before_anything_is_built(self):
        text = (ROOT / ".github" / "workflows" / "release.yml").read_text()
        self.assertIn("fetch-depth: 0", text)
        self.assertLess(text.index("rev-parse origin/master"),
                        text.index("- name: Build FunctionApp.zip"))


if __name__ == "__main__":
    unittest.main()
