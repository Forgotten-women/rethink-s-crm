import React, { useCallback, useEffect, useState } from 'react';
import {
  Search, Download, ChevronLeft, ChevronRight, CheckCircle2, RotateCcw, FileSpreadsheet,
  AlertTriangle, Clock, History, X, Undo2,
} from 'lucide-react';
import { API_BASE_URL, getAuthHeaders, downloadFile } from '../../config';
import { formatMoney } from './treasuryUtils';

export const treasuryApi = async (path, { method = 'GET', body, company = 'rethink', params = {} } = {}) => {
  const q = new URLSearchParams({ company_id: company, ...Object.fromEntries(Object.entries(params).filter(([, v]) => v !== '' && v !== undefined && v !== null)) });
  const res = await fetch(`${API_BASE_URL}/api/treasury${path}${path.includes('?') ? '&' : '?'}${q.toString()}`, {
    method,
    headers: { ...getAuthHeaders(), ...(body ? { 'Content-Type': 'application/json' } : {}) },
    body: body ? JSON.stringify({ company_id: company, ...body }) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch { /* empty */ }
  if (!res.ok) {
    const d = data?.detail;
    const err = new Error(typeof d === 'string' ? d : d?.message || `Request failed (${res.status})`);
    err.status = res.status;
    err.detail = d;
    throw err;
  }
  return data;
};

export const treasuryExport = (path, company, params = {}) => {
  const q = new URLSearchParams({ company_id: company, ...Object.fromEntries(Object.entries(params).filter(([, v]) => v && v !== 'ALL')) });
  return downloadFile(`${API_BASE_URL}/api/treasury${path}?${q.toString()}`, 'treasury.csv');
};

export function Pager({ page, totalPages, total, onPage, label = 'entries' }) {
  return (
    <div className="flex items-center justify-between pt-3 border-t border-slate-700/30 text-xs">
      <span className="text-slate-400">Page {page} of {totalPages} · {total} {label}</span>
      <div className="flex items-center gap-2">
        <button type="button" disabled={page <= 1} onClick={() => onPage(page - 1)} className="btn-secondary px-2.5 py-1 disabled:opacity-40" aria-label="Previous page"><ChevronLeft className="w-4 h-4" /></button>
        <button type="button" disabled={page >= totalPages} onClick={() => onPage(page + 1)} className="btn-secondary px-2.5 py-1 disabled:opacity-40" aria-label="Next page"><ChevronRight className="w-4 h-4" /></button>
      </div>
    </div>
  );
}

export function EmptyState({ icon: Icon = CheckCircle2, title, text }) {
  return (
    <div className="py-14 text-center">
      <Icon className="w-8 h-8 mx-auto text-slate-500" />
      <div className="font-bold mt-2">{title}</div>
      {text && <div className="text-xs text-slate-400 mt-1 max-w-md mx-auto">{text}</div>}
    </div>
  );
}

const ADJ_TYPE_LABEL = {
  reallocation: 'Reallocation', expense_adj: 'Expense restated', income_adj: 'Income restated', expense: 'Expense',
  income: 'Income', cover: 'Cover (deficit funded)', reclassify_income: 'Income reclassified', reversal: 'Reversal',
  transfer_loss: 'Transfer / FX loss', provisional_income: 'Provisional income', income_reclass: 'Income reclassified',
  reclassify_expense: 'Expense reclassified', opening_balance: 'Opening balance', write_off: 'Write-off',
};

/** Corrections register - every approved correction from the monthly close plus reallocations made in the CRM. */
export function CorrectionsPanel({ company, canExport, onOpenPot }) {
  const [data, setData] = useState({ adjustments: [], types: [], total: 0, total_pages: 1, page: 1, total_usd: 0 });
  const [type, setType] = useState('ALL');
  const [source, setSource] = useState('ALL');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(null);

  useEffect(() => {
    const t = setTimeout(async () => {
      setLoading(true);
      try {
        setData(await treasuryApi('/adjustments', { company, params: { adj_type: type, source, search: search.trim(), page, page_size: 40 } }));
      } catch (e) { console.error(e); } finally { setLoading(false); }
    }, search ? 250 : 0);
    return () => clearTimeout(t);
  }, [company, type, source, search, page]);

  return (
    <div className="glass-panel p-5 space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold flex items-center gap-2"><FileSpreadsheet className="w-5 h-5 text-cyan-400" /> Corrections register</h2>
          <p className="text-xs text-slate-400 mt-0.5 max-w-2xl">
            Errors in the source sheets are never fixed by editing the sheets — each correction is a dated line here
            (who approved it, why, and which period it lands in). Reallocations made in the CRM appear here too.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} placeholder="Fund, note, approver…"
              className="pl-8 pr-3 py-1.5 rounded-lg border text-xs w-56" aria-label="Search corrections" />
          </div>
          <select value={source} onChange={(e) => { setSource(e.target.value); setPage(1); }} className="px-2 py-1.5 rounded-lg border text-xs" aria-label="Source">
            <option value="ALL">All sources</option><option value="archive">Monthly close</option><option value="crm">Made in CRM</option>
          </select>
          {canExport && (
            <button type="button" onClick={() => treasuryExport('/adjustments/export', company, { adj_type: type, source, search })}
              className="btn-secondary text-xs flex items-center gap-1.5"><Download className="w-3.5 h-3.5" /> CSV</button>
          )}
        </div>
      </div>

      <div className="flex flex-wrap gap-1.5">
        <button type="button" onClick={() => { setType('ALL'); setPage(1); }}
          className={`px-2.5 py-1 rounded-md text-xs font-semibold ${type === 'ALL' ? 'bg-blue-600 keep-white' : 'bg-slate-800/40 text-slate-400'}`}>All types</button>
        {data.types.map((t) => (
          <button type="button" key={t.adj_type} onClick={() => { setType(t.adj_type); setPage(1); }}
            className={`px-2.5 py-1 rounded-md text-xs font-semibold ${type === t.adj_type ? 'bg-blue-600 keep-white' : 'bg-slate-800/40 text-slate-400 hover:text-slate-200'}`}>
            {ADJ_TYPE_LABEL[t.adj_type] || t.adj_type} <span className="opacity-70">({t.n})</span>
          </button>
        ))}
      </div>

      <div className="text-xs text-slate-400">{data.total} corrections · {formatMoney(data.total_usd, 'USD')} moved or restated{loading ? ' · loading…' : ''}</div>

      <div className="overflow-x-auto">
        <table className="crm-table">
          <thead><tr><th>Date</th><th>Type</th><th>From</th><th>To</th><th className="text-right">USD</th><th>Approved</th><th>Lands in</th></tr></thead>
          <tbody>
            {data.adjustments.map((a) => (
              <React.Fragment key={a.id}>
                <tr className="cursor-pointer" onClick={() => setOpen(open === a.id ? null : a.id)}>
                  <td className="tabular-nums whitespace-nowrap">{a.adj_date}</td>
                  <td><span className={`badge text-[10px] ${a.source === 'crm' ? 'badge-cyan' : 'badge-slate'}`}>{ADJ_TYPE_LABEL[a.adj_type] || a.adj_type}</span></td>
                  <td className="text-xs">{a.from_fund ? <><div className="font-semibold">{a.from_fund}</div><div className="text-slate-400">{a.from_country} · {a.from_pool}</div></> : '—'}</td>
                  <td className="text-xs">{a.to_fund ? <><div className="font-semibold">{a.to_fund}</div><div className="text-slate-400">{a.to_country} · {a.to_pool}</div></> : '—'}</td>
                  <td className="text-right tabular-nums font-bold whitespace-nowrap">{formatMoney(a.usd, 'USD')}</td>
                  <td className="text-xs text-slate-400 max-w-[10rem] truncate">{a.approved_by}</td>
                  <td className="text-xs text-slate-400 whitespace-nowrap">{a.applied_to}</td>
                </tr>
                {open === a.id && (
                  <tr><td colSpan={7} className="text-xs text-slate-300 bg-slate-900/30">
                    <div className="py-1 whitespace-pre-wrap">{a.note || 'No note.'}</div>
                    {onOpenPot && a.from_fund && <button type="button" className="text-cyan-400 mr-3" onClick={() => onOpenPot(a.from_fund, a.from_country, a.from_pool)}>Open {a.from_fund} →</button>}
                    {onOpenPot && a.to_fund && <button type="button" className="text-cyan-400" onClick={() => onOpenPot(a.to_fund, a.to_country, a.to_pool)}>Open {a.to_fund} →</button>}
                  </td></tr>
                )}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>
      <Pager page={data.page} totalPages={data.total_pages} total={data.total} onPage={setPage} label="corrections" />
    </div>
  );
}

/** Lines the close could only book with an assumption, waiting for Osman's confirmation. */
export function ConfirmPanel({ company, canResolve, onChanged }) {
  const [status, setStatus] = useState('open');
  const [data, setData] = useState({ items: [], counts: {} });
  const [editing, setEditing] = useState(null);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const load = useCallback(async () => {
    try { setData(await treasuryApi('/confirm-items', { company, params: { status } })); } catch (e) { setErr(e.message); }
  }, [company, status]);
  useEffect(() => { load(); }, [load]);

  const resolve = async (id) => {
    setBusy(true); setErr('');
    try {
      await treasuryApi(`/confirm-items/${id}/resolve`, { method: 'POST', company, body: { resolution: text } });
      setEditing(null); setText(''); await load(); onChanged && onChanged();
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  const reopen = async (id) => {
    try { await treasuryApi(`/confirm-items/${id}/reopen`, { method: 'POST', company }); await load(); onChanged && onChanged(); } catch (e) { setErr(e.message); }
  };

  const groups = {};
  data.items.forEach((it) => { (groups[it.category] = groups[it.category] || []).push(it); });
  const open = data.counts.open || { count: 0, usd: 0 };
  const done = data.counts.resolved || { count: 0, usd: 0 };

  return (
    <div className="glass-panel p-5 space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold flex items-center gap-2"><AlertTriangle className="w-5 h-5 text-amber-400" /> Waiting for confirmation</h2>
          <p className="text-xs text-slate-400 mt-0.5 max-w-2xl">
            The close booked these lines on an assumption (a note in the country column, a default country, a small
            uncoded line parked in &quot;To be coded&quot;). Confirm each one or note the fix for the next close.
          </p>
        </div>
        <div className="flex rounded-xl p-1 border border-slate-700/60 bg-slate-900/40 text-xs font-bold">
          {[['open', `Open (${open.count})`], ['resolved', `Confirmed (${done.count})`], ['all', 'All']].map(([k, l]) => (
            <button type="button" key={k} onClick={() => setStatus(k)}
              className={`px-3 py-1.5 rounded-lg ${status === k ? 'bg-blue-600 keep-white' : 'text-slate-400'}`}>{l}</button>
          ))}
        </div>
      </div>
      {err && <div className="text-xs text-rose-400">{err}</div>}
      {status === 'open' && open.count > 0 && (
        <div className="text-xs text-slate-400">{open.count} open lines · {formatMoney(open.usd, 'USD')} booked on an assumption</div>
      )}
      {!data.items.length && <EmptyState title="Nothing waiting" text="Every assumption from the close has been confirmed." />}
      {Object.entries(groups).map(([cat, items]) => (
        <div key={cat} className="space-y-1.5">
          <div className="text-[11px] uppercase tracking-wider font-bold text-slate-400">{cat} · {items.length}</div>
          {items.map((it) => (
            <div key={it.id} className="p-3 rounded-xl bg-slate-900/40 border border-slate-700/40">
              <div className="flex items-start justify-between gap-3">
                <div className="text-xs">
                  <div className="font-semibold">{it.item}</div>
                  {it.status === 'resolved' && (
                    <div className="text-emerald-400 mt-1 flex items-center gap-1"><CheckCircle2 className="w-3.5 h-3.5" /> {it.resolution} <span className="text-slate-400">— {it.resolved_by}, {it.resolved_at}</span></div>
                  )}
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <span className="font-bold tabular-nums text-sm">{formatMoney(it.usd, 'USD')}</span>
                  {canResolve && it.status === 'open' && editing !== it.id && (
                    <button type="button" className="btn-secondary text-xs" onClick={() => { setEditing(it.id); setText('Confirmed as booked'); }}>Confirm…</button>
                  )}
                  {canResolve && it.status === 'resolved' && (
                    <button type="button" className="text-xs text-slate-400 hover:text-slate-200" onClick={() => reopen(it.id)} title="Reopen"><RotateCcw className="w-3.5 h-3.5" /></button>
                  )}
                </div>
              </div>
              {editing === it.id && (
                <div className="mt-2 flex items-center gap-2">
                  <input autoFocus value={text} onChange={(e) => setText(e.target.value)} className="flex-1 p-2 rounded-lg border text-xs"
                    placeholder="e.g. Confirmed as booked / Recode to Gaza Food next close" aria-label="Resolution" />
                  <button type="button" disabled={busy || !text.trim()} onClick={() => resolve(it.id)} className="btn-primary keep-white text-xs">Save</button>
                  <button type="button" onClick={() => setEditing(null)} className="btn-secondary text-xs">Cancel</button>
                </div>
              )}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

const daysBetween = (a, b) => Math.round((new Date(b) - new Date(a)) / 86400000);

/** Every workbook/tab the close was built from and how recent its last line is. */
export function SourcesPanel({ company, onOpenAccount }) {
  const [data, setData] = useState({ sources: [], period_end: '2026-10-31' });
  const [filter, setFilter] = useState('ALL');
  useEffect(() => { treasuryApi('/sources', { company }).then(setData).catch(console.error); }, [company]);
  const rows = data.sources.filter((s) => filter === 'ALL' || s.period === filter);
  const stale = data.sources.filter((s) => s.period === 'October' && !s.covers_period_end).length;
  return (
    <div className="glass-panel p-5 space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold flex items-center gap-2"><Clock className="w-5 h-5 text-cyan-400" /> Source sheets</h2>
          <p className="text-xs text-slate-400 mt-0.5 max-w-2xl">
            The {data.sources.length} workbook tabs behind the {data.period_end} close. &quot;Last line&quot; is the newest dated row in each —
            a holder whose sheet stops early hasn&apos;t delivered the full month yet (cut-off: 5th of the month for cash holders, 10th for the Syria office).
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5 text-xs">
          {['ALL', 'October', 'September', 'Jul–Aug'].map((f) => (
            <button type="button" key={f} onClick={() => setFilter(f)}
              className={`px-2.5 py-1 rounded-md font-semibold ${filter === f ? 'bg-blue-600 keep-white' : 'bg-slate-800/40 text-slate-400'}`}>{f === 'ALL' ? 'All' : f}</button>
          ))}
        </div>
      </div>
      {stale > 0 && <div className="text-xs text-amber-400 flex items-center gap-1.5"><AlertTriangle className="w-3.5 h-3.5" /> {stale} October tab(s) end before 25 Oct.</div>}
      <div className="overflow-x-auto">
        <table className="crm-table">
          <thead><tr><th>Workbook · tab</th><th>Account</th><th>Folder</th><th className="text-right">Lines</th><th>Last line</th><th className="text-right">Income</th><th className="text-right">Spend</th><th className="text-right">Internal</th></tr></thead>
          <tbody>
            {rows.map((s) => {
              const lag = s.last_date ? daysBetween(s.last_date, data.period_end) : null;
              const future = lag !== null && lag < -60;
              return (
                <tr key={s.id}>
                  <td className="text-xs"><div className="font-semibold">{s.file}</div><div className="text-slate-400">{s.tab}</div></td>
                  <td className="text-xs">{s.account_name ? <button type="button" className="text-cyan-400 hover:underline" onClick={() => onOpenAccount && onOpenAccount(s.account_id)}>{s.account_name}</button> : <span className="text-slate-500">—</span>}</td>
                  <td className="text-xs">{s.period}</td>
                  <td className="text-right tabular-nums text-xs">{s.lines}</td>
                  <td className="text-xs whitespace-nowrap">
                    {s.last_date || '—'}{' '}
                    {future ? <span className="badge badge-pink text-[10px]">date typo?</span>
                      : s.period === 'October' && lag > 6 ? <span className="badge badge-amber text-[10px]">{lag}d early</span> : null}
                  </td>
                  <td className="text-right tabular-nums text-xs">{s.inc_usd ? formatMoney(s.inc_usd, 'USD', { compact: true }) : '—'}</td>
                  <td className="text-right tabular-nums text-xs">{s.exp_usd ? formatMoney(s.exp_usd, 'USD', { compact: true }) : '—'}</td>
                  <td className="text-right tabular-nums text-xs text-slate-400">{s.internal_usd ? formatMoney(s.internal_usd, 'USD', { compact: true }) : '—'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const ACTION_LABEL = {
  transfer: 'Transfer', income: 'Income', expense: 'Expense', reallocation: 'Reallocation', balance_update: 'Balance update',
  account_create: 'New account', account_edit: 'Account edited', trust_create: 'Amanah added', trust_edit: 'Amanah edited',
  trust_settle: 'Amanah handed over', receivable_create: 'Receivable added', receivable_edit: 'Receivable edited',
  receivable_settle: 'Receivable cleared', pot_create: 'New pot', confirm_resolve: 'Confirmed', reversal: 'Reversal',
};

/** Everything changed from the CRM, with an exact one-click reversal. */
export function ActivityPanel({ company, canReverse, onChanged, refreshKey }) {
  const [data, setData] = useState({ activity: [], total: 0, page: 1, total_pages: 1 });
  const [page, setPage] = useState(1);
  const [confirmId, setConfirmId] = useState(null);
  const [reason, setReason] = useState('');
  const [err, setErr] = useState('');
  const load = useCallback(async () => {
    try { setData(await treasuryApi('/activity', { company, params: { page, page_size: 30 } })); } catch (e) { setErr(e.message); }
  }, [company, page]);
  useEffect(() => { load(); }, [load, refreshKey]);

  const reverse = async (id) => {
    setErr('');
    try {
      await treasuryApi(`/activity/${id}/reverse`, { method: 'POST', company, body: { reason } });
      setConfirmId(null); setReason(''); await load(); onChanged && onChanged();
    } catch (e) { setErr(e.message); }
  };

  return (
    <div className="glass-panel p-5 space-y-4">
      <div>
        <h2 className="text-lg font-bold flex items-center gap-2"><History className="w-5 h-5 text-purple-400" /> Activity &amp; undo</h2>
        <p className="text-xs text-slate-400 mt-0.5">Every change made here, who made it, and an exact reversal. The original and its reversal both stay on record.</p>
      </div>
      {err && <div className="text-xs text-rose-400">{err}</div>}
      {!data.activity.length ? <EmptyState icon={History} title="No changes yet" text="Transfers, entries, reallocations and balance updates made in the CRM will show here." /> : (
        <div className="space-y-2">
          {data.activity.map((a) => (
            <div key={a.id} className={`p-3 rounded-xl border flex flex-wrap items-center justify-between gap-3 ${a.reversed_by ? 'border-slate-700/30 opacity-60' : 'border-slate-700/50 bg-slate-900/30'}`}>
              <div className="text-xs min-w-0">
                <div className="flex items-center gap-2">
                  <span className={`badge text-[10px] ${a.action === 'reversal' ? 'badge-amber' : 'badge-cyan'}`}>{ACTION_LABEL[a.action] || a.action}</span>
                  <span className={`font-semibold ${a.reversed_by ? 'line-through' : ''}`}>{a.summary}</span>
                </div>
                <div className="text-slate-400 mt-0.5">#{a.id} · {a.ts} UTC · {a.actor}{a.reversed_by ? ` · reversed by #${a.reversed_by}` : ''}</div>
              </div>
              <div className="flex items-center gap-2">
                {a.amount_usd ? <span className="tabular-nums font-bold text-sm">{formatMoney(a.amount_usd, 'USD')}</span> : null}
                {canReverse && a.reversible && !a.reversed_by && !a.reversal_of && confirmId !== a.id && (
                  <button type="button" className="btn-secondary text-xs flex items-center gap-1" onClick={() => setConfirmId(a.id)}><Undo2 className="w-3.5 h-3.5" /> Reverse</button>
                )}
              </div>
              {confirmId === a.id && (
                <div className="w-full flex items-center gap-2">
                  <input autoFocus value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why? (optional)" className="flex-1 p-2 rounded-lg border text-xs" aria-label="Reason" />
                  <button type="button" onClick={() => reverse(a.id)} className="px-3 py-2 rounded-lg bg-rose-600 keep-white text-xs font-bold">Reverse #{a.id}</button>
                  <button type="button" onClick={() => setConfirmId(null)} className="btn-secondary text-xs"><X className="w-3.5 h-3.5" /></button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      <Pager page={data.page} totalPages={data.total_pages} total={data.total} onPage={setPage} label="changes" />
    </div>
  );
}
