import React, { useEffect, useMemo, useState } from 'react';
import { Crown, Plus, Search, Trash2, Users, AlertTriangle, Divide, Loader2, Check, UserRound } from 'lucide-react';
import { API_BASE_URL } from '../../config';
import { toDraftDonor, clean, donorKeyFor } from './trackerUtils';

const blankDonor = (role) => ({
  key: `new_${Math.random().toString(36).slice(2, 9)}`,
  donor_id: '',
  donor_name: '',
  donor_email: '',
  donor_phone: '',
  contribution_amount: 0,
  is_primary: false,
  is_manual: true,
  role
});

const sameDonor = (a, b) =>
  (a.donor_email && b.donor_email && a.donor_email.toLowerCase() === b.donor_email.toLowerCase()) ||
  (a.donor_id && b.donor_id && a.donor_id.toLowerCase() === b.donor_id.toLowerCase());

/**
 * Edits the list of donors (or campaign organizers) sharing one sponsorship.
 *  - mode="draft": controlled list for a new allocation (value / onChange).
 *  - mode="live": loads and saves an existing allocation's donors through the API.
 */
export default function AllocationDonorsEditor({
  mode = 'draft',
  value = [],
  onChange,
  allocationId,
  companyId,
  targetAmount = 0,
  sponsorshipType,
  role = 'donor',
  onSaved,
  onOpenDonor
}) {
  const [liveDonors, setLiveDonors] = useState([]);
  const [loading, setLoading] = useState(mode === 'live');
  const [busyId, setBusyId] = useState(null);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [newRow, setNewRow] = useState(null);

  const donors = mode === 'live' ? liveDonors : value;
  const funded = useMemo(() => donors.reduce((s, d) => s + Number(d.contribution_amount || 0), 0), [donors]);
  const pct = targetAmount > 0 ? Math.min(100, (funded / targetAmount) * 100) : 0;
  const gap = targetAmount > 0 ? Math.round((targetAmount - funded) * 100) / 100 : 0;

  const loadLive = () => {
    if (mode !== 'live' || !allocationId) return;
    setLoading(true);
    fetch(`${API_BASE_URL}/api/tracker/allocations/${allocationId}/donors?company_id=${companyId}`)
      .then(r => r.json())
      .then(res => setLiveDonors((res.donors || []).map(d => ({ ...d, key: String(d.id) }))))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  };
  useEffect(loadLive, [mode, allocationId, companyId]);

  // Debounced donor search (all CRM + manual donors of this charity)
  useEffect(() => {
    const q = query.trim();
    if (q.length < 2) { setResults([]); return undefined; }
    const t = setTimeout(() => {
      setSearching(true);
      const params = new URLSearchParams({ query: q, company_id: companyId, sponsorship_type: sponsorshipType || 'Orphan' });
      fetch(`${API_BASE_URL}/api/tracker/search-any-donor?${params}`)
        .then(r => r.json())
        .then(res => setResults((res.donors || []).slice(0, 8)))
        .catch(() => setResults([]))
        .finally(() => setSearching(false));
    }, 300);
    return () => clearTimeout(t);
  }, [query, companyId, sponsorshipType]);

  const apiCall = async (url, method, body) => {
    const res = await fetch(`${API_BASE_URL}${url}`, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: body ? JSON.stringify({ ...body, company_id: companyId }) : undefined
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || 'Request failed');
    return data;
  };

  const afterLiveChange = (data) => {
    setLiveDonors((data.donors || []).map(d => ({ ...d, key: String(d.id) })));
    setError('');
    if (onSaved) onSaved(data.donors || []);
  };

  // ---- draft helpers ----
  const setDraft = (list) => {
    let next = list;
    if (next.length && !next.some(d => d.is_primary)) next = next.map((d, i) => ({ ...d, is_primary: i === 0 }));
    if (onChange) onChange(next);
  };

  const addDonor = async (raw) => {
    const row = raw.key ? raw : toDraftDonor(raw, role);
    if (donors.some(d => sameDonor(d, row))) { setError(`${row.donor_name || row.donor_email} is already on this sponsorship.`); return; }
    if (!clean(row.donor_email) && !clean(row.donor_phone)) { setError('Each donor needs an email or phone number.'); return; }
    if (!row.contribution_amount && targetAmount > 0) {
      row.contribution_amount = donors.length === 0 ? targetAmount : Math.max(0, Math.round(gap * 100) / 100);
    }
    setQuery(''); setResults([]); setError('');
    if (mode === 'draft') {
      setDraft([...donors, { ...row, is_primary: donors.length === 0 }]);
      return;
    }
    try {
      setBusyId('new');
      afterLiveChange(await apiCall(`/api/tracker/allocations/${allocationId}/donors`, 'POST', {
        donor_id: row.donor_id, donor_name: row.donor_name, donor_email: row.donor_email, donor_phone: row.donor_phone,
        contribution_amount: Number(row.contribution_amount || 0), is_manual: row.is_manual, role: row.role || role
      }));
      setNewRow(null);
    } catch (e) { setError(e.message); } finally { setBusyId(null); }
  };

  const updateDonor = async (d, patch) => {
    if (mode === 'draft') {
      setDraft(donors.map(x => x.key === d.key ? { ...x, ...patch } : (patch.is_primary ? { ...x, is_primary: false } : x)));
      return;
    }
    try {
      setBusyId(d.id);
      afterLiveChange(await apiCall(`/api/tracker/allocation-donors/${d.id}`, 'PUT', patch));
    } catch (e) { setError(e.message); loadLive(); } finally { setBusyId(null); }
  };

  const removeDonor = async (d) => {
    if (mode === 'draft') { setDraft(donors.filter(x => x.key !== d.key)); return; }
    if (!window.confirm(`Remove ${d.donor_name || d.donor_email} from this sponsorship? Their pending queued emails will be skipped.`)) return;
    try {
      setBusyId(d.id);
      afterLiveChange(await apiCall(`/api/tracker/allocation-donors/${d.id}`, 'DELETE'));
    } catch (e) { setError(e.message); } finally { setBusyId(null); }
  };

  const splitEqually = () => {
    if (!donors.length || !targetAmount) return;
    const share = Math.floor((targetAmount / donors.length) * 100) / 100;
    const remainder = Math.round((targetAmount - share * donors.length) * 100) / 100;
    const amounts = donors.map((_, i) => (i === 0 ? Math.round((share + remainder) * 100) / 100 : share));
    if (mode === 'draft') { setDraft(donors.map((d, i) => ({ ...d, contribution_amount: amounts[i] }))); return; }
    donors.reduce((p, d, i) => p.then(() => apiCall(`/api/tracker/allocation-donors/${d.id}`, 'PUT', { contribution_amount: amounts[i] })), Promise.resolve())
      .then(() => { loadLive(); if (onSaved) onSaved(); })
      .catch(e => setError(e.message));
  };

  const commitField = (d, field, raw) => {
    const valueOut = field === 'contribution_amount' ? Number(raw || 0) : raw;
    if (String(d[field] ?? '') === String(valueOut ?? '')) return;
    updateDonor(d, { [field]: valueOut });
  };

  const isOrganizer = role === 'organizer';
  const label = isOrganizer ? 'organizer' : 'donor';

  return (
    <div className="flex flex-col gap-2.5 text-xs">
      {/* Funding summary */}
      <div className="p-3 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/40 flex flex-col gap-2">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <span className="font-bold text-slate-700 dark:text-slate-200 flex items-center gap-1.5">
            <Users className="w-3.5 h-3.5 text-blue-600" />
            {donors.length} {label}{donors.length === 1 ? '' : 's'} on this sponsorship
          </span>
          <div className="flex items-center gap-2">
            {targetAmount > 0 && (
              <span className={`font-bold ${gap > 0.005 ? 'text-amber-600' : gap < -0.005 ? 'text-rose-600' : 'text-emerald-600'}`}>
                £{funded.toLocaleString(undefined, { maximumFractionDigits: 2 })} / £{Number(targetAmount).toLocaleString()}
              </span>
            )}
            {donors.length > 1 && targetAmount > 0 && (
              <button type="button" onClick={splitEqually}
                className="px-2 py-1 rounded-md bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 font-semibold text-slate-600 dark:text-slate-300 hover:border-blue-400 flex items-center gap-1">
                <Divide className="w-3 h-3" /> Split equally
              </button>
            )}
          </div>
        </div>
        {targetAmount > 0 && (
          <>
            <div className="h-1.5 rounded-full bg-slate-200 dark:bg-slate-700 overflow-hidden">
              <div className={`h-full ${gap > 0.005 ? 'bg-amber-500' : gap < -0.005 ? 'bg-rose-500' : 'bg-emerald-500'}`} style={{ width: `${pct}%` }} />
            </div>
            {Math.abs(gap) > 0.005 && donors.length > 0 && (
              <span className={`flex items-center gap-1 ${gap > 0 ? 'text-amber-700 dark:text-amber-400' : 'text-rose-700 dark:text-rose-400'}`}>
                <AlertTriangle className="w-3 h-3" />
                {gap > 0 ? `£${gap.toLocaleString()} still unfunded` : `Over-funded by £${Math.abs(gap).toLocaleString()}`} — you can still save.
              </span>
            )}
          </>
        )}
      </div>

      {loading && <div className="py-4 text-center text-slate-400 flex items-center justify-center gap-2"><Loader2 className="w-4 h-4 animate-spin" /> Loading donors…</div>}

      {/* Donor rows */}
      {!loading && donors.map(d => (
        <div key={d.key} className={`p-2.5 rounded-xl border bg-white dark:bg-slate-900 flex flex-col gap-2 ${d.is_primary ? 'border-blue-400 dark:border-blue-700' : 'border-slate-200 dark:border-slate-700'} ${busyId === d.id ? 'opacity-60' : ''}`}>
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 min-w-0">
              <button type="button" title={d.is_primary ? 'Primary contact' : 'Make primary contact'}
                onClick={() => !d.is_primary && updateDonor(d, { is_primary: true })}
                className={`p-1 rounded-md ${d.is_primary ? 'bg-blue-600 text-white' : 'bg-slate-100 dark:bg-slate-800 text-slate-400 hover:text-blue-600'}`}>
                <Crown className="w-3 h-3" />
              </button>
              {onOpenDonor && donorKeyFor(d) ? (
                <button type="button" onClick={() => onOpenDonor(donorKeyFor(d))}
                  className="font-bold text-slate-800 dark:text-slate-100 truncate hover:text-blue-600 hover:underline text-left">
                  {d.donor_name || d.donor_email || 'Unnamed'}
                </button>
              ) : (
                <span className="font-bold text-slate-800 dark:text-slate-100 truncate">{d.donor_name || d.donor_email || 'New ' + label}</span>
              )}
              {d.needs_review && (
                <span title={d.review_note} className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300 shrink-0">Review</span>
              )}
              {d.slots && (
                <span className={`text-[10px] font-semibold shrink-0 ${d.slots.remaining > 0 ? 'text-emerald-600' : 'text-amber-600'}`}>
                  {d.slots.remaining > 0 ? `${d.slots.remaining} slot(s) left` : `Exceptional (${d.slots.used}/${d.slots.max})`}
                </span>
              )}
            </div>
            <button type="button" onClick={() => removeDonor(d)} title={`Remove ${label}`}
              className="p-1 rounded-md text-slate-400 hover:text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950/40">
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>
          {d.needs_review && d.review_note && (
            <span className="text-[10px] text-amber-700 dark:text-amber-400">{d.review_note}</span>
          )}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5">
            <input defaultValue={d.donor_name} placeholder="Name" onBlur={e => commitField(d, 'donor_name', e.target.value.trim())}
              className="px-2 py-1.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg" />
            <input defaultValue={d.donor_email} type="email" placeholder="Email" onBlur={e => commitField(d, 'donor_email', e.target.value.trim())}
              className="px-2 py-1.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg font-mono" />
            <input defaultValue={d.donor_phone} placeholder="Phone" onBlur={e => commitField(d, 'donor_phone', e.target.value.trim())}
              className="px-2 py-1.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg font-mono" />
            <div className="relative">
              <span className="absolute left-2 top-1.5 text-slate-400">£</span>
              <input key={`${d.key}_${d.contribution_amount}`} defaultValue={d.contribution_amount} type="number" min="0" step="0.01" placeholder="Amount"
                onBlur={e => commitField(d, 'contribution_amount', e.target.value)}
                className="w-full pl-5 pr-2 py-1.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg font-mono" />
            </div>
          </div>
          {!clean(d.donor_email) && (
            <span className="text-[10px] text-slate-500 flex items-center gap-1"><AlertTriangle className="w-3 h-3" /> No email — this {label} will be skipped when emails are sent.</span>
          )}
        </div>
      ))}

      {error && <div className="p-2 rounded-lg bg-rose-50 dark:bg-rose-950/40 text-rose-700 dark:text-rose-300 border border-rose-200 dark:border-rose-900">{error}</div>}

      {/* Add donors */}
      <div className="flex flex-col gap-1.5">
        <div className="relative">
          <Search className="w-3.5 h-3.5 absolute left-2.5 top-2.5 text-slate-400" />
          <input value={query} onChange={e => setQuery(e.target.value)}
            placeholder={`Search any ${isOrganizer ? 'contact' : 'donor'} by name, email or phone to add…`}
            className="w-full pl-8 pr-8 py-2 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg" />
          {searching && <Loader2 className="w-3.5 h-3.5 absolute right-2.5 top-2.5 animate-spin text-slate-400" />}
        </div>
        {results.length > 0 && (
          <div className="border border-slate-200 dark:border-slate-700 rounded-lg divide-y divide-slate-100 dark:divide-slate-800 bg-white dark:bg-slate-900 max-h-48 overflow-y-auto">
            {results.map((r, i) => (
              <button type="button" key={i} onClick={() => addDonor(r)}
                className="w-full text-left px-3 py-2 hover:bg-blue-50 dark:hover:bg-blue-950/40 flex items-center justify-between gap-2">
                <span className="min-w-0">
                  <span className="font-semibold text-slate-800 dark:text-slate-100 block truncate">{r.donor_name}</span>
                  <span className="text-[10px] text-slate-500 font-mono truncate block">{clean(r.donor_email) || clean(r.donor_phone) || 'No contact on file'}</span>
                </span>
                <Plus className="w-3.5 h-3.5 text-blue-600 shrink-0" />
              </button>
            ))}
          </div>
        )}
        {newRow ? (
          <div className="p-2.5 rounded-xl border border-dashed border-blue-300 dark:border-blue-800 grid grid-cols-2 sm:grid-cols-4 gap-1.5">
            <input autoFocus placeholder="Name" value={newRow.donor_name} onChange={e => setNewRow({ ...newRow, donor_name: e.target.value })}
              className="px-2 py-1.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg" />
            <input placeholder="Email" type="email" value={newRow.donor_email} onChange={e => setNewRow({ ...newRow, donor_email: e.target.value })}
              className="px-2 py-1.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg font-mono" />
            <input placeholder="Phone" value={newRow.donor_phone} onChange={e => setNewRow({ ...newRow, donor_phone: e.target.value })}
              className="px-2 py-1.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg font-mono" />
            <div className="flex gap-1">
              <button type="button" disabled={busyId === 'new'} onClick={() => addDonor({ ...newRow, donor_name: newRow.donor_name.trim(), donor_email: newRow.donor_email.trim(), donor_phone: newRow.donor_phone.trim() })}
                className="flex-1 px-2 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-bold flex items-center justify-center gap-1">
                <Check className="w-3 h-3" /> Add
              </button>
              <button type="button" onClick={() => setNewRow(null)} className="px-2 py-1.5 rounded-lg text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800">Cancel</button>
            </div>
          </div>
        ) : (
          <button type="button" onClick={() => setNewRow(blankDonor(role))}
            className="self-start px-2.5 py-1.5 rounded-lg border border-dashed border-slate-300 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:border-blue-400 hover:text-blue-600 font-semibold flex items-center gap-1.5">
            <UserRound className="w-3.5 h-3.5" /> Add {label} not in the CRM
          </button>
        )}
      </div>
    </div>
  );
}
