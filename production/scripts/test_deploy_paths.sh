#!/usr/bin/env bash
# Five live deployment paths. Run from the repository root.
#
# A customer deployed this template with CreateWorkspace=false and a workspace
# name that was not there. ARM treats a false condition as a SATISFIED
# dependency, so everything that does not touch the workspace was created anyway.
# Measured on the untouched template, 7 Sep 2026: Failed, 11 resources left.
# The same run showed a second defect - a cross-resource-group install failed
# with four ParentResourceNotFound errors, also leaving 11 resources.
#
# What is asserted is the OUTCOME, not the reason. When a path fails, the reason
# is read back from Azure (blame_detail) instead of guessed: a harness that
# prints its author's hypothesis blamed the wrong thing four times in a row on
# the sister product (EXP-AZURE-0210).
#
# The App Registration is REUSED, never created (CLAUDE.md). A created one is
# not removed by `az group delete`, and it needs consent. The FIC and App Reg
# counts are compared before and after so litter cannot go unnoticed.
#
# SkipFicCreation=true on every path: the default (false) makes the reuse path
# fail, which the parameter's own description admits. That is defect 3 in
# task_azure_0062 and it is not what these paths measure, so it is turned off
# here - a known-good carrier, so a failure means the guard.
set -uo pipefail

# No subscription or App Registration id is written down here. The active
# `az` context decides where this runs; TEST_SUBSCRIPTION only cross-checks it.
# APP is passed as EntraIdClientId and, with SkipFicCreation=true, is never
# resolved against the tenant - so the placeholder is enough. Set TEST_APP_ID
# to a real consented App Registration if you want the FIC counters to mean
# something.
SUB="$(az account show --query id -o tsv 2>/dev/null || true)"
if [ -z "$SUB" ]; then
    echo "ERROR: not logged in. Run: az login" >&2
    exit 1
fi
if [ -n "${TEST_SUBSCRIPTION:-}" ] && [ "$TEST_SUBSCRIPTION" != "$SUB" ]; then
    echo "ERROR: TEST_SUBSCRIPTION is $TEST_SUBSCRIPTION but the active context is" >&2
    echo "       $SUB. Run: az account set --subscription $TEST_SUBSCRIPTION" >&2
    exit 1
fi
LOC=${TEST_LOCATION:-northeurope}
APP=${TEST_APP_ID:-00000000-0000-0000-0000-000000000000}
TPL="$(cd "$(dirname "$0")/.." && pwd)/azuredeploy.json"
T=$(python3 -c "import uuid;print(uuid.uuid4().hex[:4])")

RG_A=rg-eid-paths-a-$T
RG_B=rg-eid-paths-b-$T
RG_C=rg-eid-paths-c-$T
RG_D=rg-eid-paths-d-$T
RG_W=rg-eid-paths-w-$T
WS_B=law-b-$T
WS_W=law-w-$T

pass=0; fail=0; skip=0
row() { # row <title> <expected> <actual>
    # An empty expectation compared against an empty reading passes while proving
    # nothing. Say SKIP and count it -- silence is not success.
    if [ -z "$2" ] || [ -z "$3" ]; then
        printf '  %-52s SKIP  not measured\n' "$1"; skip=$((skip+1)); return
    fi
    if [ "$2" = "$3" ]; then printf '  %-52s PASS  %s\n' "$1" "$3"; pass=$((pass+1))
    else printf '  %-52s FAIL  expected %s, got %s\n' "$1" "$2" "$3"; fail=$((fail+1)); fi
}
state() { az deployment group show -g "$1" -n "$2" --query properties.provisioningState -o tsv 2>/dev/null || echo NOTFOUND; }
count() { az resource list -g "$1" --query "length(@)" -o tsv 2>/dev/null || echo ERR; }
blame_detail() {
    az deployment operation group list -g "$1" -n "$2" \
        --query "[?properties.provisioningState=='Failed'].[properties.targetResource.resourceName,properties.statusMessage.error.code]|[0]" \
        -o tsv 2>/dev/null | tr '\t' ' '
}
guard_state() { state "$1" precheck-workspace-exists; }

fn_count() { # fn_count <rg>
    local rg=$1 app
    app=$(az functionapp list -g "$rg" --query "[0].name" -o tsv 2>/dev/null)
    if [ -z "$app" ]; then echo NOAPP; return; fi
    az functionapp function list -g "$rg" -n "$app" --query "length(@)" -o tsv 2>/dev/null || echo ERR
}

deploy() { # deploy <rg> <name> <extra params...>
    local rg=$1 name=$2; shift 2
    az deployment group create -g "$rg" -n "$name" --template-file "$TPL" --no-prompt \
      --parameters SocradarApiKey=placeholder-not-a-real-key SocradarCompanyId=1 \
                   WorkspaceLocation="$LOC" CreateAppRegistration=false \
                   EntraIdClientId="$APP" SkipFicCreation=true "$@" \
      -o none 2>"/tmp/eid-$name.err"
}

echo "[0/5] subscription: $SUB"
FIC0=$(az ad app federated-credential list --id "$APP" --query "length(@)" -o tsv 2>/dev/null)
APP0=$(az ad app list --filter "startswith(displayName,'SOCRadar')" --query "length(@)" -o tsv 2>/dev/null)
echo "      App Reg reused: $APP  FIC=$FIC0  SOCRadar App Regs=$APP0"

for r in $RG_A $RG_B $RG_C $RG_D $RG_W; do az group create -n $r -l $LOC -o none; done
az monitor log-analytics workspace create -g $RG_B -n $WS_B -l $LOC -o none 2>/dev/null
az monitor log-analytics workspace create -g $RG_W -n $WS_W -l $LOC -o none 2>/dev/null

echo "[1/5] Path A: the workspace does not exist"
deploy $RG_A path-a WorkspaceName=law-absent-$T CreateWorkspace=false
row "A fails" Failed "$(state $RG_A path-a)"
row "A leaves nothing behind" 0 "$(count $RG_A)"
case "$(blame_detail $RG_A path-a)" in
  *precheck-workspace-exists*) row "A is stopped by the guard" yes yes;;
  *) row "A is stopped by the guard" yes "no ($(blame_detail $RG_A path-a))";;
esac

echo "[2/5] Path B: an existing workspace in the same resource group"
deploy $RG_B path-b WorkspaceName=$WS_B CreateWorkspace=false
row "B succeeds" Succeeded "$(state $RG_B path-b)"
row "B ran the guard" Succeeded "$(guard_state $RG_B)"
row "B indexed its function" 1 "$(fn_count $RG_B)"

echo "[3/5] Path C: the default greenfield install"
deploy $RG_C path-c WorkspaceName=law-c-$T
row "C succeeds" Succeeded "$(state $RG_C path-c)"
row "C skips the guard (this deployment creates the workspace)" NOTFOUND "$(guard_state $RG_C)"

echo "[4/5] Path D: cross-resource-group"
deploy $RG_D path-d WorkspaceName=$WS_W WorkspaceResourceGroup=$RG_W
row "D succeeds" Succeeded "$(state $RG_D path-d)"
row "D ran the guard next to the workspace" Succeeded "$(guard_state $RG_W)"
row "D put the tables next to the workspace" 4 \
    "$(az monitor log-analytics workspace table list -g $RG_W --workspace-name $WS_W --query "length([?starts_with(name,'SOCRadar_')])" -o tsv 2>/dev/null || echo ERR)"
row "D indexed its function" 1 "$(fn_count $RG_D)"
row "D created no workspace in the deployment group" 0 \
    "$(az resource list -g $RG_D --resource-type Microsoft.OperationalInsights/workspaces --query "length(@)" -o tsv 2>/dev/null)"

echo "[5/5] Path E: redeploy over path B"
deploy $RG_B path-e WorkspaceName=$WS_B CreateWorkspace=false
row "E succeeds" Succeeded "$(state $RG_B path-e)"

FIC1=$(az ad app federated-credential list --id "$APP" --query "length(@)" -o tsv 2>/dev/null)
APP1=$(az ad app list --filter "startswith(displayName,'SOCRadar')" --query "length(@)" -o tsv 2>/dev/null)
row "no federated credential was added to the tenant" "$FIC0" "$FIC1"
row "no App Registration was created" "$APP0" "$APP1"

echo
echo "cleanup: delete queued for $RG_A $RG_B $RG_C $RG_D $RG_W"
for r in $RG_A $RG_B $RG_C $RG_D $RG_W; do az group delete -n $r --yes --no-wait -o none; done

echo "$pass passed, $fail failed, $skip skipped"
if [ "$skip" -gt 0 ]; then
    echo "NOTE: set TEST_APP_ID to a consented App Registration to measure the"
    echo "      federated-credential counters; with the placeholder they read empty."
fi
[ "$fail" -eq 0 ] || exit 1
echo "All five deployment paths behaved as asserted."
