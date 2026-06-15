import { cn } from '../../utils/cn';

interface CardProps {
  children: React.ReactNode;
  className?: string;
  padding?: 'none' | 'sm' | 'md' | 'lg';
  hover?: boolean;
}

export function Card({ children, className, padding = 'md', hover = false }: CardProps) {
  const paddingClasses = { none: '', sm: 'p-3', md: 'p-4', lg: 'p-6' };
  return (
    <div className={cn('bg-slate-800/50 backdrop-blur-sm border border-slate-700/50 rounded-xl', paddingClasses[padding], hover && 'hover:border-slate-600 transition-colors cursor-pointer', className)}>
      {children}
    </div>
  );
}

interface CardHeaderProps {
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
  className?: string;
}

export function CardHeader({ title, subtitle, action, className }: CardHeaderProps) {
  return (
    <div className={cn('flex items-center justify-between mb-4', className)}>
      <div>
        <h3 className="text-lg font-semibold text-white">{title}</h3>
        {subtitle && <p className="text-sm text-slate-400">{subtitle}</p>}
      </div>
      {action && <div>{action}</div>}
    </div>
  );
}

interface MetricCardProps {
  title: string;
  value: string | number;
  change?: number;
  changeLabel?: string;
  icon?: React.ReactNode;
  trend?: 'up' | 'down' | 'neutral';
  className?: string;
}

export function MetricCard({ title, value, change, changeLabel, icon, trend, className }: MetricCardProps) {
  const trendColors = { up: 'text-emerald-400', down: 'text-red-400', neutral: 'text-slate-400' };
  const getTrend = () => {
    if (trend) return trend;
    if (change === undefined) return 'neutral';
    return change > 0 ? 'up' : change < 0 ? 'down' : 'neutral';
  };
  return (
    <Card className={cn('relative overflow-hidden', className)}>
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm text-slate-400 mb-1">{title}</p>
          <p className="text-2xl font-bold text-white">{value}</p>
          {change !== undefined && (
            <div className={cn('flex items-center gap-1 mt-1 text-sm', trendColors[getTrend()])}>
              {getTrend() === 'up' && <span>↑</span>}
              {getTrend() === 'down' && <span>↓</span>}
              <span>{Math.abs(change).toFixed(2)}%</span>
              {changeLabel && <span className="text-slate-500">{changeLabel}</span>}
            </div>
          )}
        </div>
        {icon && <div className="p-2 bg-slate-700/50 rounded-lg text-slate-400">{icon}</div>}
      </div>
      <div className="absolute top-0 right-0 w-32 h-32 bg-gradient-to-br from-indigo-500/10 to-transparent rounded-full -translate-y-16 translate-x-16" />
    </Card>
  );
}
