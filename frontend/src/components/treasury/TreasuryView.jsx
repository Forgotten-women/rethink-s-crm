import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Landmark, ArrowRightLeft, ShieldAlert, Search, LayoutGrid, List, RefreshCw, PlusCircle, X, Building2,
  CheckCircle2, AlertTriangle, ArrowUpRight, ArrowDownLeft, Download, Scale, FileSpreadsheet, Clock,
  History, PieChart, Pencil, Check, Equal, Minus, Plus, MoreHorizontal, Wallet,
} from 'lucide-react';
import { can } from '../../access';
import { REGION_FLAGS, accountTypeMeta, formatMoney } from './treasuryUtils';
import { FlowChart, BarList, MiniFlow, monthLabel } from './TreasuryCharts';
import {
  treasuryApi, treasuryExport, Pager, EmptyState, CorrectionsPanel, ConfirmPanel, SourcesPanel, ActivityPanel,
} from './TreasuryPanels';
import { TransferForm, EntryForm, BalanceForm, TrustForm, ReceivableForm, AccountForm } from './TreasuryForms';
import { CountryFlag } from './CountryFlag';
import { AccountCard } from './AccountCard';
import { ApprovalsPanel } from './ApprovalsPanel';
import PotsView from './PotsView';

const MONTH_OPTIONS = [
  { id: 'ALL', label: 'Jul – Oct 2026' },
  { id: '2026-10', label: 'October 2026' },
  { id: '2026-09', label: 'September 2026' },
  { id: '2026-08', label: 'August 2026' },
  { id: '2026-07', label: 'July 2026' },
];

const TYPE_FILTERS = [
  { id: 'ALL', label: 'All types' }, { id: 'bank', label: 'Banks' }, { id: 'cash_safe', label: 'Cash boxes' },
  { id: 'crypto', label: 'Crypto' }, { id: 'platform', label: 'Platforms' }, { id: 'reserve', label: 'Reserves' },
];

const STATUS_META = {
  counted: { label: 'Counted', badge: 'badge-emerald' },
  duplicate: { label: 'Duplicate', badge: 'badge-pink', hint: 'Also in a later month’s file — the close counts it there, not here.' },
  before_period: { label: 'Before 1 Jul', badge: 'badge-slate', hint: 'Dated before the period; already inside the 30 June opening balances.' },
};

function EquationTile({ label, value, sub, tone = '', onClick, op }) {
  return (
    <div className="flex items-stretch gap-2 min-w-0">
      {op && <div className="flex items-center text-slate-500 shrink-0" aria-hidden>{op}</div>}
      <button type="button" onClick={onClick} disabled={!onClick}
        className={`glass-panel p-4 text-left flex-1 min-w-0 ${onClick ? 'hover:border-cyan-400/50 cursor-pointer' : 'cursor-default'}`}>
        <div className="text-[11px] font-bold uppercase tracking-wider text-slate-400">{label}</div>
        <div className={`text-2xl font-extrabold tabular-nums mt-1 tracking-tight truncate ${tone}`}>{value}</div>
        {sub && <div className="text-[11px] text-slate-400 mt-1 truncate">{sub}</div>}
      </button>
    </div>
  );
}

export default function TreasuryView({ user, activeCompany = 'rethink' }) {
  const company = (activeCompany && activeCompany !== 'all' ? activeCompany : 'rethink').toLowerCase();
  const [fxMode, setFxMode] = useState('reconciled');
  const [displayCurrency, setDisplayCurrency] = useState('USD');
  const [month, setMonth] = useState('ALL');
  const [subTab, setSubTab] = useState('overview');
  const [initialPotCountry, setInitialPotCountry] = useState('ALL');
  const [flowBasis, setFlowBasis] = useState('fund');

  const [overview, setOverview] = useState(null);
  const [accounts, setAccounts] = useState([]);
  const [pots, setPots] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');

  const [regionFilter, setRegionFilter] = useState('ALL');
  const [typeFilter, setTypeFilter] = useState('ALL');
  const [search, setSearch] = useState('');
  const [viewMode, setViewMode] = useState('grid');

  const [selectedAccount, setSelectedAccount] = useState(null);
  const [statementData, setStatementData] = useState(null);
  const [statementLoading, setStatementLoading] = useState(false);
  const [stmtKind, setStmtKind] = useState('ALL');
  const [stmtStatus, setStmtStatus] = useState('counted');
  const [stmtSearch, setStmtSearch] = useState('');
  const [stmtPage, setStmtPage] = useState(1);

  const [transfersData, setTransfersData] = useState({ transfers: [], top_routes: [], aliases: [], total: 0, total_pages: 1, page: 1 });
  const [trPage, setTrPage] = useState(1);
  const [trSearch, setTrSearch] = useState('');

  const [modal, setModal] = useState(null); // {type, ...}
  const [menuFor, setMenuFor] = useState(null);
  const [toast, setToast] = useState(null);
  const [activityKey, setActivityKey] = useState(0);

  const canWrite = can(user, 'expenses.transfers', activeCompany) || can(user, 'expenses.submit', activeCompany);
  const canManage = can(user, 'expenses.transfers', activeCompany);
  const canExport = can(user, 'expenses.export', activeCompany);
  const canConfirm = can(user, 'expenses.approve', activeCompany) || canManage;
  const canApproveTransfers = can(user, 'expenses.transfers_approve', activeCompany) || user?.role === 'super_admin';
  const canApproveExpenses = can(user, 'expenses.approve', activeCompany) || user?.role === 'super_admin';
  const [pendingApprovalsCount, setPendingApprovalsCount] = useState(0);

  const showToast = (msg, type = 'success') => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 5000);
  };

  const fetchCoreData = useCallback(async () => {
    setLoading(true);
    setLoadError('');
    try {
      const params = { fx_mode: fxMode, display_currency: displayCurrency, ...(month !== 'ALL' ? { month } : {}) };
      const [ov, acc, pt] = await Promise.all([
        treasuryApi('/overview', { company, params }),
        treasuryApi('/accounts', { company, params }),
        treasuryApi('/pots', { company, params: { display_currency: displayCurrency } }),
      ]);
      setOverview(ov);
      setAccounts(acc.accounts || []);
      setPots(pt.pots || []);

      try {
        const apv = await treasuryApi('/approvals', { company, params: { status: 'PENDING' } });
        setPendingApprovalsCount(apv?.counts?.pending || 0);
      } catch { /* ignore */ }
    } catch (e) {
      setLoadError(e.message);
    } finally {
      setLoading(false);
    }
  }, [company, fxMode, displayCurrency, month]);

  useEffect(() => { fetchCoreData(); }, [fetchCoreData]);

  const fetchTransfers = useCallback(async () => {
    try {
      setTransfersData(await treasuryApi('/internal-transfers', { company, params: { page: trPage, page_size: 25, ...(month !== 'ALL' ? { month } : {}), search: trSearch.trim() } }));
    } catch (e) { console.error(e); }
  }, [company, trPage, month, trSearch]);
  useEffect(() => { if (subTab === 'transfers') fetchTransfers(); }, [subTab, fetchTransfers]);

  const fetchStatement = useCallback(async () => {
    if (!selectedAccount) return;
    setStatementLoading(true);
    try {
      setStatementData(await treasuryApi(`/accounts/${encodeURIComponent(selectedAccount.id)}/transactions`, {
        company, params: { page: stmtPage, page_size: 30, status: stmtStatus, ...(stmtKind !== 'ALL' ? { kind: stmtKind } : {}), ...(month !== 'ALL' ? { month } : {}), search: stmtSearch.trim() },
      }));
    } catch (e) { console.error(e); } finally { setStatementLoading(false); }
  }, [company, selectedAccount, stmtPage, stmtKind, stmtStatus, stmtSearch, month]);
  useEffect(() => { fetchStatement(); }, [fetchStatement]);

  const openAccount = (acc) => {
    const a = typeof acc === 'string' ? accounts.find((x) => x.id === acc) : acc;
    if (!a) return;
    setSelectedAccount(a); setStmtPage(1); setStmtKind('ALL'); setStmtStatus('counted'); setStmtSearch('');
  };

  const afterWrite = (msg) => {
    setModal(null);
    showToast(msg);
    fetchCoreData();
    if (subTab === 'transfers') fetchTransfers();
    if (selectedAccount) fetchStatement();
    setActivityKey((k) => k + 1);
  };

  // keep the open drawer's account in sync with fresh balances
  useEffect(() => {
    if (selectedAccount) {
      const fresh = accounts.find((a) => a.id === selectedAccount.id);
      if (fresh && fresh.current_balance_native !== selectedAccount.current_balance_native) setSelectedAccount(fresh);
    }
  }, [accounts]); // eslint-disable-line react-hooks/exhaustive-deps

  const settle = async (kind, item) => {
    const what = kind === 'trust' ? `the amanah for ${item.holder}` : item.name;
    if (!window.confirm(`Mark ${what} as ${kind === 'trust' ? 'handed over' : 'received / cleared'}? It leaves the totals (you can reverse it from Activity).`)) return;

    let recordWithdrawal = false;
    if (kind === 'trust' && item.account_id) {
      const acc = accounts.find((a) => a.id === item.account_id);
      const accName = acc?.name || item.account_id;
      recordWithdrawal = window.confirm(
        `Did physical cash leave ${accName}?\n\n` +
        `• Click OK to record a cash withdrawal (-${formatMoney(item.native_amount, item.currency)}) from ${accName} and add a statement ledger line.\n` +
        `• Click CANCEL to only remove the amanah tag without deducting cash from the account balance.`
      );
    }

    try {
      const url = `/${kind === 'trust' ? 'trusts' : 'receivables'}/${item.id}/settle${recordWithdrawal ? '?record_withdrawal=true' : ''}`;
      const d = await treasuryApi(url, { method: 'POST', company });
      afterWrite(`${kind === 'trust' ? (recordWithdrawal ? 'Amanah handed over & cash withdrawn' : 'Amanah handed over') : 'Receivable cleared'} (#${d.activity_id})`);
    } catch (e) { showToast(e.message, 'error'); }
  };

  const filteredAccounts = useMemo(() => {
    const q = search.trim().toLowerCase();
    return accounts.filter((a) => {
      if (regionFilter !== 'ALL' && a.group_name !== regionFilter) return false;
      if (typeFilter !== 'ALL' && a.account_type !== typeFilter) return false;
      if (!q) return true;
      return [a.name, a.name_ar, a.holder, a.currency, a.group_name].some((v) => (v || '').toLowerCase().includes(q));
    });
  }, [accounts, regionFilter, typeFilter, search]);

  const eq = overview?.equation || {};
  const fx = overview?.fx || {};
  const rates = fx.rates || {};
  const health = overview?.health || {};
  const disp = displayCurrency;

  const isAccountsFiltered = regionFilter !== 'ALL' || typeFilter !== 'ALL' || Boolean(search.trim());

  const filteredAccountsCash = useMemo(() => {
    return filteredAccounts.reduce((s, a) => s + (a.active_display || 0), 0);
  }, [filteredAccounts]);

  const filteredAccountsAmanah = useMemo(() => {
    return filteredAccounts.reduce((s, a) => {
      if (a.amanah_display != null) return s + a.amanah_display;
      const usd = a.amanah_usd || 0;
      return s + (disp === 'USD' ? usd : usd * (rates['GBP'] || 0.75));
    }, 0);
  }, [filteredAccounts, disp, rates]);

  const filteredAccountsSpendable = filteredAccountsCash - filteredAccountsAmanah;

  const filteredInflows = useMemo(() => {
    return filteredAccounts.reduce((s, a) => s + (a.inflow_display != null ? a.inflow_display : (a.inflow_usd || 0)), 0);
  }, [filteredAccounts]);

  const filteredOutflows = useMemo(() => {
    return filteredAccounts.reduce((s, a) => s + (a.outflow_display != null ? a.outflow_display : (a.outflow_usd || 0)), 0);
  }, [filteredAccounts]);

  const filteredTxCount = useMemo(() => {
    return filteredAccounts.reduce((s, a) => s + (a.tx_count || 0), 0);
  }, [filteredAccounts]);

  // Dynamic region totals based on active typeFilter & search
  const dynamicRegionTotals = useMemo(() => {
    const map = {};
    accounts.forEach((a) => {
      if (typeFilter !== 'ALL' && a.account_type !== typeFilter) return;
      if (search.trim()) {
        const q = search.trim().toLowerCase();
        if (![a.name, a.name_ar, a.holder, a.currency, a.group_name].some((v) => (v || '').toLowerCase().includes(q))) return;
      }
      map[a.group_name] = (map[a.group_name] || 0) + (a.active_display || 0);
    });
    return map;
  }, [accounts, typeFilter, search]);

  const allRegionsCashForType = useMemo(() => {
    return accounts.reduce((s, a) => {
      if (typeFilter !== 'ALL' && a.account_type !== typeFilter) return s;
      if (search.trim()) {
        const q = search.trim().toLowerCase();
        if (![a.name, a.name_ar, a.holder, a.currency, a.group_name].some((v) => (v || '').toLowerCase().includes(q))) return s;
      }
      return s + (a.active_display || 0);
    }, 0);
  }, [accounts, typeFilter, search]);

  // Dynamic type totals based on active regionFilter & search
  const dynamicTypeTotals = useMemo(() => {
    const map = {};
    accounts.forEach((a) => {
      if (regionFilter !== 'ALL' && a.group_name !== regionFilter) return;
      if (search.trim()) {
        const q = search.trim().toLowerCase();
        if (![a.name, a.name_ar, a.holder, a.currency, a.group_name].some((v) => (v || '').toLowerCase().includes(q))) return;
      }
      map[a.account_type] = (map[a.account_type] || 0) + (a.active_display || 0);
    });
    return map;
  }, [accounts, regionFilter, search]);

  const regions = useMemo(() => [...new Set(accounts.map((a) => a.group_name))], [accounts]);
  const regionTotals = useMemo(() => {
    const map = {};
    (accounts || []).forEach((a) => {
      map[a.group_name] = (map[a.group_name] || 0) + (a.active_usd || 0);
    });
    return map;
  }, [accounts]);

  const flowData = useMemo(() => {
    if (flowBasis === 'fund') {
      return (overview?.fund_flow || []).map((m) => ({ month: m.month, inc: m.income_display, out: m.expense_display }));
    }
    return (overview?.monthly_flow || []).filter((m) => m.month >= '2026-07').map((m) => ({ month: m.month, inc: m.income_display, out: m.expense_display }));
  }, [overview, flowBasis]);
  const flowTotals = flowData.reduce((s, d) => ({ inc: s.inc + d.inc, out: s.out + d.out }), { inc: 0, out: 0 });

  const TABS = [
    { id: 'overview', label: 'Overview', icon: PieChart },
    { id: 'accounts', label: `Accounts (${accounts.length})`, icon: Building2 },
    { id: 'pots', label: `Pots (${pots.length || 274})`, icon: Wallet },
    { id: 'transfers', label: 'Transfers', icon: ArrowRightLeft },
    { id: 'approvals', label: 'Approvals', icon: CheckCircle2, badge: pendingApprovalsCount },
    { id: 'trusts', label: 'Held & owed', icon: ShieldAlert },
    { id: 'corrections', label: 'Corrections', icon: FileSpreadsheet },
    { id: 'confirm', label: 'To confirm', icon: AlertTriangle, badge: health.open_confirm_count },
    { id: 'sources', label: 'Sources', icon: Clock },
    { id: 'activity', label: 'Activity', icon: History },
  ];

  return (
    <div className="space-y-5 pb-12 panel-pop">
      {toast && (
        <div role="status" className={`fixed bottom-6 right-6 z-[60] px-5 py-3.5 rounded-xl shadow-2xl border flex items-center gap-3 keep-white ${toast.type === 'error' ? 'bg-rose-600 border-rose-400' : 'bg-emerald-600 border-emerald-400'}`}>
          {toast.type === 'error' ? <ShieldAlert className="w-5 h-5" /> : <CheckCircle2 className="w-5 h-5" />}
          <span className="font-semibold text-sm">{toast.msg}</span>
        </div>
      )}

      {/* Header */}
      <div className="glass-panel p-5">
        <div className="flex flex-col xl:flex-row xl:items-center xl:justify-between gap-4">
          <div className="flex items-start gap-4">
            <div className="w-11 h-11 rounded-2xl bg-gradient-to-br from-cyan-500 to-blue-600 flex items-center justify-center shrink-0 keep-white"><Landmark className="w-5 h-5" /></div>
            <div>
              <h1 className="text-2xl font-bold tracking-tight">Treasury &amp; Banks</h1>
              <p className="text-sm text-slate-400 mt-0.5">
                Where the money is — {accounts.length} banks, cash boxes, wallets and platform balances · baseline: 31 Oct 2026 close
                {health.latest_source_date ? ` · sources to ${health.latest_source_date}` : ''}
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex rounded-xl p-1 border border-slate-700/60 bg-slate-900/40" role="group" aria-label="Display currency">
              {['USD', 'GBP'].map((c) => (
                <button type="button" key={c} onClick={() => setDisplayCurrency(c)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-bold ${displayCurrency === c ? 'bg-blue-600 keep-white' : 'text-slate-400 hover:text-slate-200'}`}>{c}</button>
              ))}
            </div>
            <div className="flex rounded-xl p-1 border border-slate-700/60 bg-slate-900/40" role="group" aria-label="Exchange rates">
              <button type="button" onClick={() => setFxMode('reconciled')} title="The rates used in the monthly close (GBP 1.33, TL 0.02001, EUR 1.12315, ZAR 0.05981)"
                className={`px-3 py-1.5 rounded-lg text-xs font-bold ${fxMode === 'reconciled' ? 'bg-blue-600 keep-white' : 'text-slate-400 hover:text-slate-200'}`}>Close rates</button>
              <button type="button" onClick={() => setFxMode('live')} title="Today's ECB mid-market rates — shows what the same native balances are worth now"
                className={`px-3 py-1.5 rounded-lg text-xs font-bold ${fxMode === 'live' ? 'bg-blue-600 keep-white' : 'text-slate-400 hover:text-slate-200'}`}>Today&apos;s rates</button>
            </div>
            <select value={month} onChange={(e) => setMonth(e.target.value)} className="px-3 py-2 rounded-xl border text-xs font-semibold" aria-label="Period">
              {MONTH_OPTIONS.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
            </select>
            {canWrite && (
              <>
                <button type="button" onClick={() => setModal({ type: 'transfer' })} className="btn-primary text-xs flex items-center gap-1.5 keep-white"><ArrowRightLeft className="w-3.5 h-3.5" /> Move money</button>
                <button type="button" onClick={() => setModal({ type: 'entry' })} className="btn-secondary text-xs flex items-center gap-1.5"><PlusCircle className="w-3.5 h-3.5" /> Record entry</button>
              </>
            )}
            <button type="button" onClick={fetchCoreData} title="Refresh" aria-label="Refresh" className="p-2 rounded-xl border border-slate-700/60 hover:border-cyan-400/60">
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin text-cyan-400' : 'text-slate-400'}`} />
            </button>
          </div>
        </div>
        <div className="mt-3 pt-3 border-t border-slate-700/30 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-slate-400 tabular-nums">
          <span className="font-semibold uppercase tracking-wider">{fx.source || 'Rates'} · {fx.as_of || ''}</span>
          {[['GBP', 4], ['EUR', 4], ['TRY', 5], ['ZAR', 5], ['EGP', 4]].map(([c, d]) => (
            <span key={c}>1 {c} = <strong className="text-slate-200">${Number(rates[c] || 0).toFixed(d)}</strong></span>
          ))}
        </div>
      </div>

      {loadError && <div className="glass-panel p-4 text-sm text-rose-400 flex items-center gap-2"><AlertTriangle className="w-4 h-4" /> {loadError}</div>}

      {/* The equation: cash − held for others + owed to us = fund balances */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-[1fr_1fr_1fr_1.15fr] gap-3">
        <EquationTile
          label={subTab === 'accounts' && isAccountsFiltered ? 'Cash in shown accounts' : 'Cash in accounts'}
          value={formatMoney(subTab === 'accounts' && isAccountsFiltered ? filteredAccountsCash : eq.gross_cash_display, disp)}
          sub={subTab === 'accounts' && isAccountsFiltered
            ? `${filteredAccounts.length} of ${accounts.length} accounts shown (${regionFilter !== 'ALL' ? regionFilter : 'All'}${typeFilter !== 'ALL' ? ` · ${accountTypeMeta(typeFilter).label}` : ''})`
            : `${accounts.length} accounts — click to view all`}
          onClick={() => setSubTab('accounts')}
        />
        <EquationTile
          op={<Minus className="w-4 h-4" />}
          label={subTab === 'accounts' && isAccountsFiltered ? 'Held in shown accounts' : 'Held for others'}
          value={formatMoney(subTab === 'accounts' && isAccountsFiltered ? filteredAccountsAmanah : eq.trust_amanahs_display, disp)}
          sub={subTab === 'accounts' && isAccountsFiltered
            ? `${filteredAccounts.filter((a) => (a.amanah_usd || 0) > 0).length} accounts holding amanahs (${formatMoney(filteredAccountsAmanah, disp)})`
            : `${(eq.trust_items || []).length} amanahs — not ours to spend`}
          onClick={() => setSubTab('trusts')}
        />
        <EquationTile
          op={<Plus className="w-4 h-4" />}
          label="Owed to us"
          value={formatMoney(eq.receivables_display, disp)}
          sub={`One Nation, advances, amanah receivable`}
          onClick={() => setSubTab('trusts')}
        />
        <div className="flex items-stretch gap-2 min-w-0">
          <div className="flex items-center text-slate-500 shrink-0" aria-hidden><Equal className="w-4 h-4" /></div>
          <button
            type="button"
            onClick={() => { setInitialPotCountry('ALL'); setSubTab('pots'); }}
            className={`glass-panel p-4 flex-1 min-w-0 text-left hover:border-purple-400/50 cursor-pointer ${
              subTab === 'accounts' && isAccountsFiltered ? 'border-cyan' : eq.ties ? 'border-emerald' : 'border-amber'
            }`}
          >
            <div className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
              {subTab === 'accounts' && isAccountsFiltered ? 'Spendable in shown accounts' : `Fund balances (${pots.length || 274} pots)`}
            </div>
            <div className="text-2xl font-extrabold tabular-nums mt-1 tracking-tight">
              {formatMoney(subTab === 'accounts' && isAccountsFiltered ? filteredAccountsSpendable : eq.pots_total_balance_display, disp)}
            </div>
            <div className={`text-[11px] mt-1 flex items-center gap-1 ${
              subTab === 'accounts' && isAccountsFiltered ? 'text-cyan-400' : eq.ties ? 'text-emerald-400' : 'text-amber-400'
            }`}>
              {subTab === 'accounts' && isAccountsFiltered
                ? <><Check className="w-3.5 h-3.5" /> Net spendable cash after deducting amanahs</>
                : eq.ties
                  ? <><Check className="w-3.5 h-3.5" /> Ties to cash − held + owed · click to open pots</>
                  : <><AlertTriangle className="w-3.5 h-3.5" /> Off by {formatMoney(eq.gap_display, disp, { signed: true })} · click to open pots</>}
            </div>
          </button>
        </div>
      </div>
      {fxMode === 'live' && <div className="text-[11px] text-amber-400 -mt-2">Today&apos;s rates revalue cash but the pots stay at close rates, so the tie-out shows the FX movement since 31 Oct.</div>}

      {/* Health chips */}
      <div className="flex flex-wrap gap-2 text-xs">
        {health.open_confirm_count > 0 && (
          <button type="button" onClick={() => setSubTab('confirm')} className="px-3 py-1.5 rounded-full border border-amber-500/40 bg-amber-500/10 text-amber-400 flex items-center gap-1.5">
            <AlertTriangle className="w-3.5 h-3.5" /> {health.open_confirm_count} lines waiting for confirmation · {formatMoney(health.open_confirm_usd, 'USD', { compact: true })}
          </button>
        )}
        {health.duplicate_rows > 0 && (
          <span className="px-3 py-1.5 rounded-full border border-slate-700/60 text-slate-400 flex items-center gap-1.5" title="Lines that appear in two monthly files are counted once (in the later file). They are hidden from statements unless you ask for them.">
            <CheckCircle2 className="w-3.5 h-3.5" /> {health.duplicate_rows} duplicate lines and {health.before_period_rows} pre-July lines excluded from totals
          </span>
        )}
        {health.future_dated_rows > 0 && (
          <span className="px-3 py-1.5 rounded-full border border-rose-500/40 bg-rose-500/10 text-rose-400 flex items-center gap-1.5"><AlertTriangle className="w-3.5 h-3.5" /> {health.future_dated_rows} line dated in the future (date typo in a source sheet)</span>
        )}
      </div>

      {/* Tabs */}
      <div className="flex flex-wrap items-center gap-1.5 border-b border-slate-700/40 pb-2" role="tablist">
        {TABS.map((t) => (
          <button type="button" role="tab" aria-selected={subTab === t.id} key={t.id} onClick={() => setSubTab(t.id)}
            className={`px-3.5 py-2 rounded-xl text-sm font-bold flex items-center gap-2 transition-colors ${subTab === t.id ? 'bg-blue-600 keep-white shadow' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/40'}`}>
            <t.icon className="w-4 h-4" /> {t.label}
            {t.badge > 0 && <span className={`text-[10px] px-1.5 rounded-full ${subTab === t.id ? 'bg-white/25' : 'bg-amber-500/20 text-amber-400'}`}>{t.badge}</span>}
          </button>
        ))}
      </div>

      {/* OVERVIEW */}
      {subTab === 'overview' && (
        <div className="grid grid-cols-1 xl:grid-cols-5 gap-5">
          <div className="glass-panel p-5 xl:col-span-3 space-y-3">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="font-bold">Money in and out by month</h2>
                <p className="text-xs text-slate-400 mt-0.5">
                  {flowBasis === 'fund'
                    ? 'As the fund position books it: bank & cash sheets, Syria field reports and approved corrections.'
                    : 'Bank & cash sheets only (counted lines). Syria field spend and corrections are not in here.'}
                </p>
              </div>
              <div className="flex rounded-lg p-0.5 border border-slate-700/60 text-[11px] font-bold" role="group" aria-label="Basis">
                <button type="button" onClick={() => setFlowBasis('fund')} className={`px-2.5 py-1 rounded-md ${flowBasis === 'fund' ? 'bg-blue-600 keep-white' : 'text-slate-400'}`}>Fund position</button>
                <button type="button" onClick={() => setFlowBasis('ledger')} className={`px-2.5 py-1 rounded-md ${flowBasis === 'ledger' ? 'bg-blue-600 keep-white' : 'text-slate-400'}`}>Bank ledger</button>
              </div>
            </div>
            <div className="flex gap-6 text-sm tabular-nums">
              <div><div className="text-[11px] text-slate-400">In</div><div className="font-bold">{formatMoney(flowTotals.inc, disp)}</div></div>
              <div><div className="text-[11px] text-slate-400">Out</div><div className="font-bold">{formatMoney(flowTotals.out, disp)}</div></div>
              <div><div className="text-[11px] text-slate-400">Net</div><div className="font-bold">{formatMoney(flowTotals.inc - flowTotals.out, disp, { signed: true })}</div></div>
            </div>
            {flowData.length ? <FlowChart data={flowData} currency={disp} inLabel="Income" outLabel="Spending" /> : <EmptyState title="No monthly data" />}
          </div>

          <div className="glass-panel p-5 xl:col-span-2 space-y-3">
            <div>
              <h2 className="font-bold">Cash by region</h2>
              <p className="text-xs text-slate-400 mt-0.5">Click a region to see its accounts.</p>
            </div>
            <BarList currency={disp}
              rows={(overview?.by_region || []).map((r) => ({ key: r.region, label: `${REGION_FLAGS[r.region] || ''} ${r.region}`, value: r.display_total, sub: `${r.accounts_count} accounts` }))}
              onSelect={(k) => { setRegionFilter(k); setTypeFilter('ALL'); setSubTab('accounts'); }} />
            <div className="pt-3 border-t border-slate-700/30">
              <h3 className="text-sm font-bold mb-2">By currency held</h3>
              <div className="grid grid-cols-2 gap-2">
                {(overview?.by_currency || []).map((c) => (
                  <div key={c.currency} className="p-2.5 rounded-lg bg-slate-900/40 border border-slate-700/30 text-xs">
                    <div className="flex justify-between"><span className="font-bold">{c.currency}</span><span className="text-slate-400">{c.accounts_count} acc.</span></div>
                    <div className="tabular-nums font-semibold mt-0.5">{formatMoney(c.native_total, c.currency, { compact: true })}</div>
                    <div className="tabular-nums text-slate-400">{formatMoney(c.display_total, disp, { compact: true })}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="glass-panel p-5 xl:col-span-5 space-y-3">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <h2 className="font-bold">Fund balances by country</h2>
                <p className="text-xs text-slate-400 mt-0.5">What the pots say each country&apos;s projects have left (negative = spent ahead of income, covered by other funds). Click any country to open its pots.</p>
              </div>
              <button
                type="button"
                onClick={() => { setInitialPotCountry('ALL'); setSubTab('pots'); }}
                className="btn-secondary text-xs flex items-center gap-1.5"
              >
                <Wallet className="w-3.5 h-3.5" /> View all {pots.length || 274} Pots →
              </button>
            </div>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-x-8">
              <BarList currency={disp} maxRows={20}
                rows={(overview?.fund_by_country || []).map((r) => ({ key: r.country, label: `${REGION_FLAGS[r.country] || ''} ${r.country}`, value: r.display_total }))}
                onSelect={(country) => { setInitialPotCountry(country); setSubTab('pots'); }} />
            </div>
          </div>
        </div>
      )}

      {/* ACCOUNTS */}
      {subTab === 'accounts' && (
        <div className="space-y-4">
          <div className="glass-panel p-4 space-y-3">
            <div className="flex flex-wrap items-center gap-1.5">
              <button
                type="button"
                onClick={() => setRegionFilter('ALL')}
                className={`px-3 py-1.5 rounded-xl text-xs font-bold flex items-center gap-1.5 transition-all ${
                  regionFilter === 'ALL'
                    ? 'bg-blue-600 keep-white shadow-md shadow-blue-500/20'
                    : 'bg-slate-800/40 text-slate-400 hover:text-slate-200 border border-slate-700/50'
                }`}
              >
                <span>🌐</span>
                <span>All regions · {formatMoney(allRegionsCashForType, disp, { compact: true })}</span>
              </button>
              {(overview?.by_region || []).map((r) => {
                const regAmt = dynamicRegionTotals[r.region] || 0;
                return (
                  <button
                    type="button"
                    key={r.region}
                    onClick={() => setRegionFilter(regionFilter === r.region ? 'ALL' : r.region)}
                    className={`px-3 py-1.5 rounded-xl text-xs font-bold tabular-nums flex items-center gap-1.5 transition-all ${
                      regionFilter === r.region
                        ? 'bg-blue-600 keep-white shadow-md shadow-blue-500/20'
                        : regAmt > 0
                          ? 'bg-slate-800/40 text-slate-400 hover:text-slate-200 border border-slate-700/50'
                          : 'bg-slate-900/30 text-slate-600 border border-slate-800/40 opacity-60'
                    }`}
                  >
                    <CountryFlag country={r.region} className="w-4 h-3 rounded-xs" />
                    <span>{r.region} · {formatMoney(regAmt, disp, { compact: true })}</span>
                  </button>
                );
              })}
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-slate-700/30">
              <div className="flex flex-wrap items-center gap-1.5">
                {TYPE_FILTERS.map((t) => {
                  const tAmt = t.id === 'ALL' ? filteredAccountsCash : (dynamicTypeTotals[t.id] || 0);
                  return (
                    <button
                      type="button"
                      key={t.id}
                      onClick={() => setTypeFilter(t.id)}
                      className={`px-2.5 py-1 rounded-md text-xs font-semibold flex items-center gap-1 transition-all ${
                        typeFilter === t.id ? 'badge-cyan font-bold' : 'text-slate-400 hover:text-slate-200'
                      }`}
                    >
                      <span>{t.label}</span>
                      {tAmt > 0 && <span className="opacity-75 text-[10px]">· {formatMoney(tAmt, disp, { compact: true })}</span>}
                    </button>
                  );
                })}
              </div>
              <div className="flex items-center gap-2">
                <div className="relative">
                  <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                  <input
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Account, holder, currency, Arabic name…"
                    aria-label="Search accounts"
                    className="pl-8 pr-3 py-1.5 rounded-lg border text-xs w-64"
                  />
                </div>
                <div className="flex rounded-lg border border-slate-700/50 p-0.5">
                  <button
                    type="button"
                    onClick={() => setViewMode('grid')}
                    aria-label="Cards"
                    className={`p-1.5 rounded-md ${viewMode === 'grid' ? 'bg-blue-600 keep-white' : 'text-slate-400'}`}
                  >
                    <LayoutGrid className="w-3.5 h-3.5" />
                  </button>
                  <button
                    type="button"
                    onClick={() => setViewMode('table')}
                    aria-label="Table"
                    className={`p-1.5 rounded-md ${viewMode === 'table' ? 'bg-blue-600 keep-white' : 'text-slate-400'}`}
                  >
                    <List className="w-3.5 h-3.5" />
                  </button>
                </div>
                {canExport && (
                  <button
                    type="button"
                    onClick={() => treasuryExport('/accounts/export', company, { fx_mode: fxMode, region: regionFilter, account_type: typeFilter, search })}
                    className="btn-secondary text-xs flex items-center gap-1.5"
                  >
                    <Download className="w-3.5 h-3.5" /> CSV
                  </button>
                )}
                {canManage && (
                  <button
                    type="button"
                    onClick={() => setModal({ type: 'account' })}
                    className="btn-secondary text-xs flex items-center gap-1.5"
                  >
                    <PlusCircle className="w-3.5 h-3.5" /> Account
                  </button>
                )}
              </div>
            </div>

            {/* Dynamic KPI Cards Strip for Accounts */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 pt-3 border-t border-slate-700/30">
              <div className="p-3 rounded-xl border border-blue-500/30 bg-blue-500/10 backdrop-blur-sm">
                <div className="text-[10px] font-bold uppercase tracking-wider text-blue-400">Cash in Shown Accounts</div>
                <div className="text-xl font-extrabold tabular-nums mt-0.5 text-slate-100">{formatMoney(filteredAccountsCash, disp)}</div>
                <div className="text-[10px] text-slate-400 mt-0.5">{filteredAccounts.length} of {accounts.length} accounts shown</div>
              </div>

              <div className="p-3 rounded-xl border border-amber-500/30 bg-amber-500/10 backdrop-blur-sm">
                <div className="text-[10px] font-bold uppercase tracking-wider text-amber-400">Held for Others (Amanah)</div>
                <div className="text-xl font-extrabold tabular-nums mt-0.5 text-amber-400">{formatMoney(filteredAccountsAmanah, disp)}</div>
                <div className="text-[10px] text-slate-400 mt-0.5">{filteredAccounts.filter((a) => (a.amanah_usd || 0) > 0).length} accounts with amanahs</div>
              </div>

              <div className="p-3 rounded-xl border border-emerald-500/30 bg-emerald-500/10 backdrop-blur-sm">
                <div className="text-[10px] font-bold uppercase tracking-wider text-emerald-400">Net Spendable Cash</div>
                <div className="text-xl font-extrabold tabular-nums mt-0.5 text-emerald-400">{formatMoney(filteredAccountsSpendable, disp)}</div>
                <div className="text-[10px] text-slate-400 mt-0.5">Cash minus money held for others</div>
              </div>

              <div className="p-3 rounded-xl border border-purple-500/30 bg-purple-500/10 backdrop-blur-sm">
                <div className="text-[10px] font-bold uppercase tracking-wider text-purple-400">Period Recorded Flow</div>
                <div className="text-xl font-extrabold tabular-nums mt-0.5 text-slate-100">
                  <span className="text-emerald-400">+{formatMoney(filteredInflows, disp, { compact: true })}</span>
                  <span className="text-slate-500 mx-1">/</span>
                  <span className="text-rose-400">−{formatMoney(filteredOutflows, disp, { compact: true })}</span>
                </div>
                <div className="text-[10px] text-slate-400 mt-0.5">{filteredTxCount} recorded transaction lines</div>
              </div>
            </div>
          </div>

          {!filteredAccounts.length && <EmptyState icon={Search} title="No accounts match" text="Clear the filters or search." />}

          {viewMode === 'grid' ? (
            <div className="grid grid-cols-1 md:grid-cols-2 2xl:grid-cols-3 gap-4">
              {filteredAccounts.map((acc) => (
                <AccountCard
                  key={acc.id}
                  acc={acc}
                  disp={disp}
                  canWrite={canWrite}
                  canManage={canManage}
                  regionTotalUsd={regionTotals[acc.group_name]}
                  onOpenAccount={openAccount}
                  onMoveMoney={(accId) => setModal({ type: 'transfer', from: accId })}
                  onRecordEntry={(accId) => setModal({ type: 'entry', account: accId })}
                  onUpdateBalance={(accObj) => setModal({ type: 'balance', account: accObj })}
                />
              ))}
            </div>) : (
            <div className="glass-panel overflow-x-auto">
              <table className="crm-table">
                <thead><tr><th>Account</th><th>Region</th><th>Type</th><th className="text-right">Balance</th><th className="text-right">{disp}</th><th>As of</th><th className="text-right">Lines</th></tr></thead>
                <tbody>
                  {filteredAccounts.map((acc) => (
                    <tr key={acc.id} onClick={() => openAccount(acc)} className="cursor-pointer hover:bg-slate-800/40">
                      <td>
                        <div className="font-bold flex items-center gap-2">
                          <CountryFlag country={acc.group_name} className="w-4 h-3 rounded-xs shrink-0" />
                          <span>{acc.name}</span>
                        </div>
                        <div className="text-xs text-slate-400">{acc.holder}{acc.amanah_usd > 0 ? ` · ${formatMoney(acc.amanah_usd, 'USD')} held for others` : ''}</div>
                      </td>
                      <td className="text-xs">
                        <div className="flex items-center gap-1.5">
                          <CountryFlag country={acc.group_name} className="w-3.5 h-2.5 rounded-xs shrink-0" />
                          <span>{acc.group_name}</span>
                        </div>
                      </td>
                      <td><span className={`badge ${accountTypeMeta(acc.account_type).badge} text-[10px]`}>{accountTypeMeta(acc.account_type).label}</span></td>
                      <td className={`text-right font-bold tabular-nums ${acc.current_balance_native < -0.01 ? 'text-rose-400' : ''}`}>{formatMoney(acc.current_balance_native, acc.currency)}</td>
                      <td className="text-right tabular-nums">{formatMoney(acc.active_display, disp)}</td>
                      <td className="text-xs text-slate-400 whitespace-nowrap">{acc.balance_as_of}</td>
                      <td className="text-right text-xs tabular-nums">{acc.tx_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* TRANSFERS */}
      {subTab === 'transfers' && (
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
          <div className="xl:col-span-2 glass-panel p-5 space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-bold">Movements between our own accounts</h2>
                <p className="text-xs text-slate-400">{transfersData.total} lines — internal moves are neither income nor spending, so they never touch the pots.</p>
              </div>
              <div className="flex items-center gap-2">
                <div className="relative">
                  <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                  <input value={trSearch} onChange={(e) => { setTrSearch(e.target.value); setTrPage(1); }} placeholder="Account, reference, category…" aria-label="Search transfers" className="pl-8 pr-3 py-1.5 rounded-lg border text-xs w-60" />
                </div>
                {canWrite && <button type="button" onClick={() => setModal({ type: 'transfer' })} className="btn-primary text-xs keep-white flex items-center gap-1.5"><ArrowRightLeft className="w-3.5 h-3.5" /> Move money</button>}
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="crm-table">
                <thead><tr><th>Date</th><th>Account</th><th>Other side</th><th className="text-right">Amount</th><th className="text-right">USD</th><th>Reference</th></tr></thead>
                <tbody>
                  {transfersData.transfers.map((t) => (
                    <tr key={t.id}>
                      <td className="tabular-nums whitespace-nowrap">{t.tx_date || 'Undated'}</td>
                      <td className="font-semibold text-xs">{t.account_name || t.account_id}</td>
                      <td className="text-xs">{t.counterparty_name || t.category || 'FX / internal'}</td>
                      <td className="text-right font-bold tabular-nums whitespace-nowrap">{formatMoney(t.amount_native, t.currency, { signed: true })}</td>
                      <td className="text-right tabular-nums text-slate-400 whitespace-nowrap">{formatMoney(t.amount_usd, 'USD', { signed: true })}</td>
                      <td className="text-xs text-slate-400 max-w-xs truncate" title={t.description}>{t.description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager page={transfersData.page} totalPages={transfersData.total_pages} total={transfersData.total} onPage={setTrPage} />
          </div>
          <div className="space-y-5">
            <div className="glass-panel p-5">
              <h3 className="font-bold text-sm mb-1">Busiest routes</h3>
              <p className="text-[11px] text-slate-400 mb-3">Total moved Jul–Oct, both directions.</p>
              <BarList currency="USD" maxRows={8}
                rows={(transfersData.top_routes || []).map((r, i) => ({ key: `${i}`, label: `${r.source_name} → ${r.target_name}`, value: r.total_usd, sub: `${r.tx_count} lines`, hint: `${r.source_name} → ${r.target_name}` }))} />
            </div>
            <div className="glass-panel p-5">
              <h3 className="font-bold text-sm mb-1">How sheet categories map to accounts</h3>
              <p className="text-[11px] text-slate-400 mb-3">A line whose category is one of these names is an internal move to that account.</p>
              <div className="max-h-72 overflow-y-auto custom-scrollbar space-y-1">
                {(transfersData.aliases || []).map((al) => (
                  <div key={al.alias} className="flex items-center justify-between text-xs py-1 border-b border-slate-700/20">
                    <span className="font-mono">{al.alias}</span><span className="text-slate-400">{al.account_name} ({al.currency})</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* HELD & OWED */}
      {subTab === 'trusts' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
          <div className="glass-panel p-5 space-y-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="text-lg font-bold">Held for others (amanahs)</h2>
                <p className="text-xs text-slate-400 mt-0.5">Cash in our accounts that belongs to partners or individuals; deducted from what we can spend.</p>
              </div>
              <div className="text-right shrink-0">
                <div className="text-xl font-extrabold tabular-nums">{formatMoney(eq.trust_amanahs_display, disp)}</div>
                {canManage && <button type="button" onClick={() => setModal({ type: 'trust' })} className="text-xs text-cyan-400 hover:underline flex items-center gap-1 ml-auto mt-1"><PlusCircle className="w-3.5 h-3.5" /> Add</button>}
              </div>
            </div>
            {!(eq.trust_items || []).length && <EmptyState title="Nothing held for others" />}
            {(eq.trust_items || []).map((t) => (
              <div key={t.id} className="p-3.5 rounded-xl bg-slate-900/40 border border-slate-700/40 flex items-start justify-between gap-3">
                <div className="text-xs min-w-0">
                  <div className="font-bold text-sm">{t.holder}</div>
                  <div className="text-slate-400 mt-0.5">{t.note}</div>
                  {t.account_id && <button type="button" onClick={() => openAccount(t.account_id)} className="text-cyan-400 mt-1 hover:underline">in {accounts.find((a) => a.id === t.account_id)?.name || t.account_id}</button>}
                </div>
                <div className="text-right shrink-0">
                  <div className="font-extrabold tabular-nums">{formatMoney(t.active_display, disp)}</div>
                  <div className="text-[11px] text-slate-400 tabular-nums">{formatMoney(t.native_amount, t.currency)}</div>
                  {canManage && (
                    <div className="flex gap-2 justify-end mt-1 text-[11px]">
                      <button type="button" onClick={() => setModal({ type: 'trust', item: t })} className="text-slate-400 hover:text-slate-200 flex items-center gap-0.5"><Pencil className="w-3 h-3" /> Edit</button>
                      <button type="button" onClick={() => settle('trust', t)} className="text-cyan-400 hover:underline">Handed over</button>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>

          <div className="glass-panel p-5 space-y-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="text-lg font-bold">Owed to us</h2>
                <p className="text-xs text-slate-400 mt-0.5">Partner settlements, field advances awaiting receipts, amanahs we paid on someone&apos;s behalf. Memo lines are shown but not counted.</p>
              </div>
              <div className="text-right shrink-0">
                <div className="text-xl font-extrabold tabular-nums">{formatMoney(eq.receivables_display, disp)}</div>
                {canManage && <button type="button" onClick={() => setModal({ type: 'receivable' })} className="text-xs text-cyan-400 hover:underline flex items-center gap-1 ml-auto mt-1"><PlusCircle className="w-3.5 h-3.5" /> Add</button>}
              </div>
            </div>
            {(eq.receivables_items || []).map((r) => (
              <div key={r.id} className={`p-3.5 rounded-xl bg-slate-900/40 border border-slate-700/40 flex items-start justify-between gap-3 ${r.is_included_in_net_position ? '' : 'opacity-70'}`}>
                <div className="text-xs min-w-0">
                  <div className="flex items-center gap-2"><span className="font-bold text-sm">{r.name}</span>{!r.is_included_in_net_position && <span className="badge badge-slate text-[10px]">Memo only</span>}</div>
                  <div className="text-slate-400 mt-0.5">{r.note}</div>
                  <div className="text-slate-500 mt-0.5">as of {r.as_of_date}</div>
                </div>
                <div className="text-right shrink-0">
                  <div className="font-extrabold tabular-nums">{formatMoney(r.active_display, disp)}</div>
                  <div className="text-[11px] text-slate-400 tabular-nums">{formatMoney(r.native_amount, r.currency)}</div>
                  {canManage && (
                    <div className="flex gap-2 justify-end mt-1 text-[11px]">
                      <button type="button" onClick={() => setModal({ type: 'receivable', item: r })} className="text-slate-400 hover:text-slate-200 flex items-center gap-0.5"><Pencil className="w-3 h-3" /> Edit</button>
                      <button type="button" onClick={() => settle('receivable', r)} className="text-cyan-400 hover:underline">Cleared</button>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {subTab === 'pots' && <PotsView user={user} activeCompany={activeCompany} initialCountry={initialPotCountry} embedded />}
      {subTab === 'approvals' && (
        <ApprovalsPanel
          company={company}
          canApproveTransfers={canApproveTransfers}
          canApproveExpenses={canApproveExpenses}
          onOpenAccount={openAccount}
          onOpenPot={() => { setInitialPotCountry('ALL'); setSubTab('pots'); }}
        />
      )}
      {subTab === 'corrections' && <CorrectionsPanel company={company} canExport={canExport} />}
      {subTab === 'confirm' && <ConfirmPanel company={company} canResolve={canConfirm} onChanged={fetchCoreData} />}
      {subTab === 'sources' && <SourcesPanel company={company} onOpenAccount={openAccount} />}
      {subTab === 'activity' && <ActivityPanel company={company} canReverse={canManage} refreshKey={activityKey} onChanged={() => { fetchCoreData(); if (selectedAccount) fetchStatement(); }} />}

      {/* STATEMENT DRAWER */}
      {selectedAccount && (
        <>
          <div className="drawer-backdrop" onClick={() => setSelectedAccount(null)} />
          <div className="drawer-content drawer-wide flex flex-col" role="dialog" aria-label={`Statement for ${selectedAccount.name}`}>
            <div className="p-5 border-b border-slate-700/40 flex flex-wrap items-start justify-between gap-4">
              <div className="min-w-0">
                <h2 className="text-xl font-bold truncate flex items-center gap-2.5">
                  <CountryFlag country={selectedAccount.group_name} className="w-6 h-4.5 rounded-sm shrink-0" />
                  <span>{selectedAccount.name}</span>
                </h2>
                <p className="text-xs text-slate-400">{selectedAccount.group_name} · {selectedAccount.holder}{selectedAccount.supervisor ? ` (supervisor ${selectedAccount.supervisor})` : ''}</p>
                {selectedAccount.note && <p className="text-xs text-slate-400 mt-1 max-w-xl">{selectedAccount.note}</p>}
              </div>
              <div className="flex items-start gap-3">
                <div className="text-right">
                  <div className="text-[10px] uppercase tracking-wider text-slate-400 font-bold">Balance · as of {selectedAccount.balance_as_of}</div>
                  <div className="text-2xl font-extrabold tabular-nums">{formatMoney(selectedAccount.current_balance_native, selectedAccount.currency)}</div>
                  {selectedAccount.currency !== 'USD' && <div className="text-xs text-slate-400 tabular-nums">≈ {formatMoney(selectedAccount.active_usd, 'USD')}</div>}
                </div>
                <button type="button" onClick={() => setSelectedAccount(null)} aria-label="Close" className="p-2 rounded-xl border border-slate-700/50 hover:border-slate-500"><X className="w-5 h-5" /></button>
              </div>
            </div>

            <div className="px-5 py-3 border-b border-slate-700/30 flex flex-wrap items-center gap-2">
              {canWrite && <button type="button" onClick={() => setModal({ type: 'transfer', from: selectedAccount.id })} className="btn-secondary text-xs flex items-center gap-1.5"><ArrowRightLeft className="w-3.5 h-3.5" /> Move money</button>}
              {canWrite && <button type="button" onClick={() => setModal({ type: 'entry', account: selectedAccount.id })} className="btn-secondary text-xs flex items-center gap-1.5"><PlusCircle className="w-3.5 h-3.5" /> Entry</button>}
              {canManage && <button type="button" onClick={() => setModal({ type: 'balance', account: selectedAccount })} className="btn-secondary text-xs flex items-center gap-1.5"><Scale className="w-3.5 h-3.5" /> Update balance</button>}
              {canExport && <button type="button" onClick={() => treasuryExport(`/accounts/${encodeURIComponent(selectedAccount.id)}/transactions/export`, company, { status: stmtStatus, kind: stmtKind, month, search: stmtSearch })} className="btn-secondary text-xs flex items-center gap-1.5"><Download className="w-3.5 h-3.5" /> CSV</button>}
              <div className="ml-auto"><MiniFlow currency={selectedAccount.currency} months={Object.fromEntries((statementData?.monthly || []).map((m) => [m.month, { inc: m.inflow_native, exp: m.outflow_native }]))} /></div>
            </div>

            <div className="px-5 py-3 border-b border-slate-700/30 flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap items-center gap-1.5">
                {[['counted', 'Counted'], ['duplicate', 'Duplicates'], ['before_period', 'Before 1 Jul'], ['all', 'Everything']].map(([k, l]) => (
                  <button type="button" key={k} onClick={() => { setStmtStatus(k); setStmtPage(1); }} title={STATUS_META[k]?.hint || ''}
                    className={`px-2.5 py-1 rounded-md text-xs font-bold ${stmtStatus === k ? 'bg-blue-600 keep-white' : 'bg-slate-800/40 text-slate-400'}`}>
                    {l}{statementData?.status_counts && k !== 'all' ? ` (${statementData.status_counts[k] || 0})` : ''}
                  </button>
                ))}
                <span className="w-px h-5 bg-slate-700/50 mx-1" />
                {[['ALL', 'All kinds'], ['income', 'Income'], ['expense', 'Spending'], ['internal', 'Internal']].map(([k, l]) => (
                  <button type="button" key={k} onClick={() => { setStmtKind(k); setStmtPage(1); }} className={`px-2.5 py-1 rounded-md text-xs font-semibold ${stmtKind === k ? 'badge-cyan' : 'text-slate-400'}`}>{l}</button>
                ))}
              </div>
              <div className="relative">
                <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                <input value={stmtSearch} onChange={(e) => { setStmtSearch(e.target.value); setStmtPage(1); }} placeholder="Description, category, fund…" aria-label="Search statement" className="pl-8 pr-3 py-1.5 rounded-lg border text-xs w-56" />
              </div>
            </div>
            {stmtStatus !== 'counted' && STATUS_META[stmtStatus]?.hint && <div className="px-5 pt-2 text-[11px] text-amber-400">{STATUS_META[stmtStatus].hint}</div>}

            <div className="flex-1 overflow-y-auto custom-scrollbar p-4">
              {statementLoading && !statementData ? (
                <div className="py-20 text-center text-slate-400 text-sm">Loading statement…</div>
              ) : !(statementData?.transactions || []).length ? (
                <EmptyState icon={List} title="No lines" text="Nothing matches these filters for this account." />
              ) : (
                <table className="crm-table">
                  <thead><tr><th>Date</th><th>Kind</th><th>Category / other side</th><th>Fund</th><th>Description</th><th className="text-right">{selectedAccount.currency}</th><th className="text-right">USD</th></tr></thead>
                  <tbody>
                    {statementData.transactions.map((tx) => (
                      <tr key={tx.id} className={tx.status !== 'counted' ? 'opacity-60' : ''}>
                        <td className="tabular-nums whitespace-nowrap text-xs">{tx.tx_date || 'Undated'}
                          {tx.status !== 'counted' && <div><span className={`badge ${STATUS_META[tx.status]?.badge} text-[9px]`} title={STATUS_META[tx.status]?.hint}>{STATUS_META[tx.status]?.label}</span></div>}
                        </td>
                        <td><span className={`badge text-[10px] ${tx.kind === 'income' ? 'badge-emerald' : tx.kind === 'expense' ? 'badge-pink' : tx.kind === 'internal' ? 'badge-purple' : 'badge-amber'}`}>{tx.kind}</span></td>
                        <td className="text-xs font-semibold">{tx.counterparty_name || tx.category || '—'}</td>
                        <td className="text-xs">{tx.allocation || '—'}{tx.zakat_status ? <div className="text-slate-400">{tx.country} · {tx.zakat_status}</div> : null}</td>
                        <td className="text-xs text-slate-400 max-w-sm truncate" title={`${tx.description || ''}\n${tx.source_file || ''} · ${tx.source_tab || ''} row ${tx.source_row || ''}`}>{tx.description}</td>
                        <td className={`text-right font-bold tabular-nums whitespace-nowrap ${tx.amount_native < 0 ? 'text-rose-400' : ''}`}>{formatMoney(tx.amount_native, tx.currency, { signed: true })}</td>
                        <td className="text-right tabular-nums text-slate-400 whitespace-nowrap">{formatMoney(tx.amount_usd, 'USD', { signed: true })}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {(statementData?.balance_history || []).length > 0 && (
                <div className="mt-5">
                  <h3 className="text-sm font-bold mb-2">Balance updates</h3>
                  {statementData.balance_history.map((h) => (
                    <div key={h.id} className="text-xs flex justify-between py-1.5 border-b border-slate-700/20">
                      <span>{h.as_of} · {h.actor}{h.note ? ` — ${h.note}` : ''}</span>
                      <span className="tabular-nums">{formatMoney(h.old_native, selectedAccount.currency)} → <strong>{formatMoney(h.new_native, selectedAccount.currency)}</strong></span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {statementData && (
              <div className="px-5 py-3 border-t border-slate-700/40 flex flex-wrap items-center justify-between gap-2 text-xs">
                <div className="flex items-center gap-4 tabular-nums">
                  <span>In: <strong>{formatMoney(statementData.summary?.total_in, selectedAccount.currency)}</strong></span>
                  <span>Out: <strong>{formatMoney(statementData.summary?.total_out, selectedAccount.currency)}</strong></span>
                  {month !== 'ALL' && <span className="text-slate-400">{monthLabel(month)} only</span>}
                </div>
                <div className="w-72"><Pager page={statementData.page} totalPages={statementData.total_pages} total={statementData.total} onPage={setStmtPage} label="lines" /></div>
              </div>
            )}
          </div>
        </>
      )}

      {/* MODALS */}
      {modal?.type === 'transfer' && (
        <TransferForm
          accounts={accounts}
          company={company}
          defaultFrom={modal.from}
          canApprove={canApproveTransfers}
          onClose={() => setModal(null)}
          onDone={afterWrite}
        />
      )}
      {modal?.type === 'entry' && <EntryForm accounts={accounts} pots={pots} company={company} defaultAccount={modal.account} onClose={() => setModal(null)} onDone={afterWrite} />}
      {modal?.type === 'balance' && <BalanceForm account={modal.account} company={company} onClose={() => setModal(null)} onDone={afterWrite} />}
      {modal?.type === 'trust' && <TrustForm accounts={accounts} company={company} item={modal.item} onClose={() => setModal(null)} onDone={afterWrite} />}
      {modal?.type === 'receivable' && <ReceivableForm company={company} item={modal.item} onClose={() => setModal(null)} onDone={afterWrite} />}
      {modal?.type === 'account' && <AccountForm company={company} regions={regions} onClose={() => setModal(null)} onDone={afterWrite} />}
    </div>
  );
}
