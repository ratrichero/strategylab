"""
Open Trade Filter
=================
Kiểm tra trước khi tạo PendingSignal / trước khi place order.

QUAN TRỌNG:
- get_open_trade_filter() phải nhận đúng OTF config block
- KHÔNG được truyền full runtime_cfg vào
- Nếu lỡ truyền full runtime_cfg, function sẽ tự bóc OPEN_TRADE_FILTER ra

LIVE NOTE:
- LIVE dùng cùng ConflictRule với scanner:
    + open signal block = symbol + status=OPEN
    + pending block     = symbol + status=WAIT
- Hỗ trợ exclude current pending/signal để tránh self-block
  khi check ở intent phase / command phase.
"""

from datetime import timedelta
from typing import Tuple, Optional, Dict
from app.core.trading_mode import get_current_mode, TradingMode, get_trading_mode
from app.core.time_utils import utc_now, vn_now


class OpenTradeFilter:
    def __init__(self, config: dict):
        self.cfg = config or {"enabled": False}

        # Safety: nếu caller lỡ truyền full runtime config
        if "OPEN_TRADE_FILTER" in self.cfg and "enabled" not in self.cfg:
            self.cfg = self.cfg.get("OPEN_TRADE_FILTER", {"enabled": False})

    def check(self, symbol, direction, strategy_name, pattern,
               timeframe, regime, score, ml_prob, components,
               atr_ratio=None, db=None,
               exclude_pending_id=None, exclude_signal_id=None) -> Tuple[bool, str]:

        # 1. Bật / Tắt Filter
        if not self.cfg.get("enabled", False):
            return True, "filter_disabled"

        identity = self.cfg.get("identity", {})

        # ========================================================
        # A. IDENTITY CHECKS
        # ========================================================

        # 2. Direction
        allowed_dirs = identity.get("directions")
        if allowed_dirs is not None and len(allowed_dirs) > 0:
            if direction not in allowed_dirs:
                return False, f"direction_blocked_{direction}"

        # 3. Strategy
        allowed_strats = identity.get("strategies")
        if allowed_strats is not None and len(allowed_strats) > 0:
            if strategy_name not in allowed_strats:
                return False, f"strategy_blocked_{strategy_name}"

        # 4. Pattern
        allowed_patterns = identity.get("patterns")
        if allowed_patterns is not None and len(allowed_patterns) > 0:
            if pattern not in allowed_patterns:
                return False, f"pattern_blocked_{pattern}"

        # 5. Timeframe
        allowed_tfs = identity.get("timeframes")
        if allowed_tfs is not None and len(allowed_tfs) > 0:
            if timeframe not in allowed_tfs:
                return False, f"timeframe_blocked_{timeframe}"

        # 6. Symbol
        sym_mode = identity.get("symbol_mode", "all")
        if sym_mode == "whitelist":
            wl = identity.get("symbol_whitelist")
            if wl and len(wl) > 0 and symbol not in wl:
                return False, "symbol_not_whitelisted"
        elif sym_mode == "blacklist":
            bl = identity.get("symbol_blacklist")
            if bl and len(bl) > 0 and symbol in bl:
                return False, "symbol_blacklisted"

        # ========================================================
        # B. MARKET CONDITION & SCORE
        # ========================================================

        mkt = self.cfg.get("market_condition", {})
        allowed_regimes = mkt.get("allowed_regimes")
        if allowed_regimes is not None and len(allowed_regimes) > 0:
            if regime not in allowed_regimes:
                return False, f"regime_blocked_{regime}"

        if atr_ratio is not None:
            min_atr = mkt.get("min_atr_pct", 0)
            max_atr = mkt.get("max_atr_pct", 0)
            if min_atr > 0 and atr_ratio < min_atr:
                return False, "atr_too_low"
            if max_atr > 0 and atr_ratio > max_atr:
                return False, "atr_too_high"

        sc = self.cfg.get("score", {})
        if score < sc.get("min_overall", 0):
            return False, "score_below_filter"

        if ml_prob is not None and sc.get("min_ml_prob", 0) > 0:
            if ml_prob < sc["min_ml_prob"]:
                return False, "ml_prob_below_filter"

        if components:
            if sc.get("min_trend_score", 0) > 0:
                if components.get("trend_score", 0) < sc["min_trend_score"]:
                    return False, "trend_below_filter"
            if sc.get("min_mtf_score", 0) > 0:
                if components.get("mtf_score", 0) < sc["min_mtf_score"]:
                    return False, "mtf_below_filter"

        # ========================================================
        # C. POSITION CHECK
        # ========================================================

        if db is not None:
            ok, reason = self._check_position(
                db, symbol, strategy_name, timeframe,
                exclude_pending_id=exclude_pending_id,
                exclude_signal_id=exclude_signal_id,
            )
            if not ok:
                return False, reason

        # ========================================================
        # D. TIME CHECK
        # ========================================================

        time_cfg = self.cfg.get("time", {})
        if time_cfg.get("enabled", False):
            ok, reason = self._check_time(time_cfg)
            if not ok:
                return False, reason

        return True, "passed"

    def _check_position(self, db, symbol, strategy_name, timeframe,
                    exclude_pending_id=None, exclude_signal_id=None):
        from app.db.models import Signal, PendingSignal
        from sqlalchemy import func
        from app.services.live.capacity_service import get_live_otf_symbol_count

        pos = self.cfg.get("position", {})
        mode = get_current_mode()
        mode_manager = get_trading_mode()
        rule = mode_manager.get_conflict_rule()

        max_conc = pos.get("max_concurrent_trades", 999)

        # LIVE: dùng count theo OPEN signals + ALL WAIT pendings
        if mode != TradingMode.PAPER:
            live_count = get_live_otf_symbol_count(db)

            # Nếu exclude current pending mà pending đó đang WAIT trong DB, trừ bớt 1 symbol nếu cần
            # (trường hợp intent phase check lại cho row hiện tại)
            if exclude_pending_id is not None:
                current_pending = db.query(PendingSignal).get(exclude_pending_id)
                if current_pending and current_pending.status == "WAIT":
                    # chỉ trừ nếu symbol đó thực sự nằm trong counted set
                    # giữ đơn giản: recalc thủ công
                    live_symbols = set()
                    open_signal_rows = db.query(Signal.symbol).filter(
                        Signal.status == "OPEN"
                    ).distinct().all()
                    for row in open_signal_rows:
                        if row and row[0]:
                            live_symbols.add(row[0])

                    waiting_pending_rows = db.query(PendingSignal.symbol).filter(
                        PendingSignal.status == "WAIT"
                    ).all()
                    for row in waiting_pending_rows:
                        if row and row[0]:
                            live_symbols.add(row[0])

                    if current_pending.symbol in live_symbols:
                        # remove self symbol only if no other WAIT/OPEN row of same symbol still exists
                        other_wait = db.query(PendingSignal).filter(
                            PendingSignal.symbol == current_pending.symbol,
                            PendingSignal.status == "WAIT",
                            PendingSignal.id != current_pending.id
                        ).count()
                        other_open = db.query(Signal).filter(
                            Signal.symbol == current_pending.symbol,
                            Signal.status == "OPEN"
                        ).count()

                        if other_wait == 0 and other_open == 0:
                            live_count = max(0, live_count - 1)

            if live_count >= max_conc:
                return False, "max_concurrent_reached"
        else:
            if db.query(Signal).filter(Signal.status == "OPEN").count() >= max_conc:
                return False, "max_concurrent_reached"

        # ── Conflict checks dùng cùng rule với scanner ───────
        open_cond = rule.get_open_signal_block_condition(
            symbol, strategy_name, timeframe, mode
        )
        open_q = db.query(Signal).filter_by(**open_cond)

        if exclude_signal_id is not None:
            open_q = open_q.filter(Signal.id != exclude_signal_id)

        if open_q.count() > 0:
            if mode != TradingMode.PAPER:
                return False, "live_symbol_occupied"
            return False, "max_per_symbol"

        pending_cond = rule.get_pending_block_condition(
            symbol, strategy_name, timeframe, mode
        )
        pending_q = db.query(PendingSignal).filter_by(**pending_cond)

        if exclude_pending_id is not None:
            pending_q = pending_q.filter(PendingSignal.id != exclude_pending_id)

        if pending_q.count() > 0:
            if mode != TradingMode.PAPER:
                return False, "live_symbol_pending_exists"

        # ── PAPER-specific max per symbol ────────────────────
        if mode == TradingMode.PAPER:
            max_sym = pos.get("max_per_symbol", 1)
            paper_open_count = db.query(Signal).filter(
                Signal.symbol == symbol,
                Signal.strategy_name == strategy_name,
                Signal.timeframe == timeframe,
                Signal.status == "OPEN"
            ).count()
            if paper_open_count >= max_sym:
                return False, "max_per_symbol"

        max_tf_cfg = pos.get("max_per_timeframe", {})
        tf_limit = max_tf_cfg.get(timeframe, 999)
        if db.query(Signal).filter(
                Signal.timeframe == timeframe,
                Signal.status == "OPEN").count() >= tf_limit:
            return False, f"max_per_tf_{timeframe}"

        # Daily trades
        max_daily = pos.get("max_daily_trades", 0)
        if max_daily > 0:
            from app.core.time_utils import vn_day_to_utc_range
            today_start_utc, _ = vn_day_to_utc_range(
                vn_now().date().isoformat()
            )
            if db.query(Signal).filter(
                    Signal.created_at >= today_start_utc).count() >= max_daily:
                return False, "max_daily_trades"

        # Daily loss
        max_loss = pos.get("max_daily_loss_pct", 0)
        if max_loss > 0:
            from app.core.time_utils import vn_day_to_utc_range
            today_start_utc, _ = vn_day_to_utc_range(
                vn_now().date().isoformat()
            )
            pnl = db.query(func.sum(Signal.result_percent)).filter(
                Signal.exit_time >= today_start_utc,
                Signal.status.in_(["WIN", "LOSS"])
            ).scalar() or 0
            if pnl <= -max_loss:
                return False, "daily_loss_limit"

        # Loss streak
        pause_n = pos.get("pause_after_loss_streak", 0)
        if pause_n > 0:
            recent = (
                db.query(Signal.status)
                .filter(Signal.status.in_(["WIN", "LOSS"]))
                .order_by(Signal.exit_time.desc())
                .limit(pause_n)
                .all()
            )
            if len(recent) >= pause_n and all(r[0] == "LOSS" for r in recent[:pause_n]):
                return False, "loss_streak_pause"

        return True, "ok"

    def _check_time(self, time_cfg):
        now_vn = vn_now()
        allowed_days = time_cfg.get("allowed_days", list(range(7)))
        if now_vn.weekday() not in allowed_days:
            return False, "day_restricted"

        hours = time_cfg.get("allowed_hours", {"start": "00:00", "end": "23:59"})
        sh, sm = map(int, hours["start"].split(":"))
        eh, em = map(int, hours["end"].split(":"))
        cur = now_vn.hour * 60 + now_vn.minute
        if not (sh * 60 + sm <= cur <= eh * 60 + em):
            return False, "outside_hours"

        blackout = time_cfg.get("blackout_minutes_before_funding", 0)
        if blackout > 0:
            now_utc = utc_now()
            for fh in [0, 8, 16]:
                ft = now_utc.replace(hour=fh, minute=0, second=0, microsecond=0)
                if ft <= now_utc:
                    ft += timedelta(days=1)
                if (ft - now_utc).total_seconds() / 60 <= blackout:
                    return False, "funding_blackout"

        return True, "ok"


def get_open_trade_filter(cfg=None) -> OpenTradeFilter:
    """
    Hỗ trợ 3 kiểu truyền:
    1. None         -> tự load runtime config rồi bóc OPEN_TRADE_FILTER
    2. Full runtime -> tự bóc OPEN_TRADE_FILTER
    3. OTF config   -> dùng luôn
    """
    if cfg is None:
        from app.services.config_service import get_runtime_config
        cfg = get_runtime_config().get("OPEN_TRADE_FILTER", {"enabled": False})
    elif isinstance(cfg, dict) and "OPEN_TRADE_FILTER" in cfg:
        cfg = cfg.get("OPEN_TRADE_FILTER", {"enabled": False})

    return OpenTradeFilter(cfg or {"enabled": False})