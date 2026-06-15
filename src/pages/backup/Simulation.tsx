import { Card, CardHeader } from "../components/ui/Card";
import { Play } from "lucide-react";

export function Simulation() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-white">Simulation Studio</h2>
        <p className="text-slate-400 mt-1">Coming soon — will be finalized after strategy requirements are confirmed</p>
      </div>
      <Card className="h-96 flex items-center justify-center">
        <div className="text-center">
          <div className="w-16 h-16 bg-indigo-500/20 rounded-full flex items-center justify-center mx-auto mb-4">
            <Play className="w-8 h-8 text-indigo-400" />
          </div>
          <h3 className="text-lg font-medium text-white mb-2">Simulation Studio</h3>
          <p className="text-slate-400 max-w-sm">
            This page is pending final requirements. The backend simulation endpoint 
            (<code className="text-indigo-400">/api/simulation/run</code>) is ready.
          </p>
        </div>
      </Card>
    </div>
  );
}
