// @ts-nocheck
/* eslint-disable */
import { useState, useMemo, useEffect } from 'react';
import { Card, CardHeader } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Input } from '../components/ui/Input';
import { Select } from '../components/ui/Select';
import { DataTable } from '../components/ui/Table';
import { Tabs, TabContent } from '../components/ui/Tabs';
import { StatusBadge, DirectionBadge, PercentChangeBadge } from '../components/ui/Badge';
import { Loader2, Wallet, RefreshCw, TrendingUp, TrendingDown, DollarSign, ShieldAlert, BarChart3, ArrowUpDown } from 'lucide-react';
import { ResponsiveContainer, AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell, XAxis, YAxis, CartesianGrid, Tooltip, Legend } from 'recharts';
import { parseUtcMs, utcToVN, getTodayVN } from '../utils/time';
import toast from 'react-hot-toast';

const API = '/api';
const COLORS = ['#6366f1', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4', '#ec4899', '#84cc16'];

function ChartTT({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-slate-800 border border-slate-600 rounded-lg p-3 shadow-xl text-sm">
      <p className="text-slate-400 mb-2 font-medium">{label}</p>
      {payload.map((e, i) => (
        <div key={i} className="flex items-center gap-2 mb-1">
          <div className="w-3 h-3 rounded-full" style={{ backgroundColor: e.color }} />
          <span className="text-slate-300">{e.name}:</span>
          <span className="font-bold text-white">{typeof e.value === 'number' ? e.value.toFixed(4) : e.value}</span>
        </div>
      ))}
    </div>
  );
}

const TABS = [
  { id: 'overview', label: 'Account Overview' },
  { id: 'positions', label: 'Open Positions' },
  { id: 'orders', label: 'Open Orders' },
  { id: 'history', label: 'Trade History' },
  { id: 'income', label: 'Income History' },
];

export function AccountPage() {
  const today = getTodayVN();
  const [tab, setTab] = useState('overview');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  // Account data
  const [accountInfo, setAccountInfo] = useState(null);
  const [positions, setPositions] = useState([]);
  const [openOrders, setOpenOrders] = useState([]);
  const [tradeHistory, setTradeHistory] = useState([]);
  const [incomeHistory, setIncomeHistory] = useState([]);

  // Filters
  const [hSymbol, setHSymbol] = useState('');
  const [hSide, setHSide] = useState('all');
  const [hStartDate, setHStartDate] = useState('');
  const [hEndDate, setHEndDate] = useState('');
  const [incomeType, setIncomeType] = useState('all');

  // Fetch account data from backend proxy
  const fetchAccountData = async (showToast = false) => {
    try {
      setRefreshing(true);
      const [accRes, posRes, ordRes, tradeRes, incRes] = await Promise.all([
        fetch(`${API}/account/info`).then(r => r.ok ? r.json() : null).catch(() => null),
        fetch(`${API}/account/positions`).then(r => r.ok ? r.json() : null).catch(() => null),
        fetch(`${API}/account/open-orders`).then(r => r.ok ? r.json() : null).catch(() => null),
        fetch(`${API}/account/trades?limit=500`).then(r => r.ok ? r.json() : null).catch(() => null),
        fetch(`${API}/account/income?limit=500`).then(r => r.ok ? r.json() : null).catch(() => null),
      ]);
      if (accRes) setAccountInfo(accRes);
      if (posRes) setPositions(Array.isArray(posRes) ? posRes : posRes.data || []);
      if (ordRes) setOpenOrders(Array.isArray(ordRes) ? ordRes : ordRes.data || []);
      if (tradeRes) setTradeHistory(Array.isArray(tradeRes) ? tradeRes : tradeRes.data || []);
      if (incRes) setIncomeHistory(Array.isArray(incRes) ? incRes : incRes.data || []);
      if (showToast) toast.success('Account data refreshed');
    } catch (e) {
      console.error('Account fetch error:', e);
      if (showToast) toast.error('Failed to fetch account data');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => { fetchAccountData(); }, []);

  // Account KPI
  const kpi = useMemo(() => {
    if (!accountInfo) return null;
    const totalWalletBalance = Number(accountInfo.totalWalletBalance || 0);
    const totalUnrealizedProfit = Number(accountInfo.totalUnrealizedProfit || 0);
    const totalMarginBalance = Number(accountInfo.totalMarginBalance || 0);
    const availableBalance = Number(accountInfo.availableBalance || 0);
    const totalPositionInitialMargin = Number(accountInfo.totalPositionInitialMargin || 0);
    const totalOpenOrderInitialMargin = Number(accountInfo.totalOpenOrderInitialMargin || 0);
    return {
      totalWalletBalance,
      totalUnrealizedProfit,
      totalMarginBalance,
      availableBalance,
      totalPositionInitialMargin,
      totalOpenOrderInitialMargin,
      marginLevel: totalPositionInitialMargin > 0 ? totalMarginBalance / totalPositionInitialMargin : 0,
    };
  }, [accountInfo]);

  // Active positions (non-zero)
  const activePositions = useMemo(() => {
    return positions.filter(p => Math.abs(Number(p.positionAmt || 0)) > 0);
  }, [positions]);

  // Position distribution for pie chart
  const posDistribution = useMemo(() => {
    return activePositions.map(p => ({
      name: p.symbol,
      value: Math.abs(Number(p.notional || 0)),
      pnl: Number(p.unrealizedProfit || 0),
    }));
  }, [activePositions]);

  // Filtered trade history
  const filteredTrades = useMemo(() => {
    return tradeHistory.filter(t => {
      if (hSymbol && !t.symbol?.toUpperCase().includes(hSymbol.toUpperCase())) return false;
      if (hSide !== 'all' && t.side !== hSide) return false;
      if (hStartDate || hEndDate) {
        const ts = Number(t.time || 0);
        if (!ts) return false;
        const VN_MS = 7 * 3600 * 1000;
        const vn = new Date(ts + VN_MS);
        const vnStr = `${vn.getUTCFullYear()}-${String(vn.getUTCMonth()+1).padStart(2,'0')}-${String(vn.getUTCDate()).padStart(2,'0')}`;
        if (hStartDate && vnStr < hStartDate) return false;
        if (hEndDate && vnStr > hEndDate) return false;
      }
      return true;
    });
  }, [tradeHistory, hSymbol, hSide, hStartDate, hEndDate]);

  // Filtered income history
  const filteredIncome = useMemo(() => {
    return incomeHistory.filter(i => {
      if (incomeType !== 'all' && i.incomeType !== incomeType) return false;
      return true;
    });
  }, [incomeHistory, incomeType]);

  // Income types for filter
  const incomeTypes = useMemo(() => {
    return Array.from(new Set(incomeHistory.map(i => i.incomeType).filter(Boolean))).sort();
  }, [incomeHistory]);

  // Trade stats
  const tradeStats = useMemo(() => {
    if (!filteredTrades.length) return { total: 0, volume: 0, commission: 0, pnl: 0 };
    const total = filteredTrades.length;
    const volume = filteredTrades.reduce((s, t) => s + Math.abs(Number(t.quoteQty || 0)), 0);
    const commission = filteredTrades.reduce((s, t) => s + Math.abs(Number(t.commission || 0)), 0);
    const pnl = filteredTrades.reduce((s, t) => s + Number(t.realizedPnl || 0), 0);
    return { total, volume, commission, pnl };
  }, [filteredTrades]);

  // Income stats
  const incomeStats = useMemo(() => {
    const byType = {};
    filteredIncome.forEach(i => {
      const t = i.incomeType || 'UNKNOWN';
      if (!byType[t]) byType[t] = 0;
      byType[t] += Number(i.income || 0);
    });
    return Object.entries(byType).map(([type, total]) => ({ type, total })).sort((a, b) => Math.abs(b.total) - Math.abs(a.total));
  }, [filteredIncome]);

  // Format helpers
  const $n = (v, d = 2) => Number(v || 0).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
  const pnlClr = v => Number(v) >= 0 ? 'text-emerald-400' : 'text-red-400';
  const tsToVN = (ts) => { if (!ts) return '-'; const d = new Date(Number(ts)); const VN = 7*3600*1000; const vn = new Date(d.getTime()+VN); return `${String(vn.getUTCMonth()+1).padStart(2,'0')}/${String(vn.getUTCDate()).padStart(2,'0')} ${String(vn.getUTCHours()).padStart(2,'0')}:${String(vn.getUTCMinutes()).padStart(2,'0')}`; };

  // Position columns
  const posColumns = [
    { key: 'symbol', header: 'Symbol', sortable: true },
    { key: 'positionAmt', header: 'Size', sortable: true, align: 'right', render: (v, r) => <span className={Number(v) > 0 ? 'text-emerald-400' : 'text-red-400'}>{Number(v).toFixed(4)}</span> },
    { key: 'entryPrice', header: 'Entry', align: 'right', render: v => $n(v, 4) },
    { key: 'markPrice', header: 'Mark', align: 'right', render: v => $n(v, 4) },
    { key: 'unrealizedProfit', header: 'Unrealized PnL', sortable: true, align: 'right', render: v => <span className={pnlClr(v)}>{Number(v) >= 0 ? '+' : ''}{$n(v, 4)}</span> },
    { key: 'notional', header: 'Notional', sortable: true, align: 'right', render: v => `$${$n(Math.abs(Number(v)), 2)}` },
    { key: 'leverage', header: 'Lev', align: 'center', render: v => `${v}x` },
    { key: 'marginType', header: 'Margin', render: v => <span className="text-xs">{v}</span> },
    { key: 'liquidationPrice', header: 'Liq Price', align: 'right', render: v => Number(v) > 0 ? $n(v, 4) : '-' },
  ];

  // Order columns
  const orderColumns = [
    { key: 'symbol', header: 'Symbol', sortable: true },
    { key: 'side', header: 'Side', render: v => <span className={v === 'BUY' ? 'text-emerald-400 font-bold text-xs' : 'text-red-400 font-bold text-xs'}>{v}</span> },
    { key: 'type', header: 'Type', render: v => <span className="text-xs">{v}</span> },
    { key: 'origQty', header: 'Qty', align: 'right', render: v => Number(v).toFixed(4) },
    { key: 'price', header: 'Price', align: 'right', render: v => $n(v, 4) },
    { key: 'stopPrice', header: 'Stop', align: 'right', render: v => Number(v) > 0 ? $n(v, 4) : '-' },
    { key: 'status', header: 'Status', render: v => <span className="text-xs text-slate-400">{v}</span> },
    { key: 'time', header: 'Time', sortable: true, render: v => tsToVN(v) },
  ];

  // Trade history columns
  const tradeColumns = [
    { key: 'symbol', header: 'Symbol', sortable: true },
    { key: 'side', header: 'Side', render: v => <span className={v === 'BUY' ? 'text-emerald-400 font-bold text-xs' : 'text-red-400 font-bold text-xs'}>{v}</span> },
    { key: 'price', header: 'Price', align: 'right', render: v => $n(v, 4) },
    { key: 'qty', header: 'Qty', align: 'right', render: v => Number(v).toFixed(4) },
    { key: 'quoteQty', header: 'Volume', sortable: true, align: 'right', render: v => `$${$n(v, 2)}` },
    { key: 'realizedPnl', header: 'PnL', sortable: true, align: 'right', render: v => <span className={pnlClr(v)}>{Number(v) >= 0 ? '+' : ''}{$n(v, 4)}</span> },
    { key: 'commission', header: 'Fee', align: 'right', render: v => $n(v, 4) },
    { key: 'commissionAsset', header: 'Asset', render: v => <span className="text-xs text-slate-400">{v}</span> },
    { key: 'time', header: 'Time', sortable: true, render: v => tsToVN(v) },
  ];

  // Income columns
  const incomeColumns = [
    { key: 'symbol', header: 'Symbol', sortable: true, render: v => v || '-' },
    { key: 'incomeType', header: 'Type', sortable: true, render: v => <span className="text-xs font-medium">{v}</span> },
    { key: 'income', header: 'Amount', sortable: true, align: 'right', render: v => <span className={pnlClr(v)}>{Number(v) >= 0 ? '+' : ''}{$n(v, 6)}</span> },
    { key: 'asset', header: 'Asset', render: v => <span className="text-xs text-slate-400">{v}</span> },
    { key: 'time', header: 'Time', sortable: true, render: v => tsToVN(v) },
  ];

  if (loading) return <div className="flex items-center justify-center h-96"><Loader2 className="w-8 h-8 animate-spin text-indigo-500" /></div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Wallet className="w-7 h-7 text-indigo-400" />
          <div>
            <h2 className="text-2xl font-bold text-white">Account Manager</h2>
            <p className="text-slate-400 mt-0.5">Binance Futures Account</p>
          </div>
        </div>
        <Button variant="secondary" icon={refreshing ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />} onClick={() => fetchAccountData(true)} disabled={refreshing}>
          Refresh
        </Button>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
        <Card className="p-3 text-center">
          <div className="flex items-center justify-center gap-2 mb-1"><DollarSign className="w-4 h-4 text-indigo-400" /><p className="text-xs text-slate-400">Wallet Balance</p></div>
          <p className="text-xl font-bold text-white">${$n(kpi?.totalWalletBalance)}</p>
        </Card>
        <Card className="p-3 text-center">
          <div className="flex items-center justify-center gap-2 mb-1"><TrendingUp className="w-4 h-4 text-emerald-400" /><p className="text-xs text-slate-400">Unrealized PnL</p></div>
          <p className={`text-xl font-bold ${pnlClr(kpi?.totalUnrealizedProfit)}`}>{Number(kpi?.totalUnrealizedProfit||0) >= 0 ? '+' : ''}${$n(kpi?.totalUnrealizedProfit)}</p>
        </Card>
        <Card className="p-3 text-center">
          <div className="flex items-center justify-center gap-2 mb-1"><BarChart3 className="w-4 h-4 text-cyan-400" /><p className="text-xs text-slate-400">Margin Balance</p></div>
          <p className="text-xl font-bold text-white">${$n(kpi?.totalMarginBalance)}</p>
        </Card>
        <Card className="p-3 text-center">
          <div className="flex items-center justify-center gap-2 mb-1"><DollarSign className="w-4 h-4 text-emerald-400" /><p className="text-xs text-slate-400">Available</p></div>
          <p className="text-xl font-bold text-emerald-400">${$n(kpi?.availableBalance)}</p>
        </Card>
        <Card className="p-3 text-center">
          <div className="flex items-center justify-center gap-2 mb-1"><ShieldAlert className="w-4 h-4 text-yellow-400" /><p className="text-xs text-slate-400">Position Margin</p></div>
          <p className="text-xl font-bold text-white">${$n(kpi?.totalPositionInitialMargin)}</p>
        </Card>
        <Card className="p-3 text-center">
          <div className="flex items-center justify-center gap-2 mb-1"><ArrowUpDown className="w-4 h-4 text-purple-400" /><p className="text-xs text-slate-400">Open Positions</p></div>
          <p className="text-xl font-bold text-white">{activePositions.length}</p>
        </Card>
        <Card className="p-3 text-center">
          <div className="flex items-center justify-center gap-2 mb-1"><ArrowUpDown className="w-4 h-4 text-orange-400" /><p className="text-xs text-slate-400">Open Orders</p></div>
          <p className="text-xl font-bold text-white">{openOrders.length}</p>
        </Card>
      </div>

      <Tabs tabs={TABS} activeTab={tab} onChange={setTab} variant="underline" />
      <TabContent>
        {/* OVERVIEW */}
        {tab === 'overview' && (
          <div className="space-y-6">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {/* Assets breakdown */}
              <Card>
                <CardHeader title="Balance Breakdown" />
                <div className="space-y-3">
                  {[
                    ['Wallet Balance', kpi?.totalWalletBalance, 'text-white'],
                    ['Unrealized PnL', kpi?.totalUnrealizedProfit, pnlClr(kpi?.totalUnrealizedProfit)],
                    ['Margin Balance', kpi?.totalMarginBalance, 'text-white'],
                    ['Available Balance', kpi?.availableBalance, 'text-emerald-400'],
                    ['Position Margin', kpi?.totalPositionInitialMargin, 'text-yellow-400'],
                    ['Order Margin', kpi?.totalOpenOrderInitialMargin, 'text-slate-400'],
                  ].map(([label, val, clr]) => (
                    <div key={label} className="flex justify-between py-2 border-b border-slate-700 last:border-0">
                      <span className="text-slate-400">{label}</span>
                      <span className={`font-bold font-mono ${clr}`}>${$n(val)}</span>
                    </div>
                  ))}
                </div>
              </Card>

              {/* Position distribution */}
              <Card>
                <CardHeader title="Position Distribution" subtitle={`${activePositions.length} active positions`} />
                {posDistribution.length > 0 ? (
                  <ResponsiveContainer width="100%" height={250}>
                    <PieChart>
                      <Pie data={posDistribution} cx="50%" cy="50%" outerRadius={90} innerRadius={50} dataKey="value" label={({ name, percent }) => `${name} ${(percent*100).toFixed(0)}%`} labelLine={false}>
                        {posDistribution.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                      </Pie>
                      <Tooltip formatter={(v) => [`$${$n(v, 2)}`, 'Notional']} contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }} />
                    </PieChart>
                  </ResponsiveContainer>
                ) : <div className="h-48 flex items-center justify-center text-slate-500">No active positions</div>}
              </Card>
            </div>

            {/* Position PnL bars */}
            {activePositions.length > 0 && (
              <Card>
                <CardHeader title="Position PnL" />
                <ResponsiveContainer width="100%" height={250}>
                  <BarChart data={activePositions.map(p => ({ symbol: p.symbol, pnl: Number(p.unrealizedProfit || 0) }))}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="symbol" stroke="#64748b" fontSize={11} />
                    <YAxis stroke="#64748b" fontSize={11} tickFormatter={v => `$${v}`} />
                    <Tooltip content={<ChartTT />} />
                    <Bar dataKey="pnl" name="PnL ($)" radius={[4, 4, 0, 0]}>
                      {activePositions.map((p, i) => <Cell key={i} fill={Number(p.unrealizedProfit) >= 0 ? '#10b981' : '#ef4444'} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </Card>
            )}

            {/* Income breakdown */}
            {incomeStats.length > 0 && (
              <Card>
                <CardHeader title="Income Summary" subtitle="By type" />
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  {incomeStats.map(({ type, total }) => (
                    <div key={type} className="bg-slate-800/50 rounded-lg p-4 text-center">
                      <p className="text-xs text-slate-400 mb-1">{type}</p>
                      <p className={`text-lg font-bold font-mono ${pnlClr(total)}`}>{total >= 0 ? '+' : ''}{$n(total, 4)}</p>
                    </div>
                  ))}
                </div>
              </Card>
            )}
          </div>
        )}

        {/* POSITIONS */}
        {tab === 'positions' && (
          <Card>
            <CardHeader title="Open Positions" subtitle={`${activePositions.length} active`} />
            <DataTable columns={posColumns} data={activePositions} pageSize={20} emptyMessage="No open positions" />
          </Card>
        )}

        {/* OPEN ORDERS */}
        {tab === 'orders' && (
          <Card>
            <CardHeader title="Open Orders" subtitle={`${openOrders.length} orders`} />
            <DataTable columns={orderColumns} data={openOrders} pageSize={20} emptyMessage="No open orders" />
          </Card>
        )}

        {/* TRADE HISTORY */}
        {tab === 'history' && (
          <div className="space-y-6">
            {/* Trade stats KPI */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <Card className="p-3 text-center"><p className="text-xs text-slate-400">Total Trades</p><p className="text-lg font-bold text-white">{tradeStats.total}</p></Card>
              <Card className="p-3 text-center"><p className="text-xs text-slate-400">Volume</p><p className="text-lg font-bold text-white">${$n(tradeStats.volume)}</p></Card>
              <Card className="p-3 text-center"><p className="text-xs text-slate-400">Commission</p><p className="text-lg font-bold text-red-400">${$n(tradeStats.commission, 4)}</p></Card>
              <Card className="p-3 text-center"><p className="text-xs text-slate-400">Realized PnL</p><p className={`text-lg font-bold ${pnlClr(tradeStats.pnl)}`}>{tradeStats.pnl >= 0 ? '+' : ''}${$n(tradeStats.pnl, 4)}</p></Card>
            </div>

            {/* Filters */}
            <Card>
              <div className="flex items-center gap-2 mb-3"><span className="text-sm font-semibold text-white">Filters</span></div>
              <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                <Input type="text" label="Symbol" value={hSymbol} onChange={e => setHSymbol(e.target.value)} placeholder="BTC..." />
                <Select label="Side" value={hSide} onChange={setHSide} options={[{ value: 'all', label: 'All' }, { value: 'BUY', label: 'BUY' }, { value: 'SELL', label: 'SELL' }]} />
                <Input type="date" label="Start" value={hStartDate} onChange={e => setHStartDate(e.target.value)} />
                <Input type="date" label="End" value={hEndDate} onChange={e => setHEndDate(e.target.value)} />
                <div className="flex items-end"><Button variant="ghost" onClick={() => { setHSymbol(''); setHSide('all'); setHStartDate(''); setHEndDate(''); }}>Clear</Button></div>
              </div>
            </Card>

            <Card>
              <CardHeader title="Trade History" subtitle={`${filteredTrades.length} trades`} />
              <DataTable columns={tradeColumns} data={[...filteredTrades].sort((a, b) => Number(b.time) - Number(a.time))} pageSize={20} emptyMessage="No trades found" />
            </Card>
          </div>
        )}

        {/* INCOME HISTORY */}
        {tab === 'income' && (
          <div className="space-y-6">
            <Card>
              <div className="flex items-center gap-3 mb-3">
                <span className="text-sm font-semibold text-white">Filter</span>
                <Select value={incomeType} onChange={setIncomeType} options={[{ value: 'all', label: 'All Types' }, ...incomeTypes.map(t => ({ value: t, label: t }))]} className="w-48" />
              </div>
            </Card>

            {/* Income stats */}
            {incomeStats.length > 0 && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                {incomeStats.slice(0, 8).map(({ type, total }) => (
                  <Card key={type} className="p-3 text-center">
                    <p className="text-xs text-slate-400">{type}</p>
                    <p className={`text-lg font-bold font-mono ${pnlClr(total)}`}>{total >= 0 ? '+' : ''}{$n(total, 4)}</p>
                  </Card>
                ))}
              </div>
            )}

            <Card>
              <CardHeader title="Income History" subtitle={`${filteredIncome.length} records`} />
              <DataTable columns={incomeColumns} data={[...filteredIncome].sort((a, b) => Number(b.time) - Number(a.time))} pageSize={20} emptyMessage="No income records" />
            </Card>
          </div>
        )}
      </TabContent>

      {/* API info note */}
      {!accountInfo && (
        <Card className="border-yellow-500/30">
          <div className="flex items-center gap-3 p-2">
            <ShieldAlert className="w-5 h-5 text-yellow-400 flex-shrink-0" />
            <div>
              <p className="text-sm text-yellow-300 font-medium">Account API not configured</p>
              <p className="text-xs text-slate-400 mt-0.5">Backend cần expose các endpoint: /api/account/info, /api/account/positions, /api/account/open-orders, /api/account/trades, /api/account/income. Các endpoint này gọi Binance Futures API với BINANCE_API_KEY/SECRET từ app_config.</p>
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}
