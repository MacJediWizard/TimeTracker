"""Shared sync configuration helpers for accounting connectors."""

from datetime import datetime, timedelta
from typing import Any, Dict, Optional


def export_enabled(config: Optional[Dict[str, Any]], provider: str) -> bool:
    """True when this connector should push data to the external system."""
    cfg = config or {}
    default = f"timetracker_to_{provider}"
    direction = cfg.get("sync_direction", default)
    return direction in (default, "bidirectional")


def should_sync_invoices(config: Optional[Dict[str, Any]], sync_type: str) -> bool:
    cfg = config or {}
    if cfg.get("sync_invoices") is False:
        return False
    items = cfg.get("sync_items") or []
    if items and "invoices" not in items:
        return False
    return sync_type in ("full", "invoices", "incremental")


def should_sync_expenses(config: Optional[Dict[str, Any]], sync_type: str, approved_only: bool = False) -> bool:
    cfg = config or {}
    if cfg.get("sync_expenses") is False:
        return False
    items = cfg.get("sync_items") or []
    if items and "expenses" not in items:
        return False
    return sync_type in ("full", "expenses", "incremental")


def sync_window_start(config: Optional[Dict[str, Any]], days: int = 90) -> datetime:
    """Return UTC datetime for incremental/full scan window.

    Use this to compare against UTC audit columns (e.g. Invoice.created_at).
    """
    cfg = config or {}
    window_days = int(cfg.get("sync_window_days") or days)
    return datetime.utcnow() - timedelta(days=window_days)


def sync_window_start_date(config: Optional[Dict[str, Any]], days: int = 90):
    """Return the business-calendar date for the scan window.

    Use this to compare against ``db.Date`` business-calendar columns
    (e.g. Expense.expense_date), which are keyed to the app timezone rather
    than UTC — otherwise the window is off by up to a day near midnight.
    """
    from app.models.time_entry import local_now

    cfg = config or {}
    window_days = int(cfg.get("sync_window_days") or days)
    return local_now().date() - timedelta(days=window_days)
