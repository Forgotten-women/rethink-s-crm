import React, { useEffect, useState } from 'react';
import { RefreshCw, Send, Ban, Loader2, Inbox, Eye, CheckCircle2, AlertTriangle, X, Mail } from 'lucide-react';
import { API_BASE_URL } from '../../config';
import TrackerFilterBar from './TrackerFilterBar';
import { readFiltersFromUrl, writeFiltersToUrl, filtersToParams, donorKeyFor } from './trackerUtils';
import { denyUnless } from '../../access';

const TEMPLATE_LABELS = {
  profile_intro: 'Profile introduction',
  renewal_notice: 'Renewal notice',
  end_year_feedback: 'End-of-year feedback',
  general_custom: 'Thank-you for new donation',
  video_update: 'Video update',
  campaign_update: 'Campaign update'
};

/**
 * Review queue of system-triggered sponsorship emails. Nothing is sent until staff tick items and
 * press Send; each item is rendered for its own donor and sent from the charity's own mailbox.
 */
export default function EmailQueueView({ companyId, sponsorshipTypes = [], onOpenDonor }) {
  const [filters, setFilters] = useState(() => ({ status: 'pending', ...readFiltersFromUrl('queue') }));
  const [data, setData] = useState({ items: [], total: 0, summary: {} });
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState([]);
  const [busy, setBusy] = useState('');
  const [message, setMessage] = useState(null);
  const [preview, setPreview] = useState(null);
  const [confirmSendItems, setConfirmSendItems] = useState(null);
  const pageSize = 50;

  const load = () => {
    setLoading(true);
    const params = filtersToParams(filters);
    params.set('company_id', companyId);
    params.set('page', page);
    params.set('page_size', pageSize);
    params.set('status', filters.status || 'all');
    fetch(`${API_BASE_URL}/api/tracker/email-queue?${params}`)
      .then(async r => { const j = await r.json().catch(() => ({})); if (!r.ok) throw new Error(j.detail || `Queue unavailable (HTTP ${r.status})`); return j; })
      .then(res => { setData({ items: res.items || [], total: res.total || 0, summary: res.summary || {} }); setSelected([]); })
      .catch(e => setMessage({ type: 'error', text: e.message }))
      .finally(() => setLoading(false));
  };
  useEffect(() => { writeFiltersToUrl('queue', filters); load(); }, [filters, page, companyId]); // eslint-disable-line react-hooks/exhaustive-deps

  const post = async (url, body) => {
    const res = await fetch(`${API_BASE_URL}${url}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined
    });
    const j = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(j.detail || 'Request failed');
    return j;
  };

  const refreshQueue = async () => {
    setBusy('generate'); setMessage(null);
    try {
      const res = await post(`/api/tracker/email-queue/generate?company_id=${companyId}`);
      const created = Object.values(res.created || {}).reduce((a, b) => a + b, 0);
      setMessage({ type: 'ok', text: created ? `${created} new email(s) added to the queue.` : 'Queue is up to date — nothing new to add.' });
      load();
    } catch (e) { setMessage({ type: 'error', text: e.message }); } finally { setBusy(''); }
  };

  const openSendConfirm = (items) => {
    if (!items || !items.length) return;
    setConfirmSendItems(items);
  };

  const executeSend = async () => {
    if (!confirmSendItems || !confirmSendItems.length) return;
    const sendIds = confirmSendItems.map(i => i.id);
    setBusy('send'); setMessage(null);
    try {
if (denyUnless('email.send')) return;
      const res = await post('/api/tracker/email-queue/send', { company_id: companyId, ids: sendIds });
      const failed = (res.results || []).filter(r => r.status !== 'sent');
      const sentList = res.sent_emails || (res.results || []).filter(r => r.status === 'sent').map(r => r.recipient_email || r.recipient_name);
      setMessage({
        type: failed.length ? (sentList.length ? 'warn' : 'error') : 'ok',
        text: res.message || `Processed ${sendIds.length} queued email(s).`,
        sentEmails: sentList,
        details: (res.results || []).filter(r => r.status !== 'sent')
      });
      setConfirmSendItems(null);
      if (preview && sendIds.includes(preview.item?.id)) {
        setPreview(null);
      }
      load();
    } catch (e) {
      setMessage({ type: 'error', text: e.message });
    } finally {
      setBusy('');
    }
  };

  const skipSelected = async () => {
    if (!window.confirm(`Skip ${selected.length} queued email(s)? They will not be sent.`)) return;
    setBusy('skip');
    try {
      const res = await post('/api/tracker/email-queue/skip', { company_id: companyId, ids: selected });
      setMessage({ type: 'ok', text: `${res.skipped} item(s) skipped.` });
      load();
    } catch (e) {
      setMessage({ type: 'error', text: e.message });
    } finally {
      setBusy('');
    }
  };

  const openPreview = async (item) => {
    setPreview({ item, loading: true });
    try {
      const p = await post('/api/tracker/email/preview', {
        allocation_id: item.allocation_id,
        allocation_donor_id: item.allocation_donor_id,
        template_type: item.template_type,
        company_id: companyId
      });
      setPreview({ item, data: p });
    } catch (e) {
      setPreview({ item, error: e.message });
    }
  };

  const pendingOnPage = data.items.filter(i => i.status === 'pending');
  const allSelected = pendingOnPage.length > 0 && pendingOnPage.every(i => selected.includes(i.id));
  const totalPages = Math.max(1, Math.ceil((data.total || 0) / pageSize));

  const selectedPendingItems = data.items.filter(i => selected.includes(i.id) && i.status === 'pending');

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-lg font-bold text-slate-800 dark:text-slate-100 flex items-center gap-2"><Inbox className="w-5 h-5 text-blue-600" /> Email Queue</h2>
          <p className="text-xs text-slate-500">Emails the system suggests for each donor — profile intros, renewal notices, year-end feedback and thank-yous for new sponsorship donations. Nothing is sent until you review and press Send.</p>
        </div>
        <div className="flex items-center gap-2 text-xs">
          {Object.entries(data.summary || {}).map(([k, v]) => (
            <span key={k} className="px-2 py-1 rounded-full bg-slate-100 dark:bg-slate-800 font-semibold text-slate-600 dark:text-slate-300">{k}: {v}</span>
          ))}
          <button type="button" onClick={refreshQueue} disabled={busy === 'generate'}
            className="px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 font-semibold flex items-center gap-1.5 hover:border-blue-400 disabled:opacity-50">
            {busy === 'generate' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />} Check for new triggers
          </button>
        </div>
      </div>

      <TrackerFilterBar values={filters} onChange={v => { setPage(1); setFilters(v); }} resultCount={data.total}
        fields={[
          { key: 'status', label: 'Status', type: 'select', options: [{ value: 'pending', label: 'Pending' }, { value: 'sent', label: 'Sent' }, { value: 'skipped', label: 'Skipped' }, { value: 'failed', label: 'Failed' }, { value: 'all', label: 'All' }] },
          { key: 'template_type', label: 'Email', type: 'select', options: [{ value: 'all', label: 'All emails' }, ...Object.entries(TEMPLATE_LABELS).map(([value, label]) => ({ value, label }))] },
          { key: 'sponsorship_type', label: 'Sponsorship', type: 'select', options: [{ value: 'all', label: 'All types' }, ...sponsorshipTypes.map(t => ({ value: t, label: t }))] },
          { key: 'donor', label: 'Donor', placeholder: 'Name or email' },
          { key: 'beneficiary', label: 'Beneficiary', placeholder: 'Name or code' },
          { key: 'due', label: 'Due date', type: 'daterange' }
        ]} />

      {message && (
        <div className={`p-4 rounded-xl text-xs flex items-start justify-between gap-3 shadow-xs ${
          message.type === 'error'
            ? 'bg-rose-50 text-rose-800 dark:bg-rose-950/40 dark:text-rose-200 border border-rose-200 dark:border-rose-900/50'
            : message.type === 'warn'
            ? 'bg-amber-50 text-amber-800 dark:bg-amber-950/40 dark:text-amber-200 border border-amber-200 dark:border-amber-900/50'
            : 'bg-emerald-50 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-200 border border-emerald-200 dark:border-emerald-900/50'
        }`}>
          <div className="flex flex-col gap-1.5 w-full">
            <div className="font-bold flex items-center gap-1.5 text-xs md:text-sm">
              {message.type === 'ok' ? <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" /> : <AlertTriangle className="w-4 h-4 shrink-0" />}
              <span>{message.text}</span>
            </div>
            {message.sentEmails && message.sentEmails.length > 0 && (
              <div className="text-[11px] text-emerald-900 dark:text-emerald-300 flex items-center gap-1.5 flex-wrap mt-0.5">
                <span className="font-bold">Sent to:</span>
                {message.sentEmails.map((email, idx) => (
                  <span key={idx} className="font-mono bg-white dark:bg-slate-800 px-2 py-0.5 rounded-md border border-emerald-300 dark:border-emerald-700 font-semibold shadow-2xs">
                    {email}
                  </span>
                ))}
              </div>
            )}
            {(message.details || []).map(d => (
              <div key={d.queue_id} className="text-[11px] font-mono text-slate-700 dark:text-slate-300">
                #{d.queue_id}: {d.recipient_email || 'Donor'} &mdash; <span className="font-semibold">{d.status}</span>: {d.detail}
              </div>
            ))}
          </div>
          <button type="button" onClick={() => setMessage(null)} className="p-1 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 shrink-0">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      <div className="rounded-xl border border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden shadow-2xs">
        <div className="px-4 py-2.5 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between gap-2 text-xs">
          <label className="flex items-center gap-2 font-semibold text-slate-600 dark:text-slate-300">
            <input type="checkbox" checked={allSelected} disabled={!pendingOnPage.length}
              onChange={() => setSelected(allSelected ? [] : pendingOnPage.map(i => i.id))} />
            {selected.length ? `${selected.length} selected` : 'Select all pending on this page'}
          </label>
          <div className="flex items-center gap-2">
            <button type="button" disabled={!selected.length || !!busy} onClick={skipSelected}
              className="px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 font-semibold flex items-center gap-1.5 disabled:opacity-40 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors">
              <Ban className="w-3.5 h-3.5" /> Skip
            </button>
            <button type="button" disabled={!selectedPendingItems.length || !!busy} onClick={() => openSendConfirm(selectedPendingItems)}
              className="px-3.5 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-bold flex items-center gap-1.5 disabled:opacity-40 shadow-xs transition-colors">
              {busy === 'send' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
              Send selected {selectedPendingItems.length > 0 ? `(${selectedPendingItems.length})` : ''}
            </button>
          </div>
        </div>
        {loading ? (
          <div className="py-12 flex justify-center text-slate-400"><Loader2 className="w-5 h-5 animate-spin" /></div>
        ) : data.items.length === 0 ? (
          <div className="py-12 text-center text-slate-400 text-xs">No queued emails match these filters.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-slate-50 dark:bg-slate-800/60 text-slate-500 text-left">
                <tr>{['', 'Donor & Recipient Email', 'Beneficiary', 'Email', 'Reason', 'Due', 'Status', 'Actions'].map((h, i) => <th key={i} className="px-3 py-2 font-semibold">{h}</th>)}</tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {data.items.map(item => (
                  <tr key={item.id} className="text-slate-700 dark:text-slate-200 hover:bg-slate-50/50 dark:hover:bg-slate-800/40 transition-colors">
                    <td className="px-3 py-2">
                      <input type="checkbox" disabled={item.status !== 'pending'} checked={selected.includes(item.id)}
                        onChange={() => setSelected(s => (s.includes(item.id) ? s.filter(x => x !== item.id) : [...s, item.id]))} />
                    </td>
                    <td className="px-3 py-2">
                      <button type="button" onClick={() => { if (onOpenDonor) onOpenDonor(donorKeyFor({ ...item, id: item.allocation_donor_id })); }} className="font-semibold hover:text-blue-600 hover:underline text-left">
                        {item.donor_name || item.donor_email}
                      </button>
                      <div className="font-mono text-[11px] text-blue-600 dark:text-blue-400 font-medium flex items-center gap-1 mt-0.5">
                        <Mail className="w-3 h-3 text-slate-400" />
                        <span>{item.donor_email || '(No email)'}</span>
                      </div>
                    </td>
                    <td className="px-3 py-2">{item.beneficiary_name}<div className="text-[10px] text-slate-500">{item.sponsorship_type}{item.project_code ? ` · ${item.project_code}` : ''}</div></td>
                    <td className="px-3 py-2 whitespace-nowrap">{TEMPLATE_LABELS[item.template_type] || item.template_type}</td>
                    <td className="px-3 py-2">{item.reason}</td>
                    <td className="px-3 py-2 whitespace-nowrap">{item.due_date}</td>
                    <td className="px-3 py-2">
                      <span className={`px-2 py-0.5 rounded-full font-bold text-[10px] ${item.status === 'pending' ? 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300' : item.status === 'sent' ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300' : item.status === 'failed' ? 'bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300' : 'bg-slate-100 text-slate-600 dark:bg-slate-800'}`}
                        title={item.error_message || ''}>{item.status}</span>
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-1">
                        <button type="button" onClick={() => openPreview(item)} className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 hover:text-blue-600 transition-colors" title="Preview email">
                          <Eye className="w-3.5 h-3.5" />
                        </button>
                        {item.status === 'pending' && (
                          <button
                            type="button"
                            onClick={() => openSendConfirm([item])}
                            className="p-1.5 rounded-lg hover:bg-blue-50 dark:hover:bg-blue-950/60 text-blue-600 hover:text-blue-700 transition-colors"
                            title={`Send email directly to ${item.donor_email}`}
                          >
                            <Send className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {totalPages > 1 && (
          <div className="px-4 py-2 border-t border-slate-100 dark:border-slate-800 flex items-center justify-end gap-2 text-xs">
            <button type="button" disabled={page <= 1} onClick={() => setPage(p => p - 1)} className="px-2 py-1 rounded border border-slate-200 dark:border-slate-700 disabled:opacity-40">Prev</button>
            <span>Page {page} / {totalPages}</span>
            <button type="button" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)} className="px-2 py-1 rounded border border-slate-200 dark:border-slate-700 disabled:opacity-40">Next</button>
          </div>
        )}
      </div>

      {/* CONFIRM DISPATCH MODAL: Prominently shows every recipient email before sending */}
      {confirmSendItems && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs animate-in fade-in" onClick={() => setConfirmSendItems(null)}>
          <div className="bg-white dark:bg-slate-900 w-full max-w-xl rounded-2xl overflow-hidden shadow-2xl border border-slate-200 dark:border-slate-800 flex flex-col" onClick={e => e.stopPropagation()}>
            <div className="px-5 py-4 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <div className="w-9 h-9 rounded-xl bg-blue-50 dark:bg-blue-950/60 border border-blue-200 dark:border-blue-800 flex items-center justify-center text-blue-600 dark:text-blue-400">
                  <Mail className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="font-bold text-slate-800 dark:text-slate-100 text-sm md:text-base">
                    Confirm Dispatch of {confirmSendItems.length} Email{confirmSendItems.length > 1 ? 's' : ''}
                  </h3>
                  <p className="text-xs text-slate-500">
                    Sending personalized emails from the <strong className="text-slate-700 dark:text-slate-300">{companyId}</strong> mailbox.
                  </p>
                </div>
              </div>
              <button type="button" onClick={() => setConfirmSendItems(null)} className="p-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-800">
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="p-5 flex flex-col gap-3">
              <div className="text-xs font-semibold text-slate-700 dark:text-slate-300">
                The following recipient email{confirmSendItems.length > 1 ? 's are' : ' is'} queued for immediate dispatch:
              </div>

              <div className="max-h-64 overflow-y-auto divide-y divide-slate-100 dark:divide-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl bg-slate-50/60 dark:bg-slate-800/40">
                {confirmSendItems.map((item, idx) => (
                  <div key={item.id || idx} className="p-3 flex items-start justify-between gap-3 text-xs">
                    <div className="flex flex-col gap-0.5">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-bold text-slate-800 dark:text-slate-100">
                          {item.donor_name || 'Donor'}
                        </span>
                        <span className="font-mono text-blue-600 dark:text-blue-400 font-bold bg-white dark:bg-slate-800 px-2 py-0.5 rounded border border-blue-200 dark:border-blue-800 text-[11px] shadow-2xs">
                          {item.donor_email || '(No email)'}
                        </span>
                      </div>
                      <div className="text-[11px] text-slate-500">
                        Beneficiary: <strong className="text-slate-700 dark:text-slate-300">{item.beneficiary_name}</strong> · {TEMPLATE_LABELS[item.template_type] || item.template_type}
                      </div>
                    </div>
                    <span className="text-[10px] font-bold text-slate-500 dark:text-slate-400 bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded shrink-0">
                      {item.reason}
                    </span>
                  </div>
                ))}
              </div>

              <div className="p-3 rounded-xl bg-blue-50/60 dark:bg-blue-950/30 border border-blue-100 dark:border-blue-900/50 text-[11px] text-blue-800 dark:text-blue-300 leading-relaxed">
                Each donor receives their own individual personalized copy directly to the email address shown above. Unsubscribe footers and tracking pixels will be attached automatically.
              </div>
            </div>

            <div className="px-5 py-3 border-t border-slate-100 dark:border-slate-800 flex items-center justify-end gap-2.5 bg-slate-50/50 dark:bg-slate-900/50">
              <button
                type="button"
                onClick={() => setConfirmSendItems(null)}
                className="px-3.5 py-2 rounded-xl border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-300 font-semibold text-xs hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={busy === 'send'}
                onClick={executeSend}
                className="px-5 py-2 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700 disabled:opacity-50 text-white font-bold text-xs flex items-center gap-1.5 shadow-sm transition-all"
              >
                {busy === 'send' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
                {busy === 'send' ? 'Sending Emails...' : `Send Now to ${confirmSendItems.length} Recipient${confirmSendItems.length > 1 ? 's' : ''}`}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* PREVIEW MODAL */}
      {preview && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs animate-in fade-in" onClick={() => setPreview(null)}>
          <div className="bg-white dark:bg-slate-900 w-full max-w-3xl max-h-[90vh] rounded-2xl overflow-hidden flex flex-col shadow-2xl border border-slate-200 dark:border-slate-800" onClick={e => e.stopPropagation()}>
            <div className="px-5 py-3.5 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between text-xs">
              <div className="flex flex-col gap-0.5">
                <div className="font-bold text-slate-800 dark:text-slate-100 text-sm md:text-base">
                  {preview.data?.subject || (preview.item?.reason ? `${TEMPLATE_LABELS[preview.item?.template_type] || preview.item?.template_type}: ${preview.item?.reason}` : 'Email Preview')}
                </div>
                <div className="text-slate-500 flex items-center gap-1.5 mt-0.5 flex-wrap">
                  <span className="font-semibold text-slate-700 dark:text-slate-300">To:</span>
                  <span className="font-semibold text-slate-800 dark:text-slate-200">
                    {preview.data?.recipient_name || preview.item?.donor_name || 'Donor'}
                  </span>
                  <span className="font-mono text-blue-600 dark:text-blue-400 font-bold bg-blue-50 dark:bg-blue-950/60 px-2 py-0.5 rounded border border-blue-200 dark:border-blue-800 text-xs">
                    &lt;{preview.data?.recipient_email || preview.item?.donor_email || 'No email address'}&gt;
                  </span>
                  {preview.item?.beneficiary_name && (
                    <span className="text-slate-400">· Supporting: <strong className="text-slate-700 dark:text-slate-300">{preview.item.beneficiary_name}</strong></span>
                  )}
                </div>
              </div>
              <button type="button" onClick={() => setPreview(null)} className="p-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-800">
                <X className="w-4 h-4" />
              </button>
            </div>
            {preview.loading && <div className="py-16 flex justify-center"><Loader2 className="w-6 h-6 animate-spin text-blue-600" /></div>}
            {preview.error && (
              <div className="m-4 p-3.5 rounded-xl bg-rose-50 border border-rose-200 text-rose-700 text-xs flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 shrink-0" />
                <span>{preview.error}</span>
              </div>
            )}
            {preview.data && <iframe title="Queued email preview" sandbox="" srcDoc={preview.data.body_html} className="w-full h-[65vh] bg-white border-0" />}
            {preview.data && preview.item.status === 'pending' && (
              <div className="px-5 py-3 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between gap-3 bg-slate-50/60 dark:bg-slate-800/40">
                <div className="text-xs text-slate-500 flex items-center gap-1.5 flex-wrap">
                  <span className="font-semibold text-slate-700 dark:text-slate-300">Recipient:</span>
                  <span className="font-mono font-bold text-blue-600 dark:text-blue-400 bg-white dark:bg-slate-800 px-2 py-0.5 rounded border border-blue-200 dark:border-blue-800">
                    {preview.data?.recipient_email || preview.item?.donor_email}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => { setSelected(s => (s.includes(preview.item.id) ? s : [...s, preview.item.id])); setPreview(null); }}
                    className="px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-200 font-semibold text-xs flex items-center gap-1.5 transition-colors"
                  >
                    <CheckCircle2 className="w-3.5 h-3.5" /> Select for batch
                  </button>
                  <button
                    type="button"
                    onClick={() => openSendConfirm([preview.item])}
                    className="px-4 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-bold text-xs flex items-center gap-1.5 shadow-xs transition-colors"
                  >
                    <Send className="w-3.5 h-3.5" /> Send to {preview.data?.recipient_email || preview.item?.donor_email}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
