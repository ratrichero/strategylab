import { BrowserRouter as Router, Routes, Route } from "react-router-dom";
import { Toaster } from "react-hot-toast";
import { Layout } from "./components/layout/Layout";
import { Dashboard } from "./pages/Dashboard";
import { Research } from "./pages/Research";
import { Market } from "./pages/Market";
import { Signals } from "./pages/Signals";
import { EdgeDiscovery } from "./pages/EdgeDiscovery";
import { Indicators } from "./pages/Indicators";
import { Engine } from "./pages/Engine";
import { Blocked } from "./pages/Blocked";
import { Simulation } from "./pages/Simulation";
import { QueryLab } from "./pages/QueryLab";
import { SettingsPage } from "./pages/Settings";

function App() {
  return (
    <Router>
      <Toaster position="top-right" toastOptions={{
        duration: 4000,
        style: { background: "#1e293b", color: "#f1f5f9", border: "1px solid #334155" },
        success: { iconTheme: { primary: "#10b981", secondary: "#f1f5f9" } },
        error:   { iconTheme: { primary: "#ef4444", secondary: "#f1f5f9" } },
      }} />
      <Layout>
        <Routes>
          <Route path="/"               element={<Dashboard />} />
          <Route path="/research"       element={<Research />} />
          <Route path="/market"         element={<Market />} />
          <Route path="/signals"        element={<Signals />} />
          <Route path="/edge-discovery" element={<EdgeDiscovery />} />
          <Route path="/indicators"     element={<Indicators />} />
          <Route path="/engine"         element={<Engine />} />
          <Route path="/blocked"        element={<Blocked />} />
          <Route path="/simulation"     element={<Simulation />} />
          <Route path="/query-lab"      element={<QueryLab />} />
          <Route path="/settings"       element={<SettingsPage />} />
        </Routes>
      </Layout>
    </Router>
  );
}

export default App;
