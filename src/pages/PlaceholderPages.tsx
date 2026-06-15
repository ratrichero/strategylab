// Placeholder pages — send actual code to replace
import { Card } from "../components/ui/Card";

function PlaceholderPage({ title, description }: { title: string; description: string }) {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-white">{title}</h2>
        <p className="text-slate-400 mt-1">{description}</p>
      </div>
      <Card className="flex items-center justify-center h-96">
        <div className="text-center">
          <p className="text-slate-500 text-lg mb-2">🚧 Coming Soon</p>
          <p className="text-slate-600 text-sm">Send actual code to replace this placeholder</p>
        </div>
      </Card>
    </div>
  );
}

export function MarketPage() {
  return <PlaceholderPage title="Market" description="Per-symbol analysis" />;
}

export function EnginePage() {
  return <PlaceholderPage title="Engine" description="Version comparison" />;
}

export function BlockedPage() {
  return <PlaceholderPage title="Blocked" description="Real API, filter by reason" />;
}

export function SimulationPage() {
  return <PlaceholderPage title="Simulation" description="Backtesting and simulation" />;
}
