#!/usr/bin/env python3
"""
Couples the code to the ARM template it ships with.

Two failure classes these catch, both invisible at runtime:
  * the code reads an App Setting the template never writes — the feature
    silently runs on its default;
  * the code sends a column the collection rule does not declare — the DCR
    drops it without an error and the data never reaches the table.

The template is read at test time, so these stay correct as both sides move.
"""

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "production" / "FunctionApp"
sys.path.insert(0, str(APP))

TEMPLATE = json.loads((ROOT / "production" / "azuredeploy.json").read_text())

# Settings the platform itself provides or that tests/tools read — the
# template legitimately does not write these.
_PLATFORM_PREFIXES = ("AzureWebJobs", "WEBSITE_", "FUNCTIONS_",
                      "APPLICATIONINSIGHTS")


def _app_settings():
    for r in TEMPLATE["resources"].values():
        if r.get("type") == "Microsoft.Web/sites":
            return {a["name"] for a in
                    r["properties"]["siteConfig"]["appSettings"]}
    raise AssertionError("no Microsoft.Web/sites resource in template")


def _dcr_streams():
    for r in TEMPLATE["resources"].values():
        if r.get("type", "").startswith("Microsoft.Insights/dataCollectionRules"):
            return {s: {c["name"] for c in v["columns"]}
                    for s, v in r["properties"]["streamDeclarations"].items()}
    raise AssertionError("no dataCollectionRules resource in template")


def _every_resource(doc):
    """Root resources plus the ones inside nested deployments.

    The four tables moved into a module in task_azure_0062 so a
    cross-resource-group install lands them next to the workspace. Reading only
    the root would have made this file's assertions vacuous - it raised instead,
    which is why the move did not go unnoticed."""
    res = doc.get("resources")
    items = list(res.values()) if isinstance(res, dict) else list(res or [])
    for r in list(items):
        if r.get("type") == "Microsoft.Resources/deployments":
            inner = r.get("properties", {}).get("template")
            if inner:
                items.extend(_every_resource(inner))
    return items


def _law_tables():
    out = {}
    for r in _every_resource(TEMPLATE):
        if r.get("type", "").endswith("workspaces/tables"):
            name = re.search(r"SOCRadar_[A-Za-z_]+", str(r["name"])).group(0)
            out[name] = {c["name"] for c in r["properties"]["schema"]["columns"]}
    if not out:
        raise AssertionError("no workspaces/tables resources in template or in "
                             "any nested deployment")
    return out


def _env_keys_read_by_code():
    keys = set()
    for p in APP.rglob("*.py"):
        if ".python_packages" in p.parts:
            continue
        src = p.read_text()
        keys |= set(re.findall(
            r'os\.environ(?:\.get)?\(\s*["\']([A-Z_0-9]+)["\']', src))
        keys |= set(re.findall(r'os\.environ\[\s*["\']([A-Z_0-9]+)["\']', src))
        if p.name == "config.py":
            keys |= set(re.findall(
                r'_(?:get|bool|int|list)\(\s*["\']([A-Z_0-9]+)["\']', src))
    return keys


class SettingsCoupling(unittest.TestCase):

    def test_every_setting_the_code_reads_is_written_by_the_template(self):
        code = _env_keys_read_by_code()
        self.assertGreater(len(code), 20, "extraction swept nothing")
        written = _app_settings()
        missing = {k for k in code - written
                   if not k.startswith(_PLATFORM_PREFIXES)}
        self.assertEqual(missing, set(),
                         "code reads settings the template never writes")


class ColumnCoupling(unittest.TestCase):
    """Every field the app ADDS to a feed record must be declared for every
    source stream, or the DCR silently drops it for that source only."""

    # Fields function_app.py sets on records before they go to LAW.
    APP_ADDED = {"entra_status", "entra_tenant_id", "actions_taken",
                 "severity", "entra_account_enabled",
                 "mfa_methods_deleted", "mfa_methods_skipped"}

    def test_app_added_fields_are_declared_in_every_source_stream(self):
        streams = _dcr_streams()
        for stream in ("Custom-SOCRadar_Botnet_CL", "Custom-SOCRadar_PII_CL",
                       "Custom-SOCRadar_VIP_CL"):
            missing = self.APP_ADDED - streams[stream]
            self.assertEqual(missing, set(),
                             f"{stream} silently drops {sorted(missing)}")

    def test_app_added_fields_exist_in_every_source_law_table(self):
        tables = _law_tables()
        for table in ("SOCRadar_Botnet_CL", "SOCRadar_PII_CL",
                      "SOCRadar_VIP_CL"):
            missing = self.APP_ADDED - tables[table]
            self.assertEqual(missing, set(),
                             f"{table} lacks columns {sorted(missing)}")

    def test_dcr_stream_and_law_table_agree_per_source(self):
        streams, tables = _dcr_streams(), _law_tables()
        for name, cols in tables.items():
            diff = streams[f"Custom-{name}"] ^ cols
            self.assertEqual(diff, set(),
                             f"{name}: stream and table disagree on {sorted(diff)}")

    # The accounting buckets the audit row must carry. Dropping one of these
    # from write_audit silently blinds the run summary — a removal is as wrong
    # as sending an undeclared field.
    AUDIT_REQUIRED = {"total_records", "found_count", "not_found_count",
                      "domain_filtered", "no_address_count",
                      "lookup_disabled_count", "no_token_count",
                      "lookup_failed_count", "truncated", "capped",
                      "error_count"}

    def test_audit_summary_fields_are_declared(self):
        src = (APP / "actions" / "law_writer.py").read_text()
        body = src.split("def write_audit", 1)[1].split("\ndef ", 1)[0]
        sent = set(re.findall(r'"([A-Za-z_]+)":\s', body))
        self.assertGreater(len(sent), 5, "extraction swept nothing")
        cols = _dcr_streams()["Custom-SOCRadar_EntraID_Audit_CL"]
        self.assertEqual(sent - cols, set(),
                         "write_audit sends fields the audit stream drops")
        missing = self.AUDIT_REQUIRED - sent
        self.assertEqual(missing, set(),
                         f"write_audit stopped sending {sorted(missing)}")

    def test_every_source_the_code_writes_has_a_stream(self):
        from actions import law_writer
        streams = _dcr_streams()
        for stream in law_writer.STREAM_MAP.values():
            self.assertIn(stream, streams)


if __name__ == "__main__":
    unittest.main()
