// Tailwind CSS class mapping for light theme
// Import in components when theme-light is active

export const light = {
  // Backgrounds
  bgBase:      'bg-[#fafbfc]',
  bgSurface:   'bg-white',
  bgElevated:  'bg-slate-50',
  bgSidebar:   'bg-slate-50',
  bgHover:     'hover:bg-slate-100',

  // Text
  textPrimary:   'text-slate-800',
  textSecondary: 'text-slate-500',
  textTertiary:  'text-slate-400',

  // Borders
  border:      'border-slate-200',
  borderLight: 'border-slate-100',
  borderFocus: 'focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/10',

  // Cards
  card:        'bg-white border border-slate-200 rounded-xl shadow-sm hover:shadow-md transition-shadow',
  cardHeader:  'text-slate-800',
  cardSubtext: 'text-slate-500',

  // Buttons
  btnPrimary:  'bg-gradient-to-br from-indigo-500 to-indigo-600 text-white shadow-sm shadow-indigo-500/30 hover:shadow-md hover:shadow-indigo-500/40 hover:-translate-y-0.5 transition-all',
  btnSecondary:'bg-white border border-slate-200 text-slate-700 hover:bg-slate-50',
  btnGhost:    'bg-transparent text-slate-500 hover:bg-slate-100 hover:text-slate-800',
  btnDanger:   'bg-gradient-to-br from-red-500 to-red-600 text-white',

  // Inputs
  input:       'bg-white border border-slate-200 text-slate-800 placeholder:text-slate-400 focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/10',

  // Table
  tableHead:   'bg-slate-50 text-slate-500 uppercase text-xs tracking-wider',
  tableRow:    'border-b border-slate-100 hover:bg-slate-50',
  tableCell:   'text-slate-700',

  // Badges
  badgeSuccess:'bg-emerald-50 text-emerald-600 border border-emerald-200/50',
  badgeDanger: 'bg-red-50 text-red-600 border border-red-200/50',
  badgeWarning:'bg-amber-50 text-amber-600 border border-amber-200/50',
  badgeInfo:   'bg-blue-50 text-blue-600 border border-blue-200/50',
  badgeDefault:'bg-slate-100 text-slate-600 border border-slate-200/50',

  // Tabs
  tabActive:   'text-indigo-600 border-b-2 border-indigo-500 font-semibold',
  tabInactive: 'text-slate-400 hover:text-slate-700',

  // Score colors
  scoreHigh:   'text-emerald-600',
  scoreMid:    'text-amber-500',
  scoreLow:    'text-red-500',

  // Charts
  chartGrid:   '#f1f5f9',
  chartText:   '#94a3b8',
  chartLine1:  '#6366f1',
  chartLine2:  '#14b8a6',
  chartArea1:  'rgba(99, 102, 241, 0.08)',
  chartArea2:  'rgba(20, 184, 166, 0.08)',

  // Status badges
  modePaper:   'bg-blue-50 text-blue-600 border border-blue-200/50',
  modeTestnet: 'bg-amber-50 text-amber-600 border border-amber-200/50',
  modeLive:    'bg-red-50 text-red-600 border border-red-200/50 animate-pulse',

  // Sidebar
  sidebarBg:     'bg-gradient-to-b from-white to-slate-50',
  sidebarBorder: 'border-r border-slate-200',
  navActive:     'bg-indigo-50 text-indigo-600 border border-indigo-100',
  navInactive:   'text-slate-500 hover:bg-slate-100 hover:text-slate-800',

  // Header
  headerBg:      'bg-white/80 backdrop-blur-xl border-b border-slate-100',
};

export default light;
