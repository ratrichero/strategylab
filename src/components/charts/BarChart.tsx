import { BarChart as RechartsBarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, Cell } from 'recharts';

interface BarChartProps { data: Record<string, any>[]; xKey: string; yKey: string; yKey2?: string; height?: number; colorByValue?: boolean; showLegend?: boolean; horizontal?: boolean; className?: string; }

export function BarChart({ data, xKey, yKey, yKey2, height = 300, colorByValue = false, showLegend = false, horizontal = false, className }: BarChartProps) {
  const getBarColor = (value: number) => { if (!colorByValue) return '#6366f1'; return value >= 50 ? '#10b981' : value >= 40 ? '#f59e0b' : '#ef4444'; };
  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      return (<div className="bg-slate-800 border border-slate-700 rounded-lg p-3 shadow-lg"><p className="text-slate-400 text-sm mb-1">{label}</p>{payload.map((entry: any, index: number) => (<p key={index} className="text-white font-medium" style={{ color: entry.color }}>{entry.name}: {typeof entry.value === 'number' ? entry.value.toFixed(2) : entry.value}</p>))}</div>);
    }
    return null;
  };
  if (horizontal) {
    return (<div className={className}><ResponsiveContainer width="100%" height={height}><RechartsBarChart data={data} layout="vertical" margin={{ top: 10, right: 30, left: 80, bottom: 0 }}><CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.5} horizontal={true} vertical={false} /><XAxis type="number" stroke="#64748b" fontSize={12} tickLine={false} axisLine={false} /><YAxis type="category" dataKey={xKey} stroke="#64748b" fontSize={12} tickLine={false} axisLine={false} width={70} /><Tooltip content={<CustomTooltip />} />{showLegend && <Legend />}<Bar dataKey={yKey} fill="#6366f1" radius={[0, 4, 4, 0]}>{colorByValue && data.map((entry, index) => <Cell key={`cell-${index}`} fill={getBarColor(entry[yKey])} />)}</Bar>{yKey2 && <Bar dataKey={yKey2} fill="#10b981" radius={[0, 4, 4, 0]} />}</RechartsBarChart></ResponsiveContainer></div>);
  }
  return (<div className={className}><ResponsiveContainer width="100%" height={height}><RechartsBarChart data={data} margin={{ top: 10, right: 10, left: 10, bottom: 0 }}><CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.5} vertical={false} /><XAxis dataKey={xKey} stroke="#64748b" fontSize={12} tickLine={false} axisLine={false} /><YAxis stroke="#64748b" fontSize={12} tickLine={false} axisLine={false} /><Tooltip content={<CustomTooltip />} />{showLegend && <Legend />}<Bar dataKey={yKey} fill="#6366f1" radius={[4, 4, 0, 0]}>{colorByValue && data.map((entry, index) => <Cell key={`cell-${index}`} fill={getBarColor(entry[yKey])} />)}</Bar>{yKey2 && <Bar dataKey={yKey2} fill="#10b981" radius={[4, 4, 0, 0]} />}</RechartsBarChart></ResponsiveContainer></div>);
}
