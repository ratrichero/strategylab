// @ts-nocheck
import { Card } from "../components/ui/Card";

export function QueryLab() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-white">Query Lab</h2>
        <p className="text-slate-400 mt-1">SQL editor + sample queries</p>
      </div>
      <Card className="flex items-center justify-center h-96">
        <div className="text-center">
          <p className="text-slate-500 text-lg mb-2">💻 Query Lab</p>
          <p className="text-slate-600 text-sm">Send actual code to replace this placeholder</p>
        </div>
      </Card>
    </div>
  );
}
