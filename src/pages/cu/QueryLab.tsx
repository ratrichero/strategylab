import { useState, useMemo } from 'react';
import { Card } from '../components/ui/Card';
import { Button, IconButton } from '../components/ui/Button';
import { SearchInput, Input } from '../components/ui/Input';
import { Select } from '../components/ui/Select';
import { Tabs, TabContent } from '../components/ui/Tabs';
import { DataTable } from '../components/ui/Table';
import { BarChart } from '../components/charts/BarChart';
import { useAppStore } from '../store/appStore';
import { executeQuery, fetchSchema } from '../services/dataService';
import type { ResearchQuery } from '../types/database';
import {
  Play,
  Save,
  FolderOpen,
  FileCode,
  Pin,
  Trash2,
  Copy,
  ChevronRight,
  ChevronDown,
  Plus,
  Database,
  Table,
  Hash,
  Type,
  Calendar,
  Clock,
  AlertCircle,
  CheckCircle,
} from 'lucide-react';

const FOLDER_STRUCTURE = [
  { path: '/signals', name: 'Signals', icon: '📊' },
  { path: '/signals/performance', name: 'Performance', icon: '📈' },
  { path: '/engine', name: 'Engine', icon: '⚙️' },
  { path: '/engine/comparison', name: 'Comparison', icon: '🔄' },
  { path: '/indicator', name: 'Indicators', icon: '📉' },
  { path: '/indicator/edge', name: 'Edge Discovery', icon: '🎯' },
  { path: '/blocked', name: 'Blocked', icon: '🚫' },
  { path: '/blocked/analysis', name: 'Analysis', icon: '🔍' },
  { path: '/experimental', name: 'Experimental', icon: '🧪' },
  { path: '/custom', name: 'Custom', icon: '📁' },
];

export function QueryLab() {
  const { researchQueries, addResearchQuery, updateResearchQuery, deleteResearchQuery, toggleQueryPin } = useAppStore();
  
  const [selectedQuery, setSelectedQuery] = useState<ResearchQuery | null>(null);
  const [sqlText, setSqlText] = useState('SELECT * FROM signals ORDER BY candle_time DESC LIMIT 20;');
  const [queryName, setQueryName] = useState('');
  const [queryFolder, setQueryFolder] = useState('/custom');
  const [searchTerm, setSearchTerm] = useState('');
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set(['/signals', '/engine']));
  const [resultTab, setResultTab] = useState('table');
  const [isExecuting, setIsExecuting] = useState(false);
  const [results, setResults] = useState<any[] | null>(null);
  const [executionTime, setExecutionTime] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showSchema, setShowSchema] = useState(false);
  const [schema, setSchema] = useState<Record<string, any>>({});

  const filteredQueries = useMemo(() => {
    if (!searchTerm) return researchQueries;
    return researchQueries.filter(q => 
      q.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      q.sql_text.toLowerCase().includes(searchTerm.toLowerCase())
    );
  }, [researchQueries, searchTerm]);

  const queriesByFolder = useMemo(() => {
    const grouped: Record<string, ResearchQuery[]> = {};
    FOLDER_STRUCTURE.forEach(f => { grouped[f.path] = []; });
    
    filteredQueries.forEach(q => {
      if (grouped[q.folder_path]) {
        grouped[q.folder_path].push(q);
      } else {
        grouped['/custom'].push(q);
      }
    });
    
    return grouped;
  }, [filteredQueries]);

  const toggleFolder = (path: string) => {
    const newExpanded = new Set(expandedFolders);
    if (newExpanded.has(path)) {
      newExpanded.delete(path);
    } else {
      newExpanded.add(path);
    }
    setExpandedFolders(newExpanded);
  };

  const selectQuery = (query: ResearchQuery) => {
    setSelectedQuery(query);
    setSqlText(query.sql_text);
    setQueryName(query.name);
    setQueryFolder(query.folder_path);
    setResults(null);
    setError(null);
  };

  const runQuery = async () => {
    setIsExecuting(true);
    setError(null);
    setResults(null);
    
    const startTime = Date.now();
    
    try {
      const result = await executeQuery(sqlText);
      setResults(result.data);
      setExecutionTime(Date.now() - startTime);
      
      // Update last used
      if (selectedQuery) {
        updateResearchQuery(selectedQuery.id, { last_used_at: new Date().toISOString() });
      }
    } catch (err: any) {
      setError(err.message || 'Query execution failed. Please check your SQL syntax.');
      setExecutionTime(Date.now() - startTime);
    } finally {
      setIsExecuting(false);
    }
  };

  const loadSchema = async () => {
    const schemaData = await fetchSchema();
    setSchema(schemaData);
    setShowSchema(true);
  };

  const saveQuery = () => {
    if (!queryName.trim()) {
      alert('Please enter a query name');
      return;
    }

    if (selectedQuery) {
      updateResearchQuery(selectedQuery.id, {
        name: queryName,
        sql_text: sqlText,
        folder_path: queryFolder,
      });
    } else {
      const newQuery: ResearchQuery = {
        id: Date.now().toString(),
        name: queryName,
        folder_path: queryFolder,
        description: '',
        sql_text: sqlText,
        parameters: {},
        chart_config: null,
        created_at: new Date().toISOString(),
        last_used_at: new Date().toISOString(),
        is_pinned: false,
      };
      addResearchQuery(newQuery);
      setSelectedQuery(newQuery);
    }
  };

  const createNewQuery = () => {
    setSelectedQuery(null);
    setSqlText('SELECT * FROM signals ORDER BY candle_time DESC LIMIT 10;');
    setQueryName('New Query');
    setQueryFolder('/custom');
    setResults(null);
    setError(null);
  };

  const resultColumns = results && results.length > 0
    ? Object.keys(results[0]).map(key => ({
        key,
        header: key,
        sortable: true,
        render: (v: any) => {
          if (v === null) return <span className="text-slate-500">NULL</span>;
          if (typeof v === 'number') return Number.isInteger(v) ? v : v.toFixed(4);
          if (typeof v === 'boolean') return v ? 'true' : 'false';
          if (typeof v === 'object') return <span className="text-xs">{JSON.stringify(v).slice(0, 50)}...</span>;
          return String(v).slice(0, 100);
        },
      }))
    : [];

  const chartData = results && results.length > 0 ? results.slice(0, 20) : [];

  const resultTabs = [
    { id: 'table', label: 'Table' },
    { id: 'chart', label: 'Chart' },
    { id: 'json', label: 'JSON' },
    { id: 'sql', label: 'Raw SQL' },
  ];

  return (
    <div className="h-[calc(100vh-8rem)] flex gap-6">
      {/* Left Panel - Query Library */}
      <div className="w-72 flex-shrink-0 flex flex-col">
        <Card className="flex-1 flex flex-col overflow-hidden">
          <div className="p-4 border-b border-slate-700">
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-semibold text-white">Query Library</h3>
              <IconButton
                icon={<Plus className="w-4 h-4" />}
                onClick={createNewQuery}
                size="sm"
              />
            </div>
            <SearchInput
              value={searchTerm}
              onChange={setSearchTerm}
              placeholder="Search queries..."
            />
          </div>

          <div className="flex-1 overflow-y-auto p-2">
            {/* Pinned Queries */}
            {filteredQueries.filter(q => q.is_pinned).length > 0 && (
              <div className="mb-4">
                <p className="text-xs font-medium text-slate-500 px-2 py-1">PINNED</p>
                {filteredQueries.filter(q => q.is_pinned).map(query => (
                  <button
                    key={query.id}
                    onClick={() => selectQuery(query)}
                    className={`w-full text-left px-3 py-2 rounded-lg text-sm transition-colors flex items-center gap-2 ${
                      selectedQuery?.id === query.id
                        ? 'bg-indigo-600/20 text-indigo-400'
                        : 'text-slate-400 hover:bg-slate-700/50'
                    }`}
                  >
                    <Pin className="w-3 h-3 text-yellow-400" />
                    <span className="truncate">{query.name}</span>
                  </button>
                ))}
              </div>
            )}

            {/* Folder Structure */}
            {FOLDER_STRUCTURE.filter(f => !f.path.includes('/', 1)).map(folder => {
              const isExpanded = expandedFolders.has(folder.path);
              const children = FOLDER_STRUCTURE.filter(f => 
                f.path.startsWith(folder.path + '/') && 
                f.path.split('/').length === folder.path.split('/').length + 1
              );
              const queries = queriesByFolder[folder.path] || [];

              return (
                <div key={folder.path} className="mb-1">
                  <button
                    onClick={() => toggleFolder(folder.path)}
                    className="w-full flex items-center gap-2 px-2 py-1.5 rounded text-sm text-slate-400 hover:bg-slate-700/50"
                  >
                    {children.length > 0 || queries.length > 0 ? (
                      isExpanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />
                    ) : (
                      <span className="w-4" />
                    )}
                    <FolderOpen className="w-4 h-4" />
                    <span>{folder.name}</span>
                    <span className="ml-auto text-xs text-slate-600">{queries.length}</span>
                  </button>

                  {isExpanded && (
                    <div className="ml-4">
                      {children.map(child => {
                        const childQueries = queriesByFolder[child.path] || [];
                        return (
                          <div key={child.path}>
                            <button
                              onClick={() => toggleFolder(child.path)}
                              className="w-full flex items-center gap-2 px-2 py-1.5 rounded text-sm text-slate-500 hover:bg-slate-700/50"
                            >
                              <ChevronRight className={`w-3 h-3 transition-transform ${expandedFolders.has(child.path) ? 'rotate-90' : ''}`} />
                              <span>{child.name}</span>
                              <span className="ml-auto text-xs text-slate-600">{childQueries.length}</span>
                            </button>
                            {expandedFolders.has(child.path) && childQueries.map(query => (
                              <button
                                key={query.id}
                                onClick={() => selectQuery(query)}
                                className={`w-full text-left pl-8 pr-2 py-1.5 rounded text-sm transition-colors flex items-center gap-2 ${
                                  selectedQuery?.id === query.id
                                    ? 'bg-indigo-600/20 text-indigo-400'
                                    : 'text-slate-400 hover:bg-slate-700/50'
                                }`}
                              >
                                <FileCode className="w-3 h-3" />
                                <span className="truncate">{query.name}</span>
                              </button>
                            ))}
                          </div>
                        );
                      })}

                      {queries.map(query => (
                        <button
                          key={query.id}
                          onClick={() => selectQuery(query)}
                          className={`w-full text-left pl-6 pr-2 py-1.5 rounded text-sm transition-colors flex items-center gap-2 ${
                            selectedQuery?.id === query.id
                              ? 'bg-indigo-600/20 text-indigo-400'
                              : 'text-slate-400 hover:bg-slate-700/50'
                          }`}
                        >
                          <FileCode className="w-3 h-3" />
                          <span className="truncate">{query.name}</span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </Card>
      </div>

      {/* Main Panel */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Editor */}
        <Card className="mb-4">
          <div className="flex items-center justify-between p-3 border-b border-slate-700">
            <div className="flex items-center gap-3">
              <Input
                value={queryName}
                onChange={(e) => setQueryName(e.target.value)}
                placeholder="Query name..."
                className="w-64"
              />
              <Select
                value={queryFolder}
                onChange={setQueryFolder}
                options={FOLDER_STRUCTURE.map(f => ({ value: f.path, label: `${f.icon} ${f.name}` }))}
                className="w-48"
              />
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                size="sm"
                icon={<Database className="w-4 h-4" />}
                onClick={loadSchema}
              >
                Schema
              </Button>
              <Button
                variant="ghost"
                size="sm"
                icon={<Copy className="w-4 h-4" />}
                onClick={() => navigator.clipboard.writeText(sqlText)}
              >
                Copy
              </Button>
              {selectedQuery && (
                <>
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={<Pin className={`w-4 h-4 ${selectedQuery.is_pinned ? 'text-yellow-400' : ''}`} />}
                    onClick={() => toggleQueryPin(selectedQuery.id)}
                  >
                    {selectedQuery.is_pinned ? 'Unpin' : 'Pin'}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={<Trash2 className="w-4 h-4 text-red-400" />}
                    onClick={() => {
                      deleteResearchQuery(selectedQuery.id);
                      createNewQuery();
                    }}
                  />
                </>
              )}
              <Button
                variant="secondary"
                size="sm"
                icon={<Save className="w-4 h-4" />}
                onClick={saveQuery}
              >
                Save
              </Button>
              <Button
                variant="primary"
                size="sm"
                icon={<Play className="w-4 h-4" />}
                onClick={runQuery}
                loading={isExecuting}
              >
                Run (F5)
              </Button>
            </div>
          </div>

          <div className="relative">
            <textarea
              value={sqlText}
              onChange={(e) => setSqlText(e.target.value)}
              placeholder="Enter your SQL query..."
              className="w-full h-48 bg-slate-900 text-white font-mono text-sm p-4 resize-none focus:outline-none"
              spellCheck={false}
              onKeyDown={(e) => {
                if (e.key === 'F5' || (e.ctrlKey && e.key === 'Enter')) {
                  e.preventDefault();
                  runQuery();
                }
                if (e.key === 'Tab') {
                  e.preventDefault();
                  const start = e.currentTarget.selectionStart;
                  const end = e.currentTarget.selectionEnd;
                  setSqlText(sqlText.substring(0, start) + '  ' + sqlText.substring(end));
                }
              }}
            />
            
            {/* Execution Status */}
            <div className="absolute bottom-2 right-2 flex items-center gap-2 text-xs">
              {executionTime !== null && (
                <span className="text-slate-500 flex items-center gap-1">
                  <Clock className="w-3 h-3" />
                  {executionTime}ms
                </span>
              )}
              {results && (
                <span className="text-emerald-500 flex items-center gap-1">
                  <CheckCircle className="w-3 h-3" />
                  {results.length} rows
                </span>
              )}
              {error && (
                <span className="text-red-400 flex items-center gap-1">
                  <AlertCircle className="w-3 h-3" />
                  Error
                </span>
              )}
            </div>
          </div>
        </Card>

        {/* Schema Browser */}
        {showSchema && Object.keys(schema).length > 0 && (
          <Card className="mb-4 max-h-48 overflow-y-auto">
            <div className="p-3">
              <div className="flex items-center justify-between mb-3">
                <h4 className="text-sm font-medium text-white">Schema Reference</h4>
                <button 
                  onClick={() => setShowSchema(false)}
                  className="text-slate-400 hover:text-white"
                >
                  ✕
                </button>
              </div>
              <div className="grid grid-cols-3 gap-4">
                {Object.entries(schema).slice(0, 6).map(([table, info]: [string, any]) => (
                  <div key={table} className="text-xs">
                    <p className="font-medium text-indigo-400 flex items-center gap-1 mb-1">
                      <Table className="w-3 h-3" /> {table}
                    </p>
                    <div className="space-y-0.5">
                      {info.columns?.slice(0, 6).map((col: any) => (
                        <p key={col.name} className="text-slate-500 flex items-center gap-1 pl-2">
                          {col.type?.includes('numeric') || col.type?.includes('int') ? <Hash className="w-3 h-3" /> :
                           col.type?.includes('timestamp') ? <Calendar className="w-3 h-3" /> :
                           <Type className="w-3 h-3" />}
                          {col.name}
                        </p>
                      ))}
                      {info.columns?.length > 6 && (
                        <p className="text-slate-600 pl-2">+{info.columns.length - 6} more...</p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </Card>
        )}

        {/* Results */}
        <Card className="flex-1 flex flex-col overflow-hidden">
          {error && (
            <div className="p-4 bg-red-500/10 border-b border-red-500/30 text-red-400 text-sm flex items-center gap-2">
              <AlertCircle className="w-4 h-4" />
              {error}
            </div>
          )}

          {results && (
            <>
              <div className="p-3 border-b border-slate-700">
                <Tabs tabs={resultTabs} activeTab={resultTab} onChange={setResultTab} variant="pills" />
              </div>

              <div className="flex-1 overflow-auto p-4">
                <TabContent>
                  {resultTab === 'table' && (
                    <DataTable
                      columns={resultColumns}
                      data={results}
                      pageSize={20}
                    />
                  )}

                  {resultTab === 'chart' && resultColumns.length >= 2 && (
                    <div className="space-y-4">
                      <div className="flex items-center gap-4">
                        <Select
                          label="X Axis"
                          value={resultColumns[0]?.key}
                          onChange={() => {}}
                          options={resultColumns.map(c => ({ value: c.key, label: c.key }))}
                          className="w-40"
                        />
                        <Select
                          label="Y Axis"
                          value={resultColumns[1]?.key}
                          onChange={() => {}}
                          options={resultColumns.map(c => ({ value: c.key, label: c.key }))}
                          className="w-40"
                        />
                      </div>
                      <BarChart
                        data={chartData}
                        xKey={resultColumns[0]?.key}
                        yKey={resultColumns[1]?.key}
                        height={300}
                      />
                    </div>
                  )}

                  {resultTab === 'json' && (
                    <pre className="text-sm text-slate-300 font-mono whitespace-pre-wrap overflow-auto max-h-96">
                      {JSON.stringify(results, null, 2)}
                    </pre>
                  )}

                  {resultTab === 'sql' && (
                    <pre className="text-sm text-slate-300 font-mono whitespace-pre-wrap">
                      {sqlText}
                    </pre>
                  )}
                </TabContent>
              </div>
            </>
          )}

          {!results && !error && (
            <div className="flex-1 flex items-center justify-center text-slate-500">
              <div className="text-center">
                <Database className="w-12 h-12 mx-auto mb-3 opacity-30" />
                <p>Run a query to see results</p>
                <p className="text-sm mt-1">Press F5 or Ctrl+Enter to execute</p>
              </div>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
