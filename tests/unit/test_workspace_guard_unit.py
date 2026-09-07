"""Nothing may be created before the workspace is proved to exist.

A customer deployed this template with CreateWorkspace=false and a workspace
name that was not there. ARM does not treat a false condition as a missing
dependency -- it treats it as a SATISFIED one -- so every resource that does
not touch the workspace was created anyway and the install was half done:
resources billing, integration dead, and the deployment reported the failure
only at the end.

`dependsOn: [Workspace]` therefore guards nothing. The guard has to READ the
workspace, which is what `existing` + an output that reads a property compiles
to: an inner-scope nested deployment whose expression is reference(). An outer
scope would be evaluated in the parent and pass for a workspace that is not
there, which is the single mistake that makes this whole file worthless.

The guard's condition is the Workspace resource's condition negated, and both
come from one variable: two copies of the same condition drift (EXP-AZURE-0178).

Reads files only: no app import, no Azure stub, no network.
"""

import json
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TEMPLATE = REPO / "production" / "azuredeploy.json"
BICEP = REPO / "production" / "azuredeploy.bicep"
MODULE = REPO / "production" / "nested_workspace_precheck.bicep"

GUARD = "precheck_workspace_exists"
VAR = "workspaceIsCreatedHere"


class WorkspaceGuard(unittest.TestCase):
    def setUp(self):
        self.doc = json.loads(TEMPLATE.read_text())
        res = self.doc.get("resources")
        self.assertIsInstance(res, dict,
                              "languageVersion 2.0 keys resources by symbolic name; "
                              "this test reads those keys")
        self.res = res
        self.src = BICEP.read_text()

    # --- the guard exists and has the only shape that works ----------------

    def test_the_guard_is_in_the_template(self):
        self.assertIn(GUARD, self.res,
                      "the missing-workspace guard is gone; a wrong workspace name "
                      "leaves a half install again")

    def test_the_guard_is_a_nested_deployment(self):
        self.assertEqual(self.res[GUARD]["type"], "Microsoft.Resources/deployments")

    def test_the_guard_is_evaluated_in_its_own_scope(self):
        """scope: outer is evaluated in the parent and passes for a workspace that
        is not there. This is the assertion the whole guard rests on."""
        opts = self.res[GUARD]["properties"].get("expressionEvaluationOptions", {})
        self.assertEqual(opts.get("scope"), "inner")

    def test_the_guard_reads_the_workspace(self):
        """resourceId() is string arithmetic and succeeds for anything. Only a
        reference() call fails on a resource that does not exist."""
        outputs = self.res[GUARD]["properties"]["template"].get("outputs") or {}
        self.assertTrue(outputs, "the guard has no output, so it evaluates nothing")
        self.assertTrue(
            any("reference(" in json.dumps(v) for v in outputs.values()),
            "no output calls reference(); the guard would pass for a workspace "
            "that does not exist",
        )

    def test_the_guard_creates_nothing(self):
        inner = self.res[GUARD]["properties"]["template"].get("resources")
        inner = list(inner.values()) if isinstance(inner, dict) else list(inner or [])
        self.assertEqual(inner, [],
                         "the guard deploys a resource; it is meant to read only")

    def test_the_guard_runs_exactly_when_the_workspace_is_not_ours(self):
        """Unconditional would break the default greenfield install, where this
        deployment is the one creating the workspace."""
        cond = self.res[GUARD].get("condition", "")
        self.assertIn(VAR, cond,
                      "the guard's condition does not come from %s" % VAR)
        self.assertIn("not(", cond.replace(" ", ""),
                      "the guard's condition is not the negation of %s" % VAR)

    def test_the_guard_looks_in_the_resource_group_that_holds_the_workspace(self):
        """Cross-resource-group installs pass WorkspaceResourceGroup; a guard that
        always looks in the deployment resource group would fail a correct install."""
        rg = self.res[GUARD].get("resourceGroup", "")
        self.assertIn("WorkspaceResourceGroup", rg)
        self.assertIn("resourceGroup()", rg,
                      "the same-resource-group case has no fallback")

    def test_the_tables_land_where_the_workspace_is(self):
        """The four custom tables used to be declared `parent: Workspace`, which
        resolved in the deployment's own resource group. A cross-resource-group
        install therefore failed with four ParentResourceNotFound errors after
        creating 11 resources (measured 7 Sep 2026). They are a module now, and
        its scope has to follow the workspace."""
        self.assertIn("lawTables", self.res, "the law-tables module is gone")
        rg = self.res["lawTables"].get("resourceGroup", "")
        self.assertIn("WorkspaceResourceGroup", rg,
                      "the tables are pinned to the deployment resource group; "
                      "a cross-resource-group install would fail again")
        self.assertIn("resourceGroup()", rg,
                      "the same-resource-group case has no fallback")
        inner = self.res["lawTables"]["properties"]["template"]["resources"]
        inner = list(inner.values()) if isinstance(inner, dict) else list(inner or [])
        tables = [r for r in inner if r.get("type", "").endswith("workspaces/tables")]
        self.assertEqual(len(tables), 4,
                         "expected 4 tables in the module, found %d" % len(tables))

    def test_the_tables_are_declared_once(self):
        """Copying the schemas into the module instead of moving them would give
        two column lists that drift, and the coupling test only reads one."""
        root = [k for k, v in self.res.items()
                if v.get("type", "").endswith("workspaces/tables")]
        self.assertEqual(root, [],
                         "these tables are still declared in the root template "
                         "as well: %s" % ", ".join(root))

    # --- everything waits for it -------------------------------------------

    def test_every_other_resource_waits_for_the_guard(self):
        """`existing` declarations are exempt: they create nothing, and bicep
        rejects dependsOn on them outright (BCP037)."""
        missing = [name for name, body in self.res.items()
                   if name != GUARD
                   and not body.get("existing")
                   and GUARD not in (body.get("dependsOn") or [])]
        self.assertEqual(missing, [],
                         "these resources can be created before the guard answers: %s"
                         % ", ".join(sorted(missing)))

    def test_the_exemption_is_earned_in_the_source(self):
        """The gate above skips resources marked `existing`. A hand-edited JSON
        could claim that to dodge it, so each exemption has to be declared that
        way in the bicep the compiler reads. (`existing` resources do carry a
        properties block - it holds the lookup key - so "creates nothing" cannot
        be read off the JSON body.)"""
        for name, body in self.res.items():
            if body.get("existing"):
                self.assertTrue(
                    re.search(r"^resource %s .*existing" % re.escape(name),
                              self.src, re.M),
                    "%s is exempt from the guard but the bicep source does not "
                    "declare it existing" % name)

    # --- the condition is stated once --------------------------------------

    def test_the_workspace_condition_is_not_a_second_copy(self):
        """The guard fires when the Workspace resource does not. If the two
        conditions are written out separately, changing one silently opens a hole."""
        # assertIn would print the whole 1500-line source on failure.
        self.assertTrue(
            "var %s = CreateWorkspace && empty(WorkspaceResourceGroup)" % VAR in self.src,
            "the shared condition variable is gone from the bicep source")
        body = self.src.split("resource Workspace ", 1)
        self.assertEqual(len(body), 2, "the Workspace resource is gone")
        head = body[1].split("\n", 1)[0]
        self.assertIn("if (%s)" % VAR, head,
                      "the Workspace resource states its own copy of the condition")

    def test_the_guard_module_exists_on_disk(self):
        self.assertTrue(MODULE.exists(),
                        "nested_workspace_precheck.bicep is missing, so a fresh "
                        "bicep build cannot reproduce the template")
        text = MODULE.read_text()
        self.assertIn("existing", text)
        self.assertIn("output customerId", text)

    def test_the_source_and_the_built_template_agree_about_the_guard(self):
        """Anyone editing edits the bicep; the deploy button serves the JSON. The
        two drifted once already in this repository."""
        self.assertTrue("module %s " % GUARD in self.src,
                        "the guard is in the built JSON but not in the bicep source, "
                        "so the next compile deletes it")
        refs = len(re.findall(r"dependsOn: \[\s*\n\s*%s" % GUARD, self.src))
        gated = sum(1 for name, body in self.res.items()
                    if name != GUARD and not body.get("existing"))
        self.assertGreaterEqual(refs, gated,
                                "the bicep source gates %d resources, the built "
                                "template gates %d" % (refs, gated))


if __name__ == "__main__":
    unittest.main()
