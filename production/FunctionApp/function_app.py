"""
SOCRadar Entra ID Integration — Azure Function App
Timer-triggered function that pulls leaked employee credentials from SOCRadar
and takes automated remediation actions in Microsoft Entra ID.

Sources:
  - Botnet Data v2
  - PII Exposure v2
  - VIP Protection v2 (UNVERIFIED — no official API docs)
"""

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

    return permissions


@app.timer_trigger(
    schedule="%POLLING_SCHEDULE%",
    arg_name="timer",
    run_on_startup=True
)
def socradar_entra_id_import(timer: func.TimerRequest) -> None:
    start_time = time.time()
    logger.info("=== SOCRadar Entra ID Integration started ===")

    if timer.past_due:
        logger.warning("Timer is past due, running anyway")

    conf = cfg.load()
    credential = DefaultAzureCredential()

    # Get Entra ID token once — shared across all sources
    graph_headers = None
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
            conf["enable_ropc"],
        )):
            logger.warning("[ENTRA] One or more Entra action toggles are enabled, but they cannot run while EnableUserLookup=false")
    else:
        try:
            graph_token = entra.get_graph_token(
                tenant_id=conf["tenant_id"],
                client_id=conf["client_id"],
                client_secret=conf["client_secret"]
            )
            graph_headers = {
                "Authorization": f"Bearer {graph_token}",
                "Content-Type": "application/json"
            }
        except Exception as e:
            logger.error("[ENTRA] Failed to acquire Graph token — Entra ID actions will be skipped: %s", e)

    sources_to_run = []
    if conf["enable_botnet_source"]:
        sources_to_run.append("botnet")
    if conf["enable_pii_source"]:
        sources_to_run.append("pii")
    if conf["enable_vip_source"]:
        logger.warning("[VIP] Source enabled — endpoint is UNVERIFIED (not in official API docs)")
        sources_to_run.append("vip")

    logger.info("Active sources: %s", sources_to_run)

    audit_results = []

    for source_name in sources_to_run:
        src_start = time.time()
        try:
            result = _process_source(
                source_name=source_name,
                conf=conf,
                credential=credential,
                graph_headers=graph_headers
            )
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
            errors=r["errors"], duration_sec=r.get("duration", 0)
        )

    if conf["workspace_id"] and conf["workspace_key"]:
        law.write_audit(conf, audit_results)

    total_duration = round(time.time() - start_time, 1)
    logger.info("=== SOCRadar Entra ID Integration finished in %.1fs ===", total_duration)


def _process_source(source_name: str, conf: dict, credential, graph_headers: dict) -> dict:
    """Fetch one source, process each employee credential, return audit dict."""

    chk = cp.load(conf["storage_account_name"], credential, source_name)

    # Fetch employees from source
    if source_name == "botnet":
        employees = src_botnet.fetch(conf, chk)
    elif source_name == "pii":
        employees = src_pii.fetch(conf, chk)
    elif source_name == "vip":
        employees = src_vip.fetch(conf, chk)
    else:
        return {"source": source_name, "total": 0, "employees": 0,
                "found": 0, "not_found": 0, "actions": 0, "errors": 0, "duration": 0}

    found = not_found = actions = errors = 0
    records = []
    graph_disabled = graph_headers is None
    consecutive_403 = 0

    # Extract checkpoint before the loop — it sits on the last record and
    # will be popped from emp before appending to LAW records below.
    new_checkpoint = employees[-1].get("_checkpoint_update", {}) if employees else {}

    for emp in employees:
        try:
            email = emp.get("email") or emp.get("user", "")
            if not email:
                continue

            # User lookup in Entra ID (skipped if Graph token unavailable or permissions missing)
            if not conf["enable_user_lookup"]:
                emp["entra_status"] = "skipped_user_lookup_disabled"
                emp["actions_taken"] = []
                emp.pop("_checkpoint_update", None)
                records.append(emp)
                continue

            if graph_disabled:
                emp["entra_status"] = "skipped_no_token"
                emp["actions_taken"] = []
                emp.pop("_checkpoint_update", None)
                records.append(emp)
                continue

            user_info = entra.lookup_user(email, graph_headers)

            # Detect permission denied — stop wasting API calls
            if user_info is None and hasattr(entra, '_last_status') and entra._last_status == 403:
                consecutive_403 += 1
                if consecutive_403 >= 3:
                    logger.warning("[%s] 3 consecutive 403s — disabling Graph lookups for this run (admin consent needed)",
                                   source_name.upper())
                    graph_disabled = True
                    emp["entra_status"] = "skipped_no_permission"
                    emp["actions_taken"] = []
                    emp.pop("_checkpoint_update", None)
                    records.append(emp)
                    continue
            else:
                consecutive_403 = 0

            if user_info is None:
                not_found += 1
                emp["entra_status"] = "not_found"
                emp["actions_taken"] = []
                emp.pop("_checkpoint_update", None)
                records.append(emp)
                continue

            found += 1
            emp["entra_status"] = "found"
            emp["entra_account_enabled"] = user_info.get("accountEnabled", True)
            emp["entra_user_id"] = user_info.get("id", "")

            # ROPC validation (only if plaintext password available)
            ropc_result = None
            if conf["enable_ropc"] and emp.get("sanitized", {}).get("is_plaintext"):
                raw_pw = emp.get("sanitized", {}).get("_raw")
                if raw_pw:
                    ropc_result = entra.validate_password_ropc(
                        email=email,
                        password=raw_pw,
                        tenant_id=conf["tenant_id"],
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

            if conf["enable_create_incident"]:
                sent.create_incident(conf, email, source_name, emp.get("severity", "MEDIUM"))

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

    duration = 0  # caller sets this
    return {
        "source":     source_name,
        "total":      len(employees),
        "employees":  len([e for e in employees if e.get("is_employee", True)]),
        "found":      found,
        "not_found":  not_found,
        "actions":    actions,
        "errors":     errors,
        "duration":   duration,
    }
