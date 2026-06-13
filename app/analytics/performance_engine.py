import numpy as np
from typing import List, Dict


def calculate_performance(trades: list) -> Dict:
    if not trades: return _empty()
    returns = np.array([float(t.result_percent or 0) for t in trades])
    total = len(returns); wins = int((returns > 0).sum()); losses = total - wins
    wr = wins/total*100 if total > 0 else 0
    avg_win  = float(returns[returns>0].mean()) if wins   > 0 else 0
    avg_loss = float(returns[returns<0].mean()) if losses > 0 else 0
    gp = float(returns[returns>0].sum()) if wins   > 0 else 0
    gl = abs(float(returns[returns<0].sum())) if losses > 0 else 1
    pf = round(gp/gl, 2) if gl > 0 else 999
    exp    = round(float(returns.mean()), 4)
    sharpe = round(float(returns.mean()/(returns.std()+1e-10)*np.sqrt(252)), 2)
    equity = 10000.0; peak = equity; max_dd = 0
    cur_streak = max_cw = max_cl = 0
    for r in returns:
        equity *= (1+r/100); peak = max(peak, equity)
        max_dd = max(max_dd, (peak-equity)/peak*100)
        if r > 0:
            cur_streak = cur_streak+1 if cur_streak > 0 else 1; max_cw = max(max_cw, cur_streak)
        else:
            cur_streak = cur_streak-1 if cur_streak < 0 else -1; max_cl = max(max_cl, abs(cur_streak))
    return {
        "total_trades": total, "wins": wins, "losses": losses,
        "winrate_percent": round(wr,1), "avg_win_percent": round(avg_win,3),
        "avg_loss_percent": round(avg_loss,3), "profit_factor": pf,
        "expectancy_percent": round(exp*100,3), "sharpe_ratio": sharpe,
        "max_drawdown_percent": round(max_dd,2), "final_equity": round(equity,2),
        "gross_profit": round(gp,2), "gross_loss": round(gl,2),
        "max_consecutive_wins": max_cw, "max_consecutive_losses": max_cl,
    }


def _empty(): return {
    "total_trades":0,"wins":0,"losses":0,"winrate_percent":0,
    "avg_win_percent":0,"avg_loss_percent":0,"profit_factor":0,
    "expectancy_percent":0,"sharpe_ratio":0,"max_drawdown_percent":0,
    "final_equity":10000,"gross_profit":0,"gross_loss":0,
    "max_consecutive_wins":0,"max_consecutive_losses":0,
}
