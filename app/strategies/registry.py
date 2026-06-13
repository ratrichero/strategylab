from typing import Dict, List, Optional
from app.strategies.base import BaseStrategy
from app.strategies.candlestick_strategy    import CandlestickStrategy
from app.strategies.breakout_strategy       import BreakoutStrategy
from app.strategies.mean_reversion_strategy import MeanReversionStrategy
from app.strategies.pullback_strategy       import PullBackStrategy
from app.strategies.trend_following_strategy import TrendFollowingStrategy

_REGISTRY: Dict[str, BaseStrategy] = {
    "candlestick":    CandlestickStrategy(),
    "breakout":       BreakoutStrategy(),
    "mean_reversion": MeanReversionStrategy(),
    "pullback":       PullBackStrategy(),
    "trend_following":TrendFollowingStrategy(),
}

def get_strategy(name: str) -> Optional[BaseStrategy]:
    return _REGISTRY.get(name)

def get_active_strategies(cfg: dict) -> List[BaseStrategy]:
    raw = cfg.get("ACTIVE_STRATEGIES", "candlestick")
    names = [n.strip() for n in (raw.split(",") if isinstance(raw, str) else raw) if n.strip()]
    result = [_REGISTRY[n] for n in names if n in _REGISTRY]
    return result if result else [_REGISTRY["candlestick"]]

def list_all() -> List[str]:
    return list(_REGISTRY.keys())

def register_strategy(name: str, strategy: BaseStrategy):
    _REGISTRY[name] = strategy
    print(f"✅ Registered: {name}")
