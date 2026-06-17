// @ts-nocheck
import { HashRouter, Routes, Route } from 'react-router-dom';
import { Toaster } from 'react-hot-toast';
import { Layout } from './components/layout/Layout';
import { Dashboard } from './pages/DashboardPage';
import { Research } from './pages/ResearchPage';
import { Signals } from './pages/SignalsPage';
import { EdgeDiscovery } from './pages/EdgeDiscoveryPage';
import { Indicators } from './pages/IndicatorsPage';
import { PendingSignalsPage as PendingSignals } from './pages/PendingSignalsPage';
import { QueryLab } from './pages/QueryLabPage';
import { SettingsPage } from './pages/SettingsPage';
import { MarketPage, EnginePage, BlockedPage, SimulationPage } from './pages/PlaceholderPages';

export default function App() {
  return (
    <HashRouter>
      <Toaster position="top-right" toastOptions={{ style: { background: '#1e293b', color: '#e2e8f0', border: '1px solid #334155' } }} />
      <Layout>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/research" element={<Research />} />
          <Route path="/market" element={<MarketPage />} />
          <Route path="/signals" element={<Signals />} />
          <Route path="/edge-discovery" element={<EdgeDiscovery />} />
          <Route path="/indicators" element={<Indicators />} />
          <Route path="/pending-signals" element={<PendingSignals />} />
          <Route path="/engine" element={<EnginePage />} />
          <Route path="/blocked" element={<BlockedPage />} />
          <Route path="/simulation" element={<SimulationPage />} />
          <Route path="/query-lab" element={<QueryLab />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </Layout>
    </HashRouter>
  );
}
