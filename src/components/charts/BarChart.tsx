import { BarChart as RechartsBarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, Cell, defs } from 'recharts';

interface BarChartProps {
  data: Record<string, any>[];
  xKey: string;
  yKey: string;
  yKey2?: string;
  height?: number;
  colorByValue?: boolean;
  showLegend?: boolean;
  horizontal?: boolean;
  className?: string;
}

const getBarColor = (value: number, defaultColor = '#6366f1') => {
  if (value === undefined || value === null || Number.isNaN(value)) return defaultColor;
  if (value >= 50) return '#10b981';
  if (value >= 40) return '#f59e0b';
  return '#ef4444';
};

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-slate-900 border border-slate-700 rounded-2xl p-3 shadow-2xl text-sm">
      <p className="text-slate-400 text-xs uppercase tracking-[0.18em] mb-2">{label}</p>
      {payload.map((entry: any, index: number) => (
        <div key={index} className="flex items-center justify-between gap-3 mb-1">
          <span className="text-slate-300">{entry.name}</span>
          <span className="font-semibold text-white" style={{ color: entry.color }}>{typeof entry.value === 'number' ? entry.value.toFixed(2) : entry.value}</span>
        </div>
      ))}
    </div>
  );
};

export function BarChart({
  data,
  xKey,
  yKey,
  yKey2,
  height = 300,
  colorByValue = false,
  showLegend = false,
  horizontal = false,
  className,
}: BarChartProps) {
  const config = {
    gridStroke: '#334155',
    gridOpacity: 0.25,
    axisStroke: '#64748b',
    tickColor: '#94a3b8',
  };

  const commonProps = {
    margin: { top: 16, right: 16, left: 16, bottom: 8 },
  };

  const barRadius = horizontal ? [0, 10, 10, 0] : [10, 10, 0, 0];
  const barSize = horizontal ? 18 : 22;

  return (
    <div className={className}>
      <ResponsiveContainer width="100%" height={height}>
        <RechartsBarChart
          data={data}
          {...commonProps}
          layout={horizontal ? 'vertical' : undefined}
          barCategoryGap="20%"
          barGap={8}
        >
          <CartesianGrid
            stroke={config.gridStroke}
            strokeDasharray="4 4"
            opacity={config.gridOpacity}
            vertical={false}
          />
          <XAxis
            dataKey={horizontal ? undefined : xKey}
            type={horizontal ? 'number' : 'category'}
            stroke={config.axisStroke}
            tick={{ fill: config.tickColor, fontSize: 12 }}
            tickLine={false}
            axisLine={false}
            minTickGap={12}
          />
          <YAxis
            dataKey={horizontal ? xKey : undefined}
            type={horizontal ? 'category' : 'number'}
            stroke={config.axisStroke}
            tick={{ fill: config.tickColor, fontSize: 12 }}
            tickLine={false}
            axisLine={false}
            width={horizontal ? 100 : undefined}
          />
          <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(148, 163, 184, 0.08)' }} />
          {showLegend && <Legend verticalAlign="top" height={24} />}
          <Bar dataKey={yKey} fill="#6366f1" radius={barRadius} barSize={barSize}>
            {colorByValue && data.map((entry, index) => (
              <Cell key={`cell-${index}`} fill={getBarColor(entry[yKey])} />
            ))}
          </Bar>
          {yKey2 && <Bar dataKey={yKey2} fill="#10b981" radius={barRadius} barSize={barSize} />}
        </RechartsBarChart>
      </ResponsiveContainer>
    </div>
  );
}
