import React, { useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { X, Mail, Users, Search, Send, ListChecks, Eye, Plus, ChevronLeft, ChevronRight, Clock } from 'lucide-react';
import { API_BASE_URL } from '../config';
import SegmentBuilder, { cleanSegment, segmentChips } from './SegmentBuilder';

const inputStyle = { backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' };
const gbp = (v) => (v == null ? '—' : `£${Number(v).toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);
const VARIABLES = ['first_name', 'donor_name', 'total_given', 'gifts_count', 'average_gift', 'lifetime_tier', 'first_gift_date',
  'last_gift_date', 'last_gift_amount', 'last_gift_cause', 'top_cause', 'sponsorship_types', 'message_body',
  'beneficiary_name', 'sponsorship_type', 'location', 'profile_link', 'video_link', 'renewal_deadline'];
const BATCH = 25;

async function post(path, body) {
  const res = await fetch(`${API_BASE_URL}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Error ${res.status}`);
  return data;
}

/**
 * Email anyone: pick people by filters (segment), by hand, or by typing addresses; choose a template of this charity;
 * preview per person; then send now (in batches) or queue the selection as a named campaign.
 */
export default function EmailComposer({ company, initialSegment = {}, initialDonorIds = [], startAsCampaign = false, onClose, onDone }) {
  const [step, setStep] = useState(1);
  const [segment, setSegment] = useState(initialSegment);
  const [excludeDays, setExcludeDays] = useState('');
  const [extraText, setExtraText] = useState('');
  const [picked, setPicked] = useState([]); // hand-picked {donor_id,email,name}
  const [pickQuery, setPickQuery] = useState('');
  const [pickResults, setPickResults] = useState([]);
  const [recipients, setRecipients] = useState(null);
  const [selected, setSelected] = useState(new Set());
  const [listFilter, setListFilter] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [themes, setThemes] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [theme, setTheme] = useState('');
  const [templateType, setTemplateType] = useState('general_custom');
  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  const [edited, setEdited] = useState(false);
  const [messageBody, setMessageBody] = useState('');
  const [previewEmail, setPreviewEmail] = useState('');
  const [preview, setPreview] = useState(null);
  const [results, setResults] = useState(null);
  const [progress, setProgress] = useState(null);
  const [campaignName, setCampaignName] = useState('');
  const [asCampaign, setAsCampaign] = useState(startAsCampaign);

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') { e.stopPropagation(); onClose(); } };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [onClose]);

  useEffect(() => {
    if (initialDonorIds.length) {
      post('/api/tracker/direct-email/recipients', { company_id: company, donor_ids: initialDonorIds })
        .then(d => { setPicked(d.recipients); }).catch(() => {});
    }
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    fetch(`${API_BASE_URL}/api/tracker/email-templates?company_id=${encodeURIComponent(company)}`)
      .then(r => (r.ok ? r.json() : {})).then(d => {
        setThemes(d.available_themes || []);
        setTemplates(d.templates || []);
        setTheme(t => t || d.selected_theme || (d.available_themes?.[0]?.id ?? ''));
      }).catch(() => {});
  }, [company]);

  const themeTemplates = useMemo(() => templates.filter(t => (t.charity_theme || t.company_id) === theme), [templates, theme]);
  useEffect(() => {
    if (edited) return;
    const t = themeTemplates.find(x => x.template_type === templateType);
    setSubject(t?.subject || ''); setBody(t?.body_html || '');
  }, [themeTemplates, templateType, edited]);

  // hand-pick search
  useEffect(() => {
    const q = pickQuery.trim();
    if (q.length < 2) { setPickResults([]); return; }
    const t = setTimeout(() => {
      fetch(`${API_BASE_URL}/api/donors/directory?company_id=${encodeURIComponent(company)}&search=${encodeURIComponent(q)}&page_size=8`)
        .then(r => (r.ok ? r.json() : { donors: [] })).then(d => setPickResults(d.donors || [])).catch(() => {});
    }, 300);
    return () => clearTimeout(t);
  }, [pickQuery, company]);

  const extra = useMemo(() => extraText.split(/[\s,;]+/).map(s => s.trim()).filter(s => s.includes('@')).map(email => ({ email, name: '' })), [extraText]);
  const segActive = Object.keys(cleanSegment(segment)).length > 0;

  const findRecipients = async () => {
    setError(''); setLoading(true);
    try {
      const d = await post('/api/tracker/direct-email/recipients', {
        company_id: company, segment: segActive ? cleanSegment(segment) : null,
        donor_ids: picked.map(p => p.donor_id || p.email), extra,
        exclude_emailed_days: excludeDays ? Number(excludeDays) : null,
      });
      setRecipients(d);
      setSelected(new Set(d.recipients.map(r => r.email)));
      setPreviewEmail(d.recipients[0]?.email || '');
    } catch (e) { setError(e.message); } finally { setLoading(false); }
  };

  const chosen = useMemo(() => (recipients?.recipients || []).filter(r => selected.has(r.email)), [recipients, selected]);
  const shownList = useMemo(() => {
    const q = listFilter.trim().toLowerCase();
    return (recipients?.recipients || []).filter(r => !q || `${r.name} ${r.email}`.toLowerCase().includes(q));
  }, [recipients, listFilter]);

  const payloadText = () => ({
    company_id: company, theme, template_type: templateType, message_body: messageBody || null,
    subject_template: edited ? subject : null, body_template: edited ? body : null,
  });

  const loadPreview = async (email) => {
    const r = chosen.find(x => x.email === email) || chosen[0];
    if (!r) return;
    setPreviewEmail(r.email);
    try { setPreview(await post('/api/tracker/direct-email/preview', { ...payloadText(), recipient: r })); } catch (e) { setPreview({ error: e.message }); }
  };
  useEffect(() => { if (step === 3 && chosen.length) loadPreview(previewEmail || chosen[0].email); }, [step]); // eslint-disable-line react-hooks/exhaustive-deps

  const runBatches = async (dryRun) => {
    setError(''); setResults(null);
    const all = [];
    for (let i = 0; i < chosen.length; i += BATCH) {
      setProgress({ done: i, total: chosen.length, dryRun });
      try {
        const d = await post('/api/tracker/direct-email/send', { ...payloadText(), recipients: chosen.slice(i, i + BATCH), dry_run: dryRun });
        all.push(...d.results);
      } catch (e) { setError(e.message); break; }
    }
    setProgress(null);
    setResults({ dryRun, rows: all });
    if (!dryRun) onDone?.();
  };

  const queueCampaign = async () => {
    setError('');
    if (!campaignName.trim()) { setError('Give the campaign a name.'); return; }
    setLoading(true);
    try {
      const d = await post('/api/tracker/direct-email/campaigns', {
        ...payloadText(), name: campaignName.trim(),
        donor_ids: chosen.map(r => r.donor_id || r.email).filter(Boolean),
        extra: chosen.filter(r => !r.donor_id).map(r => ({ email: r.email, name: r.name })),
        segment: null, exclude_other_pending: false,
      });
      setResults({ campaign: d });
      onDone?.();
    } catch (e) { setError(e.message); } finally { setLoading(false); }
  };

  const summary = results?.rows ? results.rows.reduce((a, r) => ({ ...a, [r.status]: (a[r.status] || 0) + 1 }), {}) : null;

  return createPortal(
    <div className="fixed inset-0 z-[80] flex items-center justify-center p-2 sm:p-5" role="dialog" aria-modal="true" aria-label="Email donors">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-6xl h-[94vh] flex flex-col rounded-2xl shadow-2xl overflow-hidden border" style={{ backgroundColor: 'var(--bg-card, var(--bg-main))', borderColor: 'var(--border-glass)' }}>
        <div className="px-6 py-4 border-b flex items-center justify-between gap-3 bg-gradient-to-br from-sky-500/10 to-transparent" style={{ borderColor: 'var(--border-glass)' }}>
          <div>
            <h2 className="text-base font-black flex items-center gap-2" style={{ color: 'var(--text-main)' }}><Mail className="w-5 h-5 text-sky-500" /> Email donors</h2>
            <div className="flex items-center gap-2 text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
              {['Who', 'Message', 'Review & send'].map((s, i) => (
                <span key={s} className={`px-2 py-0.5 rounded-full ${step === i + 1 ? 'bg-sky-600 text-white font-bold' : ''}`}>{i + 1}. {s}</span>
              ))}
            </div>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="w-8 h-8 rounded-full flex items-center justify-center" style={{ color: 'var(--text-sub)' }}><X className="w-4 h-4" /></button>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto px-6 py-5 flex flex-col gap-4 text-sm">
          {step === 1 && (
            <>
              <SegmentBuilder company={company} value={segment} onChange={setSegment} defaultOpen />
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
                <div className="glass-panel p-3 flex flex-col gap-2">
                  <div className="text-xs font-bold" style={{ color: 'var(--text-main)' }}>Add people by name</div>
                  <span className="relative">
                    <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
                    <input value={pickQuery} onChange={e => setPickQuery(e.target.value)} placeholder="Search name, email or phone" className="w-full pl-8 pr-2 py-1.5 text-xs rounded-lg" style={inputStyle} />
                  </span>
                  {pickResults.map(d => (
                    <button key={d.donor_id} type="button" disabled={!d.email} onClick={() => { setPicked(p => (p.some(x => x.email === d.email) ? p : [...p, { donor_id: d.donor_id, email: d.email, name: d.name }])); setPickQuery(''); }}
                      className="text-left text-xs px-2 py-1.5 rounded-lg hover:bg-sky-500/10 disabled:opacity-40 flex justify-between gap-2" style={{ color: 'var(--text-main)' }}>
                      <span className="truncate">{d.name || d.email} <span style={{ color: 'var(--text-muted)' }}>{d.email || '(no email)'}</span></span><Plus className="w-3.5 h-3.5 shrink-0" />
                    </button>
                  ))}
                  <div className="flex flex-wrap gap-1">
                    {picked.map(p => (
                      <span key={p.email} className="text-[11px] px-2 py-0.5 rounded-full bg-sky-500/10 text-sky-700 dark:text-sky-300 flex items-center gap-1">
                        {p.name || p.email}<button type="button" onClick={() => setPicked(x => x.filter(y => y.email !== p.email))}><X className="w-3 h-3" /></button>
                      </span>
                    ))}
                  </div>
                </div>
                <div className="glass-panel p-3 flex flex-col gap-2">
                  <div className="text-xs font-bold" style={{ color: 'var(--text-main)' }}>Or type email addresses</div>
                  <textarea value={extraText} onChange={e => setExtraText(e.target.value)} rows={4} placeholder="one@example.com, two@example.com" className="w-full px-2 py-1.5 text-xs rounded-lg" style={inputStyle} />
                  <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>{extra.length} address{extra.length === 1 ? '' : 'es'}</span>
                </div>
                <div className="glass-panel p-3 flex flex-col gap-2">
                  <div className="text-xs font-bold flex items-center gap-1" style={{ color: 'var(--text-main)' }}><Clock className="w-3.5 h-3.5" /> Don't email people contacted recently</div>
                  <label className="text-xs flex items-center gap-2" style={{ color: 'var(--text-sub)' }}>
                    Skip anyone emailed in the last
                    <input type="number" min="0" value={excludeDays} onChange={e => setExcludeDays(e.target.value)} className="w-16 px-2 py-1 rounded-lg" style={inputStyle} /> days
                  </label>
                  <button type="button" onClick={findRecipients} disabled={loading || (!segActive && !picked.length && !extra.length)}
                    className="mt-auto px-3 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 text-white font-bold text-xs disabled:opacity-40 flex items-center justify-center gap-1.5">
                    <Users className="w-4 h-4" />{loading ? 'Finding…' : 'Find recipients'}
                  </button>
                </div>
              </div>
              {recipients && (
                <div className="glass-panel overflow-hidden">
                  <div className="px-3 py-2 flex items-center justify-between gap-2 flex-wrap border-b" style={{ borderColor: 'var(--border-glass)' }}>
                    <span className="text-xs" style={{ color: 'var(--text-main)' }}>
                      <b>{selected.size}</b> of {recipients.count} selected{recipients.excluded_recently_emailed ? ` · ${recipients.excluded_recently_emailed} skipped (emailed recently)` : ''}
                    </span>
                    <span className="flex items-center gap-2">
                      <input value={listFilter} onChange={e => setListFilter(e.target.value)} placeholder="Filter list" className="px-2 py-1 text-xs rounded-lg" style={inputStyle} />
                      <button type="button" onClick={() => setSelected(new Set(recipients.recipients.map(r => r.email)))} className="text-xs text-sky-600">All</button>
                      <button type="button" onClick={() => setSelected(new Set())} className="text-xs text-sky-600">None</button>
                    </span>
                  </div>
                  <div className="max-h-72 overflow-y-auto">
                    <table className="w-full text-xs">
                      <thead className="sticky top-0" style={{ backgroundColor: 'var(--bg-card, var(--bg-main))', color: 'var(--text-sub)' }}>
                        <tr>{['', 'Name', 'Email', 'Tier', 'Lifetime', 'Matching', 'Last gift', 'Sponsorships'].map(h => <th key={h} className="px-2 py-1.5 text-left font-bold">{h}</th>)}</tr>
                      </thead>
                      <tbody>
                        {shownList.slice(0, 1000).map(r => (
                          <tr key={r.email} className="border-t" style={{ borderColor: 'var(--border-glass)', color: 'var(--text-main)' }}>
                            <td className="px-2 py-1"><input type="checkbox" checked={selected.has(r.email)} onChange={() => setSelected(s => { const n = new Set(s); n.has(r.email) ? n.delete(r.email) : n.add(r.email); return n; })} /></td>
                            <td className="px-2 py-1">{r.name || '—'}</td><td className="px-2 py-1">{r.email}</td><td className="px-2 py-1">{r.tier || '—'}</td>
                            <td className="px-2 py-1 tabular-nums">{gbp(r.total)}</td><td className="px-2 py-1 tabular-nums">{r.matched_total != null ? gbp(r.matched_total) : '—'}</td>
                            <td className="px-2 py-1">{r.last_gift || '—'}</td><td className="px-2 py-1">{r.sponsorship_types || '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </>
          )}

          {step === 2 && (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              <div className="lg:col-span-2 flex flex-col gap-3">
                <div className="flex flex-wrap gap-3">
                  <label className="flex flex-col gap-1 text-xs" style={{ color: 'var(--text-sub)' }}>Theme / sender branding
                    <select value={theme} onChange={e => { setTheme(e.target.value); setEdited(false); }} className="px-2 py-1.5 rounded-lg text-sm" style={inputStyle}>
                      {themes.map(t => <option key={t.id || t} value={t.id || t}>{t.label || t.name || t.id || t}</option>)}
                    </select>
                  </label>
                  <label className="flex flex-col gap-1 text-xs flex-1 min-w-[14rem]" style={{ color: 'var(--text-sub)' }}>Template
                    <select value={templateType} onChange={e => { setTemplateType(e.target.value); setEdited(false); }} className="px-2 py-1.5 rounded-lg text-sm" style={inputStyle}>
                      {themeTemplates.map(t => <option key={t.template_type} value={t.template_type}>{t.template_type.replace(/_/g, ' ')} — {t.subject}</option>)}
                    </select>
                  </label>
                </div>
                <label className="flex flex-col gap-1 text-xs" style={{ color: 'var(--text-sub)' }}>Subject
                  <input value={subject} onChange={e => { setSubject(e.target.value); setEdited(true); }} className="px-2.5 py-2 rounded-lg text-sm" style={inputStyle} />
                </label>
                <label className="flex flex-col gap-1 text-xs" style={{ color: 'var(--text-sub)' }}>Email body (HTML; edits apply to this send only)
                  <textarea value={body} onChange={e => { setBody(e.target.value); setEdited(true); }} rows={14} className="px-2.5 py-2 rounded-lg text-xs font-mono" style={inputStyle} />
                </label>
                <label className="flex flex-col gap-1 text-xs" style={{ color: 'var(--text-sub)' }}>Your message (fills {'{message_body}'})
                  <textarea value={messageBody} onChange={e => setMessageBody(e.target.value)} rows={4} className="px-2.5 py-2 rounded-lg text-sm" style={inputStyle} placeholder="Thank you for your generous support." />
                </label>
              </div>
              <div className="glass-panel p-3 text-xs flex flex-col gap-1.5" style={{ color: 'var(--text-sub)' }}>
                <div className="font-bold" style={{ color: 'var(--text-main)' }}>Personalise with</div>
                <div className="flex flex-wrap gap-1">{VARIABLES.map(v => <code key={v} className="px-1.5 py-0.5 rounded bg-sky-500/10 text-sky-700 dark:text-sky-300">{`{${v}}`}</code>)}</div>
                <p className="mt-2">Sponsorship fields (beneficiary, location, links…) come from the donor's latest sponsorship; anyone without one is skipped for templates that need them, never sent a half-filled email.</p>
              </div>
            </div>
          )}

          {step === 3 && (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              <div className="lg:col-span-2 flex flex-col gap-2">
                <div className="flex items-center gap-2 text-xs" style={{ color: 'var(--text-sub)' }}>
                  <Eye className="w-4 h-4" /> Preview for
                  <select value={previewEmail} onChange={e => loadPreview(e.target.value)} className="px-2 py-1 rounded-lg" style={inputStyle}>
                    {chosen.slice(0, 500).map(r => <option key={r.email} value={r.email}>{r.name || r.email}</option>)}
                  </select>
                </div>
                {preview?.error && <div className="text-rose-500 text-xs">{preview.error}</div>}
                {preview && !preview.error && (
                  <div className="rounded-xl border overflow-hidden" style={{ borderColor: 'var(--border-glass)' }}>
                    <div className="px-3 py-2 text-xs border-b" style={{ borderColor: 'var(--border-glass)', color: 'var(--text-main)' }}>
                      <b>{preview.subject}</b> → {preview.recipient_email}
                      {preview.unresolved_placeholders?.length > 0 && <span className="ml-2 text-amber-600">Will be skipped: needs {preview.unresolved_placeholders.join(', ')}</span>}
                    </div>
                    <iframe title="Email preview" sandbox="" srcDoc={preview.body_html} className="w-full h-[50vh] bg-white" />
                  </div>
                )}
              </div>
              <div className="flex flex-col gap-3">
                <div className="glass-panel p-3 text-xs flex flex-col gap-2" style={{ color: 'var(--text-main)' }}>
                  <div><b>{chosen.length}</b> recipient{chosen.length === 1 ? '' : 's'} · template <b>{templateType.replace(/_/g, ' ')}</b>{edited ? ' (edited)' : ''}</div>
                  {segmentChips(cleanSegment(segment)).length > 0 && <div style={{ color: 'var(--text-muted)' }}>{segmentChips(cleanSegment(segment)).map(c => c.text).join(' · ')}</div>}
                  <label className="flex items-center gap-2"><input type="checkbox" checked={asCampaign} onChange={e => setAsCampaign(e.target.checked)} /> Queue as a campaign instead of sending now</label>
                  {asCampaign ? (
                    <>
                      <input value={campaignName} onChange={e => setCampaignName(e.target.value)} placeholder="Campaign name, e.g. Hafiz donors – Jan update" className="px-2 py-1.5 rounded-lg" style={inputStyle} />
                      <button type="button" onClick={queueCampaign} disabled={loading || !chosen.length} className="px-3 py-2 rounded-lg bg-violet-600 hover:bg-violet-500 text-white font-bold disabled:opacity-40 flex items-center justify-center gap-1.5"><ListChecks className="w-4 h-4" /> Add to email queue</button>
                    </>
                  ) : (
                    <>
                      <button type="button" onClick={() => runBatches(true)} disabled={!!progress || !chosen.length} className="px-3 py-2 rounded-lg border font-bold disabled:opacity-40" style={{ borderColor: 'var(--border-glass)' }}>Check everyone (no sending)</button>
                      <button type="button" onClick={() => { if (window.confirm(`Send this email to ${chosen.length} people now?`)) runBatches(false); }} disabled={!!progress || !chosen.length} className="px-3 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 text-white font-bold disabled:opacity-40 flex items-center justify-center gap-1.5"><Send className="w-4 h-4" /> Send to {chosen.length}</button>
                    </>
                  )}
                  {progress && <div style={{ color: 'var(--text-muted)' }}>{progress.dryRun ? 'Checking' : 'Sending'}… {progress.done}/{progress.total}</div>}
                  {summary && <div><b>{results.dryRun ? 'Check' : 'Done'}:</b> {Object.entries(summary).map(([k, v]) => `${v} ${k === 'ok' ? 'ready' : k}`).join(' · ')}</div>}
                  {results?.campaign && <div className="text-violet-700 dark:text-violet-300">Queued {results.campaign.queued} in the email queue (Email campaigns tab).</div>}
                </div>
                {results?.rows && results.rows.some(r => r.detail) && (
                  <div className="glass-panel p-3 text-[11px] max-h-60 overflow-y-auto" style={{ color: 'var(--text-sub)' }}>
                    {results.rows.filter(r => r.detail).slice(0, 200).map(r => <div key={r.recipient_email}>{r.recipient_email}: {r.detail}</div>)}
                  </div>
                )}
              </div>
            </div>
          )}
          {error && <div className="text-sm rounded-lg px-3 py-2 bg-rose-500/10 text-rose-600 dark:text-rose-400 border border-rose-500/25">{error}</div>}
        </div>

        <div className="px-6 py-3 border-t flex justify-between" style={{ borderColor: 'var(--border-glass)' }}>
          <button type="button" onClick={() => setStep(s => Math.max(1, s - 1))} disabled={step === 1} className="px-3 py-2 text-sm rounded-lg font-semibold flex items-center gap-1 disabled:opacity-30" style={{ color: 'var(--text-sub)' }}><ChevronLeft className="w-4 h-4" /> Back</button>
          {step < 3 && (
            <button type="button" onClick={() => setStep(s => s + 1)} disabled={step === 1 ? !chosen.length : !theme}
              className="px-4 py-2 text-sm rounded-lg font-bold bg-sky-600 hover:bg-sky-500 text-white disabled:opacity-40 flex items-center gap-1">Next <ChevronRight className="w-4 h-4" /></button>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
