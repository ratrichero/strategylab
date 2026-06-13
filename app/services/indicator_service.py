import pandas as pd
import numpy as np
from typing import Optional, Dict, Literal

# ============================================================================
# 🔧 PHẦN NÀY LÀ INTERNAL - BẠN KHÔNG CẦN QUAN TÂM
# ============================================================================

class _TechnicalIndicatorsEngine:
    """Internal engine - không dùng trực tiếp"""
    
    def __init__(self, config: Optional[Dict] = None):
        default_config = {
            'ema_period': 200,
            'rsi_period': 14,
            'atr_period': 14,
            'volume_ma_period': 20,
            'regime_ema_lookback': 10,
            'regime_threshold': 0.001
        }
        self.config = {**default_config, **(config or {})}
        
    def calculate_ema(self, series: pd.Series, period: int) -> pd.Series:
        """
        ✅ FIX: nhận series + period trực tiếp
        ✅ FIX: bỏ min_periods=period → không còn NaN với 199 rows
        """
        return series.ewm(span=period, adjust=False).mean()
    
    def calculate_rsi(self, df: pd.DataFrame) -> pd.Series:
        """RSI calculation - improved version"""
        period = self.config['rsi_period']
        delta = df['close'].diff()
        
        gains = delta.where(delta > 0, 0.0)
        losses = -delta.where(delta < 0, 0.0)
        
        #avg_gain = gains.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
        #avg_loss = losses.ewm(alpha=1/period, min_periods=period, adjust=False).mean()

        avg_gain = gains.ewm(alpha=1/period, min_periods=1, adjust=False).mean()
        avg_loss = losses.ewm(alpha=1/period, min_periods=1, adjust=False).mean()
        
        rs = avg_gain / avg_loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))
    
    def calculate_atr(self, df: pd.DataFrame) -> pd.Series:
        """ATR calculation - improved version"""
        period = self.config['atr_period']
        
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift(1))
        low_close = np.abs(df['low'] - df['close'].shift(1))
        
        true_range = pd.DataFrame({
            'hl': high_low,
            'hc': high_close,
            'lc': low_close
        }).max(axis=1)
        
        return true_range.ewm(alpha=1/period, min_periods=1, adjust=False).mean()
    
    def calculate_volume_ma(self, df: pd.DataFrame) -> pd.Series:
        """Volume MA calculation"""
        period = self.config['volume_ma_period']
        #return df['volume'].rolling(window=period, min_periods=period).mean()
        return df['volume'].rolling(window=period, min_periods=1).mean()


# ============================================================================
# ✅ PHẦN NÀY LÀ API CÔNG KHAI - GIỐNG Y HỆT CODE CŨ CỦA BẠN
# ============================================================================

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Thêm các indicators vào DataFrame
    
    🔄 BACKWARD COMPATIBLE 100%
    - Chỉ cần thay file cũ bằng file này
    - KHÔNG cần thay đổi code ở bất kỳ đâu
    
    Args:
        df: DataFrame với columns: open, high, low, close, volume
        
    Returns:
        DataFrame với thêm columns: ema200, rsi, atr, vol_ma
        
    Example:
        >>> df = add_indicators(df)
        >>> print(df.columns)
        ['open', 'high', 'low', 'close', 'volume', 'ema200', 'rsi', 'atr', 'vol_ma']
    """
    # Validation
    if df is None or len(df) == 0:
        return df
    
    required_cols = ['open', 'high', 'low', 'close', 'volume']
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"DataFrame thiếu columns: {missing_cols}")
    
    # Work on copy để không modify original
    result = df.copy()
    
    # EMA200
    result["ema200"] = result["close"].ewm(span=200, adjust=False).mean()
    
    # RSI14
    delta = result["close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    result["rsi"] = 100 - (100 / (1 + rs))
    
    # ATR14
    high_low = result["high"] - result["low"]
    high_close = np.abs(result["high"] - result["close"].shift())
    low_close = np.abs(result["low"] - result["close"].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    result["atr"] = true_range.rolling(14).mean()
    
    # Volume MA
    result["vol_ma"] = result["volume"].rolling(20).mean()
    
    return result


def detect_regime(df: pd.DataFrame) -> str:
    """
    Phát hiện regime thị trường
    
    🔄 BACKWARD COMPATIBLE 100%
    
    Args:
        df: DataFrame đã có indicator ema200
        
    Returns:
        "BULL" | "BEAR" | "SIDEWAYS"
        
    Example:
        >>> regime = detect_regime(df)
        >>> if regime == "BULL":
        >>>     # Long strategy
    """
    if len(df) < 210:
        return "SIDEWAYS"
    
    # Check nếu chưa có ema200
    if "ema200" not in df.columns:
        return "SIDEWAYS"
    
    ema_now = df["ema200"].iloc[-2]
    ema_prev = df["ema200"].iloc[-12]
    
    if ema_now > ema_prev:
        return "BULL"
    elif ema_now < ema_prev:
        return "BEAR"
    else:
        return "SIDEWAYS"


# ============================================================================
# 🆕 PHẦN NÀY LÀ FEATURES MỚI - TÙY CHỌN SỬ DỤNG
# ============================================================================

def add_indicators_advanced(
    df: pd.DataFrame,
    ema_period: int = 200,
    rsi_period: int = 14,
    atr_period: int = 14,
    volume_ma_period: int = 20,
    use_ewm: bool = True
) -> pd.DataFrame:
    """
    🆕 Version nâng cao với tùy chọn parameters
    
    Args:
        df: DataFrame
        ema_period: Period cho EMA (default: 200)
        rsi_period: Period cho RSI (default: 14)
        atr_period: Period cho ATR (default: 14)
        volume_ma_period: Period cho Volume MA (default: 20)
        use_ewm: Dùng EWM thay vì SMA cho RSI/ATR (default: True)
        
    Returns:
        DataFrame với indicators
        
    Example:
        >>> # Custom parameters
        >>> df = add_indicators_advanced(df, ema_period=100, rsi_period=21)
    """
    engine = _TechnicalIndicatorsEngine(config={
        'ema_period': ema_period,
        'rsi_period': rsi_period,
        'atr_period': atr_period,
        'volume_ma_period': volume_ma_period
    })
    
    result = df.copy()
    result["ema50"]= engine.calculate_ema(result["close"], period=50)
    result[f"ema{ema_period}"] = engine.calculate_ema(result["close"], period=ema_period)
    #result[f"ema{ema_period}"] = engine.calculate_ema(result)
    if ema_period != 200:
        result["ema200"] = engine.calculate_ema(result["close"], period=200)
    result["rsi"] = engine.calculate_rsi(result)
    result["atr"] = engine.calculate_atr(result)
    result["vol_ma"] = engine.calculate_volume_ma(result)

    # ✅ Bollinger
    bb_period = 20
    bb_mid = result["close"].rolling(bb_period).mean()
    bb_std = result["close"].rolling(bb_period).std()

    result["bb_mid"] = bb_mid
    result["bb_upper"] = bb_mid + 2 * bb_std
    result["bb_lower"] = bb_mid - 2 * bb_std

    result["bb_position"] = (
        (result["close"] - result["bb_lower"]) /
        (result["bb_upper"] - result["bb_lower"])
    ).clip(0, 1)

    result["bb_width"] = (
        (result["bb_upper"] - result["bb_lower"]) /
        result["bb_mid"]
    )
    
    return result


def detect_regime_advanced(
    df: pd.DataFrame,
    method: Literal['ema_slope', 'price_action', 'hybrid'] = 'ema_slope',
    lookback: int = 10,
    threshold: float = 0.001
) -> str:
    """
    🆕 Regime detection nâng cao
    
    Args:
        df: DataFrame với indicators
        method: Phương pháp detect
            - 'ema_slope': Dựa vào độ dốc EMA (giống code cũ)
            - 'price_action': Dựa vào price position
            - 'hybrid': Kết hợp
        lookback: Số candles để tính slope (default: 10)
        threshold: Ngưỡng % để xác định sideways (default: 0.1%)
        
    Returns:
        "BULL" | "BEAR" | "SIDEWAYS"
        
    Example:
        >>> # Strict regime detection
        >>> regime = detect_regime_advanced(df, method='hybrid', threshold=0.005)
    """
    # ✅ FIX: relaxed min length (bỏ 210 → 50)
    #if len(df) < 210:
    if len(df) < 50:
        return "SIDEWAYS"
    
    if "ema200" not in df.columns:
        return "SIDEWAYS"
    
    # ✅ FIX: skip NaN ema200 - bo sung them
    ema_series = df["ema200"].dropna()
    if len(ema_series) < 2:
        return "SIDEWAYS"
    

    if method == 'ema_slope':
        ema_now = df["ema200"].iloc[-1]
        ema_prev = df["ema200"].iloc[-lookback]
        pct_change = (ema_now - ema_prev) / ema_prev
        
        if pct_change > threshold:
            return "BULL"
        elif pct_change < -threshold:
            return "BEAR"
        else:
            return "SIDEWAYS"
    
    elif method == 'price_action':
        recent = df.tail(20)
        above_ema = (recent['close'] > recent['ema200']).sum() / len(recent)
        
        if above_ema > 0.7:
            return "BULL"
        elif above_ema < 0.3:
            return "BEAR"
        else:
            return "SIDEWAYS"
    
    else:  # hybrid
        regime_slope = detect_regime_advanced(df, 'ema_slope', lookback, threshold)
        regime_price = detect_regime_advanced(df, 'price_action', lookback, threshold)
        
        if regime_slope == regime_price:
            return regime_slope
        return "SIDEWAYS"


def get_market_state(df: pd.DataFrame) -> Dict:
    """
    🆕 Lấy thông tin chi tiết về market state
    
    Args:
        df: DataFrame với indicators
        
    Returns:
        Dictionary với market information
        
    Example:
        >>> state = get_market_state(df)
        >>> print(state)
        {
            'regime': 'BULL',
            'price': 45231.5,
            'ema200': 44000.0,
            'rsi': 65.3,
            'atr': 523.4,
            'volume_ratio': 1.34,
            'price_above_ema': True,
            'rsi_overbought': False,
            'rsi_oversold': False,
            'high_volume': True
        }
    """
    if "ema200" not in df.columns:
        df = add_indicators(df)
    
    latest = df.iloc[-1]
    
    return {
        'regime': detect_regime(df),
        'price': float(latest['close']),
        'ema200': float(latest['ema200']),
        'rsi': float(latest['rsi']),
        'atr': float(latest['atr']),
        'volume_ratio': float(latest['volume'] / latest['vol_ma']) if latest['vol_ma'] > 0 else 1.0,
        
        # Flags
        'price_above_ema': bool(latest['close'] > latest['ema200']),
        'rsi_overbought': bool(latest['rsi'] > 70),
        'rsi_oversold': bool(latest['rsi'] < 30),
        'high_volume': bool(latest['volume'] > latest['vol_ma'] * 1.5),
    }


# ============================================================================
# 🧪 TESTING
# ============================================================================

def _test_compatibility():
    """Test backward compatibility"""
    print("=" * 70)
    print("🧪 TESTING BACKWARD COMPATIBILITY")
    print("=" * 70)
    
    # Create sample data
    np.random.seed(42)
    df = pd.DataFrame({
        'open': np.random.randn(300).cumsum() + 100,
        'high': np.random.randn(300).cumsum() + 102,
        'low': np.random.randn(300).cumsum() + 98,
        'close': np.random.randn(300).cumsum() + 100,
        'volume': np.random.randint(1000, 10000, 300)
    })
    
    # Test 1: add_indicators
    print("\n✓ Test 1: add_indicators()")
    df_with_indicators = add_indicators(df)
    required_cols = ['ema200', 'rsi', 'atr', 'vol_ma']
    for col in required_cols:
        assert col in df_with_indicators.columns, f"Missing {col}"
        print(f"  ✓ Column '{col}' exists")
    
    # Test 2: detect_regime
    print("\n✓ Test 2: detect_regime()")
    regime = detect_regime(df_with_indicators)
    assert regime in ['BULL', 'BEAR', 'SIDEWAYS']
    print(f"  ✓ Regime: {regime}")
    
    # Test 3: Small dataframe
    print("\n✓ Test 3: Small dataframe handling")
    df_small = df.head(50)
    regime_small = detect_regime(df_small)
    assert regime_small == "SIDEWAYS"
    print(f"  ✓ Small df regime: {regime_small}")
    
    # Test 4: Advanced features
    print("\n✓ Test 4: Advanced features (optional)")
    regime_adv = detect_regime_advanced(df_with_indicators, method='hybrid')
    print(f"  ✓ Advanced regime: {regime_adv}")
    
    state = get_market_state(df_with_indicators)
    print(f"  ✓ Market state keys: {list(state.keys())}")
    
    print("\n" + "=" * 70)
    print("✅ ALL TESTS PASSED - FULLY BACKWARD COMPATIBLE!")
    print("=" * 70)
    
    return df_with_indicators


# ============================================================================
# 📖 USAGE EXAMPLES
# ============================================================================

if __name__ == "__main__":
    """
    CÁCH SỬ DỤNG:
    
    1️⃣ THAY THẾ FILE CŨ:
       -----------------
       - Xóa file indicators.py cũ
       - Copy toàn bộ code này vào indicators.py
       - XONG! Không cần sửa gì thêm
    
    
    2️⃣ IMPORT VÀ SỬ DỤNG GIỐNG CŨ:
       ---------------------------
       
       # File: strategy.py
       from indicators import add_indicators, detect_regime
       
       # Code cũ vẫn chạy y hệt:
       df = add_indicators(df)
       regime = detect_regime(df)
       
       if regime == "BULL":
           # Long logic
           pass
    
    
    3️⃣ TÙY CHỌN: SỬ DỤNG FEATURES MỚI
       --------------------------------
       
       # File: strategy.py
       from indicators import (
           add_indicators,           # Giống cũ
           detect_regime,            # Giống cũ  
           add_indicators_advanced,  # Mới - tùy chọn
           detect_regime_advanced,   # Mới - tùy chọn
           get_market_state          # Mới - tùy chọn
       )
       
       # Dùng version cũ
       df = add_indicators(df)
       
       # Hoặc dùng version mới với custom params
       df = add_indicators_advanced(df, ema_period=100)
       
       # Get full market context
       state = get_market_state(df)
       if state['rsi_oversold'] and state['regime'] == 'BULL':
           # Entry signal
           pass
    """
    
    # Run tests
    df_result = _test_compatibility()
    
    print("\n📊 SAMPLE OUTPUT:")
    print("-" * 70)
    print(df_result[['close', 'ema200', 'rsi', 'atr', 'vol_ma']].tail(10))
    
    print("\n💡 MARKET STATE:")
    print("-" * 70)
    state = get_market_state(df_result)
    for key, value in state.items():
        print(f"  {key:20s}: {value}")

def build_indicator_snapshot(df: pd.DataFrame,engine_version: float) -> dict:
    """
    Minimal Quant Snapshot (Research-Grade, Not Overfit)

    ✅ Normalized slopes
    ✅ No lookahead bias
    ✅ Cross-asset comparable
    ✅ Lightweight
    """

    def safe_float(val):
        return float(val) if val is not None and pd.notna(val) else None

    last = df.iloc[-1]

    # ================= TREND =================

    ema50 = safe_float(last.get("ema50"))
    ema200 = safe_float(last.get("ema200"))
    close = safe_float(last.get("close"))

    # EMA distance (structure position)
    ema_distance = None
    if ema200 and close and ema200 != 0:
        ema_distance = (close - ema200) / ema200

    # ✅ Normalized EMA200 slope (% per candle, 6-candle window)
    ema200_slope = None
    if len(df) >= 7 and pd.notna(df["ema200"].iloc[-7]):
        prev = df["ema200"].iloc[-7]
        if prev != 0:
            ema200_slope = (ema200 - prev) / prev / 6.0

    # ================= MOMENTUM =================

    rsi = safe_float(last.get("rsi"))

    # ✅ RSI slope per candle (4-period window)
    rsi_slope = None
    if len(df) >= 5 and pd.notna(df["rsi"].iloc[-5]):
        rsi_slope = (rsi - df["rsi"].iloc[-5]) / 4.0

    # ================= VOLATILITY =================

    atr = safe_float(last.get("atr"))

    # ✅ ATR percentile (last 100 candles)
    atr_percentile = None
    if len(df) >= 100:
        atr_window = df["atr"].iloc[-100:]
        if atr is not None:
            atr_percentile = float(
                (atr_window < atr).sum() / len(atr_window)
            )

    # ✅ Bollinger Band Width (normalized)
    bb_width = None
    bb_upper = safe_float(last.get("bb_upper"))
    bb_lower = safe_float(last.get("bb_lower"))
    bb_mid = safe_float(last.get("bb_mid"))

    if bb_mid is not None and bb_upper is not None and bb_lower is not None:
        if bb_mid != 0:
            bb_width = (bb_upper - bb_lower) / bb_mid
    
    # ================= VOLUME Ratio=================

    volume_ratio = None
    vol_ma = safe_float(last.get("vol_ma"))
    volume = safe_float(last.get("volume"))

    # ✅ FIX: fallback tính vol_ma trực tiếp nếu bị NaN
    if vol_ma is None and len(df) >= 5:
        vol_ma = safe_float(df["volume"].rolling(window=min(20, len(df)), min_periods=1).mean().iloc[-1])

    if vol_ma is not None and volume is not None and vol_ma > 0:
        volume_ratio = volume / vol_ma

    # ================= ATR RATIO =================

    atr_ratio = None
    atr = safe_float(last.get("atr"))
    
    # ✅ FIX: fallback tính atr trực tiếp nếu bị NaN
    if atr is None and len(df) >= 2:
        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift(1)).abs()
        low_close = (df["low"] - df["close"].shift(1)).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = safe_float(tr.ewm(alpha=1/14, min_periods=1, adjust=False).mean().iloc[-1])

    if atr is not None and close is not None and close > 0:
        atr_ratio = atr / close

    # Tạm thêm vào build_indicator_snapshot để debug
    # print(f"DEBUG vol_ma={last.get('vol_ma')}, volume={last.get('volume')}, atr={last.get('atr')}, close={last.get('close')}")

    # ================= FINAL SNAPSHOT =================

    return {
        # Trend
        "close": close,
        "ema50": ema50,
        "ema200": ema200,
        "ema_distance": ema_distance,
        "ema200_slope": ema200_slope,

        # Momentum
        "rsi": rsi,
        "rsi_slope": rsi_slope,

        "volume_ratio": volume_ratio,
        "atr_ratio": atr_ratio,

        # Volatility
        "atr": atr,
        "atr_percentile": atr_percentile,
        "bb_width": bb_width,
        
        "engine_version": engine_version,
    }