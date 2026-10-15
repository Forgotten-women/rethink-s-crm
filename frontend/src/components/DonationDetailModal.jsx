import React, { useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  X, Receipt, User, Mail, Phone, MapPin, Calendar, Tag, Layers, Wallet, CreditCard, Link2, Copy, Check,
  Search, Gift, ExternalLink, ChevronDown, ChevronUp, Info,
} from 'lucide-react';
import { API_BASE_URL } from '../config';
import { canEditRecords, useProjectCodes } from './AddDonationModal';
import { Pencil, Trash2, Save } from 'lucide-react';

// Fields that can be edited on one donation (column -> label). Amounts only for donations added by hand.
const EDIT_FIELDS = [
  ['First Name', 'First name'], ['Last Name', 'Last name'], ['Email', 'Email'], ['Phone Number', 'Phone'],
  ['Billing Address', 'Address'], ['Billing City', 'City'], ['Billing Zip', 'Postcode'], ['Billing Country', 'Country'],
  ['Created Date (UTC)', 'Date', 'date'], ['Status', 'Status'], ['Payment Type', 'Payment method'], ['Payment Frequency', 'Frequency'],
  ['Campaign Name', 'Campaign'], ['Giving Level Title', 'Giving level'], ['fundraiser_name', 'Fundraiser'],
  ['Gift Aid (yes or no)', 'Gift Aid (Yes/No)'], ['Zakat (yes or no)', 'Zakat (Yes/No)'], ['Anonymous or Public', 'Anonymous or Public'],
  ['Comments', 'Comments'],
];
const AMOUNT_FIELDS = [['Total Online Donation Gross Amount in Settled Currency', 'Gross (GBP)'], ['Total Processing Fees Paid by CC In Settled Currency', 'Fees (GBP)'],
  ['Total Online Donations Net Amount in Settled Currency', 'Net received (GBP)'], ['Donation Amount (in Donation Currency)', 'Donated (original currency)']];

const NET = 'Total Online Donations Net Amount in Settled Currency';
const GROSS = 'Total Online Donation Gross Amount in Settled Currency';
const FEES = 'Total Processing Fees Paid by CC In Settled Currency';

const isBlank = (v) => v === undefined || v === null || ['', 'nan', 'none', 'null', 'n/a', 'nat'].includes(String(v).trim().toLowerCase());
const num = (v) => (isBlank(v) || Number.isNaN(Number(v)) ? null : Number(v));
const fmtMoney = (v, cur = 'GBP') => {
  const n = num(v);
  if (n === null) return '—';
  try { return n.toLocaleString('en-GB', { style: 'currency', currency: String(cur || 'GBP').toUpperCase().slice(0, 3) }); }
  catch { return `${n.toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${cur || ''}`.trim(); }
};
const pick = (d, ...keys) => { for (const k of keys) if (!isBlank(d?.[k])) return d[k]; return null; };
const yes = (v) => ['yes', 'true', '1', 'y'].includes(String(v ?? '').trim().toLowerCase());
const isUrl = (v) => /^https?:\/\//i.test(String(v || ''));

// Field groups; every field not listed here still appears under "All other fields".
const SECTIONS = [
  { title: 'Donor', icon: User, fields: [
    ['Name', d => [pick(d, 'First Name'), pick(d, 'Last Name')].filter(Boolean).join(' ') || pick(d, 'Billing Name', 'Display Name')],
    ['Shown publicly as', 'Display Name'], ['Email', 'Email'], ['Phone', 'Phone Number', 'Phone'], ['Donor ID', 'Donor ID'],
    ['Billing address', d => [pick(d, 'Billing Address', 'Billing Address Line 1'), pick(d, 'Billing City'), pick(d, 'Billing State'), pick(d, 'Billing Postcode', 'Billing Zip'), pick(d, 'Billing Country')].filter(Boolean).join(', ')],
    ['Anonymous or public', 'Anonymous or Public'], ['Marketing consent', 'Marketing Consent'],
    ['Lifetime tier', 'Lifetime Donor Classification'], ['Gift tier', 'Transaction Donor Classification'],
  ] },
  { title: 'Campaign & page', icon: Link2, fields: [
    ['Campaign', 'Campaign Name'], ['Giving level', 'Giving Level Title'], ['Fundraiser', 'fundraiser_name', 'Fundraiser Name'],
    ['Campaign page', 'Campaign URL', 'campaign_url'], ['Fundraiser page', 'Fundraiser URL', 'fundraiser_url'],
    ['Community page', 'Community URL', 'community_url'], ['Platform', 'Platform'], ['Source', 'Source'],
  ] },
  { title: 'Classification', icon: Layers, fields: [
    ['Code', 'Code'], ['Old code', 'Old Code'], ['Heading', 'Heading'], ['Sub-heading', 'Sub-Heading'],
    ['Programme fund', 'Programme Fund'], ['Fund code', 'Fund Code'], ['Department', 'Department'], ['Office', 'Office'],
    ['Portfolio', 'Portfolio'], ['Project country', 'Country'], ['Zakat eligibility', 'Zakat Eligibility'], ['Classification', 'Classification'],
  ] },
  { title: 'Payment', icon: CreditCard, fields: [
    ['Status', 'Status'], ['Transaction type', 'Transaction Type'], ['Payment type', 'Payment Type'],
    ['Frequency', 'Payment Frequency', 'Frequency'], ['Payment method', 'Payment Method'], ['Card brand', 'Card Brand'],
    ['Payout settled', 'Payout Settled', 'payout_settled'], ['Payout / transfer ID', 'Transfer ID', 'Payout ID'],
    ['Tax receipt requested', 'Tax Receipt Requested'], ['Comments', 'Comments'],
  ] },
];

function CopyButton({ value }) {
  const [done, setDone] = useState(false);
  return (
    <button type="button" aria-label="Copy" title="Copy"
      onClick={(e) => { e.stopPropagation(); navigator.clipboard?.writeText(String(value)).then(() => { setDone(true); setTimeout(() => setDone(false), 1200); }); }}
      className="opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity p-0.5 rounded text-slate-400 hover:text-cyan-500 shrink-0">
      {done ? <Check className="w-3 h-3 text-emerald-500" /> : <Copy className="w-3 h-3" />}
    </button>
  );
}

function Value({ v }) {
  if (isUrl(v)) {
    return (
      <a href={v} target="_blank" rel="noopener noreferrer" className="text-cyan-600 dark:text-cyan-400 hover:underline break-all inline-flex items-start gap-1">
        {String(v).replace(/^https?:\/\/(www\.)?/, '')}<ExternalLink className="w-3 h-3 mt-0.5 shrink-0" />
      </a>
    );
  }
  return <span className="break-words">{String(v)}</span>;
}

function Field({ label, value }) {
  return (
    <div className="group flex flex-col gap-0.5 min-w-0">
      <span className="text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--text-sub)' }}>{label}</span>
      <span className="text-sm flex items-start gap-1.5 min-w-0" style={{ color: 'var(--text-main)' }}>
        <Value v={value} /><CopyButton value={value} />
      </span>
    </div>
  );
}

/**
 * Popup with every detail of one donation. Opened from the donor panel and the Donations (explorer) table.
 * Pass `donationId` (fetched within `companyId`) and optionally `initial` (the row already on screen, shown instantly).
 */
export default function DonationDetailModal({ donationId, companyId, initial, onClose, onChanged }) {
  const [data, setData] = useState(initial || null);
  const [manual, setManual] = useState(false);
  const [duplicates, setDuplicates] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showAll, setShowAll] = useState(false);
  const [fieldFilter, setFieldFilter] = useState('');
  const [editing, setEditing] = useState(null);
  const [saving, setSaving] = useState(false);
  const [editError, setEditError] = useState('');
  const [reloadTick, setReloadTick] = useState(0);
  const codes = useProjectCodes(companyId);

  useEffect(() => {
    if (!donationId) return undefined;
    let alive = true;
    setLoading(true); setError('');
    const qs = companyId ? `?company_id=${encodeURIComponent(companyId)}` : '';
    fetch(`${API_BASE_URL}/api/donors/donation/${encodeURIComponent(donationId)}${qs}`)
      .then(async r => { if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `Error ${r.status}`); return r.json(); })
      .then(j => { if (!alive) return; setData(j.donation); setManual(!!j.manual); setDuplicates(j.duplicates || 0); })
      .catch(e => { if (alive) setError(e.message); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [donationId, companyId, reloadTick]);

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') { e.stopPropagation(); onClose(); } };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [onClose]);

  const d = data || {};
  const settleCur = pick(d, 'Settlement Currency') || 'GBP';
  const donCur = pick(d, 'Donation Currency (DC)') || settleCur;
  const donated = pick(d, 'Donation Amount (in Donation Currency)');
  const gross = pick(d, GROSS);
  const fees = pick(d, FEES);
  const net = pick(d, NET);
  const giftAid = yes(pick(d, 'Gift Aid (yes or no)', 'Gift Aid'));
  const zakat = yes(pick(d, 'Zakat (yes or no)', 'Zakat'));
  const date = [pick(d, 'Created Date (UTC)'), pick(d, 'Created Time (UTC)')].filter(Boolean).join(' ').replace('T', ' ').replace(/\.\d+.*$/, '');
  const status = pick(d, 'Status');
  const name = [pick(d, 'First Name'), pick(d, 'Last Name')].filter(Boolean).join(' ') || pick(d, 'Billing Name', 'Display Name', 'Email') || 'Unnamed donor';
  const isManualEntry = String(d.Source || '') === 'Manual Entry';
  const canEdit = canEditRecords() && companyId && companyId !== 'all' && !manual && data && !error;
  const startEdit = () => {
    const f = {};
    [...EDIT_FIELDS, ...(isManualEntry ? AMOUNT_FIELDS : []), ['Code', 'Code']].forEach(([k]) => { f[k] = d[k] ?? ''; });
    setEditError(''); setEditing(f);
  };
  const saveEdit = async () => {
    setSaving(true); setEditError('');
    try {
      const changed = Object.fromEntries(Object.entries(editing).filter(([k, v]) => String(v ?? '') !== String(d[k] ?? '')));
      if (!Object.keys(changed).length) { setEditing(null); return; }
      if (changed.Code && !codes.some(c => c.code.toUpperCase() === String(changed.Code).toUpperCase())) throw new Error(`'${changed.Code}' isn't one of this charity's codes.`);
      const res = await fetch(`${API_BASE_URL}/api/donors/update-record`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ company_id: companyId, donation_id: donationId, updated_fields: changed }) });
      const j = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(j.detail || `Error ${res.status}`);
      setEditing(null); setReloadTick(t => t + 1); onChanged?.();
    } catch (e) { setEditError(e.message); } finally { setSaving(false); }
  };
  const deleteManual = async () => {
    if (!window.confirm('Delete this manually added donation? This cannot be undone.')) return;
    try {
      const res = await fetch(`${API_BASE_URL}/api/donors/donations/${encodeURIComponent(donationId)}?company_id=${encodeURIComponent(companyId)}`, { method: 'DELETE' });
      const j = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(j.detail || `Error ${res.status}`);
      onChanged?.(); onClose();
    } catch (e) { setEditError(e.message); }
  };

  const { sections, rest } = useMemo(() => {
    const used = new Set([GROSS, FEES, NET, 'Donation Amount (in Donation Currency)', 'Donation Currency (DC)', 'Settlement Currency',
      'Created Date (UTC)', 'Created Time (UTC)', 'Donation ID', 'Gift Aid (yes or no)', 'Zakat (yes or no)', 'First Name', 'Last Name', 'Billing Name']);
    const secs = SECTIONS.map(s => ({
      ...s,
      items: s.fields.map(([label, ...keys]) => {
        if (typeof keys[0] === 'function') return [label, keys[0](d)];
        const k = keys.find(key => !isBlank(d[key]));
        if (k) used.add(k);
        keys.forEach(key => used.add(key));
        return [label, k ? d[k] : null];
      }).filter(([, v]) => !isBlank(v)),
    })).filter(s => s.items.length);
    ['Billing Address', 'Billing Address Line 1', 'Billing City', 'Billing State', 'Billing Postcode', 'Billing Zip', 'Billing Country'].forEach(k => used.add(k));
    const others = Object.entries(d).filter(([k, v]) => !used.has(k) && !isBlank(v)).sort(([a], [b]) => a.localeCompare(b));
    return { sections: secs, rest: others };
  }, [d]);
  const restShown = fieldFilter ? rest.filter(([k, v]) => `${k} ${v}`.toLowerCase().includes(fieldFilter.toLowerCase())) : rest;

  const statusTone = /fail|refund|declin|cancel|dispute/i.test(status || '') ? 'bg-rose-500/15 text-rose-600 dark:text-rose-400 border-rose-500/30'
    : /pend|process/i.test(status || '') ? 'bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/30'
    : 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30';

  return createPortal(
    <div className="fixed inset-0 z-[80] flex items-center justify-center p-3 sm:p-6" role="dialog" aria-modal="true" aria-label="Donation details">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-5xl max-h-[92vh] flex flex-col rounded-2xl shadow-2xl overflow-hidden border"
        style={{ backgroundColor: 'var(--bg-card, var(--bg-main))', borderColor: 'var(--border-glass)' }}>
        {/* Hero */}
        <div className="relative px-6 pt-5 pb-4 bg-gradient-to-br from-cyan-500/15 via-sky-500/5 to-transparent border-b" style={{ borderColor: 'var(--border-glass)' }}>
          <div className="absolute top-4 right-4 flex items-center gap-2">
            {canEdit && !editing && <button type="button" onClick={startEdit} className="px-2.5 py-1.5 text-xs rounded-lg font-semibold border flex items-center gap-1" style={{ borderColor: 'var(--border-glass)', color: 'var(--text-main)' }}><Pencil className="w-3.5 h-3.5" /> Edit</button>}
            {canEdit && isManualEntry && !editing && <button type="button" onClick={deleteManual} className="px-2.5 py-1.5 text-xs rounded-lg font-semibold text-rose-600 border border-rose-500/30 flex items-center gap-1"><Trash2 className="w-3.5 h-3.5" /> Delete</button>}
            <button type="button" onClick={onClose} aria-label="Close donation details"
              className="w-8 h-8 rounded-full flex items-center justify-center hover:bg-black/10" style={{ color: 'var(--text-sub)' }}>
              <X className="w-4 h-4" />
            </button>
          </div>
          <div className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-wider" style={{ color: 'var(--text-sub)' }}>
            <Receipt className="w-3.5 h-3.5 text-cyan-500" /> Donation
            <span className="font-mono normal-case tracking-normal group inline-flex items-center gap-1" style={{ color: 'var(--text-main)' }}>
              {donationId}<CopyButton value={donationId} />
            </span>
            {manual && <span className="px-2 py-0.5 rounded-full border text-[10px] bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/30 normal-case">Recorded in Sponsorship Tracker</span>}
          </div>
          <div className="mt-3 flex flex-wrap items-end gap-x-8 gap-y-3 pr-10">
            <div>
              <div className="text-3xl sm:text-4xl font-black tabular-nums text-cyan-600 dark:text-cyan-400">
                {fmtMoney(donated ?? net, donated !== null ? donCur : settleCur)}
              </div>
              <div className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
                {loading && !data ? 'Loading…' : `${name}${date ? ` · ${date}` : ''}`}
              </div>
            </div>
            <div className="flex flex-wrap gap-1.5 pb-1">
              {status && <span className={`px-2.5 py-0.5 rounded-full border text-[11px] font-bold capitalize ${statusTone}`}>{status}</span>}
              {pick(d, 'Platform') && <span className="px-2.5 py-0.5 rounded-full border text-[11px] font-bold bg-sky-500/10 text-sky-600 dark:text-sky-400 border-sky-500/30">{pick(d, 'Platform')}</span>}
              {giftAid && <span className="px-2.5 py-0.5 rounded-full border text-[11px] font-bold bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30 inline-flex items-center gap-1"><Gift className="w-3 h-3" />Gift Aid</span>}
              {zakat && <span className="px-2.5 py-0.5 rounded-full border text-[11px] font-bold bg-violet-500/15 text-violet-600 dark:text-violet-400 border-violet-500/30">Zakat</span>}
              {pick(d, 'Code') && <span className="px-2.5 py-0.5 rounded-full border text-[11px] font-mono font-bold border-slate-400/30" style={{ color: 'var(--text-main)' }}>{pick(d, 'Code')}</span>}
            </div>
          </div>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto px-6 py-5 flex flex-col gap-5">
          {error && <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 text-rose-600 dark:text-rose-400 text-sm px-4 py-3">Couldn't load this donation: {error}</div>}
          {duplicates > 0 && (
            <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300 text-xs px-4 py-2 flex items-center gap-2">
              <Info className="w-3.5 h-3.5" /> {duplicates} more record{duplicates > 1 ? 's' : ''} share this donation ID; showing the first.
            </div>
          )}

          {editing && (
            <section className="rounded-xl border border-cyan-500/30 p-4 flex flex-col gap-3">
              <div className="text-xs font-black uppercase tracking-wider" style={{ color: 'var(--text-main)' }}>Edit donation {!isManualEntry && <span className="normal-case font-normal" style={{ color: 'var(--text-muted)' }}>(amounts come from the platform and stay locked)</span>}</div>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
                {[...EDIT_FIELDS, ...(isManualEntry ? AMOUNT_FIELDS : [])].map(([k, label, type]) => (
                  <label key={k} className="flex flex-col gap-1 text-[11px] font-semibold" style={{ color: 'var(--text-sub)' }}>{label}
                    <input type={type || 'text'} value={editing[k] ?? ''} onChange={e => setEditing(v => ({ ...v, [k]: e.target.value }))}
                      className="px-2 py-1.5 text-sm rounded-lg font-normal" style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' }} />
                  </label>
                ))}
                <label className="flex flex-col gap-1 text-[11px] font-semibold" style={{ color: 'var(--text-sub)' }}>Project code (classification follows)
                  <input list="donation-edit-codes" value={editing.Code ?? ''} onChange={e => setEditing(v => ({ ...v, Code: e.target.value.toUpperCase() }))}
                    className="px-2 py-1.5 text-sm rounded-lg font-mono font-normal" style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' }} />
                  <datalist id="donation-edit-codes">{codes.map(c => <option key={c.code} value={c.code}>{[c.heading || c.department, c.sub_heading || c.office].filter(Boolean).join(' · ')}</option>)}</datalist>
                </label>
              </div>
              {editError && <div className="text-xs text-rose-500">{editError}</div>}
              <div className="flex justify-end gap-2">
                <button type="button" onClick={() => setEditing(null)} className="px-3 py-1.5 text-xs rounded-lg font-semibold" style={{ color: 'var(--text-sub)' }}>Cancel</button>
                <button type="button" onClick={saveEdit} disabled={saving} className="px-3 py-1.5 text-xs rounded-lg font-bold bg-cyan-600 hover:bg-cyan-500 text-white disabled:opacity-50 flex items-center gap-1"><Save className="w-3.5 h-3.5" />{saving ? 'Saving…' : 'Save changes'}</button>
              </div>
            </section>
          )}
          {!editing && editError && <div className="text-xs text-rose-500">{editError}</div>}

          {/* Money flow */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {[
              ['Donated', fmtMoney(donated, donCur), donCur !== settleCur ? `in ${donCur}` : 'donor paid', Wallet],
              ['Gross settled', fmtMoney(gross, settleCur), `in ${settleCur}`, Tag],
              ['Fees', fmtMoney(fees, settleCur), num(gross) && num(fees) !== null ? `${((num(fees) / num(gross)) * 100).toFixed(1)}% of gross` : 'processing', CreditCard],
              ['Net received', fmtMoney(net, settleCur), 'after fees', Receipt],
            ].map(([label, value, sub, Icon], i) => (
              <div key={label} className={`rounded-xl border p-3 ${i === 3 ? 'bg-cyan-500/10 border-cyan-500/30' : ''}`} style={i === 3 ? undefined : { borderColor: 'var(--border-glass)' }}>
                <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--text-sub)' }}><Icon className="w-3 h-3" />{label}</div>
                <div className={`text-lg font-black tabular-nums mt-0.5 ${i === 3 ? 'text-cyan-600 dark:text-cyan-400' : ''}`} style={i === 3 ? undefined : { color: 'var(--text-main)' }}>{value}</div>
                <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{sub}</div>
              </div>
            ))}
          </div>

          {/* Quick facts */}
          <div className="flex flex-wrap gap-x-5 gap-y-1.5 text-xs" style={{ color: 'var(--text-muted)' }}>
            {date && <span className="flex items-center gap-1"><Calendar className="w-3.5 h-3.5" />{date} UTC</span>}
            {pick(d, 'Email') && <span className="flex items-center gap-1"><Mail className="w-3.5 h-3.5" />{pick(d, 'Email')}</span>}
            {pick(d, 'Phone Number', 'Phone') && <span className="flex items-center gap-1"><Phone className="w-3.5 h-3.5" />{pick(d, 'Phone Number', 'Phone')}</span>}
            {pick(d, 'Billing City', 'Billing Country') && <span className="flex items-center gap-1"><MapPin className="w-3.5 h-3.5" />{[pick(d, 'Billing City'), pick(d, 'Billing Country')].filter(Boolean).join(', ')}</span>}
          </div>

          {/* Grouped sections */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {sections.map(({ title, icon: Icon, items }) => (
              <section key={title} className="rounded-xl border p-4" style={{ borderColor: 'var(--border-glass)' }}>
                <h3 className="flex items-center gap-1.5 text-xs font-black uppercase tracking-wider mb-3" style={{ color: 'var(--text-main)' }}>
                  <Icon className="w-3.5 h-3.5 text-cyan-500" />{title}
                </h3>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-3">
                  {items.map(([label, value]) => <Field key={label} label={label} value={value} />)}
                </div>
              </section>
            ))}
          </div>

          {/* Everything else */}
          {rest.length > 0 && (
            <section className="rounded-xl border" style={{ borderColor: 'var(--border-glass)' }}>
              <button type="button" onClick={() => setShowAll(v => !v)} className="w-full flex items-center justify-between px-4 py-3 text-xs font-black uppercase tracking-wider" style={{ color: 'var(--text-main)' }}>
                <span className="flex items-center gap-1.5"><Info className="w-3.5 h-3.5 text-cyan-500" />All other fields ({rest.length})</span>
                {showAll ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
              </button>
              {showAll && (
                <div className="px-4 pb-4 flex flex-col gap-3">
                  <span className="relative max-w-xs">
                    <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
                    <input value={fieldFilter} onChange={e => setFieldFilter(e.target.value)} placeholder="Find a field"
                      className="w-full pl-8 pr-3 py-1.5 text-xs rounded-lg focus:outline-none"
                      style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' }} />
                  </span>
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-4 gap-y-3">
                    {restShown.map(([k, v]) => <Field key={k} label={k} value={v} />)}
                  </div>
                </div>
              )}
            </section>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
