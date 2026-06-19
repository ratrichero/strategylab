"""
Snapshot Service — LIVE
=======================
Lấy exchange snapshot chuẩn hóa cho reconciler.

RULE:
- Với position / protection đang ACTIVE:
    open algo orders là source of truth
- Không query individual algo detail mỗi vòng nữa
  vì endpoint single algo status đang cho false negative (-2013)
"""

from dataclasses import dataclass
from typing import Optional, Dict, List

from app.core.time_utils import utc_now
from app.services.execution_service import (
    get_entry_order_status,
    get_open_algo_orders,
    get_open_orders,
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


def _algo_from_open_order(row: Optional[Dict]) -> Optional[AlgoSnapshot]:
    if not row:
        return None

    return AlgoSnapshot(
        algo_id=str(row.get("algoId", "")) if row.get("algoId") is not None else None,
        algo_status=row.get("algoStatus"),
        actual_order_id=row.get("actualOrderId"),
        actual_price=float(row.get("actualPrice", 0) or 0) if row.get("actualPrice") is not None else None,
        actual_qty=float(row.get("actualQty", 0) or 0) if row.get("actualQty") is not None else None,
        trigger_price=float(row.get("triggerPrice", 0) or 0) if row.get("triggerPrice") is not None else None,
        trigger_time=row.get("triggerTime"),
        raw=row,
    )


def _find_open_algo_by_type(open_algo_orders: List[Dict], order_type: str) -> Optional[Dict]:
    for o in open_algo_orders or []:
        if str(o.get("orderType", "")).upper() == order_type.upper():
            return o
    return None


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
    need_algo_detail: bool = True,  # giữ param cho backward compatibility
) -> SymbolSnapshot:
    try:
        order_id = getattr(pending, "exchange_order_id", None) if pending else None

        if order_id:
            entry_info = get_entry_order_status(symbol, order_id)
        else:
            entry_info = {
                "status": None,
                "avg_price": None,
                "executed_qty": 0.0,
                "orig_qty": 0.0,
            }

        position = get_position_info_by_symbol(symbol)
        open_normal_orders = get_open_orders(symbol)

        # Chỉ cần open algo orders là đủ cho active protection truth
        open_algo_orders = get_open_algo_orders(symbol)

        sl_open = _find_open_algo_by_type(open_algo_orders, "STOP_MARKET")
        tp_open = _find_open_algo_by_type(open_algo_orders, "TAKE_PROFIT_MARKET")

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
            sl_algo=_algo_from_open_order(sl_open),
            tp_algo=_algo_from_open_order(tp_open),
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