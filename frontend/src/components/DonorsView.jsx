import React, { useEffect, useMemo, useState } from 'react';
import { Users, Search, ChevronLeft, ChevronRight, ArrowUp, ArrowDown, Gift, X, PlusCircle, Mail, Repeat, SlidersHorizontal } from 'lucide-react';
import { API_BASE_URL } from '../config';
import SegmentBuilder, { cleanSegment } from './SegmentBuilder';
import AddDonationModal, { canEditRecords } from './AddDonationModal';

const gbp = (v) => `£${Number(v || 0).toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const PLATFORMS = ['all', 'GiveBrite', 'LaunchGood', 'Madinah', 'Rethink Website', 'Paysuite', 'Offline / Manual'];
const TIERS = ['Low End', 'Medium Low', 'Medium', 'High', 'Super High'];
const TIER_TONE = {
  'Super High': 'bg-violet-500/15 text-violet-700 dark:text-violet-300', High: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300',
  Medium: 'bg-sky-500/15 text-sky-700 dark:text-sky-300', 'Medium Low': 'bg-amber-500/15 text-amber-700 dark:text-amber-300',
  'Low End': 'bg-slate-500/15 text-slate-600 dark:text-slate-300',
};
const GIFT_RULES = ['date_from', 'date_to', 'headings', 'subheadings', 'codes', 'campaign', 'platforms', 'sponsorship_types',
  'frequency', 'gift_aid_gift', 'sp_gift', 'min_amount', 'max_amount', 'min_matched_gifts', 'min_matched_total'];

/**
 * One row per donor (not per donation). Clicking a donor opens the donor panel with every donation they made.
 * Quick filters + "More filters" (the shared segment builder); the same filters can be emailed straight away.
 */
export default function DonorsView({ activeCompany, onSelectDonor, user, onOpenEmail }) {
  const [search, setSearch] = useState('');
  const [searchApplied, setSearchApplied] = useState('');
  const [platform, setPlatform] = useState('all');
  const [giftAid, setGiftAid] = useState('all');
  const [source, setSource] = useState('all');
  const [tier, setTier] = useState('all');
  const [recurring, setRecurring] = useState('all');
  const [sp, setSp] = useState('all');
  const [segment, setSegment] = useState({});
  const [showMore, setShowMore] = useState(false);
  const [sortBy, setSortBy] = useState('total');
  const [sortDir, setSortDir] = useState('desc');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [refreshTick, setRefreshTick] = useState(0);
  const [adding, setAdding] = useState(false);
  const [notice, setNotice] = useState('');
  const canEdit = canEditRecords(user) && activeCompany !== 'all';
  const segJson = useMemo(() => JSON.stringify(cleanSegment(segment)), [segment]);
  const hasGiftRules = GIFT_RULES.some(k => segment[k] !== undefined);

  useEffect(() => {
    const t = setTimeout(() => { setSearchApplied(search.trim()); setPage(1); }, 350);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => { setPage(1); }, [platform, giftAid, source, tier, recurring, sp, segJson, sortBy, sortDir, pageSize, activeCompany]);

  useEffect(() => {
    const qs = new URLSearchParams({ company_id: activeCompany, sort_by: sortBy, sort_dir: sortDir, page: String(page), page_size: String(pageSize) });
    if (searchApplied) qs.set('search', searchApplied);
    if (platform !== 'all') qs.set('platform', platform);
    if (giftAid !== 'all') qs.set('gift_aid', giftAid);
    if (source !== 'all') qs.set('source', source);
    if (tier !== 'all') qs.set('tier', tier);
    if (recurring !== 'all') qs.set('recurring', recurring);
    if (sp !== 'all') qs.set('sp', sp);
    if (segJson !== '{}') qs.set('segment', segJson);
    setLoading(true); setError('');
    const ctrl = new AbortController();
    fetch(`${API_BASE_URL}/api/donors/directory?${qs.toString()}`, { signal: ctrl.signal })
      .then(async r => { const j = await r.json(); if (!r.ok) throw new Error(j.detail || 'Could not load donors'); return j; })
      .then(j => { setData(j); setLoading(false); })
      .catch(e => { if (e.name !== 'AbortError') { setError(e.message); setLoading(false); } });
    return () => ctrl.abort();
  }, [activeCompany, searchApplied, platform, giftAid, source, tier, recurring, sp, segJson, sortBy, sortDir, page, pageSize, refreshTick]);

  // Live refresh when new donations arrive (app-wide live update stream)
  useEffect(() => {
    const onChange = () => setRefreshTick(t => t + 1);
    window.addEventListener('crm:data-changed', onChange);
    return () => window.removeEventListener('crm:data-changed', onChange);
  }, []);

  const toggleSort = (key) => {
    if (!key) return;
    if (sortBy === key) setSortDir(d => (d === 'desc' ? 'asc' : 'desc'));
    else { setSortBy(key); setSortDir(key === 'name' ? 'asc' : 'desc'); }
  };
  const filtersActive = searchApplied || platform !== 'all' || giftAid !== 'all' || source !== 'all' || tier !== 'all' || recurring !== 'all' || sp !== 'all' || segJson !== '{}';
  const clearFilters = () => { setSearch(''); setSearchApplied(''); setPlatform('all'); setGiftAid('all'); setSource('all'); setTier('all'); setRecurring('all'); setSp('all'); setSegment({}); };
  // Everything on screen as one segment (for emailing exactly these donors)
  const fullSegment = () => cleanSegment({
    ...segment, search: searchApplied || segment.search, platforms: platform !== 'all' ? [platform] : segment.platforms,
    gift_aid: giftAid !== 'all' ? giftAid : segment.gift_aid, manual: source === 'manual' ? 'yes' : (source === 'platform' ? 'no' : segment.manual),
    tiers: tier !== 'all' ? [tier] : segment.tiers, recurring: recurring !== 'all' ? recurring : segment.recurring, sp: sp !== 'all' ? sp : segment.sp,
  });
  const s = data?.summary || {};
  const inputStyle = { backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' };
  const columns = [
    { key: 'name', label: 'Donor' }, { key: null, label: 'Contact' }, { key: null, label: 'Location' },
    { key: 'gifts', label: 'Gifts', align: 'right' }, { key: 'total', label: 'Total given', align: 'right' },
    ...(hasGiftRules ? [{ key: 'matched_total', label: 'Matching gifts', align: 'right' }] : []),
    { key: 'avg_gift', label: 'Avg gift', align: 'right' }, { key: 'recurring_gifts', label: 'Recurring', align: 'right' },
    { key: null, label: 'LTV tier' }, { key: 'allocations', label: 'Sponsorships' },
    { key: 'first_gift', label: 'First gift' }, { key: 'last_gift', label: 'Last gift' }, { key: null, label: 'Platforms' },
    { key: null, label: 'Mostly gives to' },
  ];
  const sel = (id, value, set, options) => (
    <select id={id} value={value} onChange={e => set(e.target.value)} className="px-2 py-1.5 text-xs rounded-lg" style={inputStyle}>
      {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
    </select>
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-lg font-black flex items-center gap-2" style={{ color: 'var(--text-main)' }}>
            <Users className="w-5 h-5 text-cyan-500" /> Donors
          </h2>
          <p className="text-xs" style={{ color: 'var(--text-muted)' }}>Each person once, with everything they have given. Click a donor to see all of their donations.</p>
        </div>
        <div className="flex gap-2">
          {canEdit && (
            <button type="button" onClick={() => setAdding(true)} className="px-3 py-2 text-xs rounded-lg font-bold bg-emerald-600 hover:bg-emerald-500 text-white flex items-center gap-1.5">
              <PlusCircle className="w-4 h-4" /> Add donation
            </button>
          )}
        </div>
      </div>
      {notice && <div className="text-xs rounded-lg px-3 py-2 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border border-emerald-500/25 flex justify-between">{notice}<button type="button" onClick={() => setNotice('')}><X className="w-3.5 h-3.5" /></button></div>}

      <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7 gap-3">
        {[
          ['Donors', (s.donors ?? 0).toLocaleString()],
          ['Total given', gbp(s.total_raised)],
          ['Average per donor', gbp(s.average_per_donor)],
          ['Average gift', gbp(s.average_gift)],
          ['Recurring donors', (s.recurring_donors ?? 0).toLocaleString()],
          ['SP donors', (s.sp_donors ?? 0).toLocaleString()],
          ['Gift Aid donors', (s.gift_aid_donors ?? 0).toLocaleString()],
        ].map(([label, value]) => (
          <div key={label} className="glass-panel p-3">
            <div className="text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--text-sub)' }}>{label}</div>
            <div className="text-lg font-black mt-0.5 tabular-nums" style={{ color: 'var(--text-main)' }}>{loading && !data ? '…' : value}</div>
            {label === 'Total given' && s.unidentified_gifts > 0 && (
              <div className="text-[10px] mt-0.5" style={{ color: 'var(--text-muted)' }}>
                includes {gbp(s.unidentified_amount)} from {s.unidentified_gifts.toLocaleString()} gifts with no donor details
              </div>
            )}
            {label === 'Total given' && s.manual_total > 0 && (
              <div className="text-[10px] mt-0.5 text-amber-600 dark:text-amber-400">
                + {gbp(s.manual_total)} recorded manually in the Sponsorship Tracker ({(s.manual_donors ?? 0).toLocaleString()} donors)
              </div>
            )}
            {label === 'Total given' && hasGiftRules && s.matched_total != null && (
              <div className="text-[10px] mt-0.5 text-violet-600 dark:text-violet-300">{gbp(s.matched_total)} from the matching gifts</div>
            )}
          </div>
        ))}
      </div>
      {s.tiers && (
        <div className="flex flex-wrap gap-1.5 text-[11px]">
          {TIERS.map(t => (
            <button type="button" key={t} onClick={() => setTier(tier === t ? 'all' : t)} className={`px-2 py-0.5 rounded-full font-semibold ${TIER_TONE[t]} ${tier === t ? 'ring-2 ring-cyan-500' : ''}`}>
              {t}: {(s.tiers[t] || 0).toLocaleString()}
            </button>
          ))}
        </div>
      )}

      <div className="glass-panel p-3 flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-0.5 flex-1 min-w-[16rem]">
          <span className="text-[10px] font-semibold" style={{ color: 'var(--text-sub)' }}>Search</span>
          <span className="relative">
            <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
            <input id="donor-search" value={search} onChange={e => setSearch(e.target.value)} placeholder="Name, email, phone or donor ID"
              className="w-full pl-8 pr-3 py-1.5 text-xs rounded-lg focus:outline-none" style={inputStyle} />
          </span>
        </label>
        <label className="flex flex-col gap-0.5"><span className="text-[10px] font-semibold" style={{ color: 'var(--text-sub)' }}>Platform</span>
          {sel('donor-platform', platform, setPlatform, PLATFORMS.map(p => [p, p === 'all' ? 'All platforms' : p]))}</label>
        <label className="flex flex-col gap-0.5"><span className="text-[10px] font-semibold" style={{ color: 'var(--text-sub)' }}>LTV tier</span>
          {sel('donor-tier', tier, setTier, [['all', 'Any tier'], ...TIERS.map(t => [t, t])])}</label>
        <label className="flex flex-col gap-0.5"><span className="text-[10px] font-semibold" style={{ color: 'var(--text-sub)' }}>Recurring</span>
          {sel('donor-recurring', recurring, setRecurring, [['all', 'Any'], ['yes', 'Recurring donors'], ['no', 'One-off only']])}</label>
        <label className="flex flex-col gap-0.5"><span className="text-[10px] font-semibold" style={{ color: 'var(--text-sub)' }}>SP (Sisters' Project)</span>
          {sel('donor-sp', sp, setSp, [['all', 'Everyone'], ['yes', 'SP donors'], ['no', 'Non-SP donors']])}</label>
        <label className="flex flex-col gap-0.5"><span className="text-[10px] font-semibold" style={{ color: 'var(--text-sub)' }}>Gift Aid</span>
          {sel('donor-giftaid', giftAid, setGiftAid, [['all', 'Any'], ['yes', 'Has Gift Aid'], ['no', 'No Gift Aid']])}</label>
        <label className="flex flex-col gap-0.5"><span className="text-[10px] font-semibold" style={{ color: 'var(--text-sub)' }}>Source</span>
          {sel('donor-source', source, setSource, [['all', 'Everyone'], ['platform', 'Platform donations'], ['manual', 'Added in Sponsorship Tracker']])}</label>
        <button type="button" onClick={() => setShowMore(v => !v)} className={`px-2.5 py-1.5 text-xs font-semibold rounded-lg flex items-center gap-1 border ${showMore || segJson !== '{}' ? 'text-cyan-600 border-cyan-500/40' : ''}`} style={showMore || segJson !== '{}' ? undefined : { borderColor: 'var(--border-glass)', color: 'var(--text-sub)' }}>
          <SlidersHorizontal className="w-3.5 h-3.5" /> More filters{segJson !== '{}' ? ` (${Object.keys(cleanSegment(segment)).length})` : ''}
        </button>
        {filtersActive && (
          <button type="button" onClick={clearFilters} className="px-2.5 py-1.5 text-xs font-semibold rounded-lg flex items-center gap-1" style={{ color: 'var(--text-muted)' }}>
            <X className="w-3.5 h-3.5" /> Clear
          </button>
        )}
      </div>
      {showMore && <SegmentBuilder company={activeCompany} value={segment} onChange={setSegment} hideSearch />}

      <div className="glass-panel overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr style={{ color: 'var(--text-sub)' }}>
                {columns.map(c => (
                  <th key={c.label} className={`px-3 py-2 font-bold uppercase tracking-wider text-[10px] whitespace-nowrap ${c.align === 'right' ? 'text-right' : 'text-left'}`}>
                    {c.key ? (
                      <button type="button" onClick={() => toggleSort(c.key)} className="inline-flex items-center gap-1 uppercase hover:text-cyan-500">
                        {c.label}{sortBy === c.key && (sortDir === 'desc' ? <ArrowDown className="w-3 h-3" /> : <ArrowUp className="w-3 h-3" />)}
                      </button>
                    ) : c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {error && <tr><td colSpan={columns.length} className="px-3 py-6 text-rose-500">{error}</td></tr>}
              {!error && loading && !data && Array.from({ length: 8 }).map((_, i) => (
                <tr key={i}><td colSpan={columns.length} className="px-3 py-3"><div className="h-3 rounded bg-slate-500/20 animate-pulse" /></td></tr>
              ))}
              {!error && data && data.donors.length === 0 && (
                <tr><td colSpan={columns.length} className="px-3 py-8 text-center" style={{ color: 'var(--text-muted)' }}>No donors match these filters.</td></tr>
              )}
              {!error && data?.donors.map(d => (
                <tr key={d.donor_id} onClick={() => onSelectDonor({ donor_id: d.donor_id, email: d.email, name: d.name })}
                  className={`border-t cursor-pointer hover:bg-cyan-500/5 ${loading ? 'opacity-60' : ''}`} style={{ borderColor: 'var(--border-glass)' }}
                  tabIndex={0} onKeyDown={e => { if (e.key === 'Enter') onSelectDonor({ donor_id: d.donor_id, email: d.email, name: d.name }); }}>
                  <td className="px-3 py-2">
                    <div className="font-bold flex items-center gap-1.5" style={{ color: 'var(--text-main)' }}>
                      {d.name || 'Unnamed donor'}
                      {d.sp && <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-pink-500/15 text-pink-700 dark:text-pink-300 font-bold" title="Gave through a Sisters' Project page">SP</span>}
                    </div>
                    <div className="text-[10px] font-mono" style={{ color: 'var(--text-muted)' }}>{d.donor_id}</div>
                  </td>
                  <td className="px-3 py-2">
                    <div style={{ color: 'var(--text-main)' }}>{d.email || '—'}</div>
                    <div style={{ color: 'var(--text-muted)' }}>{d.phone || ''}</div>
                  </td>
                  <td className="px-3 py-2" style={{ color: 'var(--text-muted)' }}>{[d.city, d.country].filter(Boolean).join(', ') || '—'}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{d.gifts}</td>
                  <td className="px-3 py-2 text-right tabular-nums font-black text-cyan-600 dark:text-cyan-400">
                    {gbp(d.total)}
                    {d.manual_total > 0 && <div className="text-[10px] font-semibold text-amber-600 dark:text-amber-400">incl. {gbp(d.manual_total)} manual</div>}
                  </td>
                  {hasGiftRules && <td className="px-3 py-2 text-right tabular-nums font-bold text-violet-600 dark:text-violet-300">{gbp(d.matched_total)}<div className="text-[10px] font-normal" style={{ color: 'var(--text-muted)' }}>{d.matched_gifts} gift{d.matched_gifts === 1 ? '' : 's'}</div></td>}
                  <td className="px-3 py-2 text-right tabular-nums" style={{ color: 'var(--text-main)' }}>{d.gifts ? gbp(d.avg_gift) : '—'}</td>
                  <td className="px-3 py-2 text-right tabular-nums" style={{ color: 'var(--text-main)' }}>
                    {d.recurring_gifts > 0 ? <span className="inline-flex items-center gap-1 text-emerald-600 dark:text-emerald-400 font-semibold"><Repeat className="w-3 h-3" />{d.recurring_gifts}</span> : '—'}
                  </td>
                  <td className="px-3 py-2"><span className={`text-[10px] px-2 py-0.5 rounded-full font-bold whitespace-nowrap ${TIER_TONE[d.tier] || ''}`}>{d.tier || '—'}</span></td>
                  <td className="px-3 py-2" style={{ color: 'var(--text-muted)' }}>
                    {d.sponsorship_types || '—'}{d.allocations > 0 && <span className="ml-1 text-violet-600 dark:text-violet-300 font-bold">· {d.allocations} active</span>}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap tabular-nums" style={{ color: 'var(--text-muted)' }}>{d.first_gift || '—'}</td>
                  <td className="px-3 py-2 whitespace-nowrap tabular-nums" style={{ color: 'var(--text-main)' }}>{d.last_gift || '—'}</td>
                  <td className="px-3 py-2" style={{ color: 'var(--text-muted)' }}>{d.platforms || '—'}</td>
                  <td className="px-3 py-2" style={{ color: 'var(--text-muted)' }}>
                    {d.top_heading || '—'}{d.gift_aid && <span className="ml-1.5 inline-flex items-center gap-0.5 text-emerald-600 dark:text-emerald-400 font-bold"><Gift className="w-3 h-3" />GA</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {data && (
          <div className="flex items-center justify-between gap-2 flex-wrap px-3 py-2 border-t text-xs" style={{ borderColor: 'var(--border-glass)', color: 'var(--text-muted)' }}>
            <span>{data.total_donors.toLocaleString()} donors · page {data.page} of {data.total_pages}</span>
            <div className="flex items-center gap-2">
              <select id="donor-pagesize" value={pageSize} onChange={e => setPageSize(Number(e.target.value))} className="px-2 py-1 rounded-lg" style={inputStyle}>
                {[25, 50, 100, 200].map(n => <option key={n} value={n}>{n} per page</option>)}
              </select>
              <button type="button" disabled={page <= 1} onClick={() => setPage(p => p - 1)} className="p-1.5 rounded-lg disabled:opacity-30" aria-label="Previous page"><ChevronLeft className="w-4 h-4" /></button>
              <button type="button" disabled={page >= data.total_pages} onClick={() => setPage(p => p + 1)} className="p-1.5 rounded-lg disabled:opacity-30" aria-label="Next page"><ChevronRight className="w-4 h-4" /></button>
            </div>
          </div>
        )}
      </div>
      {adding && <AddDonationModal company={activeCompany} onClose={() => setAdding(false)} onCreated={(d) => { setNotice(`Donation ${d.donation_id} added (£${d.net.toFixed(2)}, ${d.code}).`); setRefreshTick(t => t + 1); }} />}
    </div>
  );
}
