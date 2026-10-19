import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { ArrowDownLeft, ArrowUpRight, Inbox, LayoutTemplate, ListChecks, Mail, MailOpen, Activity, PenSquare, Search, UserMinus, X } from 'lucide-react';
import { API_BASE_URL } from '../../config';
import BulkEmailComposer from './BulkEmailComposer';
import EmailThread, { localTime } from './EmailThread';
import EmailCampaignsView from '../tracker/EmailCampaignsView';
import TrackerView from '../TrackerView';
import { FIELD, post } from './emailUi';
import GmailMailbox from './GmailMailbox';
import { OPEN_UNSUBSCRIBES_EVENT, UNSUBSCRIBES_SEEN_EVENT, takePendingOpen } from './unsubscribeAlerts';

const TABS = [
  ['compose', 'Compose', PenSquare], ['campaigns', 'Campaigns', ListChecks], ['activity', 'Sent & replies', Activity],
  ['queue', 'Sponsorship queue', Inbox], ['templates', 'Templates', LayoutTemplate], ['mailbox', 'Mailbox (Outlook)', Mail],
  ['unsubscribed', 'Unsubscribed', UserMinus],
];

/** Everyone who pressed Unsubscribe in one of this charity's emails (their marketing consent was set to No). */
function UnsubscribedList({ company, user, onSelectDonor }) {
  const [data, setData] = useState(null);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [busy, setBusy] = useState('');
  const PAGE = 25;
  const load = () => fetch(`${API_BASE_URL}/api/email/unsubscribes?company_id=${encodeURIComponent(company)}`)
    .then(r => (r.ok ? r.json() : { items: [] })).then(setData).catch(() => setData({ items: [] }));
  useEffect(() => { setData(null); load(); }, [company]); // eslint-disable-line react-hooks/exhaustive-deps
  const markSeen = async (ids) => {
    setBusy('seen');
    try { await post('/api/email/unsubscribes/mark-seen', { company_id: company, ids }); await load(); window.dispatchEvent(new Event(UNSUBSCRIBES_SEEN_EVENT)); }
    catch (e) { alert(e.message); } finally { setBusy(''); }
  };
  const resubscribe = async (email) => {
    if (!window.confirm(`Only do this if ${email} asked to get emails again. Their marketing consent stays No until you change it on the donor. Continue?`)) return;
    setBusy(email);
    try { await post('/api/email/unsubscribes/resubscribe', { company_id: company, email }); await load(); window.dispatchEvent(new Event(UNSUBSCRIBES_SEEN_EVENT)); }
    catch (e) { alert(e.message); } finally { setBusy(''); }
  };
  const items = (data?.items || []).filter(i => !search.trim() || `${i.name || ''} ${i.email}`.toLowerCase().includes(search.trim().toLowerCase()));
  const pages = Math.max(1, Math.ceil(items.length / PAGE));
  const p = Math.min(page, pages);
  const rows = items.slice((p - 1) * PAGE, p * PAGE);
  const canResub = ['admin', 'super_admin'].includes(user?.role);
  return (
    <div className="rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-700 flex items-center gap-2 flex-wrap">
        <div className="text-sm font-bold text-slate-900 dark:text-white">Unsubscribed <span className="font-normal text-slate-500">({data?.items?.length ?? '…'})</span></div>
        {data?.unseen > 0 && <span className="px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300 text-xs font-bold">{data.unseen} new</span>}
        <span className="text-xs text-slate-500">They pressed Unsubscribe in an email: marketing consent is No and bulk / sponsorship emails skip them.</span>
        <span className="ml-auto flex items-center gap-2">
          <span className="relative">
            <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
            <input value={search} onChange={e => { setSearch(e.target.value); setPage(1); }} placeholder="Search name or email" className={`${FIELD} !w-56 pl-8 pr-2 py-1.5 text-xs`} />
          </span>
          {data?.unseen > 0 && <button type="button" disabled={!!busy} onClick={() => markSeen(null)} className="px-3 py-1.5 rounded-lg bg-sky-600 hover:bg-sky-700 text-white text-xs font-bold disabled:opacity-50">Mark all as seen</button>}
        </span>
      </div>
      {!data && <div className="p-6 text-center text-xs text-slate-500">Loading…</div>}
      {data && items.length === 0 && <div className="p-6 text-center text-xs text-slate-500">{search ? 'No one matches.' : 'No one has unsubscribed.'}</div>}
      {rows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="bg-slate-50 dark:bg-slate-950 text-slate-500"><tr>{['Person', 'Unsubscribed', 'From the email', 'Gifts set to No', 'Seen', ''].map(h => <th key={h} className="px-3 py-2 text-left font-bold whitespace-nowrap">{h}</th>)}</tr></thead>
            <tbody>
              {rows.map(i => (
                <tr key={i.id} className={`border-t border-slate-100 dark:border-slate-800 text-slate-800 dark:text-slate-100 ${!i.seen_at ? 'bg-amber-50/60 dark:bg-amber-950/20' : ''}`}>
                  <td className="px-3 py-1.5">
                    <button type="button" onClick={() => onSelectDonor?.({ donor_id: i.email, email: i.email, name: i.name })} className="text-left hover:text-sky-600">
                      <span className="font-semibold">{i.name || i.email}</span>{i.name && <span className="block text-[10px] text-slate-500">{i.email}</span>}
                    </button>
                  </td>
                  <td className="px-3 py-1.5 tabular-nums whitespace-nowrap">{localTime(i.unsubscribed_at)}</td>
                  <td className="px-3 py-1.5 max-w-[18rem] truncate" title={i.subject || ''}>{i.subject || '—'}</td>
                  <td className="px-3 py-1.5 tabular-nums">{i.gifts_updated}</td>
                  <td className="px-3 py-1.5 whitespace-nowrap">{i.seen_at ? <span className="text-slate-500">{i.seen_by || 'yes'}</span> : <button type="button" disabled={!!busy} onClick={() => markSeen([i.id])} className="text-sky-600 hover:underline font-semibold">Mark seen</button>}</td>
                  <td className="px-3 py-1.5 text-right">{canResub && <button type="button" disabled={!!busy} onClick={() => resubscribe(i.email)} className="text-slate-500 hover:text-slate-800 dark:hover:text-white underline-offset-2 hover:underline">Resubscribe</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {pages > 1 && (
        <div className="px-4 py-2 border-t border-slate-200 dark:border-slate-700 flex items-center justify-between text-xs text-slate-500">
          <span>{(p - 1) * PAGE + 1}–{Math.min(p * PAGE, items.length)} of {items.length}</span>
          <span className="flex gap-1">
            <button type="button" disabled={p <= 1} onClick={() => setPage(p - 1)} className="px-2.5 py-1 rounded border border-slate-200 dark:border-slate-700 disabled:opacity-40">Previous</button>
            <span className="px-2 py-1">Page {p} of {pages}</span>
            <button type="button" disabled={p >= pages} onClick={() => setPage(p + 1)} className="px-2.5 py-1 rounded border border-slate-200 dark:border-slate-700 disabled:opacity-40">Next</button>
          </span>
        </div>
      )}
    </div>
  );
}

function ActivityFeed({ company, onSelectDonor }) {
  const [direction, setDirection] = useState('');
  const [search, setSearch] = useState('');
  const [items, setItems] = useState(null);
  const [thread, setThread] = useState(null);
  const [tick, setTick] = useState(0);
  useEffect(() => { const t = setInterval(() => setTick(x => x + 1), 60000); return () => clearInterval(t); }, []);
  useEffect(() => {
    if (!tick) setItems(null);
    const t = setTimeout(() => {
      const qs = new URLSearchParams({ company_id: company, limit: '300' });
      if (direction) qs.set('direction', direction);
      if (search.trim()) qs.set('search', search.trim());
      fetch(`${API_BASE_URL}/api/tracker/direct-email/activity?${qs}`)
        .then(r => (r.ok ? r.json() : { items: [] })).then(d => setItems(d.items || [])).catch(() => setItems([]));
    }, search ? 300 : 0);
    return () => clearTimeout(t);
  }, [company, direction, search, tick]);
  return (
    <div className="rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-700 flex items-center gap-2 flex-wrap">
        {[['', 'Everything'], ['out', 'Sent'], ['in', 'Replies']].map(([v, l]) => (
          <button key={l} type="button" onClick={() => setDirection(v)}
            className={`px-3 py-1 rounded-full text-xs font-bold ${direction === v ? 'bg-sky-600 text-white' : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300'}`}>{l}</button>
        ))}
        <span className="relative ml-auto">
          <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search person or subject" className={`${FIELD} !w-64 pl-8 pr-2 py-1.5 text-xs`} />
        </span>
      </div>
      {!items && <div className="p-6 text-center text-xs text-slate-500">Loading…</div>}
      {items && items.length === 0 && <div className="p-6 text-center text-xs text-slate-500">Nothing here yet.</div>}
      {items && items.length > 0 && (
        <div className="max-h-[70vh] overflow-y-auto">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-slate-50 dark:bg-slate-950 text-slate-500"><tr>{['', 'When', 'Person', 'Subject', 'From', 'Status'].map(h => <th key={h} className="px-3 py-2 text-left font-bold">{h}</th>)}</tr></thead>
            <tbody>
              {items.map(i => (
                <tr key={i.id} className="border-t border-slate-100 dark:border-slate-800 text-slate-800 dark:text-slate-100 hover:bg-sky-50/60 dark:hover:bg-sky-950/20">
                  <td className="px-3 py-1.5">{i.direction === 'out' ? <ArrowUpRight className="w-3.5 h-3.5 text-sky-500" /> : <ArrowDownLeft className="w-3.5 h-3.5 text-emerald-600" />}</td>
                  <td className="px-3 py-1.5 tabular-nums whitespace-nowrap">{localTime(i.at)}</td>
                  <td className="px-3 py-1.5">
                    <button type="button" onClick={() => onSelectDonor?.({ donor_id: String(i.email || '').toLowerCase(), email: i.email, name: i.name })} className="text-left hover:text-sky-600">
                      <span className="font-semibold">{i.name || i.email}</span>{i.name && <span className="block text-[10px] text-slate-500">{i.email}</span>}
                    </button>
                  </td>
                  <td className="px-3 py-1.5 max-w-[22rem]">
                    <button type="button" onClick={() => setThread(i)} className="text-left hover:text-sky-600 truncate block max-w-full" title="Open the conversation">{i.subject || '(no subject)'}</button>
                    {i.direction === 'in' && i.body_preview && <span className="block text-[10px] text-slate-500 truncate">{i.body_preview}</span>}
                  </td>
                  <td className="px-3 py-1.5 text-slate-500">{i.source}</td>
                  <td className="px-3 py-1.5 whitespace-nowrap">
                    {i.direction === 'out'
                      ? <span className="flex items-center gap-1.5">{i.status}{i.open_count > 0 && <span className="flex items-center gap-0.5 text-sky-600" title="Opened"><MailOpen className="w-3 h-3" />{i.open_count}×</span>}{i.replied_at && <span className="px-1.5 rounded bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300 font-semibold">replied</span>}</span>
                      : <span className="text-emerald-600 font-semibold">reply</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {thread && createPortal(
        <div className="fixed inset-0 z-[90] flex justify-end" role="dialog" aria-modal="true" aria-label="Conversation">
          <div className="absolute inset-0 bg-black/40" onClick={() => setThread(null)} />
          <div className="relative w-full max-w-2xl h-full bg-white dark:bg-slate-900 border-l border-slate-200 dark:border-slate-700 p-4 overflow-y-auto">
            <div className="flex items-center justify-between gap-2 mb-3">
              <div className="text-sm font-bold text-slate-900 dark:text-white">{thread.name || thread.email}<span className="block text-xs font-normal text-slate-500">{thread.email}</span></div>
              <button type="button" onClick={() => setThread(null)} aria-label="Close" className="w-8 h-8 rounded-full flex items-center justify-center text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"><X className="w-4 h-4" /></button>
            </div>
            <EmailThread company={company} email={thread.email} />
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
}

/**
 * The Email section: everything about emailing donors in one place - compose to many people (chosen by their
 * donations), campaigns, everything sent and every reply, the sponsorship email queue, templates and the
 * charity's mailbox. Writing to ONE person stays on that person (donor panel / sponsorship): a single email.
 */
export default function EmailView({ user, activeCompany, onSelectDonor, preset }) {
  const [tab, setTab] = useState(() => (takePendingOpen() ? 'unsubscribed' : (sessionStorage.getItem('crm_email_tab') || 'compose')));
  const [mailProvider, setMailProvider] = useState(null);
  useEffect(() => { try { sessionStorage.removeItem('crm_email_tab'); } catch { /* ignore */ } }, []);
  useEffect(() => {
    setMailProvider(null);
    if (!activeCompany || activeCompany === 'all') return;
    fetch(`${API_BASE_URL}/api/mailbox/status?company_id=${encodeURIComponent(activeCompany)}`)
      .then(r => (r.ok ? r.json() : null)).then(d => setMailProvider(d?.provider || 'outlook')).catch(() => setMailProvider('outlook'));
  }, [activeCompany]);
  const [composeKey, setComposeKey] = useState(0);
  useEffect(() => { if (preset) { setTab('compose'); setComposeKey(k => k + 1); } }, [preset]);
  useEffect(() => {
    const open = () => { takePendingOpen(); setTab('unsubscribed'); };
    window.addEventListener(OPEN_UNSUBSCRIBES_EVENT, open);
    return () => window.removeEventListener(OPEN_UNSUBSCRIBES_EVENT, open);
  }, []);

  if (!activeCompany || activeCompany === 'all') {
    return <div className="p-6 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-sm text-slate-500">Choose Rethink or Iqra to email from that charity's mailbox.</div>;
  }
  return (
    <div className="flex flex-col gap-4 p-1 md:p-2">
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3 bg-white/80 dark:bg-slate-900/80 p-4 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-gradient-to-br from-sky-500 to-blue-600 text-white shadow-md"><Mail className="w-5 h-5" /></div>
          <div>
            <h1 className="text-xl font-black text-slate-800 dark:text-white tracking-tight">Email <span className="text-xs uppercase px-2 py-0.5 rounded-full font-bold bg-sky-50 dark:bg-sky-950/60 text-sky-600 dark:text-sky-400 border border-sky-200 dark:border-sky-800 align-middle">{activeCompany}</span></h1>
            <p className="text-xs text-slate-500">Choose people by their donations - one email per person, everything they gave and sponsor combined. To write to one person, open them and press Email.</p>
          </div>
        </div>
        <div className="flex flex-wrap items-center bg-slate-100 dark:bg-slate-800/80 p-1 rounded-xl border border-slate-200 dark:border-slate-700 gap-1">
          {TABS.map(([id, label0, Icon]) => { const label = id === 'mailbox' ? (mailProvider === 'gmail' ? 'Mailbox (Gmail)' : 'Mailbox (Outlook)') : label0; return (
            <button key={id} type="button" onClick={() => setTab(id)}
              className={`px-3 py-1.5 rounded-lg text-xs font-bold flex items-center gap-1.5 ${tab === id ? 'bg-white dark:bg-slate-900 text-sky-600 dark:text-sky-400 shadow-sm border border-slate-200 dark:border-slate-700' : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'}`}>
              <Icon className="w-3.5 h-3.5" />{label}
            </button>
          ); })}
        </div>
      </div>
      {tab === 'compose' && <BulkEmailComposer key={`${activeCompany}-${composeKey}`} inline company={activeCompany} initialSegment={preset?.segment || {}} />}
      {tab === 'campaigns' && <EmailCampaignsView companyId={activeCompany} />}
      {tab === 'activity' && <ActivityFeed company={activeCompany} onSelectDonor={onSelectDonor} />}
      {tab === 'queue' && <TrackerView key={`queue-${activeCompany}`} embeddedTab="queue" user={user} activeCompany={activeCompany} onSelectDonor={onSelectDonor} />}
      {tab === 'templates' && <TrackerView key={`tpl-${activeCompany}`} embeddedTab="templates" user={user} activeCompany={activeCompany} onSelectDonor={onSelectDonor} />}
      {tab === 'unsubscribed' && <UnsubscribedList company={activeCompany} user={user} onSelectDonor={onSelectDonor} />}
      {tab === 'mailbox' && mailProvider === 'gmail' && <GmailMailbox company={activeCompany} user={user} />}
      {tab === 'mailbox' && mailProvider && mailProvider !== 'gmail' && <TrackerView key={`mail-${activeCompany}`} embeddedTab="outlook" user={user} activeCompany={activeCompany} onSelectDonor={onSelectDonor} />}
    </div>
  );
}
