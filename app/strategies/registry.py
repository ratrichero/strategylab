from typing import Dict, List, Optional, Tuple
from app.strategies.base import BaseStrategy
from app.strategies.candlestick_strategy    import CandlestickStrategy
from app.strategies.breakout_strategy       import BreakoutStrategy
from app.strategies.mean_reversion_strategy import MeanReversionStrategy
from app.strategies.pullback_strategy       import PullBackStrategy
from app.strategies.trend_following_strategy import TrendFollowingStrategy
from app.strategies.contextual_edge_v1      import ContextualEdgeStrategyV1
from app.strategies.grid_reversion_strategy import GridReversionStrategy   

_REGISTRY: Dict[str, BaseStrategy] = {
    "candlestick":    CandlestickStrategy(),
    "breakout":       BreakoutStrategy(),
    "mean_reversion": MeanReversionStrategy(),
    "pullback":       PullBackStrategy(),
    "trend_following":TrendFollowingStrategy(),
    "contextual_edge_v1": ContextualEdgeStrategyV1(),
    "grid_reversion_v1": GridReversionStrategy(),
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


def merge_default_strategy_config(runtime_cfg: dict, default_threshold: float = 8.0) -> tuple[dict, bool]:
    strategy_cfg = runtime_cfg.get("STRATEGY_CONFIG") or {}
    if not isinstance(strategy_cfg, dict):
        strategy_cfg = {}

    modified = False
    for name, strat in _REGISTRY.items():
        default_block = strat.get_default_strategy_config(default_threshold)
        block = strategy_cfg.get(name)
        if not isinstance(block, dict):
            strategy_cfg[name] = default_block
            modified = True
            continue

        if "threshold" not in block:
            block["threshold"] = default_block["threshold"]
            modified = True

        if not isinstance(block.get("patterns"), dict):
            block["patterns"] = default_block["patterns"]
            modified = True
        else:
            for pattern, threshold in default_block["patterns"].items():
                if pattern not in block["patterns"]:
                    block["patterns"][pattern] = threshold
                    modified = True

        if not isinstance(block.get("symbols"), (str, list, tuple, set)):
            block["symbols"] = default_block["symbols"]
            modified = True

        strategy_cfg[name] = block

    runtime_cfg["STRATEGY_CONFIG"] = strategy_cfg
    return runtime_cfg, modified


# ============================================================
# STRATEGY CONFIG HELPERS
# ← CHANGED: thêm verify + threshold resolver để hỗ trợ
#   per-strategy / per-pattern threshold (Phương án 2)
#   STRATEGY_THRESHOLDS đã được gộp vào STRATEGY_CONFIG
# ============================================================

def verify_strategy_config(runtime_cfg: dict) -> None:
    """
    Verify mềm STRATEGY_CONFIG:
    - strategy key có tồn tại trong _REGISTRY không
    - patterns có phải dict không
    - threshold có parse float được không
    Chỉ warning, không raise, không chặn scan.
    """
    strategy_cfg = runtime_cfg.get("STRATEGY_CONFIG")
    if not isinstance(strategy_cfg, dict):
        print("[STRATEGY CONFIG WARN] STRATEGY_CONFIG không phải dict, bỏ qua verify")
        return

    for strat_key, strat_val in strategy_cfg.items():
        # C: verify strategy key match registry
        if strat_key not in _REGISTRY:
            print(f"[STRATEGY CONFIG WARN] Unknown strategy key in STRATEGY_CONFIG: '{strat_key}' (không có trong registry)")

        if not isinstance(strat_val, dict):
            print(f"[STRATEGY CONFIG WARN] Config của '{strat_key}' không phải dict")
            continue

        # verify threshold parse được float
        threshold = strat_val.get("threshold")
        if threshold is not None:
            try:
                float(threshold)
            except (TypeError, ValueError):
                print(f"[STRATEGY CONFIG WARN] threshold của '{strat_key}' không parse được float: {threshold!r}")
        
        # verify symbols là str/list/tuple/set
        symbols = strat_val.get("symbols")
        if symbols is not None and not isinstance(symbols, (str, list, tuple, set)):
            print(f"[STRATEGY CONFIG WARN] symbols của '{strat_key}' không hợp lệ: {type(symbols)}")

        # verify patterns là dict
        patterns = strat_val.get("patterns")
        if patterns is not None:
            if not isinstance(patterns, dict):
                print(f"[STRATEGY CONFIG WARN] patterns của '{strat_key}' không phải dict: {type(patterns)}")
            else:
                for pat_key, pat_threshold in patterns.items():
                    try:
                        float(pat_threshold)
                    except (TypeError, ValueError):
                        print(f"[STRATEGY CONFIG WARN] threshold của pattern '{pat_key}' trong '{strat_key}' không hợp lệ: {pat_threshold!r}")

    # verify active strategies có đủ config không (warn nhẹ, không chặn)
    active_raw = runtime_cfg.get("ACTIVE_STRATEGIES", "candlestick")
    active_names = [n.strip() for n in (active_raw.split(",") if isinstance(active_raw, str) else active_raw) if n.strip()]
    for name in active_names:
        if name not in strategy_cfg:
            print(f"[STRATEGY CONFIG WARN] Strategy '{name}' đang active nhưng chưa có config trong STRATEGY_CONFIG → sẽ dùng global SCORE_THRESHOLD")


def get_effective_threshold(
    strategy_name: str,
    pattern: Optional[str],
    runtime_cfg: dict
) -> float:
    """
    Resolve threshold theo priority:
      1. STRATEGY_CONFIG[strategy]["patterns"][pattern]  ← per-pattern (cao nhất)
      2. STRATEGY_CONFIG[strategy]["threshold"]          ← per-strategy
      3. global SCORE_THRESHOLD                          ← fallback cuối

    Note: STRATEGY_THRESHOLDS đã được gộp vào STRATEGY_CONFIG,
          không còn dùng làm fallback riêng nữa.

    Returns:
        float threshold hiệu lực cho candidate này
    """
    global_threshold = float(runtime_cfg.get("SCORE_THRESHOLD", 5.0))
    strategy_cfg     = runtime_cfg.get("STRATEGY_CONFIG") or {}

    strat_block = strategy_cfg.get(strategy_name)
    if not isinstance(strat_block, dict):
        # strategy không có config riêng → fallback global
        return global_threshold

    # Priority 1: per-pattern threshold
    if pattern is not None:
        patterns_cfg = strat_block.get("patterns") or {}
        if isinstance(patterns_cfg, dict) and pattern in patterns_cfg:
            try:
                return float(patterns_cfg[pattern])
            except (TypeError, ValueError):
                print(f"[THRESHOLD WARN] pattern threshold parse lỗi: {strategy_name}/{pattern}")

    # Priority 2: per-strategy threshold
    strat_threshold = strat_block.get("threshold")
    if strat_threshold is not None:
        try:
            return float(strat_threshold)
        except (TypeError, ValueError):
            print(f"[THRESHOLD WARN] strategy threshold parse lỗi: {strategy_name}")

    # Priority 3: global fallback
    return global_threshold


def evaluate_candidates(
    signal_candidates: list,
    runtime_cfg: dict,
    derivative_bias_fn,          # callable(symbol, timeframe, direction) → float
    bias_scale_map: dict,
    pre_buffer: float,
    symbol: str,
    timeframe: str,
) -> Tuple[Optional[object], List[dict]]:
    """
    Phương án 2 — Evaluate từng candidate riêng:
      1. Pre-filter: technical_score < global_floor → loại sớm
      2. Tính derivative bias riêng cho từng candidate
      3. Resolve effective_threshold riêng theo strategy/pattern
      4. Đánh dấu pass/fail
      5. Trả về:
         - best_passed: candidate pass tốt nhất (final_score cao nhất)
         - eval_results: list metadata để ghi debug

    Returns:
        (best_passed_or_None, eval_results)
        - Nếu không có candidate nào pass → best_passed = None
        - eval_results luôn chứa toàn bộ để ghi ScanDebug
    """
    global_threshold = float(runtime_cfg.get("SCORE_THRESHOLD", 5.0))
    pre_buffer_val   = float(pre_buffer)
    technical_floor  = global_threshold - pre_buffer_val

    eval_results = []
    passed       = []

    for sig in signal_candidates:
        technical_score = float(sig.final_score)

        # ── Pre-filter: loại sớm nếu technical quá thấp ──────────
        if technical_score < technical_floor:
            eval_results.append({
                "sig":               sig,
                "technical_score":   technical_score,
                "derivative_bias":   0.0,
                "final_score":       technical_score,
                "effective_threshold": global_threshold,
                "passed":            False,
                "reject_reason":     "pre_filter_floor",
            })
            continue

        # ── Tính derivative bias cho candidate này ────────────────
        try:
            raw_bias    = derivative_bias_fn(
                symbol=symbol, timeframe=timeframe, direction=sig.direction
            )
            bias_scale  = bias_scale_map.get(timeframe, 0.6)
            deriv_bias  = round(float(raw_bias) * bias_scale, 4)
        except Exception as e:
            print(f"[EVAL WARN] derivative_bias lỗi cho {symbol}/{sig.strategy_name}: {e}")
            deriv_bias  = 0.0

        final_score = round(max(0.0, min(10.0, technical_score + deriv_bias)), 2)

        # ── Resolve threshold riêng cho candidate này ─────────────
        effective_threshold = get_effective_threshold(
            strategy_name=sig.strategy_name,
            pattern=sig.pattern,
            runtime_cfg=runtime_cfg,
        )

        is_passed = final_score >= effective_threshold

        eval_results.append({
            "sig":                sig,
            "technical_score":    technical_score,
            "derivative_bias":    deriv_bias,
            "final_score":        final_score,
            "effective_threshold": effective_threshold,
            "passed":             is_passed,
            "reject_reason":      None if is_passed else (
                f"score_threshold::{sig.strategy_name}::{sig.pattern}::{effective_threshold}"
            ),
        })

        if is_passed:
            passed.append(eval_results[-1])

    # ── Chọn best candidate ───────────────────────────────────────
    if passed:
        # Lấy candidate pass có final_score cao nhất
        best_eval = max(passed, key=lambda x: x["final_score"])
    else:
        # Không có candidate nào pass → lấy candidate mạnh nhất để ghi debug
        best_eval = max(eval_results, key=lambda x: x["final_score"]) if eval_results else None

    return best_eval, eval_results
