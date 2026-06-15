import { useMemo } from 'react';
import { cn } from '../../utils/cn';

interface HeatmapData { x: string; y: string; value: number; count?: number; }
interface HeatmapProps { data: HeatmapData[]; xLabel?: string; yLabel?: string; valueLabel?: string; colorScale?: 'green-red' | 'blue-orange' | 'single'; showValues?: boolean; onCellClick?: (data: HeatmapData) => void; className?: string; }

export function Heatmap({ data, xLabel, yLabel, valueLabel = 'Value', colorScale = 'green-red', showValues = true, onCellClick, className }: HeatmapProps) {
  const { xValues, yValues, grid, minValue, maxValue } = useMemo(() => {
    const xSet = new Set(data.map(d => d.x)); const ySet = new Set(data.map(d => d.y));
    const xValues = Array.from(xSet); const yValues = Array.from(ySet);
    const grid: Record<string, Record<string, HeatmapData>> = {};
    let minValue = Infinity; let maxValue = -Infinity;
    for (const item of data) { if (!grid[item.y]) grid[item.y] = {}; grid[item.y][item.x] = item; minValue = Math.min(minValue, item.value); maxValue = Math.max(maxValue, item.value); }
    return { xValues, yValues, grid, minValue, maxValue };
  }, [data]);

  const getColor = (value: number): string => {
    const normalized = (value - minValue) / (maxValue - minValue || 1);
    if (colorScale === 'green-red') { if (normalized >= 0.5) { const intensity = (normalized - 0.5) * 2; return `rgba(16, 185, 129, ${0.3 + intensity * 0.7})`; } else { const intensity = (0.5 - normalized) * 2; return `rgba(239, 68, 68, ${0.3 + intensity * 0.7})`; } }
    else if (colorScale === 'blue-orange') { if (normalized >= 0.5) { const intensity = (normalized - 0.5) * 2; return `rgba(249, 115, 22, ${0.3 + intensity * 0.7})`; } else { const intensity = (0.5 - normalized) * 2; return `rgba(59, 130, 246, ${0.3 + intensity * 0.7})`; } }
    else { return `rgba(99, 102, 241, ${0.2 + normalized * 0.8})`; }
  };
  const getTextColor = (value: number): string => { const normalized = (value - minValue) / (maxValue - minValue || 1); return normalized > 0.3 && normalized < 0.7 ? '#cbd5e1' : '#ffffff'; };

  return (
    <div className={cn('space-y-4', className)}>
      <div className="flex items-center justify-end gap-4 text-sm">
        <span className="text-slate-400">{valueLabel}:</span>
        <div className="flex items-center gap-1"><div className="w-4 h-4 rounded" style={{ backgroundColor: getColor(minValue) }} /><span className="text-slate-400">{minValue.toFixed(1)}</span></div>
        <div className="w-20 h-2 rounded bg-gradient-to-r from-red-500/50 via-slate-500/50 to-emerald-500/50" />
        <div className="flex items-center gap-1"><div className="w-4 h-4 rounded" style={{ backgroundColor: getColor(maxValue) }} /><span className="text-slate-400">{maxValue.toFixed(1)}</span></div>
      </div>
      <div className="overflow-x-auto">
        <div className="inline-block min-w-full">
          <div className="flex"><div className="w-40 flex-shrink-0" />{xValues.map(x => <div key={x} className="flex-1 min-w-24 px-1 py-2 text-center text-sm text-slate-300 font-medium">{x}</div>)}</div>
          {yValues.map(y => (
            <div key={y} className="flex">
              <div className="w-40 flex-shrink-0 px-2 py-2 text-right text-sm text-slate-300 font-medium">{y}</div>
              {xValues.map(x => {
                const cell = grid[y]?.[x]; const value = cell?.value ?? 0;
                return (<div key={`${x}-${y}`} className={cn('flex-1 min-w-24 min-h-12 flex items-center justify-center m-0.5 rounded transition-transform', onCellClick && 'cursor-pointer hover:scale-105')} style={{ backgroundColor: getColor(value) }} onClick={() => cell && onCellClick?.(cell)} title={cell ? `${xLabel || 'X'}: ${x}, ${yLabel || 'Y'}: ${y}, ${valueLabel}: ${value.toFixed(2)}${cell.count ? `, Count: ${cell.count}` : ''}` : ''}>
                  {showValues && cell && <span className="text-sm font-semibold whitespace-nowrap" style={{ color: getTextColor(value) }}>{value.toFixed(1)}%{cell.count !== undefined ? ` · ${cell.count}` : ''}</span>}
                </div>);
              })}
            </div>
          ))}
        </div>
      </div>
      <div className="flex justify-between text-xs text-slate-500">{yLabel && <span>↑ {yLabel}</span>}{xLabel && <span>{xLabel} →</span>}</div>
    </div>
  );
}
