import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  X, Mail, Phone, MapPin, ShieldCheck, ShieldX, ShieldQuestion, Gift, Repeat, Layers, Calendar,
  HeartHandshake, Inbox, Clock, Loader2, ExternalLink, Users, Eye, Reply
} from 'lucide-react';
import { API_BASE_URL } from '../../config';
import DonationDetailModal from '../DonationDetailModal';
import AddDonationModal, { canEditRecords } from '../AddDonationModal';
import SingleEmailComposer from '../email/SingleEmailComposer';
import { PlusCircle, Send, Search } from 'lucide-react';

const money = (v, cur = '£') => (v === null || v === undefined ? '—' : `${cur}${Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 })}`);
const CURRENCY_SYMBOLS = { GBP: '£', USD: '$', EUR: '€', CAD: 'C$', AUD: 'A$' };
const curSym = (c) => CURRENCY_SYMBOLS[(c || '').toUpperCase()] || `${c || ''} `;

const consentStyle = {
  Yes: { cls: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300', Icon: ShieldCheck },
  'Yes (inferred)': { cls: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300', Icon: ShieldCheck },
  No: { cls: 'bg-rose-50 text-rose-700 dark:bg-rose-950/50 dark:text-rose-300', Icon: ShieldX },
  Unknown: { cls: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300', Icon: ShieldQuestion }
};

function Section({ title, icon: Icon, children, right }) {
  return (
    <section className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400 flex items-center gap-1.5">
          <Icon className="w-4 h-4" /> {title}
        </h4>
        {right}
      </div>
      {children}
    </section>
  );
}

/**
 * Side panel with everything about one donor for the active charity: contact & consent,
 * giving towards each sponsorship type, their sponsorships, email history and donations.
 */
export default function SponsorshipDonorPanel({ donorKey, companyId, sponsorshipType, onClose, onOpenCrmProfile }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [showAllDonations, setShowAllDonations] = useState(false);
  const [dFrom, setDFrom] = useState('');
  const [dTo, setDTo] = useState('');
  const [dType, setDType] = useState('all');
  const [dPlatform, setDPlatform] = useState('all');
  const [dSearch, setDSearch] = useState('');
  const [openDonation, setOpenDonation] = useState(null);
  const [adding, setAdding] = useState(false);
  const [emailing, setEmailing] = useState(false);
  const [reloadTick, setReloadTick] = useState(0);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!donorKey) return undefined;
    const onKey = (e) => e.key === 'Escape' && onCloseRef.current();
    window.addEventListener('keydown', onKey);
    setLoading(true); setError(''); if (!reloadTick) setData(null); setShowAllDonations(false);
    const params = new URLSearchParams({ company_id: companyId });
    fetch(`${API_BASE_URL}/api/tracker/donors/${encodeURIComponent(donorKey)}/details?${params}`)
      .then(async r => { const j = await r.json(); if (!r.ok) throw new Error(j.detail || 'Could not load donor'); return j; })
      .then(setData)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
    return () => window.removeEventListener('keydown', onKey);
  }, [donorKey, companyId, reloadTick]);

  if (!donorKey) return null;
  const consent = consentStyle[data?.contact?.marketing_consent] || consentStyle.Unknown;
  const allDonations = data?.donations || [];
  const donationTypes = [...new Set(allDonations.map(d => d.sponsorship_type).filter(Boolean))];
  const donationPlatforms = [...new Set(allDonations.map(d => d.platform).filter(Boolean))];
  const filtersOn = dFrom || dTo || dType !== 'all' || dPlatform !== 'all' || dSearch.trim();
  const donations = allDonations.filter(d => {
    const day = String(d.date || '').slice(0, 10);
    if (dFrom && day < dFrom) return false;
    if (dTo && day > dTo) return false;
    if (dType !== 'all' && d.sponsorship_type !== dType) return false;
    if (dPlatform !== 'all' && d.platform !== dPlatform) return false;
    const q = dSearch.trim().toLowerCase();
    if (q && !`${d.campaign} ${d.code} ${d.heading} ${d.sub_heading} ${d.fundraiser} ${d.giving_level} ${d.donation_id}`.toLowerCase().includes(q)) return false;
    return true;
  });
  const filteredSettled = donations.reduce((a, d) => a + (Number(d.settled_amount) || 0), 0);
  const visibleDonations = showAllDonations || filtersOn ? donations : donations.slice(0, 10);
  const canEdit = canEditRecords() && companyId && companyId !== 'all';
  const primaryEmail = data?.contact?.emails?.[0] || '';
  const focusType = sponsorshipType && sponsorshipType !== 'All' ? sponsorshipType : null;
  const giving = (data?.giving || []).slice().sort((a, b) => (a.sponsorship_type === focusType ? -1 : b.sponsorship_type === focusType ? 1 : 0));

  return (
    <div className="fixed inset-0 z-[60] flex justify-end bg-black/40 backdrop-blur-xs" onClick={onClose}>
      <aside className="w-[min(1400px,96vw)] max-w-[96vw] h-full overflow-y-auto bg-white dark:bg-slate-950 border-l border-slate-200 dark:border-slate-800 shadow-2xl animate-in slide-in-from-right duration-200"
        onClick={e => e.stopPropagation()}>
        <header className="sticky top-0 z-10 px-5 py-4 bg-white/95 dark:bg-slate-950/95 backdrop-blur border-b border-slate-200 dark:border-slate-800 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="text-xl font-bold text-slate-900 dark:text-white truncate">{data?.contact?.name || donorKey}</h3>
              {data && (
                <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-blue-50 text-blue-700 dark:bg-blue-950/50 dark:text-blue-300 uppercase">
                  {data.is_organizer ? 'Organizer' : data.donor_type === 'manual' ? 'Manual donor' : data.donor_type === 'crm' ? 'CRM donor' : 'Contact'}
                </span>
              )}
            </div>
            <p className="text-sm text-slate-500 mt-0.5">Sponsorship donor profile · {companyId}</p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {data && canEdit && (
              <button type="button" onClick={() => setAdding(true)} className="px-3 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-semibold flex items-center gap-1">
                <PlusCircle className="w-4 h-4" /> Add donation
              </button>
            )}
            {data && primaryEmail && companyId !== 'all' && (
              <button type="button" onClick={() => setEmailing(true)} className="px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 text-sm font-semibold text-slate-700 dark:text-slate-200 hover:border-sky-400 flex items-center gap-1">
                <Send className="w-4 h-4 text-sky-500" /> Email
              </button>
            )}
            {data?.donor_type === 'crm' && onOpenCrmProfile && (
              <button type="button" onClick={() => onOpenCrmProfile(data.contact.emails[0] || donorKey)}
                className="px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 text-sm font-semibold text-slate-600 dark:text-slate-300 hover:border-blue-400 flex items-center gap-1">
                <ExternalLink className="w-3.5 h-3.5" /> Full CRM profile
              </button>
            )}
            <button type="button" onClick={onClose} className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500"><X className="w-4 h-4" /></button>
          </div>
        </header>

        <div className="p-6 flex flex-col gap-6 text-sm">
          {loading && <div className="py-16 flex items-center justify-center gap-2 text-slate-400"><Loader2 className="w-5 h-5 animate-spin" /> Loading donor…</div>}
          {error && <div className="p-3 rounded-lg bg-rose-50 dark:bg-rose-950/40 text-rose-700 dark:text-rose-300">{error}</div>}

          {data && (
            <>
              <Section title="Contact" icon={Mail}>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  <div className="p-3 rounded-xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 flex flex-col gap-1.5">
                    {data.contact.emails.length ? data.contact.emails.map(e => (
                      <span key={e} className="flex items-center gap-1.5 font-mono text-slate-700 dark:text-slate-200 break-all"><Mail className="w-3.5 h-3.5 text-slate-400 shrink-0" />{e}</span>
                    )) : <span className="text-slate-400">No email on file</span>}
                    {data.contact.phone && <span className="flex items-center gap-1.5 font-mono text-slate-700 dark:text-slate-200"><Phone className="w-3.5 h-3.5 text-slate-400" />{data.contact.phone}</span>}
                    {data.contact.country && <span className="flex items-center gap-1.5 text-slate-700 dark:text-slate-200"><MapPin className="w-3.5 h-3.5 text-slate-400" />{data.contact.country}</span>}
                  </div>
                  <div className={`p-3 rounded-xl flex items-start gap-2 ${consent.cls}`}>
                    <consent.Icon className="w-4 h-4 shrink-0 mt-0.5" />
                    <div>
                      <div className="font-bold">Email updates consent: {data.contact.marketing_consent}</div>
                      <div className="opacity-80 mt-0.5">
                        {data.contact.marketing_consent === 'Yes (inferred)'
                          ? 'Madinah donor shared their details (not hidden). Inferred, pending confirmation from Madinah.'
                          : data.contact.marketing_consent === 'Unknown'
                            ? 'No consent recorded on their latest donations.'
                            : 'From the donor\'s most recent donation record.'}
                      </div>
                    </div>
                  </div>
                </div>
                {data.contact.notes && <p className="text-slate-500 italic">{data.contact.notes}</p>}
              </Section>

              <Section title="Giving towards sponsorships" icon={HeartHandshake}>
                {giving.length === 0 ? (
                  <p className="text-slate-400">{data.donor_type === 'manual' ? `Manual donor · recorded total ${money(data.contact.manual_total_donated)}` : 'No donations towards sponsorship causes found.'}</p>
                ) : (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    {giving.map(g => (
                      <div key={g.sponsorship_type} className={`p-3 rounded-xl border flex flex-col gap-1.5 ${g.sponsorship_type === focusType ? 'border-blue-400 bg-blue-50/40 dark:bg-blue-950/20' : 'border-slate-200 dark:border-slate-800'}`}>
                        <div className="flex items-center justify-between">
                          <span className="font-bold text-slate-800 dark:text-slate-100">{g.sponsorship_type}</span>
                          <span className="font-bold text-slate-900 dark:text-white">{money(g.total_settled)}{g.settlement_currencies.length && g.settlement_currencies.join('') !== 'GBP' ? ` (${g.settlement_currencies.join(', ')})` : ''}</span>
                        </div>
                        <div className="flex flex-wrap gap-1">
                          {Object.entries(g.by_currency).map(([c, v]) => (
                            <span key={c} className="px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 font-mono">{curSym(c)}{Number(v).toLocaleString()}</span>
                          ))}
                        </div>
                        <div className="grid grid-cols-2 gap-x-2 gap-y-1 text-slate-600 dark:text-slate-300">
                          <span className="flex items-center gap-1"><Layers className="w-3 h-3" /> {g.donation_count} donation{g.donation_count === 1 ? '' : 's'}</span>
                          <span className="flex items-center gap-1"><Gift className="w-3 h-3" /> Gift Aid: {g.gift_aid_count ? `${g.gift_aid_count} (${money(g.gift_aid_total)})` : 'No'}</span>
                          <span className="flex items-center gap-1 col-span-2"><Repeat className="w-3 h-3" /> {g.frequencies.join(', ') || '—'}</span>
                          <span className="col-span-2 flex flex-wrap gap-1">
                            {Object.entries(g.by_platform || {}).map(([p, v]) => (
                              <span key={p} className="px-1.5 py-0.5 rounded bg-blue-50 dark:bg-blue-950/40 text-blue-700 dark:text-blue-300">{p}: {money(v)}</span>
                            ))}
                            {g.manual_total > 0 && (
                              <span className="px-1.5 py-0.5 rounded bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-300">Manual entry: {money(g.manual_total)} (not in total)</span>
                            )}
                          </span>
                          <span className="flex items-center gap-1 col-span-2"><Calendar className="w-3 h-3" /> {g.first_donation || '—'} → {g.last_donation || '—'}</span>
                        </div>
                        <div className="pt-1.5 mt-0.5 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between">
                          <span>Slots: <strong>{g.slots_used}</strong> used of <strong>{g.max_slots}</strong></span>
                          <span className={g.slots_remaining > 0 ? 'text-emerald-600 font-bold' : 'text-slate-400'}>{g.slots_remaining} left</span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </Section>

              {(data.manual_entries || []).length > 0 && (
                <Section title="Manual / offline entries" icon={Layers}>
                  <p className="text-slate-500">Recorded by hand in the tracker, separate from the platform donations above (LaunchGood, GiveBrite, Madinah, website).</p>
                  {data.manual_entries.map(m => (
                    <div key={m.id} className="p-2.5 rounded-lg border border-amber-200 dark:border-amber-900 flex items-center justify-between gap-2">
                      <span><strong>{m.donor_name}</strong> · {m.sponsorship_type}{m.notes ? <span className="text-slate-500"> · {m.notes}</span> : null}</span>
                      <span className="font-bold">{money(m.total_donated)}{m.custom_slots ? <span className="font-normal text-slate-500"> · {m.custom_slots} slot(s)</span> : null}</span>
                    </div>
                  ))}
                </Section>
              )}

              <Section title={`Sponsorships (${data.sponsorships.length})`} icon={Users}>
                {data.sponsorships.length === 0 ? <p className="text-slate-400">Not on any sponsorship yet.</p> : (
                  <div className="flex flex-col gap-2">
                    {data.sponsorships.map(s => (
                      <div key={s.allocation_donor_id} className="p-3 rounded-xl border border-slate-200 dark:border-slate-800 flex flex-col gap-1">
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-bold text-slate-800 dark:text-slate-100">{s.beneficiary_name}
                            <span className="ml-1.5 font-normal text-slate-500">{s.sponsorship_type}{s.project_code ? ` · ${s.project_code}` : ''}</span>
                          </span>
                          <span className="font-bold">{money(s.contribution_amount)}{s.share_percent !== null ? <span className="font-normal text-slate-500"> · {s.share_percent}%</span> : null}</span>
                        </div>
                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-slate-500">
                          <span>{s.role === 'organizer' ? 'Organizer' : s.is_primary ? 'Primary donor' : 'Co-sponsor'}</span>
                          <span>{s.sponsorship_year}</span>
                          <span>{s.start_date} → {s.end_date}{s.days_remaining !== null ? ` (${s.days_remaining} days)` : ''}</span>
                          <span>{s.communication_status}</span>
                        </div>
                        {s.co_sponsors.length > 0 && (
                          <div className="text-slate-500">With: {s.co_sponsors.map(c => `${c.donor_name || c.donor_email} (${money(c.contribution_amount)})`).join(', ')}</div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </Section>

              <Section title={`Emails (${data.email_history.length}${data.pending_emails.length ? ` · ${data.pending_emails.length} queued` : ''})`} icon={Inbox}>
                {data.pending_emails.map(p => (
                  <div key={`q${p.id}`} className="p-2.5 rounded-lg border border-dashed border-amber-300 dark:border-amber-800 text-amber-800 dark:text-amber-300 flex items-center justify-between">
                    <span className="flex items-center gap-1.5"><Clock className="w-3.5 h-3.5" />Queued: {p.template_type.replace(/_/g, ' ')} — {p.reason}</span>
                    <span>due {p.due_date}</span>
                  </div>
                ))}
                {data.email_history.length === 0 && data.pending_emails.length === 0 && <p className="text-slate-400">No emails yet.</p>}
                {data.email_history.slice(0, 15).map(m => (
                  <div key={m.id} className="p-2.5 rounded-lg border border-slate-200 dark:border-slate-800 flex items-center justify-between gap-2">
                    <span className="min-w-0">
                      <span className={`mr-1.5 px-1.5 py-0.5 rounded text-xs font-bold ${m.direction === 'inbound' ? 'bg-purple-100 text-purple-700 dark:bg-purple-950 dark:text-purple-300' : 'bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300'}`}>
                        {m.direction === 'inbound' ? 'Reply' : 'Sent'}
                      </span>
                      <span className="text-slate-700 dark:text-slate-200">{m.subject || '(no subject)'}</span>
                    </span>
                    <span className="flex items-center gap-2 text-slate-500 shrink-0">
                      {m.direction === 'outbound' && m.open_count > 0 && <span className="flex items-center gap-0.5"><Eye className="w-3 h-3" />{m.open_count}</span>}
                      {m.delivery_status === 'replied' && <Reply className="w-3 h-3 text-purple-600" />}
                      {(m.sent_at || '').slice(0, 10)}
                    </span>
                  </div>
                ))}
              </Section>

              <Section title={`Sponsorship donations (${filtersOn ? `${donations.length} of ${allDonations.length}` : allDonations.length})`} icon={Layers}
                right={!filtersOn && donations.length > 10 && (
                  <button type="button" onClick={() => setShowAllDonations(!showAllDonations)} className="text-blue-600 font-semibold hover:underline">
                    {showAllDonations ? 'Show fewer' : `Show all ${donations.length}`}
                  </button>
                )}>
                {allDonations.length > 0 && (
                  <div className="flex flex-wrap items-end gap-2 p-3 rounded-xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800">
                    <label className="flex flex-col gap-1 text-xs font-semibold text-slate-500">From<input type="date" value={dFrom} onChange={e => setDFrom(e.target.value)} className="px-2 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-950 text-sm" /></label>
                    <label className="flex flex-col gap-1 text-xs font-semibold text-slate-500">To<input type="date" value={dTo} onChange={e => setDTo(e.target.value)} className="px-2 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-950 text-sm" /></label>
                    <label className="flex flex-col gap-1 text-xs font-semibold text-slate-500">Cause
                      <select value={dType} onChange={e => setDType(e.target.value)} className="px-2 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-950 text-sm">
                        <option value="all">All sponsorships</option>{donationTypes.map(t => <option key={t}>{t}</option>)}
                      </select>
                    </label>
                    <label className="flex flex-col gap-1 text-xs font-semibold text-slate-500">Platform
                      <select value={dPlatform} onChange={e => setDPlatform(e.target.value)} className="px-2 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-950 text-sm">
                        <option value="all">All platforms</option>{donationPlatforms.map(t => <option key={t}>{t}</option>)}
                      </select>
                    </label>
                    <label className="flex flex-col gap-1 text-xs font-semibold text-slate-500 flex-1 min-w-[12rem]">Search
                      <span className="relative"><Search className="w-4 h-4 absolute left-2 top-1/2 -translate-y-1/2 text-slate-400" />
                        <input value={dSearch} onChange={e => setDSearch(e.target.value)} placeholder="Campaign, code, fundraiser, ID" className="w-full pl-8 pr-2 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-950 text-sm" /></span>
                    </label>
                    {filtersOn && <button type="button" onClick={() => { setDFrom(''); setDTo(''); setDType('all'); setDPlatform('all'); setDSearch(''); }} className="text-sm text-blue-600 font-semibold pb-1.5">Clear</button>}
                    <span className="text-sm text-slate-600 dark:text-slate-300 pb-1.5 ml-auto">{donations.length} donation{donations.length === 1 ? '' : 's'} · <b>{money(filteredSettled)}</b> settled</span>
                  </div>
                )}
                {donations.length === 0 ? <p className="text-slate-400">{allDonations.length ? 'No donations match these filters.' : 'No sponsorship donations on record.'}</p> : (
                  <div className="overflow-x-auto rounded-xl border border-slate-200 dark:border-slate-800">
                    <table className="w-full text-left">
                      <thead className="bg-slate-50 dark:bg-slate-900 text-slate-500">
                        <tr>
                          {['Date', 'Amount', 'Settled', 'Type', 'Campaign', 'Giving level', 'Code', 'Heading', 'Sub-heading', 'Fundraiser', 'Gift Aid', 'Frequency', 'Method', 'Status', 'Platform', 'Donation ID'].map(h => <th key={h} className="px-3 py-2.5 font-semibold whitespace-nowrap">{h}</th>)}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                        {visibleDonations.map((d, i) => (
                          <tr key={`${d.donation_id}_${i}`} className="text-slate-700 dark:text-slate-200 cursor-pointer hover:bg-blue-50/60 dark:hover:bg-blue-950/30"
                            onClick={() => d.donation_id && setOpenDonation(d)} title="Click for full donation details">
                            <td className="px-3 py-2 whitespace-nowrap">{d.date}</td>
                            <td className="px-3 py-2 whitespace-nowrap font-mono">{d.amount === null ? '—' : `${curSym(d.currency)}${Number(d.amount).toLocaleString()}`}</td>
                            <td className="px-3 py-2 whitespace-nowrap font-mono">{d.settled_amount === null ? '—' : `${curSym(d.settlement_currency)}${Number(d.settled_amount).toLocaleString()}`}</td>
                            <td className="px-3 py-2 whitespace-nowrap">{d.sponsorship_type}</td>
                            <td className="px-3 py-2 min-w-[12rem]" title={d.campaign}>{d.campaign}</td>
                            <td className="px-3 py-2 whitespace-nowrap">{d.giving_level || '—'}</td>
                            <td className="px-3 py-2 whitespace-nowrap font-mono">{d.code || '—'}</td>
                            <td className="px-3 py-2 whitespace-nowrap">{d.heading || '—'}</td>
                            <td className="px-3 py-2 whitespace-nowrap">{d.sub_heading || '—'}</td>
                            <td className="px-3 py-2 whitespace-nowrap">{d.fundraiser || '—'}</td>
                            <td className="px-2.5 py-1.5">{d.gift_aid || '—'}</td>
                            <td className="px-3 py-2 whitespace-nowrap">{d.frequency || '—'}</td>
                            <td className="px-3 py-2 whitespace-nowrap">{d.payment_method || '—'}</td>
                            <td className="px-3 py-2 whitespace-nowrap">{d.status || '—'}</td>
                            <td className="px-3 py-2 whitespace-nowrap">{d.platform}</td>
                            <td className="px-3 py-2 whitespace-nowrap font-mono text-xs">{d.donation_id}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Section>
            </>
          )}
        </div>
      </aside>
      {openDonation && (
        <span onClick={e => e.stopPropagation()}>
          <DonationDetailModal donationId={String(openDonation.donation_id)} companyId={companyId} onClose={() => setOpenDonation(null)} onChanged={() => setReloadTick(t => t + 1)} />
        </span>
      )}
      {adding && (
        <span onClick={e => e.stopPropagation()}>
          <AddDonationModal company={companyId}
            donor={{ name: data?.contact?.name, email: primaryEmail, phone: data?.contact?.phone, country: data?.contact?.country }}
            defaults={focusType ? { campaign_name: `${focusType} Sponsorship` } : {}}
            onClose={() => setAdding(false)} onCreated={() => setReloadTick(t => t + 1)} />
        </span>
      )}
      {emailing && (
        <span onClick={e => e.stopPropagation()}>
          <SingleEmailComposer company={companyId} recipient={{ email: primaryEmail, name: data?.contact?.name || '', donor_id: primaryEmail.toLowerCase() }}
            onClose={() => setEmailing(false)} onSent={() => setReloadTick(t => t + 1)} />
        </span>
      )}
    </div>
  );
}
