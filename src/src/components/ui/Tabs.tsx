import { cn } from '../../utils/cn';

interface Tab { id: string; label: string; icon?: React.ReactNode; badge?: number; }

interface TabsProps { tabs: Tab[]; activeTab: string; onChange: (tabId: string) => void; variant?: 'default' | 'pills' | 'underline'; className?: string; }

export function Tabs({ tabs, activeTab, onChange, variant = 'default', className }: TabsProps) {
  const variants: Record<string, any> = {
    default: { container: 'bg-slate-800/50 p-1 rounded-lg', tab: 'px-4 py-2 rounded-md text-sm font-medium transition-colors', active: 'bg-slate-700 text-white shadow', inactive: 'text-slate-400 hover:text-white hover:bg-slate-700/50' },
    pills: { container: 'flex gap-2', tab: 'px-4 py-2 rounded-full text-sm font-medium transition-colors', active: 'bg-indigo-600 text-white', inactive: 'bg-slate-800 text-slate-400 hover:bg-slate-700 hover:text-white' },
    underline: { container: 'border-b border-slate-700', tab: 'px-4 py-3 text-sm font-medium transition-colors relative', active: 'text-indigo-400 after:absolute after:bottom-0 after:left-0 after:right-0 after:h-0.5 after:bg-indigo-400', inactive: 'text-slate-400 hover:text-white' },
  };
  const style = variants[variant];
  return (
    <div className={cn('flex', style.container, className)}>
      {tabs.map((tab) => (
        <button key={tab.id} onClick={() => onChange(tab.id)} className={cn(style.tab, activeTab === tab.id ? style.active : style.inactive, 'flex items-center gap-2')}>
          {tab.icon}<span>{tab.label}</span>
          {tab.badge !== undefined && tab.badge > 0 && <span className="px-1.5 py-0.5 text-xs bg-indigo-500 text-white rounded-full">{tab.badge}</span>}
        </button>
      ))}
    </div>
  );
}

export function TabContent({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn('mt-4', className)}>{children}</div>;
}
