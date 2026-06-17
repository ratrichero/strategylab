"""Open Trade Filter — kiểm tra trước khi tạo PendingSignal"""
from datetime import datetime, timedelta
from typing import Tuple, Optional, Dict
from app.core.trading_mode import get_current_mode, TradingMode
from app.core.time_utils import utc_now, vn_now


class OpenTradeFilter:
    def __init__(self, config: dict):
        self.cfg = config

    def check(self, symbol, direction, strategy_name, pattern,
               timeframe, regime, score, ml_prob, components,
               atr_ratio=None, db=None) -> Tuple[bool, str]:

        # 1. Bật / Tắt Filter
        if not self.cfg.get("enabled", False):
            return True, "filter_disabled"

        identity = self.cfg.get("identity", {})

        # ========================================================
        # A. KHỐI IDENTITY (Fix triệt để lỗi fallback lọt lưới)
        # ========================================================

        # 2. Kiểm tra Direction
        allowed_dirs = identity.get("directions")
        if allowed_dirs is not None and len(allowed_dirs) > 0:
            if direction not in allowed_dirs:
                return False, f"direction_blocked_{direction}"

        # 3. Kiểm tra Strategy
        allowed_strats = identity.get("strategies")
        if allowed_strats is not None and len(allowed_strats) > 0:
            if strategy_name not in allowed_strats:
                return False, f"strategy_blocked_{strategy_name}"

        # 4. Kiểm tra Pattern
        allowed_patterns = identity.get("patterns")
        if allowed_patterns is not None and len(allowed_patterns) > 0:
            if pattern not in allowed_patterns:
                return False, f"pattern_blocked_{pattern}"

        # 5. Kiểm tra Timeframe
        allowed_tfs = identity.get("timeframes")
        if allowed_tfs is not None and len(allowed_tfs) > 0:
            if timeframe not in allowed_tfs:
                return False, f"timeframe_blocked_{timeframe}"

        # 6. Kiểm tra Symbol Whitelist / Blacklist
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
        # B. KHỐI MARKET CONDITION & SCORE
        # ========================================================

        mkt = self.cfg.get("market_condition", {})
        allowed_regimes = mkt.get("allowed_regimes")
        if allowed_regimes is not None and len(allowed_regimes) > 0:
            if regime not in allowed_regimes:
                return False, f"regime_blocked_{regime}"

        if atr_ratio is not None:
            min_atr = mkt.get("min_atr_pct", 0)
            max_atr = mkt.get("max_atr_pct", 0)
            if min_atr > 0 and atr_ratio < min_atr: return False, "atr_too_low"
            if max_atr > 0 and atr_ratio > max_atr: return False, "atr_too_high"

        sc = self.cfg.get("score", {})
        if score < sc.get("min_overall", 0): return False, "score_below_filter"
        
        if ml_prob is not None and sc.get("min_ml_prob", 0) > 0:
            if ml_prob < sc["min_ml_prob"]: return False, "ml_prob_below_filter"
            
        if components:
            if sc.get("min_trend_score", 0) > 0:
                if components.get("trend_score", 0) < sc["min_trend_score"]:
                    return False, "trend_below_filter"
            if sc.get("min_mtf_score", 0) > 0:
                if components.get("mtf_score", 0) < sc["min_mtf_score"]:
                    return False, "mtf_below_filter"

        # ========================================================
        # C. KHỐI POSITION & TIME
        # ========================================================

        if db is not None:
            ok, reason = self._check_position(db, symbol, strategy_name, timeframe)
            if not ok: return False, reason

        time_cfg = self.cfg.get("time", {})
        if time_cfg.get("enabled", False):
            ok, reason = self._check_time(time_cfg)
            if not ok: return False, reason

        return True, "passed"

    def _check_position(self, db, symbol, strategy_name, timeframe):
        from app.db.models import Signal, PendingSignal
        from sqlalchemy import func

        pos  = self.cfg.get("position", {})
        mode = get_current_mode()

        max_conc = pos.get("max_concurrent_trades", 999)
        if db.query(Signal).filter(Signal.status == "OPEN").count() >= max_conc:
            return False, "max_concurrent_reached"

        if mode != TradingMode.PAPER:
            if db.query(Signal).filter(
                    Signal.symbol == symbol, Signal.status == "OPEN").count():
                return False, "live_symbol_occupied"
            if db.query(PendingSignal).filter(
                    PendingSignal.symbol == symbol,
                    PendingSignal.status == "WAIT").count():
                return False, "live_symbol_pending_exists"
        else:
            max_sym = pos.get("max_per_symbol", 1)
            if db.query(Signal).filter(
                    Signal.symbol        == symbol,
                    Signal.strategy_name == strategy_name,
                    Signal.timeframe     == timeframe,
                    Signal.status        == "OPEN").count() >= max_sym:
                return False, "max_per_symbol"

        max_tf_cfg = pos.get("max_per_timeframe", {})
        tf_limit   = max_tf_cfg.get(timeframe, 999)
        if db.query(Signal).filter(
                Signal.timeframe == timeframe,
                Signal.status    == "OPEN").count() >= tf_limit:
            return False, f"max_per_tf_{timeframe}"

        # ── Daily trades — dùng UTC range của ngày VN hôm nay ──
        max_daily = pos.get("max_daily_trades", 0)
        if max_daily > 0:
            from app.core.time_utils import vn_day_to_utc_range
            import datetime
            today_start_utc, _ = vn_day_to_utc_range(
                vn_now().date().isoformat()     # ngày hôm nay theo VN
            )
            if db.query(Signal).filter(
                    Signal.created_at >= today_start_utc).count() >= max_daily:
                return False, "max_daily_trades"

        # ── Daily loss — cùng logic ──────────────────────────
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

        # ── Loss streak ───────────────────────────────────────
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
        # Hiển thị / check giờ theo VN — dùng vn_now()
        now_vn       = vn_now()
        allowed_days = time_cfg.get("allowed_days", list(range(7)))
        if now_vn.weekday() not in allowed_days:
            return False, "day_restricted"

        hours = time_cfg.get("allowed_hours", {"start": "00:00", "end": "23:59"})
        sh, sm = map(int, hours["start"].split(":"))
        eh, em = map(int, hours["end"].split(":"))
        cur    = now_vn.hour * 60 + now_vn.minute
        if not (sh * 60 + sm <= cur <= eh * 60 + em):
            return False, "outside_hours"

        # Funding blackout — tính theo UTC
        blackout = time_cfg.get("blackout_minutes_before_funding", 0)
        if blackout > 0:
            now_utc = utc_now()
            for fh in [0, 8, 16]:
                from datetime import timedelta
                ft = now_utc.replace(hour=fh, minute=0, second=0, microsecond=0)
                if ft <= now_utc:
                    ft += timedelta(days=1)
                if (ft - now_utc).total_seconds() / 60 <= blackout:
                    return False, "funding_blackout"

        return True, "ok"


def get_open_trade_filter(cfg=None) -> OpenTradeFilter:
    if cfg is None:
        from app.services.config_service import get_runtime_config
        cfg = get_runtime_config().get("OPEN_TRADE_FILTER", {"enabled": False})
    return OpenTradeFilter(cfg)
