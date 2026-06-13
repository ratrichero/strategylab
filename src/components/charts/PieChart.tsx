import {
  PieChart as RechartsPieChart,
  Pie,
  Cell,
  ResponsiveContainer,
  Tooltip,
  Legend,
} from 'recharts';

interface PieChartProps {
  data: { name: string; value: number }[];
  height?: number;
  showLegend?: boolean;
  showLabels?: boolean;
  donut?: boolean;
  className?: string;
}

const COLORS = ['#6366f1', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4', '#ec4899', '#84cc16'];

export function PieChart({
  data,
  height = 300,
  showLegend = true,
  showLabels = false,
  donut = false,
  className,
}: PieChartProps) {
  const total = data.reduce((sum, item) => sum + item.value, 0);

  const CustomTooltip = ({ active, payload }: any) => {
    if (active && payload && payload.length) {
      const item = payload[0];
      const percentage = ((item.value / total) * 100).toFixed(1);
      return (
        <div className="bg-slate-800 border border-slate-700 rounded-lg p-3 shadow-lg">
          <p className="text-white font-medium">{item.name}</p>
          <p className="text-slate-400 text-sm">
            {item.value.toLocaleString()} ({percentage}%)
          </p>
        </div>
      );
    }
    return null;
  };

  const renderCustomLabel = ({ cx, cy, midAngle, innerRadius, outerRadius, percent }: any) => {
    if (percent < 0.05) return null;
    const RADIAN = Math.PI / 180;
    const radius = innerRadius + (outerRadius - innerRadius) * 0.5;
    const x = cx + radius * Math.cos(-midAngle * RADIAN);
    const y = cy + radius * Math.sin(-midAngle * RADIAN);

    return (
      <text
        x={x}
        y={y}
        fill="white"
        textAnchor="middle"
        dominantBaseline="central"
        fontSize={12}
        fontWeight={500}
      >
        {`${(percent * 100).toFixed(0)}%`}
      </text>
    );
  };

  return (
    <div className={className}>
      <ResponsiveContainer width="100%" height={height}>
        <RechartsPieChart>
          <Pie
            data={data}
            cx="50%"
            cy="50%"
            labelLine={false}
            label={showLabels ? renderCustomLabel : undefined}
            outerRadius={height / 3}
            innerRadius={donut ? height / 5 : 0}
            fill="#8884d8"
            dataKey="value"
            animationBegin={0}
            animationDuration={500}
          >
            {data.map((_, index) => (
              <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
            ))}
          </Pie>
          <Tooltip content={<CustomTooltip />} />
          {showLegend && (
            <Legend
              layout="vertical"
              verticalAlign="middle"
              align="right"
              iconType="circle"
              iconSize={10}
              formatter={(value) => <span className="text-slate-300 text-sm">{value}</span>}
            />
          )}
        </RechartsPieChart>
      </ResponsiveContainer>
    </div>
  );
}
