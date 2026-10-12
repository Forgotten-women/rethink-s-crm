import React, { useEffect, useMemo, useState } from 'react';
import { X, Send, Search, Loader2, CheckCircle2, AlertTriangle, Eye, Users, PenLine, RotateCcw, Mail } from 'lucide-react';
import { API_BASE_URL } from '../../config';
import { themeStorageKey } from './trackerUtils';

const BATCH = 25;  // matches BULK_SEND_BATCH_LIMIT in backend/api/tracker.py
const LIFECYCLES = [['all', 'All cycles'], ['active', 'Active'], ['due', 'Due (30d)'], ['grace', 'Grace (30d)'], ['lapsed', 'Lapsed']];
const TYPES = ['all', 'Orphan', 'Widow', 'Hafiz', 'Ex-Prisoner'];
const label = (t) => (t || '').replace(/_/g, ' ');

/**
 * Bulk email across ALL sponsorships of one charity: pick donors (filters + search, no paging), choose the
 * branding and template, optionally personalise the text for individual donors, preview exactly what each
 * donor gets, then send. Each donor receives a separately rendered email from the charity's own mailbox and
 * it is recorded in that donor's email history.
 */
export default function BulkEmailModal({ companyId, themes, templates, variables = [], outlookStatus, onClose, onSent }) {
  // ---- recipients ----
  const [recipients, setRecipients] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [search, setSearch] = useState('');
  const [sType, setSType] = useState('all');
  const [lifecycle, setLifecycle] = useState('all');
  const [kind, setKind] = useState('all');
  const [onlyNotSent, setOnlyNotSent] = useState(false);
  const [selected, setSelected] = useState(() => new Set());

  // ---- template ----
  const themeOptions = themes.filter(t => (companyId === 'iqra' ? ['iqra', 'sp'] : ['rethink', 'sp']).includes(t.id));
  const [themeId, setThemeId] = useState(companyId === 'iqra' ? 'iqra' : 'rethink');
  const themeKey = themeStorageKey(themeId, companyId);
  const themeTemplates = useMemo(
    () => templates.filter(t => (t.company_id || t.charity_theme) === themeKey || (t.charity_theme === themeId && t.company_id === themeKey)),
    [templates, themeKey, themeId]);
  const [templateType, setTemplateType] = useState('');
  const [subjectTpl, setSubjectTpl] = useState('');
  const [bodyTpl, setBodyTpl] = useState('');
  const [edited, setEdited] = useState(false);
  const [overrides, setOverrides] = useState({});  // allocation_donor_id -> { subject, body }
  const [personalising, setPersonalising] = useState(null);

  // ---- preview / send ----
  const [step, setStep] = useState(1);
  const [previewId, setPreviewId] = useState(null);
  const [preview, setPreview] = useState(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [checking, setChecking] = useState(null);   // dry-run result
  const [progress, setProgress] = useState(null);   // { done, total, results: [] }

  useEffect(() => {
    setLoading(true); setLoadError('');
    const qs = new URLSearchParams({ company_id: companyId });
    if (sType !== 'all') qs.set('sponsorship_type', sType);
    if (search.trim()) qs.set('search', search.trim());
    const t = setTimeout(() => {
      fetch(`${API_BASE_URL}/api/tracker/bulk-email/recipients?${qs.toString()}`)
        .then(async r => { const j = await r.json(); if (!r.ok) throw new Error(j.detail || 'Could not load donors'); return j; })
        .then(d => setRecipients(d.recipients || []))
        .catch(e => setLoadError(e.message))
        .finally(() => setLoading(false));
    }, search ? 350 : 0);
    return () => clearTimeout(t);
  }, [companyId, sType, search]);

  useEffect(() => {
    const tpl = themeTemplates.find(t => t.template_type === templateType) || themeTemplates[0];
    if (tpl && tpl.template_type !== templateType) { setTemplateType(tpl.template_type); return; }
    setSubjectTpl(tpl?.subject || ''); setBodyTpl(tpl?.body_html || ''); setEdited(false);
  }, [themeKey, templateType, themeTemplates]);

  // Any change to who/what is sent invalidates the last check.
  useEffect(() => { setChecking(null); }, [selected, templateType, themeKey, subjectTpl, bodyTpl]);

  const visible = useMemo(() => recipients.filter(r =>
    (lifecycle === 'all' || r.cycle_status === lifecycle)
    && (kind === 'all' || r.allocation_kind === kind)
    && (!onlyNotSent || r.last_email?.template_type !== templateType)
  ), [recipients, lifecycle, kind, onlyNotSent, templateType]);
  const selectable = visible.filter(r => r.has_email);
  const selectedRows = recipients.filter(r => selected.has(r.allocation_donor_id));
  const allVisibleSelected = selectable.length > 0 && selectable.every(r => selected.has(r.allocation_donor_id));

  const toggle = (id) => setSelected(prev => { const n = new Set(prev); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const toggleAllVisible = () => setSelected(prev => {
    const n = new Set(prev);
    if (allVisibleSelected) selectable.forEach(r => n.delete(r.allocation_donor_id));
    else selectable.forEach(r => n.add(r.allocation_donor_id));
    return n;
  });

  const itemFor = (r) => {
    const o = overrides[r.allocation_donor_id];
    return { allocation_id: r.allocation_id, allocation_donor_id: r.allocation_donor_id,
      ...(o ? { subject_template: o.subject, body_template: o.body } : {}) };
  };
  const basePayload = () => ({
    company_id: companyId, template_type: templateType, theme: themeKey,
    subject_template: edited ? subjectTpl : undefined, body_template: edited ? bodyTpl : undefined
  });

  // Server-rendered preview of one selected donor
  useEffect(() => {
    if (step !== 3 || !previewId) return;
    const r = recipients.find(x => x.allocation_donor_id === previewId);
    if (!r) return;
    setPreviewBusy(true);
    fetch(`${API_BASE_URL}/api/tracker/bulk-email/preview`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...basePayload(), items: [itemFor(r)] })
    })
      .then(async res => { const j = await res.json(); if (!res.ok) throw new Error(j.detail || 'Preview failed'); return j; })
      .then(j => setPreview(j.previews?.[0] || null))
      .catch(e => setPreview({ ready: false, problem: e.message }))
      .finally(() => setPreviewBusy(false));
  }, [step, previewId, overrides, subjectTpl, bodyTpl, templateType, themeKey]);

  const runBatches = async (dryRun) => {
    const items = selectedRows.map(itemFor);
    const results = [];
    setProgress({ done: 0, total: items.length, results, dryRun });
    for (let i = 0; i < items.length; i += BATCH) {
      const res = await fetch(`${API_BASE_URL}/api/tracker/bulk-email/send`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...basePayload(), items: items.slice(i, i + BATCH), dry_run: dryRun })
      });
      const j = await res.json().catch(() => ({}));
      if (!res.ok) {
        items.slice(i, i + BATCH).forEach(it => results.push({ ...it, status: 'failed', detail: j.detail || `HTTP ${res.status}` }));
      } else {
        results.push(...j.results);
      }
      setProgress({ done: Math.min(i + BATCH, items.length), total: items.length, results: [...results], dryRun });
    }
    return results;
  };

  const handleCheck = async () => {
    const results = await runBatches(true);
    setChecking({
      ready: results.filter(r => r.status === 'ready').length,
      problems: results.filter(r => r.status !== 'ready')
    });
    setProgress(null);
  };

  const handleSend = async () => {
    const tplName = label(templateType);
    const mailbox = outlookStatus?.connected_email || `the ${companyId} mailbox`;
    if (!window.confirm(`Send ${checking?.ready ?? selectedRows.length} separate personalised "${tplName}" email(s) from ${mailbox}?`)) return;
    const results = await runBatches(false);
    if (onSent) onSent(results);
  };

  const nameOf = (id) => { const r = recipients.find(x => x.allocation_donor_id === id); return r ? (r.donor_name || r.donor_email) : id; };
  const sendDone = progress && !progress.dryRun && progress.done === progress.total;
  const counts = (progress?.results || []).reduce((a, r) => ({ ...a, [r.status]: (a[r.status] || 0) + 1 }), {});

  return (
    <div className="fixed inset-0 z-[60] bg-slate-900/50 flex items-center justify-center p-3" role="dialog" aria-modal="true" aria-label="Bulk email">
      <div className="bg-white dark:bg-slate-900 rounded-2xl shadow-2xl w-full max-w-6xl h-[92vh] flex flex-col border border-slate-200 dark:border-slate-800 text-xs">
        {/* Header + steps */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-slate-100 dark:border-slate-800 gap-3 flex-wrap">
          <div>
            <h3 className="font-bold text-sm text-slate-900 dark:text-slate-100 flex items-center gap-2"><Mail className="w-4 h-4 text-blue-600" /> Bulk email</h3>
            <p className="text-slate-500">Each donor gets their own personalised copy from {outlookStatus?.connected_email || `the ${companyId} mailbox`}, saved to their email history.</p>
          </div>
          <div className="flex items-center gap-1">
            {[[1, 'Donors'], [2, 'Template'], [3, 'Review & send']].map(([n, t]) => (
              <button key={n} type="button" disabled={n > 1 && selected.size === 0} onClick={() => { setStep(n); if (n === 3 && !previewId && selectedRows[0]) setPreviewId(selectedRows[0].allocation_donor_id); }}
                className={`px-3 py-1.5 rounded-lg font-semibold disabled:opacity-40 ${step === n ? 'bg-blue-600 text-white' : 'text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800'}`}>
                {n}. {t}
              </button>
            ))}
            <button type="button" onClick={onClose} aria-label="Close" className="ml-2 p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800"><X className="w-4 h-4" /></button>
          </div>
        </div>

        {/* STEP 1: recipients */}
        {step === 1 && (
          <div className="flex-1 min-h-0 flex flex-col">
            <div className="px-5 py-3 flex flex-wrap items-end gap-2 border-b border-slate-100 dark:border-slate-800">
              <div className="relative flex-1 min-w-[14rem]">
                <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
                <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search donor, email, beneficiary, project code, campaign"
                  className="w-full pl-8 pr-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 focus:outline-none focus:ring-1 focus:ring-blue-500" />
              </div>
              <select value={sType} onChange={e => setSType(e.target.value)} className="px-2 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800">
                {TYPES.map(t => <option key={t} value={t}>{t === 'all' ? 'All types' : t}</option>)}
              </select>
              <select value={lifecycle} onChange={e => setLifecycle(e.target.value)} className="px-2 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800">
                {LIFECYCLES.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
              </select>
              <select value={kind} onChange={e => setKind(e.target.value)} className="px-2 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800">
                <option value="all">Donors & campaigns</option><option value="individual">Individual donors</option><option value="campaign">Campaigns</option>
              </select>
              <label className="flex items-center gap-1.5 px-2 py-1.5 text-slate-600 dark:text-slate-300">
                <input type="checkbox" checked={onlyNotSent} onChange={e => setOnlyNotSent(e.target.checked)} />
                Last email wasn't "{label(templateType) || 'this template'}"
              </label>
            </div>
            <div className="px-5 py-2 flex items-center justify-between text-slate-500">
              <label className="flex items-center gap-2 font-semibold text-slate-700 dark:text-slate-200">
                <input type="checkbox" checked={allVisibleSelected} onChange={toggleAllVisible} disabled={!selectable.length} />
                Select all {selectable.length} shown (with an email)
              </label>
              <span>{visible.length} shown · {recipients.length} donors in total · <b className="text-blue-600">{selected.size} selected</b></span>
            </div>
            <div className="flex-1 min-h-0 overflow-auto px-5 pb-3">
              {loading && <div className="flex items-center gap-2 text-slate-500 py-6"><Loader2 className="w-4 h-4 animate-spin" /> Loading donors…</div>}
              {loadError && <div className="text-rose-600 py-4">{loadError}</div>}
              {!loading && !loadError && (
                <table className="w-full">
                  <thead className="sticky top-0 bg-white dark:bg-slate-900 text-slate-500 text-left">
                    <tr><th className="py-1.5 w-6" /><th>Donor</th><th>Beneficiary</th><th>Type / cycle</th><th>Last email</th></tr>
                  </thead>
                  <tbody>
                    {visible.map(r => (
                      <tr key={r.allocation_donor_id} className={`border-t border-slate-100 dark:border-slate-800 ${r.has_email ? 'cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/50' : 'opacity-50'}`}
                        onClick={() => r.has_email && toggle(r.allocation_donor_id)}>
                        <td className="py-1.5"><input type="checkbox" checked={selected.has(r.allocation_donor_id)} disabled={!r.has_email} readOnly /></td>
                        <td className="py-1.5 pr-2">
                          <div className="font-semibold text-slate-800 dark:text-slate-100">{r.donor_name || '(no name)'}</div>
                          <div className="font-mono text-[10px] text-slate-500">{r.has_email ? r.donor_email : 'no email address'}</div>
                        </td>
                        <td className="pr-2"><div>{r.beneficiary_name}</div><div className="text-[10px] text-blue-600 font-mono">{r.project_code}</div></td>
                        <td className="pr-2">{r.sponsorship_type} · <span className="capitalize">{r.cycle_status}</span>{r.allocation_kind === 'campaign' ? ' · campaign' : ''}</td>
                        <td className="text-slate-500">{r.last_email ? <>{label(r.last_email.template_type) || 'email'} · {(r.last_email.sent_at || '').slice(0, 10)}</> : 'never'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        )}

        {/* STEP 2: template */}
        {step === 2 && (
          <div className="flex-1 min-h-0 overflow-auto px-5 py-4 grid grid-cols-1 lg:grid-cols-[16rem_1fr] gap-5">
            <div className="flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <span className="font-bold text-slate-700 dark:text-slate-200">Branding</span>
                <div className="flex flex-wrap gap-1">
                  {themeOptions.map(t => (
                    <button key={t.id} type="button" onClick={() => { if (!edited || window.confirm('Discard your edits?')) setThemeId(t.id); }}
                      className={`px-2.5 py-1 rounded-md border font-semibold ${themeId === t.id ? 'border-blue-500 bg-blue-50 text-blue-700 dark:bg-blue-950/50 dark:text-blue-300' : 'border-slate-200 dark:border-slate-700 text-slate-500'}`}>
                      {t.short_name || t.name}
                    </button>
                  ))}
                </div>
              </div>
              <div className="flex flex-col gap-1.5">
                <span className="font-bold text-slate-700 dark:text-slate-200">Template</span>
                {themeTemplates.length === 0 && <span className="text-amber-600">No templates saved for this branding.</span>}
                {themeTemplates.map(t => (
                  <button key={t.template_type} type="button" onClick={() => { if (!edited || window.confirm('Discard your edits?')) setTemplateType(t.template_type); }}
                    className={`text-left px-2.5 py-1.5 rounded-md border ${templateType === t.template_type ? 'border-blue-500 bg-blue-50 text-blue-700 dark:bg-blue-950/50 dark:text-blue-300 font-semibold' : 'border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300'}`}>
                    <div className="capitalize">{label(t.template_type)}</div>
                    <div className="text-[10px] text-slate-500 truncate">{t.subject}</div>
                  </button>
                ))}
              </div>
              <div className="flex flex-col gap-1">
                <span className="font-bold text-slate-700 dark:text-slate-200">Variables (filled per donor)</span>
                {[...variables, { tag: '{contribution_amount}', label: "This donor's share" }, { tag: '{co_sponsors}', label: 'Other donors on the sponsorship' }].map(v => (
                  <button key={v.tag} type="button" title={v.label} onClick={() => { setBodyTpl(b => b + v.tag); setEdited(true); }}
                    className="text-left font-mono text-[10px] text-blue-700 dark:text-blue-300 hover:underline">{v.tag} <span className="font-sans text-slate-400">{v.label}</span></button>
                ))}
              </div>
            </div>
            <div className="flex flex-col gap-2 min-w-0">
              <div className="flex items-center justify-between">
                <span className="font-bold text-slate-700 dark:text-slate-200">Email for all selected donors {edited && <span className="ml-1 text-amber-600">(edited for this send only)</span>}</span>
                {edited && <button type="button" onClick={() => { const tpl = themeTemplates.find(t => t.template_type === templateType); setSubjectTpl(tpl?.subject || ''); setBodyTpl(tpl?.body_html || ''); setEdited(false); }}
                  className="flex items-center gap-1 text-slate-500 hover:text-slate-800"><RotateCcw className="w-3 h-3" /> Reset to saved template</button>}
              </div>
              <input value={subjectTpl} onChange={e => { setSubjectTpl(e.target.value); setEdited(true); }} placeholder="Subject"
                className="px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 font-semibold" />
              <textarea value={bodyTpl} onChange={e => { setBodyTpl(e.target.value); setEdited(true); }} rows={18}
                className="flex-1 px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 font-mono text-[11px]" />
              <p className="text-slate-500">This text is a template: {'{First_Name}'}, {'{beneficiary_name}'} etc. are filled in separately for every donor. Check the result per donor in step 3.</p>
            </div>
          </div>
        )}

        {/* STEP 3: review, personalise, send */}
        {step === 3 && (
          <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-[20rem_1fr] gap-0">
            <div className="border-r border-slate-100 dark:border-slate-800 overflow-auto">
              <div className="px-4 py-2 font-semibold text-slate-700 dark:text-slate-200 flex items-center gap-1.5"><Users className="w-3.5 h-3.5" /> {selectedRows.length} recipients · template: <span className="capitalize text-blue-600">{label(templateType)}</span></div>
              {selectedRows.map(r => (
                <div key={r.allocation_donor_id} onClick={() => setPreviewId(r.allocation_donor_id)}
                  className={`px-4 py-2 border-t border-slate-100 dark:border-slate-800 cursor-pointer flex items-center justify-between gap-2 ${previewId === r.allocation_donor_id ? 'bg-blue-50 dark:bg-blue-950/40' : 'hover:bg-slate-50 dark:hover:bg-slate-800/50'}`}>
                  <div className="min-w-0">
                    <div className="font-semibold truncate text-slate-800 dark:text-slate-100">{r.donor_name || r.donor_email}</div>
                    <div className="text-[10px] text-slate-500 truncate">{r.beneficiary_name} · {r.project_code}</div>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    {overrides[r.allocation_donor_id] && <span className="px-1.5 py-0.5 rounded bg-amber-100 text-amber-800 text-[10px] font-bold">personalised</span>}
                    <button type="button" title="Remove" onClick={e => { e.stopPropagation(); toggle(r.allocation_donor_id); }} className="text-slate-400 hover:text-rose-600"><X className="w-3.5 h-3.5" /></button>
                  </div>
                </div>
              ))}
            </div>
            <div className="flex flex-col min-h-0">
              <div className="px-4 py-2 flex items-center justify-between gap-2 border-b border-slate-100 dark:border-slate-800 flex-wrap">
                <span className="text-slate-600 dark:text-slate-300 flex items-center gap-1.5"><Eye className="w-3.5 h-3.5" /> Exactly what {nameOf(previewId)} will receive</span>
                {previewId && (
                  <div className="flex gap-1.5">
                    {overrides[previewId] && <button type="button" onClick={() => setOverrides(o => { const n = { ...o }; delete n[previewId]; return n; })}
                      className="px-2 py-1 rounded-md border border-slate-200 dark:border-slate-700 flex items-center gap-1"><RotateCcw className="w-3 h-3" /> Use shared text</button>}
                    <button type="button" onClick={() => setPersonalising({ id: previewId, ...(overrides[previewId] || { subject: subjectTpl, body: bodyTpl }) })}
                      className="px-2 py-1 rounded-md border border-blue-300 text-blue-700 dark:text-blue-300 font-semibold flex items-center gap-1"><PenLine className="w-3 h-3" /> Personalise for this donor</button>
                  </div>
                )}
              </div>
              <div className="flex-1 min-h-0 overflow-auto p-4">
                {previewBusy && <div className="flex items-center gap-2 text-slate-500"><Loader2 className="w-4 h-4 animate-spin" /> Rendering…</div>}
                {!previewBusy && preview && (
                  <div className="flex flex-col gap-2">
                    {!preview.ready && <div className="flex items-center gap-2 text-rose-700 bg-rose-50 dark:bg-rose-900/20 rounded-lg px-3 py-2"><AlertTriangle className="w-4 h-4" /> Won't be sent: {preview.problem}</div>}
                    {preview.subject !== undefined && <>
                      <div><span className="text-slate-500">To:</span> {preview.recipient_name} &lt;{preview.recipient_email}&gt;</div>
                      <div><span className="text-slate-500">Subject:</span> <b>{preview.subject}</b></div>
                      <iframe title="Email preview" sandbox="" srcDoc={preview.body_html} className="w-full min-h-[420px] rounded-lg border border-slate-200 dark:border-slate-700 bg-white" />
                    </>}
                  </div>
                )}
              </div>
              <div className="px-4 py-3 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between gap-3 flex-wrap">
                <div className="text-slate-600 dark:text-slate-300">
                  {progress && <span className="flex items-center gap-2">{!sendDone && <Loader2 className="w-3.5 h-3.5 animate-spin" />}{progress.dryRun ? 'Checking' : 'Sending'} {progress.done} / {progress.total}{!progress.dryRun && <> · sent {counts.sent || 0} · skipped {counts.skipped || 0} · failed {counts.failed || 0}</>}</span>}
                  {!progress && checking && <span>{checking.ready} ready to send{checking.problems.length ? `, ${checking.problems.length} will be skipped` : ''}.</span>}
                  {!progress && !checking && <span>Check first: every email is rendered and validated, nothing is sent.</span>}
                </div>
                <div className="flex gap-2">
                  <button type="button" disabled={!!progress || !selectedRows.length} onClick={handleCheck}
                    className="px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 font-semibold disabled:opacity-40">Check all {selectedRows.length}</button>
                  <button type="button" disabled={!!progress || !checking || checking.ready === 0} onClick={handleSend}
                    className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-bold flex items-center gap-1.5 disabled:opacity-40"><Send className="w-3.5 h-3.5" /> Send {checking?.ready ?? ''}</button>
                </div>
              </div>
              {(checking?.problems?.length > 0 || (sendDone && counts.failed)) && (
                <div className="px-4 pb-3 max-h-32 overflow-auto text-[11px]">
                  {(sendDone ? progress.results.filter(r => r.status === 'failed') : checking.problems).map(p => (
                    <div key={p.allocation_donor_id} className="text-rose-600">{nameOf(p.allocation_donor_id)}: {p.detail || p.status}</div>
                  ))}
                </div>
              )}
              {sendDone && <div className="px-4 pb-3 flex items-center gap-2 text-emerald-700"><CheckCircle2 className="w-4 h-4" /> Done. Each email is in the donor's history; replies will appear there too.</div>}
            </div>
          </div>
        )}

        {/* Footer for steps 1-2 */}
        {step < 3 && (
          <div className="px-5 py-3 border-t border-slate-100 dark:border-slate-800 flex justify-between items-center">
            <span className="text-slate-500">{selected.size} donor{selected.size === 1 ? '' : 's'} selected{templateType ? ` · template: ${label(templateType)}` : ''}</span>
            <button type="button" disabled={selected.size === 0 || (step === 2 && !templateType)}
              onClick={() => { const n = step + 1; setStep(n); if (n === 3 && selectedRows[0]) setPreviewId(selectedRows[0].allocation_donor_id); }}
              className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-bold disabled:opacity-40">Next</button>
          </div>
        )}
      </div>

      {/* Personalise one donor */}
      {personalising && (
        <div className="fixed inset-0 z-[70] bg-slate-900/40 flex items-center justify-center p-4">
          <div className="bg-white dark:bg-slate-900 rounded-xl shadow-2xl w-full max-w-3xl p-4 flex flex-col gap-2 text-xs border border-slate-200 dark:border-slate-800">
            <div className="flex items-center justify-between">
              <b className="text-sm">Personalise for {nameOf(personalising.id)}</b>
              <button type="button" onClick={() => setPersonalising(null)} aria-label="Close"><X className="w-4 h-4" /></button>
            </div>
            <p className="text-slate-500">Only this donor gets this version. Variables still work.</p>
            <input value={personalising.subject} onChange={e => setPersonalising(p => ({ ...p, subject: e.target.value }))}
              className="px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 font-semibold" />
            <textarea rows={16} value={personalising.body} onChange={e => setPersonalising(p => ({ ...p, body: e.target.value }))}
              className="px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 font-mono text-[11px]" />
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setPersonalising(null)} className="px-3 py-2 rounded-lg">Cancel</button>
              <button type="button" onClick={() => { setOverrides(o => ({ ...o, [personalising.id]: { subject: personalising.subject, body: personalising.body } })); setChecking(null); setPersonalising(null); }}
                className="px-4 py-2 rounded-lg bg-blue-600 text-white font-bold">Save for this donor</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
