"""
LIVE Capacity Service
=====================
Capacity model cho LIVE:

Definitions:
- C_CONFIG = MAX_OPEN_TRADES (user-controlled)
- C_OPEN   = distinct symbols with Signal.status = OPEN
- C_NEW    = distinct symbols with PendingSignal:
             status=WAIT, exchange_order_id IS NOT NULL,
             executed_qty <= 0, exchange chưa terminal
- C_LOCAL  = pending local chưa place -> KHÔNG tính hard risk cap,
             nhưng dùng để quyết định pause scan hay chưa.

Rules:
- Hard risk ceiling:
    C_OPEN + C_NEW <= C_CONFIG + 2
- Block new placement when:
    C_OPEN >= C_CONFIG
    OR
    C_OPEN + C_NEW >= C_CONFIG + 2
- Pause scan when:
    (C_OPEN >= C_CONFIG OR C_OPEN + C_NEW >= C_CONFIG + 2)
    AND C_LOCAL >= LOCAL_QUEUE_RESERVE
- Cleanup when:
    C_OPEN + C_NEW > C_CONFIG + 2

IMPORTANT:
- File này giữ cả API mới và compatibility helpers cũ
  để không làm vỡ reconciler/runtime cũ đang import.
"""

from dataclasses import dataclass
from typing import Set, List
from sqlalchemy import or_, text

from app.db.models import Signal, PendingSignal


TERMINAL_EXCHANGE_STATUSES = {"FILLED", "CANCELED", "EXPIRED", "REJECTED"}
LOCAL_QUEUE_RESERVE = 6


def is_exchange_terminal_status(status: str) -> bool:
    return str(status or "").upper() in TERMINAL_EXCHANGE_STATUSES


def is_pending_exchange_active(pending: PendingSignal) -> bool:
    """
    Compatibility helper cũ:
    pending đang sống trên exchange nếu:
    - status WAIT
    - có exchange_order_id
    - exchange chưa terminal
    """
    if not pending:
        return False
    if pending.status != "WAIT":
        return False
    if not pending.exchange_order_id:
        return False
    if is_exchange_terminal_status(pending.exchange_status):
        return False
    return True


def is_pending_new_zero_fill(pending: PendingSignal) -> bool:
    """
    NEW zero-fill = đang nằm trên exchange, chưa fill gì.
    Đây là nhóm được tính vào C_NEW.
    """
    if not pending:
        return False
    if not is_pending_exchange_active(pending):
        return False
    if float(pending.executed_qty or 0) > 0:
        return False
    return True


@dataclass
class CapacitySnapshot:
    c_config: int
    c_open: int
    c_new: int
    c_local: int
    total_risk: int
    max_risk: int
    local_queue_reserve: int = LOCAL_QUEUE_RESERVE

    @property
    def place_blocked(self) -> bool:
        return self.c_open >= self.c_config or self.total_risk >= self.max_risk

    @property
    def scan_paused(self) -> bool:
        saturated = (self.c_open >= self.c_config) or (self.total_risk >= self.max_risk)
        return saturated and self.c_local >= self.local_queue_reserve

    @property
    def cleanup_needed(self) -> bool:
        return self.total_risk > self.max_risk

    @property
    def overflow_count(self) -> int:
        return max(0, self.total_risk - self.max_risk)


# ============================================================
# Core symbol sets
# ============================================================

def get_open_signal_symbols(db) -> Set[str]:
    rows = db.query(Signal.symbol).filter(
        Signal.status == "OPEN"
    ).distinct().all()

    return {row[0] for row in rows if row and row[0]}


def get_new_zero_fill_symbols(db) -> Set[str]:
    rows = db.query(PendingSignal.symbol).filter(
        PendingSignal.status == "WAIT",
        PendingSignal.exchange_order_id != None,  # noqa: E711
        or_(
            PendingSignal.executed_qty == None,    # noqa: E711
            PendingSignal.executed_qty <= 0
        ),
        or_(
            PendingSignal.exchange_status == None,  # noqa: E711
            PendingSignal.exchange_status.notin_(list(TERMINAL_EXCHANGE_STATUSES))
        )
    ).distinct().all()

    return {row[0] for row in rows if row and row[0]}


def get_local_queue_symbols(db) -> Set[str]:
    rows = db.query(PendingSignal.symbol).filter(
        PendingSignal.status == "WAIT",
        PendingSignal.exchange_order_id == None  # noqa: E711
    ).distinct().all()

    return {row[0] for row in rows if row and row[0]}


# ============================================================
# New API
# ============================================================

def get_capacity_snapshot(db, c_config: int, local_queue_reserve: int = LOCAL_QUEUE_RESERVE) -> CapacitySnapshot:
    open_symbols = get_open_signal_symbols(db)
    new_symbols = get_new_zero_fill_symbols(db)
    local_symbols = get_local_queue_symbols(db)

    c_open = len(open_symbols)
    c_new = len(new_symbols)
    c_local = len(local_symbols)
    total_risk = c_open + c_new
    max_risk = int(c_config) + 2

    return CapacitySnapshot(
        c_config=int(c_config),
        c_open=c_open,
        c_new=c_new,
        c_local=c_local,
        total_risk=total_risk,
        max_risk=max_risk,
        local_queue_reserve=int(local_queue_reserve),
    )


def get_capacity_snapshot_locked(db, c_config: int, local_queue_reserve: int = LOCAL_QUEUE_RESERVE) -> CapacitySnapshot:
    """
    Atomic capacity check với PostgreSQL advisory lock.
    
    Sử dụng pg_advisory_xact_lock để serialize capacity checks across transactions.
    Điều này fix race condition trong intent_engine nơi capacity được check 2 lần với time gap 300-500ms.
    
    Advisory lock key: 12345 (fixed key cho capacity placement serialization)
    """
    # Acquire advisory lock để serialize capacity checks
    db.execute(text("SELECT pg_advisory_xact_lock(12345)"))
    
    # Sau khi lock, query counts (không cần FOR UPDATE nữa vì advisory lock đã serialize)
    open_symbols = get_open_signal_symbols(db)
    new_symbols = get_new_zero_fill_symbols(db)
    local_symbols = get_local_queue_symbols(db)
    
    c_open = len(open_symbols)
    c_new = len(new_symbols)
    c_local = len(local_symbols)
    total_risk = c_open + c_new
    max_risk = int(c_config) + 2
    
    return CapacitySnapshot(
        c_config=int(c_config),
        c_open=c_open,
        c_new=c_new,
        c_local=c_local,
        total_risk=total_risk,
        max_risk=max_risk,
        local_queue_reserve=int(local_queue_reserve),
    )


def should_pause_scan(snapshot: CapacitySnapshot) -> bool:
    return snapshot.scan_paused


def should_block_new_entry(snapshot: CapacitySnapshot) -> bool:
    return snapshot.place_blocked


def get_new_zero_fill_cancel_candidates(db) -> List[PendingSignal]:
    """
    Candidate để dọn khi overflow:
    - pending WAIT
    - đã place lên exchange
    - zero fill
    - chưa terminal
    - ưu tiên cancel lệnh mới nhất trước
    """
    rows = db.query(PendingSignal).filter(
        PendingSignal.status == "WAIT",
        PendingSignal.exchange_order_id != None,  # noqa: E711
        or_(
            PendingSignal.executed_qty == None,    # noqa: E711
            PendingSignal.executed_qty <= 0
        ),
        or_(
            PendingSignal.exchange_status == None,  # noqa: E711
            PendingSignal.exchange_status.notin_(list(TERMINAL_EXCHANGE_STATUSES))
        )
    ).order_by(
        PendingSignal.placed_at.desc(),
        PendingSignal.created_at.desc(),
        PendingSignal.id.desc()
    ).all()

    return rows


# ============================================================
# Compatibility API for reconciler/runtime cũ
# ============================================================

def get_active_live_symbols(db) -> Set[str]:
    """
    Compatibility helper cũ:
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


def get_zero_fill_resting_pending_candidates(db) -> List[PendingSignal]:
    """
    Compatibility alias cũ.
    """
    return get_new_zero_fill_cancel_candidates(db)