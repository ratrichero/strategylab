import { cn } from "../../utils/cn";

interface ToggleProps { checked: boolean; onChange: (v: boolean) => void; size?: "sm" | "md"; disabled?: boolean; label?: string; description?: string; }

export function Toggle({ checked, onChange, size = "md", disabled = false, label, description }: ToggleProps) {
  const track = size === "sm" ? "w-10 h-5" : "w-14 h-7";
  const thumb = size === "sm" ? "w-3.5 h-3.5 top-0.75 left-0.5" : "w-5 h-5 top-1 left-1";
  const xl = size === "sm" ? (checked ? "translate-x-5" : "translate-x-0") : (checked ? "translate-x-8" : "translate-x-0");
  const btn = (
    <button type="button" role="switch" aria-checked={checked} disabled={disabled} onClick={() => !disabled && onChange(!checked)}
      className={cn("relative rounded-full transition-colors disabled:opacity-50", track, checked ? "bg-indigo-600" : "bg-slate-700")}>
      <span className={cn("absolute bg-white rounded-full shadow transition-transform", thumb, xl)} />
    </button>
  );
  if (!label) return btn;
  return (
    <label className={cn("flex items-center gap-3 cursor-pointer", disabled && "opacity-50 cursor-not-allowed")}>
      {btn}
      <div><div className="text-sm font-medium text-slate-300">{label}</div>{description && <div className="text-xs text-slate-500 mt-0.5">{description}</div>}</div>
    </label>
  );
}
