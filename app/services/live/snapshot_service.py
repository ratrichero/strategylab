"""
Snapshot Service — LIVE
=======================
Lấy exchange snapshot chuẩn hóa cho reconciler.

OPTIMIZATIONS:
- Algo order status chỉ query khi:
    + có sl_order_id / tp_order_id trong pending
    + VÀ pending đã có fill (executed_qty > 0)
  Nếu pending chưa fill, không cần query algo vì chưa place protection.

- Open algo orders query cho symbol chỉ khi có fill.

- Entry order status chỉ query khi có exchange_order_id.
"""

from dataclasses import dataclass
from typing import Optional, Dict, List

from app.core.time_utils import utc_now
from app.services.execution_service import (
    get_entry_order_status,
    get_open_algo_orders,
    get_open_orders,
    get_algo_order_status,
    get_position_info_by_symbol,
)


@dataclass
class EntrySnapshot:
    order_id: Optional[str]
    status: Optional[str]
    orig_qty: float
    executed_qty: float
    avg_fill_price: Optional[float]


@dataclass
class PositionSnapshot:
    exists: bool
    qty: float
    direction: Optional[str]
    entry_price: Optional[float]
    leverage: Optional[int]
    unrealized_profit: Optional[float]


@dataclass
class AlgoSnapshot:
    algo_id: Optional[str]
    algo_status: Optional[str]
    actual_order_id: Optional[str]
    actual_price: Optional[float]
    actual_qty: Optional[float]
    trigger_price: Optional[float]
    trigger_time: Optional[int]
    raw: Optional[Dict]


@dataclass
class SymbolSnapshot:
    symbol: str
    entry: EntrySnapshot
    position: PositionSnapshot
    open_normal_orders: List[Dict]
    open_algo_orders: List[Dict]
    sl_algo: Optional[AlgoSnapshot]
    tp_algo: Optional[AlgoSnapshot]
    snapshot_time: object
    ok: bool
    error: Optional[str] = None


def _algo_from_status(algo_id: Optional[str]) -> Optional[AlgoSnapshot]:
    if not algo_id:
        return None

    data = get_algo_order_status(algo_id)
    return AlgoSnapshot(
        algo_id=str(algo_id),
        algo_status=data.get("algo_status"),
        actual_order_id=data.get("actual_order_id"),
        actual_price=data.get("actual_price"),
        actual_qty=data.get("actual_qty"),
        trigger_price=data.get("trigger_price"),
        trigger_time=data.get("trigger_time"),
        raw=data.get("raw"),
    )


_EMPTY_ENTRY = EntrySnapshot(
    order_id=None,
    status=None,
    orig_qty=0.0,
    executed_qty=0.0,
    avg_fill_price=None,
)

_EMPTY_POSITION = PositionSnapshot(
    exists=False,
    qty=0.0,
    direction=None,
    entry_price=None,
    leverage=None,
    unrealized_profit=None,
)


def build_symbol_snapshot(
    symbol: str,
    pending=None,
    need_algo_detail: bool = True,
) -> SymbolSnapshot:
    """
    Build exchange snapshot for 1 symbol.

    Args:
        symbol: trading pair
        pending: PendingSignal row (optional)
        need_algo_detail: nếu False, skip individual algo order query
            (dùng khi chưa cần chi tiết SL/TP status)
    """
    try:
        order_id = getattr(pending, "exchange_order_id", None) if pending else None
        has_fill = float(getattr(pending, "executed_qty", 0) or 0) > 0

        # ── Entry order status ───────────────────────────
        if order_id:
            entry_info = get_entry_order_status(symbol, order_id)
        else:
            entry_info = {
                "status": None,
                "avg_price": None,
                "executed_qty": 0.0,
                "orig_qty": 0.0,
            }

        # ── Position ─────────────────────────────────────
        position = get_position_info_by_symbol(symbol)

        # ── Normal open orders ───────────────────────────
        open_normal_orders = get_open_orders(symbol)

        # ── Algo orders ──────────────────────────────────
        # Chỉ query open algo khi đã có fill hoặc có position
        if has_fill or position:
            open_algo_orders = get_open_algo_orders(symbol)
        else:
            open_algo_orders = []

        # ── Individual algo status ───────────────────────
        # Chỉ query khi:
        # 1) need_algo_detail = True
        # 2) pending có fill (protection đã place)
        # 3) pending có sl/tp order id
        sl_algo = None
        tp_algo = None

        if need_algo_detail and has_fill and pending:
            sl_id = getattr(pending, "sl_order_id", None)
            tp_id = getattr(pending, "tp_order_id", None)

            if sl_id:
                sl_algo = _algo_from_status(sl_id)
            if tp_id:
                tp_algo = _algo_from_status(tp_id)

        return SymbolSnapshot(
            symbol=symbol,
            entry=EntrySnapshot(
                order_id=str(order_id) if order_id else None,
                status=entry_info.get("status"),
                orig_qty=float(entry_info.get("orig_qty") or 0),
                executed_qty=float(entry_info.get("executed_qty") or 0),
                avg_fill_price=(
                    float(entry_info.get("avg_price"))
                    if entry_info.get("avg_price")
                    else None
                ),
            ),
            position=PositionSnapshot(
                exists=bool(position),
                qty=abs(float(position.get("positionAmt", 0))) if position else 0.0,
                direction=position.get("direction") if position else None,
                entry_price=float(position.get("entryPrice", 0)) if position else None,
                leverage=int(position.get("leverage", 1)) if position else None,
                unrealized_profit=float(position.get("unrealizedProfit", 0)) if position else None,
            ),
            open_normal_orders=open_normal_orders or [],
            open_algo_orders=open_algo_orders or [],
            sl_algo=sl_algo,
            tp_algo=tp_algo,
            snapshot_time=utc_now(),
            ok=True,
            error=None,
        )
    except Exception as e:
        return SymbolSnapshot(
            symbol=symbol,
            entry=_EMPTY_ENTRY,
            position=_EMPTY_POSITION,
            open_normal_orders=[],
            open_algo_orders=[],
            sl_algo=None,
            tp_algo=None,
            snapshot_time=utc_now(),
            ok=False,
            error=f"{type(e).__name__}: {e}",
        )