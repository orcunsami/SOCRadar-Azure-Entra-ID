#!/usr/bin/env python3
"""
IncidentMode (None | AlertBacked | Direct): what each mode does in the template
and in the code, one test per way it could quietly stop working.

  - the mode table: 3 IncidentMode values x EnableCreateIncident true/false give
    the right Function App setting and the right rule state
  - the rules are deployed in every mode and switched by one expression, so a
    redeploy with another mode turns them off instead of leaving them on
  - the rule queries and the rules' mappings agree with each other and with the
    table schema, and never read a credential column
  - with the direct path off the code never calls the incidents API

The template is read at test time (the compiled JSON, built from the bicep).
"""

import json
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[2]
PROD = ROOT / "production"
sys.path.insert(0, str(PROD / "FunctionApp"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

TEMPLATE = json.loads((PROD / "azuredeploy.json").read_text())
RULES_BICEP = (PROD / "nested_alert_rules.bicep").read_text()


def _items(res):
    return list(res.values()) if isinstance(res, dict) else list(res or [])


def _module():
    for r in _items(TEMPLATE["resources"]):
        if r.get("type") == "Microsoft.Resources/deployments" and r["name"] == "socradar-alert-rules":
            return r
    raise AssertionError("no socradar-alert-rules deployment in the template")


def _rules_template():
    return _module()["properties"]["template"]


def _resolve(obj, variables):
    """Replace every `[variables('x')]` string, at any depth, with the variable's value."""
    if isinstance(obj, str):
        m = re.fullmatch(r"\[variables\('(\w+)'\)\]", obj)
        return _resolve(variables[m.group(1)], variables) if m else obj
    if isinstance(obj, list):
        return [_resolve(v, variables) for v in obj]
    if isinstance(obj, dict):
        return {k: _resolve(v, variables) for k, v in obj.items()}
    return obj


def _alert_rules():
    variables = _rules_template().get("variables", {})
    return [{**r, "properties": _resolve(r["properties"], variables)}
            for r in _items(_rules_template()["resources"]) if r["type"].endswith("/alertRules")]


def _automation_rules():
    return [r for r in _items(_rules_template()["resources"]) if r["type"].endswith("/automationRules")]


# ---- a small evaluator for the ARM expressions this template uses for the mode ----

def _tokens(s):
    return re.findall(r"'(?:[^']|'')*'|[A-Za-z_]+|\(|\)|,", s)


def _parse(toks):
    t = toks.pop(0)
    if t.startswith("'"):
        return t[1:-1].replace("''", "'")
    if toks and toks[0] == "(":
        toks.pop(0)
        args = []
        while toks[0] != ")":
            args.append(_parse(toks))
            if toks[0] == ",":
                toks.pop(0)
        toks.pop(0)
        return (t, args)
    raise AssertionError("cannot parse " + t)


def _eval(node, params, variables):
    if isinstance(node, str):
        return node
    fn, args = node
    if fn == "parameters":
        return params[args[0]]
    if fn == "variables":
        return _eval(_parse(_tokens(variables[args[0]][1:-1])), params, variables)
    vals = [_eval(a, params, variables) for a in args]
    if fn == "equals":
        return vals[0] == vals[1]
    if fn == "and":
        return all(vals)
    if fn == "if":
        return vals[1] if vals[0] else vals[2]
    if fn == "string":
        return {True: "True", False: "False"}.get(vals[0], str(vals[0]))
    raise AssertionError("function not supported by the test evaluator: " + fn)


def _evaluate(expr, **params):
    assert expr.startswith("[") and expr.endswith("]"), expr
    return _eval(_parse(_tokens(expr[1:-1])), params, TEMPLATE["variables"])


def _app_setting(name):
    for r in _items(TEMPLATE["resources"]):
        if r.get("type") == "Microsoft.Web/sites":
            return next(a["value"] for a in r["properties"]["siteConfig"]["appSettings"] if a["name"] == name)
    raise AssertionError("no Function App")


# mode, legacy flag -> (Function App PUTs incidents, rules enabled)
MODE_TABLE = {
    ("None", False): (False, False),
    ("None", True): (True, False),     # the deprecated flag still means Direct
    ("AlertBacked", False): (False, True),
    ("AlertBacked", True): (False, True),   # an explicit mode beats the legacy flag
    ("Direct", False): (True, False),
    ("Direct", True): (True, False),
}


class ModeTableTests(unittest.TestCase):

    def test_the_parameter_offers_exactly_the_three_modes_and_defaults_to_none(self):
        p = TEMPLATE["parameters"]["IncidentMode"]
        self.assertEqual(p["allowedValues"], ["None", "AlertBacked", "Direct"])
        self.assertEqual(p["defaultValue"], "None")

    def test_the_legacy_flag_is_still_a_parameter_and_still_false_by_default(self):
        p = TEMPLATE["parameters"]["EnableCreateIncident"]
        self.assertIs(p["defaultValue"], False)
        self.assertIn("Deprecated", p["metadata"]["description"])

    def test_every_cell_of_the_mode_table(self):
        enabled_expr = _module()["properties"]["parameters"]["Enabled"]["value"]
        for (mode, legacy), (puts, rules_on) in MODE_TABLE.items():
            params = {"IncidentMode": mode, "EnableCreateIncident": legacy}
            setting = _evaluate(_app_setting("ENABLE_CREATE_INCIDENT"), **params)
            self.assertEqual(setting, "True" if puts else "False", f"setting for {mode}/{legacy}")
            self.assertEqual(_evaluate(enabled_expr, **params), rules_on, f"rules for {mode}/{legacy}")

    def test_the_setting_string_the_template_writes_is_read_as_the_bool_it_means(self):
        from utils import config  # noqa: E402
        import os
        for text, want in (("True", True), ("False", False)):
            os.environ["ENABLE_CREATE_INCIDENT"] = text
            try:
                self.assertIs(config._bool("ENABLE_CREATE_INCIDENT"), want)
            finally:
                del os.environ["ENABLE_CREATE_INCIDENT"]

    def test_a_mode_the_template_does_not_know_is_not_silently_none(self):
        # the only place the mode is compared is effectiveIncidentMode and the Enabled expression
        text = json.dumps(TEMPLATE["variables"]) + json.dumps(_module())
        self.assertEqual(sorted(set(re.findall(r"'(None|AlertBacked|Direct)'", text))),
                         ["AlertBacked", "Direct", "None"])


class RuleLifecycleTests(unittest.TestCase):

    def test_the_rules_are_deployed_in_every_mode(self):
        self.assertNotIn("condition", _module(), "a conditional module leaves rules on after a mode switch")

    def test_three_scheduled_rules_one_per_source_all_switched_by_the_same_expression(self):
        rules = _alert_rules()
        self.assertEqual(len(rules), 3)
        for r in rules:
            self.assertEqual(r["kind"], "Scheduled")
            self.assertEqual(r["properties"]["enabled"], "[parameters('Enabled')]", r["properties"]["displayName"])
            self.assertEqual(r["properties"]["queryFrequency"], "PT1H")   # a period of 2 days or more needs a frequency of at least 1 hour
            self.assertEqual(r["properties"]["queryPeriod"], "P7D")   # the dedup look-back: the engine reads SecurityAlert no further back than this
            self.assertIs(r["properties"]["incidentConfiguration"]["createIncident"], True)
            self.assertEqual(r["properties"]["eventGroupingSettings"]["aggregationKind"], "AlertPerResult")
            self.assertIs(r["properties"]["suppressionEnabled"], False)

    def test_a_period_of_two_days_or_more_runs_at_most_hourly(self):
        # measured: "When 'queryPeriod' greater than or equal to 2 days, the 'queryFrequency' should be
        # greater than or equal to 1 hour" - Sentinel refuses the rule and the whole deployment fails
        def minutes(iso):
            m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?", iso)
            d, h, mi = (int(x or 0) for x in m.groups())
            return d * 1440 + h * 60 + mi
        for r in _alert_rules():
            p = r["properties"]
            if minutes(p["queryPeriod"]) >= 2 * 1440:
                self.assertGreaterEqual(minutes(p["queryFrequency"]), 60, p["displayName"])

    def test_the_labeler_follows_the_same_switch(self):
        (auto,) = _automation_rules()
        self.assertEqual(auto["properties"]["triggeringLogic"]["isEnabled"], "[parameters('Enabled')]")

    def test_one_rule_per_table(self):
        tables = sorted(re.search(r"\n(SOCRadar_\w+_CL)\n", r["properties"]["query"]).group(1) for r in _alert_rules())
        self.assertEqual(tables, ["SOCRadar_Botnet_CL", "SOCRadar_PII_CL", "SOCRadar_VIP_CL"])

    def test_the_module_lands_in_the_workspace_group_after_the_tables_and_the_onboarding(self):
        m = _module()
        self.assertIn("lawTables", m["dependsOn"])
        self.assertIn("WorkspaceName_Microsoft_SecurityInsights_default", m["dependsOn"])
        self.assertIn("sentinel_onboard_id", m["dependsOn"])
        self.assertIn("precheck_workspace_exists", m["dependsOn"])
        self.assertIn("WorkspaceResourceGroup", m["resourceGroup"])   # the workspace's group, not the Function App's

    def test_the_function_app_gets_no_role_for_the_rules(self):
        roles = [r for r in _items(TEMPLATE["resources"]) if r.get("type") == "Microsoft.Authorization/roleAssignments"]
        self.assertFalse([r for r in roles if "Sentinel" in json.dumps(r)],
                         "AlertBacked needs no Microsoft Sentinel role for the Function App")


def _table_columns():
    """Columns of the three source tables, from the bicep that creates them."""
    src = (PROD / "nested_law_tables.bicep").read_text()
    cols = {}
    for m in re.finditer(r"name: '(SOCRadar_\w+_CL)'\s*\n\s*properties:.*?columns: \[(.*?)\]\s*\n\s*\}", src, re.S):
        cols[m.group(1)] = set(re.findall(r"name: '(\w+)'", m.group(2)))
    return cols


def _final_projection(query):
    last = [l for l in query.splitlines() if l.startswith("| project ")][-1]
    return [c.strip() for c in last[len("| project "):].split(",")]


def _first_projection(query):
    first = [l for l in query.splitlines() if l.startswith("| project ")][0]
    return [c.strip() for c in first[len("| project "):].split(",")]


class RuleContentTests(unittest.TestCase):

    def test_no_rule_resource_mentions_a_credential_column_anywhere(self):
        # the module source AND the compiled rule resources, case-insensitive: password_present and
        # password_masked count too, they are credential-derived
        compiled = json.dumps(_items(_rules_template()["resources"])).lower()
        self.assertEqual(compiled.count("password"), 0)
        self.assertEqual(RULES_BICEP.lower().count("password"), 0)

    def test_the_queries_read_only_columns_the_table_has_and_nothing_else(self):
        cols = _table_columns()
        for r in _alert_rules():
            q = r["properties"]["query"]
            table = re.search(r"\n(SOCRadar_\w+_CL)\n", q).group(1)
            picked = [c for c in _first_projection(q) if c != "TimeGenerated"]
            self.assertTrue(set(picked) <= cols[table], (table, set(picked) - cols[table]))
            self.assertEqual(len(picked), len(set(picked)))

    def test_the_final_projection_has_every_column_a_mapping_or_placeholder_uses(self):
        for r in _alert_rules():
            p = r["properties"]
            out = set(_final_projection(p["query"]))
            used = set(p["customDetails"].values())
            for e in p["entityMappings"]:
                used |= {f["columnName"] for f in e["fieldMappings"]}
            used.add(p["alertDetailsOverride"]["alertSeverityColumnName"])
            fmt = p["alertDetailsOverride"]["alertDisplayNameFormat"] + p["alertDetailsOverride"]["alertDescriptionFormat"]
            used |= set(re.findall(r"\{\{(\w+)\}\}", fmt))
            self.assertFalse(used - out, (p["displayName"], used - out))

    def test_a_description_names_at_most_three_columns(self):
        # measured: Microsoft Sentinel refuses more ("You have defined 5 parameters ... maximum allowed is 3")
        for r in _alert_rules():
            o = r["properties"]["alertDetailsOverride"]
            for key in ("alertDisplayNameFormat", "alertDescriptionFormat"):
                self.assertLessEqual(len(re.findall(r"\{\{\w+\}\}", o[key])), 3, key)

    def test_the_account_is_an_entity_in_every_rule_and_only_botnet_adds_an_address(self):
        for r in _alert_rules():
            types = [e["entityType"] for e in r["properties"]["entityMappings"]]
            self.assertEqual(types[0], "Account")
            botnet = "Botnet" in r["properties"]["displayName"]
            self.assertEqual(types, ["Account", "IP"] if botnet else ["Account"])
            acct = r["properties"]["entityMappings"][0]["fieldMappings"]
            self.assertEqual({f["identifier"] for f in acct}, {"Name", "UPNSuffix"})

    def test_the_dedup_key_is_in_the_alert_and_read_back_under_the_same_name(self):
        for r in _alert_rules():
            q = r["properties"]["query"]
            self.assertEqual(r["properties"]["customDetails"]["DedupKey"], "DedupKey")
            self.assertIn(".DedupKey[0]", q)           # read back from the still-encoded Custom Details
            self.assertIn("join kind=leftanti Alerted on $left.DedupKey == $right.AlertedKey", q)
            self.assertIn("union isfuzzy=true", q)      # a workspace with no SecurityAlert yet
            # the key carries the alarm, the account and the source, as text on both sides
            self.assertIn('strcat(source, "|", tostring(alarm_id), "|", tolower(email))', q)

    def test_a_row_is_held_back_until_the_platform_can_see_the_previous_alert(self):
        for r in _alert_rules():
            q = r["properties"]["query"]
            self.assertIn("ingestion_time() < ago(12m)", q)
            self.assertIn("ingestion_time() > ago(7d)", q)   # rows are read over the same window
            # no explicit look-back on SecurityAlert: the rule engine clamps it to queryPeriod (measured)
            self.assertNotIn("SecurityAlert | where", q)
            self.assertIn("take 149", q)                # a rule raises at most 150 alerts per run

    def test_the_severity_column_emits_only_values_the_platform_accepts(self):
        for r in _alert_rules():
            q = r["properties"]["query"]
            case = re.search(r"SentinelSeverity = case\((.*)\)", q).group(1)
            self.assertEqual(sorted(set(re.findall(r'"(High|Medium|Low)"', case))), ["High", "Low", "Medium"])
            self.assertIn('"CRITICAL", "HIGH"), "High"', case)   # sentinel.py maps Critical to High


class DirectPathTests(unittest.TestCase):

    def test_with_the_direct_path_off_the_incidents_api_is_never_called_and_nothing_is_ledgered(self):
        from test_lookup_and_actions_unit import _emp, _run  # noqa: E402
        create = Mock(return_value=True)
        audit, written, led = _run(_emp(), {"enable_create_incident": False}, sent__create_incident=create)
        create.assert_not_called()
        self.assertNotIn("create_incident", " ".join(written[0]["actions_taken"]))
        self.assertFalse(led.already_applied("botnet", "a@x.com", "create_incident", "initial"))

    def test_with_the_direct_path_on_it_is_called_once(self):
        from test_lookup_and_actions_unit import _emp, _run  # noqa: E402
        create = Mock(return_value=True)
        _run(_emp(), {"enable_create_incident": True}, sent__create_incident=create)
        create.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
