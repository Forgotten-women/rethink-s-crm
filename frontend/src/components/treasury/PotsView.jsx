import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Wallet, Search, ArrowRightLeft, ShieldAlert, CheckCircle2, Building, Layers,
  X, ChevronLeft, ChevronRight, RefreshCw, AlertTriangle, TrendingUp, TrendingDown,
  Filter, LayoutGrid, List, ArrowUpRight, ArrowDownLeft, Download, PlusCircle,
  ChevronDown, ChevronUp, History
} from 'lucide-react';
import { can } from '../../access';
import { CURRENCY_META, REGION_FLAGS, formatMoney } from './treasuryUtils';
import { treasuryApi, treasuryExport } from './TreasuryPanels';
import { ReallocationPlanner, PotCreateForm } from './PotsForms';
import { MiniFlow } from './TreasuryCharts';
import { PotCard } from './PotCard';

export default function PotsView({ user, activeCompany = 'rethink', initialCountry = 'ALL', embedded = false }) {
  const company = (activeCompany && activeCompany !== 'all' ? activeCompany : 'rethink').toLowerCase();
  const [loadError, setLoadError] = useState('');
  const [plannerFrom, setPlannerFrom] = useState(null); // null = closed, '' = open with no source
  const [showNewPot, setShowNewPot] = useState(false);
  const [displayCurrency, setDisplayCurrency] = useState('USD');
  const [data, setData] = useState({ summary: {}, portfolios: [], countries: [], pots: [] });
  const [loading, setLoading] = useState(true);

  // Filters
  const [portfolioFilter, setPortfolioFilter] = useState('ALL');
  const [countryFilter, setCountryFilter] = useState(initialCountry || 'ALL');
  useEffect(() => {
    setCountryFilter(initialCountry || 'ALL');
  }, [initialCountry]);
  const [poolFilter, setPoolFilter] = useState('ALL');
  const [overheadFilter, setOverheadFilter] = useState('ALL'); // 'ALL' | '0' (projects) | '1' (offices/overheads)
  const [healthFilter, setHealthFilter] = useState('ALL'); // 'ALL' | 'surplus' | 'deficit'
  const [search, setSearch] = useState('');
  const [viewMode, setViewMode] = useState('table'); // 'table' | 'grid'
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);

  // Pot Detail Drawer
  const [selectedPotId, setSelectedPotId] = useState(null);
  const [potDetail, setPotDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [lineFilter, setLineFilter] = useState('ALL'); // 'ALL' | 'inc' | 'exp' | 'adj'
  const [ledgerSearch, setLedgerSearch] = useState('');
  const [correctionsOpen, setCorrectionsOpen] = useState(false);

  const [submitting, setSubmitting] = useState(false);
  const [toast, setToast] = useState(null);

  const canWrite = can(user, 'expenses.transfers', activeCompany) || can(user, 'expenses.submit', activeCompany);
  const canManage = can(user, 'expenses.transfers', activeCompany);
  const canExport = can(user, 'expenses.export', activeCompany);
  const filterParams = {
    ...(portfolioFilter !== 'ALL' ? { portfolio: portfolioFilter } : {}),
    ...(countryFilter !== 'ALL' ? { country: countryFilter } : {}),
    ...(poolFilter !== 'ALL' ? { pool: poolFilter } : {}),
    ...(overheadFilter !== 'ALL' ? { is_overhead: overheadFilter } : {}),
    ...(healthFilter !== 'ALL' ? { health: healthFilter } : {}),
    ...(search.trim() ? { search: search.trim() } : {}),
  };

  const showToast = (msg, type = 'success') => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 4500);
  };

  const fetchPots = useCallback(async () => {
    setLoading(true);
    setLoadError('');
    try {
      setData(await treasuryApi('/pots', { company, params: { display_currency: displayCurrency, ...filterParams } }));
    } catch (e) {
      setLoadError(e.message);
    } finally {
      setLoading(false);
    }
  }, [company, displayCurrency, portfolioFilter, countryFilter, poolFilter, overheadFilter, healthFilter, search]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    fetchPots();
  }, [fetchPots]);

  useEffect(() => {
    setPage(1);
  }, [portfolioFilter, countryFilter, poolFilter, overheadFilter, healthFilter, search]);

  const fetchPotDetail = useCallback(async (potId) => {
    if (!potId) return;
    setDetailLoading(true);
    try {
      setPotDetail(await treasuryApi(`/pots/${encodeURIComponent(potId)}`, { company }));
    } catch (e) {
      console.error('Pot detail error:', e);
    } finally {
      setDetailLoading(false);
    }
  }, [company]);

  useEffect(() => {
    if (selectedPotId) {
      setLineFilter('ALL');
      setLedgerSearch('');
      setCorrectionsOpen(false);
      fetchPotDetail(selectedPotId);
    } else {
      setPotDetail(null);
    }
  }, [selectedPotId, fetchPotDetail]);

  // Keep unfiltered list for reallocation modal dropdowns
  const [allPotsOptions, setAllPotsOptions] = useState([]);
  useEffect(() => {
    treasuryApi('/pots', { company, params: { display_currency: 'USD' } })
      .then((d) => { if (d?.pots) setAllPotsOptions(d.pots); })
      .catch(() => {});
  }, [company, data.summary?.total_balance_usd]);

  const summary = data.summary || {};
  const pots = data.pots || [];
  const totalPages = pageSize === 0 ? 1 : Math.max(1, Math.ceil(pots.length / pageSize));
  const pagedPots = useMemo(() => {
    if (pageSize === 0) return pots;
    const start = (page - 1) * pageSize;
    return pots.slice(start, start + pageSize);
  }, [pots, page, pageSize]);

  const handleOpenReallocFor = (potId) => setPlannerFrom(potId || '');
  const afterPlan = (msg) => {
    setPlannerFrom(null);
    setShowNewPot(false);
    showToast(msg);
    fetchPots();
    if (selectedPotId) fetchPotDetail(selectedPotId);
  };

  const lineCounts = useMemo(() => {
    const lines = potDetail?.lines || [];
    return {
      all: lines.length,
      inc: lines.filter((l) => l.amount_usd > 0).length,
      exp: lines.filter((l) => l.amount_usd < 0).length,
      adj: lines.filter((l) => l.line_kind === 'adj' || l.line_kind === 'reallocation' || l.line_kind === 'manual').length,
    };
  }, [potDetail]);

  const filteredLines = useMemo(() => {
    let lines = potDetail?.lines || [];
    if (lineFilter === 'inc') lines = lines.filter((l) => l.amount_usd > 0);
    else if (lineFilter === 'exp') lines = lines.filter((l) => l.amount_usd < 0);
    else if (lineFilter === 'adj') lines = lines.filter((l) => l.line_kind === 'adj' || l.line_kind === 'reallocation' || l.line_kind === 'manual');

    if (ledgerSearch.trim()) {
      const q = ledgerSearch.toLowerCase().trim();
      lines = lines.filter((l) =>
        (l.description && l.description.toLowerCase().includes(q)) ||
        (l.source && l.source.toLowerCase().includes(q)) ||
        (l.native_note && l.native_note.toLowerCase().includes(q)) ||
        (l.line_date && l.line_date.includes(q))
      );
    }
    return lines;
  }, [potDetail, lineFilter, ledgerSearch]);

  const ledgerMetrics = useMemo(() => {
    let inTotal = 0;
    let outTotal = 0;
    for (const ln of filteredLines) {
      if (ln.amount_usd > 0) inTotal += ln.amount_usd;
      else if (ln.amount_usd < 0) outTotal += Math.abs(ln.amount_usd);
    }
    return {
      inTotal: Math.round(inTotal * 100) / 100,
      outTotal: Math.round(outTotal * 100) / 100,
      netTotal: Math.round((inTotal - outTotal) * 100) / 100,
    };
  }, [filteredLines]);

  const disp = displayCurrency;
  const zakatTotal = (summary.zakat_balance_usd || 0) + (summary.non_zakat_balance_usd || 0);
  const zakatPct = zakatTotal > 0 ? Math.max(0, Math.min(100, Math.round(((summary.zakat_balance_usd || 0) / zakatTotal) * 100))) : 50;

  return (
    <div className="space-y-6 pb-12 panel-pop">
      {toast && (
        <div
          className={`fixed bottom-6 right-6 z-50 px-5 py-3.5 rounded-xl shadow-2xl border flex items-center gap-3 keep-white ${
            toast.type === 'error' ? 'bg-rose-600 border-rose-400' : 'bg-emerald-600 border-emerald-400'
          }`}
        >
          {toast.type === 'error' ? <ShieldAlert className="w-5 h-5" /> : <CheckCircle2 className="w-5 h-5" />}
          <span className="font-semibold text-sm">{toast.msg}</span>
        </div>
      )}

      {/* Header */}
      <div className="glass-panel p-5 border-purple">
        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
          <div className="flex items-start gap-4">
            {!embedded && (
              <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-purple-500 to-indigo-600 flex items-center justify-center shadow-lg shrink-0 keep-white">
                <Wallet className="w-6 h-6" />
              </div>
            )}
            <div>
              <div className="flex flex-wrap items-center gap-2.5">
                {embedded ? (
                  <h2 className="text-lg font-bold tracking-tight">Project Pots, Programmes &amp; Office Budgets</h2>
                ) : (
                  <h1 className="text-2xl font-bold tracking-tight">Project Pots, Programmes &amp; Office Budgets</h1>
                )}
                <span className="badge badge-purple">
                  {summary.filtered_count != null && summary.filtered_count !== summary.total_count
                    ? `${summary.filtered_count} of ${summary.total_count} Active Pots`
                    : `${summary.total_count || 274} Active Pots`}
                </span>
              </div>
              <p className="text-xs text-slate-400 mt-1">
                Every campaign income allocation, field expenditure, administrative office overhead &amp; Zakat wall tracked per pot.
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2.5">
            <div className="flex rounded-xl p-1 border border-slate-700/60 bg-slate-900/50">
              {['USD', 'GBP'].map((cur) => (
                <button
                  key={cur}
                  onClick={() => setDisplayCurrency(cur)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${
                    displayCurrency === cur ? 'bg-purple-600 keep-white shadow' : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {CURRENCY_META[cur].flag} {cur}
                </button>
              ))}
            </div>

            {canWrite && (
              <button
                onClick={() => handleOpenReallocFor('')}
                className="btn-primary text-xs flex items-center gap-1.5 keep-white"
              >
                <ArrowRightLeft className="w-3.5 h-3.5" /> Reallocate / plan
              </button>
            )}
            {canManage && (
              <button onClick={() => setShowNewPot(true)} className="btn-secondary text-xs flex items-center gap-1.5">
                <PlusCircle className="w-3.5 h-3.5" /> New pot
              </button>
            )}
            {canExport && (
              <button onClick={() => treasuryExport('/pots/export', company, filterParams)} className="btn-secondary text-xs flex items-center gap-1.5">
                <Download className="w-3.5 h-3.5" /> CSV
              </button>
            )}

            <button
              onClick={fetchPots}
              className="p-2 rounded-xl border border-slate-700/60 hover:border-purple-400/60"
              title="Refresh Pots"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin text-purple-400' : 'text-slate-400'}`} />
            </button>
          </div>
        </div>
      </div>

      {loadError && <div className="glass-panel p-4 text-sm text-rose-400 flex items-center gap-2"><AlertTriangle className="w-4 h-4" /> {loadError}</div>}

      {/* KPI Cards & Pool Split */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        <div className="glass-panel p-5 border-cyan">
          <div className="text-xs font-bold uppercase tracking-wider text-slate-400">Balance 30 Jun 2026</div>
          <div className="text-3xl font-extrabold tabular-nums mt-2">{formatMoney(disp === 'USD' ? summary.total_bal_jun_usd : (summary.total_bal_jun_display || summary.total_bal_jun_usd), disp)}</div>
          <div className="text-xs text-slate-400 mt-1">{summary.filtered_count != null && summary.filtered_count !== summary.total_count ? `${summary.filtered_count} filtered pots carried forward` : 'FY 2025/26 closing carried forward'}</div>
        </div>

        <div className="glass-panel p-5 border-emerald">
          <div className="text-xs font-bold uppercase tracking-wider text-emerald-400">Jul–Oct Income Credited</div>
          <div className="text-3xl font-extrabold tabular-nums mt-2 text-emerald-400">+{formatMoney(disp === 'USD' ? summary.total_inc_usd : (summary.total_inc_display || summary.total_inc_usd), disp)}</div>
          <div className="text-xs text-slate-400 mt-1">{summary.filtered_count != null && summary.filtered_count !== summary.total_count ? `Income for ${summary.filtered_count} shown pots` : 'From payouts, platforms & direct bank gifts'}</div>
        </div>

        <div className="glass-panel p-5 border-pink">
          <div className="text-xs font-bold uppercase tracking-wider text-rose-400">Jul–Oct Spend &amp; Field Costs</div>
          <div className="text-3xl font-extrabold tabular-nums mt-2 text-rose-400">−{formatMoney(disp === 'USD' ? summary.total_exp_usd : (summary.total_exp_display || summary.total_exp_usd), disp)}</div>
          <div className="text-xs text-slate-400 mt-1">{summary.filtered_count != null && summary.filtered_count !== summary.total_count ? `Spend for ${summary.filtered_count} shown pots` : 'Direct project execution + office running costs'}</div>
        </div>

        <div className="glass-panel p-5 border-purple">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-wider text-purple-400">Net Fund Balance</span>
            <span className="badge badge-emerald text-[10px]">{summary.surplus_count || 0} Surplus · {summary.deficit_count || 0} Deficit</span>
          </div>
          <div className="text-3xl font-extrabold tabular-nums mt-2 text-purple-400">
            {formatMoney(summary.total_balance_display, disp)}
          </div>
          {/* Zakat vs Non-Zakat Visual Bar */}
          <div className="mt-2.5 space-y-1">
            <div className="tviz h-2 w-full flex gap-[2px]" role="img" aria-label={`Zakat ${zakatPct}%, non-zakat ${100 - zakatPct}%`}>
              <div style={{ width: `${zakatPct}%`, background: 'var(--viz-1)', borderRadius: '4px 0 0 4px' }} title="Zakat balance" />
              <div style={{ width: `${100 - zakatPct}%`, background: 'var(--viz-2)', borderRadius: '0 4px 4px 0' }} title="Non-zakat balance" />
            </div>
            <div className="tviz flex items-center justify-between text-[10px] text-slate-400 tabular-nums">
              <span className="flex items-center gap-1"><span className="tviz-swatch" style={{ background: 'var(--viz-1)' }} />Zakat <strong className="text-slate-200">{formatMoney(summary.zakat_balance_usd, 'USD', { compact: true })}</strong></span>
              <span className="flex items-center gap-1"><span className="tviz-swatch" style={{ background: 'var(--viz-2)' }} />Non-zakat <strong className="text-slate-200">{formatMoney(summary.non_zakat_balance_usd, 'USD', { compact: true })}</strong></span>
            </div>
            {summary.deficit_count > 0 && (
              <button type="button" onClick={() => setHealthFilter('deficit')} className="text-[10px] text-rose-400 hover:underline">
                {summary.deficit_count} pots in deficit · {formatMoney(summary.deficit_total_usd, 'USD', { compact: true })} → show
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Portfolio Quick Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3">
        <button
          onClick={() => setPortfolioFilter('ALL')}
          className={`glass-panel p-3.5 text-left transition-all ${
            portfolioFilter === 'ALL' ? 'ring-2 ring-purple-500' : 'hover:border-purple-400/40'
          }`}
        >
          <div className="text-[11px] font-bold text-slate-400 truncate">
            {countryFilter !== 'ALL' ? `${countryFilter} Portfolios` : 'All Portfolios'}
          </div>
          <div className="text-lg font-extrabold tabular-nums mt-1">{formatMoney(summary.total_balance_display, disp, { compact: true })}</div>
          <div className="text-[10px] text-slate-500">{summary.filtered_count || summary.total_count} pots</div>
        </button>

        {(data.portfolios || []).map((pf) => (
          <button
            key={pf.portfolio}
            onClick={() => setPortfolioFilter(portfolioFilter === pf.portfolio ? 'ALL' : pf.portfolio)}
            className={`glass-panel p-3.5 text-left transition-all ${
              portfolioFilter === pf.portfolio ? 'ring-2 ring-purple-500' : 'hover:border-purple-400/40'
            }`}
          >
            <div className="text-[11px] font-bold text-slate-400 truncate" title={pf.portfolio}>{pf.portfolio}</div>
            <div className={`text-lg font-extrabold tabular-nums mt-1 ${pf.balance_display < 0 ? 'text-rose-400' : ''}`}>
              {formatMoney(pf.balance_display, disp, { compact: true })}
            </div>
            <div className="text-[10px] text-slate-500">{pf.count} pots</div>
          </button>
        ))}
      </div>

      {/* Multi-Faceted Filter Bar */}
      <div className="glass-panel p-4 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative">
              <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search fund code, pot, country..."
                className="pl-8 pr-3 py-1.5 rounded-lg border text-xs w-64"
              />
            </div>

            <select
              value={countryFilter}
              onChange={(e) => setCountryFilter(e.target.value)}
              className="px-3 py-1.5 rounded-lg border text-xs font-semibold"
            >
              <option value="ALL">All Countries</option>
              {(data.countries || []).map((c) => (
                <option key={c.country} value={c.country}>
                  {REGION_FLAGS[c.country] || '🌐'} {c.country} ({c.count})
                </option>
              ))}
            </select>

            <div className="flex rounded-lg border border-slate-700/50 p-0.5 text-xs">
              {[
                { id: 'ALL', label: 'All Pools' },
                { id: 'Zakat', label: '🛡️ Zakat' },
                { id: 'Non-Zakat', label: 'Non-Zakat' },
              ].map((pl) => (
                <button
                  key={pl.id}
                  onClick={() => setPoolFilter(pl.id)}
                  className={`px-2.5 py-1 rounded-md font-semibold ${
                    poolFilter === pl.id ? 'bg-emerald-600 keep-white' : 'text-slate-400'
                  }`}
                >
                  {pl.label}
                </button>
              ))}
            </div>

            <div className="flex rounded-lg border border-slate-700/50 p-0.5 text-xs">
              {[
                { id: 'ALL', label: 'Projects & Offices' },
                { id: '0', label: 'Programme Pots' },
                { id: '1', label: '🏢 Office & Running Costs' },
              ].map((ov) => (
                <button
                  key={ov.id}
                  onClick={() => setOverheadFilter(ov.id)}
                  className={`px-2.5 py-1 rounded-md font-semibold ${
                    overheadFilter === ov.id ? 'bg-purple-600 keep-white' : 'text-slate-400'
                  }`}
                >
                  {ov.label}
                </button>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-2">
            <div className="flex rounded-lg border border-slate-700/50 p-0.5 text-xs">
              {[
                { id: 'ALL', label: 'All Statuses' },
                { id: 'surplus', label: 'Surplus' },
                { id: 'deficit', label: '⚠️ Deficit' },
              ].map((h) => (
                <button
                  key={h.id}
                  onClick={() => setHealthFilter(h.id)}
                  className={`px-2.5 py-1 rounded-md font-semibold ${
                    healthFilter === h.id ? 'bg-blue-600 keep-white' : 'text-slate-400'
                  }`}
                >
                  {h.label}
                </button>
              ))}
            </div>

            <div className="flex rounded-lg border border-slate-700/50 p-0.5">
              <button
                onClick={() => setViewMode('table')}
                className={`p-1.5 rounded-md ${viewMode === 'table' ? 'bg-blue-600 keep-white' : 'text-slate-400'}`}
              >
                <List className="w-3.5 h-3.5" />
              </button>
              <button
                onClick={() => setViewMode('grid')}
                className={`p-1.5 rounded-md ${viewMode === 'grid' ? 'bg-blue-600 keep-white' : 'text-slate-400'}`}
              >
                <LayoutGrid className="w-3.5 h-3.5" />
              </button>
            </div>

            <select
              value={pageSize}
              onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }}
              className="px-2.5 py-1.5 rounded-lg border text-xs font-semibold"
              aria-label="Rows per page"
            >
              <option value={50}>50 per page</option>
              <option value={100}>100 per page</option>
              <option value={0}>All {pots.length} pots</option>
            </select>
          </div>
        </div>
      </div>

      {/* Pots List (Table or Card Grid) */}
      {viewMode === 'table' ? (
        <div className="glass-panel overflow-x-auto">
          <table className="crm-table">
            <thead>
              <tr>
                <th>Code &amp; Pot Name</th>
                <th>Portfolio / Programme</th>
                <th>Country</th>
                <th>Pool &amp; Cost Type</th>
                <th className="text-right">Jun 30 Bal</th>
                <th className="text-right">Jul–Oct In</th>
                <th className="text-right">Jul–Oct Out</th>
                <th className="text-right">Net Balance ({disp})</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {pagedPots.map((p) => {
                const isDeficit = p.current_balance_usd < -0.01;
                return (
                  <tr key={p.id} onClick={() => { setSelectedPotId(p.id); setLineFilter('ALL'); }} className="cursor-pointer">
                    <td>
                      <div className="flex items-center gap-2">
                        {p.code && <span className="font-mono text-[11px] px-1.5 py-0.5 rounded bg-slate-800/70 text-cyan-400">{p.code}</span>}
                        <span className="font-bold">{p.name}</span>
                      </div>
                    </td>
                    <td>
                      <div className="text-xs font-semibold">{p.portfolio}</div>
                      <div className="text-[11px] text-slate-400">{p.program}</div>
                    </td>
                    <td className="whitespace-nowrap text-xs">
                      {REGION_FLAGS[p.country] || '🌐'} {p.country}
                    </td>
                    <td>
                      <div className="flex flex-wrap items-center gap-1">
                        <span className={`badge text-[10px] ${p.pool === 'Zakat' ? 'badge-emerald' : 'badge-purple'}`}>
                          {p.pool}
                        </span>
                        {Boolean(p.is_overhead) && <span className="badge badge-amber text-[10px]">Office / Admin</span>}
                      </div>
                    </td>
                    <td className="text-right tabular-nums text-xs text-slate-400">{formatMoney(p.bal_jun_usd, 'USD')}</td>
                    <td className="text-right tabular-nums text-xs text-emerald-400">+{formatMoney(p.display_income, disp)}</td>
                    <td className="text-right tabular-nums text-xs text-rose-400">−{formatMoney(p.display_expense, disp)}</td>
                    <td className={`text-right font-extrabold tabular-nums ${isDeficit ? 'text-rose-400' : 'text-emerald-400'}`}>
                      {formatMoney(p.display_balance, disp)}
                    </td>
                    <td className="text-right text-cyan-400 font-semibold text-xs whitespace-nowrap">Ledger →</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4.5">
          {pagedPots.map((p) => (
            <PotCard
              key={p.id}
              pot={p}
              disp={disp}
              onClick={() => { setSelectedPotId(p.id); setLineFilter('ALL'); }}
            />
          ))}
        </div>
      )}

      {/* Pagination */}
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-400">
        <span>Showing {pagedPots.length} of {pots.length} matching pots (Page {page} of {totalPages})</span>
        <div className="flex items-center gap-2">
          <select
            value={pageSize}
            onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }}
            className="px-2.5 py-1 rounded-lg border text-xs font-semibold"
            aria-label="Rows per page footer"
          >
            <option value={50}>50 per page</option>
            <option value={100}>100 per page</option>
            <option value={0}>All {pots.length} pots</option>
          </select>
          <button
            disabled={page <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            className="btn-secondary px-2.5 py-1 disabled:opacity-40"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
          <button
            disabled={page >= totalPages}
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            className="btn-secondary px-2.5 py-1 disabled:opacity-40"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* SLIDE-OVER DRAWER: POT WATERFALL & ITEMIZED LEDGER */}
      {selectedPotId && (
        <>
          <div className="drawer-backdrop" onClick={() => setSelectedPotId(null)} />
          <div className="drawer-content drawer-wide flex flex-col">
            <div className="p-6 border-b border-slate-700/40 flex flex-wrap items-center justify-between gap-4">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  {potDetail?.pot?.code && <span className="font-mono text-xs px-2 py-0.5 rounded bg-slate-800 text-cyan-400">{potDetail.pot.code}</span>}
                  <h2 className="text-xl font-bold">{potDetail?.pot?.name || 'Loading...'}</h2>
                  {potDetail?.pot && (
                    <span className={`badge ${potDetail.pot.pool === 'Zakat' ? 'badge-emerald' : 'badge-purple'}`}>
                      {potDetail.pot.pool}
                    </span>
                  )}
                  {Boolean(potDetail?.pot?.is_overhead) && <span className="badge badge-amber">Office / Overhead Cost</span>}
                </div>
                {potDetail?.pot && (
                  <p className="text-xs text-slate-400 mt-1">
                    {REGION_FLAGS[potDetail.pot.country]} {potDetail.pot.country} · {potDetail.pot.portfolio} &rarr; {potDetail.pot.program}
                  </p>
                )}
              </div>

              <div className="flex items-center gap-3">
                {canWrite && potDetail?.pot && (
                  <button
                    onClick={() => handleOpenReallocFor(potDetail.pot.id)}
                    className="btn-primary text-xs flex items-center gap-1.5 keep-white"
                  >
                    <ArrowRightLeft className="w-3.5 h-3.5" /> Reallocate Funds
                  </button>
                )}
                <button
                  onClick={() => setSelectedPotId(null)}
                  className="p-2 rounded-xl border border-slate-700/50 hover:border-slate-500"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
            </div>

            {detailLoading ? (
              <div className="p-20 text-center text-slate-400 text-sm">Loading pot waterfall and transaction lines...</div>
            ) : potDetail?.pot ? (
              <div className="flex-1 overflow-y-auto custom-scrollbar p-6 space-y-5">
                {/* Waterfall Progression Strip */}
                <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
                  <div className="p-3 rounded-xl bg-slate-900/40 border border-slate-700/30">
                    <div className="text-[10px] text-slate-400 uppercase font-bold">Opening (FY Start)</div>
                    <div className="text-base font-bold tabular-nums mt-1">{formatMoney(potDetail.pot.opening_balance_usd, 'USD')}</div>
                  </div>
                  <div className="p-3 rounded-xl bg-slate-900/40 border border-slate-700/30">
                    <div className="text-[10px] text-slate-400 uppercase font-bold">Bal 30 Jun 2026</div>
                    <div className="text-base font-bold tabular-nums mt-1">{formatMoney(potDetail.pot.bal_jun_usd, 'USD')}</div>
                  </div>
                  <div className="p-3 rounded-xl bg-slate-900/40 border border-emerald-500/20">
                    <div className="text-[10px] text-emerald-400 uppercase font-bold">Jul–Oct Income</div>
                    <div className="text-base font-bold tabular-nums text-emerald-400 mt-1">+{formatMoney(potDetail.pot.inc_jul_oct_usd, 'USD')}</div>
                  </div>
                  <div className="p-3 rounded-xl bg-slate-900/40 border border-rose-500/20">
                    <div className="text-[10px] text-rose-400 uppercase font-bold">Jul–Oct Spend</div>
                    <div className="text-base font-bold tabular-nums text-rose-400 mt-1">−{formatMoney(potDetail.pot.exp_jul_oct_usd, 'USD')}</div>
                  </div>
                  <div className="p-3 rounded-xl bg-slate-900/40 border border-purple-500/40">
                    <div className="text-[10px] text-purple-400 uppercase font-bold">Current Net Balance</div>
                    <div className={`text-lg font-extrabold tabular-nums mt-1 ${potDetail.pot.current_balance_usd < 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
                      {formatMoney(potDetail.pot.current_balance_usd, 'USD')}
                    </div>
                  </div>
                </div>

                {Object.keys(potDetail.pot.months || {}).length > 0 && (
                  <div className="flex items-center justify-between gap-4 p-3 rounded-xl bg-slate-900/40 border border-slate-700/30">
                    <div className="text-xs">
                      <div className="font-bold">By month</div>
                      <div className="tviz flex items-center gap-3 text-slate-400 mt-1">
                        <span className="flex items-center gap-1"><span className="tviz-swatch" style={{ background: 'var(--viz-1)' }} />In</span>
                        <span className="flex items-center gap-1"><span className="tviz-swatch" style={{ background: 'var(--viz-2)' }} />Out</span>
                      </div>
                    </div>
                    <MiniFlow months={potDetail.pot.months} currency="USD" />
                  </div>
                )}

                {/* Corrections touching this pot */}
                {(potDetail.adjustments || []).length > 0 && (
                  <div className="rounded-2xl border border-purple-500/25 bg-purple-500/5 dark:bg-purple-950/20 overflow-hidden shadow-xs transition-all">
                    <button
                      type="button"
                      onClick={() => setCorrectionsOpen((prev) => !prev)}
                      className="w-full px-4 py-3 flex items-center justify-between text-left hover:bg-purple-500/10 transition-colors"
                    >
                      <div className="flex items-center gap-2.5">
                        <div className="p-1.5 rounded-lg bg-purple-500/15 text-purple-600 dark:text-purple-400 shrink-0">
                          <History className="w-4 h-4" />
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="font-extrabold text-xs text-slate-800 dark:text-slate-100">
                            Corrections touching this pot
                          </span>
                          <span className="px-2 py-0.5 rounded-full text-[10px] font-black bg-purple-500/15 text-purple-700 dark:text-purple-300 border border-purple-500/25">
                            {potDetail.adjustments.length}
                          </span>
                        </div>
                      </div>
                      <div className="flex items-center gap-1.5 text-xs font-bold text-purple-600 dark:text-purple-400">
                        <span>{correctionsOpen ? 'Hide' : 'View'}</span>
                        <ChevronDown className={`w-4 h-4 transition-transform duration-200 ${correctionsOpen ? 'rotate-180' : ''}`} />
                      </div>
                    </button>

                    {correctionsOpen && (
                      <div className="px-4 pb-3 pt-1 border-t border-purple-500/15 space-y-2 max-h-64 overflow-y-auto custom-scrollbar">
                        {potDetail.adjustments.map((a) => {
                          const out = a.from_fund === potDetail.pot.name && a.from_country === potDetail.pot.country && a.from_pool === potDetail.pot.pool;
                          return (
                            <div key={a.id} className="p-2.5 rounded-xl bg-white/60 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-800 flex items-center justify-between gap-3 text-xs shadow-2xs">
                              <div className="min-w-0 flex-1">
                                <div className="flex items-center gap-2 font-bold text-slate-800 dark:text-slate-200">
                                  <span className="font-mono text-[11px] text-slate-500">{a.adj_date}</span>
                                  <span className="px-1.5 py-0.5 rounded text-[10px] uppercase font-black bg-purple-500/15 text-purple-700 dark:text-purple-300">
                                    {a.adj_type}
                                  </span>
                                  {a.to_fund && (
                                    <span className="text-[11px] font-semibold text-cyan-600 dark:text-cyan-400 truncate">
                                      {out ? `→ ${a.to_fund}` : `← ${a.from_fund}`}
                                    </span>
                                  )}
                                </div>
                                {a.note && <div className="text-slate-500 dark:text-slate-400 truncate text-[11px] mt-0.5" title={a.note}>{a.note}</div>}
                                {a.approved_by && <div className="text-[10px] text-slate-400 mt-0.5">Approved by: <span className="font-semibold text-slate-600 dark:text-slate-300">{a.approved_by}</span></div>}
                              </div>
                              <span className={`font-mono font-black text-xs px-2.5 py-1 rounded-lg border tabular-nums shrink-0 ${
                                out && a.to_fund
                                  ? 'text-rose-600 dark:text-rose-400 bg-rose-500/10 border-rose-500/25'
                                  : 'text-emerald-600 dark:text-emerald-400 bg-emerald-500/10 border-emerald-500/25'
                              }`}>
                                {formatMoney(out && a.to_fund ? -a.usd : a.usd, 'USD', { signed: !!a.to_fund })}
                              </span>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                )}

                {/* Line Type Filter Toolbar & Metrics */}
                <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3 pt-2">
                  <div className="flex flex-wrap items-center gap-1.5 text-xs">
                    {[
                      { id: 'ALL', label: 'All Entries', count: lineCounts.all, color: 'purple' },
                      { id: 'inc', label: 'Income In', count: lineCounts.inc, color: 'emerald' },
                      { id: 'exp', label: 'Expenses Out', count: lineCounts.exp, color: 'rose' },
                      { id: 'adj', label: 'Adjustments & Reallocations', count: lineCounts.adj, color: 'blue' },
                    ].map((lf) => {
                      const isActive = lineFilter === lf.id;
                      return (
                        <button
                          key={lf.id}
                          onClick={() => setLineFilter(lf.id)}
                          className={`px-3 py-1.5 rounded-xl font-bold flex items-center gap-1.5 text-xs transition-all ${
                            isActive
                              ? lf.color === 'emerald'
                                ? 'bg-emerald-600 text-white shadow-xs'
                                : lf.color === 'rose'
                                ? 'bg-rose-600 text-white shadow-xs'
                                : lf.color === 'blue'
                                ? 'bg-blue-600 text-white shadow-xs'
                                : 'bg-purple-600 text-white shadow-xs'
                              : 'bg-slate-100 hover:bg-slate-200 dark:bg-slate-800/60 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-400'
                          }`}
                        >
                          <span>{lf.label}</span>
                          <span className={`px-1.5 py-0.2 rounded-full text-[10px] font-black ${
                            isActive ? 'bg-white/20 text-white' : 'bg-slate-200/80 dark:bg-slate-700/80 text-slate-600 dark:text-slate-300'
                          }`}>
                            {lf.count}
                          </span>
                        </button>
                      );
                    })}
                  </div>

                  {/* Search within ledger */}
                  <div className="relative min-w-[200px] sm:max-w-xs">
                    <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                    <input
                      type="text"
                      placeholder="Search narrative, report..."
                      value={ledgerSearch}
                      onChange={(e) => setLedgerSearch(e.target.value)}
                      className="w-full pl-8 pr-7 py-1.5 text-xs rounded-xl border border-slate-200 dark:border-slate-700/60 bg-white dark:bg-slate-900/60 text-slate-800 dark:text-slate-200 focus:outline-none focus:border-cyan-500"
                    />
                    {ledgerSearch && (
                      <button
                        onClick={() => setLedgerSearch('')}
                        className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
                      >
                        <X className="w-3 h-3" />
                      </button>
                    )}
                  </div>
                </div>

                {/* Subtotal KPI Strip */}
                <div className="flex flex-wrap items-center justify-between gap-2 px-3.5 py-2 rounded-xl bg-slate-50 dark:bg-slate-900/40 border border-slate-200/80 dark:border-slate-800/80 text-xs">
                  <span className="font-semibold text-slate-500 dark:text-slate-400 text-[11px]">
                    Showing <span className="font-bold text-slate-800 dark:text-slate-100">{filteredLines.length}</span> of {lineCounts.all} entries
                  </span>
                  <div className="flex items-center gap-3 text-xs font-mono font-bold">
                    <span className="text-emerald-600 dark:text-emerald-400">
                      Inflows: +{formatMoney(ledgerMetrics.inTotal, 'USD')}
                    </span>
                    <span className="text-slate-300 dark:text-slate-700">•</span>
                    <span className="text-rose-600 dark:text-rose-400">
                      Outflows: -{formatMoney(ledgerMetrics.outTotal, 'USD')}
                    </span>
                    <span className="text-slate-300 dark:text-slate-700">•</span>
                    <span className={ledgerMetrics.netTotal >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'}>
                      Net: {formatMoney(ledgerMetrics.netTotal, 'USD', { signed: true })}
                    </span>
                  </div>
                </div>

                {/* Itemized Ledger Table with Green & Red Badges */}
                <div className="rounded-2xl border border-slate-200 dark:border-slate-800 overflow-hidden bg-white dark:bg-slate-900/40 shadow-xs">
                  <div className="overflow-x-auto">
                    <table className="crm-table w-full text-left">
                      <thead>
                        <tr className="border-b border-slate-200 dark:border-slate-800 bg-slate-50/80 dark:bg-slate-900/80 text-[10px] font-black uppercase tracking-wider text-slate-500 dark:text-slate-400">
                          <th className="py-3 px-4">Date</th>
                          <th className="py-3 px-3">Type</th>
                          <th className="py-3 px-3">Source Sheet / Report</th>
                          <th className="py-3 px-4">Narrative / Description</th>
                          <th className="py-3 px-3">Native Note</th>
                          <th className="py-3 px-4 text-right">USD Impact</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60 text-xs">
                        {filteredLines.length === 0 ? (
                          <tr>
                            <td colSpan={6} className="text-center py-12 text-slate-400 text-xs">
                              <Layers className="w-8 h-8 mx-auto mb-2 opacity-30 text-slate-400" />
                              No transactions found matching the current filter.
                            </td>
                          </tr>
                        ) : (
                          filteredLines.map((ln) => {
                            const isIncome = ln.amount_usd > 0;
                            const isExpense = ln.amount_usd < 0;
                            return (
                              <tr key={ln.id} className="hover:bg-slate-500/5 dark:hover:bg-slate-800/40 transition-colors">
                                <td className="py-3 px-4 font-mono text-[11px] font-semibold text-slate-600 dark:text-slate-300 tabular-nums whitespace-nowrap">
                                  {ln.line_date || '—'}
                                </td>
                                <td className="py-3 px-3 whitespace-nowrap">
                                  {isIncome ? (
                                    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-black uppercase tracking-wide bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border border-emerald-500/25 shrink-0 shadow-2xs">
                                      <ArrowDownLeft className="w-3.5 h-3.5 text-emerald-500 stroke-[2.5]" />
                                      <span>Income</span>
                                    </span>
                                  ) : isExpense ? (
                                    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-black uppercase tracking-wide bg-rose-500/10 text-rose-700 dark:text-rose-400 border border-rose-500/25 shrink-0 shadow-2xs">
                                      <ArrowUpRight className="w-3.5 h-3.5 text-rose-500 stroke-[2.5]" />
                                      <span>Expense</span>
                                    </span>
                                  ) : (
                                    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-black uppercase tracking-wide bg-purple-500/10 text-purple-700 dark:text-purple-400 border border-purple-500/25 shrink-0 shadow-2xs">
                                      <ArrowRightLeft className="w-3.5 h-3.5 text-purple-500 stroke-[2.5]" />
                                      <span>Adjustment</span>
                                    </span>
                                  )}
                                </td>
                                <td className="py-3 px-3 whitespace-nowrap">
                                  <span className="inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-bold bg-cyan-500/10 text-cyan-700 dark:text-cyan-300 border border-cyan-500/20 max-w-[220px] truncate" title={ln.source}>
                                    {ln.source}
                                  </span>
                                </td>
                                <td className="py-3 px-4 max-w-md">
                                  <div className="text-xs font-medium text-slate-800 dark:text-slate-200 leading-snug break-words" dir="auto">
                                    {ln.description || '—'}
                                  </div>
                                </td>
                                <td className="py-3 px-3 whitespace-nowrap">
                                  {ln.native_note && ln.native_note !== '—' ? (
                                    <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-mono font-medium bg-slate-100 dark:bg-slate-800/80 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700/60">
                                      {ln.native_note}
                                    </span>
                                  ) : (
                                    <span className="text-slate-400 text-xs">—</span>
                                  )}
                                </td>
                                <td className="py-3 px-4 text-right tabular-nums whitespace-nowrap">
                                  <span className={`inline-block font-mono font-extrabold text-xs px-2.5 py-1 rounded-lg border ${
                                    isIncome
                                      ? 'text-emerald-700 dark:text-emerald-400 bg-emerald-500/10 border-emerald-500/25'
                                      : isExpense
                                      ? 'text-rose-700 dark:text-rose-400 bg-rose-500/10 border-rose-500/25'
                                      : 'text-slate-600 dark:text-slate-400 bg-slate-500/10 border-slate-500/20'
                                  }`}>
                                    {formatMoney(ln.amount_usd, 'USD', { signed: true })}
                                  </span>
                                </td>
                              </tr>
                            );
                          })
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        </>
      )}

      {plannerFrom !== null && (
        <ReallocationPlanner pots={allPotsOptions} company={company} defaultFrom={plannerFrom} canApprove={can(user, 'expenses.transfers_approve', activeCompany) || user?.role === 'super_admin'} onClose={() => setPlannerFrom(null)} onDone={afterPlan} />
      )}
      {showNewPot && (
        <PotCreateForm company={company} onClose={() => setShowNewPot(false)} onDone={afterPlan}
          portfolios={(data.portfolios || []).map((p) => p.portfolio)} countries={(data.countries || []).map((c) => c.country)} />
      )}
    </div>
  );
}
