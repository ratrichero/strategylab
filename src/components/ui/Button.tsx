import { cn } from '../../utils/cn';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  size?: 'sm' | 'md' | 'lg';
  loading?: boolean;
  icon?: React.ReactNode;
}

export function Button({
  children,
  variant = 'primary',
  size = 'md',
  loading = false,
  icon,
  className,
  disabled,
  ...props
}: ButtonProps) {
  const variants = {
    primary: 'bg-indigo-600 hover:bg-indigo-700 text-white border-transparent',
    secondary: 'bg-slate-700 hover:bg-slate-600 text-white border-slate-600',
    ghost: 'bg-transparent hover:bg-slate-700/50 text-slate-300 border-transparent',
    danger: 'bg-red-600 hover:bg-red-700 text-white border-transparent',
  };

  const sizes = {
    sm: 'px-3 py-1.5 text-sm',
    md: 'px-4 py-2 text-sm',
    lg: 'px-6 py-3 text-base',
  };

  return (
    <button
      className={cn(
        'inline-flex items-center justify-center gap-2 font-medium rounded-lg border transition-colors',
        'disabled:opacity-50 disabled:cursor-not-allowed',
        variants[variant],
        sizes[size],
        className
      )}
      disabled={disabled || loading}
      {...props}
    >
      {loading ? (
        <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
          <circle
            className="opacity-25"
            cx="12"
            cy="12"
            r="10"
            stroke="currentColor"
            strokeWidth="4"
            fill="none"
          />
          <path
            className="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
          />
        </svg>
      ) : icon ? (
        icon
      ) : null}
      {children}
    </button>
  );
}

interface IconButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  icon: React.ReactNode;
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  size?: 'sm' | 'md' | 'lg';
}

export function IconButton({
  icon,
  variant = 'ghost',
  size = 'md',
  className,
  ...props
}: IconButtonProps) {
  const variants = {
    primary: 'bg-indigo-600 hover:bg-indigo-700 text-white',
    secondary: 'bg-slate-700 hover:bg-slate-600 text-white',
    ghost: 'bg-transparent hover:bg-slate-700/50 text-slate-400 hover:text-white',
    danger: 'bg-red-600 hover:bg-red-700 text-white',
  };

  const sizes = {
    sm: 'p-1.5',
    md: 'p-2',
    lg: 'p-3',
  };

  return (
    <button
      className={cn(
        'inline-flex items-center justify-center rounded-lg transition-colors',
        'disabled:opacity-50 disabled:cursor-not-allowed',
        variants[variant],
        sizes[size],
        className
      )}
      {...props}
    >
      {icon}
    </button>
  );
}
