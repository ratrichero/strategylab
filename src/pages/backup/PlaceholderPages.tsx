import { Card } from '../components/ui/Card';

function PlaceholderPage({ title, description }: { title: string; description: string }) {
  return (
    <div className="space-y-6">
      <div><h2 className="text-2xl font-bold text-white">{title}</h2><p className="text-slate-400 mt-1">{description}</p></div>
      <Card className="h-64 flex items-center justify-center"><p className="text-slate-500">Coming soon...</p></Card>
    </div>
  );
}

export function MarketPage() { return <PlaceholderPage title="Market Overview" description="Real-time market data and analysis" />; }
export function EnginePage() { return <PlaceholderPage title="Engine Status" description="Trading engine monitoring and control" />; }
export function BlockedPage() { return <PlaceholderPage title="Blocked Signals" description="Signals that were filtered out" />; }
export function SimulationPage() { return <PlaceholderPage title="Simulation" description="Monte Carlo and backtesting simulations" />; }
