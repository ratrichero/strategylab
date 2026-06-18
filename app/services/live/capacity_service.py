"""
LIVE Capacity Service
=====================
Hard-cap exposure helpers cho LIVE mode.

Definitions:
- HARD-CAP execution exposure:
    OPEN signals
    UNION
    placed WAIT pendings chưa terminal

- OTF/Scanner soft-cap:
    OPEN signals
    UNION
    ALL WAIT pendings (kể cả chưa place)
"""

from typing import Set, List
from sqlalchemy import or_

from app.db.models import Signal, PendingSignal


TERMINAL_EXCHANGE_STATUSES = {"FILLED", "CANCELED", "EXPIRED", "REJECTED"}


def is_exchange_terminal_status(status: str) -> bool:
    return str(status or "").upper() in TERMINAL_EXCHANGE_STATUSES


def is_pending_exchange_active(pending: PendingSignal) -> bool:
    if not pending:
        return False
    if pending.status != "WAIT":
        return False
    if not pending.exchange_order_id:
        return False
    if is_exchange_terminal_status(pending.exchange_status):
        return False
    return True


def get_active_live_symbols(db) -> Set[str]:
    """
    ACTIVE LIVE SYMBOLS =
      OPEN signals
      UNION
      placed WAIT pendings chưa terminal
    """
    symbols = set()

    open_signal_rows = db.query(Signal.symbol).filter(
        Signal.status == "OPEN"
    ).distinct().all()

    for row in open_signal_rows:
        if row and row[0]:
            symbols.add(row[0])

    pending_rows = db.query(PendingSignal.symbol).filter(
        PendingSignal.status == "WAIT",
        PendingSignal.exchange_order_id != None,  # noqa: E711
        or_(
            PendingSignal.exchange_status == None,  # noqa: E711
            PendingSignal.exchange_status.notin_(list(TERMINAL_EXCHANGE_STATUSES))
        )
    ).distinct().all()

    for row in pending_rows:
        if row and row[0]:
            symbols.add(row[0])

    return symbols


def get_active_live_symbol_count(db) -> int:
    return len(get_active_live_symbols(db))


def get_live_otf_symbols(db) -> Set[str]:
    """
    LIVE OTF / scanner cap symbols =
      OPEN signals
      UNION
      ALL WAIT pendings (kể cả chưa place)
    """
    symbols = set()

    open_signal_rows = db.query(Signal.symbol).filter(
        Signal.status == "OPEN"
    ).distinct().all()

    for row in open_signal_rows:
        if row and row[0]:
            symbols.add(row[0])

    waiting_pending_rows = db.query(PendingSignal.symbol).filter(
        PendingSignal.status == "WAIT"
    ).distinct().all()

    for row in waiting_pending_rows:
        if row and row[0]:
            symbols.add(row[0])

    return symbols


def get_live_otf_symbol_count(db) -> int:
    return len(get_live_otf_symbols(db))


def get_zero_fill_resting_pending_candidates(db) -> List[PendingSignal]:
    """
    Candidate để dọn khi overflow hard-cap:
    - pending WAIT
    - đã place lên exchange
    - chưa terminal
    - chưa fill gì
    - ưu tiên cancel lệnh mới nhất trước
    """
    rows = db.query(PendingSignal).filter(
        PendingSignal.status == "WAIT",
        PendingSignal.exchange_order_id != None,  # noqa: E711
        or_(
            PendingSignal.exchange_status == None,  # noqa: E711
            PendingSignal.exchange_status.notin_(list(TERMINAL_EXCHANGE_STATUSES))
        ),
        or_(
            PendingSignal.executed_qty == None,     # noqa: E711
            PendingSignal.executed_qty <= 0
        )
    ).order_by(
        PendingSignal.placed_at.desc(),
        PendingSignal.created_at.desc(),
        PendingSignal.id.desc()
    ).all()

    return rows