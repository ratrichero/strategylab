import { cn } from '../../utils/cn';
import { Search } from 'lucide-react';

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  icon?: React.ReactNode;
}

export function Input({ label, error, icon, className, ...props }: InputProps) {
  return (
    <div className={cn('space-y-1.5', className)}>
      {label && <label className="block text-sm font-medium text-slate-400">{label}</label>}
      <div className="relative">
        {icon && <div className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400">{icon}</div>}
        <input className={cn('w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-white text-sm placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent disabled:opacity-50 disabled:cursor-not-allowed', icon && 'pl-10', error && 'border-red-500 focus:ring-red-500')} {...props} />
      </div>
      {error && <p className="text-sm text-red-400">{error}</p>}
    </div>
  );
}

export function SearchInput({ value, onChange, placeholder = 'Search...', className }: { value: string; onChange: (value: string) => void; placeholder?: string; className?: string }) {
  return <Input type="text" value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} icon={<Search className="w-4 h-4" />} className={className} />;
}

export function NumberInput({ value, onChange, min, max, step = 1, label, className }: { value: number; onChange: (value: number) => void; min?: number; max?: number; step?: number; label?: string; className?: string }) {
  return (
    <div className={cn('space-y-1.5', className)}>
      {label && <label className="block text-sm font-medium text-slate-400">{label}</label>}
      <input type="number" value={value} onChange={(e) => onChange(parseFloat(e.target.value) || 0)} min={min} max={max} step={step} className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent" />
    </div>
  );
}

export function RangeInput({ min, max, value, onChange, label, className }: { min: number; max: number; value: [number, number]; onChange: (value: [number, number]) => void; label?: string; className?: string }) {
  return (
    <div className={cn('space-y-2', className)}>
      {label && <label className="block text-sm font-medium text-slate-400">{label}</label>}
      <div className="flex items-center gap-2">
        <input type="number" value={value[0]} onChange={(e) => onChange([parseFloat(e.target.value) || min, value[1]])} min={min} max={value[1]} className="w-24 bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500" />
        <span className="text-slate-400">to</span>
        <input type="number" value={value[1]} onChange={(e) => onChange([value[0], parseFloat(e.target.value) || max])} min={value[0]} max={max} className="w-24 bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500" />
      </div>
    </div>
  );
}
