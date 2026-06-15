// @ts-nocheck
/* eslint-disable */
import { useState, useEffect, useRef } from 'react';
import { Card, CardHeader } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Input } from '../components/ui/Input';
import { DataTable } from '../components/ui/Table';
import { Tabs, TabContent } from '../components/ui/Tabs';
import { Loader2, Search, Filter } from 'lucide-react';

const API = '/api';
async function fetchQ(query, params = {}) {
  console.log('[EdgeDiscovery] fetchQ:', query, JSON.stringify(params));
  try {
    const res = await fetch(`${API}/signal-analysis`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ query, params }) });
    if (!res.ok) {
      const errText = await res.text().catch(() => res.statusText);
      console.error(`[EdgeDiscovery] fetchQ FAILED: ${query} → ${res.status}:`, errText);
      return [];
    }
    return (await res.json()).data || [];
  } catch (e) {
    console.error(`[EdgeDiscovery] fetchQ ERROR: ${query}`, e);
    return [];
  }
}
const TABS = [{id:'health',label:'Health & Overview'},{id:'feature',label:'Feature & Alpha'},{id:'setup',label:'Setup & Pattern'},{id:'execution',label:'Execution & Optimization'},{id:'indicator',label:'Indicator Optimization'}];
const RR_COL = {key:'avg_r',header:'Avg RR',sortable:true,align:'right',render:v=><span className={Number(v)>=0?'text-emerald-400':'text-red-400'}>{v}</span>};
const WR_COL = {key:'winrate',header:'WR%',sortable:true,align:'right',render:v=><span className={Number(v)>=50?'text-emerald-400':'text-red-400'}>{v}%</span>};

const EDGE_TAB_Q = {
  health: ['edge_baseline','edge_strategy','edge_data_validate'],
  feature: ['edge_score','edge_mtf','edge_mtf_analysis','edge_mtf_direction','edge_rsi_bucket','edge_atr_bucket','edge_correlation'],
  setup: ['edge_pattern','edge_timeframe','edge_direction','edge_regime','edge_top_combo','edge_regime_pattern'],
  execution: ['edge_mfe_tp','edge_mfe_mae_avg','edge_hold_time'],
  indicator: ['edge_derivative_bias'],
};

function toAnalysisDate(dateStr, isEnd = false) {
  // Backend _parse_vn accepts raw date string like "2026-06-13" or ISO without Z
  // Simplest: send VN date as-is, let backend handle +07:00 conversion
  return dateStr;
}

function buildParams(applied) {
  const fp = {};
  // Send dates as plain VN date strings — backend _parse_vn handles conversion
  if (applied.startDate) fp.start_date = applied.startDate;
  if (applied.endDate) fp.end_date = applied.endDate;
  if (applied.symbols?.trim()) { fp.symbols = applied.symbols; fp.symbol_mode = applied.symbolMode; }
  // Send arrays directly — backend _build_sig_filter reads these
  if (applied.timeframes?.length) fp.timeframes = applied.timeframes;
  if (applied.strategies?.length) fp.strategies = applied.strategies;
  if (applied.patterns?.length) fp.patterns = applied.patterns;
  if (applied.regimes?.length) fp.regimes = applied.regimes;
  if (applied.directions?.length) fp.directions = applied.directions;
  if (applied.engineVersion !== 'all') fp.engine_version = applied.engineMode === 'newest' ? applied.engineVersion + '+' : applied.engineVersion;
  if (applied.scoreMin > 0) fp.score_min = applied.scoreMin;
  if (applied.scoreMax < 10) fp.score_max = applied.scoreMax;
  return fp;
}

export function EdgeDiscovery() {
  const [tab, setTab] = useState('health');
  const [loading, setLoading] = useState(true);
  const [ad, setAd] = useState({});
  const [allStrategies, setAllStrategies] = useState([]);
  const [allPatterns, setAllPatterns] = useState([]);
  const [engineVersions, setEngineVersions] = useState([]);
  const [fetchingTop50, setFetchingTop50] = useState(false);

  const [f, setF] = useState({startDate:'',endDate:'',symbols:'',symbolMode:'include',scoreMin:0,scoreMax:10,engineVersion:'all',engineMode:'only',timeframes:[],strategies:[],patterns:[],regimes:[],directions:[]});
  const [applied, setApplied] = useState({...f});
  const setFV = (k,v) => setF(prev=>({...prev,[k]:v}));
  const toggleArr = (k,v) => setF(prev=>{const arr=prev[k]; return {...prev,[k]:arr.includes(v)?arr.filter(x=>x!==v):[...arr,v]};});

  // Use ref so refill functions always read latest applied
  const appliedRef = useRef(applied);
  appliedRef.current = applied;

  const [mtfMin,setMtfMin]=useState('0.6');
  const [atrThreshold,setAtrThreshold]=useState('0.4');
  const [mtfThreshold,setMtfThreshold]=useState('0.6');
  const [atrLimit,setAtrLimit]=useState('0.4');
  const [volLimit,setVolLimit]=useState('2');

  // Track which (tab + filterVersion) combos have loaded
  const [filterVersion, setFilterVersion] = useState(0);
  const loadedRef = useRef({});

  const fetchTop50 = async () => {
    setFetchingTop50(true);
    try { const res = await fetch('https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=50&page=1&sparkline=false',{headers:{'x-cg-demo-api-key':'CG-r9KNtFCb794fJuozcK1AMr2W'}}); const coins = await res.json(); setFV('symbols', coins.map(c=>c.symbol.toUpperCase()).join(' ')); }
    catch(e) { console.error(e); } finally { setFetchingTop50(false); }
  };

  // Load filter options once
  useEffect(() => {
    (async () => {
      try {
        const [sigRes, versRes] = await Promise.all([
          fetch(`${API}/signals?limit=2000`).then(r=>r.json()).catch(()=>({data:[]})),
          fetch(`${API}/engine/versions`).then(r=>r.json()).catch(()=>[]),
        ]);
        const sigs = sigRes.data || [];
        setAllStrategies(Array.from(new Set(sigs.map(s=>s.strategy_name).filter(Boolean))).sort());
        setAllPatterns(Array.from(new Set(sigs.map(s=>s.pattern).filter(Boolean))).sort());
        setEngineVersions(versRes.map(v=>String(v.engine_version)).filter(Boolean).sort().reverse());
      } catch {}
    })();
  }, []);

  // Main data loader — runs when tab or applied filters change
  useEffect(() => {
    const cacheKey = `${tab}_v${filterVersion}`;
    if (loadedRef.current[cacheKey]) { setLoading(false); return; }

    const fp = buildParams(applied);
    console.log('[EdgeDiscovery] Loading tab:', tab, 'v:', filterVersion, 'params:', JSON.stringify(fp));

    setLoading(true);
    (async () => {
      try {
        const queries = EDGE_TAB_Q[tab] || [];
        const results = await Promise.all(queries.map(q => fetchQ(q, fp).catch(() => [])));
        const obj = {};
        queries.forEach((q, i) => { obj[q] = results[i]; });

        if (tab === 'health') {
          obj['edge_baseline_compare'] = await fetchQ('edge_baseline_compare', { ...fp, mtf_min_score: parseFloat(mtfMin) }).catch(() => []);
        }
        if (tab === 'setup') {
          obj['edge_sweet_spot'] = await fetchQ('edge_sweet_spot', { ...fp, atr_threshold: parseFloat(atrThreshold), mtf_threshold: parseFloat(mtfThreshold) }).catch(() => []);
        }
        if (tab === 'indicator') {
          obj['edge_indicator_discovery'] = await fetchQ('edge_indicator_discovery', { ...fp, atr_limit: parseFloat(atrLimit), vol_ratio_limit: parseFloat(volLimit) }).catch(() => []);
          obj['edge_derivative_effect'] = await fetchQ('edge_derivative_effect', fp).catch(() => []);
        }

        setAd(prev => ({ ...prev, ...obj }));
        loadedRef.current[cacheKey] = true;
      } catch (e) { console.error(e); }
      finally { setLoading(false); }
    })();
  }, [tab, applied, filterVersion]);

  const handleApply = () => {
    const next = { ...f };
    loadedRef.current = {}; // clear all cache
    setAd({});
    setFilterVersion(v => v + 1);
    setApplied(next); // this triggers the useEffect above
  };

  // Refill functions — always read latest applied from ref
  const refillBaseline = async () => {
    const fp = buildParams(appliedRef.current);
    const params = { ...fp, mtf_min_score: parseFloat(mtfMin) };
    console.log('[Refill Baseline]', JSON.stringify(params));
    setAd(prev => ({ ...prev, edge_baseline_compare: [] }));
    const d = await fetchQ('edge_baseline_compare', params);
    setAd(prev => ({ ...prev, edge_baseline_compare: d }));
  };

  const refillSweet = async () => {
    const fp = buildParams(appliedRef.current);
    const params = { ...fp, atr_threshold: parseFloat(atrThreshold), mtf_threshold: parseFloat(mtfThreshold) };
    console.log('[Refill Sweet]', JSON.stringify(params));
    setAd(prev => ({ ...prev, edge_sweet_spot: [] }));
    const d = await fetchQ('edge_sweet_spot', params);
    setAd(prev => ({ ...prev, edge_sweet_spot: d }));
  };

  const refillIndicator = async () => {
    const fp = buildParams(appliedRef.current);
    const params = { ...fp, atr_limit: parseFloat(atrLimit), vol_ratio_limit: parseFloat(volLimit) };
    console.log('[Refill Indicator]', JSON.stringify(params));
    setAd(prev => ({ ...prev, edge_indicator_discovery: [] }));
    const d = await fetchQ('edge_indicator_discovery', params);
    setAd(prev => ({ ...prev, edge_indicator_discovery: d }));
  };

  const kpi = ad.edge_baseline?.length ? (() => {
    const all = ad.edge_baseline;
    const totalTrades = all.reduce((s,r) => s + Number(r.total), 0);
    const avgWR = all.reduce((s,r) => s + Number(r.winrate) * Number(r.total), 0) / (totalTrades || 1);
    const avgR = all.reduce((s,r) => s + Number(r.avg_r) * Number(r.total), 0) / (totalTrades || 1);
    const avgExp = all.reduce((s,r) => s + Number(r.expectancy || 0) * Number(r.total), 0) / (totalTrades || 1);
    return { totalTrades, winrate: avgWR, avgR, expectancy: avgExp };
  })() : null;

  // Don't block render — show loading indicator inline instead

  return (
    <div className="space-y-6">
      <div><h2 className="text-2xl font-bold text-white flex items-center gap-2"><Search className="w-6 h-6 text-indigo-400" /> Edge Discovery {loading && <Loader2 className="w-5 h-5 animate-spin text-indigo-400" />}</h2><p className="text-slate-400 mt-1">Find alpha in your trading system</p></div>


      {kpi && <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Card className="p-3 text-center"><p className="text-xs text-slate-400">Total Trades</p><p className="text-lg font-bold text-white">{kpi.totalTrades}</p></Card>
        <Card className="p-3 text-center"><p className="text-xs text-slate-400">Win Rate</p><p className={`text-lg font-bold ${kpi.winrate>=50?'text-emerald-400':'text-red-400'}`}>{kpi.winrate.toFixed(2)}%</p></Card>
        <Card className="p-3 text-center"><p className="text-xs text-slate-400">Expectancy</p><p className={`text-lg font-bold ${kpi.expectancy>=0?'text-emerald-400':'text-red-400'}`}>{kpi.expectancy.toFixed(4)}</p></Card>
        <Card className="p-3 text-center"><p className="text-xs text-slate-400">Avg RR</p><p className={`text-lg font-bold ${kpi.avgR>=0?'text-emerald-400':'text-red-400'}`}>{kpi.avgR.toFixed(3)}</p></Card>
      </div>}

      {/* FILTERS */}
      <Card>
        <div className="flex items-center gap-2 mb-4"><Filter className="w-4 h-4 text-slate-400" /><span className="text-sm font-semibold text-white">Filters</span><span className="text-xs text-slate-500 ml-2">Leave dates empty = all time.</span></div>
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-3 mb-4">
          <Input type="date" label="Start" value={f.startDate} onChange={e=>setFV('startDate',e.target.value)} />
          <Input type="date" label="End" value={f.endDate} onChange={e=>setFV('endDate',e.target.value)} />
          <div className="col-span-2"><label className="block text-sm font-medium text-slate-400 mb-1.5">Symbol</label><div className="flex gap-1"><input type="text" value={f.symbols} onChange={e=>setFV('symbols',e.target.value)} placeholder="BTC ETH SOL..." className="flex-1 bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-white text-sm" /><button onClick={()=>setFV('symbolMode',f.symbolMode==='include'?'exclude':'include')} className={`px-3 py-2 rounded-lg text-xs font-bold ${f.symbolMode==='include'?'bg-emerald-600 text-white':'bg-red-600 text-white'}`}>{f.symbolMode==='include'?'Include':'Exclude'}</button><button onClick={fetchTop50} disabled={fetchingTop50} className="px-3 py-2 bg-yellow-600 hover:bg-yellow-500 text-white rounded-lg text-xs">{fetchingTop50?'...':'Top50'}</button></div></div>
          <div><label className="block text-sm font-medium text-slate-400 mb-1.5">Engine</label><div className="flex gap-1"><select value={f.engineVersion} onChange={e=>setFV('engineVersion',e.target.value)} className="flex-1 bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-white text-sm"><option value="all">All</option>{engineVersions.map(v=><option key={v} value={v}>v{v}</option>)}</select><button onClick={()=>setFV('engineMode',f.engineMode==='only'?'newest':f.engineMode==='newest'?'older':'only')} className={`px-3 py-2 rounded-lg text-xs font-bold ${f.engineMode!=='only'?'bg-indigo-600 text-white':'bg-slate-700 text-slate-400'}`}>{f.engineMode==='only'?'Only':f.engineMode==='newest'?'+New':'+Old'}</button></div></div>
          <div className="col-span-2"><label className="block text-sm font-medium text-slate-400 mb-1.5">Score {f.scoreMin.toFixed(1)} – {f.scoreMax.toFixed(1)}</label><input type="range" min={0} max={10} step={0.5} value={f.scoreMin} onChange={e=>setFV('scoreMin',Number(e.target.value))} className="w-full accent-indigo-500 h-1.5" /><input type="range" min={0} max={10} step={0.5} value={f.scoreMax} onChange={e=>setFV('scoreMax',Number(e.target.value))} className="w-full accent-indigo-500 h-1.5" /></div>
          <div className="flex items-end"><Button variant="primary" className="w-full" onClick={handleApply}>Apply</Button></div>
        </div>
        <div className="grid grid-cols-12 gap-4 pt-3 border-t border-slate-700">
          <div className="col-span-1"><p className="text-[10px] text-slate-500 uppercase font-semibold mb-1.5">TF</p><div className="flex gap-1">{['15m','1h','4h'].map(tf=><button key={tf} onClick={()=>toggleArr('timeframes',tf)} className={`px-2.5 py-1.5 rounded text-xs ${f.timeframes.includes(tf)?'bg-indigo-600 text-white':'bg-slate-700 text-slate-400'}`}>{tf}</button>)}</div></div>
          <div className="col-span-2"><p className="text-[10px] text-slate-500 uppercase font-semibold mb-1.5">Strategy</p><div className="flex gap-1 flex-wrap">{allStrategies.map(s=><button key={s} onClick={()=>toggleArr('strategies',s)} className={`px-2 py-1 rounded text-xs ${f.strategies.includes(s)?'bg-indigo-600 text-white':'bg-slate-700 text-slate-400'}`}>{s}</button>)}</div></div>
          <div className="col-span-5"><p className="text-[10px] text-slate-500 uppercase font-semibold mb-1.5">Pattern</p><div className="flex gap-1 flex-wrap">{allPatterns.map(p=><button key={p} onClick={()=>toggleArr('patterns',p)} className={`px-2 py-1 rounded text-xs ${f.patterns.includes(p)?'bg-indigo-600 text-white':'bg-slate-700 text-slate-400'}`}>{p}</button>)}</div></div>
          <div className="col-span-2"><p className="text-[10px] text-slate-500 uppercase font-semibold mb-1.5">Regime</p><div className="flex gap-1 flex-wrap">{['BULL','BEAR','SIDEWAYS'].map(r=><button key={r} onClick={()=>toggleArr('regimes',r)} className={`px-2 py-1 rounded text-xs ${f.regimes.includes(r)?'bg-indigo-600 text-white':'bg-slate-700 text-slate-400'}`}>{r}</button>)}</div></div>
          <div className="col-span-2"><p className="text-[10px] text-slate-500 uppercase font-semibold mb-1.5">Direction</p><div className="flex gap-1 flex-wrap">{['LONG','SHORT'].map(d=><button key={d} onClick={()=>toggleArr('directions',d)} className={`px-2 py-1 rounded text-xs ${f.directions.includes(d)?'bg-indigo-600 text-white':'bg-slate-700 text-slate-400'}`}>{d}</button>)}</div></div>
        </div>
      </Card>

      <Tabs tabs={TABS} activeTab={tab} onChange={setTab} variant="underline" />
      <TabContent>
        {tab==='health'&&(<div className="space-y-6">
          <Card><CardHeader title="Baseline Performance" subtitle="Direction × Timeframe breakdown" />{ad.edge_baseline?.length>0?<DataTable columns={[{key:'direction',header:'Dir',sortable:true},{key:'timeframe',header:'TF',sortable:true},{key:'total',header:'Trades',sortable:true,align:'right'},RR_COL,{key:'median_r',header:'Median RR',sortable:true,align:'right'},WR_COL,{key:'avg_win_r',header:'Avg Win',align:'right'},{key:'avg_loss_r',header:'Avg Loss',align:'right'},{key:'expectancy',header:'Expect',sortable:true,align:'right'}]} data={ad.edge_baseline} pageSize={10} />:<div className="h-32 flex items-center justify-center text-slate-500">No data</div>}</Card>
          <Card><div className="flex items-center gap-3 mb-4"><h3 className="font-semibold text-white">Baseline Compare (MTF Filter)</h3><Input type="number" value={mtfMin} onChange={e=>setMtfMin(e.target.value)} className="w-24" /><Button variant="secondary" size="sm" onClick={refillBaseline}>Fill</Button></div>{ad.edge_baseline_compare?.length>0?<DataTable columns={[{key:'direction',header:'Dir',sortable:true},{key:'timeframe',header:'TF',sortable:true},{key:'base_r',header:'Base RR',align:'right'},{key:'filtered_r',header:'Filtered RR',align:'right',render:v=><span className={Number(v)>=0?'text-emerald-400':'text-red-400'}>{v}</span>},{key:'improvement',header:'Δ',sortable:true,align:'right',render:v=><span className={Number(v)>=0?'text-emerald-400':'text-red-400'}>{Number(v)>=0?'+':''}{v}</span>},{key:'total',header:'N',align:'right'}]} data={ad.edge_baseline_compare} pageSize={10} />:<div className="h-32 flex items-center justify-center text-slate-500">No data or loading...</div>}</Card>
          <Card><CardHeader title="Strategy Performance" />{ad.edge_strategy?.length>0?<DataTable columns={[{key:'strategy_name',header:'Strategy',sortable:true},{key:'total',header:'Trades',sortable:true,align:'right'},RR_COL,WR_COL]} data={ad.edge_strategy} pageSize={10} />:<div className="h-32 flex items-center justify-center text-slate-500">No data</div>}</Card>
          <Card><CardHeader title="Data Validation" subtitle="SL/TP sanity check" />{ad.edge_data_validate?.length>0?<DataTable columns={[{key:'id',header:'ID'},{key:'symbol',header:'Symbol',sortable:true},{key:'direction',header:'Dir'},{key:'entry_price',header:'Entry',render:v=>Number(v).toFixed(4)},{key:'stop_loss',header:'SL',render:v=>Number(v).toFixed(4)},{key:'take_profit',header:'TP',render:v=>Number(v).toFixed(4)},{key:'rr',header:'RR',align:'right'},{key:'flag',header:'Status',sortable:true,render:v=><span className={v==='OK'?'text-emerald-400':'text-red-400 font-bold'}>{v}</span>}]} data={ad.edge_data_validate} pageSize={15} />:<div className="h-32 flex items-center justify-center text-slate-500">No data</div>}</Card>
        </div>)}

        {tab==='feature'&&(<div className="space-y-6">
          <Card><CardHeader title="Predictive Power (Correlation with RR)" />{ad.edge_correlation?.length>0?(<div className="grid grid-cols-5 gap-4 py-4">{Object.entries(ad.edge_correlation[0]||{}).map(([k,v])=>(<div key={k} className="bg-slate-800/50 rounded-lg p-4 text-center"><p className="text-xs text-slate-400 capitalize">{k.replace('_corr','')}</p><p className={`text-xl font-bold ${Number(v)>=0?'text-emerald-400':'text-red-400'}`}>{Number(v).toFixed(4)}</p></div>))}</div>):<div className="h-32 flex items-center justify-center text-slate-500">No data</div>}</Card>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <Card><CardHeader title="Score Validation" subtitle="Avg RR by score bucket" />{ad.edge_score?.length>0?<DataTable columns={[{key:'score_bucket',header:'Score',sortable:true},{key:'total',header:'Trades',sortable:true,align:'right'},RR_COL,WR_COL]} data={ad.edge_score} pageSize={10} />:<div className="h-32 flex items-center justify-center text-slate-500">No data</div>}</Card>
            <Card><CardHeader title="MTF Edge" subtitle="Avg RR by MTF bucket" />{ad.edge_mtf?.length>0?<DataTable columns={[{key:'mtf_bucket',header:'MTF',sortable:true},{key:'total',header:'Trades',sortable:true,align:'right'},RR_COL]} data={ad.edge_mtf} pageSize={10} />:<div className="h-32 flex items-center justify-center text-slate-500">No data</div>}</Card>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <Card><CardHeader title="MTF Deep Analysis" />{ad.edge_mtf_analysis?.length>0?<DataTable columns={[{key:'mtf_bucket',header:'MTF Band'},{key:'n',header:'N',sortable:true,align:'right'},WR_COL,RR_COL,{key:'vs_baseline',header:'vs Base',sortable:true,align:'right',render:v=><span className={Number(v)>=0?'text-emerald-400':'text-red-400'}>{Number(v)>=0?'+':''}{v}</span>}]} data={ad.edge_mtf_analysis} pageSize={10} />:<div className="h-32 flex items-center justify-center text-slate-500">No data</div>}</Card>
            <Card><CardHeader title="MTF × Direction" />{ad.edge_mtf_direction?.length>0?<DataTable columns={[{key:'mtf_bucket',header:'MTF'},{key:'direction',header:'Dir',sortable:true},{key:'total',header:'N',sortable:true,align:'right'},RR_COL]} data={ad.edge_mtf_direction} pageSize={10} />:<div className="h-32 flex items-center justify-center text-slate-500">No data</div>}</Card>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <Card><CardHeader title="RSI Bucket Edge" />{ad.edge_rsi_bucket?.length>0?<DataTable columns={[{key:'rsi_bucket',header:'RSI'},{key:'total',header:'N',sortable:true,align:'right'},RR_COL]} data={ad.edge_rsi_bucket} pageSize={10} />:<div className="h-32 flex items-center justify-center text-slate-500">No data</div>}</Card>
            <Card><CardHeader title="ATR Ratio Bucket" />{ad.edge_atr_bucket?.length>0?<DataTable columns={[{key:'atr_bucket',header:'ATR'},{key:'total',header:'N',sortable:true,align:'right'},RR_COL]} data={ad.edge_atr_bucket} pageSize={10} />:<div className="h-32 flex items-center justify-center text-slate-500">No data</div>}</Card>
          </div>
        </div>)}

        {tab==='setup'&&(<div className="space-y-6">
          <Card><div className="flex items-center gap-3 mb-4"><h3 className="font-semibold text-white">Sweet Spot Discovery</h3><span className="text-xs text-slate-400">ATR:</span><Input type="number" value={atrThreshold} onChange={e=>setAtrThreshold(e.target.value)} className="w-20" /><span className="text-xs text-slate-400">MTF:</span><Input type="number" value={mtfThreshold} onChange={e=>setMtfThreshold(e.target.value)} className="w-20" /><Button variant="secondary" size="sm" onClick={refillSweet}>Fill</Button></div>{ad.edge_sweet_spot?.length>0?<DataTable columns={[{key:'timeframe',header:'TF'},{key:'direction',header:'Dir'},{key:'regime',header:'Regime'},{key:'mtf_q',header:'MTF'},{key:'trend',header:'Trend'},{key:'vol',header:'Vol'},{key:'n',header:'N',sortable:true,align:'right'},WR_COL,RR_COL]} data={ad.edge_sweet_spot} pageSize={20} />:<div className="h-32 flex items-center justify-center text-slate-500">No data</div>}</Card>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <Card><CardHeader title="Long vs Short" />{ad.edge_direction?.length>0?<DataTable columns={[{key:'direction',header:'Dir'},{key:'total',header:'N',sortable:true,align:'right'},RR_COL,WR_COL]} data={ad.edge_direction} pageSize={5} />:<div className="h-32 flex items-center justify-center text-slate-500">No data</div>}</Card>
            <Card><CardHeader title="Timeframe Edge" />{ad.edge_timeframe?.length>0?<DataTable columns={[{key:'timeframe',header:'TF'},{key:'total',header:'N',sortable:true,align:'right'},RR_COL,WR_COL]} data={ad.edge_timeframe} pageSize={5} />:<div className="h-32 flex items-center justify-center text-slate-500">No data</div>}</Card>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <Card><CardHeader title="Pattern Edge" />{ad.edge_pattern?.length>0?<DataTable columns={[{key:'pattern',header:'Pattern',sortable:true},{key:'total',header:'N',sortable:true,align:'right'},RR_COL,WR_COL]} data={ad.edge_pattern} pageSize={10} />:<div className="h-32 flex items-center justify-center text-slate-500">No data</div>}</Card>
            <Card><CardHeader title="Regime Analysis" />{ad.edge_regime?.length>0?<DataTable columns={[{key:'regime',header:'Regime',sortable:true},{key:'total',header:'N',sortable:true,align:'right'},RR_COL,WR_COL]} data={ad.edge_regime} pageSize={5} />:<div className="h-32 flex items-center justify-center text-slate-500">No data</div>}</Card>
          </div>
          <Card><CardHeader title="Top Signal Combinations" subtitle="Pattern × Direction × TF" />{ad.edge_top_combo?.length>0?<DataTable columns={[{key:'pattern',header:'Pattern',sortable:true},{key:'direction',header:'Dir'},{key:'timeframe',header:'TF'},{key:'total',header:'N',sortable:true,align:'right'},RR_COL]} data={ad.edge_top_combo} pageSize={15} />:<div className="h-32 flex items-center justify-center text-slate-500">No data</div>}</Card>
          <Card><CardHeader title="Regime × Pattern" />{ad.edge_regime_pattern?.length>0?<DataTable columns={[{key:'regime',header:'Regime',sortable:true},{key:'pattern',header:'Pattern',sortable:true},{key:'total',header:'N',sortable:true,align:'right'},RR_COL]} data={ad.edge_regime_pattern} pageSize={15} />:<div className="h-32 flex items-center justify-center text-slate-500">No data</div>}</Card>
        </div>)}

        {tab==='execution'&&(<div className="space-y-6">
          <Card><CardHeader title="MFE vs Realized (by Strategy)" subtitle="Is TP capturing enough?" />{ad.edge_mfe_tp?.length>0?<DataTable columns={[{key:'strategy_name',header:'Strategy',sortable:true},{key:'avg_mfe',header:'Avg MFE',sortable:true,align:'right'},{key:'avg_realized',header:'Avg RR',sortable:true,align:'right'},{key:'mfe_ratio',header:'MFE/RR',sortable:true,align:'right',render:v=><span className={Number(v)>1.5?'text-yellow-400':'text-white'}>{v}</span>}]} data={ad.edge_mfe_tp} pageSize={10} />:<div className="h-32 flex items-center justify-center text-slate-500">No data</div>}</Card>
          <Card><CardHeader title="MFE / MAE Average" />{ad.edge_mfe_mae_avg?.length>0?(<div className="grid grid-cols-2 gap-6 py-6"><div className="text-center"><p className="text-sm text-slate-400">Avg MFE</p><p className="text-3xl font-bold text-emerald-400">{Number(ad.edge_mfe_mae_avg[0]?.avg_mfe||0).toFixed(3)}</p></div><div className="text-center"><p className="text-sm text-slate-400">Avg MAE</p><p className="text-3xl font-bold text-red-400">{Number(ad.edge_mfe_mae_avg[0]?.avg_mae||0).toFixed(3)}</p></div></div>):<div className="h-32 flex items-center justify-center text-slate-500">No data</div>}</Card>
          <Card><CardHeader title="Hold Time Edge" subtitle="Avg RR by holding duration" />{ad.edge_hold_time?.length>0?<DataTable columns={[{key:'bucket',header:'Hold Time'},{key:'total',header:'N',sortable:true,align:'right'},RR_COL]} data={ad.edge_hold_time} pageSize={5} />:<div className="h-32 flex items-center justify-center text-slate-500">No data</div>}</Card>
        </div>)}

        {tab==='indicator'&&(<div className="space-y-6">
          <Card><div className="flex items-center gap-3 mb-4"><h3 className="font-semibold text-white">Indicator Edge Discovery (LONG)</h3><span className="text-xs text-slate-400">ATR limit:</span><Input type="number" value={atrLimit} onChange={e=>setAtrLimit(e.target.value)} className="w-20" /><span className="text-xs text-slate-400">Vol limit:</span><Input type="number" value={volLimit} onChange={e=>setVolLimit(e.target.value)} className="w-20" /><Button variant="secondary" size="sm" onClick={refillIndicator}>Fill</Button></div>{ad.edge_indicator_discovery?.length>0?<DataTable columns={[{key:'filter_name',header:'Filter',sortable:true},{key:'n',header:'N',sortable:true,align:'right'},RR_COL,WR_COL]} data={ad.edge_indicator_discovery} pageSize={10} />:<div className="h-32 flex items-center justify-center text-slate-500">No data</div>}</Card>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <Card><CardHeader title="Derivative Bias Impact" />{ad.edge_derivative_bias?.length>0?<DataTable columns={[{key:'bias_type',header:'Bias'},{key:'total',header:'N',sortable:true,align:'right'},RR_COL,WR_COL]} data={ad.edge_derivative_bias} pageSize={5} />:<div className="h-32 flex items-center justify-center text-slate-500">No data</div>}</Card>
            <Card><CardHeader title="Derivative Bias Detail" />{ad.edge_derivative_effect?.length>0?<DataTable columns={[{key:'bucket',header:'Bias Band'},{key:'n',header:'N',sortable:true,align:'right'},{key:'avg_bias',header:'Avg Bias',align:'right'},{key:'avg_score',header:'Avg Score',align:'right'},WR_COL,RR_COL]} data={ad.edge_derivative_effect} pageSize={10} />:<div className="h-32 flex items-center justify-center text-slate-500">No data</div>}</Card>
          </div>
        </div>)}
      </TabContent>
    </div>
  );
}
