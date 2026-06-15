// @ts-nocheck
/* eslint-disable */
import { useEffect, useState } from "react";
import { Card, CardHeader } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
import { Select } from "../components/ui/Select";
import { Settings as SettingsIcon, Save, RotateCcw, Loader2, CheckCircle, AlertCircle, Zap, Radar, ShieldCheck, Server, Layers, Filter, BarChart3, Crosshair } from "lucide-react";
import { config, tradingMode as tmApi, strategies as stratsApi, otf as otfApi, prefill as prefillApi, ml } from "../services/api";
import toast from "react-hot-toast";

const API = "/api";
async function loadConfig() { const r = await fetch(`${API}/app-config`); return r.json(); }
async function saveConfigKeys(u) { await fetch(`${API}/app-config`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(u) }); }
function Field({ label, hint, children }) { return (<div><label className="block text-sm font-medium text-slate-300 mb-1.5">{label}</label>{children}{hint && <p className="text-xs text-slate-500 mt-1">{hint}</p>}</div>); }
function NumField({ label, value, onChange, hint, step }) { return (<Field label={label} hint={hint}><input type="number" step={step || "any"} value={value} onChange={e => onChange(e.target.value)} className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-white text-sm font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500" /></Field>); }
function BoolField({ label, value, onChange, hint }) { return (<Field label={label} hint={hint}><div className="flex items-center gap-3"><button onClick={() => onChange(!value)} className={`relative w-14 h-7 rounded-full transition-colors ${value ? "bg-indigo-600" : "bg-slate-700"}`}><div className={`absolute top-1 w-5 h-5 bg-white rounded-full shadow transition-transform ${value ? "translate-x-8" : "translate-x-1"}`} /></button><span className={`text-sm font-medium ${value ? "text-emerald-400" : "text-slate-500"}`}>{value ? "Enabled" : "Disabled"}</span></div></Field>); }
function SaveRow({ saving, saved, onSave, onCancel }) { return (<div className="flex items-center gap-3 mt-6 pt-4 border-t border-slate-700"><Button variant="primary" icon={saving ? undefined : <Save className="w-4 h-4" />} loading={saving} onClick={onSave}>Apply</Button><Button variant="ghost" icon={<RotateCcw className="w-4 h-4" />} onClick={onCancel}>Cancel</Button>{saved && <span className="flex items-center gap-1 text-sm text-emerald-400"><CheckCircle className="w-4 h-4" /> Saved</span>}</div>); }

const TFS = ["15m", "1h", "4h"];

const TABS = [
  { id: "scan", label: "Scan Config", icon: Radar },
  { id: "signals", label: "Signal Config", icon: Crosshair },
  { id: "filter", label: "Trade Filter", icon: Filter },
  { id: "prefill", label: "Pre-Fill", icon: ShieldCheck },
  { id: "strats", label: "Strategies", icon: Layers },
  { id: "system", label: "System", icon: Server },
];

export function SettingsPage() {
  const [tab, setTab] = useState("scan"); const [loading, setLoading] = useState(true); const [error, setError] = useState(""); const [orig, setOrig] = useState({});
  // Signal Config — simple fields
  const [scoreThreshold, setScoreThreshold] = useState(""); const [bodyRatio, setBodyRatio] = useState(""); const [volMult, setVolMult] = useState(""); const [atrMin, setAtrMin] = useState(""); const [cooldown, setCooldown] = useState(""); const [aiThreshold, setAiThreshold] = useState(""); const [mtfEnabled, setMtfEnabled] = useState(false);
  // Signal Config — DERIVATIVE_CONFIG expanded
  const [derivBias15m, setDerivBias15m] = useState(""); const [derivBias1h, setDerivBias1h] = useState(""); const [derivBias4h, setDerivBias4h] = useState(""); const [derivPreBuffer, setDerivPreBuffer] = useState("");
  // Signal Config — RISK_CONFIG expanded
  const [riskSl15m, setRiskSl15m] = useState(""); const [riskTp15m, setRiskTp15m] = useState(""); const [riskSl1h, setRiskSl1h] = useState(""); const [riskTp1h, setRiskTp1h] = useState(""); const [riskSl4h, setRiskSl4h] = useState(""); const [riskTp4h, setRiskTp4h] = useState("");
  // Signal Config — PENDING_CONFIG expanded
  const [pendEnabled, setPendEnabled] = useState(true);
  const [pendAtr15m, setPendAtr15m] = useState(""); const [pendAtr1h, setPendAtr1h] = useState(""); const [pendAtr4h, setPendAtr4h] = useState("");
  const [pendExp15m, setPendExp15m] = useState(""); const [pendExp1h, setPendExp1h] = useState(""); const [pendExp4h, setPendExp4h] = useState("");
  const [s1, setS1] = useState(false); const [sv1, setSv1] = useState(false);
  // Scan Config
  const [engVer, setEngVer] = useState(""); const [topLimit, setTopLimit] = useState(""); const [maxOpenTrades, setMaxOpenTrades] = useState('50'); const [timeframe, setTimeframe] = useState("15m"); const [scheduler, setScheduler] = useState(false); const [monitor, setMonitor] = useState(false);
  const [s2, setS2] = useState(false); const [sv2, setSv2] = useState(false);
  // Trade Filter
  const [otfConfig, setOtfConfig] = useState(null); const [otfStatus, setOtfStatus] = useState(null); const [sOtf, setSOtf] = useState(false); const [svOtf, setSvOtf] = useState(false);
  // Pre-Fill
  const [pfConfig, setPfConfig] = useState(null); const [sPf, setSPf] = useState(false); const [svPf, setSvPf] = useState(false);
  // Strategies
  const [stratsList, setStratsList] = useState([]); const [sSt, setSSt] = useState(false); const [svSt, setSvSt] = useState(false);
  // System
  const [modeInfo, setModeInfo] = useState(null); const [feedInfo, setFeedInfo] = useState(null); const [mlInfo, setMlInfo] = useState(null); const [retraining, setRetraining] = useState(false); const [retainResult, setRetainResult] = useState(null);

  // Parse JSON configs into expanded fields
  const applyConfig = (c) => {
    setScoreThreshold(c["SCORE_THRESHOLD"]||""); setBodyRatio(c["BODY_RATIO_THRESHOLD"]||""); setVolMult(c["VOLUME_MULTIPLIER"]||""); setAtrMin(c["ATR_RATIO_MIN"]||""); setCooldown(c["COOLDOWN_HOURS"]||""); setAiThreshold(c["AI_THRESHOLD"]||""); setMtfEnabled(c["MTF_ENABLED"]?.toLowerCase()==="true");
    // DERIVATIVE_CONFIG
    try { const d = JSON.parse(c["DERIVATIVE_CONFIG"]||"{}"); setDerivBias15m(String(d.bias_scale?.["15m"] ?? "")); setDerivBias1h(String(d.bias_scale?.["1h"] ?? "")); setDerivBias4h(String(d.bias_scale?.["4h"] ?? "")); setDerivPreBuffer(String(d.pre_buffer ?? "")); } catch { setDerivBias15m(""); setDerivBias1h(""); setDerivBias4h(""); setDerivPreBuffer(""); }
    // RISK_CONFIG
    try { const r = JSON.parse(c["RISK_CONFIG"]||"{}"); setRiskSl15m(String(r["15m"]?.sl_mult ?? "")); setRiskTp15m(String(r["15m"]?.tp_mult ?? "")); setRiskSl1h(String(r["1h"]?.sl_mult ?? "")); setRiskTp1h(String(r["1h"]?.tp_mult ?? "")); setRiskSl4h(String(r["4h"]?.sl_mult ?? "")); setRiskTp4h(String(r["4h"]?.tp_mult ?? "")); } catch { setRiskSl15m(""); setRiskTp15m(""); setRiskSl1h(""); setRiskTp1h(""); setRiskSl4h(""); setRiskTp4h(""); }
    // PENDING_CONFIG
    try { const p = JSON.parse(c["PENDING_CONFIG"]||"{}"); setPendEnabled(p.enabled !== false); setPendAtr15m(String(p.atr_entry_multiplier?.["15m"] ?? "")); setPendAtr1h(String(p.atr_entry_multiplier?.["1h"] ?? "")); setPendAtr4h(String(p.atr_entry_multiplier?.["4h"] ?? "")); setPendExp15m(String(p.expire_hours?.["15m"] ?? "")); setPendExp1h(String(p.expire_hours?.["1h"] ?? "")); setPendExp4h(String(p.expire_hours?.["4h"] ?? "")); } catch { setPendEnabled(true); setPendAtr15m(""); setPendAtr1h(""); setPendAtr4h(""); setPendExp15m(""); setPendExp1h(""); setPendExp4h(""); }
    // Scan
    setEngVer(c["ENGINE_VERSION"]||""); setTopLimit(c["TOP_LIMIT"]||""); setTimeframe(c["TIMEFRAME"]||"15m"); setScheduler(c["ENABLE_SCHEDULER"]?.toLowerCase()==="true"); setMonitor(c["ENABLE_MONITOR"]?.toLowerCase()==="true"); setMaxOpenTrades(c['MAX_OPEN_TRADES']||'50');
  };

  // Rebuild JSON strings from expanded fields for save
  const buildDerivJson = () => JSON.stringify({ bias_scale: { "15m": parseFloat(derivBias15m) || 0, "1h": parseFloat(derivBias1h) || 0, "4h": parseFloat(derivBias4h) || 0 }, pre_buffer: parseFloat(derivPreBuffer) || 0 });
  const buildRiskJson = () => JSON.stringify({ "15m": { sl_mult: parseFloat(riskSl15m) || 0, tp_mult: parseFloat(riskTp15m) || 0 }, "1h": { sl_mult: parseFloat(riskSl1h) || 0, tp_mult: parseFloat(riskTp1h) || 0 }, "4h": { sl_mult: parseFloat(riskSl4h) || 0, tp_mult: parseFloat(riskTp4h) || 0 } });
  const buildPendJson = () => JSON.stringify({ enabled: pendEnabled, atr_entry_multiplier: { "15m": parseFloat(pendAtr15m) || 0, "1h": parseFloat(pendAtr1h) || 0, "4h": parseFloat(pendAtr4h) || 0 }, expire_hours: { "15m": parseFloat(pendExp15m) || 0, "1h": parseFloat(pendExp1h) || 0, "4h": parseFloat(pendExp4h) || 0 } });

  useEffect(() => { (async () => { setLoading(true); try { const [cfg, otf, pf, strats, mode, feed, mlEval] = await Promise.all([loadConfig(), otfApi.get().catch(() => ({ enabled: false })), prefillApi.get().catch(() => ({ enabled: true })), stratsApi.list().catch(() => null), tmApi.get().catch(() => null), fetch("/api/price-feed/status").then(r => r.json()).catch(() => null), ml.evaluate(30).catch(() => null)]); setOrig(cfg); applyConfig(cfg); setOtfConfig(otf); setPfConfig(pf);
    // Load strategies: prefer API, fallback to ACTIVE_STRATEGIES in app_config
    const ALL_STRATS = ["candlestick","breakout","mean_reversion","pullback","trend_following"];
    let allS = strats?.all || ALL_STRATS;
    let activeS = strats?.active || [];
    if (!activeS.length && cfg["ACTIVE_STRATEGIES"]) { activeS = cfg["ACTIVE_STRATEGIES"].split(",").map(s => s.trim()).filter(Boolean); }
    setStratsList(allS.map(name => ({ name, active: activeS.includes(name) })));
    setModeInfo(mode); setFeedInfo(feed); setMlInfo(mlEval); const s = await otfApi.status().catch(() => null); setOtfStatus(s); } catch (e) { setError(e.message); } finally { setLoading(false); } })(); }, []);

  const saveSignalConfig = async () => { setS1(true); setSv1(false); setError(""); try { await saveConfigKeys({ SCORE_THRESHOLD: scoreThreshold, BODY_RATIO_THRESHOLD: bodyRatio, VOLUME_MULTIPLIER: volMult, ATR_RATIO_MIN: atrMin, COOLDOWN_HOURS: cooldown, AI_THRESHOLD: aiThreshold, MTF_ENABLED: String(mtfEnabled), DERIVATIVE_CONFIG: buildDerivJson(), RISK_CONFIG: buildRiskJson(), PENDING_CONFIG: buildPendJson() }); setSv1(true); setTimeout(() => setSv1(false), 3000); toast.success("Signal config saved"); } catch (e) { setError(e.message); toast.error(e.message); } finally { setS1(false); } };
  const saveScanConfig = async () => { setS2(true); setSv2(false); setError(""); try { await saveConfigKeys({ ENGINE_VERSION: engVer, TOP_LIMIT: topLimit, TIMEFRAME: timeframe, ENABLE_SCHEDULER: String(scheduler), ENABLE_MONITOR: String(monitor), MAX_OPEN_TRADES: maxOpenTrades }); setSv2(true); setTimeout(() => setSv2(false), 3000); toast.success("Scan config saved"); } catch (e) { setError(e.message); toast.error(e.message); } finally { setS2(false); } };
  const updOtf = (path, value) => { setOtfConfig(prev => { if (!prev) return prev; const next = JSON.parse(JSON.stringify(prev)); const keys = path.split("."); let obj = next; for (let i = 0; i < keys.length - 1; i++) { if (!obj[keys[i]]) obj[keys[i]] = {}; obj = obj[keys[i]]; } obj[keys[keys.length - 1]] = value; return next; }); };
  const togOtfArr = (path, val) => { setOtfConfig(prev => { if (!prev) return prev; const next = JSON.parse(JSON.stringify(prev)); const keys = path.split("."); let arr = next; for (const k of keys) { if (!arr[k]) arr[k] = []; arr = arr[k]; } if (!Array.isArray(arr)) return next; const parent = keys.slice(0, -1).reduce((o, k) => o[k], next); const lastKey = keys[keys.length - 1]; const currentArr = parent[lastKey] || []; const idx = currentArr.indexOf(val); if (idx >= 0) { currentArr.splice(idx, 1); } else { currentArr.push(val); } parent[lastKey] = currentArr; return next; }); };
  const saveOtf = async () => { setSOtf(true); setSvOtf(false); try { await otfApi.save(otfConfig); setSvOtf(true); setTimeout(() => setSvOtf(false), 3000); toast.success("Trade Filter saved"); } catch (e) { toast.error(e.message); } finally { setSOtf(false); } };
  const updPf = (path, value) => { setPfConfig(prev => { if (!prev) return prev; const next = JSON.parse(JSON.stringify(prev)); const keys = path.split("."); let obj = next; for (let i = 0; i < keys.length - 1; i++) { if (!obj[keys[i]]) obj[keys[i]] = {}; obj = obj[keys[i]]; } obj[keys[keys.length - 1]] = value; return next; }); };
  const savePf = async () => { setSPf(true); setSvPf(false); try { await prefillApi.save(pfConfig); setSvPf(true); setTimeout(() => setSvPf(false), 3000); toast.success("Pre-Fill Config saved"); } catch (e) { toast.error(e.message); } finally { setSPf(false); } };
  const toggleStrat = (name) => { setStratsList(prev => prev.map(s => s.name === name ? { ...s, active: !s.active } : s)); };
  const saveStrats = async () => { setSSt(true); setSvSt(false); try { const active = stratsList.filter(s => s.active).map(s => s.name); if (!active.length) active.push("candlestick"); await saveConfigKeys({ ACTIVE_STRATEGIES: active.join(",") }); setSvSt(true); setTimeout(() => setSvSt(false), 3000); toast.success("Strategies saved"); } catch (e) { toast.error(e.message); } finally { setSSt(false); } };
  const switchMode = async (mode) => { if (mode === "LIVE" && !confirm("⚠️ LIVE mode uses REAL MONEY. Confirm?")) return; try { const r = await tmApi.set(mode); setModeInfo(r); toast.success(`Mode → ${mode}`); } catch (e) { toast.error(e.message); } };
  const retrain = async () => { setRetraining(true); setRetainResult(null); try { const r = await ml.retrain(false); setRetainResult(r); } catch (e) { toast.error(e.message); } finally { setRetraining(false); } };

  if (loading) return (<div className="flex items-center justify-center h-96"><div className="text-center"><Loader2 className="w-8 h-8 animate-spin text-indigo-500 mx-auto mb-4" /><p className="text-slate-400">Loading...</p></div></div>);

  const otf = otfConfig || {};
  const pf = pfConfig || {};

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div><h2 className="text-2xl font-bold text-white flex items-center gap-3"><SettingsIcon className="w-7 h-7 text-indigo-400" /> Settings</h2><p className="text-slate-400 mt-1">Runtime configuration from database (app_config)</p></div>
      </div>
      {error && (<div className="flex items-center gap-2 p-4 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm"><AlertCircle className="w-5 h-5 flex-shrink-0" />{error}</div>)}
      <div className="flex gap-2 bg-slate-800/50 p-1.5 rounded-xl overflow-x-auto">{TABS.map(t => (<button key={t.id} onClick={() => setTab(t.id)} className={`flex items-center gap-2 px-5 py-2.5 text-sm font-medium whitespace-nowrap rounded-lg transition-all ${tab === t.id ? "bg-indigo-600 text-white shadow-lg shadow-indigo-500/20" : "text-slate-400 hover:text-white hover:bg-slate-700/50"}`}><t.icon className="w-4 h-4" />{t.label}</button>))}</div>

      {/* ===================== SCAN CONFIG ===================== */}
      {tab === "scan" && (<Card padding="lg"><CardHeader title="Scan Runtime Config" subtitle="Scanner engine parameters" action={<Radar className="w-5 h-5 text-cyan-400" />} />
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-6"><NumField label="ENGINE_VERSION" value={engVer} onChange={setEngVer} hint="Engine version" step="0.01" /><NumField label="TOP_LIMIT" value={topLimit} onChange={setTopLimit} hint="Max symbols to scan" step="1" /><Field label="TIMEFRAME" hint="Scan timeframe"><Select value={timeframe} onChange={setTimeframe} options={[{value:"15m",label:"15m"},{value:"1h",label:"1h"},{value:"4h",label:"4h"}]} /></Field><NumField label="MAX_OPEN_TRADES" value={maxOpenTrades} onChange={setMaxOpenTrades} hint="Max concurrent open trades" step="1" /><BoolField label="ENABLE_SCHEDULER" value={scheduler} onChange={setScheduler} hint="Auto scan" /><BoolField label="ENABLE_MONITOR" value={monitor} onChange={setMonitor} hint="Monitor trades" /></div>
        <SaveRow saving={s2} saved={sv2} onSave={saveScanConfig} onCancel={() => applyConfig(orig)} /></Card>)}

      {/* ===================== SIGNAL CONFIG ===================== */}
      {tab === "signals" && (<Card padding="lg"><CardHeader title="Signal Runtime Config" subtitle="Signal detection & filtering parameters" action={<Crosshair className="w-5 h-5 text-yellow-400" />} />
        {/* Simple fields */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-6"><NumField label="SCORE_THRESHOLD" value={scoreThreshold} onChange={setScoreThreshold} hint="Min score" step="0.1" /><NumField label="BODY_RATIO_THRESHOLD" value={bodyRatio} onChange={setBodyRatio} hint="Candle body ratio" step="0.01" /><NumField label="VOLUME_MULTIPLIER" value={volMult} onChange={setVolMult} hint="Volume filter" step="0.1" /><NumField label="ATR_RATIO_MIN" value={atrMin} onChange={setAtrMin} hint="Min ATR ratio" step="0.0001" /><NumField label="COOLDOWN_HOURS" value={cooldown} onChange={setCooldown} hint="Hours between signals" step="1" /><NumField label="AI_THRESHOLD" value={aiThreshold} onChange={setAiThreshold} hint="ML probability" step="0.05" /><BoolField label="MTF_ENABLED" value={mtfEnabled} onChange={setMtfEnabled} hint="Multi-timeframe" /></div>

        {/* DERIVATIVE_CONFIG + RISK_CONFIG + PENDING_CONFIG — expanded */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mt-8">
          {/* DERIVATIVE_CONFIG */}
          <div className="p-4 bg-slate-900/30 rounded-lg border border-slate-700/50">
            <h4 className="text-sm font-semibold text-slate-300 mb-4">DERIVATIVE_CONFIG</h4>
            <div className="space-y-3">
              <NumField label="bias_scale · 15m" value={derivBias15m} onChange={setDerivBias15m} step="0.1" />
              <NumField label="bias_scale · 1h" value={derivBias1h} onChange={setDerivBias1h} step="0.1" />
              <NumField label="bias_scale · 4h" value={derivBias4h} onChange={setDerivBias4h} step="0.1" />
              <NumField label="pre_buffer" value={derivPreBuffer} onChange={setDerivPreBuffer} step="0.1" />
            </div>
          </div>
          {/* RISK_CONFIG */}
          <div className="p-4 bg-slate-900/30 rounded-lg border border-slate-700/50">
            <h4 className="text-sm font-semibold text-slate-300 mb-4">RISK_CONFIG</h4>
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3"><NumField label="15m · SL %" value={riskSl15m} onChange={setRiskSl15m} step="0.001" /><NumField label="15m · TP %" value={riskTp15m} onChange={setRiskTp15m} step="0.001" /></div>
              <div className="grid grid-cols-2 gap-3"><NumField label="1h · SL %" value={riskSl1h} onChange={setRiskSl1h} step="0.001" /><NumField label="1h · TP %" value={riskTp1h} onChange={setRiskTp1h} step="0.001" /></div>
              <div className="grid grid-cols-2 gap-3"><NumField label="4h · SL %" value={riskSl4h} onChange={setRiskSl4h} step="0.001" /><NumField label="4h · TP %" value={riskTp4h} onChange={setRiskTp4h} step="0.001" /></div>
            </div>
          </div>
          {/* PENDING_CONFIG */}
          <div className="p-4 bg-slate-900/30 rounded-lg border border-slate-700/50">
            <h4 className="text-sm font-semibold text-slate-300 mb-4">PENDING_CONFIG</h4>
            <div className="space-y-3">
              <BoolField label="Pending Enabled" value={pendEnabled} onChange={setPendEnabled} />
              <div className="grid grid-cols-2 gap-3"><NumField label="ATR mult · 15m" value={pendAtr15m} onChange={setPendAtr15m} step="0.1" /><NumField label="Expire hrs · 15m" value={pendExp15m} onChange={setPendExp15m} step="1" /></div>
              <div className="grid grid-cols-2 gap-3"><NumField label="ATR mult · 1h" value={pendAtr1h} onChange={setPendAtr1h} step="0.1" /><NumField label="Expire hrs · 1h" value={pendExp1h} onChange={setPendExp1h} step="1" /></div>
              <div className="grid grid-cols-2 gap-3"><NumField label="ATR mult · 4h" value={pendAtr4h} onChange={setPendAtr4h} step="0.1" /><NumField label="Expire hrs · 4h" value={pendExp4h} onChange={setPendExp4h} step="1" /></div>
            </div>
          </div>
        </div>
        <SaveRow saving={s1} saved={sv1} onSave={saveSignalConfig} onCancel={() => applyConfig(orig)} /></Card>)}

      {/* ===================== TRADE FILTER ===================== */}
      {tab === "filter" && otf && (<div className="space-y-4"><Card><div className="flex items-center justify-between mb-4"><div><h3 className="text-lg font-semibold text-white">Open Trade Filter</h3><p className="text-sm text-slate-400">Kiểm soát điều kiện trước khi mở lệnh</p></div><div className="flex items-center gap-3"><button onClick={() => updOtf("enabled", !otf.enabled)} className={`relative w-12 h-6 rounded-full transition ${otf.enabled ? "bg-green-500" : "bg-slate-600"}`}><span className={`absolute top-1 w-4 h-4 bg-white rounded-full transition-transform ${otf.enabled ? "translate-x-7" : "translate-x-1"}`} /></button><span className={`text-sm font-medium ${otf.enabled ? "text-green-400" : "text-slate-500"}`}>{otf.enabled ? "ACTIVE" : "OFF"}</span><Button variant="primary" size="sm" loading={sOtf} onClick={saveOtf}>{svOtf ? "✅ Saved" : "Save"}</Button></div></div>
        {otfStatus && (<div className="grid grid-cols-4 gap-3 mb-4">{[{ label: "Open Trades", value: otfStatus.open_trades, max: otf.position?.max_concurrent_trades }, { label: "Pending", value: otfStatus.pending_trades }, { label: "Today PnL", value: `${(otfStatus.today?.pnl_pct||0)>=0?"+":""}${(otfStatus.today?.pnl_pct||0).toFixed(2)}%` }, { label: "Loss Streak", value: otfStatus.current_loss_streak }].map((c,i) => (<div key={i} className="p-3 bg-slate-900/50 rounded-lg border border-slate-700"><div className="text-xs text-slate-400">{c.label}</div><div className="text-xl font-bold text-white mt-1">{c.value}{c.max !== undefined && <span className="text-sm text-slate-500 font-normal ml-1">/ {c.max}</span>}</div></div>))}</div>)}
        <div className="space-y-6">
          {/* A. Identity */}
          <div className="p-4 bg-slate-900/30 rounded-lg border border-slate-700/50"><h4 className="text-sm font-semibold text-slate-300 mb-3">🎯 A. Identity</h4><div className="space-y-3">
            <div className="flex gap-2 items-center"><span className="text-xs text-slate-400 w-24">Direction</span>{["LONG","SHORT"].map(d => (<button key={d} onClick={() => togOtfArr("identity.directions", d)} className={`px-3 py-1 rounded text-xs font-medium transition-colors ${(otf.identity?.directions||[]).includes(d) ? "bg-blue-600 text-white" : "bg-slate-700 text-slate-400 hover:bg-slate-600"}`}>{d}</button>))}</div>
            <div className="flex gap-2 items-center flex-wrap"><span className="text-xs text-slate-400 w-24">Strategies</span>{["candlestick","breakout","mean_reversion","pullback","trend_following"].map(s => (<button key={s} onClick={() => togOtfArr("identity.strategies", s)} className={`px-2 py-1 rounded text-xs font-medium transition-colors ${(otf.identity?.strategies||[]).includes(s) ? "bg-blue-600 text-white" : "bg-slate-700 text-slate-400 hover:bg-slate-600"}`}>{s}</button>))}{(otf.identity?.strategies||[]).length === 0 && <span className="text-xs text-slate-500 italic">(All allowed)</span>}</div>
            <div className="flex gap-2 items-center flex-wrap"><span className="text-xs text-slate-400 w-24">Patterns</span>{["engulfing","hammer","shooting_star","doji","morning_star","evening_star","harami","marubozu"].map(p => (<button key={p} onClick={() => togOtfArr("identity.patterns", p)} className={`px-2 py-1 rounded text-xs font-medium transition-colors ${(otf.identity?.patterns||[]).includes(p) ? "bg-blue-600 text-white" : "bg-slate-700 text-slate-400 hover:bg-slate-600"}`}>{p}</button>))}{(otf.identity?.patterns||[]).length === 0 && <span className="text-xs text-slate-500 italic">(All allowed)</span>}</div>
            <div className="flex gap-2 items-center"><span className="text-xs text-slate-400 w-24">Timeframes</span>{["15m","1h","4h"].map(tf => (<button key={tf} onClick={() => togOtfArr("identity.timeframes", tf)} className={`px-3 py-1 rounded text-xs font-medium transition-colors ${(otf.identity?.timeframes||["15m","1h","4h"]).includes(tf) ? "bg-blue-600 text-white" : "bg-slate-700 text-slate-400 hover:bg-slate-600"}`}>{tf}</button>))}</div>
            <div className="flex gap-2 items-center"><span className="text-xs text-slate-400 w-24">Regimes</span>{["BULL","BEAR","SIDEWAYS"].map(r => (<button key={r} onClick={() => togOtfArr("market_condition.allowed_regimes", r)} className={`px-2 py-1 rounded text-xs font-medium transition-colors ${(otf.market_condition?.allowed_regimes||["BULL","BEAR","SIDEWAYS"]).includes(r) ? "bg-blue-600 text-white" : "bg-slate-700 text-slate-400 hover:bg-slate-600"}`}>{r}</button>))}</div>
          </div></div>

          {/* B. Market — placeholder row if needed in future */}

          {/* C. Score + D. Position — same row */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="p-4 bg-slate-900/30 rounded-lg border border-slate-700/50"><h4 className="text-sm font-semibold text-slate-300 mb-3">⭐ C. Score Requirements</h4><div className="space-y-3">{[{key:"score.min_overall",label:"Min Score",step:0.5,min:0,max:10},{key:"score.min_ml_prob",label:"Min ML Prob",step:0.05,min:0,max:1},{key:"score.min_trend_score",label:"Min Trend",step:0.1,min:0,max:3},{key:"score.min_mtf_score",label:"Min MTF",step:0.05,min:0,max:1}].map(f => { const keys = f.key.split("."); const val = otf?.[keys[0]]?.[keys[1]] ?? 0; return (<div key={f.key}><label className="block text-xs text-slate-400 mb-1">{f.label}</label><input type="number" step={f.step} min={f.min} max={f.max} value={val} onChange={e => updOtf(f.key, parseFloat(e.target.value))} className="w-full px-2 py-1.5 bg-slate-900 border border-slate-600 rounded text-sm text-white font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500" /></div>); })}</div></div>
            <div className="p-4 bg-slate-900/30 rounded-lg border border-slate-700/50"><h4 className="text-sm font-semibold text-slate-300 mb-3">📐 D. Position Management</h4><div className="space-y-3">{[{key:"position.max_concurrent_trades",label:"Max Concurrent",step:1,min:1,max:100},{key:"position.max_per_symbol",label:"Max / Symbol",step:1,min:1,max:10},{key:"position.max_daily_trades",label:"Max Daily Trades",step:1,min:0,max:200},{key:"position.max_daily_loss_pct",label:"Max Daily Loss %",step:0.5,min:0,max:50},{key:"position.pause_after_loss_streak",label:"Pause After Streak",step:1,min:0,max:20}].map(f => { const keys = f.key.split("."); const val = otf?.[keys[0]]?.[keys[1]] ?? 0; return (<div key={f.key}><label className="block text-xs text-slate-400 mb-1">{f.label}</label><input type="number" step={f.step} min={f.min} max={f.max} value={val} onChange={e => updOtf(f.key, parseFloat(e.target.value))} className="w-full px-2 py-1.5 bg-slate-900 border border-slate-600 rounded text-sm text-white font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500" /></div>); })}</div></div>
          </div>

          {/* E. Time */}
          <div className="p-4 bg-slate-900/30 rounded-lg border border-slate-700/50"><h4 className="text-sm font-semibold text-slate-300 mb-3">🕐 E. Time Restrictions (UTC+7)</h4><label className="flex items-center gap-2 cursor-pointer mb-3"><input type="checkbox" checked={otf.time?.enabled || false} onChange={e => updOtf("time.enabled", e.target.checked)} className="w-4 h-4 accent-blue-500" /><span className="text-sm text-slate-300">Enable time restriction</span></label>{otf.time?.enabled && (<div className="flex items-center gap-3"><input type="time" value={otf.time?.allowed_hours?.start || "00:00"} onChange={e => updOtf("time.allowed_hours.start", e.target.value)} className="px-2 py-1 bg-slate-900 border border-slate-600 rounded text-sm text-white" /><span className="text-slate-500">→</span><input type="time" value={otf.time?.allowed_hours?.end || "23:59"} onChange={e => updOtf("time.allowed_hours.end", e.target.value)} className="px-2 py-1 bg-slate-900 border border-slate-600 rounded text-sm text-white" /></div>)}</div>
        </div></Card></div>)}

      {/* ===================== PRE-FILL ===================== */}
      {tab === "prefill" && pf && (<div className="space-y-4"><Card><div className="flex items-center justify-between mb-4"><div><h3 className="text-lg font-semibold text-white">Pre-Fill Validation</h3><p className="text-sm text-slate-400">Kiểm tra thị trường TRƯỚC khi fill Pending → Signal</p></div><div className="flex items-center gap-3"><button onClick={() => updPf("enabled", !pf.enabled)} className={`relative w-12 h-6 rounded-full transition ${pf.enabled ? "bg-green-500" : "bg-slate-600"}`}><span className={`absolute top-1 w-4 h-4 bg-white rounded-full transition-transform ${pf.enabled ? "translate-x-7" : "translate-x-1"}`} /></button><span className={`text-sm font-medium ${pf.enabled ? "text-green-400" : "text-slate-500"}`}>{pf.enabled ? "ACTIVE" : "OFF"}</span><Button variant="primary" size="sm" loading={sPf} onClick={savePf}>{svPf ? "✅ Saved" : "Save"}</Button></div></div>
        {[{ key: "price_context", title: "1. Price Context", subtitle: "Giá di chuyển ngược quá nhiều từ lúc scan?", fields: [{ label:"Max adverse 15m %", path:"price_context.max_adverse_move_pct.15m", step:0.1, min:0, max:10 }, { label:"Max adverse 1h %", path:"price_context.max_adverse_move_pct.1h", step:0.1, min:0, max:10 }, { label:"Max adverse 4h %", path:"price_context.max_adverse_move_pct.4h", step:0.1, min:0, max:10 }] }, { key: "candle_invalidation", title: "2. Candle Invalidation", subtitle: "Nến body lớn ngược chiều phá mô hình?", fields: [{ label:"Adverse body ATR mult", path:"candle_invalidation.adverse_body_atr_mult", step:0.1, min:0.5, max:5 }] }, { key: "momentum_check", title: "3. Momentum Check", subtitle: "RSI vẫn hỗ trợ direction?", fields: [{ label:"Reject LONG if RSI above", path:"momentum_check.rsi_reject_long_above", step:1, min:50, max:100 }, { label:"Reject SHORT if RSI below", path:"momentum_check.rsi_reject_short_below", step:1, min:0, max:50 }] }, { key: "volatility_guard", title: "4. Volatility Guard", subtitle: "ATR spike so với lúc scan?", fields: [{ label:"ATR spike multiplier", path:"volatility_guard.atr_spike_multiplier", step:0.1, min:1, max:5 }] }, { key: "regime_check", title: "5. Regime Check", subtitle: "Regime flip → conflict direction → reject", fields: [] }].map(section => (<div key={section.key} className="p-4 bg-slate-900/30 rounded-lg border border-slate-700/50 mb-3"><div className="flex items-center gap-3 mb-3"><label className="flex items-center gap-2 cursor-pointer"><input type="checkbox" checked={pf[section.key]?.enabled ?? true} onChange={e => updPf(`${section.key}.enabled`, e.target.checked)} className="w-4 h-4 accent-blue-500" /><span className="text-sm font-semibold text-slate-300">{section.title}</span></label><span className="text-xs text-slate-500">{section.subtitle}</span></div>{pf[section.key]?.enabled && section.fields.length > 0 && (<div className="grid grid-cols-1 md:grid-cols-3 gap-4 ml-6">{section.fields.map(f => { const keys = f.path.split("."); let val = pf; for (const k of keys) val = val?.[k]; return (<div key={f.path}><label className="block text-xs text-slate-400 mb-1">{f.label}</label><input type="number" step={f.step} min={f.min} max={f.max} value={val ?? 0} onChange={e => updPf(f.path, parseFloat(e.target.value))} className="w-full px-2 py-1.5 bg-slate-900 border border-slate-600 rounded text-sm text-white" /></div>); })}</div>)}</div>))}
        <div className="flex justify-end pt-2"><Button variant="primary" loading={sPf} onClick={savePf}>{svPf ? "✅ Saved!" : "💾 Save Prefill Config"}</Button></div></Card></div>)}

      {/* ===================== STRATEGIES ===================== */}
      {tab === "strats" && (()=>{ const STRAT_DESC = { candlestick: "Mô hình nến: Engulfing, Hammer, Star...", breakout: "Phá vỡ swing high/low + volume surge", mean_reversion: "RSI extreme + BB touch → đảo chiều", pullback: "Trend mạnh → giá về EMA50", trend_following: "EMA crossover + volume confirm" }; return (<Card><div className="flex items-center justify-between mb-4"><div><h3 className="text-lg font-semibold text-white">Strategy Management</h3><p className="text-sm text-slate-400">Bật/tắt chiến thuật giao dịch</p></div><Button variant="primary" size="sm" loading={sSt} onClick={saveStrats}>{svSt ? "✅ Saved" : "Save"}</Button></div><div className="space-y-3">{stratsList.map(s => (<div key={s.name} className="flex items-center p-4 bg-slate-900/30 rounded-xl border border-slate-700"><button onClick={() => toggleStrat(s.name)} className={`relative w-10 h-5 rounded-full transition flex-shrink-0 ${s.active ? "bg-green-500" : "bg-slate-600"}`}><span className={`absolute top-0.5 w-4 h-4 bg-white rounded-full transition-transform ${s.active ? "translate-x-5" : "translate-x-0.5"}`} /></button><div className="ml-4"><div className="flex items-center gap-2"><span className="font-medium text-white capitalize">{s.name.replace(/_/g, " ")}</span><span className={`text-xs ${s.active ? "text-emerald-400" : "text-slate-500"}`}>{s.active ? "● Active" : "○ Inactive"}</span></div><div className="text-xs text-slate-500 mt-0.5">{STRAT_DESC[s.name] || ""}</div></div></div>))}</div></Card>); })()}

      {/* ===================== SYSTEM ===================== */}
      {tab === "system" && (<div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card padding="lg"><h3 className="text-lg font-semibold text-white mb-4">🔄 Trading Mode</h3><div className="flex gap-3 mb-4">{["PAPER","TESTNET","LIVE"].map(m => { const colors = { PAPER: "bg-blue-900/30 border-blue-700 text-blue-300", TESTNET: "bg-yellow-900/30 border-yellow-700 text-yellow-300", LIVE: "bg-red-900/30 border-red-700 text-red-300" }; const current = modeInfo?.mode === m; return (<button key={m} onClick={() => switchMode(m)} className={`flex-1 py-3 rounded-lg border font-medium text-sm transition ${current ? colors[m] : "bg-slate-700 border-slate-600 text-slate-300 hover:bg-slate-600"}`}>{m === "PAPER" ? "📋 PAPER" : m === "TESTNET" ? "🧪 TESTNET" : "💰 LIVE"}</button>); })}</div>{modeInfo && (<div className="p-3 bg-slate-900/30 rounded-lg border border-slate-700 text-sm text-slate-300">{modeInfo.description}</div>)}</Card>
        <Card padding="lg"><h3 className="text-lg font-semibold text-white mb-4">📡 Price Feed</h3>{feedInfo ? (<div className="grid grid-cols-2 md:grid-cols-4 gap-4">{[{ label: "Status", value: feedInfo.healthy ? "🟢 Healthy" : "🔴 Unhealthy" }, { label: "Mode", value: (feedInfo.mode || "").toUpperCase() }, { label: "Symbols", value: feedInfo.symbols_count }, { label: "Last Update", value: feedInfo.last_update_ago_s != null ? `${feedInfo.last_update_ago_s}s ago` : "—" }].map((item, i) => (<div key={i} className="bg-slate-900/30 rounded-lg p-3 text-center"><div className="text-xs text-slate-400">{item.label}</div><div className="text-white font-medium mt-1">{item.value}</div></div>))}</div>) : <div className="text-slate-400 text-sm">Loading...</div>}</Card>
        <Card padding="lg"><div className="flex items-center justify-between mb-4"><h3 className="text-lg font-semibold text-white">🤖 ML Model</h3><Button variant="secondary" size="sm" loading={retraining} onClick={retrain}>🔁 Retrain</Button></div>{mlInfo && !mlInfo.error ? (<div className="space-y-3"><div className="grid grid-cols-3 gap-3">{[{ label: "Signals (30d)", value: mlInfo.total_signals }, { label: "AUC", value: mlInfo.auc?.toFixed(4) }, { label: "Win Rate", value: `${(mlInfo.overall_winrate*100).toFixed(1)}%` }].map((item, i) => (<div key={i} className="bg-slate-900/30 rounded-lg p-3 text-center"><div className="text-xs text-slate-400">{item.label}</div><div className="text-white font-medium mt-1">{item.value}</div></div>))}</div>{mlInfo.threshold_analysis?.length > 0 && (<div className="overflow-x-auto"><table className="w-full text-xs"><thead><tr className="text-slate-400 border-b border-slate-700"><th className="text-left py-1">Threshold</th><th className="text-right py-1">Signals</th><th className="text-right py-1">Win Rate</th><th className="text-right py-1">Avg Return</th></tr></thead><tbody>{mlInfo.threshold_analysis.map(t => (<tr key={t.threshold} className="border-b border-slate-800"><td className="py-1 text-white">≥{t.threshold}</td><td className="py-1 text-right">{t.n_signals}</td><td className={`py-1 text-right ${t.winrate>=0.55?"text-green-400":"text-gray-300"}`}>{(t.winrate*100).toFixed(1)}%</td><td className={`py-1 text-right ${t.avg_return>0?"text-green-400":"text-red-400"}`}>{t.avg_return>0?"+":""}{t.avg_return?.toFixed(2)}%</td></tr>))}</tbody></table></div>)}</div>) : <div className="text-slate-400 text-sm">{mlInfo?.error || "Loading..."}</div>}{retainResult && (<div className={`mt-3 p-3 rounded-lg border text-sm ${retainResult.status === "success" ? "bg-green-900/30 border-green-700 text-green-300" : "bg-slate-700 border-slate-600 text-slate-300"}`}>{retainResult.status === "success" && `✅ AUC: ${retainResult.avg_auc?.toFixed(4)} | Samples: ${retainResult.train_size}`}{retainResult.status === "skipped" && `⏭ ${retainResult.reason}`}{retainResult.status === "rejected" && `❌ ${retainResult.reason}`}</div>)}</Card>
        <Card padding="lg"><h3 className="text-lg font-semibold text-white mb-4">⚡ Admin Actions</h3><div className="flex flex-wrap gap-3"><Button variant="secondary" onClick={async () => { const r = await fetch("/api/admin/cancel-all-pending",{method:"POST"}).then(r=>r.json()); toast.success(`Cancelled ${r.cancelled} pending`); }}>🚫 Cancel All Pending</Button><Button variant="secondary" onClick={async () => { await fetch("/api/admin/refresh-views",{method:"POST"}); toast.success("Views refreshed"); }}>♻️ Refresh DB Views</Button></div></Card>
      </div>)}
    </div>
  );
}
