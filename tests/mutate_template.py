#!/usr/bin/env python3
"""Break the template on purpose and prove the gate notices.

This repository is bicep-sourced: azuredeploy.json is a build product. Mutating
the JSON would prove nothing about what the next `az bicep build` produces, so
each mutation edits azuredeploy.bicep, RECOMPILES, runs the test that should
catch it, and restores both files.

A mutation that survives is BLIND. A mutation whose anchor no longer matches is
a FAILURE, not a skip: a stale anchor is how a mutation set quietly stops
testing anything.

    python3 tests/mutate_template.py
"""

import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BICEP = os.path.join(REPO, "production", "azuredeploy.bicep")
JSON = os.path.join(REPO, "production", "azuredeploy.json")
MODULE = os.path.join(REPO, "production", "nested_workspace_precheck.bicep")
TABLES = os.path.join(REPO, "production", "nested_law_tables.bicep")
RELEASE = os.path.join(REPO, ".github", "workflows", "release.yml")

GATE = "test_workspace_guard_unit.py"
COUPLING = "test_template_coupling_unit.py"
ISSUER = "test_lookup_and_actions_unit.py"

# (label, file, find, replace, test pattern)
MUTATIONS = [
    ("guard removed entirely", BICEP,
     "module precheck_workspace_exists './nested_workspace_precheck.bicep' = if (!workspaceIsCreatedHere) {",
     "module precheck_workspace_exists './nested_workspace_precheck.bicep' = if (false) {",
     GATE),
    ("guard evaluated in the parent scope", MODULE,
     "output customerId string = ws.properties.customerId",
     "output customerId string = ws.id",
     GATE),
    ("guard stops reading the workspace", MODULE,
     "output customerId string = ws.properties.customerId",
     "output nothing string = 'ok'",
     GATE),
    ("guard always looks in the deployment resource group", BICEP,
     "  scope: resourceGroup(empty(WorkspaceResourceGroup) ? resourceGroup().name : WorkspaceResourceGroup)\n  params: {\n    WorkspaceName: WorkspaceName\n  }\n}\n",
     "  scope: resourceGroup(resourceGroup().name)\n  params: {\n    WorkspaceName: WorkspaceName\n  }\n}\n",
     GATE),
    ("condition written out a second time", BICEP,
     "resource Workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = if (workspaceIsCreatedHere) {",
     "resource Workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = if (CreateWorkspace && empty(WorkspaceResourceGroup)) {",
     GATE),
    ("one resource stops waiting for the guard", BICEP,
     "  dependsOn: [\n    precheck_workspace_exists\n    storageAccountName_default_table\n  ]",
     "  dependsOn: [\n    storageAccountName_default_table\n  ]",
     GATE),
    ("tables back in the deployment's own resource group", BICEP,
     "module lawTables './nested_law_tables.bicep' = {\n  name: 'socradar-law-tables'\n  scope: resourceGroup(empty(WorkspaceResourceGroup) ? resourceGroup().name : WorkspaceResourceGroup)",
     "module lawTables './nested_law_tables.bicep' = {\n  name: 'socradar-law-tables'\n  scope: resourceGroup(resourceGroup().name)",
     GATE),
    ("a table column disappears", TABLES,
     "          name: 'TimeGenerated'\n          type: 'dateTime'",
     "          name: 'TimeGenerated_x'\n          type: 'dateTime'",
     COUPLING),
    ("FIC script issuer follows EntraIdTenantId", BICEP,
     "{ name: 'TENANT_ID', value: subscription().tenantId }",
     "{ name: 'TENANT_ID', value: empty(EntraIdTenantId) ? subscription().tenantId : EntraIdTenantId }",
     ISSUER),
    ("printed FIC command issuer follows EntraIdTenantId", BICEP,
     '"issuer":"https://login.microsoftonline.com/${subscription().tenantId}/v2.0"',
     '"issuer":"https://login.microsoftonline.com/${(empty(EntraIdTenantId)?subscription().tenantId:EntraIdTenantId)}/v2.0"',
     ISSUER),
    ("release gate: refusal no longer fails the job", RELEASE,
     "            exit 1\n", "            exit 0\n", ISSUER),
    ("release gate: comparison inverted", RELEASE,
     '[ "$GITHUB_SHA" != "$TIP" ]', '[ "$GITHUB_SHA" = "$TIP" ]', ISSUER),
    ("release gate: compares against HEAD (always the tag in CI)", RELEASE,
     "TIP=$(git rev-parse origin/master)", "TIP=$(git rev-parse HEAD)", ISSUER),
]


def compile_template():
    r = subprocess.run(["az", "bicep", "build", "--file", BICEP, "--outfile", JSON],
                       capture_output=True, text=True, timeout=300)
    # A mutation that does not compile is caught too: the gate cannot run, which
    # is a louder failure than a red test.
    return r.returncode == 0, (r.stderr or "")[-400:]


def run_gate(pattern):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, "-m", "unittest", "discover",
                        "-s", "tests/unit", "-p", pattern],
                       cwd=REPO, capture_output=True, text=True, timeout=180, env=env)
    return r.returncode == 0


def main():
    backups = {p: p + ".mutbak" for p in (BICEP, JSON, MODULE, TABLES, RELEASE)}
    for src, dst in backups.items():
        shutil.copy2(src, dst)

    ok, err = compile_template()
    if not ok:
        print("REFUSING: the template does not compile before any mutation\n" + err)
        return 2
    if not run_gate(GATE):
        print("REFUSING: the gate is already red, so nothing it says about a "
              "mutation means anything (EXP-AZURE-0148)")
        return 2

    blind, broken = [], []
    try:
        for label, path, find, repl, pattern in MUTATIONS:
            text = open(path, encoding="utf-8").read()
            if find not in text:
                broken.append(label)
                print("ANCHOR GONE  %s" % label)
                continue
            open(path, "w", encoding="utf-8").write(text.replace(find, repl, 1))
            compiled, cerr = (True, "") if path == RELEASE else compile_template()
            if not compiled:
                print("caught (build) %s" % label)
            elif run_gate(pattern):
                blind.append(label)
                print("BLIND        %s" % label)
            else:
                print("caught       %s" % label)
            for src, dst in backups.items():
                shutil.copy2(dst, src)
    finally:
        for src, dst in backups.items():
            shutil.copy2(dst, src)
            os.remove(dst)

    ok, _ = compile_template()
    print("\n%d mutations, %d blind, %d stale anchors" %
          (len(MUTATIONS), len(blind), len(broken)))
    if blind or broken or not ok:
        return 1
    print("every mutation was caught")
    return 0


if __name__ == "__main__":
    sys.exit(main())
