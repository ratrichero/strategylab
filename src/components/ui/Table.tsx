import { cn } from '../../utils/cn';
import { ChevronUp, ChevronDown, ChevronsUpDown } from 'lucide-react';
import { useState, useMemo } from 'react';

interface Column<T> { key: keyof T | string; header: string; sortable?: boolean; width?: string; render?: (value: any, row: T) => React.ReactNode; align?: 'left' | 'center' | 'right'; }

interface DataTableProps<T> { columns: Column<T>[]; data: T[]; pageSize?: number; onRowClick?: (row: T) => void; className?: string; emptyMessage?: string; loading?: boolean; }

export function DataTable<T extends Record<string, any>>({ columns, data, pageSize = 10, onRowClick, className, emptyMessage = 'No data available', loading = false }: DataTableProps<T>) {
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc');
  const [page, setPage] = useState(1);

  const sortedData = useMemo(() => {
    if (!sortKey) return data;
    return [...data].sort((a, b) => {
      const aVal = a[sortKey]; const bVal = b[sortKey];
      if (aVal === bVal) return 0;
      if (aVal === null || aVal === undefined) return 1;
      if (bVal === null || bVal === undefined) return -1;
      const comparison = aVal < bVal ? -1 : 1;
      return sortDir === 'asc' ? comparison : -comparison;
    });
  }, [data, sortKey, sortDir]);

  const paginatedData = useMemo(() => { const start = (page - 1) * pageSize; return sortedData.slice(start, start + pageSize); }, [sortedData, page, pageSize]);
  const totalPages = Math.ceil(data.length / pageSize);

  const handleSort = (key: string) => { if (sortKey === key) setSortDir(sortDir === 'asc' ? 'desc' : 'asc'); else { setSortKey(key); setSortDir('asc'); } };

  const SortIcon = ({ columnKey }: { columnKey: string }) => {
    if (sortKey !== columnKey) return <ChevronsUpDown className="w-4 h-4 opacity-30" />;
    return sortDir === 'asc' ? <ChevronUp className="w-4 h-4 text-indigo-400" /> : <ChevronDown className="w-4 h-4 text-indigo-400" />;
  };

  if (loading) return <div className="flex items-center justify-center h-64"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-500"></div></div>;

  return (
    <div className={cn('space-y-4', className)}>
      <div className="overflow-x-auto rounded-lg border border-slate-700">
        <table className="w-full min-w-max">
          <thead><tr className="bg-slate-800/80">
            {columns.map((col) => (
              <th key={col.key as string} className={cn('px-4 py-3 text-sm font-medium text-slate-300', col.align === 'center' && 'text-center', col.align === 'right' && 'text-right', col.sortable && 'cursor-pointer hover:bg-slate-700/50 select-none')} style={{ width: col.width }} onClick={() => col.sortable && handleSort(col.key as string)}>
                <div className={cn('flex items-center gap-1', col.align === 'center' && 'justify-center', col.align === 'right' && 'justify-end')}>{col.header}{col.sortable && <SortIcon columnKey={col.key as string} />}</div>
              </th>
            ))}
          </tr></thead>
          <tbody className="divide-y divide-slate-700/50">
            {paginatedData.length === 0 ? (
              <tr><td colSpan={columns.length} className="px-4 py-12 text-center text-slate-500">{emptyMessage}</td></tr>
            ) : paginatedData.map((row, i) => (
              <tr key={i} onClick={() => onRowClick?.(row)} className={cn('bg-slate-800/30 hover:bg-slate-700/50 transition-colors', onRowClick && 'cursor-pointer')}>
                {columns.map((col) => (
                  <td key={col.key as string} className={cn('px-4 py-3 text-sm text-slate-300', col.align === 'center' && 'text-center', col.align === 'right' && 'text-right')}>
                    {col.render ? col.render(row[col.key as keyof T], row) : row[col.key as keyof T]}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {totalPages > 1 && (
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-slate-400">Showing {(page - 1) * pageSize + 1} to {Math.min(page * pageSize, data.length)} of {data.length}</p>
          <div className="flex flex-wrap items-center gap-1.5">
            <button onClick={() => setPage(1)} disabled={page === 1} className="px-2.5 py-1.5 text-sm bg-slate-700 text-white rounded-lg disabled:opacity-30 hover:bg-slate-600">First</button>
            <button onClick={() => setPage(Math.max(1, page - 1))} disabled={page === 1} className="px-2.5 py-1.5 text-sm bg-slate-700 text-white rounded-lg disabled:opacity-30 hover:bg-slate-600">‹ Prev</button>
            <div className="flex gap-1">
              {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                let pageNum: number;
                if (totalPages <= 5) pageNum = i + 1;
                else if (page <= 3) pageNum = i + 1;
                else if (page >= totalPages - 2) pageNum = totalPages - 4 + i;
                else pageNum = page - 2 + i;
                return <button key={pageNum} onClick={() => setPage(pageNum)} className={cn('w-8 h-8 text-sm rounded-lg transition-colors', page === pageNum ? 'bg-indigo-600 text-white' : 'bg-slate-700 text-slate-300 hover:bg-slate-600')}>{pageNum}</button>;
              })}
            </div>
            <button onClick={() => setPage(Math.min(totalPages, page + 1))} disabled={page === totalPages} className="px-2.5 py-1.5 text-sm bg-slate-700 text-white rounded-lg disabled:opacity-30 hover:bg-slate-600">Next ›</button>
            <button onClick={() => setPage(totalPages)} disabled={page === totalPages} className="px-2.5 py-1.5 text-sm bg-slate-700 text-white rounded-lg disabled:opacity-30 hover:bg-slate-600">Last</button>
          </div>
        </div>
      )}
    </div>
  );
}
