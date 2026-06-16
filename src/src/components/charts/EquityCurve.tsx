import { useMemo } from 'react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts';
import { format } from 'date-fns';
import type { EquityPoint } from '../../types/database';

interface EquityCurveProps { data: EquityPoint[]; height?: number; showDrawdown?: boolean; baseline?: number; compareData?: EquityPoint[]; className?: string; }

export function EquityCurve({ data, height = 300, showDrawdown = false, baseline, compareData, className }: EquityCurveProps) {
  const chartData = useMemo(() => data.map((point, i) => ({ ...point, date: format(new Date(point.timestamp), 'MM/dd'), compare: compareData?.[i]?.equity })), [data, compareData]);
  const minEquity = Math.min(...data.map(d => d.equity)) * 0.98;
  const maxEquity = Math.max(...data.map(d => d.equity)) * 1.02;
  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      return (<div className="bg-slate-800 border border-slate-700 rounded-lg p-3 shadow-lg"><p className="text-slate-400 text-sm mb-1">{label}</p><p className="text-white font-medium">${payload[0].value.toLocaleString(undefined, { minimumFractionDigits: 2 })}</p>{payload[0].payload.drawdown > 0 && <p className="text-red-400 text-sm">DD: -{payload[0].payload.drawdown.toFixed(2)}%</p>}{payload[0].payload.trade_count > 0 && <p className="text-slate-400 text-sm">Trades: {payload[0].payload.trade_count}</p>}</div>);
    }
    return null;
  };
  return (
    <div className={className}>
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={chartData} margin={{ top: 10, right: 10, left: 10, bottom: 0 }}>
          <defs><linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#6366f1" stopOpacity={0.3} /><stop offset="95%" stopColor="#6366f1" stopOpacity={0} /></linearGradient><linearGradient id="compareGradient" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#10b981" stopOpacity={0.3} /><stop offset="95%" stopColor="#10b981" stopOpacity={0} /></linearGradient></defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.5} /><XAxis dataKey="date" stroke="#64748b" fontSize={12} tickLine={false} axisLine={false} /><YAxis stroke="#64748b" fontSize={12} tickLine={false} axisLine={false} domain={[minEquity, maxEquity]} tickFormatter={(v) => `$${(v / 1000).toFixed(1)}k`} /><Tooltip content={<CustomTooltip />} />{baseline && <ReferenceLine y={baseline} stroke="#64748b" strokeDasharray="5 5" />}{compareData && <Area type="monotone" dataKey="compare" stroke="#10b981" strokeWidth={2} fill="url(#compareGradient)" dot={false} />}<Area type="monotone" dataKey="equity" stroke="#6366f1" strokeWidth={2} fill="url(#equityGradient)" dot={false} />
        </AreaChart>
      </ResponsiveContainer>
      {showDrawdown && (
        <ResponsiveContainer width="100%" height={80}>
          <AreaChart data={chartData} margin={{ top: 10, right: 10, left: 10, bottom: 0 }}>
            <defs><linearGradient id="ddGradient" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#ef4444" stopOpacity={0.3} /><stop offset="95%" stopColor="#ef4444" stopOpacity={0} /></linearGradient></defs>
            <XAxis dataKey="date" hide /><YAxis stroke="#64748b" fontSize={10} tickLine={false} axisLine={false} orientation="right" tickFormatter={(v) => `-${v}%`} /><Area type="monotone" dataKey="drawdown" stroke="#ef4444" strokeWidth={1} fill="url(#ddGradient)" dot={false} />
          </AreaChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
