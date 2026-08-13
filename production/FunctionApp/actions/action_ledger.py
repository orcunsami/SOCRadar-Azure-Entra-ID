"""
Idempotency ledger for remediation actions.

Why this module exists: the checkpoint now HOLDS on an unfinished run, which
makes re-reading the same window normal operation. Without a ledger, every
re-read repeats every action — the same user gets revoke_session or an MFA
reset applied again and again. The ledger records what was already applied so
a re-read skips it.

Key design: PartitionKey = source ("botnet" / "pii" / "vip"),
            RowKey       = sha256("{email}:{action}:{window}")

The window (the run's start date) is part of the key on purpose: a NEW window
means a new finding, and acting again on a fresh finding is correct. The raw
email is never stored — only its hash inside the row key.

Failure posture is fail-open and says so: if the ledger cannot be read or
written, the action proceeds and a warning is logged. That is exactly the
pre-ledger behaviour, so an unreachable table never blocks remediation; the
ledger closes the REPEAT path, it is not a gate on the first application.

Rows older than the retention window (floored at 30 days) are purged each
run — no re-read can reach them once the checkpoint has moved past.
"""

import hashlib
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("socradar.entra.ledger")

TABLE_NAME = "EntraIDActionLedger"
RETENTION_FLOOR_DAYS = 30


def _row_key(email: str, action: str, window: str) -> str:
    raw = f"{(email or '').strip().lower()}:{action}:{window}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class InMemoryActionLedger:
    """For unit tests and as the fail-open stand-in when storage is down."""

    def __init__(self):
        self._rows = set()

    def already_applied(self, source: str, email: str, action: str, window: str) -> bool:
        return (source, _row_key(email, action, window)) in self._rows

    def record(self, source: str, email: str, action: str, window: str) -> None:
        self._rows.add((source, _row_key(email, action, window)))

    def purge_old(self, retention_days: int) -> int:
        return 0


class ActionLedger:
    """Azure Table implementation. One table, one row per applied action."""

    def __init__(self, storage_account_name: str, credential):
        from azure.data.tables import TableServiceClient
        url = f"https://{storage_account_name}.table.core.windows.net"
        service = TableServiceClient(endpoint=url, credential=credential)
        self._table = service.create_table_if_not_exists(TABLE_NAME)

    def already_applied(self, source: str, email: str, action: str, window: str) -> bool:
        from azure.core.exceptions import ResourceNotFoundError
        try:
            self._table.get_entity(partition_key=source,
                                   row_key=_row_key(email, action, window))
            return True
        except ResourceNotFoundError:
            return False
        except Exception as e:
            # Fail-open: an unreadable ledger must not block remediation.
            logger.warning("[LEDGER] read failed (%s) — proceeding as not applied", e)
            return False

    def record(self, source: str, email: str, action: str, window: str) -> None:
        try:
            self._table.upsert_entity({
                "PartitionKey": source,
                "RowKey": _row_key(email, action, window),
                "action": action,
                "window": window,
            })
        except Exception as e:
            logger.warning("[LEDGER] write failed (%s) — a re-read may repeat this action", e)

    def purge_old(self, retention_days: int) -> int:
        """Delete rows past retention. Floored so a typo cannot empty the ledger
        while a re-read could still reach those windows."""
        days = max(int(retention_days or 0), RETENTION_FLOOR_DAYS)
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        removed = 0
        try:
            stale = self._table.query_entities(
                f"Timestamp lt datetime'{cutoff.strftime('%Y-%m-%dT%H:%M:%SZ')}'")
            for row in stale:
                self._table.delete_entity(partition_key=row["PartitionKey"],
                                          row_key=row["RowKey"])
                removed += 1
        except Exception as e:
            logger.warning("[LEDGER] purge failed (%s) — old rows kept", e)
        if removed:
            logger.info("[LEDGER] purged %d rows older than %d days", removed, days)
        return removed


def build(conf: dict, credential):
    """Table ledger in production; the in-memory stand-in if storage is down."""
    try:
        return ActionLedger(conf["storage_account_name"], credential)
    except Exception as e:
        logger.warning("[LEDGER] table unavailable (%s) — running without "
                       "persistence; a re-read may repeat actions", e)
        return InMemoryActionLedger()
