"""
Configuration loader — reads all settings from Azure App Settings (environment variables).
Validates required fields and provides typed accessors.
"""

import logging
import os

_logger = logging.getLogger("socradar.entra.config")


def _get(key: str, default=None, required: bool = False):
    val = os.environ.get(key, default)
    if required and not val:
        raise EnvironmentError(f"Required App Setting missing: {key}")
    return val


def _bool(key: str, default: bool = False) -> bool:
    raw = os.environ.get(key, "")
    val = raw.strip().lower()
    if val in ("true", "1", "yes", "on"):
        return True
    if val in ("false", "0", "no", "off"):
        return False
    if val:
        # Several of these switches arm directory mutations and default to on.
        # A value we do not recognise used to fall through to that default, so
        # "ENABLE_REVOKE_SESSION=disabled" left the action ARMED with only the
        # operator's intention to say otherwise. Between the two wrong guesses
        # only one changes somebody's directory: an unrecognised value now
        # reads as False.
        _logger.error(
            "App Setting %s has an unrecognised value %r; treating it as "
            "false. Use true or false.", key, raw.strip())
        return False
    return default


def _int(key: str, default: int = 0, on_invalid: int = None) -> int:
    """on_invalid: what an unparseable value becomes. Ceilings should pass 0
    so that a typo in a limit closes the gate rather than silently restoring
    the default."""
    raw = os.environ.get(key, "")
    if not raw.strip():
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        fallback = default if on_invalid is None else on_invalid
        _logger.error(
            "App Setting %s has a non-numeric value %r; using %d.",
            key, raw.strip(), fallback)
        return fallback


def _list(key: str, default: str = "") -> list:
    """Parse a comma-separated env value into a list of stripped non-empty strings."""
    raw = os.environ.get(key, default).strip()
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def resolve_tenants(conf: dict) -> list:
    """Return ordered list of tenant IDs to query for Graph lookups.

    Priority:
      1. ENTRA_TENANT_IDS (CSV)       — multi-tenant mode
      2. ENTRA_TENANT_ID (single)     — single-tenant backward compat
      3. []                           — Graph lookups disabled
    """
    if conf.get("tenant_ids"):
        return list(conf["tenant_ids"])
    if conf.get("tenant_id"):
        return [conf["tenant_id"]]
    return []


def load() -> dict:
    """Load and validate all configuration. Raises EnvironmentError on missing required settings."""
    user_lookup = _bool("ENABLE_USER_LOOKUP", True)

    # Validate tenant config when user_lookup is enabled: at least one of
    # ENTRA_TENANT_IDS (CSV) or ENTRA_TENANT_ID (single) must be set.
    if user_lookup:
        tenant_ids_raw = os.environ.get("ENTRA_TENANT_IDS", "").strip()
        tenant_id_raw = os.environ.get("ENTRA_TENANT_ID", "").strip()
        if not tenant_ids_raw and not tenant_id_raw:
            raise EnvironmentError(
                "Required App Setting missing: ENTRA_TENANT_IDS (or legacy ENTRA_TENANT_ID)"
            )

    return {
        # SOCRadar API
        "socradar_base_url":   _get("SOCRADAR_BASE_URL", default="https://platform.socradar.com"),
        "socradar_api_key":    _get("SOCRADAR_API_KEY", required=True),
        "socradar_company_id": _get("SOCRADAR_COMPANY_ID", required=True),

        # Source toggles
        "enable_botnet_source": _bool("ENABLE_BOTNET_SOURCE", True),
        "enable_pii_source":      _bool("ENABLE_PII_SOURCE", True),
        "enable_vip_source":      _bool("ENABLE_VIP_SOURCE", False),

        # Entra ID — identifiers only, NO secret.
        # Graph auth uses Workload Identity Federation: UAMI → App Registration.
        # Permissions managed in portal (App Registration → API permissions).
        #
        # Multi-tenant: ENTRA_TENANT_IDS (CSV) is the primary path; the customer's
        # multi-tenant App Registration lives in the first ("primary") tenant and
        # is consented in the others. Each lookup tries tenants in order, first
        # match wins. ENTRA_TENANT_ID (single) is retained for backward compat —
        # see resolve_tenants() in this module.
        "tenant_ids":    _list("ENTRA_TENANT_IDS"),
        "tenant_id":     _get("ENTRA_TENANT_ID", default=""),
        "client_id":     _get("ENTRA_CLIENT_ID", required=user_lookup),

        # Verified-domain allowlist (optional). When non-empty, only records whose
        # email domain matches one of these is forwarded to Microsoft Graph; others
        # are written to LAW with entra_status="skipped_domain_allowlist". Empty
        # list disables filtering (current behavior). Case-insensitive exact match
        # — lowercased on load so the per-record comparison stays cheap.
        "verified_domains": [d.lower() for d in _list("ENTRA_ID_VERIFIED_DOMAINS")],

        # Action toggles
        "enable_user_lookup":       user_lookup,
        "enable_ropc":              _bool("ENABLE_ROPC", False),
        "enable_revoke_session":    _bool("ENABLE_REVOKE_SESSION", True),
        "enable_add_to_group":      _bool("ENABLE_ADD_TO_GROUP", True),
        "enable_remove_from_group": _bool("ENABLE_REMOVE_FROM_GROUP", False),
        "enable_password_change":   _bool("ENABLE_PASSWORD_CHANGE", False),
        "enable_disable_account":   _bool("ENABLE_DISABLE_ACCOUNT", False),
        "enable_enable_account":    _bool("ENABLE_ENABLE_ACCOUNT", False),
        "enable_confirm_risky":     _bool("ENABLE_CONFIRM_RISKY", False),
        "enable_force_mfa_reregistration": _bool("ENABLE_FORCE_MFA_REREGISTRATION", False),
        "enable_create_incident":   _bool("ENABLE_CREATE_INCIDENT", False),
        "enable_resolve_alarm":     _bool("ENABLE_RESOLVE_ALARM", False),
        "security_group_id":        _get("SECURITY_GROUP_ID", default=""),

        # Password policy
        "enable_log_plaintext_password": _bool("ENABLE_LOG_PLAINTEXT_PASSWORD", False),

        # Log Analytics (read-only — used by tests/diagnostics, not for ingestion)
        "workspace_id":  _get("WORKSPACE_ID", default=""),

        # DCR-based Logs Ingestion API (replaces legacy HTTP Data Collector API).
        # See: https://learn.microsoft.com/azure/azure-monitor/logs/custom-logs-migrate
        "dcr_immutable_id": _get("DCR_IMMUTABLE_ID", required=True),
        "dcr_endpoint":     _get("DCR_ENDPOINT", required=True),

        # Microsoft Sentinel (optional, only if create_incident=true)
        "subscription_id":          _get("SUBSCRIPTION_ID", default=""),
        "workspace_name":           _get("WORKSPACE_NAME", default=""),
        "workspace_location":       _get("WORKSPACE_LOCATION", default=""),
        "workspace_resource_group": _get("WORKSPACE_RESOURCE_GROUP", default=""),

        # Storage (for checkpoint)
        "storage_account_name": _get("STORAGE_ACCOUNT_NAME", required=True),

        # How long the action idempotency ledger keeps rows. Floored at 30
        # days in the ledger itself, so a typo cannot empty it while a held
        # window could still be re-read.
        "action_ledger_retention_days": _int("ACTION_LEDGER_RETENTION_DAYS", 90),

        # Absolute ceiling on directory mutations per source per run. A feed
        # that suddenly returns thousands of records must not turn into
        # thousands of account changes. on_invalid=0: a broken value CLOSES
        # the gate (no actions) rather than silently restoring the default.
        "entra_max_actions_per_run": _int("ENTRA_MAX_ACTIONS_PER_RUN", 50, on_invalid=0),

        # Schedule
        "initial_lookback_minutes": _int("INITIAL_LOOKBACK_MINUTES", 43200),
        "initial_start_date": _get("INITIAL_START_DATE", default=""),
    }
