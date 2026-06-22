// @ts-nocheck
import { useEffect, useState } from "react";
import { adminBots } from "../services/api";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Toggle } from "../components/ui/Toggle";
import toast from "react-hot-toast";
import {
  Loader2, Plus, RefreshCw, Shield, ShieldOff,
  Clock, Key, Database, Activity, ChevronDown,
  ChevronRight, Trash2, Copy, AlertTriangle,
} from "lucide-react";

export function BotManagementPage() {
  const [bots, setBots] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dashboard, setDashboard] = useState(null);
  const [showCreate, setShowCreate] = useState(false);
  const [expandedBot, setExpandedBot] = useState(null);
  const [creating, setCreating] = useState(false);
  const [newSecret, setNewSecret] = useState(null);

  // Create form
  const [form, setForm] = useState({
    name: "", slug: "", database_url: "",
    dashboard_username: "", dashboard_password: "",
    license_expires_at: "", description: "",
  });

  const loadData = async () => {
    setLoading(true);
    try {
      const [d, b] = await Promise.all([
        adminBots.dashboard(),
        adminBots.list(),
      ]);
      setDashboard(d);
      setBots(b);
    } catch (e) {
      toast.error(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadData(); }, []);

  const handleCreate = async () => {
    setCreating(true);
    try {
      const result = await adminBots.create(form);
      setNewSecret({ uuid: result.bot_uuid, secret: result.bot_secret });
      setShowCreate(false);
      setForm({ name: "", slug: "", database_url: "", dashboard_username: "", dashboard_password: "", license_expires_at: "", description: "" });
      toast.success("Bot created!");
      loadData();
    } catch (e) {
      toast.error(e.message);
    } finally {
      setCreating(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-96">
        <Loader2 className="w-8 h-8 animate-spin text-indigo-500" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-white flex items-center gap-3">
            🤖 Bot Management
          </h2>
          <p className="text-slate-400 mt-1">Manage bot instances, licenses, and credentials</p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" icon={<RefreshCw className="w-4 h-4" />} onClick={loadData}>Refresh</Button>
          <Button variant="primary" icon={<Plus className="w-4 h-4" />} onClick={() => setShowCreate(true)}>Create Bot</Button>
        </div>
      </div>

      {/* Dashboard Summary */}
      {dashboard && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          {[
            { label: "Total", value: dashboard.total_bots, color: "text-white" },
            { label: "Active", value: dashboard.active_bots, color: "text-emerald-400" },
            { label: "Disabled", value: dashboard.disabled_bots, color: "text-red-400" },
            { label: "Expired", value: dashboard.expired_bots, color: "text-yellow-400" },
            { label: "Online", value: dashboard.online_bots, color: "text-cyan-400" },
          ].map((s, i) => (
            <div key={i} className="p-4 bg-slate-900/50 rounded-xl border border-slate-700 text-center">
              <div className="text-xs text-slate-400">{s.label}</div>
              <div className={`text-2xl font-bold mt-1 ${s.color}`}>{s.value}</div>
            </div>
          ))}
        </div>
      )}

      {/* New Secret Display */}
      {newSecret && (
        <div className="p-4 bg-amber-500/10 border border-amber-500/30 rounded-xl">
          <div className="flex items-center gap-2 mb-3">
            <AlertTriangle className="w-5 h-5 text-amber-400" />
            <span className="text-amber-300 font-semibold">Save these credentials — shown only once!</span>
          </div>
          <div className="space-y-2 font-mono text-sm">
            <div className="flex items-center gap-2">
              <span className="text-slate-400">BOT_ID:</span>
              <span className="text-white">{newSecret.uuid}</span>
              <button onClick={() => { navigator.clipboard.writeText(newSecret.uuid); toast.success("Copied!"); }} className="text-slate-500 hover:text-white"><Copy className="w-3.5 h-3.5" /></button>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-slate-400">BOT_SECRET:</span>
              <span className="text-white">{newSecret.secret}</span>
              <button onClick={() => { navigator.clipboard.writeText(newSecret.secret); toast.success("Copied!"); }} className="text-slate-500 hover:text-white"><Copy className="w-3.5 h-3.5" /></button>
            </div>
          </div>
          <button onClick={() => setNewSecret(null)} className="mt-3 text-xs text-slate-500 hover:text-slate-300">Dismiss</button>
        </div>
      )}

      {/* Create Bot Modal */}
      {showCreate && (
        <Card>
          <h3 className="text-lg font-semibold text-white mb-4">Create New Bot</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {[
              { label: "Bot Name", key: "name", placeholder: "Bot Alpha" },
              { label: "Slug", key: "slug", placeholder: "bot-alpha" },
              { label: "Database URL", key: "database_url", placeholder: "postgresql://...", colSpan: true },
              { label: "Dashboard Username", key: "dashboard_username", placeholder: "bot_user" },
              { label: "Dashboard Password", key: "dashboard_password", placeholder: "••••••", type: "password" },
              { label: "License Expires At", key: "license_expires_at", placeholder: "2026-01-01T00:00:00", type: "datetime-local" },
              { label: "Description", key: "description", placeholder: "Optional description" },
            ].map((f) => (
              <div key={f.key} className={f.colSpan ? "md:col-span-2" : ""}>
                <label className="block text-sm text-slate-300 mb-1">{f.label}</label>
                <input
                  type={f.type || "text"}
                  value={form[f.key]}
                  onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
                  placeholder={f.placeholder}
                  className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-white text-sm font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>
            ))}
          </div>
          <div className="flex gap-2 mt-4">
            <Button variant="primary" loading={creating} onClick={handleCreate}>Create Bot</Button>
            <Button variant="ghost" onClick={() => setShowCreate(false)}>Cancel</Button>
          </div>
        </Card>
      )}

      {/* Bot List */}
      <div className="space-y-3">
        {bots.map((bot) => {
          const isExpanded = expandedBot === bot.id;
          const statusColors = {
            active: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
            disabled: "bg-red-500/20 text-red-400 border-red-500/30",
            expired: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
          };

          return (
            <div key={bot.id} className="bg-slate-900/50 border border-slate-700 rounded-xl overflow-hidden">
              {/* Header */}
              <div
                className="flex items-center justify-between p-4 cursor-pointer hover:bg-slate-800/30 transition"
                onClick={() => setExpandedBot(isExpanded ? null : bot.id)}
              >
                <div className="flex items-center gap-4">
                  {isExpanded ? <ChevronDown className="w-4 h-4 text-slate-400" /> : <ChevronRight className="w-4 h-4 text-slate-400" />}
                  <div className={`w-2.5 h-2.5 rounded-full ${bot.is_online ? "bg-emerald-400 animate-pulse" : "bg-slate-600"}`} />
                  <div>
                    <div className="text-white font-medium">{bot.name}</div>
                    <div className="text-xs text-slate-500 font-mono">{bot.slug}</div>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <span className={`text-xs px-2 py-1 rounded-full border ${statusColors[bot.status] || "bg-slate-700 text-slate-400"}`}>
                    {bot.status}
                  </span>
                  {bot.license_expires_at && (
                    <span className="text-xs text-slate-500">
                      <Clock className="w-3 h-3 inline mr-1" />
                      {new Date(bot.license_expires_at).toLocaleDateString()}
                    </span>
                  )}
                  {bot.last_seen_version && (
                    <span className="text-xs text-slate-600">v{bot.last_seen_version}</span>
                  )}
                </div>
              </div>

              {/* Expanded Detail */}
              {isExpanded && (
                <div className="border-t border-slate-700 p-4 space-y-4">
                  {/* Actions */}
                  <div className="flex flex-wrap gap-2">
                    {bot.status === "active" ? (
                      <Button variant="secondary" size="sm" icon={<ShieldOff className="w-3.5 h-3.5" />}
                        onClick={async (e) => { e.stopPropagation(); await adminBots.disable(bot.id); loadData(); toast.success("Bot disabled"); }}>
                        Disable
                      </Button>
                    ) : (
                      <Button variant="secondary" size="sm" icon={<Shield className="w-3.5 h-3.5" />}
                        onClick={async (e) => { e.stopPropagation(); await adminBots.activate(bot.id); loadData(); toast.success("Bot activated"); }}>
                        Activate
                      </Button>
                    )}
                    <Button variant="secondary" size="sm" icon={<Clock className="w-3.5 h-3.5" />}
                      onClick={async (e) => {
                        e.stopPropagation();
                        const d = prompt("New expiry (ISO format):", "2026-12-31T23:59:59");
                        if (d) { await adminBots.extendLicense(bot.id, d); loadData(); toast.success("License extended"); }
                      }}>
                      Extend License
                    </Button>
                    <Button variant="secondary" size="sm" icon={<Database className="w-3.5 h-3.5" />}
                      onClick={async (e) => {
                        e.stopPropagation();
                        const url = prompt("New Database URL:");
                        if (url) { await adminBots.overrideDbUrl(bot.id, url); loadData(); toast.success("DB URL updated (next restart)"); }
                      }}>
                      Override DB URL
                    </Button>
                    <Button variant="secondary" size="sm" icon={<Key className="w-3.5 h-3.5" />}
                      onClick={async (e) => {
                        e.stopPropagation();
                        if (!confirm("Rotate secret? Old secret will be invalidated.")) return;
                        const r = await adminBots.rotateSecret(bot.id);
                        setNewSecret({ uuid: bot.bot_uuid, secret: r.new_bot_secret });
                        toast.success("Secret rotated");
                      }}>
                      Rotate Secret
                    </Button>
                    <Button variant="danger" size="sm" icon={<Trash2 className="w-3.5 h-3.5" />}
                      onClick={async (e) => {
                        e.stopPropagation();
                        if (!confirm(`Delete bot "${bot.name}" from registry? Database will NOT be deleted.`)) return;
                        await adminBots.delete(bot.id);
                        loadData();
                        toast.success("Bot removed");
                      }}>
                      Remove
                    </Button>
                  </div>

                  {/* Info Grid */}
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                    {[
                      { label: "Bot UUID", value: bot.bot_uuid },
                      { label: "Dashboard User", value: bot.dashboard_username },
                      { label: "Last Heartbeat", value: bot.last_heartbeat_at ? new Date(bot.last_heartbeat_at).toLocaleString() : "Never" },
                      { label: "Created", value: new Date(bot.created_at).toLocaleDateString() },
                    ].map((info, i) => (
                      <div key={i} className="bg-slate-800/50 rounded-lg p-3">
                        <div className="text-xs text-slate-500">{info.label}</div>
                        <div className="text-slate-300 mt-0.5 font-mono text-xs truncate">{info.value}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          );
        })}

        {bots.length === 0 && (
          <div className="text-center py-12 text-slate-500">
            No bots yet. Click "Create Bot" to get started.
          </div>
        )}
      </div>
    </div>
  );
}