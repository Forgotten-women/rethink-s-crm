import React, { useEffect, useState } from 'react';
import { Mail, Plus, Send, XCircle, Trash2, ChevronDown, ChevronUp, RefreshCw, Users, Pencil, Tags, RotateCcw } from 'lucide-react';
import { API_BASE_URL } from '../../config';
import EmailComposer from '../EmailComposer';
import { segmentChips } from '../SegmentBuilder';
import { denyUnless } from '../../access';

// Outreach statuses the campaign's sponsorships can be marked as (mirrors CAMPAIGN_MARK_STATUSES in the backend)
const MARK_STATUSES = ['First Mailed', 'Profile Sent', 'Welcome Sent', 'Update Sent', 'Video Sent',
  'Feedback Sent', 'Annual Report Sent', 'Renewal Sent', 'Donor Replied'];

const STATUS_TONE = {
  queued: 'bg-amber-500/15 text-amber-700 dark:text-amber-300', sending: 'bg-sky-500/15 text-sky-700 dark:text-sky-300',
  done: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300', cancelled: 'bg-slate-500/15 text-slate-500',
};

async function call(method, path, body) {
  const res = await fetch(`${API_BASE_URL}${path}`, { method, headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Error ${res.status}`);
  return data;
}

/**
 * Email queue by segment: each campaign is one group of people (any filters) with one template. Create as many as
 * needed - e.g. "Hafiz donors since January" with one template, "High-end donors with 2+ sponsorships" with another -
 * then send each in batches, watch sent / opened, cancel what's left.
 */
export default function EmailCampaignsView({ companyId }) {
  const [campaigns, setCampaigns] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [composer, setComposer] = useState(false);
  const [open, setOpen] = useState(null);
  const [messages, setMessages] = useState({});
  const [sending, setSending] = useState(null);
  const [notice, setNotice] = useState('');
  const [composerDonors, setComposerDonors] = useState(null);

  const rename = async (c) => {
    if (denyUnless('email.campaigns')) return;
    const name = window.prompt('New name for this campaign:', c.name);
    if (!name || !name.trim() || name.trim() === c.name) return;
    setError('');
    try { await call('PATCH', `/api/tracker/direct-email/campaigns/${c.id}`, { company_id: companyId, name: name.trim() }); load(); }
    catch (e) { setError(e.message); }
  };

  // "Email again": reuse this campaign's recipients in the composer - pick any template / message, and the send
  // becomes a NEW campaign of its own (separate name, counts and tracking).
  const emailAgain = async (c) => {
    if (denyUnless('email.campaigns')) return;
    setError(''); setNotice('');
    try {
      const ids = new Set();
      for (let page = 1; page <= 20; page += 1) {
        const d = await call('GET', `/api/tracker/direct-email/campaigns/${c.id}/messages?company_id=${encodeURIComponent(companyId)}&status=sent&page=${page}&page_size=500`);
        (d.messages || []).forEach(m => { const k = m.donor_id || m.recipient_email; if (k) ids.add(k); });
        if (page * 500 >= (d.total || 0)) break;
      }
      if (!ids.size) { setError('This campaign has no sent emails yet, so there is nobody to email again.'); return; }
      setComposerDonors([...ids]);
      setComposer(true);
    } catch (e) { setError(e.message); }
  };

  const markSponsorships = async (c, status) => {
    if (!status || denyUnless('tracker.edit')) return;
    if (!window.confirm(`Mark the sponsorships of everyone "${c.name}" was SENT to as "${status}"?\n\nThis sets their outreach status in the Sponsorship Tracker.`)) return;
    setError(''); setNotice('');
    try {
      const d = await call('POST', `/api/tracker/direct-email/campaigns/${c.id}/mark-sponsorships`, { company_id: companyId, communication_status: status });
      setNotice(`"${c.name}": ${d.sponsorships_marked} sponsorship(s) across ${d.donors_covered} donor(s) marked "${status}"`
        + (d.donors_without_sponsorships?.length ? ` — ${d.donors_without_sponsorships.length} recipient(s) have no sponsorship: ${d.donors_without_sponsorships.slice(0, 5).join(', ')}${d.donors_without_sponsorships.length > 5 ? '…' : ''}` : ''));
    } catch (e) { setError(e.message); }
  };

  const load = async () => {
    setLoading(true); setError('');
    try { setCampaigns((await call('GET', `/api/tracker/direct-email/campaigns?company_id=${encodeURIComponent(companyId)}`)).campaigns || []); }
    catch (e) { setError(e.message); } finally { setLoading(false); }
  };
  useEffect(() => { if (companyId && companyId !== 'all') load(); }, [companyId]); // eslint-disable-line react-hooks/exhaustive-deps

  const loadMessages = async (id) => {
    try { const d = await call('GET', `/api/tracker/direct-email/campaigns/${id}/messages?company_id=${encodeURIComponent(companyId)}&page_size=500`); setMessages(m => ({ ...m, [id]: d.messages })); }
    catch (e) { setError(e.message); }
  };

  const sendAll = async (c) => {
    if (!window.confirm(`Send "${c.name}" to the ${c.pending} people still pending?`)) return;
    setError(''); setSending({ id: c.id, done: 0, total: c.pending });
    let remaining = c.pending, done = 0;
    try {
      while (remaining > 0) {
if (denyUnless('email.send')) return;
        const d = await call('POST', `/api/tracker/direct-email/campaigns/${c.id}/send`, { company_id: companyId, limit: 25 });
        done += d.results.length; remaining = d.remaining;
        setSending({ id: c.id, done, total: done + remaining });
        if (!d.results.length) break;
      }
    } catch (e) { setError(e.message); }
    setSending(null); load(); if (open === c.id) loadMessages(c.id);
  };

  if (companyId === 'all') return <div className="glass-panel p-6 text-sm" style={{ color: 'var(--text-muted)' }}>Choose a charity to manage its email campaigns.</div>;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h3 className="text-base font-black flex items-center gap-2" style={{ color: 'var(--text-main)' }}><Mail className="w-5 h-5 text-sky-500" /> Email campaigns</h3>
          <p className="text-sm" style={{ color: 'var(--text-muted)' }}>Each campaign is one group of donors (any filters you like) with its own template. Make one per group, then send.</p>
        </div>
        <div className="flex gap-2">
          <button type="button" onClick={load} className="px-3 py-2 text-sm rounded-lg border flex items-center gap-1.5" style={{ borderColor: 'var(--border-glass)', color: 'var(--text-sub)' }}><RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} /> Refresh</button>
          <button type="button" onClick={() => setComposer(true)} className="px-3 py-2 text-sm rounded-lg bg-sky-600 hover:bg-sky-500 text-white font-bold flex items-center gap-1.5"><Plus className="w-4 h-4" /> New campaign / email</button>
        </div>
      </div>
      {error && <div className="text-sm rounded-lg px-3 py-2 bg-rose-500/10 text-rose-600 dark:text-rose-400 border border-rose-500/25">{error}</div>}
      {notice && <div className="text-sm rounded-lg px-3 py-2 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border border-emerald-500/25">{notice}</div>}
      {!loading && campaigns.length === 0 && <div className="glass-panel p-8 text-center text-sm" style={{ color: 'var(--text-muted)' }}>No campaigns yet. Use “New campaign / email” to pick a group of donors and a template.</div>}
      {campaigns.map(c => (
        <div key={c.id} className="glass-panel overflow-hidden">
          <div className="p-4 flex items-start justify-between gap-3 flex-wrap">
            <div className="min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-sm font-black" style={{ color: 'var(--text-main)' }}>{c.name}</span>
                <button type="button" onClick={() => rename(c)} title="Rename campaign" aria-label="Rename campaign"
                  className="p-1 rounded hover:bg-sky-500/10" style={{ color: 'var(--text-muted)' }}><Pencil className="w-3.5 h-3.5" /></button>
                <span className={`text-[11px] px-2 py-0.5 rounded-full font-bold ${STATUS_TONE[c.status] || ''}`}>{c.status}</span>
                <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
                  {c.template_type?.replace(/_/g, ' ')} · {c.theme} · {String(c.created_at || '').slice(0, 16)}
                  {c.sender_email ? ` · from ${c.sender_email}` : ''}
                  {c.created_by ? ` · by ${c.created_by}` : ''}
                </span>
              </div>
              {c.segment && <div className="text-[11px] mt-1" style={{ color: 'var(--text-muted)' }}>{segmentChips(c.segment).map(x => x.text).join(' · ')}</div>}
              <div className="flex gap-4 mt-2 text-sm tabular-nums" style={{ color: 'var(--text-main)' }}>
                <span><Users className="w-3.5 h-3.5 inline" /> {c.total}</span>
                <span className="text-emerald-600">sent {c.sent || 0}</span>
                <span className="text-sky-600">opened {c.opened || 0}</span>
                <span className="text-amber-600">pending {c.pending || 0}</span>
                {c.skipped > 0 && <span style={{ color: 'var(--text-muted)' }}>skipped {c.skipped}</span>}
                {c.failed > 0 && <span className="text-rose-600">failed {c.failed}</span>}
              </div>
              {sending?.id === c.id && <div className="text-xs mt-1 text-sky-600">Sending… {sending.done}/{sending.total}</div>}
            </div>
            <div className="flex gap-2 flex-wrap items-start">
              {(c.sent || 0) > 0 && (
                <button type="button" disabled={!!sending} onClick={() => emailAgain(c)} title="Reuse everyone this campaign was sent to in a new campaign - pick any template; it is tracked as its own campaign"
                  className="px-3 py-1.5 text-sm rounded-lg border font-bold flex items-center gap-1 disabled:opacity-40" style={{ borderColor: 'var(--border-glass)', color: 'var(--text-sub)' }}>
                  <RotateCcw className="w-4 h-4 text-sky-500" /> Email again
                </button>
              )}
              {(c.sent || 0) > 0 && (
                <label className="flex items-center gap-1 text-sm rounded-lg border px-2 py-1" style={{ borderColor: 'var(--border-glass)', color: 'var(--text-sub)' }} title="Set the outreach status on the sponsorships of everyone this campaign was sent to">
                  <Tags className="w-4 h-4 text-indigo-500" />
                  <select value="" onChange={e => { markSponsorships(c, e.target.value); e.target.value = ''; }}
                    className="bg-transparent text-sm focus:outline-none cursor-pointer" style={{ color: 'var(--text-sub)' }}>
                    <option value="" disabled>Mark sponsorships…</option>
                    {MARK_STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
                  </select>
                </label>
              )}
              {c.pending > 0 && ['queued', 'sending'].includes(c.status) && (
                <button type="button" disabled={!!sending} onClick={() => sendAll(c)} className="px-3 py-1.5 text-sm rounded-lg bg-sky-600 hover:bg-sky-500 text-white font-bold disabled:opacity-40 flex items-center gap-1"><Send className="w-4 h-4" /> Send {c.pending}</button>
              )}
              {c.pending > 0 && ['queued', 'sending'].includes(c.status) && (
                <button type="button" onClick={async () => { if (window.confirm('Cancel the emails still pending?')) { try { await call('POST', `/api/tracker/direct-email/campaigns/${c.id}/cancel`, { company_id: companyId }); load(); } catch (e) { setError(e.message); } } }}
                  className="px-3 py-1.5 text-sm rounded-lg border flex items-center gap-1" style={{ borderColor: 'var(--border-glass)', color: 'var(--text-sub)' }}><XCircle className="w-4 h-4" /> Cancel</button>
              )}
              {!c.sent && (
                <button type="button" onClick={async () => { if (window.confirm('Delete this campaign?')) { try { await call('DELETE', `/api/tracker/direct-email/campaigns/${c.id}?company_id=${encodeURIComponent(companyId)}`); load(); } catch (e) { setError(e.message); } } }}
                  className="px-2.5 py-1.5 text-sm rounded-lg text-rose-500" aria-label="Delete campaign"><Trash2 className="w-4 h-4" /></button>
              )}
              <button type="button" onClick={() => { const n = open === c.id ? null : c.id; setOpen(n); if (n) loadMessages(n); }} className="px-2.5 py-1.5 text-sm rounded-lg" style={{ color: 'var(--text-sub)' }} aria-label="Show recipients">
                {open === c.id ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
              </button>
            </div>
          </div>
          {open === c.id && (
            <div className="border-t max-h-80 overflow-y-auto" style={{ borderColor: 'var(--border-glass)' }}>
              <table className="w-full text-sm">
                <thead style={{ color: 'var(--text-sub)' }}><tr>{['Name', 'Email', 'Status', 'Sent', 'Opened', 'Note'].map(h => <th key={h} className="px-3 py-1.5 text-left text-xs font-bold">{h}</th>)}</tr></thead>
                <tbody>
                  {(messages[c.id] || []).map(m => (
                    <tr key={m.id} className="border-t" style={{ borderColor: 'var(--border-glass)', color: 'var(--text-main)' }}>
                      <td className="px-3 py-1.5">{m.recipient_name || '—'}{m.about && <span className="ml-1 text-[10px] text-slate-500">· about {m.about}</span>}</td><td className="px-3 py-1.5">{m.recipient_email}</td>
                      <td className="px-3 py-1.5">{m.status}</td><td className="px-3 py-1.5 tabular-nums">{String(m.sent_at || '').slice(0, 16) || '—'}</td>
                      <td className="px-3 py-1.5">{m.open_count ? `${m.open_count}×` : '—'}</td><td className="px-3 py-1.5 text-xs" style={{ color: 'var(--text-muted)' }}>{m.detail || ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ))}
      {composer && <EmailComposer company={companyId} startAsCampaign initialDonorIds={composerDonors || []}
        onClose={() => { setComposer(false); setComposerDonors(null); }} onDone={load} />}
    </div>
  );
}
