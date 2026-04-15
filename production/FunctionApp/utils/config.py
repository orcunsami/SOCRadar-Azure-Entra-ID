"""
Configuration loader — reads all settings from Azure App Settings (environment variables).
Validates required fields and provides typed accessors.
"""

import os


def _get(key: str, default=None, required: bool = False):
    val = os.environ.get(key, default)
    if required and not val:
        raise EnvironmentError(f"Required App Setting missing: {key}")
    return val


def _bool(key: str, default: bool = False) -> bool:
    val = os.environ.get(key, "").lower()
    if val in ("true", "1", "yes"):
        return True
    if val in ("false", "0", "no"):
        return False
    return default


def _int(key: str, default: int = 0) -> int:
    try:
        return int(os.environ.get(key, str(default)))
    except (ValueError, TypeError):
        return default


def load() -> dict:
    """Load and validate all configuration. Raises EnvironmentError on missing required settings."""
    user_lookup = _bool("ENABLE_USER_LOOKUP", True)

    return {
        # SOCRadar API
        "socradar_base_url":   _get("SOCRADAR_BASE_URL", default="https://platform.socradar.com"),
        "socradar_api_key":    _get("SOCRADAR_API_KEY", required=True),
        "socradar_company_id": _get("SOCRADAR_COMPANY_ID", required=True),

        # Source toggles
        "enable_botnet_source": _bool("ENABLE_BOTNET_SOURCE", True),
        "enable_pii_source":      _bool("ENABLE_PII_SOURCE", True),
        "enable_vip_source":      _bool("ENABLE_VIP_SOURCE", False),

        # Entra ID (required only when user lookup is enabled)
        "tenant_id":     _get("ENTRA_TENANT_ID", required=user_lookup),
        "client_id":     _get("ENTRA_CLIENT_ID", required=user_lookup),
        "client_secret": _get("ENTRA_CLIENT_SECRET", required=user_lookup),

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

        # Log Analytics
        "workspace_id":  _get("WORKSPACE_ID", required=True),
        "workspace_key": _get("WORKSPACE_KEY", required=True),

        # Microsoft Sentinel (optional, only if create_incident=true)
        "subscription_id":          _get("SUBSCRIPTION_ID", default=""),
        "workspace_name":           _get("WORKSPACE_NAME", default=""),
        "workspace_location":       _get("WORKSPACE_LOCATION", default=""),
        "workspace_resource_group": _get("WORKSPACE_RESOURCE_GROUP", default=""),

        # Storage (for checkpoint)
        "storage_account_name": _get("STORAGE_ACCOUNT_NAME", required=True),

        # Schedule
        "initial_lookback_minutes": _int("INITIAL_LOOKBACK_MINUTES", 43200),
        "initial_start_date": _get("INITIAL_START_DATE", default=""),
    }
