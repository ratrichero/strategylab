// @ts-nocheck
import { useState } from 'react';
import { Card } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Input } from '../components/ui/Input';
import { Zap, ExternalLink, Maximize2, Minimize2, Settings2 } from 'lucide-react';

const DEFAULT_URL = '/scanner/index.html';

export function ScanTestPage() {
  const [scannerUrl, setScannerUrl] = useState(() => {
    try { return localStorage.getItem('scan-test-url') || DEFAULT_URL; } catch { return DEFAULT_URL; }
  });
  const [inputUrl, setInputUrl] = useState(scannerUrl);
  const [fullscreen, setFullscreen] = useState(false);
  const [showConfig, setShowConfig] = useState(false);

  const applyUrl = () => {
    setScannerUrl(inputUrl);
    try { localStorage.setItem('scan-test-url', inputUrl); } catch {}
  };

  if (fullscreen) {
    return (
      <div className="fixed inset-0 z-50 bg-gray-950">
        <div className="absolute top-2 right-2 z-10 flex gap-2">
          <button onClick={() => setFullscreen(false)} className="p-2 bg-slate-800/80 hover:bg-slate-700 rounded-lg text-slate-400 hover:text-white transition-colors backdrop-blur-sm" title="Exit fullscreen">
            <Minimize2 className="w-5 h-5" />
          </button>
          <a href={scannerUrl} target="_blank" rel="noopener noreferrer" className="p-2 bg-slate-800/80 hover:bg-slate-700 rounded-lg text-slate-400 hover:text-white transition-colors backdrop-blur-sm" title="Open in new tab">
            <ExternalLink className="w-5 h-5" />
          </a>
        </div>
        <iframe src={scannerUrl} className="w-full h-full border-0" title="Binance Futures Signal Scanner" allow="clipboard-read; clipboard-write" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Zap className="w-7 h-7 text-yellow-400" />
          <div>
            <h2 className="text-2xl font-bold text-white">Scan Test</h2>
            <p className="text-slate-400 mt-0.5">Binance Futures Signal Scanner</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => setShowConfig(!showConfig)} className="p-2 rounded-lg hover:bg-slate-700/50 text-slate-400 hover:text-white transition-colors" title="Configure URL">
            <Settings2 className="w-5 h-5" />
          </button>
          <button onClick={() => setFullscreen(true)} className="p-2 rounded-lg hover:bg-slate-700/50 text-slate-400 hover:text-white transition-colors" title="Fullscreen">
            <Maximize2 className="w-5 h-5" />
          </button>
          <a href={scannerUrl} target="_blank" rel="noopener noreferrer" className="p-2 rounded-lg hover:bg-slate-700/50 text-slate-400 hover:text-white transition-colors" title="Open in new tab">
            <ExternalLink className="w-5 h-5" />
          </a>
        </div>
      </div>

      {/* Config panel */}
      {showConfig && (
        <Card>
          <div className="flex items-center gap-3">
            <Input type="text" label="Scanner URL" value={inputUrl} onChange={e => setInputUrl(e.target.value)} placeholder="http://localhost:5174 or /scanner/" className="flex-1" />
            <div className="flex items-end"><Button variant="primary" onClick={applyUrl}>Apply</Button></div>
          </div>
          <p className="text-xs text-slate-500 mt-2">
            Nhập URL của ứng dụng Scanner. Có thể là path tương đối (vd: <code>/scanner/</code>) nếu deploy cùng server, hoặc URL đầy đủ (vd: <code>http://localhost:5174</code>) nếu chạy riêng.
          </p>
        </Card>
      )}

      {/* Embedded Scanner */}
      <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 overflow-hidden" style={{ height: 'calc(100vh - 180px)' }}>
        <iframe
          src={scannerUrl}
          className="w-full h-full border-0"
          title="Binance Futures Signal Scanner"
          allow="clipboard-read; clipboard-write"
        />
      </div>
    </div>
  );
}
