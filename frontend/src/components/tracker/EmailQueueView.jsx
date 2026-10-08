import React, { useEffect, useState } from 'react';
import { RefreshCw, Send, Ban, Loader2, Inbox, Eye, CheckCircle2, AlertTriangle, X } from 'lucide-react';
import { API_BASE_URL } from '../../config';
import TrackerFilterBar from './TrackerFilterBar';
import { readFiltersFromUrl, writeFiltersToUrl, filtersToParams, donorKeyFor } from './trackerUtils';

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

  const sendSelected = async () => {
    const items = data.items.filter(i => selected.includes(i.id));
    if (!window.confirm(`Send ${items.length} personalised email(s) now? Each donor gets their own copy from the ${companyId} mailbox.`)) return;
    setBusy('send'); setMessage(null);
    try {
      const res = await post('/api/tracker/email-queue/send', { company_id: companyId, ids: selected });
      const failed = (res.results || []).filter(r => r.status !== 'sent');
      setMessage({ type: failed.length ? 'warn' : 'ok', text: res.message, details: failed });
      load();
    } catch (e) { setMessage({ type: 'error', text: e.message }); } finally { setBusy(''); }
  };

  const skipSelected = async () => {
    if (!window.confirm(`Skip ${selected.length} queued email(s)? They will not be sent.`)) return;
    setBusy('skip');
    try { const res = await post('/api/tracker/email-queue/skip', { company_id: companyId, ids: selected }); setMessage({ type: 'ok', text: `${res.skipped} item(s) skipped.` }); load(); }
    catch (e) { setMessage({ type: 'error', text: e.message }); } finally { setBusy(''); }
  };

  const openPreview = async (item) => {
    setPreview({ item, loading: true });
    try {
      const p = await post('/api/tracker/email/preview', {
        allocation_id: item.allocation_id, allocation_donor_id: item.allocation_donor_id, template_type: item.template_type
      });
      setPreview({ item, data: p });
    } catch (e) { setPreview({ item, error: e.message }); }
  };

  const pendingOnPage = data.items.filter(i => i.status === 'pending');
  const allSelected = pendingOnPage.length > 0 && pendingOnPage.every(i => selected.includes(i.id));
  const totalPages = Math.max(1, Math.ceil((data.total || 0) / pageSize));

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
        <div className={`p-3 rounded-xl text-xs flex items-start justify-between gap-2 ${message.type === 'error' ? 'bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300' : message.type === 'warn' ? 'bg-amber-50 text-amber-800 dark:bg-amber-950/40 dark:text-amber-300' : 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300'}`}>
          <div>
            <div className="font-bold">{message.text}</div>
            {(message.details || []).map(d => <div key={d.queue_id}>#{d.queue_id}: {d.status} — {d.detail}</div>)}
          </div>
          <button type="button" onClick={() => setMessage(null)}><X className="w-3.5 h-3.5" /></button>
        </div>
      )}

      <div className="rounded-xl border border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden">
        <div className="px-4 py-2.5 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between gap-2 text-xs">
          <label className="flex items-center gap-2 font-semibold text-slate-600 dark:text-slate-300">
            <input type="checkbox" checked={allSelected} disabled={!pendingOnPage.length}
              onChange={() => setSelected(allSelected ? [] : pendingOnPage.map(i => i.id))} />
            {selected.length ? `${selected.length} selected` : 'Select all pending on this page'}
          </label>
          <div className="flex items-center gap-2">
            <button type="button" disabled={!selected.length || !!busy} onClick={skipSelected}
              className="px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 font-semibold flex items-center gap-1.5 disabled:opacity-40">
              <Ban className="w-3.5 h-3.5" /> Skip
            </button>
            <button type="button" disabled={!selected.length || !!busy} onClick={sendSelected}
              className="px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-bold flex items-center gap-1.5 disabled:opacity-40">
              {busy === 'send' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />} Send selected
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
                <tr>{['', 'Donor', 'Beneficiary', 'Email', 'Reason', 'Due', 'Status', ''].map((h, i) => <th key={i} className="px-3 py-2 font-semibold">{h}</th>)}</tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {data.items.map(item => (
                  <tr key={item.id} className="text-slate-700 dark:text-slate-200">
                    <td className="px-3 py-2">
                      <input type="checkbox" disabled={item.status !== 'pending'} checked={selected.includes(item.id)}
                        onChange={() => setSelected(s => (s.includes(item.id) ? s.filter(x => x !== item.id) : [...s, item.id]))} />
                    </td>
                    <td className="px-3 py-2">
                      <button type="button" onClick={() => { if (onOpenDonor) onOpenDonor(donorKeyFor({ ...item, id: item.allocation_donor_id })); }} className="font-semibold hover:text-blue-600 hover:underline text-left">
                        {item.donor_name || item.donor_email}
                      </button>
                      <div className="font-mono text-[10px] text-slate-500">{item.donor_email}</div>
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
                      <button type="button" onClick={() => openPreview(item)} className="p-1.5 rounded-md hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500" title="Preview"><Eye className="w-3.5 h-3.5" /></button>
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

      {preview && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60" onClick={() => setPreview(null)}>
          <div className="bg-white dark:bg-slate-900 w-full max-w-3xl max-h-[90vh] rounded-2xl overflow-hidden flex flex-col" onClick={e => e.stopPropagation()}>
            <div className="px-5 py-3 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between text-xs">
              <div>
                <div className="font-bold text-slate-800 dark:text-slate-100 text-sm">{preview.data?.subject || 'Preview'}</div>
                <div className="text-slate-500">To {preview.data?.recipient_name} &lt;{preview.data?.recipient_email}&gt;</div>
              </div>
              <button type="button" onClick={() => setPreview(null)}><X className="w-4 h-4" /></button>
            </div>
            {preview.loading && <div className="py-16 flex justify-center"><Loader2 className="w-5 h-5 animate-spin text-slate-400" /></div>}
            {preview.error && <div className="m-4 p-3 rounded-lg bg-rose-50 text-rose-700 text-xs flex items-center gap-1.5"><AlertTriangle className="w-3.5 h-3.5" />{preview.error}</div>}
            {preview.data && <iframe title="Queued email preview" sandbox="" srcDoc={preview.data.body_html} className="w-full h-[65vh] bg-white" />}
            {preview.data && preview.item.status === 'pending' && (
              <div className="px-5 py-3 border-t border-slate-100 dark:border-slate-800 flex justify-end">
                <button type="button" onClick={() => { setSelected(s => (s.includes(preview.item.id) ? s : [...s, preview.item.id])); setPreview(null); }}
                  className="px-3 py-1.5 rounded-lg bg-blue-600 text-white font-bold text-xs flex items-center gap-1.5"><CheckCircle2 className="w-3.5 h-3.5" /> Select for sending</button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
