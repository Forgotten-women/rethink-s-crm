import React, { useEffect, useMemo, useState } from 'react';
import { Activity, AlertTriangle, CheckCircle2, Clock, RotateCcw, Tag, Wallet, Save, X } from 'lucide-react';
import { API_BASE_URL } from '../../config';

const gbp = (v) => `£${Number(v || 0).toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const authHeaders = () => {
  const token = localStorage.getItem('analytics_token');
  return token ? { Authorization: `Bearer ${token}` } : {};
};
const ago = (iso) => {
  if (!iso) return 'never';
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 90) return `${s}s ago`;
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  return `${Math.round(s / 3600)} h ago`;
};

const codesPromises = {};
// The charity's own project codes, loaded once per page per charity
function useMasterCodes(company) {
  const [codes, setCodes] = useState([]);
  useEffect(() => {
    codesPromises[company] = codesPromises[company] || fetch(`${API_BASE_URL}/api/classifications/master-codes?company_id=${encodeURIComponent(company)}`, { headers: authHeaders() })
      .then(r => (r.ok ? r.json() : { codes: [] })).then(d => (d.codes || []).filter(c => c.is_active !== 0));
    codesPromises[company].then(setCodes).catch(() => setCodes([]));
  }, [company]);
  return codes;
}

/** Classify one payout line: pick a code; optionally map the project name so every gift for it follows. */
export function ClassifyLineForm({ item, company = 'rethink', onDone, onCancel }) {
  const codes = useMasterCodes(company);
  const [code, setCode] = useState('');
  const [applyToProject, setApplyToProject] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const generic = /^(one-off payment of .* via stripe|subscription of .* via stripe|subscription (update|creation)|payment for invoice.*|general website donation)$/i
    .test((item.project_name || '').trim());
  const match = useMemo(() => codes.find(c => c.code === code.trim()), [codes, code]);
  const listId = `codes-${item.balance_transaction_id}`;

  const save = async () => {
    setSaving(true); setError('');
    try {
      const res = await fetch(`${API_BASE_URL}/api/payouts/stripe/classify-line`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ balance_transaction_id: item.balance_transaction_id, code: code.trim(), apply_to_project: applyToProject && !generic, company_id: company }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `Error ${res.status}`);
      onDone?.(data);
    } catch (e) { setError(e.message); } finally { setSaving(false); }
  };

  return (
    <div className="flex flex-col gap-2 p-3 rounded-xl border border-amber-500/30 bg-amber-500/5">
      <div className="flex items-center gap-2 flex-wrap">
        <input list={listId} value={code} onChange={e => setCode(e.target.value)} placeholder="Type a project code or name"
          className="flex-1 min-w-[14rem] px-3 py-1.5 text-xs rounded-lg bg-white dark:bg-slate-800 border border-slate-300 dark:border-white/10 text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-amber-500" />
        <datalist id={listId}>
          {codes.map(c => <option key={c.code} value={c.code}>{[c.heading || c.department, c.sub_heading || c.office, c.country].filter(Boolean).join(' · ')}</option>)}
        </datalist>
        <button type="button" onClick={save} disabled={!match || saving}
          className="px-3 py-1.5 text-xs font-bold rounded-lg bg-amber-600 hover:bg-amber-500 text-white disabled:opacity-40 flex items-center gap-1">
          <Save className="w-3.5 h-3.5" />{saving ? 'Saving…' : 'Save'}
        </button>
        {onCancel && <button type="button" onClick={onCancel} className="p-1.5 text-slate-400 hover:text-slate-600" aria-label="Cancel"><X className="w-4 h-4" /></button>}
      </div>
      {match && (
        <div className="text-[11px] text-slate-600 dark:text-slate-300">
          {[match.heading || match.department, match.sub_heading || match.office, match.country, match.programme_fund, match.zakat_eligibility].filter(Boolean).join(' · ')}
        </div>
      )}
      {generic ? (
        <div className="text-[11px] text-slate-500">This payment has no project in Stripe, so only this line is classified.</div>
      ) : (
        <label className="flex items-center gap-1.5 text-[11px] text-slate-600 dark:text-slate-300">
          <input type="checkbox" checked={applyToProject} onChange={e => setApplyToProject(e.target.checked)} />
          Also classify every gift for “{item.project_name}” (adds it to the classification matrix)
        </label>
      )}
      {error && <div className="text-[11px] text-rose-500">{error}</div>}
    </div>
  );
}

/** Live Stripe position (from the ledger the sync service refreshes every minute) and the classification queue. */
export default function StripeReconciliationQueue({ company = 'rethink', refreshKey = 0, onChanged }) {
  const [summary, setSummary] = useState(null);
  const [queue, setQueue] = useState([]);
  const [openId, setOpenId] = useState(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let alive = true;
    Promise.all([
      fetch(`${API_BASE_URL}/api/payouts/stripe/ledger-summary?company_id=${encodeURIComponent(company)}`, { headers: authHeaders() }).then(r => (r.ok ? r.json() : null)),
      fetch(`${API_BASE_URL}/api/payouts/stripe/needs-classification?company_id=${encodeURIComponent(company)}`, { headers: authHeaders() }).then(r => (r.ok ? r.json() : { items: [] })),
    ]).then(([s, q]) => { if (alive) { setSummary(s); setQueue(q?.items || []); } }).catch(() => {});
    return () => { alive = false; };
  }, [company, refreshKey, tick]);

  useEffect(() => {
    const t = setInterval(() => setTick(x => x + 1), 60000);  // the ledger refreshes every minute
    return () => clearInterval(t);
  }, []);

  if (!summary?.available) return null;
  const card = 'p-3.5 rounded-2xl bg-white/80 dark:bg-slate-900/80 border border-slate-200 dark:border-white/10 shadow-sm';
  const label = 'text-[10px] font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400 flex items-center gap-1.5';

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2 text-xs font-bold text-slate-700 dark:text-slate-200">
          <Activity className="w-4 h-4 text-emerald-500" /> Live Stripe position
          <span className="text-[10px] font-normal text-slate-400">
            updated {ago(summary.last_synced_at)} · {summary.movements_recorded.toLocaleString()} movements since {String(summary.recorded_since || '').slice(0, 10)}
            {!summary.history_complete && ' · loading history…'}
          </span>
        </div>
        <button type="button" onClick={() => setTick(x => x + 1)} className="text-[11px] text-cyan-600 dark:text-cyan-400 flex items-center gap-1">
          <RotateCcw className="w-3 h-3" /> Refresh
        </button>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className={card}>
          <div className={label}><Wallet className="w-3.5 h-3.5 text-cyan-500" />Received, not yet paid out</div>
          <div className="mt-1.5 text-lg font-black font-mono text-slate-900 dark:text-white">{gbp(summary.awaiting_payout.net)}</div>
          <div className="text-[10px] text-slate-400">{summary.awaiting_payout.count} movements in the next payout</div>
        </div>
        <div className={card}>
          <div className={label}><Clock className="w-3.5 h-3.5 text-indigo-500" />Gifts, last 30 days</div>
          <div className="mt-1.5 text-lg font-black font-mono text-slate-900 dark:text-white">{gbp(summary.gifts_30_days.amount)}</div>
          <div className="text-[10px] text-slate-400">{summary.gifts_30_days.count} payments</div>
        </div>
        <div className={card}>
          <div className={label}><AlertTriangle className="w-3.5 h-3.5 text-rose-500" />Refunds & disputes, 30 days</div>
          <div className="mt-1.5 text-lg font-black font-mono text-rose-600 dark:text-rose-400">{gbp(Math.abs(summary.refunds_30_days.amount))}</div>
          <div className="text-[10px] text-slate-400">{summary.refunds_30_days.count} refunds · {summary.disputed_charges} disputed charges</div>
        </div>
        <div className={card}>
          <div className={label}><Tag className="w-3.5 h-3.5 text-amber-500" />Needs classification</div>
          <div className={`mt-1.5 text-lg font-black font-mono ${queue.length ? 'text-amber-600 dark:text-amber-400' : 'text-emerald-600 dark:text-emerald-400'}`}>
            {queue.length ? queue.length : <span className="flex items-center gap-1"><CheckCircle2 className="w-4 h-4" />None</span>}
          </div>
          <div className="text-[10px] text-slate-400">{queue.length ? 'payout lines to classify before approval' : 'every payout line is classified'}</div>
        </div>
      </div>

      {queue.length > 0 && (
        <div className="rounded-2xl border border-amber-500/30 bg-white/90 dark:bg-slate-900/90 overflow-hidden">
          <div className="px-4 py-2.5 border-b border-amber-500/20 text-xs font-bold text-amber-700 dark:text-amber-300 flex items-center gap-1.5">
            <Tag className="w-3.5 h-3.5" /> Needs classification ({queue.length})
          </div>
          <div className="divide-y divide-slate-200 dark:divide-white/5">
            {queue.map(it => (
              <div key={it.balance_transaction_id} className="px-4 py-2.5 text-xs">
                <div className="flex items-center gap-3 flex-wrap">
                  <span className="font-mono text-slate-500 w-20">{String(it.created_at || '').slice(0, 10)}</span>
                  <span className="font-mono font-bold text-slate-900 dark:text-white w-24 text-right">{gbp(it.gross)}</span>
                  <span className="flex-1 min-w-[12rem]">
                    <span className="font-semibold text-slate-900 dark:text-white">{it.project_name || '—'}</span>
                    <span className="text-slate-400"> · {it.donor_name || it.donor_email || 'unknown donor'} · {it.source_type}</span>
                  </span>
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-700 dark:text-amber-300">{it.reason}</span>
                  <span className="font-mono text-[10px] text-slate-400">payout {String(it.payout_id).slice(-8)} · {it.payout_arrival}</span>
                  <button type="button" onClick={() => setOpenId(openId === it.balance_transaction_id ? null : it.balance_transaction_id)}
                    className="px-2.5 py-1 rounded-lg bg-amber-600 hover:bg-amber-500 text-white font-bold text-[11px]">Classify</button>
                </div>
                {openId === it.balance_transaction_id && (
                  <div className="mt-2">
                    <ClassifyLineForm item={it} company={company} onCancel={() => setOpenId(null)} onDone={() => { setOpenId(null); setTick(x => x + 1); onChanged?.(); }} />
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
