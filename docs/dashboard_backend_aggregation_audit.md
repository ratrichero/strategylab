# Dashboard Backend Aggregation Audit

Status: IMPORTANT - planning note only, no runtime migration done here.

## Problem

Several dashboard/analysis pages still load raw signal rows with `limit=10000` and compute KPI, grouping, filters, heatmaps, and portfolio curves in the browser. Once closed trades exceed 10k, these screens can become inaccurate because the frontend only sees the first page. They will also become slower as row volume grows.

Target direction: frontend sends filters, backend returns ready-to-render aggregates, paginated rows, and filter options.

## Pages Audited

### DashboardPage

Current:
- Fetches closed trades with `/api/signals?include_manual=true&limit=10000`.
- Fetches active realtime with `/api/signals?status=OPEN&limit=10000`.
- Computes closed-trade metrics, win rate, profit factor, expectancy, Sharpe, streaks, long/short WR, avg duration, portfolio curves, regime breakdown, and pattern heatmap in FE.
- Recent Trades is local filter/search over loaded rows.

Target:
- Keep active and pending realtime endpoints.
- Move closed KPI, portfolio curve, regime breakdown, heatmap, option lists, and recent-trade pagination to backend.

### SignalsPage

Current:
- Loads raw signals into `allSignals`.
- Computes filtered trades, KPI, performance by group, pattern heatmap, indicator distribution, and trade list locally.
- Also calls `/api/signal-analysis` for many tab-specific aggregates.

Target:
- Replace local raw signal dependency with:
  - backend overview KPI,
  - group performance,
  - pattern/timeframe heatmap,
  - indicator distribution,
  - paginated trade list.
- Keep `/api/signal-analysis` behavior initially, but wrap it behind typed dashboard endpoints.

### IndicatorsPage

Current:
- Loads `/api/signals?limit=10000` to build local filtered data.
- Computes KPI, threshold optimizer, indicator scatter sample, distribution, win/loss averages, and regime fingerprint locally.
- Some heatmaps/buckets already use `/api/signal-analysis`.

Target:
- Backend endpoints for indicator KPI, threshold optimizer, scatter sample, distribution, outcome averages, and regime fingerprint.
- Frontend should not need raw signal rows except optional drilldown table.

### EdgeDiscoveryPage

Current:
- Most analytics already come from `/api/signal-analysis`.
- Still loads `/api/signals?limit=10000` only to derive strategies/patterns.
- KPI is computed client-side from returned aggregate rows.

Target:
- Replace raw signal fetch with `/api/filter-options`.
- Optionally provide `/api/edge/overview` KPI so FE does not recompute weighted averages.

### SimulationPage

Current:
- Backtest/replay itself is backend job-based and paginated.
- Raw signal fetch is used only to populate strategy/pattern options.

Target:
- Replace raw signal fetch with `/api/filter-options`.
- Keep job/summary/rows API pattern.

### ResearchPage

Current:
- Main research run is backend `/api/research/run`.
- FE still performs optional Binance kline simulation and computes portfolio/regime/RSI/pattern/score summaries locally on returned trade sample.
- Also fetches raw signals for strategy/pattern options.

Target:
- Replace option fetch with `/api/filter-options`.
- Decide whether kline simulation remains FE-owned or moves to backend job.
- For large samples, backend should return summary aggregates and paginated rows.

### ManualBehaviorPage

Current:
- Loads `/api/signals?limit=10000`, derives manual outcomes, filters, KPI, standard-vs-manual comparison, and detail table locally.
- Important because MANUAL inclusion semantics differ from default WIN/LOSS.

Target:
- Dedicated backend endpoint for manual behavior:
  - derived outcome logic in SQL/service,
  - KPI,
  - standard/manual comparison,
  - paginated detail rows.
- Preserve default WIN/LOSS elsewhere; include MANUAL only where explicitly requested.

### PlaceholderPages

Current:
- Some placeholder/utility pages fetch `/api/signals?limit=10000` and compute small summaries locally.

Target:
- Lower priority, but should use shared filter-options and aggregate endpoints if these pages become production-facing.

## Backend Gaps

Existing stub files:
- `app/api/dashboard/analysis.py`
- `app/api/dashboard/edge.py`
- `app/api/dashboard/performance_api.py`

Existing generic API:
- `/api/signal-analysis` already contains many SQL aggregates, but it is query-name driven and not ideal as a long-term FE contract.

Needed shared backend layer:
- A filter builder used consistently across all analytics endpoints.
- A single source of truth for VN date parsing, status inclusion, engine version mode, symbol include/exclude, score ranges, strategy/pattern/regime/direction/timeframe filters.
- Materialized views or summary views for heavy closed-trade analytics.

## Proposed API Surface

### Shared

- `GET /api/filter-options`
  - Returns strategies, patterns, regimes, engine_versions, timeframes, directions, symbols.
  - Accepts optional status scope and date range.

- `POST /api/analytics/filters/preview`
  - Returns count of rows matching filters without transferring rows.

### Dashboard

- `POST /api/dashboard/overview`
  - KPI, trades today, total trades, win/loss, PF, expectancy, Sharpe, streaks, duration, long/short WR.

- `POST /api/dashboard/portfolio`
  - Compounding/fixed equity curve, drawdown, NAV summary.

- `POST /api/dashboard/breakdowns`
  - Regime breakdown, pattern/timeframe heatmap, optional direction/timeframe/strategy groups.

- `POST /api/dashboard/recent-trades`
  - Paginated closed trades, search symbols, sort by exit_time.

- `GET /api/dashboard/active-signals`
  - Realtime from `signals` where `status='OPEN'`.

### Signals / Indicators / Edge

- `POST /api/signals/overview`
- `POST /api/signals/group-performance`
- `POST /api/signals/heatmaps`
- `POST /api/signals/trades`
- `POST /api/indicators/overview`
- `POST /api/indicators/distribution`
- `POST /api/indicators/thresholds`
- `POST /api/indicators/scatter`
- `POST /api/indicators/regime-fingerprint`
- `POST /api/edge/overview`
- `POST /api/edge/{panel}`

### Manual Behavior

- `POST /api/manual-behavior/overview`
- `POST /api/manual-behavior/comparison`
- `POST /api/manual-behavior/trades`

## Data Layer Direction

Use `mv_signal_performance` as the primary closed-trade enriched source.

Consider adding later:
- `mv_signal_daily_performance`
- `mv_signal_group_performance`
- `mv_signal_indicator_buckets`
- `mv_equity_curve_daily`

Rules:
- `OPEN` always realtime from `signals`.
- Closed default is `WIN/LOSS`.
- `MANUAL` is included only when endpoint or request explicitly asks for it.
- Detail tables are paginated; aggregate endpoints never return raw full datasets.

## Implementation Phases

1. Add shared filter schema and SQL condition builder.
2. Add `/api/filter-options`; replace every raw signal fetch used only for dropdowns.
3. Migrate DashboardPage metrics and breakdowns to backend endpoints.
4. Migrate SignalsPage local KPI/group/heatmap/trade list.
5. Migrate IndicatorsPage local computations.
6. Add ManualBehavior dedicated endpoints.
7. Review Research/Simulation for remaining option fetches and large-sample summaries.
8. Add tests comparing old frontend-derived calculations against backend responses on a fixed fixture.

## Acceptance Criteria

- No production analytics page relies on `/api/signals?limit=10000` for correctness.
- Raw trade rows are only loaded through paginated table endpoints.
- Filter semantics are consistent across Dashboard, Signals, Indicators, Edge, Research, Simulation, and Manual Behavior.
- Default analytics remain WIN/LOSS only.
- Manual-inclusive analytics require explicit `include_manual` or a manual-specific endpoint.
