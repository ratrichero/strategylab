import {
  ScatterChart as RechartsScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ZAxis,
  Legend,
} from 'recharts';

interface ScatterChartProps {
  data: Record<string, any>[];
  xKey: string;
  yKey: string;
  zKey?: string;
  colorKey?: string;
  xLabel?: string;
  yLabel?: string;
  height?: number;
  onPointClick?: (data: any) => void;
  className?: string;
}

export function ScatterChart({
  data,
  xKey,
  yKey,
  zKey,
  colorKey,
  xLabel,
  yLabel,
  height = 400,
  onPointClick,
  className,
}: ScatterChartProps) {


  const CustomTooltip = ({ active, payload }: any) => {
    if (active && payload && payload.length) {
      const data = payload[0].payload;
      return (
        <div className="bg-slate-800 border border-slate-700 rounded-lg p-3 shadow-lg">
          <p className="text-white font-medium mb-1">{data.symbol || data.id || 'Point'}</p>
          <p className="text-slate-400 text-sm">
            {xLabel || xKey}: {typeof data[xKey] === 'number' ? data[xKey].toFixed(2) : data[xKey]}
          </p>
          <p className="text-slate-400 text-sm">
            {yLabel || yKey}: {typeof data[yKey] === 'number' ? data[yKey].toFixed(2) : data[yKey]}
          </p>
          {zKey && (
            <p className="text-slate-400 text-sm">
              {zKey}: {typeof data[zKey] === 'number' ? data[zKey].toFixed(2) : data[zKey]}
            </p>
          )}
        </div>
      );
    }
    return null;
  };

  // Group data by color key if provided
  const groupedData = colorKey
    ? data.reduce((acc, item) => {
        const key = item[colorKey] > 0 ? 'Positive' : item[colorKey] < 0 ? 'Negative' : 'Neutral';
        if (!acc[key]) acc[key] = [];
        acc[key].push(item);
        return acc;
      }, {} as Record<string, any[]>)
    : { All: data };

  const colors = { Positive: '#10b981', Negative: '#ef4444', Neutral: '#6366f1', All: '#6366f1' };

  return (
    <div className={className}>
      <ResponsiveContainer width="100%" height={height}>
        <RechartsScatterChart margin={{ top: 20, right: 20, bottom: 20, left: 20 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.5} />
          <XAxis
            type="number"
            dataKey={xKey}
            name={xLabel || xKey}
            stroke="#64748b"
            fontSize={12}
            tickLine={false}
            axisLine={false}
            label={{ value: xLabel || xKey, position: 'bottom', fill: '#64748b', fontSize: 12 }}
          />
          <YAxis
            type="number"
            dataKey={yKey}
            name={yLabel || yKey}
            stroke="#64748b"
            fontSize={12}
            tickLine={false}
            axisLine={false}
            label={{ value: yLabel || yKey, angle: -90, position: 'left', fill: '#64748b', fontSize: 12 }}
          />
          {zKey && <ZAxis type="number" dataKey={zKey} range={[50, 400]} />}
          <Tooltip content={<CustomTooltip />} />
          {Object.keys(groupedData).length > 1 && <Legend />}
          {Object.entries(groupedData).map(([key, items]) => (
            <Scatter
              key={key}
              name={key}
              data={items}
              fill={colors[key as keyof typeof colors] || '#6366f1'}
              onClick={onPointClick}
              style={{ cursor: onPointClick ? 'pointer' : 'default' }}
            />
          ))}
        </RechartsScatterChart>
      </ResponsiveContainer>
    </div>
  );
}
