import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Mail, X, Code, Eye, Send, Loader2, CheckCircle2, AlertTriangle, Users, Save, MinusCircle } from 'lucide-react';
import { API_BASE_URL } from '../../config';
import { themeStorageKey } from './trackerUtils';

const PER_DONOR_VARIABLES = [
  { tag: '{contribution_amount}', label: "This donor's share of the sponsorship (e.g. 160)" },
  { tag: '{co_sponsors}', label: 'First names of the other donors on this sponsorship' }
];

/**
 * Composes one sponsorship email and sends a separately personalised copy to each selected donor.
 * The editor holds the template (with {placeholders}); previews and sends are rendered on the server
 * for each donor, so {First_Name}, {donor_name} and {Email} always belong to the person receiving it.
 */
export default function EmailDispatcherModal({
  allocation, companyId, themes, templates, initialTemplateType = 'profile_intro', initialTheme,
  variables = [], onClose, onSent
}) {
  const allocCompany = allocation.company_id || companyId;
  const themeOptions = themes.filter(t => (allocCompany === 'iqra' ? ['iqra', 'sp'] : ['rethink', 'sp']).includes(t.id));
  const [themeId, setThemeId] = useState(
    themeOptions.some(t => t.id === initialTheme) ? initialTheme : (allocCompany === 'iqra' ? 'iqra' : 'rethink'));
  const themeKey = themeStorageKey(themeId, allocCompany);
  const themeTemplates = useMemo(
    () => templates.filter(t => (t.company_id || t.charity_theme) === themeKey || (t.charity_theme === themeId && t.company_id === themeKey)),
    [templates, themeKey, themeId]);
  const [templateType, setTemplateType] = useState(initialTemplateType);
  const [subjectTpl, setSubjectTpl] = useState('');
  const [bodyTpl, setBodyTpl] = useState('');
  const [edited, setEdited] = useState(false);
  const [tab, setTab] = useState('preview');
  const donors = allocation.donors || [];
  const [selectedIds, setSelectedIds] = useState(() => donors.filter(d => (d.donor_email || '').includes('@')).map(d => d.id));
  const [previewDonorId, setPreviewDonorId] = useState(() => (donors.find(d => d.is_primary) || donors[0] || {}).id);
  const [preview, setPreview] = useState(null);
  const [previewError, setPreviewError] = useState('');
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [sending, setSending] = useState(false);
  const [results, setResults] = useState(null);
  const [savingDefault, setSavingDefault] = useState(false);
  const bodyRef = useRef(null);

  // Load the saved template whenever the theme or template type changes (only this charity's themes).
  useEffect(() => {
    const tpl = themeTemplates.find(t => t.template_type === templateType) || themeTemplates[0];
    if (tpl && tpl.template_type !== templateType) setTemplateType(tpl.template_type);
    setSubjectTpl(tpl?.subject || '');
    setBodyTpl(tpl?.body_html || '');
    setEdited(false);
  }, [themeKey, templateType, themeTemplates]);

  // Server-rendered preview for the selected donor (debounced while editing).
  useEffect(() => {
    if (!previewDonorId || !subjectTpl && !bodyTpl) return undefined;
    const t = setTimeout(() => {
      setLoadingPreview(true);
      fetch(`${API_BASE_URL}/api/tracker/email/preview`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          allocation_id: allocation.id, allocation_donor_id: previewDonorId, template_type: templateType,
          company_id: themeKey, subject_template: subjectTpl, body_template: bodyTpl
        })
      })
        .then(async r => { const j = await r.json(); if (!r.ok) throw new Error(j.detail || 'Preview failed'); return j; })
        .then(p => { setPreview(p); setPreviewError(''); })
        .catch(e => setPreviewError(e.message))
        .finally(() => setLoadingPreview(false));
    }, edited ? 500 : 0);
    return () => clearTimeout(t);
  }, [previewDonorId, subjectTpl, bodyTpl, templateType, themeKey, allocation.id, edited]);

  const insertTag = (tag) => {
    const el = bodyRef.current;
    if (!el) { setBodyTpl(b => b + tag); setEdited(true); return; }
    const start = el.selectionStart ?? bodyTpl.length;
    const end = el.selectionEnd ?? bodyTpl.length;
    setBodyTpl(bodyTpl.slice(0, start) + tag + bodyTpl.slice(end));
    setEdited(true);
    requestAnimationFrame(() => { el.focus(); el.selectionStart = el.selectionEnd = start + tag.length; });
  };

  const toggleDonor = (id) => setSelectedIds(ids => (ids.includes(id) ? ids.filter(x => x !== id) : [...ids, id]));

  const handleSend = () => {
    if (!selectedIds.length) return;
    const names = donors.filter(d => selectedIds.includes(d.id)).map(d => d.donor_name || d.donor_email).join(', ');
    if (!window.confirm(`Send ${selectedIds.length} separate personalised email(s) from the ${allocCompany} mailbox to: ${names}?`)) return;
    setSending(true);
    fetch(`${API_BASE_URL}/api/tracker/outlook/send`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        allocation_id: allocation.id, template_type: templateType, company_id: themeKey,
        allocation_donor_ids: selectedIds,
        subject_template: edited ? subjectTpl : undefined,
        body_template: edited ? bodyTpl : undefined
      })
    })
      .then(async r => { const j = await r.json(); if (!r.ok) throw new Error(j.detail || 'Send failed'); return j; })
      .then(res => { setResults(res); if (onSent) onSent(res); })
      .catch(e => setResults({ status: 'failed', message: e.message, results: [] }))
      .finally(() => setSending(false));
  };

  const handleSaveDefault = () => {
    if (!window.confirm(`Overwrite the saved "${templateType}" template for the ${themeId} theme with these edits?`)) return;
    setSavingDefault(true);
    fetch(`${API_BASE_URL}/api/tracker/email-templates`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ company_id: themeKey, template_type: templateType, subject: subjectTpl, body_html: bodyTpl })
    })
      .then(async r => { const j = await r.json(); if (!r.ok) throw new Error(j.detail || 'Save failed'); setEdited(false); })
      .catch(e => alert(e.message))
      .finally(() => setSavingDefault(false));
  };

  const donorName = (id) => { const d = donors.find(x => x.id === id); return d ? (d.donor_name || d.donor_email) : ''; };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs">
      <div className="bg-white dark:bg-slate-900 w-full max-w-4xl max-h-[92vh] rounded-2xl border border-slate-200 dark:border-slate-800 shadow-2xl flex flex-col overflow-hidden animate-in fade-in zoom-in duration-150">
        <div className="px-6 py-4 flex items-center justify-between border-b border-slate-100 dark:border-slate-800">
          <div className="flex items-center gap-2.5 min-w-0">
            <div className="p-2 rounded-lg bg-blue-50 dark:bg-blue-950/60 text-blue-600 dark:text-blue-400"><Mail className="w-5 h-5" /></div>
            <div className="min-w-0">
              <h3 className="font-bold text-slate-800 dark:text-slate-100 text-base">Email donors · {allocation.beneficiary_name}</h3>
              <span className="text-xs text-slate-400">Each selected donor receives their own copy, sent from the {allocCompany} mailbox.</span>
            </div>
          </div>
          <button type="button" onClick={onClose} className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500"><X className="w-4 h-4" /></button>
        </div>

        <div className="flex-1 overflow-y-auto p-6 grid grid-cols-1 lg:grid-cols-[260px_1fr] gap-5 text-xs">
          {/* Left: recipients + settings */}
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <span className="font-bold text-slate-700 dark:text-slate-200 flex items-center gap-1.5"><Users className="w-3.5 h-3.5" /> Recipients ({selectedIds.length}/{donors.length})</span>
              {donors.map(d => {
                const hasEmail = (d.donor_email || '').includes('@');
                return (
                  <label key={d.id} className={`p-2 rounded-lg border flex items-start gap-2 ${hasEmail ? 'cursor-pointer' : 'opacity-60'} ${selectedIds.includes(d.id) ? 'border-blue-400 bg-blue-50/50 dark:bg-blue-950/30' : 'border-slate-200 dark:border-slate-700'}`}>
                    <input type="checkbox" disabled={!hasEmail} checked={selectedIds.includes(d.id)} onChange={() => toggleDonor(d.id)} className="mt-0.5" />
                    <span className="min-w-0">
                      <span className="font-semibold text-slate-800 dark:text-slate-100 block truncate">{d.donor_name || 'Unnamed'}{d.is_primary ? ' ★' : ''}</span>
                      <span className="font-mono text-[10px] text-slate-500 block truncate">{hasEmail ? d.donor_email : 'No email — cannot be emailed'}</span>
                    </span>
                  </label>
                );
              })}
            </div>

            <div className="flex flex-col gap-1.5">
              <span className="font-bold text-slate-700 dark:text-slate-200">Branding</span>
              <div className="flex gap-1 flex-wrap">
                {themeOptions.map(t => (
                  <button key={t.id} type="button" onClick={() => setThemeId(t.id)}
                    className={`px-2.5 py-1 rounded-md border font-semibold ${themeId === t.id ? 'border-blue-500 bg-blue-50 text-blue-700 dark:bg-blue-950/50 dark:text-blue-300' : 'border-slate-200 dark:border-slate-700 text-slate-500'}`}>
                    {t.short_name || t.name}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex flex-col gap-1.5">
              <span className="font-bold text-slate-700 dark:text-slate-200">Template</span>
              <div className="flex flex-col gap-1">
                {themeTemplates.length === 0 && <span className="text-amber-600">No templates saved for this branding.</span>}
                {themeTemplates.map(t => (
                  <button key={t.template_type} type="button" onClick={() => { if (!edited || window.confirm('Discard your edits?')) setTemplateType(t.template_type); }}
                    className={`text-left px-2.5 py-1.5 rounded-md border ${templateType === t.template_type ? 'border-blue-500 bg-blue-50 text-blue-700 dark:bg-blue-950/50 dark:text-blue-300 font-semibold' : 'border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300'}`}>
                    {t.template_type.replace(/_/g, ' ')}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Right: editor / preview */}
          <div className="flex flex-col gap-3 min-w-0">
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <div className="flex items-center gap-1 bg-slate-100 dark:bg-slate-800 p-0.5 rounded-lg">
                {[['preview', Eye, 'Preview per donor'], ['edit', Code, 'Edit template']].map(([id, Icon, label]) => (
                  <button key={id} type="button" onClick={() => setTab(id)}
                    className={`px-2.5 py-1 rounded-md font-bold flex items-center gap-1 ${tab === id ? 'bg-white dark:bg-slate-900 text-blue-600 shadow-2xs' : 'text-slate-500'}`}>
                    <Icon className="w-3.5 h-3.5" /> {label}
                  </button>
                ))}
              </div>
              {tab === 'preview' && donors.length > 1 && (
                <select value={previewDonorId} onChange={e => setPreviewDonorId(Number(e.target.value))}
                  className="px-2 py-1 rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900">
                  {donors.map(d => <option key={d.id} value={d.id}>As received by {d.donor_name || d.donor_email}</option>)}
                </select>
              )}
            </div>

            {tab === 'edit' ? (
              <>
                <input value={subjectTpl} onChange={e => { setSubjectTpl(e.target.value); setEdited(true); }} placeholder="Subject (placeholders allowed)"
                  className="px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 font-semibold" />
                <div className="flex flex-wrap gap-1">
                  {[...variables, ...PER_DONOR_VARIABLES].map(v => (
                    <button key={v.tag} type="button" title={v.label} onClick={() => insertTag(v.tag)}
                      className="px-1.5 py-0.5 rounded border border-slate-200 dark:border-slate-700 font-mono text-[10px] text-slate-600 dark:text-slate-300 hover:border-blue-400">
                      {v.tag}
                    </button>
                  ))}
                </div>
                <textarea ref={bodyRef} value={bodyTpl} onChange={e => { setBodyTpl(e.target.value); setEdited(true); }} rows={16}
                  className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 font-mono text-[11px] leading-relaxed" />
                <span className="text-slate-500">Placeholders are filled in separately for each donor when sending. Edits apply to this send only unless you save them as the default.</span>
              </>
            ) : (
              <div className="flex flex-col gap-2">
                {previewError && <div className="p-2 rounded-lg bg-rose-50 dark:bg-rose-950/40 text-rose-700 dark:text-rose-300">{previewError}</div>}
                {preview && (
                  <>
                    <div className="px-3 py-2 rounded-lg bg-slate-50 dark:bg-slate-800 flex flex-col gap-0.5">
                      <span><span className="text-slate-500">To:</span> <strong>{preview.recipient_name}</strong> <span className="font-mono">&lt;{preview.recipient_email || 'no email'}&gt;</span></span>
                      <span><span className="text-slate-500">Subject:</span> <strong>{preview.subject}</strong></span>
                    </div>
                    {preview.unresolved_placeholders?.length > 0 && (
                      <div className="p-2 rounded-lg bg-amber-50 dark:bg-amber-950/40 text-amber-800 dark:text-amber-300 flex items-center gap-1.5">
                        <AlertTriangle className="w-3.5 h-3.5" /> Unknown placeholders (sending is blocked): {preview.unresolved_placeholders.map(p => `{${p}}`).join(', ')}
                      </div>
                    )}
                  </>
                )}
                <div className="relative rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden bg-white">
                  {loadingPreview && <div className="absolute inset-0 bg-white/60 flex items-center justify-center"><Loader2 className="w-5 h-5 animate-spin text-slate-400" /></div>}
                  <iframe title="Email preview" sandbox="" srcDoc={preview?.body_html || ''} className="w-full h-[420px]" />
                </div>
              </div>
            )}

            {results && (
              <div className={`p-3 rounded-xl border flex flex-col gap-1 ${results.status === 'success' ? 'border-emerald-300 bg-emerald-50 dark:bg-emerald-950/30' : 'border-amber-300 bg-amber-50 dark:bg-amber-950/30'}`}>
                <span className="font-bold">{results.message}</span>
                {(results.results || []).map(r => (
                  <span key={r.allocation_donor_id} className="flex items-center gap-1.5">
                    {r.status === 'sent' ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" /> : r.status === 'skipped' ? <MinusCircle className="w-3.5 h-3.5 text-slate-400" /> : <AlertTriangle className="w-3.5 h-3.5 text-rose-600" />}
                    {donorName(r.allocation_donor_id)}: {r.status}{r.detail ? ` — ${r.detail}` : ''}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="px-6 py-3 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between gap-2">
          <button type="button" disabled={!edited || savingDefault} onClick={handleSaveDefault}
            className="px-3 py-2 rounded-lg text-xs font-semibold text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-40 flex items-center gap-1.5">
            <Save className="w-3.5 h-3.5" /> Save edits as template default
          </button>
          <div className="flex items-center gap-2">
            <button type="button" onClick={onClose} className="px-4 py-2 rounded-lg text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 font-semibold text-xs">
              {results ? 'Close' : 'Cancel'}
            </button>
            <button type="button" disabled={sending || !selectedIds.length || (preview?.unresolved_placeholders?.length > 0)} onClick={handleSend}
              className="px-5 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-bold text-xs flex items-center gap-2">
              {sending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
              Send {selectedIds.length} personalised email{selectedIds.length === 1 ? '' : 's'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
