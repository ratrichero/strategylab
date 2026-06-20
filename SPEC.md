# QUANT RESEARCH LAB v2.0 — FRONTEND SPECIFICATION
> Last Updated: 2026-06-15

---

## 1. ARCHITECTURE

```
Frontend: React 19 + Vite 7 + Tailwind CSS 4 + Recharts
State:    Zustand (persisted)
Build:    Single-file (vite-plugin-singlefile)
Serve:    FastAPI static mount at /dashboard
Mobile:   Responsive with separate MobileLayout (viewport < 768px)
Themes:   Dark (default), Trading Pro, Light Gold
```

## 2. PAGES & ROUTES

| Route | Page | Description |
|-------|------|-------------|
| `/` | Dashboard | KPI, equity curve, active/pending trades, heatmap |
| `/account` | Account Manager | Binance Futures account (testnet/live) |
| `/pending-signals` | Pending Signals | All pending signals with filters |
| `/research` | Strategy Research | RR simulation, config panel, debug |
| `/signals` | Signal Analysis | 6 tabs, performance, heatmaps, scores |
| `/manual-behavior` | Manual Behavior | Impact analysis of manual interventions |
| `/edge-discovery` | Edge Discovery | 5 tabs, alpha hunting |
| `/indicators` | Indicator Analysis | 6 tabs, buckets, scatter, regime |
| `/blocked` | Blocked Signals | Scan debug, block reasons (grouped by `::`) |
| `/market` | Market | Per-symbol signal history |
| `/scan-test` | Scan Test | Embedded external scanner app (iframe) |
| `/simulation` | Simulation | Signal Replay Backtest — policy evaluation |
| `/query-lab` | Query Lab | SQL editor with 8 sample queries |
| `/engine` | Engine | Engine version performance |
| `/settings` | Settings | 9 config tabs |

## 3. SIDEBAR NAVIGATION ORDER

```
Dashboard → Account → Pending → Strategy → Signals →
Manual Behavior → Edge Discovery → Indicators → Blocked →
Market → Scan Test → Simulation → Query Lab → Engine → Settings
```

## 4. DASHBOARD

### 4.1 KPI Cards (6)
- Total Trades (all when no filter, filtered when active, label shows "(Filtered)")
- Trades Today (always today VN timezone, unaffected by filters)
- Win Rate (from filtered data, uses derived status in ALL mode)
- Active Signals (OPEN count)
- Pending Signals (WAIT count)
- Open / Max

### 4.2 Filter Bar
Order: `From | To | Strategy | Pattern | Direction | Regime | TF | Score | CAP/PSize($) | [WL/ALL] [Apply]`

- **CAP / PSize($)**: Text input format `10000|1000` (Capital | Position Size)
- **WL/ALL Toggle**:
  - `WL` (default, indigo): Only WIN + LOSS signals
  - `ALL` (orange): All closed signals (status ≠ OPEN, has exit_time)
  - When ALL: non-WIN/LOSS signals derive WIN/LOSS from entry_price, exit_price, direction
  - LONG: exit > entry → WIN, else LOSS
  - SHORT: entry > exit → WIN, else LOSS

### 4.3 Date Filtering
- User inputs VN dates (UTC+7)
- All filtering done **locally** from `allSignals` (fetched once, limit=10000)
- `exit_time` UTC → convert to VN date string → compare with filter dates
- No dependency on backend date filtering (avoids `_parse_vn_date` issues)

### 4.4 Metrics (3 cards)
- Strategy Metrics: PF, Expectancy, Sharpe, Streaks, Long/Short WR, Avg Duration
- Portfolio Compounding: NAV, P&L, Peak/Trough, Max DD/Gain, Calmar, Sharpe
- Portfolio Fixed: Same metrics with fixed position size

### 4.5 Charts
- Equity Curve: Compounding vs Fixed (LineChart)
- Drawdown: Compounding DD vs Fixed DD (AreaChart, reversed Y)

### 4.6 Tables
- **Active Signals**: Live price (10s refresh), P&L, Qty, Close button per row, Close All button
- **Pending Signals**: Live current price, OrderQty, ExeQty, Cancel button per row, Cancel All
- **Recent Trades**: Uses `metricClosed` (date-filtered, ALL statuses regardless of WL toggle)
- **Pattern × Timeframe Heatmap**: Unfiltered, all closed trades

### 4.7 API Endpoints Used
- `POST /api/signals/{id}/close` — Close 1 active signal
- `POST /api/pending/{id}/cancel` — Cancel 1 pending
- `POST /api/admin/cancel-all-pending` — Cancel all pending
- `POST /api/admin/cancel-all-active` — Close all active

## 5. ACCOUNT MANAGER

### 5.1 Data Source
All data from Binance Futures API via backend proxy:
- `GET /api/account/info?target=testnet|live`
- `GET /api/account/positions?target=...`
- `GET /api/account/open-orders?target=...`
- `GET /api/account/trades?target=...&symbol=BTCUSDT&limit=500`
- `GET /api/account/income?target=...&limit=500`

### 5.2 Tabs (5)
1. **Overview**: Balance breakdown, Position PnL bar chart, Pie distribution, Income summary
2. **Open Positions**: Table with Size, Entry, Mark, PnL, Notional, Leverage, Liq Price
3. **Open Orders**: Table with Kind, Side, Type, Qty, Price, Stop, Status
4. **Trade History**: Requires symbol input (Binance constraint), KPI + filter + table
5. **Income History**: Filter by Type + Date Range (VN timezone), stats cards + table

### 5.3 Target Mode
Automatically switches testnet/live based on `tradingMode` from appStore.

## 6. PENDING SIGNALS PAGE

### 6.1 Default Filter
Loads all pending signals, default date = today (VN timezone).

### 6.2 Filters
Date range, Status, Reject Reason (grouped by `::` prefix), Exchange Status,
Symbol, Score, TF, Strategy, Pattern, Regime, Direction.

### 6.3 Columns
id | Symbol | TF | Pattern | Dir | Regime | Entry | SL | TP | Status | Reason | Score | EStatus | OrderAt

## 7. SIGNALS PAGE

### 7.1 Tabs (6)
Performance, Heatmap Matrix, Score Analysis, Feature Correlation, Indicator Analysis, Trade List

### 7.2 Data
- Fetch all signals once (limit=10000), filter locally
- Date range filter: VN timezone, empty = all time
- Status filter: WIN + LOSS only

### 7.3 Heatmap Layout (Heatmap Matrix tab)
- Symbol × Timeframe: Symbol = vertical (y), Timeframe = horizontal (x)
- ATR × Score + MTF × Trend: Side by side in 2-column grid

## 7.5 STRATEGY RESEARCH — SL Validation Filter
After receiving trades from `/api/research/run`, frontend filters out invalid SL placement:
- LONG with `stop_loss >= entry_price` → excluded
- SHORT with `stop_loss <= entry_price` → excluded
- Missing entry/SL data → kept

## 8. MANUAL BEHAVIOR PAGE

### 8.1 Purpose
Analyze impact of manual interventions (Kill Switch, Manual Close).

### 8.2 Derive Logic
For signals with status ≠ WIN/LOSS:
- LONG: `exit_price > entry_price` → WIN, else LOSS
- SHORT: `entry_price > exit_price` → WIN, else LOSS

### 8.3 KPI (6)
Total | Manual Count | Overall WR (Derived) | Manual WR (Derived) | Avg Manual PnL | Impact vs Std

### 8.4 Status View Filter
- All (Derived) — all signals with derived status
- Non-WIN/LOSS Only — only manual/kill-switch signals
- Specific status (e.g., MANUAL, KILL_SWITCH)

### 8.5 Comparison Cards
Standard Signals vs Manual Signals: Total, Wins, WR, Avg PnL, PF

## 9. EDGE DISCOVERY

### 9.1 Tabs (5)
Health & Overview, Feature & Alpha, Setup & Pattern, Execution & Optimization, Indicator Optimization

### 9.2 Data
Backend `/api/signal-analysis` with query-based approach. Filters sent as plain VN dates.

## 10. INDICATORS

### 10.1 Tabs (6)
Indicator Buckets, Heatmaps, MAE/MFE, Exit & Duration, Distribution, Regime Fingerprint

### 10.2 KPI
Always visible (show 0 when no data, never hidden).

## 11. BLOCKED SIGNALS

### 11.1 Block Reason Grouping
`HTF::abc` → grouped as `HTF`, `OTF::xyz` → `OTF`. Logic: split by `::`, take first part. No `::` = unique.

### 11.2 API
`GET /api/scan-debug?limit=500` + `GET /api/scan-debug/block-reasons`

## 12. SIMULATION — Signal Replay Backtest

### 12.1 Purpose
Replay real closed signals using Binance Mark Price 1m bars to evaluate trade management policy.
Compare Actual outcome vs Simulated outcome under current exit policy.

### 12.2 Scope (Phase 1)
- Only WIN + LOSS signals (toggle to include MANUAL)
- No OPEN, REJECTED, CANCELLED
- No scanner/OTF/prefill historical rerun
- Only trade management / exit policy evaluation

### 12.3 Policy Config (User-editable)
- **TP Target**: Default 2.0R, adjustable
- **Protection Levels**: Dynamic add/remove
  - Level 1 default: 1.0R → `move_to_entry` (BE + buffer 0.2%)
  - Level 2 default: 1.5R → `move_to_r` (Lock at 0.5R)
  - Actions: `move_to_entry` (shows buffer_pct), `move_to_r` (shows target_r)
- Reset to Default button
- Intrabar mode: Conservative (fixed)
- Horizon: 15m=24h, 1h=72h, 4h=7d (fixed)
- If policy unchanged → not sent to backend (backend uses default)
- If modified → sent as `{ tp_r, levels: [...] }` in POST body

### 12.4 API Endpoints
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/backtest/replay/run` | POST | Start backtest job |
| `/api/backtest/replay/jobs/{id}` | GET | Job status + progress |
| `/api/backtest/replay/jobs/{id}/summary` | GET | Summary with actual vs simulated |
| `/api/backtest/replay/jobs/{id}/rows` | GET | Paged trade rows |
| `/api/backtest/replay/jobs/{id}/rows/{signal_id}` | GET | Single trade detail + timeline |

### 12.5 UI Blocks
1. **Filters** (left 2/3): Date range, Symbols, Limit, TF/Direction/Regime/Strategy/Pattern multi-select, WL/MANUAL toggle, Run button
   **Policy Config** (right 1/3): TP(R), Protection Levels (dynamic add/remove), Reset button
2. **Job Status**: Progress bar, status badge, polling every 3s
3. **Summary Cards**: Actual vs Simulated vs Delta (WR, Avg RR, Total RR) + Exit Breakdown
4. **Trades Table**: 13 columns, click row → Detail Modal
5. **Detail Modal**: Trade info, Actual vs Sim comparison, Policy levels, Timeline events

### 12.6 Exit Reasons
TP, SL_INITIAL, SL_BE, SL_LOCK_0_5R, HORIZON, AMBIGUOUS_SL

### 12.7 FE Does NOT Calculate
All replay math done by backend. FE only sends config, polls status, renders results.

## 13. SCAN TEST

### 12.1 Architecture
Embedded external scanner app via `<iframe>`. Scanner runs independently.

### 12.2 Default URL
`/scanner/index.html` — requires backend to serve scanner static files.

### 12.3 Features
- Configurable URL (persisted localStorage)
- Fullscreen mode
- Open in new tab

## 13. SETTINGS

### 13.1 Tabs (9)
| Tab | Content |
|-----|---------|
| Scan & Signal | Signal Detection params + Scanner Engine params + DERIVATIVE/RISK/PENDING configs + Scan Now button |
| Trade Filter | OTF config: Identity (multi-select with All), Score, Position, Time |
| Pre-Fill | Whitelist (Top 50/100 MC), 5 validation checks |
| Strategies | Toggle 5 strategies with descriptions |
| Live Trading | Binance Connection test, Position Size Config, MAX_OPEN_TRADES, Limit Order Config |
| System | Trading Mode, Price Feed, ML Model, Theme (3 options), Admin Actions + Kill Switch |
| Connection | Override .env toggle, API keys (password fields) |
| API Keys | Dashboard API key |

### 13.2 Theme Options
| Theme | ID | Description |
|-------|----|-------------|
| Dark Mode | `dark` | Default — Slate + Indigo |
| Trading Pro | `trading` | Bloomberg/TradingView — Deep navy + Blue accent |
| Light Gold | `light` | Warm white + Gold accent |

### 13.3 Save Mechanism
All config saved via `PUT /api/app-config` (uses `NOW()`, avoids `utc_now()` bug).

## 14. MOBILE LAYOUT

### 14.1 Detection
`useIsMobile` hook (breakpoint 768px). Switches `Layout` ↔ `MobileLayout`.

### 14.2 MobileLayout
- Top bar: Logo + page title + Trading Mode + Kill Switch
- Bottom tab bar: Home, Account, Pending, Signals, More
- More drawer: Slide-in from right, all 14+ pages
- Safe area: iPhone notch support

### 14.3 Desktop Layout
- Sidebar: Collapsible (16px/64px/256px)
- StatusBar: Full-width, Trading Mode + Price Feed + BTC Overview + Regime dots
- Header: Page title + Kill Switch + Search + Bell + Avatar

## 15. COMPONENTS

### 15.1 UI Components
Card, CardHeader, MetricCard, Button, IconButton, Badge (StatusBadge, DirectionBadge, PercentChangeBadge, ScoreBadge),
Input, SearchInput, NumberInput, RangeInput, Select, MultiSelect, DataTable (sortable, paginated), Tabs, TabContent, Toggle

### 15.2 Chart Components
BarChart, EquityCurve, Heatmap, PieChart, ScatterChart

### 15.3 Special Components
KillSwitch (confirm modal, mode-aware), StatusBar (BTC overview, regime dots, live refresh 10s)

## 16. STATE MANAGEMENT (Zustand)

### 16.1 Persisted Keys
`sidebarCollapsed`, `darkMode`, `theme`, `activeStrategies`, `researchQueries`

### 16.2 Runtime Keys
`tradingMode`, `priceFeedHealthy/Mode/Symbols`, `killSwitchActive`

## 17. TIME HANDLING

### 17.1 Convention
- DB stores naive UTC (`timestamp with time zone`)
- Frontend converts to VN (UTC+7) for display using manual offset
- `parseUtcMs()` → normalize UTC string to ms
- `utcToVN()` → format as `MM/dd HH:mm` in VN
- `exitToVNDate()` → convert to `YYYY-MM-DD` VN date string for filtering
- `getTodayVN()` → current date in VN timezone

### 17.2 Date Range Filtering
All pages filter locally from pre-fetched `allSignals`:
1. Convert each signal's `exit_time` UTC → VN date string
2. Compare with user-selected start/end dates
3. No backend date conversion dependency

## 18. API CLIENT (`src/services/api.ts`)

### 18.1 Endpoints
| Module | Endpoints |
|--------|-----------|
| signals | `GET /api/signals`, `GET /api/signals/{id}` |
| pending | `GET /api/pending-signals` |
| engine | `GET /api/engine/status`, `GET /api/engine/versions`, `GET /api/price-feed/status` |
| config | `GET/PUT /api/app-config` |
| tradingMode | `GET/PUT /api/trading-mode` |
| strategies | `GET /api/strategies`, `PUT /api/strategies/active` |
| otf | `GET/PUT /api/open-trade-filter`, `GET /api/open-trade-filter/status` |
| prefill | via `app-config` PREFILL_CONFIG key |
| ml | `GET /api/ml/evaluate`, `POST /api/retrain` |
| admin | `POST /api/admin/cancel-all-pending`, `POST /api/admin/refresh-views` |
| research | `POST /api/research/run` |
| analysis | `POST /api/signal-analysis` |
| queryLab | `POST /api/query-lab/execute` |
| scanDebug | `GET /api/scan-debug`, `GET /api/scan-debug/block-reasons` |
| account | `GET /api/account/info|positions|open-orders|trades|income` |

## 19. BUILD & DEPLOY

```bash
npm run build          # Outputs dist/index.html (single file)
# Backend serves:
#   /dashboard → dist/index.html
#   /scanner   → scanner/ directory (separate app)
```

## 20. FILE STRUCTURE

```
src/
├── App.tsx                          # Router + Layout detection
├── main.tsx                         # Entry point
├── index.css                        # Tailwind + Theme CSS
├── hooks/
│   └── useIsMobile.ts              # Mobile detection
├── types/
│   └── database.ts                 # Signal, EquityPoint, ResearchQuery
├── utils/
│   ├── cn.ts                       # clsx + tailwind-merge
│   ├── time.ts                     # VN timezone utilities
│   └── format.ts                   # Number/date formatters
├── store/
│   └── appStore.ts                 # Zustand store (persisted)
├── services/
│   └── api.ts                      # Unified API client
├── theme/
│   └── light.ts                    # Light theme class map
├── components/
│   ├── layout/
│   │   ├── Layout.tsx              # Desktop layout (sidebar + header)
│   │   └── MobileLayout.tsx        # Mobile layout (bottom tabs)
│   ├── ui/                         # Reusable UI components
│   ├── charts/                     # Chart components
│   ├── KillSwitch.tsx
│   └── StatusBar.tsx
└── pages/
    ├── DashboardPage.tsx
    ├── AccountPage.tsx
    ├── PendingSignalsPage.tsx
    ├── ResearchPage.tsx
    ├── SignalsPage.tsx
    ├── ManualBehaviorPage.tsx
    ├── EdgeDiscoveryPage.tsx
    ├── IndicatorsPage.tsx
    ├── ScanTestPage.tsx
    ├── QueryLabPage.tsx
    ├── SettingsPage.tsx
    └── PlaceholderPages.tsx        # Market, Engine, Blocked, Simulation
```
