import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, Filter, Gift, Users, X, Search, Check } from 'lucide-react';
import { API_BASE_URL } from '../config';

/**
 * Segment builder shared by the Donors page, the email composer and email campaigns.
 * value is the segment object understood by the backend (backend/api/donors.py apply_segment):
 *   gift rules  - which gifts count: date_from/date_to, headings, subheadings, codes, sponsorship_types, campaign,
 *                 platforms, frequency, min_amount/max_amount, gift_aid_gift, sp_gift, min_matched_gifts/min_matched_total
 *   donor rules - tiers, min/max_total, min/max_gifts, min/max_avg, recurring, sp, min_allocations, has_email,
 *                 marketing_consent, countries, city, first/last_gift_from/to, manual
 * Lists mean "any of"; different rules are combined (AND).
 */
const optionsCache = {};
export function useSegmentOptions(company) {
  const [opts, setOpts] = useState(optionsCache[company] || null);
  useEffect(() => {
    if (!company || company === 'all') return;
    if (optionsCache[company]) { setOpts(optionsCache[company]); return; }
    fetch(`${API_BASE_URL}/api/donors/segment-options?company_id=${encodeURIComponent(company)}`)
      .then(r => (r.ok ? r.json() : null)).then(d => { if (d) { optionsCache[company] = d; setOpts(d); } }).catch(() => {});
  }, [company]);
  return opts;
}

const inputStyle = { backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' };
const TIERS = ['Low End', 'Medium Low', 'Medium', 'High', 'Super High'];
const YES_NO = [['', 'Any'], ['yes', 'Yes'], ['no', 'No']];

function MultiSelect({ label, options, value = [], onChange, placeholder = 'Any', renderSub }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const ref = useRef(null);
  useEffect(() => {
    const close = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, []);
  const shown = useMemo(() => {
    const ql = q.trim().toLowerCase();
    return (options || []).filter(o => !ql || String(o.value).toLowerCase().includes(ql) || String(o.sub || '').toLowerCase().includes(ql)).slice(0, 300);
  }, [options, q]);
  const toggle = (v) => onChange(value.includes(v) ? value.filter(x => x !== v) : [...value, v]);
  return (
    <label className="flex flex-col gap-1 min-w-0 relative" ref={ref}>
      <span className="text-[11px] font-semibold" style={{ color: 'var(--text-sub)' }}>{label}</span>
      <button type="button" onClick={() => setOpen(o => !o)} className="px-2.5 py-1.5 text-xs rounded-lg flex items-center justify-between gap-2 text-left" style={inputStyle}>
        <span className="truncate">{value.length ? (value.length <= 2 ? value.join(', ') : `${value.length} selected`) : placeholder}</span>
        <ChevronDown className="w-3.5 h-3.5 shrink-0 opacity-60" />
      </button>
      {open && (
        <div className="absolute z-[90] top-full mt-1 left-0 w-[min(22rem,90vw)] rounded-xl shadow-2xl border p-2 flex flex-col gap-1.5"
          style={{ backgroundColor: 'var(--bg-card, var(--bg-main))', borderColor: 'var(--border-glass)' }}>
          <span className="relative">
            <Search className="w-3.5 h-3.5 absolute left-2 top-1/2 -translate-y-1/2 text-slate-400" />
            <input autoFocus value={q} onChange={e => setQ(e.target.value)} placeholder="Search" className="w-full pl-7 pr-2 py-1.5 text-xs rounded-lg focus:outline-none" style={inputStyle} />
          </span>
          <div className="max-h-64 overflow-y-auto flex flex-col">
            {shown.length === 0 && <span className="text-xs p-2" style={{ color: 'var(--text-muted)' }}>Nothing matches</span>}
            {shown.map(o => (
              <button type="button" key={o.value} onClick={() => toggle(o.value)}
                className="flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs text-left hover:bg-cyan-500/10" style={{ color: 'var(--text-main)' }}>
                <span className={`w-4 h-4 rounded border flex items-center justify-center shrink-0 ${value.includes(o.value) ? 'bg-cyan-600 border-cyan-600' : ''}`} style={value.includes(o.value) ? undefined : { borderColor: 'var(--input-border)' }}>
                  {value.includes(o.value) && <Check className="w-3 h-3 text-white" />}
                </span>
                <span className="flex-1 min-w-0">
                  <span className="block truncate">{o.value}</span>
                  {(o.sub || renderSub) && <span className="block text-[10px] truncate" style={{ color: 'var(--text-muted)' }}>{o.sub}</span>}
                </span>
                {o.count != null && <span className="text-[10px] tabular-nums" style={{ color: 'var(--text-muted)' }}>{o.count.toLocaleString()}</span>}
              </button>
            ))}
          </div>
          {value.length > 0 && <button type="button" onClick={() => onChange([])} className="text-[11px] text-cyan-600 self-start px-1">Clear</button>}
        </div>
      )}
    </label>
  );
}

function Field({ label, children }) {
  return (
    <label className="flex flex-col gap-1 min-w-0">
      <span className="text-[11px] font-semibold" style={{ color: 'var(--text-sub)' }}>{label}</span>
      {children}
    </label>
  );
}

const LABELS = {
  date_from: 'Gifts from', date_to: 'Gifts to', headings: 'Cause', subheadings: 'Sub-cause', codes: 'Code',
  sponsorship_types: 'Sponsorship', campaign: 'Campaign has', platforms: 'Platform', frequency: 'Gift type',
  min_amount: 'Gift ≥ £', max_amount: 'Gift ≤ £', gift_aid_gift: 'Gift Aid gift', sp_gift: 'SP gift',
  min_matched_gifts: 'Matching gifts ≥', min_matched_total: 'Matching total ≥ £', tiers: 'Tier', min_total: 'Lifetime ≥ £',
  max_total: 'Lifetime ≤ £', min_gifts: 'Gifts ≥', max_gifts: 'Gifts ≤', min_avg: 'Avg gift ≥ £', max_avg: 'Avg gift ≤ £',
  recurring: 'Recurring donor', sp: 'SP donor', min_allocations: 'Sponsorships ≥', has_email: 'Has email',
  marketing_consent: 'Marketing consent', countries: 'Country', city: 'City has', first_gift_from: 'First gift from',
  first_gift_to: 'First gift to', last_gift_from: 'Last gift from', last_gift_to: 'Last gift to', manual: 'Added manually',
  search: 'Search',
};

export function segmentChips(seg = {}) {
  return Object.entries(seg).filter(([, v]) => v !== '' && v != null && !(Array.isArray(v) && !v.length))
    .map(([k, v]) => ({ key: k, text: `${LABELS[k] || k}: ${Array.isArray(v) ? (v.length > 3 ? `${v.slice(0, 3).join(', ')} +${v.length - 3}` : v.join(', ')) : v}` }));
}

export function cleanSegment(seg = {}) {
  const out = {};
  Object.entries(seg).forEach(([k, v]) => { if (v !== '' && v != null && !(Array.isArray(v) && !v.length)) out[k] = v; });
  return out;
}

export default function SegmentBuilder({ company, value = {}, onChange, defaultOpen = true, hideSearch = false }) {
  const opts = useSegmentOptions(company);
  const [open, setOpen] = useState(defaultOpen);
  const set = (k, v) => onChange(cleanSegment({ ...value, [k]: v }));
  const num = (k) => (
    <input type="number" min="0" value={value[k] ?? ''} onChange={e => set(k, e.target.value === '' ? '' : Number(e.target.value))}
      className="w-full px-2 py-1.5 text-xs rounded-lg" style={inputStyle} />
  );
  const date = (k) => <input type="date" value={value[k] || ''} onChange={e => set(k, e.target.value)} className="w-full px-2 py-1.5 text-xs rounded-lg" style={inputStyle} />;
  const yn = (k, opts2 = YES_NO) => (
    <select value={value[k] || ''} onChange={e => set(k, e.target.value)} className="w-full px-2 py-1.5 text-xs rounded-lg" style={inputStyle}>
      {opts2.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
    </select>
  );
  const subOptions = useMemo(() => {
    const all = (opts?.subheadings || []).map(s => ({ value: s.value, sub: s.heading, count: s.count }));
    const hs = value.headings || [];
    return hs.length ? all.filter(s => hs.includes(s.sub)) : all;
  }, [opts, value.headings]);
  const chips = segmentChips(value);

  return (
    <div className="glass-panel p-3 flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <button type="button" onClick={() => setOpen(o => !o)} className="flex items-center gap-1.5 text-xs font-black uppercase tracking-wider" style={{ color: 'var(--text-main)' }}>
          <Filter className="w-3.5 h-3.5 text-cyan-500" /> Filters {chips.length > 0 && <span className="px-1.5 rounded-full bg-cyan-500/15 text-cyan-600 dark:text-cyan-400 normal-case">{chips.length}</span>}
          <ChevronDown className={`w-3.5 h-3.5 transition-transform ${open ? 'rotate-180' : ''}`} />
        </button>
        <div className="flex flex-wrap gap-1.5 flex-1 justify-end">
          {chips.map(c => (
            <span key={c.key} className="text-[11px] px-2 py-0.5 rounded-full bg-cyan-500/10 text-cyan-700 dark:text-cyan-300 border border-cyan-500/25 flex items-center gap-1">
              {c.text}<button type="button" onClick={() => set(c.key, '')} aria-label={`Remove ${c.text}`}><X className="w-3 h-3" /></button>
            </span>
          ))}
          {chips.length > 0 && <button type="button" onClick={() => onChange({})} className="text-[11px] text-rose-500 font-semibold">Clear all</button>}
        </div>
      </div>
      {open && (
        <>
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider" style={{ color: 'var(--text-sub)' }}>
              <Gift className="w-3.5 h-3.5 text-violet-500" /> Gifts that count <span className="normal-case font-normal" style={{ color: 'var(--text-muted)' }}>(a donor matches when at least one gift fits all of these)</span>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-2">
              <Field label="Gifts from">{date('date_from')}</Field>
              <Field label="Gifts to">{date('date_to')}</Field>
              <MultiSelect label="Cause (heading)" options={(opts?.headings || [])} value={value.headings || []} onChange={v => set('headings', v)} />
              <MultiSelect label="Sub-cause" options={subOptions} value={value.subheadings || []} onChange={v => set('subheadings', v)} />
              <MultiSelect label="Sponsorship" options={(opts?.sponsorship_types || []).map(v => ({ value: v }))} value={value.sponsorship_types || []} onChange={v => set('sponsorship_types', v)} />
              <MultiSelect label="Project code" options={(opts?.codes || [])} value={value.codes || []} onChange={v => set('codes', v)} />
              <Field label="Campaign name has"><input value={value.campaign || ''} onChange={e => set('campaign', e.target.value)} placeholder="e.g. Ramadan" className="w-full px-2 py-1.5 text-xs rounded-lg" style={inputStyle} /></Field>
              <MultiSelect label="Platform" options={(opts?.platforms || [])} value={value.platforms || []} onChange={v => set('platforms', v)} />
              <Field label="Gift type">{yn('frequency', [['', 'Any'], ['recurring', 'Recurring'], ['one-off', 'One-off']])}</Field>
              <Field label="Single gift ≥ £">{num('min_amount')}</Field>
              <Field label="Single gift ≤ £">{num('max_amount')}</Field>
              <Field label="Gift Aid on gift">{yn('gift_aid_gift')}</Field>
              <Field label="Gift via SP page">{yn('sp_gift')}</Field>
              <Field label="Matching gifts ≥">{num('min_matched_gifts')}</Field>
              <Field label="Matching total ≥ £">{num('min_matched_total')}</Field>
            </div>
          </div>
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider" style={{ color: 'var(--text-sub)' }}>
              <Users className="w-3.5 h-3.5 text-emerald-500" /> Donor details
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-2">
              <MultiSelect label="LTV tier" options={TIERS.map(v => ({ value: v }))} value={value.tiers || []} onChange={v => set('tiers', v)} />
              <Field label="Lifetime given ≥ £">{num('min_total')}</Field>
              <Field label="Lifetime given ≤ £">{num('max_total')}</Field>
              <Field label="Number of gifts ≥">{num('min_gifts')}</Field>
              <Field label="Number of gifts ≤">{num('max_gifts')}</Field>
              <Field label="Average gift ≥ £">{num('min_avg')}</Field>
              <Field label="Average gift ≤ £">{num('max_avg')}</Field>
              <Field label="Recurring donor">{yn('recurring')}</Field>
              <Field label="SP donor">{yn('sp')}</Field>
              <Field label="Sponsorships ≥">{num('min_allocations')}</Field>
              <Field label="Has email">{yn('has_email')}</Field>
              <Field label="Marketing consent">{yn('marketing_consent')}</Field>
              <MultiSelect label="Country" options={(opts?.countries || [])} value={value.countries || []} onChange={v => set('countries', v)} />
              <Field label="City has"><input value={value.city || ''} onChange={e => set('city', e.target.value)} className="w-full px-2 py-1.5 text-xs rounded-lg" style={inputStyle} /></Field>
              <Field label="First gift from">{date('first_gift_from')}</Field>
              <Field label="First gift to">{date('first_gift_to')}</Field>
              <Field label="Last gift from">{date('last_gift_from')}</Field>
              <Field label="Last gift to">{date('last_gift_to')}</Field>
              <Field label="Added manually">{yn('manual')}</Field>
              {!hideSearch && <Field label="Name / email / phone"><input value={value.search || ''} onChange={e => set('search', e.target.value)} className="w-full px-2 py-1.5 text-xs rounded-lg" style={inputStyle} /></Field>}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
