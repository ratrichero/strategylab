// @ts-nocheck
import { useEffect, useState } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { Toaster } from 'react-hot-toast';
import { useIsMobile } from './hooks/useIsMobile';
import { Layout } from './components/layout/Layout';
import { MobileLayout } from './components/layout/MobileLayout';
import { Dashboard } from './pages/DashboardPage';
import { Research } from './pages/ResearchPage';
import { Signals } from './pages/SignalsPage';
import { EdgeDiscovery } from './pages/EdgeDiscoveryPage';
import { Indicators } from './pages/IndicatorsPage';
import { PendingSignalsPage as PendingSignals } from './pages/PendingSignalsPage';
import { AccountPage } from './pages/AccountPage';
import { ManualBehaviorPage } from './pages/ManualBehaviorPage';
import { ScanTestPage } from './pages/ScanTestPage';
import { QueryLab } from './pages/QueryLabPage';
import { SettingsPage } from './pages/SettingsPage';
import { MarketPage, EnginePage, BlockedPage } from './pages/PlaceholderPages';
import { SimulationPage } from './pages/SimulationPage';
// ← CHANGED: thêm auth pages
import { LoginPage } from './pages/LoginPage';
import { BotManagementPage } from './pages/BotManagementPage';
import { auth, appRoleApi } from './services/api';
import { useAppStore } from './store/appStore';
import { Loader2 } from 'lucide-react';

// ← CHANGED: Auth guard component
function AuthGuard({ children }: { children: React.ReactNode }) {
  const { currentUser, setCurrentUser, setAppRole, setLicenseInfo } = useAppStore();
  const [checking, setChecking] = useState(true);
  const location = useLocation();

  useEffect(() => {
    (async () => {
      try {
        const me = await auth.me();
        if (me?.user) {
          setCurrentUser(me.user);
          if (me.app_role) setAppRole(me.app_role);

          // Load license info nếu là BOT
          if (me.app_role === "BOT") {
            try {
              const li = await appRoleApi.botLicenseInfo();
              if (li?.license) setLicenseInfo(li.license);
            } catch {}
          }
        }
      } catch {}
      setChecking(false);
    })();
  }, []);

  if (checking) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-950">
        <div className="text-center">
          <Loader2 className="w-8 h-8 animate-spin text-indigo-500 mx-auto mb-4" />
          <p className="text-slate-400">Verifying session...</p>
        </div>
      </div>
    );
  }

  if (!currentUser) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return <>{children}</>;
}

// ← CHANGED: Monitor-only banner
function MonitorBanner() {
  const { appRole, licenseInfo } = useAppStore();
  if (appRole !== "BOT" || !licenseInfo?.monitor_only) return null;

  return (
    <div className="flex items-center gap-2 px-4 py-2 bg-amber-500/10 border-b border-amber-500/30 text-amber-400 text-sm">
      <span>⚠️ Bot is in <strong>monitor-only</strong> mode — no new trades will be opened</span>
    </div>
  );
}

function AdminGuard({ children }: { children: React.ReactNode }) {
  const { currentUser, appRole } = useAppStore();
  if (appRole !== "ADMIN" || currentUser?.role !== "ADMIN") {
    return <Navigate to="/" replace />;
  }
  return <>{children}</>;
}

export default function App() {
  const isMobile = useIsMobile();
  const LayoutWrapper = isMobile ? MobileLayout : Layout;

  return (
    <BrowserRouter>
      <Toaster position="top-right" toastOptions={{ style: { background: '#1e293b', color: '#e2e8f0', border: '1px solid #334155' } }} />
      <Routes>
        {/* ← CHANGED: Login route — không cần auth */}
        <Route path="/login" element={<LoginPage />} />

        {/* ← CHANGED: Protected routes — cần auth */}
        <Route path="/*" element={
          <AuthGuard>
            <MonitorBanner />
            <LayoutWrapper>
              <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/dashboard" element={<Dashboard />} />
                <Route path="/research" element={<Research />} />
                <Route path="/market" element={<MarketPage />} />
                <Route path="/signals" element={<Signals />} />
                <Route path="/edge-discovery" element={<EdgeDiscovery />} />
                <Route path="/indicators" element={<Indicators />} />
                <Route path="/pending-signals" element={<PendingSignals />} />
                <Route path="/account" element={<AccountPage />} />
                <Route path="/manual-behavior" element={<ManualBehaviorPage />} />
                <Route path="/engine" element={<EnginePage />} />
                <Route path="/blocked" element={<BlockedPage />} />
                <Route path="/scan-test" element={<ScanTestPage />} />
                <Route path="/simulation" element={<SimulationPage />} />
                <Route path="/query-lab" element={<QueryLab />} />
                <Route path="/settings" element={<SettingsPage />} />
                {/* ← CHANGED: Bot Management — chỉ admin thấy trong nav nhưng route vẫn có */}
                <Route path="/admin/bots" element={<AdminGuard><BotManagementPage /></AdminGuard>} />
              </Routes>
            </LayoutWrapper>
          </AuthGuard>
        } />
      </Routes>
    </BrowserRouter>
  );
}
