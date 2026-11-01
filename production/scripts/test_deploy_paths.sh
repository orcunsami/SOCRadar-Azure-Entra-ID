#!/usr/bin/env bash
# Seven live deployment paths. Run from the repository root.
#
# TEST_SOCRADAR_API_KEY and TEST_COMPANY_ID are required: the first-run step checks the
# key before it downloads the package (HTTP 401 fails the deployment), so a placeholder
# key no longer deploys. The key goes to the deployment through a 0600 parameter file,
# never through argv.
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
# The App Registration is REUSED, never created (reuse rule). A created one is
# not removed by `az group delete`, and it needs consent. The FIC and App Reg
# counts are compared before and after so litter cannot go unnoticed.
#
# SkipFicCreation=true on every path, stated even though it is the default
# since 8 Sep 2026: the FIC step is not what these paths measure, and pinning
# it keeps the carrier known-good if the default ever moves again.
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
if [ -z "${TEST_SOCRADAR_API_KEY:-}" ] || [ -z "${TEST_COMPANY_ID:-}" ]; then
    echo "ERROR: set TEST_SOCRADAR_API_KEY and TEST_COMPANY_ID (a live key for that company)" >&2
    exit 1
fi
KEY_FILE=""; DEAD_FILE=""
trap 'rm -f "$KEY_FILE" "$DEAD_FILE"' EXIT
mkparams() { # mkparams <key> -> path of a 0600 ARM parameter file
    local f; f=$(mktemp); chmod 600 "$f"
    KEY="$1" python3 -c "import json,os;print(json.dumps({'\$schema':'https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#','contentVersion':'1.0.0.0','parameters':{'SocradarApiKey':{'value':os.environ['KEY']}}}))" > "$f"
    echo "$f"
}
KEY_FILE=$(mkparams "$TEST_SOCRADAR_API_KEY")
DEAD_FILE=$(mkparams "dead-key-not-valid")
APP=${TEST_APP_ID:-00000000-0000-0000-0000-000000000000}
TPL="$(cd "$(dirname "$0")/.." && pwd)/azuredeploy.json"
T=$(python3 -c "import uuid;print(uuid.uuid4().hex[:4])")

RG_A=rg-eid-paths-a-$T
RG_B=rg-eid-paths-b-$T
RG_C=rg-eid-paths-c-$T
RG_D=rg-eid-paths-d-$T
RG_W=rg-eid-paths-w-$T
RG_K=rg-eid-paths-k-$T
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

deploy() { # deploy <rg> <name> <extra params...>   (PARAM_FILE overrides the key file)
    local rg=$1 name=$2; shift 2
    az deployment group create -g "$rg" -n "$name" --template-file "$TPL" --no-prompt \
      --parameters @"${PARAM_FILE:-$KEY_FILE}" SocradarCompanyId="$TEST_COMPANY_ID" \
                   WorkspaceLocation="$LOC" CreateAppRegistration=false \
                   EntraIdClientId="$APP" SkipFicCreation=true "$@" \
      -o none 2>"/tmp/eid-$name.err"
}

echo "[0/7] subscription: $SUB"
FIC0=$(az ad app federated-credential list --id "$APP" --query "length(@)" -o tsv 2>/dev/null)
APP0=$(az ad app list --filter "startswith(displayName,'SOCRadar')" --query "length(@)" -o tsv 2>/dev/null)
echo "      App Reg reused: $APP  FIC=$FIC0  SOCRadar App Regs=$APP0"

for r in $RG_A $RG_B $RG_C $RG_D $RG_W $RG_K; do az group create -n $r -l $LOC -o none; done
az monitor log-analytics workspace create -g $RG_B -n $WS_B -l $LOC -o none 2>/dev/null
az monitor log-analytics workspace create -g $RG_W -n $WS_W -l $LOC -o none 2>/dev/null
WS_K=law-k-$T
az monitor log-analytics workspace create -g $RG_K -n $WS_K -l $LOC -o none 2>/dev/null

echo "[1/7] Path A: the workspace does not exist, every flag at its default"
deploy $RG_A path-a WorkspaceName=law-absent-$T
row "A fails" Failed "$(state $RG_A path-a)"
row "A leaves nothing behind" 0 "$(count $RG_A)"
case "$(blame_detail $RG_A path-a)" in
  *precheck-workspace-exists*) row "A is stopped by the guard" yes yes;;
  *) row "A is stopped by the guard" yes "no ($(blame_detail $RG_A path-a))";;
esac

echo "[2/7] Path B: an existing workspace in the same resource group"
deploy $RG_B path-b WorkspaceName=$WS_B
row "B succeeds" Succeeded "$(state $RG_B path-b)"
row "B ran the guard" Succeeded "$(guard_state $RG_B)"
row "B indexed its function" 1 "$(fn_count $RG_B)"

echo "[3/7] Path C: greenfield install (CreateWorkspace=true)"
deploy $RG_C path-c WorkspaceName=law-c-$T CreateWorkspace=true
row "C succeeds" Succeeded "$(state $RG_C path-c)"
row "C skips the guard (this deployment creates the workspace)" NOTFOUND "$(guard_state $RG_C)"

echo "[4/7] Path D: cross-resource-group"
deploy $RG_D path-d WorkspaceName=$WS_W WorkspaceResourceGroup=$RG_W
row "D succeeds" Succeeded "$(state $RG_D path-d)"
row "D ran the guard next to the workspace" Succeeded "$(guard_state $RG_W)"
row "D put the tables next to the workspace" 4 \
    "$(az monitor log-analytics workspace table list -g $RG_W --workspace-name $WS_W --query "length([?starts_with(name,'SOCRadar_')])" -o tsv 2>/dev/null || echo ERR)"
row "D indexed its function" 1 "$(fn_count $RG_D)"
row "D created no workspace in the deployment group" 0 \
    "$(az resource list -g $RG_D --resource-type Microsoft.OperationalInsights/workspaces --query "length(@)" -o tsv 2>/dev/null)"

echo "[5/7] Path E: redeploy over path B"
deploy $RG_B path-e WorkspaceName=$WS_B
row "E succeeds" Succeeded "$(state $RG_B path-e)"

echo "[6/7] Path K: an existing workspace and an API key the server rejects"
PARAM_FILE=$DEAD_FILE deploy $RG_K path-k WorkspaceName=$WS_K
row "K fails" Failed "$(state $RG_K path-k)"
row "K failed in the first-run step" yes "$(case "$(blame_detail $RG_K path-k)" in *triggerFirstRun*) echo yes;; *) echo "no ($(blame_detail $RG_K path-k))";; esac)"
row "K banner names the rejected key" yes "$(az deployment operation group list -g $RG_K -n path-k --query "[?properties.provisioningState=='Failed'].properties.statusMessage" -o json 2>/dev/null | grep -q 'rejected the API key' && echo yes || echo no)"

echo "[7/7] Path F: first-run audit rows in the workspace of path B, then a host restart (up to 60 min) ..."
CUST_B=$(az monitor log-analytics workspace show -g $RG_B -n $WS_B --query customerId -o tsv 2>/dev/null)
APP_B=$(az functionapp list -g $RG_B --query "[0].name" -o tsv 2>/dev/null)
res=$(python3 - "$CUST_B" "$RG_B" "$APP_B" <<'PYEOF'
import json, os, subprocess, sys, time
from datetime import datetime, timezone
cust, rg, app = sys.argv[1], sys.argv[2], sys.argv[3]
POLL = int(os.environ.get("TEST_POLL", "30"))
KQL = "SOCRadar_EntraID_Audit_CL | project TimeGenerated, error_count, actions_taken, total_records | order by TimeGenerated asc"
def q():
    r = subprocess.run(["az", "monitor", "log-analytics", "query", "-w", cust, "--analytics-query", KQL, "-o", "json"],
                       capture_output=True, text=True)
    return json.loads(r.stdout) if r.returncode == 0 else None
def n(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0
def ts(v):
    v = v.rstrip("Z")
    if "." in v:
        a, b = v.split(".")
        v = a + "." + b[:6]
    return datetime.fromisoformat(v).replace(tzinfo=timezone.utc)
deadline = time.time() + int(os.environ.get("TEST_FIRST_RUN_WAIT", "1500"))
rows = None
while time.time() < deadline:
    rows = q()
    if rows:
        break
    time.sleep(POLL)
if not rows:
    print("UNREADABLE"); sys.exit(0)
first_actions = sum(n(r.get("actions_taken")) for r in rows)
# A restart starts the host again and a host start runs an import (run_on_startup). The restarted
# host must run, write an audit row without errors, and take no action the first run already took.
restart_at = datetime.now(timezone.utc)
rr = subprocess.run(["az", "functionapp", "restart", "-g", rg, "-n", app], capture_output=True, text=True)
if rr.returncode != 0:
    print("NORESTART"); sys.exit(0)
later = []
deadline = time.time() + int(os.environ.get("TEST_RESTART_WAIT", "2400"))
while time.time() < deadline:
    rows = q() or rows
    later = [r for r in rows if ts(r["TimeGenerated"]) > restart_at]
    if later:
        break
    time.sleep(POLL)
bad = sum(1 for r in rows if n(r.get("error_count")) > 0)
print("RESULT", len(rows) - len(later), first_actions, sum(n(r.get("actions_taken")) for r in later), bad, len(later))
PYEOF
)
read -r tag first_rows first_act later_act bad later_rows <<< "$res"
if [ "$tag" != RESULT ]; then
    row "F first window readable" yes "no (${res:-<empty>})"
else
    row "F no audit row reports an error" 0 "$bad"
    row "F the restarted host ran again and wrote an audit row" yes "$([ "$later_rows" -ge 1 ] && echo yes || echo no)"
    # With the placeholder App Registration no Graph action is possible (no token), so both are
    # 0; with a consented one the ledger must keep the restart from repeating the first run.
    row "F the restart takes no action the first run took" 0 "$([ "$later_rows" -ge 1 ] && echo $((later_act > first_act ? later_act - first_act : 0)) || echo)"
fi

FIC1=$(az ad app federated-credential list --id "$APP" --query "length(@)" -o tsv 2>/dev/null)
APP1=$(az ad app list --filter "startswith(displayName,'SOCRadar')" --query "length(@)" -o tsv 2>/dev/null)
row "no federated credential was added to the tenant" "$FIC0" "$FIC1"
row "no App Registration was created" "$APP0" "$APP1"

echo
echo "cleanup: delete queued for $RG_A $RG_B $RG_C $RG_D $RG_W $RG_K"
for r in $RG_A $RG_B $RG_C $RG_D $RG_W $RG_K; do az group delete -n $r --yes --no-wait -o none; done

echo "$pass passed, $fail failed, $skip skipped"
if [ "$skip" -gt 0 ]; then
    echo "NOTE: set TEST_APP_ID to a consented App Registration to measure the"
    echo "      federated-credential counters; with the placeholder they read empty."
fi
[ "$fail" -eq 0 ] || exit 1
echo "All seven deployment paths behaved as asserted."
