from app.services.backtest.replay_loader import _normalize_date_input
from app.core.time_utils import vn_range_to_utc

for v in ['2026-06-19', '2026-06-19T00:00:00', '2026-06-19T23:59:59+00:00']:
    x = _normalize_date_input(v)
    print(v, type(x).__name__, x)

s, e = vn_range_to_utc('2026-06-19', '2026-06-19')
print('RANGE', s.isoformat(), e.isoformat())
