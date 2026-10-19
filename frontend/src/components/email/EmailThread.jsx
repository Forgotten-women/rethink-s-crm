import React, { useEffect, useMemo, useState } from 'react';
import { ArrowDownLeft, ArrowUpRight, ChevronDown, Eye, MailOpen, MessageSquareReply, RefreshCw } from 'lucide-react';
import { API_BASE_URL } from '../../config';

const subjectKey = (s) => String(s || '').replace(/^\s*((re|fw|fwd)\s*:\s*)+/i, '').trim().toLowerCase();
// Stored times are UTC; show them in the viewer's own time zone (an email sent at 14:10 shows as 14:10)
export const localTime = (v) => {
  if (!v) return '';
  const d = new Date(String(v).replace(' ', 'T').replace(/Z?$/, 'Z'));
  if (Number.isNaN(d.getTime())) return String(v).slice(0, 16);
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
};

/**
 * One person's email history with this charity: every email sent from the Email section, campaigns and the
 * Sponsorship Tracker, and every reply, grouped into conversations (same subject), oldest message first.
 */
export default function EmailThread({ company, email, reloadKey = 0, compact = false }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [open, setOpen] = useState(() => new Set());
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!email || !email.includes('@') || !company || company === 'all') { setData(null); return; }
    setError('');
    fetch(`${API_BASE_URL}/api/tracker/direct-email/thread?company_id=${encodeURIComponent(company)}&email=${encodeURIComponent(email)}`)
      .then(async r => { const j = await r.json().catch(() => ({})); if (!r.ok) throw new Error(j.detail || `Error ${r.status}`); return j; })
      .then(setData).catch(e => setError(e.message));
  }, [company, email, reloadKey, tick]);
  // replies are picked up from the mailbox about once a minute; keep an open thread current
  useEffect(() => {
    const t = setInterval(() => setTick(x => x + 1), 60000);
    return () => clearInterval(t);
  }, []);

  const conversations = useMemo(() => {
    const groups = new Map();
    (data?.items || []).forEach(i => {
      // a reply goes under the email it answers (same subject without Re:/Fw:)
      const k = subjectKey(i.subject) || i.conversation || i.id;
      if (!groups.has(k)) groups.set(k, { key: k, subject: i.subject, items: [] });
      groups.get(k).items.push(i);
    });
    return [...groups.values()].sort((a, b) => String(b.items[b.items.length - 1].at).localeCompare(String(a.items[a.items.length - 1].at)));
  }, [data]);

  if (!email || !email.includes('@')) return <div className="text-xs text-slate-500">No email address on record.</div>;
  if (error) return <div className="text-xs text-rose-500">{error}</div>;
  if (!data) return <div className="text-xs text-slate-500">Loading emails…</div>;

  const toggle = (id) => setOpen(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2 text-[11px] text-slate-600 dark:text-slate-300">
        <span>
          <b>{data.summary.sent}</b> sent · <b>{data.summary.opened}</b> opened · <b>{data.summary.replies}</b> {data.summary.replies === 1 ? 'reply' : 'replies'}
          {data.summary.last_contact ? ` · last ${localTime(data.summary.last_contact)}` : ''}
        </span>
        <button type="button" onClick={() => setTick(t => t + 1)} className="flex items-center gap-1 text-sky-600 hover:text-sky-500"><RefreshCw className="w-3 h-3" /> Refresh</button>
      </div>
      {conversations.length === 0 && <div className="text-xs text-slate-500 rounded-lg border border-dashed border-slate-300 dark:border-slate-700 p-4 text-center">No emails with this person yet.</div>}
      {conversations.map(c => (
        <div key={c.key} className="rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden">
          <div className="px-3 py-1.5 text-xs font-bold bg-slate-50 dark:bg-slate-900 text-slate-800 dark:text-slate-100 flex items-center justify-between gap-2">
            <span className="truncate">{c.subject || '(no subject)'}</span>
            <span className="text-[10px] font-normal text-slate-500 shrink-0">{c.items.length} message{c.items.length === 1 ? '' : 's'}</span>
          </div>
          <div className="divide-y divide-slate-100 dark:divide-slate-800">
            {c.items.map(i => {
              const out = i.direction === 'out';
              const isOpen = open.has(i.id);
              return (
                <div key={i.id} className={`px-3 py-2 text-xs ${out ? '' : 'bg-emerald-50/60 dark:bg-emerald-950/20'}`}>
                  <button type="button" onClick={() => toggle(i.id)} className="w-full flex items-center justify-between gap-2 text-left">
                    <span className="flex items-center gap-1.5 min-w-0">
                      {out ? <ArrowUpRight className="w-3.5 h-3.5 text-sky-500 shrink-0" /> : <ArrowDownLeft className="w-3.5 h-3.5 text-emerald-600 shrink-0" />}
                      <span className="font-semibold text-slate-800 dark:text-slate-100 shrink-0">{out ? 'Sent' : 'Reply'}</span>
                      <span className="text-slate-500 truncate">{i.source}{i.template_type && out ? ` · ${String(i.template_type).replace(/_/g, ' ')}` : ''}</span>
                    </span>
                    <span className="flex items-center gap-2 shrink-0 text-slate-500">
                      {out && i.status && i.status !== 'sent' && <span className={`px-1.5 rounded ${i.status === 'failed' ? 'bg-rose-100 text-rose-700' : i.status === 'replied' ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-600'}`}>{i.status}</span>}
                      {out && (i.open_count > 0
                        ? <span className="flex items-center gap-0.5 text-sky-600" title={`First opened ${localTime(i.opened_at)}`}><MailOpen className="w-3 h-3" /> {i.open_count}×</span>
                        : i.status === 'sent' && <span title="Not opened yet"><Eye className="w-3 h-3 opacity-40" /></span>)}
                      {out && i.replied_at && <span title={`Replied ${localTime(i.replied_at)}`}><MessageSquareReply className="w-3 h-3 text-emerald-600" /></span>}
                      <span className="tabular-nums">{localTime(i.at)}</span>
                      <ChevronDown className={`w-3 h-3 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
                    </span>
                  </button>
                  {i.detail && <div className="mt-1 text-[11px] text-amber-700 dark:text-amber-400">{i.detail}</div>}
                  {isOpen && (
                    i.body_html
                      ? <iframe title={`Email ${i.id}`} sandbox="" srcDoc={i.body_html} className="mt-2 w-full rounded border border-slate-200 bg-white" style={{ height: compact ? 260 : 360 }} />
                      : <pre className="mt-2 whitespace-pre-wrap font-sans text-xs text-slate-700 dark:text-slate-200 bg-white dark:bg-slate-950 rounded border border-slate-200 dark:border-slate-700 p-2">{i.body_text || '(no text)'}</pre>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
