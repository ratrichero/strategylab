import { cn } from '../../utils/cn';
import { ChevronDown } from 'lucide-react';

interface SelectOption { value: string; label: string; }

interface SelectProps {
  options: SelectOption[];
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  label?: string;
  className?: string;
  size?: 'sm' | 'md' | 'lg';
}

export function Select({ options, value, onChange, placeholder = 'Select...', label, className, size = 'md' }: SelectProps) {
  const sizes: Record<string, string> = { sm: 'px-2 py-1.5 text-sm', md: 'px-3 py-2 text-sm', lg: 'px-4 py-2.5 text-base' };
  return (
    <div className={cn('relative', className)}>
      {label && <label className="block text-sm font-medium text-slate-400 mb-1.5">{label}</label>}
      <div className="relative">
        <select value={value} onChange={(e) => onChange(e.target.value)} className={cn('w-full bg-slate-800 border border-slate-600 rounded-lg text-white appearance-none cursor-pointer pr-10 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent', sizes[size])}>
          {placeholder && <option value="" disabled>{placeholder}</option>}
          {options.map((opt) => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
        </select>
        <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 pointer-events-none" />
      </div>
    </div>
  );
}

export function MultiSelect({ options, values, onChange, placeholder = 'Select...', label, className }: { options: SelectOption[]; values: string[]; onChange: (values: string[]) => void; placeholder?: string; label?: string; className?: string }) {
  const toggleValue = (value: string) => { if (values.includes(value)) onChange(values.filter((v) => v !== value)); else onChange([...values, value]); };
  return (
    <div className={cn('space-y-2', className)}>
      {label && <label className="block text-sm font-medium text-slate-400">{label}</label>}
      <div className="flex flex-wrap gap-2">
        {options.map((opt) => <button key={opt.value} onClick={() => toggleValue(opt.value)} className={cn('px-3 py-1.5 rounded-lg text-sm font-medium transition-colors', values.includes(opt.value) ? 'bg-indigo-600 text-white' : 'bg-slate-700 text-slate-300 hover:bg-slate-600')}>{opt.label}</button>)}
      </div>
      {values.length === 0 && <p className="text-sm text-slate-500">{placeholder}</p>}
    </div>
  );
}
