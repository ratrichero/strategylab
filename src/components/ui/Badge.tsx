import { cn } from "../../utils/cn";

interface BadgeProps {
  children: React.ReactNode;
  variant?: "default" | "success" | "warning" | "danger" | "info";
  size?: "sm" | "md";
  className?: string;
}

export function Badge({ children, variant = "default", size = "md", className }: BadgeProps) {
  const v: Record<string, string> = { default: "bg-slate-700 text-slate-300", success: "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30", warning: "bg-yellow-500/20 text-yellow-400 border border-yellow-500/30", danger: "bg-red-500/20 text-red-400 border border-red-500/30", info: "bg-blue-500/20 text-blue-400 border border-blue-500/30" };
  const s: Record<string, string> = { sm: "px-1.5 py-0.5 text-xs", md: "px-2 py-1 text-xs" };
  return <span className={cn("inline-flex items-center font-medium rounded-md", v[variant], s[size], className)}>{children}</span>;
}

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  const map: Record<string, { variant: BadgeProps["variant"]; label: string }> = {
    WIN: { variant: "success", label: "WIN" }, LOSS: { variant: "danger", label: "LOSS" }, MANUAL: { variant: "warning", label: "MANUAL" }, OPEN: { variant: "info", label: "OPEN" }, CLOSED: { variant: "default", label: "CLOSED" },
    WAIT: { variant: "warning", label: "WAIT" }, FILLED: { variant: "success", label: "FILLED" }, CANCELLED: { variant: "default", label: "CANCELLED" }, REJECTED: { variant: "danger", label: "REJECTED" },
    LONG: { variant: "success", label: "LONG" }, SHORT: { variant: "danger", label: "SHORT" },
    BULL: { variant: "success", label: "BULL" }, BEAR: { variant: "danger", label: "BEAR" }, SIDEWAYS: { variant: "warning", label: "SIDEWAYS" }, RANGING: { variant: "warning", label: "RANGING" }, VOLATILE: { variant: "info", label: "VOLATILE" },
  };
  const { variant, label } = map[status] || { variant: "default" as const, label: status };
  return <Badge variant={variant} className={className}>{label}</Badge>;
}

export function DirectionBadge({ direction, className }: { direction: string; className?: string }) {
  return <Badge variant={direction === "LONG" ? "success" : "danger"} className={cn("uppercase", className)}>{direction === "LONG" ? "▲" : "▼"} {direction}</Badge>;
}

export function ScoreBadge({ value, className }: { value: number; className?: string }) {
  const v = Number(value) || 0;
  return <span className={cn("font-mono text-sm", v >= 8 ? "text-emerald-400" : v >= 6 ? "text-yellow-400" : "text-red-400", className)}>{v.toFixed(2)}</span>;
}

export function PercentChangeBadge({ value, className }: { value: number; className?: string }) {
  const v = Number(value) || 0;
  const variant = v > 0 ? "success" : v < 0 ? "danger" : "default";
  return <Badge variant={variant} className={className}>{v > 0 ? "+" : ""}{v.toFixed(2)}%</Badge>;
}
