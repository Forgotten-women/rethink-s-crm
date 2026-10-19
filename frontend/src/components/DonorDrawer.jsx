import React, { useEffect, useMemo, useState } from 'react';
import { X, User, Mail, Phone, MapPin, Calendar, PieChart, ShieldCheck, Search, Columns, ChevronLeft, ChevronRight } from 'lucide-react';
import { API_BASE_URL } from '../config';
import DonationDetailModal from './DonationDetailModal';
import AddDonationModal, { canEditRecords } from './AddDonationModal';
import SingleEmailComposer from './email/SingleEmailComposer';
import EmailThread from './email/EmailThread';
import { Pencil, PlusCircle, Send, StickyNote, Trash2 } from 'lucide-react';

const NET = 'Total Online Donations Net Amount in Settled Currency';
const GROSS = 'Total Online Donation Gross Amount in Settled Currency';
const FEES = 'Total Processing Fees Paid by CC In Settled Currency';
const money = (v) => (v === undefined || v === null || v === 'N/A' || v === '' ? '—'
  : `£${Number(v).toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);
const clean = (v) => (v === undefined || v === null || ['n/a', 'nan', 'none', ''].includes(String(v).trim().toLowerCase()) ? '' : String(v));

// Every column the donation table can show; "core" ones are on by default.
const COLUMNS = [
  { key: 'Created Date (UTC)', label: 'Date', core: true, mono: true },
  { key: 'Donation ID', label: 'Donation ID', core: true, mono: true },
  { key: 'Platform', label: 'Platform', core: true },
  { key: 'Campaign Name', label: 'Campaign', core: true, wide: true },
  { key: 'Giving Level Title', label: 'Giving level', core: true },
  { key: 'fundraiser_name', label: 'Fundraiser', core: true },
  { key: 'Code', label: 'Code', core: true, mono: true },
  { key: 'Heading', label: 'Heading', core: true },
  { key: 'Sub-Heading', label: 'Sub-heading', core: true },
  { key: 'Programme Fund', label: 'Fund' },
  { key: 'Department', label: 'Department' },
  { key: 'Office', label: 'Office' },
  { key: 'Country', label: 'Project country' },
  { key: 'Zakat Eligibility', label: 'Zakat eligibility' },
  { key: 'Donation Amount (in Donation Currency)', label: 'Donated', money: false, core: true, amountWithCurrency: true },
  { key: GROSS, label: 'Gross', money: true },
  { key: FEES, label: 'Fees', money: true },
  { key: NET, label: 'Net', money: true, core: true },
  { key: 'Gift Aid (yes or no)', label: 'Gift Aid', core: true },
  { key: 'Zakat (yes or no)', label: 'Zakat' },
  { key: 'Payment Frequency', label: 'Frequency' },
  { key: 'Payment Type', label: 'Payment type' },
  { key: 'Status', label: 'Status', core: true },
  { key: 'Anonymous or Public', label: 'Visibility' },
  { key: 'Source', label: 'Source' },
  { key: 'Comments', label: 'Comments', wide: true },
];

export default function DonorDrawer({ donorId, onClose, activeCompany }) {
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [records, setRecords] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(100);
  const [pages, setPages] = useState(1);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [filter, setFilter] = useState('');
  const [sort, setSort] = useState({ key: 'Created Date (UTC)', dir: 'desc' });
  const [visible, setVisible] = useState(() => {
    try { const saved = JSON.parse(localStorage.getItem('donor-drawer-columns') || 'null'); if (Array.isArray(saved)) return saved; } catch { /* ignore */ }
    return COLUMNS.filter(c => c.core).map(c => c.key);
  });
  const [showColumns, setShowColumns] = useState(false);
  const [openDonation, setOpenDonation] = useState(null);
  const [cause, setCause] = useState(null); // {heading, subheading}
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [filteredNet, setFilteredNet] = useState(null);
  const [reloadTick, setReloadTick] = useState(0);
  const [editing, setEditing] = useState(null);
  const [saving, setSaving] = useState(false);
  const [editError, setEditError] = useState('');
  const [adding, setAdding] = useState(false);
  const [emailing, setEmailing] = useState(false);
  const [notes, setNotes] = useState([]);
  const [newNote, setNewNote] = useState('');
  const [noteBusy, setNoteBusy] = useState(false);
  const canEdit = canEditRecords() && activeCompany && activeCompany !== 'all';

  const resolvedDonorId = typeof donorId === 'object' && donorId !== null
    ? (donorId.donor_id || donorId.email || donorId.name || '')
    : (donorId || '');
  const fallbackDisplayName = typeof donorId === 'object' && donorId !== null
    ? (donorId.name || donorId.email || donorId.donor_id || 'Donor')
    : String(donorId || 'Donor');
  const compParam = activeCompany ? `company_id=${encodeURIComponent(activeCompany)}` : '';

  useEffect(() => {
    if (!resolvedDonorId) return;
    setLoading(true); setError(''); setPage(1); setFilter(''); setCause(null); setDateFrom(''); setDateTo('');
    fetch(`${API_BASE_URL}/api/donors/profile/${encodeURIComponent(resolvedDonorId)}${compParam ? `?${compParam}` : ''}`)
      .then(res => { if (!res.ok) throw new Error('not found'); return res.json(); })
      .then(data => { setProfile(data); setLoading(false); })
      .catch(() => { setError('This donor could not be loaded. They may belong to another charity or have no donations.'); setLoading(false); });
  }, [resolvedDonorId, activeCompany, reloadTick]);

  const noteDonorId = profile?.donor_id || resolvedDonorId;
  useEffect(() => {
    if (!noteDonorId || !activeCompany || activeCompany === 'all') { setNotes([]); return; }
    fetch(`${API_BASE_URL}/api/donors/notes?company_id=${encodeURIComponent(activeCompany)}&donor_id=${encodeURIComponent(noteDonorId)}`)
      .then(r => (r.ok ? r.json() : { notes: [] })).then(d => setNotes(d.notes || [])).catch(() => setNotes([]));
  }, [noteDonorId, activeCompany, reloadTick]);
  const addNote = async () => {
    const note = newNote.trim();
    if (!note) return;
    setNoteBusy(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/donors/notes`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ company_id: activeCompany, donor_id: noteDonorId, note }) });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `Error ${res.status}`);
      setNewNote(''); setReloadTick(t => t + 1);
    } catch (e) { window.alert(e.message); } finally { setNoteBusy(false); }
  };
  const deleteNote = async (id) => {
    if (!window.confirm('Delete this note?')) return;
    const res = await fetch(`${API_BASE_URL}/api/donors/notes/${id}?company_id=${encodeURIComponent(activeCompany)}`, { method: 'DELETE' });
    if (res.ok) setReloadTick(t => t + 1);
  };

  useEffect(() => { setPage(1); }, [cause, dateFrom, dateTo]);

  useEffect(() => {
    if (!resolvedDonorId) return;
    setHistoryLoading(true);
    const extra = new URLSearchParams();
    if (dateFrom) extra.set('date_from', dateFrom);
    if (dateTo) extra.set('date_to', dateTo);
    if (cause?.heading) extra.set('heading', cause.heading);
    if (cause?.subheading) extra.set('subheading', cause.subheading);
    fetch(`${API_BASE_URL}/api/donors/history?donor_id=${encodeURIComponent(resolvedDonorId)}${compParam ? `&${compParam}` : ''}&page=${page}&page_size=${pageSize}${extra.toString() ? `&${extra}` : ''}`)
      .then(res => res.json())
      .then(data => { setRecords(data.records || []); setTotal(data.total_records || 0); setPages(data.total_pages || 1); setFilteredNet(data.filtered_net ?? null); })
      .catch(() => setRecords([]))
      .finally(() => setHistoryLoading(false));
  }, [resolvedDonorId, activeCompany, page, pageSize, cause, dateFrom, dateTo, reloadTick]);

  const startEdit = () => {
    const parts = String(profile?.display_name || '').split(' ');
    setEditError('');
    setEditing({ first_name: clean(profile?.first_name) || parts[0] || '', last_name: clean(profile?.last_name) || parts.slice(1).join(' '),
      email: clean(profile?.email), phone: clean(profile?.phone), address: clean(profile?.billing_address), city: clean(profile?.billing_city),
      postcode: clean(profile?.billing_postcode), country: clean(profile?.billing_country), marketing_consent: clean(profile?.marketing_consent), notes: '' });
  };
  const saveEdit = async () => {
    setSaving(true); setEditError('');
    try {
      const res = await fetch(`${API_BASE_URL}/api/donors/update-donor`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ company_id: activeCompany, donor_id: profile?.donor_id || resolvedDonorId, fields: editing }) });
      const d = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(d.detail || `Error ${res.status}`);
      setEditing(null); setReloadTick(t => t + 1);
    } catch (e) { setEditError(e.message); } finally { setSaving(false); }
  };

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    if (donorId) window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [donorId, onClose]);

  useEffect(() => { try { localStorage.setItem('donor-drawer-columns', JSON.stringify(visible)); } catch { /* ignore */ } }, [visible]);

  const shown = useMemo(() => {
    const q = filter.trim().toLowerCase();
    let rows = records;
    if (q) rows = rows.filter(r => COLUMNS.some(c => String(r[c.key] ?? '').toLowerCase().includes(q)));
    const dir = sort.dir === 'asc' ? 1 : -1;
    const numeric = COLUMNS.find(c => c.key === sort.key)?.money || sort.key === 'Donation Amount (in Donation Currency)';
    return [...rows].sort((a, b) => {
      const x = a[sort.key], y = b[sort.key];
      if (numeric) return (Number(x) || 0) > (Number(y) || 0) ? dir : -dir;
      return String(x ?? '').localeCompare(String(y ?? '')) * dir;
    });
  }, [records, filter, sort]);
  const shownNet = shown.reduce((acc, r) => acc + (Number(r[NET]) || 0), 0);

  if (!donorId) return null;
  const cols = COLUMNS.filter(c => visible.includes(c.key));
  const address = [profile?.billing_city, profile?.billing_state, profile?.billing_postcode, profile?.billing_country].map(clean).filter(Boolean).join(', ');

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      {openDonation && (
        <DonationDetailModal donationId={clean(openDonation['Donation ID'])} companyId={activeCompany} initial={openDonation} onClose={() => setOpenDonation(null)} onChanged={() => setReloadTick(t => t + 1)} />
      )}
      {adding && <AddDonationModal company={activeCompany} donor={{ name: profile?.display_name, email: clean(profile?.email), phone: clean(profile?.phone), city: clean(profile?.billing_city), country: clean(profile?.billing_country) }} onClose={() => setAdding(false)} onCreated={() => setReloadTick(t => t + 1)} />}
      {emailing && <SingleEmailComposer company={activeCompany} recipient={{ email: clean(profile?.email), name: profile?.display_name || '', donor_id: profile?.donor_id || resolvedDonorId }} onClose={() => setEmailing(false)} onSent={() => setReloadTick(t => t + 1)} />}
      <div className="drawer-content drawer-wide flex flex-col panel-pop" role="dialog" aria-modal="true" aria-label="Donor details">
        {/* Header */}
        <div className="flex items-start justify-between gap-3 px-6 py-4 shrink-0" style={{ borderBottom: '1px solid var(--border-glass)' }}>
          <div className="flex items-start gap-3 min-w-0">
            <div className="w-11 h-11 rounded-2xl bg-cyan-500/15 border border-cyan-500/30 flex items-center justify-center text-cyan-500 shrink-0"><User className="w-5 h-5" /></div>
            <div className="min-w-0">
              <h2 className="text-xl font-extrabold truncate" style={{ color: 'var(--text-main)' }}>{profile?.display_name || fallbackDisplayName}</h2>
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-1 text-xs" style={{ color: 'var(--text-muted)' }}>
                {clean(profile?.email) && <span className="flex items-center gap-1"><Mail className="w-3.5 h-3.5" />{profile.email}</span>}
                {clean(profile?.phone) && <span className="flex items-center gap-1"><Phone className="w-3.5 h-3.5" />{profile.phone}</span>}
                {address && <span className="flex items-center gap-1"><MapPin className="w-3.5 h-3.5" />{address}</span>}
                {clean(profile?.donor_id) && <span className="font-mono">ID {profile.donor_id}</span>}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {profile && canEdit && <button type="button" onClick={startEdit} className="px-2.5 py-1.5 text-xs rounded-lg font-semibold border flex items-center gap-1" style={{ borderColor: 'var(--border-glass)', color: 'var(--text-main)' }}><Pencil className="w-3.5 h-3.5" /> Edit details</button>}
            {profile && canEdit && <button type="button" onClick={() => setAdding(true)} className="px-2.5 py-1.5 text-xs rounded-lg font-semibold bg-emerald-600 hover:bg-emerald-500 text-white flex items-center gap-1"><PlusCircle className="w-3.5 h-3.5" /> Add donation</button>}
            {profile && clean(profile?.email) && activeCompany !== 'all' && <button type="button" onClick={() => setEmailing(true)} className="px-2.5 py-1.5 text-xs rounded-lg font-semibold border flex items-center gap-1" style={{ borderColor: 'var(--border-glass)', color: 'var(--text-main)' }}><Send className="w-3.5 h-3.5 text-sky-500" /> Email</button>}
            <button onClick={onClose} className="w-8 h-8 rounded-full flex items-center justify-center" style={{ backgroundColor: 'var(--input-bg)', color: 'var(--text-sub)' }} aria-label="Close donor details">
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {loading ? (
          <div className="p-6"><div className="glass-panel p-6 animate-pulse h-40" /></div>
        ) : error ? (
          <div className="p-6"><div className="glass-panel p-5 text-sm font-semibold text-rose-500">{error}</div></div>
        ) : (
          <div className="flex-1 min-h-0 overflow-y-auto px-6 py-5 flex flex-col gap-5">
            {editing && (
              <div className="glass-panel p-4 flex flex-col gap-3 border border-cyan-500/30">
                <div className="text-xs font-black uppercase tracking-wider" style={{ color: 'var(--text-main)' }}>Edit donor details <span className="normal-case font-normal" style={{ color: 'var(--text-muted)' }}>(applied to all of their donations)</span></div>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                  {[['first_name', 'First name'], ['last_name', 'Last name'], ['email', 'Email'], ['phone', 'Phone'], ['address', 'Address'], ['city', 'City'], ['postcode', 'Postcode'], ['country', 'Country']].map(([k, l]) => (
                    <label key={k} className="flex flex-col gap-1 text-[11px] font-semibold" style={{ color: 'var(--text-sub)' }}>{l}
                      <input value={editing[k] || ''} onChange={e => setEditing(v => ({ ...v, [k]: e.target.value }))} className="px-2 py-1.5 text-sm rounded-lg font-normal" style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' }} />
                    </label>
                  ))}
                  <label className="flex flex-col gap-1 text-[11px] font-semibold" style={{ color: 'var(--text-sub)' }}>Marketing consent
                    <select value={editing.marketing_consent || ''} onChange={e => setEditing(v => ({ ...v, marketing_consent: e.target.value }))} className="px-2 py-1.5 text-sm rounded-lg font-normal" style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' }}>
                      <option value="">Unknown</option><option value="yes">Yes</option><option value="no">No</option>
                    </select>
                  </label>
                  <label className="col-span-2 md:col-span-4 flex flex-col gap-1 text-[11px] font-semibold" style={{ color: 'var(--text-sub)' }}>Notes <span className="font-normal" style={{ color: 'var(--text-muted)' }}>(added to their notes with your name and today's date)</span>
                    <textarea value={editing.notes || ''} onChange={e => setEditing(v => ({ ...v, notes: e.target.value }))} rows={3} placeholder="e.g. Prefers WhatsApp; called 16 Oct about Hafiz renewal"
                      className="px-2 py-1.5 text-sm rounded-lg font-normal" style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' }} />
                  </label>
                </div>
                {editError && <div className="text-xs text-rose-500">{editError}</div>}
                <div className="flex gap-2 justify-end">
                  <button type="button" onClick={() => setEditing(null)} className="px-3 py-1.5 text-xs rounded-lg font-semibold" style={{ color: 'var(--text-sub)' }}>Cancel</button>
                  <button type="button" onClick={saveEdit} disabled={saving} className="px-3 py-1.5 text-xs rounded-lg font-bold bg-cyan-600 hover:bg-cyan-500 text-white disabled:opacity-50">{saving ? 'Saving…' : 'Save'}</button>
                </div>
              </div>
            )}
            {/* Key figures */}
            <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-3">
              {[
                ['Total given', money(profile?.manual_total && profile?.platform !== 'Manual (Sponsorship Tracker)' ? (profile?.total_ltv || 0) + profile.manual_total : profile?.total_ltv),
                  `${(profile?.total_donations_count || 0).toLocaleString()} donations${profile?.manual_total ? ` · ${money(profile.manual_total)} recorded in Sponsorship Tracker` : ''}`],
                ['Average gift', money(profile?.avg_donation), 'per donation'],
                ['Lifetime tier', profile?.lifetime_tier || '—', `Transaction tier: ${profile?.transaction_tier || '—'}`],
                ['Giving pattern', clean(profile?.payment_frequency) || '—', clean(profile?.payment_type) || ''],
                ['Gift Aid', clean(profile?.gift_aid) || '—', `Tax receipt: ${clean(profile?.tax_receipt_requested) || '—'}`],
                ['Marketing consent', clean(profile?.marketing_consent) || '—', `Shown as: ${clean(profile?.anonymous_public) || '—'}`],
              ].map(([label, value, sub]) => (
                <div key={label} className="glass-panel p-3 min-w-0">
                  <div className="text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--text-sub)' }}>{label}</div>
                  <div className="text-base font-black mt-0.5 truncate tabular-nums" style={{ color: 'var(--text-main)' }}>{value}</div>
                  <div className="text-[10px] truncate" style={{ color: 'var(--text-muted)' }}>{sub}</div>
                </div>
              ))}
            </div>

            {/* Notes */}
            {(notes.length > 0 || canEdit) && (
              <div className="glass-panel p-3 flex flex-col gap-2">
                <h3 className="text-xs font-extrabold uppercase tracking-wider flex items-center gap-2" style={{ color: 'var(--text-main)' }}>
                  <StickyNote className="w-4 h-4 text-amber-500" /> Notes ({notes.length})
                </h3>
                {notes.map(n => (
                  <div key={n.id} className="rounded-lg px-3 py-2 text-xs bg-amber-50 border border-amber-200 dark:bg-amber-950/30 dark:border-amber-900 flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="whitespace-pre-wrap text-slate-800 dark:text-slate-100">{n.note}</div>
                      <div className="mt-1 text-[10px] text-slate-500">{n.created_by || 'Someone'} · {String(n.created_at || '').slice(0, 16)}</div>
                    </div>
                    {canEdit && <button type="button" onClick={() => deleteNote(n.id)} aria-label="Delete note" className="p-1 rounded text-slate-400 hover:text-rose-500"><Trash2 className="w-3.5 h-3.5" /></button>}
                  </div>
                ))}
                {canEdit && (
                  <div className="flex gap-2 items-end">
                    <textarea value={newNote} onChange={e => setNewNote(e.target.value)} rows={2} placeholder="Add a note about this donor"
                      className="flex-1 px-2 py-1.5 text-sm rounded-lg" style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' }} />
                    <button type="button" onClick={addNote} disabled={noteBusy || !newNote.trim()} className="px-3 py-2 text-xs rounded-lg font-bold bg-amber-500 hover:bg-amber-400 text-white disabled:opacity-40">{noteBusy ? 'Saving…' : 'Add note'}</button>
                  </div>
                )}
              </div>
            )}

            {/* Where the money went */}
            {profile?.category_breakdown?.length > 0 && (
              <div>
                <h3 className="text-xs font-extrabold uppercase tracking-wider flex items-center gap-2 mb-2" style={{ color: 'var(--text-main)' }}>
                  <PieChart className="w-4 h-4 text-purple-500" /> Where their giving went
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-2">
                  {profile.category_breakdown.map((cat, i) => {
                    const active = cause && cause.subheading === cat.subheading && cause.heading === cat.heading;
                    return (
                    <button type="button" key={i} onClick={() => setCause(active ? null : { heading: cat.heading, subheading: cat.subheading })}
                      title={active ? 'Show all donations again' : 'Show only these donations below'}
                      className={`glass-panel p-2.5 flex items-center justify-between gap-2 min-w-0 text-left transition-all hover:ring-2 hover:ring-cyan-500/40 ${active ? 'ring-2 ring-cyan-500' : ''}`}>
                      <div className="min-w-0">
                        <div className="text-xs font-bold truncate" style={{ color: 'var(--text-main)' }} title={cat.subheading}>{cat.subheading}</div>
                        <div className="text-[10px] truncate" style={{ color: 'var(--text-muted)' }}>{cat.heading} · {cat.count} donations</div>
                      </div>
                      <div className="text-right shrink-0">
                        <div className="text-xs font-extrabold text-cyan-600 dark:text-cyan-400 tabular-nums">{money(cat.total_amount)}</div>
                        <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{cat.percentage}%</div>
                      </div>
                    </button>
                    );
                  })}
                </div>
              </div>
            )}

            <div className="flex flex-wrap gap-x-6 gap-y-1 text-[11px]" style={{ color: 'var(--text-muted)' }}>
              <span className="flex items-center gap-1"><ShieldCheck className="w-3.5 h-3.5 text-emerald-500" />Platform: <b style={{ color: 'var(--text-main)' }}>{clean(profile?.platform) || '—'}</b></span>
              <span>Source: <b style={{ color: 'var(--text-main)' }}>{clean(profile?.source) || '—'}</b></span>
              <span>Settlement currency: <b style={{ color: 'var(--text-main)' }}>{clean(profile?.settlement_currency) || '—'}</b></span>
            </div>

            {/* Every donation */}
            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <h3 className="text-xs font-extrabold uppercase tracking-wider flex items-center gap-2" style={{ color: 'var(--text-main)' }}>
                  <Calendar className="w-4 h-4 text-cyan-500" /> All donations ({total.toLocaleString()})
                </h3>
                <div className="flex items-center gap-2 flex-wrap">
                  {cause && (
                    <span className="text-[11px] px-2 py-1 rounded-full bg-cyan-500/15 text-cyan-700 dark:text-cyan-300 flex items-center gap-1 font-semibold">
                      {cause.subheading || cause.heading}<button type="button" onClick={() => setCause(null)} aria-label="Clear cause filter"><X className="w-3 h-3" /></button>
                    </span>
                  )}
                  <label className="flex items-center gap-1 text-[11px]" style={{ color: 'var(--text-sub)' }}>From
                    <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} className="px-1.5 py-1 text-xs rounded-lg" style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' }} />
                  </label>
                  <label className="flex items-center gap-1 text-[11px]" style={{ color: 'var(--text-sub)' }}>to
                    <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} className="px-1.5 py-1 text-xs rounded-lg" style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' }} />
                  </label>
                  {(dateFrom || dateTo) && <button type="button" onClick={() => { setDateFrom(''); setDateTo(''); }} className="text-[11px] text-cyan-600">Clear dates</button>}
                  <span className="relative">
                    <Search className="w-3.5 h-3.5 absolute left-2 top-1/2 -translate-y-1/2 text-slate-400" />
                    <input id="donor-drawer-filter" value={filter} onChange={e => setFilter(e.target.value)} placeholder="Filter these donations"
                      className="pl-7 pr-2 py-1 text-xs rounded-lg w-56" style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' }} />
                  </span>
                  <div className="relative">
                    <button type="button" onClick={() => setShowColumns(v => !v)} className="px-2 py-1 text-xs rounded-lg flex items-center gap-1 font-semibold"
                      style={{ backgroundColor: 'var(--input-bg)', color: 'var(--text-main)', border: '1px solid var(--input-border)' }} aria-expanded={showColumns}>
                      <Columns className="w-3.5 h-3.5" /> Columns ({cols.length})
                    </button>
                    {showColumns && (
                      <div className="absolute right-0 mt-1 z-20 w-60 max-h-80 overflow-y-auto rounded-lg border shadow-xl p-2 flex flex-col gap-0.5"
                        style={{ backgroundColor: 'var(--drawer-bg)', borderColor: 'var(--border-glass)' }}>
                        {COLUMNS.map(c => (
                          <label key={c.key} className="flex items-center gap-2 text-xs px-1 py-0.5 cursor-pointer" style={{ color: 'var(--text-main)' }}>
                            <input type="checkbox" checked={visible.includes(c.key)}
                              onChange={() => setVisible(v => (v.includes(c.key) ? v.filter(k => k !== c.key) : [...v, c.key]))} />
                            {c.label}
                          </label>
                        ))}
                        <button type="button" onClick={() => setVisible(COLUMNS.map(c => c.key))} className="text-[11px] text-cyan-600 mt-1 text-left">Show all</button>
                      </div>
                    )}
                  </div>
                  <select id="donor-drawer-pagesize" value={pageSize} onChange={e => { setPageSize(Number(e.target.value)); setPage(1); }}
                    className="px-2 py-1 text-xs rounded-lg" style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' }}>
                    {[50, 100, 200, 500].map(n => <option key={n} value={n}>{n} per page</option>)}
                  </select>
                </div>
              </div>

              <div className="glass-panel overflow-hidden">
                <div className="overflow-auto max-h-[55vh]">
                  <table className="w-full text-xs">
                    <thead className="sticky top-0 z-10" style={{ backgroundColor: 'var(--drawer-bg)' }}>
                      <tr style={{ color: 'var(--text-sub)' }}>
                        {cols.map(c => (
                          <th key={c.key} className={`px-2.5 py-2 text-[10px] font-bold uppercase tracking-wider whitespace-nowrap ${c.money || c.amountWithCurrency ? 'text-right' : 'text-left'}`}>
                            <button type="button" onClick={() => setSort(s => ({ key: c.key, dir: s.key === c.key && s.dir === 'desc' ? 'asc' : 'desc' }))} className="uppercase hover:text-cyan-500">
                              {c.label}{sort.key === c.key ? (sort.dir === 'desc' ? ' ↓' : ' ↑') : ''}
                            </button>
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className={historyLoading ? 'opacity-50' : ''}>
                      {shown.length === 0 && (
                        <tr><td colSpan={cols.length} className="px-3 py-8 text-center" style={{ color: 'var(--text-muted)' }}>{historyLoading ? 'Loading donations…' : 'No donations match.'}</td></tr>
                      )}
                      {shown.map((r, i) => (
                        <tr key={`${r['Donation ID']}-${i}`} className={`border-t ${clean(r['Donation ID']) ? 'cursor-pointer hover:bg-cyan-500/5' : ''}`} style={{ borderColor: 'var(--border-glass)' }}
                          onClick={() => clean(r['Donation ID']) && setOpenDonation(r)} title={clean(r['Donation ID']) ? 'Click for full donation details' : undefined}>
                          {cols.map(c => {
                            const raw = r[c.key];
                            let text = clean(raw);
                            if (c.money) text = money(raw);
                            if (c.amountWithCurrency) text = clean(raw) ? `${Number(raw).toLocaleString('en-GB', { maximumFractionDigits: 2 })} ${clean(r['Donation Currency (DC)'])}` : '—';
                            if (c.key === 'Created Date (UTC)') text = String(raw || '').split('T')[0];
                            return (
                              <td key={c.key} title={clean(raw)}
                                className={`px-2.5 py-1.5 align-top ${c.money || c.amountWithCurrency ? 'text-right tabular-nums whitespace-nowrap' : ''} ${c.mono ? 'font-mono whitespace-nowrap' : ''} ${c.wide ? 'min-w-[14rem]' : 'whitespace-nowrap'} ${c.key === NET ? 'font-black text-cyan-600 dark:text-cyan-400' : ''}`}
                                style={c.key === NET ? undefined : { color: 'var(--text-main)' }}>
                                {text || '—'}
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="flex items-center justify-between gap-2 flex-wrap px-3 py-2 border-t text-xs" style={{ borderColor: 'var(--border-glass)', color: 'var(--text-muted)' }}>
                  <span>{filter ? `${shown.length} shown on this page · net ${money(shownNet)}` : `Net on this page: ${money(shownNet)}`}{(cause || dateFrom || dateTo) && filteredNet != null ? ` · ${total.toLocaleString()} matching donations, net ${money(filteredNet)}` : ''}</span>
                  {pages > 1 && (
                    <span className="flex items-center gap-2">
                      <button type="button" disabled={page <= 1 || historyLoading} onClick={() => setPage(p => p - 1)} className="p-1 rounded disabled:opacity-30" aria-label="Previous page"><ChevronLeft className="w-4 h-4" /></button>
                      Page {page} of {pages}
                      <button type="button" disabled={page >= pages || historyLoading} onClick={() => setPage(p => p + 1)} className="p-1 rounded disabled:opacity-30" aria-label="Next page"><ChevronRight className="w-4 h-4" /></button>
                    </span>
                  )}
                </div>
              </div>
            </div>
            {/* Every email with this person and every reply */}
            {clean(profile?.email) && activeCompany !== 'all' && (
              <div>
                <h3 className="text-xs font-extrabold uppercase tracking-wider flex items-center gap-2 mb-2" style={{ color: 'var(--text-main)' }}>
                  <Mail className="w-4 h-4 text-sky-500" /> Email thread
                </h3>
                <EmailThread company={activeCompany} email={clean(profile?.email)} reloadKey={reloadTick} />
              </div>
            )}
          </div>
        )}
      </div>
    </>
  );
}
