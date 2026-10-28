import React, { useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { X, PlusCircle, HeartHandshake, Info, Search } from 'lucide-react';
import { API_BASE_URL } from '../config';
import { can, storedCompany, storedUser } from '../access';

/** Whether to show an add / edit control: the person holds `perm` in the charity (access.js; the server checks
 *  every action again, so this only decides what is shown). */
export function currentUser() {
  return storedUser() || {};
}
export function canEditRecords(user, perm = 'donors.edit', company) {
  return can(user || storedUser(), perm, company || storedCompany());
}

const codesCache = {};
export function useProjectCodes(company) {
  const [codes, setCodes] = useState(codesCache[company] || []);
  useEffect(() => {
    if (!company || company === 'all' || codesCache[company]) return;
    fetch(`${API_BASE_URL}/api/classifications/master-codes?company_id=${encodeURIComponent(company)}`)
      .then(r => (r.ok ? r.json() : { codes: [] }))
      .then(d => { codesCache[company] = (d.codes || []).filter(c => c.is_active !== 0); setCodes(codesCache[company]); })
      .catch(() => {});
  }, [company]);
  return codes;
}

// Same rules the Sponsorship Tracker uses to recognise a sponsorship gift
export function sponsorshipTypeFor(code = '', campaign = '', level = '') {
  const c = String(code).toUpperCase(); const t = `${campaign} ${level}`.toUpperCase();
  if (/HUF|HAF/.test(c) || /HAFIZ|HIFZ/.test(t)) return 'Hafiz';
  if (c.includes('ORP') || t.includes('ORPHAN')) return 'Orphan';
  if (c.includes('WID') || t.includes('WIDOW')) return 'Widow';
  if (/SUR|EX-PRISONER/.test(c) || /PRISONER|SURVIVOR/.test(t)) return 'Ex-Prisoner';
  return '';
}

const inputStyle = { backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' };
const today = () => new Date().toISOString().slice(0, 10);

function Field({ label, children, wide }) {
  return (
    <label className={`flex flex-col gap-1 ${wide ? 'sm:col-span-2' : ''}`}>
      <span className="text-[11px] font-semibold" style={{ color: 'var(--text-sub)' }}>{label}</span>
      {children}
    </label>
  );
}

/**
 * Adds a manual / offline donation. `donor` pre-fills an existing person (from a donor panel); `defaults` can pre-set
 * code / campaign / fundraiser (e.g. from the Sponsorship Tracker or a fundraiser).
 */
export default function AddDonationModal({ company, donor, defaults = {}, onClose, onCreated }) {
  const codes = useProjectCodes(company);
  const split = (donor?.name || '').trim().split(' ');
  const [f, setF] = useState({
    first_name: donor?.first_name ?? split[0] ?? '', last_name: donor?.last_name ?? split.slice(1).join(' '),
    email: donor?.email || '', phone: donor?.phone || '', address: '', city: donor?.city || '', postcode: '', country: donor?.country || '',
    amount: '', currency: 'GBP', settled_amount_gbp: '', fee: '', date: today(), payment_type: 'Bank transfer',
    frequency: 'One-Time Payment', campaign_name: defaults.campaign_name || '', giving_level: defaults.giving_level || '',
    code: defaults.code || '', gift_aid: false, zakat: false, anonymous: false, platform: 'Offline / Manual',
    fundraiser_name: defaults.fundraiser_name || '', notes: '', reference: '',
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const set = (k, v) => setF(p => ({ ...p, [k]: v }));
  // Choosing an existing donor (incl. one added without donations): the gift is attached to exactly that donor
  const [donorId, setDonorId] = useState(donor?.donor_id || '');
  const [q, setQ] = useState('');
  const [hits, setHits] = useState([]);
  useEffect(() => {
    if (donor || q.trim().length < 2) { setHits([]); return undefined; }
    const t = setTimeout(() => {
      fetch(`${API_BASE_URL}/api/donors/directory?company_id=${encodeURIComponent(company)}&search=${encodeURIComponent(q.trim())}&page_size=8&sort_by=name&sort_dir=asc`)
        .then(r => (r.ok ? r.json() : { donors: [] })).then(d => setHits(d.donors || [])).catch(() => setHits([]));
    }, 300);
    return () => clearTimeout(t);
  }, [q, company, donor]);
  const pick = (d) => {
    const parts = (d.name || '').trim().split(' ');
    setF(p => ({ ...p, first_name: parts[0] || '', last_name: parts.slice(1).join(' '), email: d.email || '', phone: d.phone || '',
      city: d.city || '', country: d.country || '' }));
    setDonorId(d.donor_id); setQ(''); setHits([]);
  };
  const match = useMemo(() => codes.find(c => c.code.toUpperCase() === String(f.code).trim().toUpperCase()), [codes, f.code]);
  const sType = sponsorshipTypeFor(f.code, f.campaign_name, f.giving_level);

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') { e.stopPropagation(); onClose(); } };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [onClose]);

  const save = async () => {
    setError('');
    if (!(Number(f.amount) > 0)) { setError('Enter the amount.'); return; }
    if (!f.email.trim() && !`${f.first_name}${f.last_name}`.trim()) { setError("Enter the donor's name or email."); return; }
    if (f.currency !== 'GBP' && !(Number(f.settled_amount_gbp) > 0)) { setError('For a non-GBP gift, enter the amount received in GBP.'); return; }
    if (f.code && !match) { setError(`'${f.code}' isn't one of this charity's project codes.`); return; }
    setSaving(true);
    try {
      const body = { ...f, company_id: company, donor_id: donorId || null, amount: Number(f.amount), fee: Number(f.fee || 0),
        settled_amount_gbp: f.currency === 'GBP' ? null : Number(f.settled_amount_gbp), code: f.code.trim().toUpperCase() };
      const res = await fetch(`${API_BASE_URL}/api/donors/donations`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `Error ${res.status}`);
      onCreated?.(data);
      onClose();
    } catch (e) { setError(e.message); } finally { setSaving(false); }
  };

  const input = (k, props = {}) => <input value={f[k]} onChange={e => set(k, e.target.value)} className="w-full px-2.5 py-2 text-sm rounded-lg" style={inputStyle} {...props} />;

  return createPortal(
    <div className="fixed inset-0 z-[85] flex items-center justify-center p-3 sm:p-6" role="dialog" aria-modal="true" aria-label="Add donation">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-3xl max-h-[92vh] flex flex-col rounded-2xl shadow-2xl overflow-hidden border" style={{ backgroundColor: 'var(--bg-card, var(--bg-main))', borderColor: 'var(--border-glass)' }}>
        <div className="px-6 py-4 border-b flex items-center justify-between bg-gradient-to-br from-emerald-500/10 to-transparent" style={{ borderColor: 'var(--border-glass)' }}>
          <div>
            <h2 className="text-base font-black flex items-center gap-2" style={{ color: 'var(--text-main)' }}><PlusCircle className="w-5 h-5 text-emerald-500" /> Add donation</h2>
            <p className="text-xs" style={{ color: 'var(--text-muted)' }}>An offline or manual gift. It counts everywhere: donors, classifications, fundraisers{sType ? ' and the Sponsorship Tracker' : ''}.</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="w-8 h-8 rounded-full flex items-center justify-center" style={{ color: 'var(--text-sub)' }}><X className="w-4 h-4" /></button>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-5 flex flex-col gap-5">
          <section className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="sm:col-span-2 text-xs font-black uppercase tracking-wider" style={{ color: 'var(--text-main)' }}>Donor</div>
            {!donor && (
              <div className="sm:col-span-2 flex flex-col gap-1 relative">
                <span className="text-[11px] font-semibold" style={{ color: 'var(--text-sub)' }}>Find the donor (name, email or phone) - or type a new donor's details below</span>
                <span className="relative">
                  <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
                  <input value={q} onChange={e => setQ(e.target.value)} placeholder="Start typing…" className="w-full pl-8 pr-2.5 py-2 text-sm rounded-lg" style={inputStyle} />
                </span>
                {hits.length > 0 && (
                  <div className="absolute top-full left-0 right-0 mt-1 z-10 rounded-lg border shadow-lg overflow-hidden" style={{ backgroundColor: 'var(--bg-card, var(--bg-main))', borderColor: 'var(--border-glass)' }}>
                    {hits.map(d => (
                      <button key={d.donor_id} type="button" onClick={() => pick(d)} className="w-full text-left px-3 py-2 text-xs hover:bg-emerald-500/10 border-b last:border-0" style={{ borderColor: 'var(--border-glass)', color: 'var(--text-main)' }}>
                        <b>{d.name || d.email || d.donor_id}</b>{d.sa ? ' · SA' : ''}{d.agent ? ` · ${d.agent}` : ''}
                        <span className="block" style={{ color: 'var(--text-muted)' }}>{[d.email, d.phone].filter(Boolean).join(' · ') || d.donor_id} · {d.gifts} gift{d.gifts === 1 ? '' : 's'}</span>
                      </button>
                    ))}
                  </div>
                )}
                {donorId && <span className="text-[11px] text-emerald-600 dark:text-emerald-400">Adding to donor {donorId} <button type="button" className="underline ml-1" onClick={() => setDonorId('')}>use a different donor</button></span>}
              </div>
            )}
            <Field label="First name">{input('first_name')}</Field>
            <Field label="Last name">{input('last_name')}</Field>
            <Field label="Email">{input('email', { type: 'email', placeholder: 'Links the gift to the donor' })}</Field>
            <Field label="Phone">{input('phone')}</Field>
            <Field label="Address">{input('address')}</Field>
            <Field label="City">{input('city')}</Field>
            <Field label="Postcode">{input('postcode')}</Field>
            <Field label="Country">{input('country')}</Field>
          </section>
          <section className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="sm:col-span-2 text-xs font-black uppercase tracking-wider" style={{ color: 'var(--text-main)' }}>Gift</div>
            <Field label="Amount">{input('amount', { type: 'number', min: '0', step: '0.01' })}</Field>
            <Field label="Currency">
              <select value={f.currency} onChange={e => set('currency', e.target.value)} className="w-full px-2.5 py-2 text-sm rounded-lg" style={inputStyle}>
                {['GBP', 'USD', 'EUR', 'CAD', 'AUD', 'SGD', 'AED', 'SAR', 'PKR'].map(c => <option key={c}>{c}</option>)}
              </select>
            </Field>
            {f.currency !== 'GBP' && <Field label="Received in GBP">{input('settled_amount_gbp', { type: 'number', min: '0', step: '0.01' })}</Field>}
            <Field label="Fees (GBP, optional)">{input('fee', { type: 'number', min: '0', step: '0.01' })}</Field>
            <Field label="Date">{input('date', { type: 'date' })}</Field>
            <Field label="Payment method">
              <select value={f.payment_type} onChange={e => set('payment_type', e.target.value)} className="w-full px-2.5 py-2 text-sm rounded-lg" style={inputStyle}>
                {['Bank transfer', 'Cash', 'Cheque', 'Card terminal', 'Standing order', 'Other'].map(c => <option key={c}>{c}</option>)}
              </select>
            </Field>
            <Field label="Frequency">
              <select value={f.frequency} onChange={e => set('frequency', e.target.value)} className="w-full px-2.5 py-2 text-sm rounded-lg" style={inputStyle}>
                <option>One-Time Payment</option><option>Recurring Payment</option>
              </select>
            </Field>
            <Field label="Reference (bank ref / receipt no.)">{input('reference')}</Field>
          </section>
          <section className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="sm:col-span-2 text-xs font-black uppercase tracking-wider" style={{ color: 'var(--text-main)' }}>Where it goes</div>
            <Field label="Project code" wide>
              <input list="add-donation-codes" value={f.code} onChange={e => set('code', e.target.value.toUpperCase())} placeholder="Type a code or project name" className="w-full px-2.5 py-2 text-sm rounded-lg font-mono" style={inputStyle} />
              <datalist id="add-donation-codes">
                {codes.map(c => <option key={c.code} value={c.code}>{[c.heading || c.department, c.sub_heading || c.office, c.country].filter(Boolean).join(' · ')}</option>)}
              </datalist>
              {match && <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>{[match.heading || match.department, match.sub_heading || match.office, match.country, match.programme_fund, match.zakat_eligibility].filter(Boolean).join(' · ')}</span>}
            </Field>
            <Field label="Campaign name">{input('campaign_name')}</Field>
            <Field label="Giving level">{input('giving_level')}</Field>
            <Field label="Fundraiser (optional)">{input('fundraiser_name')}</Field>
            <Field label="Notes">{input('notes')}</Field>
            {sType && (
              <div className="sm:col-span-2 flex items-center gap-2 text-xs rounded-lg px-3 py-2 bg-violet-500/10 text-violet-700 dark:text-violet-300 border border-violet-500/25">
                <HeartHandshake className="w-4 h-4" /> This is a <b>{sType}</b> sponsorship gift: it will count towards the donor's {sType} slots in the Sponsorship Tracker.
              </div>
            )}
            <div className="sm:col-span-2 flex flex-wrap gap-4 text-sm" style={{ color: 'var(--text-main)' }}>
              {[['gift_aid', 'Gift Aid'], ['zakat', 'Zakat'], ['anonymous', 'Anonymous']].map(([k, l]) => (
                <label key={k} className="flex items-center gap-1.5"><input type="checkbox" checked={f[k]} onChange={e => set(k, e.target.checked)} />{l}</label>
              ))}
            </div>
          </section>
          {error && <div className="text-sm rounded-lg px-3 py-2 bg-rose-500/10 text-rose-600 dark:text-rose-400 border border-rose-500/25 flex items-center gap-2"><Info className="w-4 h-4" />{error}</div>}
        </div>
        <div className="px-6 py-3 border-t flex justify-end gap-2" style={{ borderColor: 'var(--border-glass)' }}>
          <button type="button" onClick={onClose} className="px-4 py-2 text-sm rounded-lg font-semibold" style={{ color: 'var(--text-sub)' }}>Cancel</button>
          <button type="button" onClick={save} disabled={saving} className="px-4 py-2 text-sm rounded-lg font-bold bg-emerald-600 hover:bg-emerald-500 text-white disabled:opacity-50">{saving ? 'Saving…' : 'Add donation'}</button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
