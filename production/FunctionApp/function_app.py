"""
SOCRadar Entra ID Integration — Azure Function App
Timer-triggered function that pulls leaked employee credentials from SOCRadar
and takes automated remediation actions in Microsoft Entra ID.

Sources:
  - Botnet Data v2
  - PII Exposure v2
  - VIP Protection v2
"""

import os
import time
import logging
import azure.functions as func
from azure.identity import DefaultAzureCredential

from utils import config as cfg
from utils import checkpoint as cp
from utils.logger import audit_summary

from sources import botnet as src_botnet
from sources import pii as src_pii
from sources import vip as src_vip

from actions import entra_id as entra
from actions import law_writer as law
from actions import sentinel as sent
from actions import socradar as socradar_api

logger = logging.getLogger(__name__)
app = func.FunctionApp()

# Time budget per run. Function timeout is 10 min (Y1 Consumption hard cap).
# Leave ~2 min headroom for cleanup (LAW write + checkpoint save).
TIME_BUDGET_SECONDS = 8 * 60

# Honour RUN_ON_STARTUP env var (ARM parameter). Default true.
_RUN_ON_STARTUP = os.environ.get("RUN_ON_STARTUP", "true").strip().lower() in ("true", "1", "yes")


def _required_graph_permissions(conf: dict) -> list[tuple[str, str]]:
    """Return the Graph application permissions implied by the current config."""
    permissions = []

    if conf["enable_user_lookup"]:
        permissions.append(("User.Read.All", "look up leaked identities in Entra ID"))
    if conf["enable_revoke_session"]:
        permissions.append(("User.RevokeSessions.All", "revoke active user sessions"))
    if conf["enable_add_to_group"] or conf["enable_remove_from_group"]:
        permissions.append(("GroupMember.ReadWrite.All", "add or remove users from a security group"))
    if conf["enable_password_change"]:
        permissions.append(("User-PasswordProfile.ReadWrite.All", "force password change at next sign-in"))
    if conf["enable_disable_account"] or conf["enable_enable_account"]:
        permissions.append(("User.EnableDisableAccount.All", "disable or re-enable user accounts"))
    if conf["enable_confirm_risky"]:
        permissions.append(("IdentityRiskyUser.ReadWrite.All", "confirm compromised users in Identity Protection"))
    if conf["enable_force_mfa_reregistration"]:
        permissions.append(("UserAuthenticationMethod.ReadWrite.All", "delete MFA methods to force re-registration"))

    return permissions


@app.timer_trigger(
    schedule="%POLLING_SCHEDULE%",
    arg_name="timer",
    run_on_startup=_RUN_ON_STARTUP
)
def socradar_entra_id_import(timer: func.TimerRequest) -> None:
    start_time = time.time()
    logger.info("=== SOCRadar Entra ID Integration started ===")

    if timer.past_due:
        logger.warning("Timer is past due, running anyway")

    conf = cfg.load()
    credential = DefaultAzureCredential()

    # Get Entra ID tokens — one per configured tenant. The first tenant in the
    # list owns the multi-tenant App Registration + FIC; the others are
    # consented by their admins so a service principal exists for our app_id
    # in each tenant. lookup_user() will try tenants in order, first match wins.
    tenant_headers_map = {}  # ordered dict: tenant_id -> graph_headers
    tenants = cfg.resolve_tenants(conf)

    for permission, reason in _required_graph_permissions(conf):
        logger.info("[ENTRA] Config requires %s — %s", permission, reason)

    if conf["enable_confirm_risky"]:
        logger.info("[ENTRA] EnableConfirmRisky also requires Entra ID P1/P2 licensing")

    if not conf["enable_user_lookup"]:
        logger.warning("[ENTRA] EnableUserLookup=false — User.Read.All is optional, but Entra lookup and all Entra-targeted actions will be skipped")
        if any((
            conf["enable_revoke_session"],
            conf["enable_add_to_group"],
            conf["enable_remove_from_group"],
            conf["enable_password_change"],
            conf["enable_disable_account"],
            conf["enable_enable_account"],
            conf["enable_confirm_risky"],
            conf["enable_force_mfa_reregistration"],
            conf["enable_ropc"],
        )):
            logger.warning("[ENTRA] One or more Entra action toggles are enabled, but they cannot run while EnableUserLookup=false")
    else:
        logger.info("[ENTRA] Multi-tenant lookup configured for %d tenant(s): %s",
                    len(tenants), ", ".join(tenants))
        for tenant_id in tenants:
            try:
                graph_token = entra.get_graph_token(
                    tenant_id=tenant_id,
                    client_id=conf["client_id"]
                )
                tenant_headers_map[tenant_id] = {
                    "Authorization": f"Bearer {graph_token}",
                    "Content-Type": "application/json"
                }
            except entra.ConsentRevokedError as e:
                logger.error(
                    "[ENTRA] Consent issue for tenant %s (%s): %s — this tenant will be skipped",
                    e.tenant_id, e.aadsts_code, e
                )
                law.write_lifecycle_event(
                    conf,
                    event_type="consent_revoked",
                    tenant_id=e.tenant_id,
                    details=str(e),
                    extra={"aadsts_code": e.aadsts_code}
                )
            except Exception as e:
                logger.error("[ENTRA] Failed to acquire Graph token for tenant %s — this tenant will be skipped: %s",
                             tenant_id, e)
                law.write_lifecycle_event(
                    conf,
                    event_type="token_acquisition_failed",
                    tenant_id=tenant_id,
                    details=str(e)[:500]
                )

        if not tenant_headers_map:
            logger.error("[ENTRA] No tenant produced a usable token — all Entra ID actions will be skipped this run")

    sources_to_run = []
    if conf["enable_botnet_source"]:
        sources_to_run.append("botnet")
    if conf["enable_pii_source"]:
        sources_to_run.append("pii")
    if conf["enable_vip_source"]:
        logger.info("[VIP] Source enabled")
        sources_to_run.append("vip")

    logger.info("Active sources: %s", sources_to_run)

    audit_results = []

    for source_name in sources_to_run:
        # Per-source time budget gate. If function-level elapsed time already
        # exceeded the budget, skip remaining sources so cleanup (LAW write,
        # checkpoint save) can finish within the 10 min function timeout.
        if time.time() - start_time > TIME_BUDGET_SECONDS:
            logger.warning(
                "[%s] Skipped — function time budget (%ds) exhausted before source ran. Will run next timer cycle.",
                source_name.upper(), TIME_BUDGET_SECONDS
            )
            audit_results.append({
                "source": source_name, "total": 0, "employees": 0,
                "found": 0, "not_found": 0, "actions": 0, "errors": 0,
                "duration": 0.0
            })
            continue

        src_start = time.time()
        try:
            result = _process_source(
                source_name=source_name,
                conf=conf,
                credential=credential,
                tenant_headers_map=tenant_headers_map,
                function_start_time=start_time
            )
            result["duration"] = round(time.time() - src_start, 1)
            audit_results.append(result)
        except Exception as e:
            logger.error("[%s] Unhandled error: %s", source_name.upper(), e, exc_info=True)
            audit_results.append({
                "source": source_name, "total": 0, "employees": 0,
                "found": 0, "not_found": 0, "actions": 0, "errors": 1,
                "duration": round(time.time() - src_start, 1)
            })

    # Write audit log
    for r in audit_results:
        audit_summary(
            source=r["source"], total=r["total"], employees=r["employees"],
            found=r["found"], not_found=r["not_found"], actions=r["actions"],
            errors=r["errors"], duration_sec=r.get("duration", 0),
            domain_filtered=r.get("domain_filtered", 0),
        )

    if conf.get("dcr_immutable_id") and conf.get("dcr_endpoint"):
        law.write_audit(conf, audit_results)

    total_duration = round(time.time() - start_time, 1)
    logger.info("=== SOCRadar Entra ID Integration finished in %.1fs ===", total_duration)


def _process_source(source_name: str, conf: dict, credential, tenant_headers_map: dict,
                    function_start_time: float) -> dict:
    """Fetch one source, process each employee credential, return audit dict.

    `tenant_headers_map` is an ordered dict {tenant_id: graph_headers}. For each
    employee, lookup_user is tried against each tenant in order; first match wins
    and all subsequent actions run against that tenant's headers. The tenant in
    which the user was found is recorded as `entra_tenant_id` on the record.

    `function_start_time` is the function invocation start time (used for the
    per-employee time budget check — exits gracefully before function timeout).
    """

    chk = cp.load(conf["storage_account_name"], credential, source_name)

    # Fetch employees from source
    if source_name == "botnet":
        employees = src_botnet.fetch(conf, chk)
    elif source_name == "pii":
        employees = src_pii.fetch(conf, chk)
    elif source_name == "vip":
        employees = src_vip.fetch(conf, chk)
    else:
        # Duration is set by the caller.
        return {"source": source_name, "total": 0, "employees": 0,
                "found": 0, "not_found": 0, "actions": 0, "errors": 0}

    found = not_found = actions = errors = domain_filtered = 0
    records = []
    # Per-tenant 403 counter: if a tenant returns 403 three times in a row,
    # drop it from the lookup map (admin consent missing — no point retrying).
    # Healthy tenants in the same map continue to function.
    tenant_403_counts = {tid: 0 for tid in tenant_headers_map}

    # Extract checkpoint before the loop — it sits on the last record and
    # will be popped from emp before appending to LAW records below.
    new_checkpoint = employees[-1].get("_checkpoint_update", {}) if employees else {}

    for emp in employees:
        # Per-employee time budget check — graceful exit so LAW write +
        # checkpoint save finish within the 10 min function timeout.
        if time.time() - function_start_time > TIME_BUDGET_SECONDS:
            logger.warning(
                "[%s] Time budget (%ds) exhausted mid-source. Stopping early — %d records processed so far. Remaining will resume next run.",
                source_name.upper(), TIME_BUDGET_SECONDS, len(records)
            )
            break

        try:
            email = emp.get("email") or emp.get("user", "")
            if not email:
                continue

            # User lookup in Entra ID (skipped if Graph token unavailable or permissions missing)
            if not conf["enable_user_lookup"]:
                emp["entra_status"] = "skipped_user_lookup_disabled"
                emp["entra_tenant_id"] = ""
                emp["actions_taken"] = []
                emp.pop("_checkpoint_update", None)
                records.append(emp)
                continue

            if not tenant_headers_map:
                emp["entra_status"] = "skipped_no_token"
                emp["entra_tenant_id"] = ""
                emp["actions_taken"] = []
                emp.pop("_checkpoint_update", None)
                records.append(emp)
                continue

            # Verified-domain allowlist gate. Applied before the per-tenant lookup
            # loop so we save Graph quota on every non-matching tenant, not just
            # the first. Empty allowlist disables filtering (backward compat).
            allow_domains = conf.get("verified_domains", [])
            if allow_domains:
                _, _, email_domain = email.partition("@")
                if not email_domain or email_domain.lower() not in allow_domains:
                    domain_filtered += 1
                    emp["entra_status"] = "skipped_domain_allowlist"
                    emp["entra_tenant_id"] = ""
                    emp["actions_taken"] = []
                    emp.pop("_checkpoint_update", None)
                    records.append(emp)
                    continue

            # Multi-tenant lookup: try each tenant in order, first match wins.
            # Track per-lookup whether any tenant returned 403 — distinguishes
            # genuine "not found" from "permission denied silently turned into 404".
            user_info = None
            lookup_status = None
            found_tenant = None
            seen_403_this_lookup = False
            for tenant_id in list(tenant_headers_map.keys()):
                headers = tenant_headers_map[tenant_id]
                u, status = entra.lookup_user(email, headers)
                if u is not None:
                    user_info = u
                    lookup_status = status
                    found_tenant = tenant_id
                    tenant_403_counts[tenant_id] = 0  # reset on any success
                    break
                if status == 403:
                    seen_403_this_lookup = True
                    tenant_403_counts[tenant_id] = tenant_403_counts.get(tenant_id, 0) + 1
                    if tenant_403_counts[tenant_id] >= 3:
                        logger.warning(
                            "[%s] Tenant %s returned 3 consecutive 403s — dropping from lookup map (admin consent likely missing)",
                            source_name.upper(), tenant_id
                        )
                        tenant_headers_map.pop(tenant_id, None)
                else:
                    # Non-403 miss (e.g. 404 not_found): tenant is healthy.
                    tenant_403_counts[tenant_id] = 0
                lookup_status = status  # last seen status

            # Fully exhausted lookup map (all tenants 403'd out mid-loop)
            if not tenant_headers_map and user_info is None:
                errors += 1
                logger.warning(
                    "[%s] %s → all tenants exhausted permission errors (403). Marking as lookup_permission_denied. Admin consent likely missing.",
                    source_name.upper(), email
                )
                emp["entra_status"] = "lookup_permission_denied"
                emp["entra_tenant_id"] = ""
                emp["actions_taken"] = []
                emp.pop("_checkpoint_update", None)
                records.append(emp)
                continue

            if user_info is None:
                if seen_403_this_lookup:
                    # User wasn't found in any tenant but at least one tenant returned 403.
                    # Treat as permission denied, not "not_found" — prevents silent false negatives
                    # when admin consent has not yet been granted on Path 1.
                    errors += 1
                    logger.warning(
                        "[%s] %s → lookup returned 403 (no 200/404 from any tenant). entra_status=lookup_permission_denied",
                        source_name.upper(), email
                    )
                    emp["entra_status"] = "lookup_permission_denied"
                else:
                    not_found += 1
                    emp["entra_status"] = "not_found"
                emp["entra_tenant_id"] = ""
                emp["actions_taken"] = []
                emp.pop("_checkpoint_update", None)
                records.append(emp)
                continue

            found += 1
            emp["entra_status"] = "found"
            emp["entra_tenant_id"] = found_tenant
            emp["entra_account_enabled"] = user_info.get("accountEnabled", True)
            emp["entra_user_id"] = user_info.get("id", "")

            # All subsequent actions use the headers of the tenant where the user was found.
            graph_headers = tenant_headers_map[found_tenant]

            # ROPC validation (only if plaintext password available)
            ropc_result = None
            if conf["enable_ropc"] and emp.get("sanitized", {}).get("is_plaintext"):
                raw_pw = emp.get("sanitized", {}).get("_raw")
                if raw_pw:
                    ropc_result = entra.validate_password_ropc(
                        email=email,
                        password=raw_pw,
                        tenant_id=found_tenant,
                        client_id=conf["client_id"]
                    )
                    del raw_pw  # remove from local scope immediately

            if ropc_result == "valid":
                emp["entra_status"] = "compromised"
                emp["severity"] = "CRITICAL"
            elif ropc_result in ("invalid", "mfa_blocked"):
                emp["severity"] = "MEDIUM"
            else:
                emp["severity"] = "MEDIUM"  # default

            # Take actions
            taken = []
            user_id = emp["entra_user_id"]

            if conf["enable_revoke_session"]:
                ok = entra.revoke_sessions(user_id, graph_headers)
                taken.append("revoke_session" if ok else "revoke_session_failed")
                actions += 1

            if conf["enable_add_to_group"] and conf["security_group_id"]:
                ok = entra.add_to_group(user_id, conf["security_group_id"], graph_headers)
                taken.append("add_to_group" if ok else "add_to_group_failed")
                actions += 1

            if conf["enable_remove_from_group"] and conf["security_group_id"]:
                ok = entra.remove_from_group(user_id, conf["security_group_id"], graph_headers)
                taken.append("remove_from_group" if ok else "remove_from_group_failed")
                actions += 1

            if conf["enable_disable_account"]:
                ok = entra.disable_account(user_id, graph_headers)
                taken.append("disable_account" if ok else "disable_account_failed")
                actions += 1

            if conf["enable_enable_account"]:
                ok = entra.enable_account(user_id, graph_headers)
                taken.append("enable_account" if ok else "enable_account_failed")
                actions += 1

            if conf["enable_password_change"]:
                ok = entra.force_password_change(user_id, graph_headers)
                taken.append("force_password_change" if ok else "force_password_change_failed")
                actions += 1

            if conf["enable_confirm_risky"]:
                ok = entra.confirm_compromised(user_id, graph_headers)
                taken.append("confirm_risky" if ok else "confirm_risky_failed")
                actions += 1

            if conf["enable_force_mfa_reregistration"]:
                mfa_result = entra.force_mfa_reregistration(user_id, graph_headers)
                if mfa_result["permission_denied"]:
                    logger.warning(
                        "[%s] force_mfa_rereg skipped — UserAuthenticationMethod.ReadWrite.All not granted",
                        source_name.upper()
                    )
                    taken.append("force_mfa_rereg_no_permission")
                elif mfa_result["methods_deleted"] > 0:
                    taken.append("force_mfa_rereg")
                elif mfa_result.get("errors"):
                    taken.append("force_mfa_rereg_failed")
                else:
                    # No MFA methods to delete (user only has password method)
                    taken.append("force_mfa_rereg_no_methods")
                emp["mfa_methods_deleted"] = mfa_result["methods_deleted"]
                emp["mfa_methods_skipped"] = mfa_result["methods_skipped"]
                actions += 1

            if conf["enable_create_incident"]:
                sent.create_incident(conf, email, source_name, emp.get("severity", "MEDIUM"), credential=credential)

            # Resolve SOCRadar alarm if user found in Entra ID
            alarm_id = emp.get("alarm_id")
            if conf.get("enable_resolve_alarm") and alarm_id:
                ok = socradar_api.resolve_alarm(
                    api_key=conf["socradar_api_key"],
                    company_id=conf["socradar_company_id"],
                    alarm_id=alarm_id,
                    comment=f"User {email} found in Entra ID — auto-resolved by SOCRadar Entra ID Integration",
                    base_url=conf.get("socradar_base_url", "https://platform.socradar.com")
                )
                taken.append("resolve_alarm" if ok else "resolve_alarm_failed")
                actions += 1

            emp["actions_taken"] = taken
            emp.pop("_checkpoint_update", None)  # internal key — must not reach LAW
            records.append(emp)

        except Exception as e:
            logger.error("[%s] Error processing %s: %s", source_name.upper(), emp.get("email", "?"), e)
            errors += 1

    # Write source records to LAW (skip empty marker records)
    real_records = [r for r in records if not r.get("_empty_marker")]
    if real_records:
        law.write_records(conf, source_name, real_records)

    # Update checkpoint (extracted before the loop above)
    if new_checkpoint:
        cp.save(conf["storage_account_name"], credential, source_name, new_checkpoint)

    # Duration is set by the caller (socradar_entra_id_import) after this returns,
    # so it always reflects real wall-clock time. Not included here to avoid a
    # silent-zero trap if a future caller forgets to overwrite it.
    return {
        "source":     source_name,
        "total":      len(employees),
        "employees":  len([e for e in employees if e.get("is_employee", True)]),
        "found":      found,
        "not_found":  not_found,
        "actions":    actions,
        "errors":     errors,
        "domain_filtered": domain_filtered,
    }
