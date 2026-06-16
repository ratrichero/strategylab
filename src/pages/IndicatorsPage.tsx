// @ts-nocheck
/* eslint-disable */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { Card, CardHeader } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Input } from '../components/ui/Input';
import { DataTable } from '../components/ui/Table';
import { Tabs, TabContent } from '../components/ui/Tabs';
import { Heatmap } from '../components/charts/Heatmap';
import { Filter, Loader2 } from 'lucide-react';
import { ResponsiveContainer, BarChart, Bar, ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip, Legend } from 'recharts';
import { parseUtcMs, getTodayVN, normalizeSignalDates } from '../utils/time';

const API = '/api';
const VN_MS = 7 * 3600 * 1000;

/** Convert exit_time UTC → VN date string "YYYY-MM-DD" */
function exitToVNDate(exitTime) {
  if (!exitTime) return '';
  const ms = parseUtcMs(exitTime);
  if (!ms) return '';
  const vn = new Date(ms + VN_MS);
  return `${vn.getUTCFullYear()}-${String(vn.getUTCMonth()+1).padStart(2,'0')}-${String(vn.getUTCDate()).padStart(2,'0')}`;
}

function ChartTT({ active, payload, label }) { if (!active || !payload?.length) return null; return (<div className="bg-slate-800 border border-slate-600 rounded-lg p-3 shadow-xl text-sm"><p className="text-yellow-400 font-semibold mb-1">{label}</p>{payload.map((e, i) => (<div key={i} className="flex items-center gap-2"><div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: e.color }} /><span className="text-white">{e.name}: <strong>{typeof e.value === 'number' ? e.value.toFixed(2) : e.value}</strong></span></div>))}</div>); }
async function fetchQ(query, params = {}) {
  console.log('[Indicators] fetchQ:', query, JSON.stringify(params));
  try {
    const res = await fetch(`${API}/signal-analysis`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ query, params }) });
    if (!res.ok) {
      const errText = await res.text().catch(() => res.statusText);
      console.error(`[Indicators] fetchQ FAILED: ${query} → ${res.status}:`, errText);
      return [];
    }
    return (await res.json()).data || [];
  } catch (e) {
    console.error(`[Indicators] fetchQ ERROR: ${query}`, e);
    return [];
  }
}
const TABS = [{id:'buckets',label:'Indicator Buckets'},{id:'heatmap',label:'Heatmaps'},{id:'scatter',label:'MAE / MFE'},{id:'exit',label:'Exit & Duration'},{id:'distribution',label:'Distribution'},{id:'regime',label:'Regime Fingerprint'}];

export function Indicators() {
  const today = getTodayVN();
  const [tab, setTab] = useState('buckets'); const [loading, setLoading] = useState(true); const [ad, setAd] = useState({}); const [loadedTabs, setLoadedTabs] = useState(new Set()); const [allSignals, setAllSignals] = useState([]);
  const [allStrategies, setAllStrategies] = useState([]); const [allPatterns, setAllPatterns] = useState([]); const [engineVersions, setEngineVersions] = useState([]);
  const [fetchingTop50, setFetchingTop50] = useState(false);
  const [f, setF] = useState({startDate:'',endDate:'',symbols:'',symbolMode:'include',scoreMin:0,scoreMax:10,engineVersion:'all',engineMode:'only',timeframes:[],strategies:[],patterns:[],regimes:[],directions:[]});
  const [applied, setApplied] = useState({...f}); const set = (k,v) => setF(prev=>({...prev,[k]:v})); const toggleArr = (k,v) => setF(prev=>{const arr=prev[k]; return {...prev,[k]:arr.includes(v)?arr.filter(x=>x!==v):[...arr,v]};});
  const fetchTop50=async()=>{setFetchingTop50(true);try{const res=await fetch('https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=50&page=1&sparkline=false',{headers:{'x-cg-demo-api-key':'CG-r9KNtFCb794fJuozcK1AMr2W'}});const coins=await res.json();set('symbols',coins.map(c=>c.symbol.toUpperCase()).join(' '));}catch(e){console.error(e);}finally{setFetchingTop50(false);}};
  const [filterVersion, setFilterVersion] = useState(0);
  const [loadedVersionTabs, setLoadedVersionTabs] = useState({});

  // For /api/signal-analysis — plain VN date strings
  const buildAnalysisParams = () => {
    const p = {};
    if (applied.startDate) p.start_date = applied.startDate;
    if (applied.endDate) p.end_date = applied.endDate;
    if (applied.symbols?.trim()) { p.symbols = applied.symbols; p.symbol_mode = applied.symbolMode; }
    if (applied.timeframes?.length) p.timeframes = applied.timeframes;
    if (applied.strategies?.length) p.strategies = applied.strategies;
    if (applied.patterns?.length) p.patterns = applied.patterns;
    if (applied.regimes?.length) p.regimes = applied.regimes;
    if (applied.directions?.length) p.directions = applied.directions;
    if (applied.engineVersion !== 'all') p.engine_version = applied.engineMode === 'newest' ? applied.engineVersion + '+' : applied.engineVersion;
    if (applied.scoreMin > 0) p.score_min = applied.scoreMin;
    if (applied.scoreMax < 10) p.score_max = applied.scoreMax;
    return p;
  };

  const TAB_Q = {buckets:['indicator_bucket_rsi','indicator_bucket_volume_ratio','indicator_bucket_atr_percentile'],heatmap:['rsi_vol_heatmap','atr_score_heatmap','mtf_trend_heatmap'],scatter:['mae_mfe_scatter'],exit:['exit_reason_breakdown','time_to_exit_dist']};

  // Load ALL signals once (no date filter on API — filter locally)
  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const [sigRes, versRes] = await Promise.all([
          fetch(`${API}/signals?limit=2000`).then(r => r.json()).catch(() => ({ data: [] })),
          fetch(`${API}/engine/versions`).then(r => r.json()).catch(() => []),
        ]);
        const sigs = (sigRes.data || []).map(normalizeSignalDates);
        setAllSignals(sigs);
        setAllStrategies(Array.from(new Set(sigs.map(s => s.strategy_name).filter(Boolean))).sort());
        setAllPatterns(Array.from(new Set(sigs.map(s => s.pattern).filter(Boolean))).sort());
        setEngineVersions(versRes.map(v => String(v.engine_version)).filter(Boolean).sort().reverse());
        setAd({});
        setLoadedVersionTabs({});
      } catch (e) { console.error(e); }
      finally { setLoading(false); }
    })();
  }, []);

  // Load tab-specific data from analysis API
  useEffect(() => {
    if (loading) return;
    const tabId = tab;
    if (tabId === 'distribution' || tabId === 'regime') return;
    const cacheKey = `${tabId}_${filterVersion}`;
    if (loadedVersionTabs[cacheKey]) return;

    const dp = buildAnalysisParams();
    const queries = TAB_Q[tabId] || [];

    (async () => {
      try {
        const results = await Promise.all(queries.map(q => {
          if (q.startsWith('indicator_bucket_')) {
            const ind = q.replace('indicator_bucket_', '');
            return fetchQ('indicator_bucket', { ...dp, indicator: ind }).catch(() => []);
          }
          return fetchQ(q, dp).catch(() => []);
        }));
        const obj = {};
        queries.forEach((q, i) => {
          if (q === 'indicator_bucket_rsi') obj['indRsi'] = results[i];
          else if (q === 'indicator_bucket_volume_ratio') obj['indVol'] = results[i];
          else if (q === 'indicator_bucket_atr_percentile') obj['indAtr'] = results[i];
          else if (q === 'mae_mfe_scatter') obj['maeMfe'] = results[i];
          else obj[q] = results[i];
        });
        setAd(prev => ({ ...prev, ...obj }));
        setLoadedVersionTabs(prev => ({ ...prev, [cacheKey]: true }));
      } catch (e) { console.error(e); }
    })();
  }, [tab, loading, filterVersion, applied]);

  // Local filtering from allSignals — same VN date logic as Dashboard
  const filtered = useMemo(() => {
    return allSignals.filter(s => {
      if (s.status !== 'WIN' && s.status !== 'LOSS') return false;
      const c = applied;
      // VN date range filter
      if (c.startDate || c.endDate) {
        const vnDate = exitToVNDate(s.exit_time);
        if (!vnDate) return false;
        if (c.startDate && vnDate < c.startDate) return false;
        if (c.endDate && vnDate > c.endDate) return false;
      }
      if (c.symbols?.trim()) {
        const list = c.symbols.replace(/,/g, ' ').split(/\s+/).map(x => x.trim().toUpperCase()).filter(Boolean).map(x => x.endsWith('USDT') ? x : x + 'USDT');
        if (list.length) { const match = list.includes(s.symbol); if (c.symbolMode === 'include' ? !match : match) return false; }
      }
      if (c.scoreMin > 0 && (s.score || 0) < c.scoreMin) return false;
      if (c.scoreMax < 10 && (s.score || 0) > c.scoreMax) return false;
      if (c.engineVersion !== 'all') {
        if (c.engineMode === 'newest' && Number(s.engine_version) < Number(c.engineVersion)) return false;
        if (c.engineMode === 'older' && Number(s.engine_version) > Number(c.engineVersion)) return false;
        if (c.engineMode === 'only' && String(s.engine_version) !== c.engineVersion) return false;
      }
      if (c.timeframes?.length && !c.timeframes.includes(s.timeframe)) return false;
      if (c.strategies?.length && !c.strategies.includes(s.strategy_name)) return false;
      if (c.patterns?.length && !c.patterns.includes(s.pattern)) return false;
      if (c.regimes?.length && !c.regimes.includes(s.regime)) return false;
      if (c.directions?.length && !c.directions.includes(s.direction)) return false;
      return true;
    });
  }, [allSignals, applied]);

  const wins = filtered.filter(s=>s.status==='WIN'); const losses = filtered.filter(s=>s.status==='LOSS');
  const kpi = filtered.length?(()=>{const t=filtered.length,w=wins.length;const wr=(w/t)*100;const gp=filtered.filter(s=>(s.result_percent||0)>0).reduce((a,s)=>a+(s.result_percent||0),0);const gl=Math.abs(filtered.filter(s=>(s.result_percent||0)<0).reduce((a,s)=>a+(s.result_percent||0),0));const pf=gl>0?gp/gl:gp>0?Infinity:0;return{total:t,wr,pf};})():null;
  const [distIndicator, setDistIndicator] = useState('rsi');
  const [scatterX, setScatterX] = useState('rsi');
  const [scatterY, setScatterY] = useState('volume_ratio');
  const INDICATOR_LIST = [{value:'rsi',label:'RSI'},{value:'volume_ratio',label:'Volume Ratio'},{value:'atr_ratio',label:'ATR Ratio'},{value:'score',label:'Score'}];

  const regimeFingerprint = useMemo(()=>{const regimes={};filtered.forEach(s=>{const r=s.regime||'UNKNOWN';if(!regimes[r])regimes[r]=[];regimes[r].push(s);});return Object.entries(regimes).map(([regime,sigs])=>{const avg=key=>{const vals=sigs.map(s=>Number(s[key])||0).filter(v=>v>0);return vals.length?vals.reduce((a,b)=>a+b,0)/vals.length:0;};const w=sigs.filter(s=>s.status==='WIN').length;return{regime,trades:sigs.length,winrate:sigs.length>0?(w/sigs.length)*100:0,rsi:avg('rsi'),volume_ratio:avg('volume_ratio'),atr_ratio:avg('atr_ratio'),score:avg('score')};}).sort((a,b)=>b.trades-a.trades);},[filtered]);

  const thresholdData = useMemo(()=>{const ind=distIndicator;const steps=ind==='rsi'?[20,30,40,50,60,70,80]:ind==='volume_ratio'?[0.5,1,1.5,2,3,5]:ind==='score'?[5,6,7,8,9]:[0.005,0.01,0.015,0.02,0.03];return steps.map(threshold=>{const above=filtered.filter(s=>(Number(s[ind])||0)>=threshold);const w=above.filter(s=>s.status==='WIN').length;return{threshold,trades:above.length,winrate:above.length>0?(w/above.length)*100:0};}).filter(d=>d.trades>0);},[filtered,distIndicator]);

  const indScatterData = useMemo(()=>filtered.slice(0,300).map(s=>({x:Number(s[scatterX])||0,y:Number(s[scatterY])||0,label:s.status==='WIN'?1:0,symbol:s.symbol})).filter(d=>d.x>0||d.y>0),[filtered,scatterX,scatterY]);

  return(
    <div className="space-y-6">
      <h2 className="text-2xl font-bold text-white flex items-center gap-2">Indicator Analysis {loading && <Loader2 className="w-5 h-5 animate-spin text-indigo-400" />}</h2>
      {kpi&&<div className="grid grid-cols-2 md:grid-cols-3 gap-3"><Card className="p-3 text-center"><p className="text-xs text-slate-400">Total Trades</p><p className="text-lg font-bold text-white">{kpi.total}</p></Card><Card className="p-3 text-center"><p className="text-xs text-slate-400">Win Rate</p><p className={`text-lg font-bold ${kpi.wr>=50?'text-emerald-400':'text-red-400'}`}>{kpi.wr.toFixed(1)}%</p></Card><Card className="p-3 text-center"><p className="text-xs text-slate-400">Profit Factor</p><p className="text-lg font-bold text-white">{kpi.pf===Infinity?'∞':kpi.pf.toFixed(2)}</p></Card></div>}
      <Card><div className="flex items-center gap-2 mb-4"><Filter className="w-4 h-4 text-slate-400" /><span className="text-sm font-semibold text-white">Filters</span><span className="text-xs text-slate-500 ml-2">Leave dates empty = all time.</span></div>
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-3 mb-4">
          <Input type="date" label="Start" value={f.startDate} onChange={e=>set('startDate',e.target.value)} />
          <Input type="date" label="End" value={f.endDate} onChange={e=>set('endDate',e.target.value)} />
          <div className="col-span-2"><label className="block text-sm font-medium text-slate-400 mb-1.5">Symbol</label><div className="flex gap-1"><input type="text" value={f.symbols} onChange={e=>set('symbols',e.target.value)} placeholder="BTC ETH SOL..." className="flex-1 bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-white text-sm" /><button onClick={()=>set('symbolMode',f.symbolMode==='include'?'exclude':'include')} className={`px-3 py-2 rounded-lg text-xs font-bold ${f.symbolMode==='include'?'bg-emerald-600 text-white':'bg-red-600 text-white'}`}>{f.symbolMode==='include'?'Include':'Exclude'}</button><button onClick={fetchTop50} disabled={fetchingTop50} className="px-3 py-2 bg-yellow-600 hover:bg-yellow-500 text-white rounded-lg text-xs">{fetchingTop50?'...':'Top50'}</button></div></div>
          <div><label className="block text-sm font-medium text-slate-400 mb-1.5">Engine</label><div className="flex gap-1"><select value={f.engineVersion} onChange={e=>set('engineVersion',e.target.value)} className="flex-1 bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-white text-sm"><option value="all">All</option>{engineVersions.map(v=><option key={v} value={v}>v{v}</option>)}</select><button onClick={()=>set('engineMode',f.engineMode==='only'?'newest':f.engineMode==='newest'?'older':'only')} className={`px-3 py-2 rounded-lg text-xs font-bold ${f.engineMode!=='only'?'bg-indigo-600 text-white':'bg-slate-700 text-slate-400'}`}>{f.engineMode==='only'?'Only':f.engineMode==='newest'?'+New':'+Old'}</button></div></div>
          <div className="col-span-2"><label className="block text-sm font-medium text-slate-400 mb-1.5">Score {f.scoreMin.toFixed(1)} – {f.scoreMax.toFixed(1)}</label><input type="range" min={0} max={10} step={0.5} value={f.scoreMin} onChange={e=>set('scoreMin',Number(e.target.value))} className="w-full accent-indigo-500 h-1.5" /><input type="range" min={0} max={10} step={0.5} value={f.scoreMax} onChange={e=>set('scoreMax',Number(e.target.value))} className="w-full accent-indigo-500 h-1.5" /></div>
          <div className="flex items-end"><Button variant="primary" className="w-full" onClick={()=>{setApplied({...f});setAd({});setLoadedVersionTabs({});setFilterVersion(v=>v+1);}}>Apply</Button></div>
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
        {tab==='buckets'&&<div className="space-y-6"><div className="grid grid-cols-1 md:grid-cols-3 gap-6"><Card><CardHeader title="RSI Buckets" />{ad.indRsi?.length?<DataTable columns={[{key:'bucket',header:'RSI'},{key:'trades',header:'Trades',sortable:true,align:'right'},{key:'win_rate',header:'WR%',sortable:true,align:'right',render:v=><span className={v>=50?'text-emerald-400':'text-red-400'}>{v}%</span>},{key:'avg_return',header:'Avg Ret',sortable:true,align:'right'}]} data={ad.indRsi} pageSize={10} />:<div className="h-32 flex items-center justify-center text-slate-500">No data</div>}</Card><Card><CardHeader title="Volume Ratio" />{ad.indVol?.length?<DataTable columns={[{key:'bucket',header:'Vol'},{key:'trades',header:'Trades',sortable:true,align:'right'},{key:'win_rate',header:'WR%',sortable:true,align:'right',render:v=><span className={v>=50?'text-emerald-400':'text-red-400'}>{v}%</span>},{key:'avg_return',header:'Avg Ret',sortable:true,align:'right'}]} data={ad.indVol} pageSize={10} />:<div className="h-32 flex items-center justify-center text-slate-500">No data</div>}</Card><Card><CardHeader title="ATR Percentile" />{ad.indAtr?.length?<DataTable columns={[{key:'bucket',header:'ATR'},{key:'trades',header:'Trades',sortable:true,align:'right'},{key:'win_rate',header:'WR%',sortable:true,align:'right',render:v=><span className={v>=50?'text-emerald-400':'text-red-400'}>{v}%</span>},{key:'avg_return',header:'Avg Ret',sortable:true,align:'right'}]} data={ad.indAtr} pageSize={10} />:<div className="h-32 flex items-center justify-center text-slate-500">No data</div>}</Card></div>
            <Card><div className="flex items-center gap-4 mb-4"><CardHeader title="Threshold Optimizer" subtitle={`Win rate when ${INDICATOR_LIST.find(i=>i.value===distIndicator)?.label||distIndicator} ≥ threshold`} /><select value={distIndicator} onChange={e=>setDistIndicator(e.target.value)} className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-white text-sm"><option value="rsi">RSI</option><option value="volume_ratio">Volume Ratio</option><option value="atr_ratio">ATR Ratio</option><option value="score">Score</option></select></div>{thresholdData.length>0?<ResponsiveContainer width="100%" height={250}><BarChart data={thresholdData}><CartesianGrid strokeDasharray="3 3" stroke="#334155" /><XAxis dataKey="threshold" stroke="#64748b" fontSize={11} /><YAxis stroke="#64748b" fontSize={11} tickFormatter={v=>`${v}%`} /><Tooltip content={<ChartTT />} /><Bar dataKey="winrate" name="Win Rate %" fill="#6366f1" radius={[4,4,0,0]} /></BarChart></ResponsiveContainer>:<div className="h-48 flex items-center justify-center text-slate-500">No data</div>}</Card>
          </div>}
        {tab==='heatmap'&&<div className="space-y-6"><Card><CardHeader title="RSI × Volume Ratio → Win Rate" />{ad.rsi_vol_heatmap?.length?<Heatmap data={ad.rsi_vol_heatmap.map(r=>({x:r.vol_zone,y:r.rsi_zone,value:Number(r.win_rate)||50,count:Number(r.n_trades)||0}))} xLabel="Volume" yLabel="RSI" valueLabel="WR%" colorScale="green-red" showValues />:<div className="h-48 flex items-center justify-center text-slate-500">No data</div>}</Card><Card><CardHeader title="ATR × Score → Win Rate" />{ad.atr_score_heatmap?.length?<Heatmap data={ad.atr_score_heatmap.map(r=>({x:r.score_band,y:r.atr_bucket,value:Number(r.win_rate)||50,count:Number(r.n_trades)||0}))} xLabel="Score" yLabel="ATR%" valueLabel="WR%" colorScale="green-red" showValues />:<div className="h-48 flex items-center justify-center text-slate-500">No data</div>}</Card><Card><CardHeader title="MTF × Trend → Win Rate" />{ad.mtf_trend_heatmap?.length?<Heatmap data={ad.mtf_trend_heatmap.map(r=>({x:r.trend_bucket,y:r.mtf_bucket,value:Number(r.win_rate)||50,count:Number(r.n_trades)||0}))} xLabel="Trend" yLabel="MTF" valueLabel="WR%" colorScale="green-red" showValues />:<div className="h-48 flex items-center justify-center text-slate-500">No data</div>}</Card>
            <Card><div className="flex items-center gap-4 mb-4"><CardHeader title="Indicator × Indicator Scatter" subtitle="Find sweet spot zones" /><select value={scatterX} onChange={e=>setScatterX(e.target.value)} className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-white text-sm"><option value="rsi">RSI</option><option value="volume_ratio">Vol Ratio</option><option value="atr_ratio">ATR Ratio</option><option value="score">Score</option></select><span className="text-slate-500">×</span><select value={scatterY} onChange={e=>setScatterY(e.target.value)} className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-white text-sm"><option value="volume_ratio">Vol Ratio</option><option value="rsi">RSI</option><option value="atr_ratio">ATR Ratio</option><option value="score">Score</option></select></div>{indScatterData.length>0?<ResponsiveContainer width="100%" height={350}><ScatterChart><CartesianGrid strokeDasharray="3 3" stroke="#334155" /><XAxis type="number" dataKey="x" name={INDICATOR_LIST.find(i=>i.value===scatterX)?.label} stroke="#64748b" fontSize={11} /><YAxis type="number" dataKey="y" name={INDICATOR_LIST.find(i=>i.value===scatterY)?.label} stroke="#64748b" fontSize={11} /><Tooltip content={<ChartTT />} /><Scatter data={indScatterData.filter(d=>d.label===1)} fill="#10b981" name="Win" /><Scatter data={indScatterData.filter(d=>d.label===0)} fill="#ef4444" name="Loss" /></ScatterChart></ResponsiveContainer>:<div className="h-48 flex items-center justify-center text-slate-500">No data</div>}</Card>
          </div>}
        {tab==='scatter'&&<Card><CardHeader title="MAE vs MFE Scatter" />{ad.maeMfe?.length?<ResponsiveContainer width="100%" height={400}><ScatterChart><CartesianGrid strokeDasharray="3 3" stroke="#334155" /><XAxis type="number" dataKey="mae" name="MAE %" stroke="#64748b" fontSize={11} /><YAxis type="number" dataKey="mfe" name="MFE %" stroke="#64748b" fontSize={11} /><Tooltip content={<ChartTT />} /><Scatter data={ad.maeMfe.filter(r=>r.label===1)} fill="#10b981" name="Win" /><Scatter data={ad.maeMfe.filter(r=>r.label!==1)} fill="#ef4444" name="Loss" /></ScatterChart></ResponsiveContainer>:<div className="h-48 flex items-center justify-center text-slate-500">No data</div>}</Card>}
        {tab==='exit'&&<div className="grid grid-cols-1 md:grid-cols-2 gap-6"><Card><CardHeader title="Exit Reason" />{ad.exit_reason_breakdown?.length?<DataTable columns={[{key:'exit_reason',header:'Reason',sortable:true},{key:'count',header:'Count',sortable:true,align:'right'},{key:'pct',header:'%',sortable:true,align:'right',render:v=>`${v}%`}]} data={ad.exit_reason_breakdown} pageSize={10} />:<div className="h-32 flex items-center justify-center text-slate-500">No data</div>}</Card><Card><CardHeader title="Time to Exit" />{ad.time_to_exit_dist?.length?<ResponsiveContainer width="100%" height={250}><BarChart data={ad.time_to_exit_dist}><CartesianGrid strokeDasharray="3 3" stroke="#334155" /><XAxis dataKey="bucket" stroke="#64748b" fontSize={11} /><YAxis stroke="#64748b" fontSize={11} /><Tooltip content={<ChartTT />} /><Bar dataKey="count" name="Count" fill="#6366f1" radius={[4,4,0,0]} /></BarChart></ResponsiveContainer>:<div className="h-32 flex items-center justify-center text-slate-500">No data</div>}</Card></div>}
        {tab==='distribution'&&<div className="space-y-6"><Card>
          <div className="flex items-center gap-4 mb-4"><CardHeader title="Indicator Win/Loss Histogram" /><select value={distIndicator} onChange={e=>setDistIndicator(e.target.value)} className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-white text-sm"><option value="rsi">RSI</option><option value="volume_ratio">Volume Ratio</option><option value="atr_ratio">ATR Ratio</option><option value="score">Score</option></select></div>
          {(()=>{
            const ind=distIndicator;
            const bucketRanges={rsi:[[0,20],[20,30],[30,40],[40,50],[50,60],[60,70],[70,80],[80,100]],volume_ratio:[[0,1],[1,2],[2,3],[3,5],[5,10],[10,Infinity]],atr_ratio:[[0,0.01],[0.01,0.02],[0.02,0.03],[0.03,0.05],[0.05,Infinity]],score:[[0,5],[5,6],[6,7],[7,8],[8,9],[9,10]]};
            const ranges=bucketRanges[ind]||bucketRanges.rsi;
            const distData=ranges.map(([lo,hi])=>{const label=hi===Infinity?`≥${lo}`:`${lo}-${hi}`;const inRange=filtered.filter(s=>{const v=Number(s[ind])||0;return v>=lo&&v<hi;});const w=inRange.filter(s=>s.status==='WIN').length;const l=inRange.length-w;return{range:label,wins:w,losses:l,total:inRange.length,winrate:inRange.length>0?(w/inRange.length)*100:0};}).filter(d=>d.total>0);
            return distData.length>0?(<div><ResponsiveContainer width="100%" height={300}><BarChart data={distData}><CartesianGrid strokeDasharray="3 3" stroke="#334155" /><XAxis dataKey="range" stroke="#64748b" fontSize={11} /><YAxis stroke="#64748b" fontSize={11} /><Tooltip content={<ChartTT />} /><Legend /><Bar dataKey="wins" name="Wins" fill="#10b981" radius={[4,4,0,0]} /><Bar dataKey="losses" name="Losses" fill="#ef4444" radius={[4,4,0,0]} /></BarChart></ResponsiveContainer>
              <div className="mt-4 overflow-x-auto"><table className="w-full text-sm"><thead><tr className="border-b border-slate-700 text-slate-400"><th className="py-2 px-3 text-left">Range</th><th className="py-2 px-3 text-right">Wins</th><th className="py-2 px-3 text-right">Losses</th><th className="py-2 px-3 text-right">Total</th><th className="py-2 px-3 text-right">WR%</th></tr></thead><tbody>{distData.map(d=><tr key={d.range} className="border-b border-slate-800"><td className="py-2 px-3 text-white">{d.range}</td><td className="py-2 px-3 text-right text-emerald-400">{d.wins}</td><td className="py-2 px-3 text-right text-red-400">{d.losses}</td><td className="py-2 px-3 text-right text-slate-400">{d.total}</td><td className={`py-2 px-3 text-right font-bold ${d.winrate>=50?'text-emerald-400':'text-red-400'}`}>{d.winrate.toFixed(1)}%</td></tr>)}</tbody></table></div></div>):<div className="h-48 flex items-center justify-center text-slate-500">No data</div>;
          })()}
        </Card>
        <Card><CardHeader title="Indicator Distribution by Outcome" subtitle="Win vs Loss average values" />
          {filtered.length?(()=>{const indicators=['rsi','volume_ratio','atr_ratio','score'];const labels={rsi:'RSI',volume_ratio:'Vol Ratio',atr_ratio:'ATR Ratio',score:'Score'};const avg=arr=>{const v=arr.filter(x=>x!=null&&!isNaN(x));return v.length?v.reduce((a,b)=>a+b,0)/v.length:0;};const data=indicators.map(ind=>({indicator:labels[ind],win_avg:Number(avg(wins.map(s=>Number(s[ind])||0)).toFixed(2)),loss_avg:Number(avg(losses.map(s=>Number(s[ind])||0)).toFixed(2))})).filter(d=>d.win_avg>0||d.loss_avg>0);return(<div><ResponsiveContainer width="100%" height={300}><BarChart data={data}><CartesianGrid strokeDasharray="3 3" stroke="#334155" /><XAxis dataKey="indicator" stroke="#64748b" fontSize={11} /><YAxis stroke="#64748b" fontSize={11} /><Tooltip content={<ChartTT />} /><Legend /><Bar dataKey="win_avg" name="Win Avg" fill="#10b981" radius={[4,4,0,0]} /><Bar dataKey="loss_avg" name="Loss Avg" fill="#ef4444" radius={[4,4,0,0]} /></BarChart></ResponsiveContainer><div className="mt-4 overflow-x-auto"><table className="w-full text-sm"><thead><tr className="border-b border-slate-700 text-slate-400"><th className="py-2 px-3 text-left">Indicator</th><th className="py-2 px-3 text-right">Win Avg</th><th className="py-2 px-3 text-right">Loss Avg</th><th className="py-2 px-3 text-right">Δ</th></tr></thead><tbody>{data.map(d=><tr key={d.indicator} className="border-b border-slate-800"><td className="py-2 px-3 text-white">{d.indicator}</td><td className="py-2 px-3 text-right text-emerald-400">{d.win_avg}</td><td className="py-2 px-3 text-right text-red-400">{d.loss_avg}</td><td className={`py-2 px-3 text-right font-bold ${d.win_avg-d.loss_avg>=0?'text-emerald-400':'text-red-400'}`}>{(d.win_avg-d.loss_avg).toFixed(2)}</td></tr>)}</tbody></table></div></div>);})():<div className="h-48 flex items-center justify-center text-slate-500">No data</div>}
        </Card></div>}
        {tab==='regime'&&<Card><CardHeader title="Regime Fingerprint" subtitle="Average indicator values per market regime" />
          {regimeFingerprint.length>0?(<div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-6 mb-6">{regimeFingerprint.map(r=>(<div key={r.regime} className="bg-slate-800/50 rounded-lg p-4"><h4 className="font-semibold text-white mb-3">{r.regime}</h4><div className="space-y-2 text-sm"><div className="flex justify-between"><span className="text-slate-400">Trades</span><span className="text-white font-medium">{r.trades}</span></div><div className="flex justify-between"><span className="text-slate-400">Win Rate</span><span className={r.winrate>=50?'text-emerald-400 font-medium':'text-red-400 font-medium'}>{r.winrate.toFixed(1)}%</span></div><div className="flex justify-between"><span className="text-slate-400">Avg RSI</span><span className="text-white">{r.rsi.toFixed(1)}</span></div><div className="flex justify-between"><span className="text-slate-400">Avg Vol Ratio</span><span className="text-white">{r.volume_ratio.toFixed(2)}</span></div><div className="flex justify-between"><span className="text-slate-400">Avg Score</span><span className="text-white">{r.score.toFixed(2)}</span></div></div></div>))}</div>
            <DataTable columns={[{key:'regime',header:'Regime',sortable:true},{key:'trades',header:'Trades',sortable:true,align:'right'},{key:'winrate',header:'WR%',sortable:true,align:'right',render:v=><span className={v>=50?'text-emerald-400':'text-red-400'}>{v.toFixed(1)}%</span>},{key:'rsi',header:'Avg RSI',sortable:true,align:'right',render:v=>v.toFixed(1)},{key:'volume_ratio',header:'Avg Vol',sortable:true,align:'right',render:v=>v.toFixed(2)},{key:'score',header:'Avg Score',sortable:true,align:'right',render:v=>v.toFixed(2)}]} data={regimeFingerprint} pageSize={5} />
          </div>):<div className="h-48 flex items-center justify-center text-slate-500">No data</div>}
        </Card>}
      </TabContent>
    </div>
  );
}
