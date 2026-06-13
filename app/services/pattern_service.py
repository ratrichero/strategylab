"""Pattern Service — backward compat wrapper."""

def detect_pattern(df):
    try:
        from app.strategies.candlestick_strategy import CandlestickStrategy
        return CandlestickStrategy()._detect_pattern(df)
    except Exception:
        return _inline(df)

def _inline(df):
    if len(df) < 5: return None
    prev2=df.iloc[-4]; prev=df.iloc[-3]; curr=df.iloc[-2]
    if prev["close"]<prev["open"] and curr["close"]>curr["open"] and curr["open"]<=prev["close"] and curr["close"]>=prev["open"]: return "Bullish Engulfing"
    if prev["close"]>prev["open"] and curr["close"]<curr["open"] and curr["open"]>=prev["close"] and curr["close"]<=prev["open"]: return "Bearish Engulfing"
    body=abs(curr["close"]-curr["open"]); fr=curr["high"]-curr["low"]
    if fr==0: return None
    uw=curr["high"]-max(curr["close"],curr["open"]); lw=min(curr["close"],curr["open"])-curr["low"]
    if lw>body*2 and uw<body: return "Hammer"
    if uw>body*2 and lw<body: return "Shooting Star"
    if prev2["close"]<prev2["open"] and abs(prev["close"]-prev["open"])<abs(prev2["close"]-prev2["open"])*0.5 and curr["close"]>curr["open"] and curr["close"]>prev2["open"]: return "Morning Star"
    if prev2["close"]>prev2["open"] and abs(prev["close"]-prev["open"])<abs(prev2["close"]-prev2["open"])*0.5 and curr["close"]<curr["open"] and curr["close"]<prev2["open"]: return "Evening Star"
    if body/fr>0.9 and curr["close"]>curr["open"]: return "Bullish Marubozu"
    if body/fr>0.9 and curr["close"]<curr["open"]: return "Bearish Marubozu"
    return None
