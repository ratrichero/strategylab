from typing import Optional, Tuple
import pandas as pd
from app.strategies.base import BaseStrategy, SignalResult, StrategyWeights

class ContextualEdgeStrategyV1(BaseStrategy):
    """
    Chiến thuật thử nghiệm tổng hợp các Edge từ dữ liệu thực chiến.
    Được chia thành các Pattern độc lập đại diện cho các "Sweet Spots" hoặc "Good Spots".
    Mỗi Pattern sẽ có bộ lọc Context (Regime, MTF, RSI) riêng biệt ở bước Score.
    """
    STRATEGY_NAME = "contextual_edge_v1"
    DEFAULT_THRESHOLD = 8.0
    
    WEIGHTS = {
        "15m": StrategyWeights(trend=0.25, momentum=0.25, volume=0.15, pattern=0.10, mtf=0.25, structure=0.0),
        "4h":  StrategyWeights(trend=0.30, momentum=0.20, volume=0.10, pattern=0.10, mtf=0.30, structure=0.0),
    }

    # Định nghĩa các Pattern Name để Tracking
    PAT_15M_LONG_PB  = "L Pullback 15m"
    PAT_4H_SHORT_PB  = "S Bearish Pullback 4h"
    PAT_15M_SHORT_REV= "S Reversal 15m"
    PATTERN_THRESHOLDS = {
        PAT_15M_LONG_PB: 8.0,
        PAT_4H_SHORT_PB: 8.0,
        PAT_15M_SHORT_REV: 8.0,
    }

    def detect(self, df, timeframe, symbol=None, trend_df=None, context_df=None, cfg=None):
        if timeframe not in ["15m", "4h"]:
            return None

        if len(df) < 5: return None
        prev2 = df.iloc[-4]; prev = df.iloc[-3]; curr = df.iloc[-2]
        
        close = float(curr["close"]); open_p = float(curr["open"])
        high = float(curr["high"]); low = float(curr["low"])
        ema50 = float(curr.get("ema50") or 0); ema200 = float(curr.get("ema200") or 0)
        atr = float(curr.get("atr") or 0)
        
        body = abs(close - open_p)
        full_range = high - low
        if full_range == 0 or ema200 == 0 or atr == 0: return None

        # ---------------------------------------------------------
        # PATTERN 1: 15m Long Pullback (Data: RR 2.9, Winrate tốt)
        # ---------------------------------------------------------
        if timeframe == "15m" and close > ema200 and ema50 > ema200:
            if abs(close - ema50) < (atr * 1.5) and close > open_p: # Gần EMA50 và là nến xanh
                return SignalResult(strategy_name=self.STRATEGY_NAME, direction="LONG", 
                                    pattern=self.PAT_15M_LONG_PB, valid=True)

        # ---------------------------------------------------------
        # PATTERN 2: 4h Short Pullback (Data: RR 2.8, Sweetspot Bear/High MTF)
        # ---------------------------------------------------------
        if timeframe == "4h" and close < ema200 and ema50 < ema200:
            if abs(close - ema50) < (atr * 1.5) and close < open_p: # Gần EMA50 và nến đỏ
                return SignalResult(strategy_name=self.STRATEGY_NAME, direction="SHORT", 
                                    pattern=self.PAT_4H_SHORT_PB, valid=True)

        # ---------------------------------------------------------
        # PATTERN 3: 15m Short Reversal (Shooting Star / Bearish Engulfing)
        # ---------------------------------------------------------
        if timeframe == "15m" and close < ema200:
            upper_wick = high - max(close, open_p)
            lower_wick = min(close, open_p) - low
            
            # Shooting Star
            if upper_wick > body * 2 and lower_wick < body:
                return SignalResult(strategy_name=self.STRATEGY_NAME, direction="SHORT", 
                                    pattern=self.PAT_15M_SHORT_REV, valid=True)
            # Bearish Engulfing
            if (prev["close"] > prev["open"] and close < open_p and
                open_p >= prev["close"] and close <= prev["open"]):
                return SignalResult(strategy_name=self.STRATEGY_NAME, direction="SHORT", 
                                    pattern=self.PAT_15M_SHORT_REV, valid=True)

        return None

    def score(self, df, signal, timeframe, symbol=None, trend_df=None, context_df=None, regime="SIDEWAYS", cfg=None)-> SignalResult:
        cfg = cfg or {}
        weights = self.get_weights(timeframe)
        last = df.iloc[-1]
        
        trend_s = self._calc_trend_score(df, signal.direction)
        vol_s, vol_ratio = self._calc_volume_score(df, cfg)
        mtf_s = self._calc_mtf_score(signal.direction, trend_df, context_df, cfg)
        mom_s = self._calc_momentum_score(df, signal.direction) # Dùng momentum chuẩn base
        total_pen, pen_n = self._calc_penalty(df, signal.direction, regime, vol_ratio, cfg)

        rsi = float(last.get("rsi") or 50)
        rsi_prev = float(df.iloc[-2].get("rsi") or 50)

        # =========================================================
        # CONTEXTUAL FILTERS DỰA TRÊN TỪNG PATTERN RIÊNG BIỆT
        # Bóp méo điểm số (Buff/Penalty) dựa trên Data Edge
        # =========================================================
        
        buff_score = 0.0

        if signal.pattern == self.PAT_15M_LONG_PB:
            # 1. Filter cho Long 15m Pullback
            if vol_ratio is not None and vol_ratio > 2.0:
                pen_n -= 1.0 # Data: LONG mà Vol > 2.0 thì tịt (RR 0.119)
            if (rsi - rsi_prev) > 0:
                buff_score += 1.0 # Data: RSI_Slope > 0 Winrate 77.8%
            if regime == "BEAR":
                pen_n -= 1.5 # Tuyệt đối không Long pullback khi Regime Bear

        elif signal.pattern == self.PAT_4H_SHORT_PB:
            # 2. Filter cho 4h Bearish Pullback
            if regime == "BEAR" and mtf_s >= 0.6:
                buff_score += 1.5 # Data: Sweetspot 4h SHORT BEAR High_MTF -> Buff điểm đè chiến thuật khác
            if mtf_s < 0.4:
                pen_n -= 1.0 # Mất đồng thuận MTF -> Phạt nặng

        elif signal.pattern == self.PAT_15M_SHORT_REV:
            # 3. Filter cho 15m Short Reversal (Phản ứng tại đỉnh/cản)
            if regime == "BULL":
                pen_n -= 1.5 # Data: Short reversal ở Bull market rất rủi ro
            if mtf_s >= 0.7:
                buff_score += 1.0 # Data: Bắt đảo chiều ngắn hạn nếu Khung lớn ủng hộ (MTF cao)

        # =========================================================

        # TỔNG HỢP VÀ CHUẨN HOÁ ĐIỂM
        t_n = self._normalize(trend_s, self.MAX_TREND)
        m_n = self._normalize(mom_s,   self.MAX_MOMENTUM)
        v_n = self._normalize(vol_s,   self.MAX_VOLUME)
        
        raw, final = self._apply_weights_and_scale(t_n, m_n, v_n, 1.0, mtf_s, 0.0, pen_n, weights)
        
        # Cộng điểm Buff Contextual (Không cho vượt quá 10)
        final = min(10.0, final + buff_score)

        signal.trend_score = trend_s; signal.momentum_score = mom_s; signal.volume_score = vol_s
        signal.mtf_score = mtf_s; signal.penalty_norm = pen_n
        signal.rule_score_raw = raw; signal.final_score = round(final, 2)
        signal.components = self._build_components(signal, weights)
        
        return signal
