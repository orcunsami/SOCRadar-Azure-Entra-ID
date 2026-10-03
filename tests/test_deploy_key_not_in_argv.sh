#!/usr/bin/env bash
# deploy.sh must not put SocradarApiKey in az's argv (visible in ps). Fake az logs argv;
# the key canary must be absent from argv and output, the param file 0600 and gone at exit.
# Then mutates deploy.sh back to the old argv form: the check must FAIL.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS="$HERE/../scripts"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
CANARY="canary-KEY-$RANDOM$RANDOM-zz"
mkdir "$T/bin"
cat > "$T/bin/az" <<'FAKE'
#!/usr/bin/env bash
printf '%s\n' "az $*" >> "$T/argv.log"
if [ "$1 $2 $3" = "deployment group create" ]; then
    for a in "$@"; do case "$a" in @*) f="${a#@}"
        echo "PERM=$(stat -c %a "$f") HASKEY=$(grep -c "$CANARY" "$f") FILE=$f" >> "$T/meta.log";; esac; done
    exit 99   # stop deploy.sh right after the deployment call
fi
echo fake
FAKE
chmod +x "$T/bin/az"

check() {  # check <deploy.sh path>; returns 0 if the key stayed out of argv
    rm -f "$T/argv.log" "$T/meta.log"; : > "$T/argv.log"
    ( export T CANARY PATH="$T/bin:$PATH" RESOURCE_GROUP=rg LOCATION=westeurope WORKSPACE_NAME=ws \
        SOCRADAR_API_KEY="$CANARY" SOCRADAR_COMPANY_ID=1 SOCRADAR_BASE_URL=https://x.invalid ENTRA_TENANT_ID=t ENTRA_CLIENT_ID=c
      bash -x "$1" ) > "$T/out.log" 2>&1
    local ok=0 f
    grep -q 'az deployment group create' "$T/argv.log" || { echo "  no deployment call seen"; return 1; }
    touch "$T/meta.log"
    grep -q "$CANARY" "$T/argv.log" && { echo "  canary in argv"; ok=1; }
    grep -q "$CANARY" "$T/out.log" && { echo "  canary in output"; ok=1; }
    grep -q 'PERM=600 HASKEY=1' "$T/meta.log" || { echo "  param file not 0600 with key"; ok=1; }
    grep -q -- '--parameters @' "$T/argv.log" || { echo "  no @file in argv"; ok=1; }
    f=$(sed 's/.*FILE=//' "$T/meta.log")
    [ -n "$f" ] && [ -e "$f" ] && { echo "  param file left behind"; ok=1; }
    [ -n "$f" ] && rm -f "$f"
    return $ok
}

fails=0
echo "real deploy.sh:"
check "$SCRIPTS/deploy.sh" && echo "  PASS" || { echo "  FAIL"; fails=1; }

mutant() {  # mutant <name> <sed expr>; the check must FAIL on the mutated copy
    local M="$SCRIPTS/.deploy.mut.$$.sh"
    sed "$2" "$SCRIPTS/deploy.sh" > "$M"
    if cmp -s "$M" "$SCRIPTS/deploy.sh"; then echo "mutant $1: mutation did not apply"; fails=1; rm -f "$M"; return; fi
    echo "mutant $1 (expected to FAIL):"
    check "$M"; local rc=$?; rm -f "$M"
    [ $rc -ne 0 ] && echo "  caught" || { echo "  NOT caught"; fails=1; }
}
mutant argv-form 's|--parameters @"\$PARAMS_FILE" \\|--parameters SocradarApiKey="$SOCRADAR_API_KEY" \\|'
mutant no-cleanup "/^trap 'rm -f/d"
exit $fails
