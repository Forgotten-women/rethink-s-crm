import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronLeft, ChevronRight, Clock, Eye, LayoutTemplate, ListChecks, Mail, Plus, RefreshCw, Search, Send, Users, X } from 'lucide-react';
import { API_BASE_URL } from '../../config';
import SegmentBuilder, { cleanSegment, segmentChips } from '../SegmentBuilder';
import { CARD, FIELD, LABEL, PreviewFrame, VariableChips, gbp, insertAtCursor, post, useLivePreview, useTemplates } from './emailUi';
import DesignModal from './builder/DesignModal';

const BATCH = 25;
const CHECK_BATCH = 200;
const STEPS = ['Who', 'Message', 'Review & send'];

/** One person's matching donations and sponsorships, under their row in the recipient list. */
function RecipientDetail({ company, segment, recipient }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState('');
  useEffect(() => {
    if (!recipient.donor_id || recipient.donor_id === recipient.email.toLowerCase() && !recipient.gifts) { setD({ gifts: [], sponsorships: [], count: 0 }); return; }
    post('/api/tracker/direct-email/recipient-gifts', { company_id: company, donor_id: recipient.donor_id, segment: Object.keys(segment).length ? segment : null })
      .then(setD).catch(e => setErr(e.message));
  }, [company, recipient.donor_id]); // eslint-disable-line react-hooks/exhaustive-deps
  if (err) return <div className="px-3 py-2 text-xs text-rose-500">{err}</div>;
  if (!d) return <div className="px-3 py-2 text-xs text-slate-500">Loading their donations…</div>;
  return (
    <div className="px-3 py-2 flex flex-col gap-2 bg-slate-50 dark:bg-slate-900/70">
      {d.sponsorships?.length > 0 && (
        <div className="flex flex-wrap gap-1.5 text-[11px]">
          <span className="font-bold text-slate-600 dark:text-slate-300">Sponsorships:</span>
          {d.sponsorships.map(s => (
            <span key={s.allocation_id} className="px-2 py-0.5 rounded-full bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-200">
              {s.beneficiary || 'Sponsorship'} · {s.type || '—'} · {s.status}{s.end_date ? ` (ends ${String(s.end_date).slice(0, 10)})` : ''}
            </span>
          ))}
        </div>
      )}
      <div className="text-[11px] text-slate-600 dark:text-slate-300"><b>{d.count}</b> matching donation{d.count === 1 ? '' : 's'} · {gbp(d.total)}{d.count > d.gifts.length ? ` (latest ${d.gifts.length} shown)` : ''}</div>
      {d.gifts.length > 0 && (
        <div className="max-h-56 overflow-y-auto rounded-lg border border-slate-200 dark:border-slate-700">
          <table className="w-full text-[11px]">
            <thead className="sticky top-0 bg-white dark:bg-slate-950 text-slate-500"><tr>{['Date', 'Amount', 'Campaign', 'Cause', 'Sponsorship', 'Fundraiser', 'Platform'].map(h => <th key={h} className="px-2 py-1 text-left font-bold">{h}</th>)}</tr></thead>
            <tbody>
              {d.gifts.map((g, i) => (
                <tr key={`${g.donation_id}-${i}`} className="border-t border-slate-100 dark:border-slate-800 text-slate-800 dark:text-slate-100">
                  <td className="px-2 py-1 tabular-nums whitespace-nowrap">{g.date}</td><td className="px-2 py-1 tabular-nums">{gbp(g.amount)}</td>
                  <td className="px-2 py-1">{g.campaign || '—'}</td><td className="px-2 py-1">{g.subheading || g.heading || '—'}</td>
                  <td className="px-2 py-1">{g.stype || '—'}</td><td className="px-2 py-1">{g.fundraiser || '—'}</td><td className="px-2 py-1">{g.platform || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/**
 * Email many people: choose them by donations (filters) - each person appears ONCE with all their matching
 * donations and sponsorships combined - or by hand / typed addresses; write the message with a live preview;
 * then send now in batches or queue it as a named campaign.
 * inline: render as a page section (Email section) instead of a window.
 */
export default function BulkEmailComposer({ company, initialSegment = {}, initialDonorIds = [], startAsCampaign = false, inline = false, onClose, onDone }) {
  const [step, setStep] = useState(1);
  const [segment, setSegment] = useState(initialSegment);
  const [excludeDays, setExcludeDays] = useState('');
  const [extraText, setExtraText] = useState('');
  const [picked, setPicked] = useState([]);
  const [pickQuery, setPickQuery] = useState('');
  const [pickResults, setPickResults] = useState([]);
  const [recipients, setRecipients] = useState(null);
  const [selected, setSelected] = useState(new Set());
  const [expanded, setExpanded] = useState(null);
  const [listFilter, setListFilter] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const { themes, templates, selected: defaultTheme } = useTemplates(company);
  const [theme, setTheme] = useState('');
  const [templateType, setTemplateType] = useState('general_custom');
  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  const [bodyDoc, setBodyDoc] = useState(null); // the builder design of this send
  const [designOpen, setDesignOpen] = useState(false);
  const [edited, setEdited] = useState(false);
  const [messageBody, setMessageBody] = useState('');
  const [previewEmail, setPreviewEmail] = useState('');
  const [rowPreview, setRowPreview] = useState(null);
  const [results, setResults] = useState(null);
  const [progress, setProgress] = useState(null);
  const [campaignName, setCampaignName] = useState('');
  const [asCampaign, setAsCampaign] = useState(startAsCampaign);
  const [customVariables, setCustomVariables] = useState({});
  const [recipientCustomizations, setRecipientCustomizations] = useState({});
  // Every chosen person's email checked before sending: who would be skipped and why (not only the previewed one)
  const [check, setCheck] = useState(null); // { running, done, total, ok, problems: [] }
  const checkSeq = useRef(0);
  const listRef = useRef(null);
  const lastField = useRef({ name: 'message', el: null });

  useEffect(() => { if (recipients && listRef.current) listRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' }); }, [recipients]);
  useEffect(() => { if (!theme && defaultTheme) setTheme(defaultTheme); }, [defaultTheme, theme]);
  useEffect(() => { setSegment(initialSegment || {}); }, [JSON.stringify(initialSegment || {})]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (inline) return undefined;
    const onKey = (e) => {
      if (e.key !== 'Escape') return;
      if (document.querySelector('[role="listbox"]')) return; // Escape closes the open filter list first
      e.stopPropagation(); if (rowPreview) setRowPreview(null); else onClose?.();
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [onClose, inline, rowPreview]);

  useEffect(() => {
    if (initialDonorIds.length) {
      post('/api/tracker/direct-email/recipients', { company_id: company, donor_ids: initialDonorIds }).then(d => setPicked(d.recipients)).catch(() => {});
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const themeTemplates = useMemo(() => templates.filter(t => (t.charity_theme || t.company_id) === theme), [templates, theme]);
  useEffect(() => {
    if (edited) return;
    const t = themeTemplates.find(x => x.template_type === templateType) || themeTemplates.find(x => x.template_type === 'general_custom') || themeTemplates[0];
    if (t && t.template_type !== templateType) { setTemplateType(t.template_type); return; }
    setSubject(t?.subject || ''); setBody(t?.body_html || ''); setBodyDoc(t?.builder_json || null);
  }, [themeTemplates, templateType, edited]);

  useEffect(() => {
    const q = pickQuery.trim();
    if (q.length < 2) { setPickResults([]); return undefined; }
    const t = setTimeout(() => {
      fetch(`${API_BASE_URL}/api/donors/directory?company_id=${encodeURIComponent(company)}&search=${encodeURIComponent(q)}&page_size=8`)
        .then(r => (r.ok ? r.json() : { donors: [] })).then(d => setPickResults(d.donors || [])).catch(() => {});
    }, 300);
    return () => clearTimeout(t);
  }, [pickQuery, company]);

  const extra = useMemo(() => extraText.split(/[\s,;]+/).map(s => s.trim()).filter(s => s.includes('@')).map(email => ({ email, name: '' })), [extraText]);
  const seg = useMemo(() => cleanSegment(segment), [segment]);
  const segActive = Object.keys(seg).length > 0;

  const findRecipients = async () => {
    setError(''); setLoading(true); setExpanded(null);
    try {
      const d = await post('/api/tracker/direct-email/recipients', {
        company_id: company, segment: segActive ? seg : null, donor_ids: picked.map(p => p.donor_id || p.email), extra,
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
    return (recipients?.recipients || []).filter(r => !q || `${r.name} ${r.email} ${r.matched_causes} ${r.sponsorship_types}`.toLowerCase().includes(q));
  }, [recipients, listFilter]);

  const previewRecipient = chosen.find(r => r.email === previewEmail) || chosen[0] || null;
  const activeEmailKey = previewRecipient ? previewRecipient.email.toLowerCase() : '';
  const activeRecipientCust = recipientCustomizations[activeEmailKey] || {};
  const combinedPreviewCustomVars = useMemo(() => ({
    ...customVariables,
    ...(activeRecipientCust.custom_variables || {}),
  }), [customVariables, activeRecipientCust.custom_variables]);
  const activeSelectedAllocationId = activeRecipientCust.selected_allocation_id ?? null;

  const live = useLivePreview({
    company, theme, templateType, subject, body, edited,
    messageBody: activeRecipientCust.message_body || messageBody,
    recipient: previewRecipient,
    customVariables: combinedPreviewCustomVars,
    selectedAllocationId: activeSelectedAllocationId,
    enabled: step >= 2,
  });

  const singleEmailKey = rowPreview ? rowPreview.email.toLowerCase() : '';
  const singleCust = recipientCustomizations[singleEmailKey] || {};
  const singleCustomVars = useMemo(() => ({
    ...customVariables,
    ...(singleCust.custom_variables || {}),
  }), [customVariables, singleCust.custom_variables]);
  const singleSelectedAllocationId = singleCust.selected_allocation_id ?? null;

  const single = useLivePreview({
    company, theme, templateType, subject, body, edited,
    messageBody: singleCust.message_body || messageBody,
    recipient: rowPreview,
    customVariables: singleCustomVars,
    selectedAllocationId: singleSelectedAllocationId,
    enabled: !!rowPreview,
  });

  const payloadText = () => ({
    company_id: company, theme, template_type: templateType, message_body: messageBody || null,
    subject_template: edited ? subject : null, body_template: edited ? body : null,
    custom_variables: customVariables,
    recipient_customizations: recipientCustomizations,
  });
  const insert = (text) => {
    const f = lastField.current;
    if (f.name === 'subject') { setSubject(v => insertAtCursor(f.el, v, text)); setEdited(true); }
    else if (f.name === 'body') { setBody(v => insertAtCursor(f.el, v, text)); setEdited(true); }
    else setMessageBody(v => insertAtCursor(f.el, v, text));
  };
  const track = (name) => (e) => { lastField.current = { name, el: e.target }; };

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
        matched: chosen.map(r => ({ email: r.email, matched_gifts: r.matched_gifts, matched_total: r.matched_total, matched_causes: r.matched_causes, matched_sponsorships: r.matched_sponsorships })),
        segment: null, exclude_other_pending: false,
      });
      setResults({ campaign: d });
      onDone?.();
    } catch (e) { setError(e.message); } finally { setLoading(false); }
  };

  const runCheck = async () => {
    const my = ++checkSeq.current;
    const list = chosen;
    setCheck({ running: true, done: 0, total: list.length, ok: 0, problems: [] });
    let ok = 0; const problems = [];
    for (let i = 0; i < list.length; i += CHECK_BATCH) {
      try {
        const d = await post('/api/tracker/direct-email/check', { ...payloadText(), recipients: list.slice(i, i + CHECK_BATCH) });
        if (my !== checkSeq.current) return; // a newer check started (text or selection changed)
        ok += d.ok; problems.push(...d.problems);
        setCheck({ running: i + CHECK_BATCH < list.length, done: Math.min(i + CHECK_BATCH, list.length), total: list.length, ok, problems: [...problems] });
      } catch (e) {
        if (my === checkSeq.current) setCheck(c => ({ ...(c || {}), running: false, error: e.message }));
        return;
      }
    }
  };
  // Re-check whenever the review step is open and what is sent (people, template, text, variables) changes
  const checkKey = `${step === 3}|${theme}|${templateType}|${edited ? subject : ''}|${edited ? body : ''}|${messageBody}|${JSON.stringify(customVariables)}|${JSON.stringify(recipientCustomizations)}|${chosen.map(r => r.email).join(',')}`;
  useEffect(() => {
    if (step !== 3 || !chosen.length || !theme) return undefined;
    const t = setTimeout(runCheck, 600);
    return () => clearTimeout(t);
  }, [checkKey]); // eslint-disable-line react-hooks/exhaustive-deps
  const problemByEmail = useMemo(() => Object.fromEntries((check?.problems || []).map(p => [p.email, p])), [check]);
  const willSkip = check && !check.running ? check.problems.length : 0;

  const summary = results?.rows ? results.rows.reduce((a, r) => ({ ...a, [r.status]: (a[r.status] || 0) + 1 }), {}) : null;
  const hasMatches = (recipients?.recipients || []).some(r => r.matched_gifts != null);

  const content = (
    <>
      <div className="px-5 py-3 border-b border-slate-200 dark:border-slate-700 flex items-center justify-between gap-3 bg-gradient-to-br from-sky-500/10 to-transparent">
        <div>
          <h2 className="text-base font-black flex items-center gap-2 text-slate-900 dark:text-white"><Mail className="w-5 h-5 text-sky-500" /> Email many people</h2>
          <div className="flex items-center gap-1.5 text-xs mt-1">
            {STEPS.map((s, i) => (
              <button key={s} type="button" disabled={i + 1 > step && !(i === 1 && chosen.length) && !(i === 2 && chosen.length && theme)}
                onClick={() => setStep(i + 1)}
                className={`px-2.5 py-0.5 rounded-full font-semibold disabled:opacity-40 ${step === i + 1 ? 'bg-sky-600 text-white' : 'text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800'}`}>
                {i + 1}. {s}
              </button>
            ))}
            {chosen.length > 0 && <span className="ml-2 text-slate-500">{chosen.length} selected</span>}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {inline && step > 1 && (
            <button type="button" onClick={() => setStep(s => Math.max(1, s - 1))} className="px-3 py-1.5 text-xs rounded-lg font-semibold flex items-center gap-1 text-slate-600 dark:text-slate-300 border border-slate-200 dark:border-slate-700"><ChevronLeft className="w-3.5 h-3.5" /> Back</button>
          )}
          {inline && step < 3 && (
            <button type="button" onClick={() => setStep(s => s + 1)} disabled={step === 1 ? !chosen.length : !theme}
              className="px-3 py-1.5 text-xs rounded-lg font-bold bg-sky-600 hover:bg-sky-500 text-white disabled:opacity-40 flex items-center gap-1">Next <ChevronRight className="w-3.5 h-3.5" /></button>
          )}
          {!inline && <button type="button" onClick={onClose} aria-label="Close" className="w-8 h-8 rounded-full flex items-center justify-center text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"><X className="w-4 h-4" /></button>}
        </div>
      </div>

      <div className={`${inline ? '' : 'flex-1 min-h-0 overflow-y-auto'} px-5 py-4 space-y-4 text-sm`}>
        {step === 1 && (
          <>
            <SegmentBuilder company={company} value={segment} onChange={setSegment} defaultOpen />
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
              <div className={`${CARD} flex flex-col gap-2`}>
                <div className="text-xs font-bold text-slate-800 dark:text-slate-100">Add people by name</div>
                <span className="relative">
                  <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
                  <input value={pickQuery} onChange={e => setPickQuery(e.target.value)} placeholder="Search name, email or phone" className={`${FIELD} pl-8 pr-2 py-1.5 text-xs`} />
                </span>
                {pickResults.map(d => (
                  <button key={d.donor_id} type="button" disabled={!d.email} onClick={() => { setPicked(p => (p.some(x => x.email === d.email) ? p : [...p, { donor_id: d.donor_id, email: d.email, name: d.name }])); setPickQuery(''); }}
                    className="text-left text-xs px-2 py-1.5 rounded-lg hover:bg-sky-500/10 disabled:opacity-40 flex justify-between gap-2 text-slate-800 dark:text-slate-100">
                    <span className="truncate">{d.name || d.email} <span className="text-slate-500">{d.email || '(no email)'}</span></span><Plus className="w-3.5 h-3.5 shrink-0" />
                  </button>
                ))}
                <div className="flex flex-wrap gap-1">
                  {picked.map(p => (
                    <span key={p.email} className="text-[11px] px-2 py-0.5 rounded-full bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-200 flex items-center gap-1">
                      {p.name || p.email}<button type="button" onClick={() => setPicked(x => x.filter(y => y.email !== p.email))}><X className="w-3 h-3" /></button>
                    </span>
                  ))}
                </div>
              </div>
              <div className={`${CARD} flex flex-col gap-2`}>
                <div className="text-xs font-bold text-slate-800 dark:text-slate-100">Or type email addresses</div>
                <textarea value={extraText} onChange={e => setExtraText(e.target.value)} rows={4} placeholder="one@example.com, two@example.com" className={`${FIELD} px-2 py-1.5 text-xs`} />
                <span className="text-[11px] text-slate-500">{extra.length} address{extra.length === 1 ? '' : 'es'}</span>
              </div>
              <div className={`${CARD} flex flex-col gap-2`}>
                <div className="text-xs font-bold flex items-center gap-1 text-slate-800 dark:text-slate-100"><Clock className="w-3.5 h-3.5" /> Don't email people contacted recently</div>
                <label className="text-xs flex items-center gap-2 text-slate-600 dark:text-slate-300">
                  Skip anyone emailed in the last
                  <input type="number" min="0" value={excludeDays} onChange={e => setExcludeDays(e.target.value)} className={`${FIELD} !w-16 px-2 py-1`} /> days
                </label>
                <button type="button" onClick={findRecipients} disabled={loading || (!segActive && !picked.length && !extra.length)}
                  className="mt-auto px-3 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 text-white font-bold text-xs disabled:opacity-40 flex items-center justify-center gap-1.5">
                  <Users className="w-4 h-4" />{loading ? 'Finding…' : 'Find recipients'}
                </button>
              </div>
            </div>
            {recipients && (
              <div ref={listRef} className="rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden">
                <div className="px-3 py-2 flex items-center justify-between gap-2 flex-wrap border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900">
                  <span className="text-xs text-slate-800 dark:text-slate-100">
                    <b>{selected.size}</b> of {recipients.count} people selected - one row per person, their matching donations combined
                    {recipients.excluded_recently_emailed ? ` · ${recipients.excluded_recently_emailed} skipped (emailed recently)` : ''}
                  </span>
                  <span className="flex items-center gap-2">
                    <input value={listFilter} onChange={e => setListFilter(e.target.value)} placeholder="Filter list" className={`${FIELD} !w-40 px-2 py-1 text-xs`} />
                    <button type="button" onClick={() => setSelected(new Set(recipients.recipients.map(r => r.email)))} className="text-xs font-semibold text-sky-600">All</button>
                    <button type="button" onClick={() => setSelected(new Set())} className="text-xs font-semibold text-sky-600">None</button>
                  </span>
                </div>
                {recipients.count === 0 && <div className="px-3 py-6 text-center text-xs text-slate-500">Nobody with an email address matches these filters.</div>}
                <div className="max-h-[55vh] overflow-y-auto">
                  <table className="w-full text-xs">
                    <thead className="sticky top-0 z-10 bg-white dark:bg-slate-950 text-slate-500">
                      <tr>{['', 'Name', 'Email', hasMatches ? 'Matching donations' : 'Gifts', 'For', 'Lifetime', 'Last gift', 'Sponsorships', ''].map((h, i) => <th key={`${h}-${i}`} className="px-2 py-1.5 text-left font-bold">{h}</th>)}</tr>
                    </thead>
                    <tbody>
                      {shownList.slice(0, 1000).map(r => (
                        <React.Fragment key={r.email}>
                          <tr className="border-t border-slate-100 dark:border-slate-800 text-slate-800 dark:text-slate-100 hover:bg-sky-50/60 dark:hover:bg-sky-950/20">
                            <td className="px-2 py-1"><input type="checkbox" checked={selected.has(r.email)} onChange={() => setSelected(s => { const n = new Set(s); n.has(r.email) ? n.delete(r.email) : n.add(r.email); return n; })} /></td>
                            <td className="px-2 py-1 font-semibold">
                              <span className="flex items-center gap-1">{r.name || '—'}
                                {problemByEmail[r.email] && <span title={`Will be skipped: ${problemByEmail[r.email].issue}`}><AlertTriangle className="w-3.5 h-3.5 text-amber-500" /></span>}
                              </span>
                            </td>
                            <td className="px-2 py-1">{r.email}</td>
                            <td className="px-2 py-1 tabular-nums whitespace-nowrap">{r.matched_gifts != null ? `${r.matched_gifts} · ${gbp(r.matched_total)}` : (r.gifts ?? '—')}</td>
                            <td className="px-2 py-1 max-w-[16rem] truncate" title={[r.matched_causes, r.matched_sponsorships].filter(Boolean).join(' · ')}>{[r.matched_sponsorships, r.matched_causes].filter(Boolean).join(' · ') || '—'}</td>
                            <td className="px-2 py-1 tabular-nums">{gbp(r.total)}</td>
                            <td className="px-2 py-1">
                              {r.allocations > 1 ? (
                                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-200">
                                  <Users className="w-3 h-3" /> {r.allocations} beneficiaries
                                </span>
                              ) : r.allocations === 1 ? (
                                `${r.allocations} (${r.sponsorship_statuses})`
                              ) : (
                                r.sponsorship_types || '—'
                              )}
                            </td>
                            <td className="px-2 py-1 whitespace-nowrap text-right">
                              <button type="button" onClick={() => setRowPreview(r)} title="Preview this person's email" className="p-1 rounded hover:bg-sky-100 dark:hover:bg-sky-900/40 text-sky-600"><Eye className="w-3.5 h-3.5" /></button>
                              <button type="button" onClick={() => setExpanded(x => (x === r.email ? null : r.email))} title="Their matching donations" className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800">
                                <ChevronDown className={`w-3.5 h-3.5 transition-transform ${expanded === r.email ? 'rotate-180' : ''}`} />
                              </button>
                            </td>
                          </tr>
                          {expanded === r.email && <tr><td colSpan={9} className="p-0"><RecipientDetail company={company} segment={seg} recipient={r} /></td></tr>}
                        </React.Fragment>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </>
        )}

        {step === 2 && (
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            <div className="flex flex-col gap-3">
              <div className={`${CARD} grid grid-cols-1 sm:grid-cols-2 gap-2`}>
                <label className={LABEL}>Theme / sender branding
                  <select value={theme} onChange={e => { setTheme(e.target.value); setEdited(false); }} className={`${FIELD} px-2 py-1.5 text-sm normal-case font-normal tracking-normal`}>
                    {themes.map(t => <option key={t.id || t} value={t.id || t}>{t.label || t.name || t.id || t}</option>)}
                  </select>
                </label>
                <label className={LABEL}>Template
                  <select value={templateType} onChange={e => { setTemplateType(e.target.value); setEdited(false); }} className={`${FIELD} px-2 py-1.5 text-sm normal-case font-normal tracking-normal`}>
                    {themeTemplates.map(t => <option key={t.template_type} value={t.template_type}>{t.template_type.replace(/_/g, ' ')} - {t.subject}</option>)}
                  </select>
                </label>
              </div>
              <label className={LABEL}>Subject
                <input value={subject} onFocus={track('subject')} onClick={track('subject')} onChange={e => { setSubject(e.target.value); setEdited(true); track('subject')(e); }} className={`${FIELD} px-2.5 py-2 text-sm normal-case font-normal tracking-normal`} />
              </label>
              <label className={LABEL}>Your message (fills {'{message_body}'})
                <textarea value={messageBody} onFocus={track('message')} onClick={track('message')} onChange={e => { setMessageBody(e.target.value); track('message')(e); }} rows={6}
                  placeholder="Thank you for your generous support." className={`${FIELD} px-2.5 py-2 text-sm normal-case font-normal tracking-normal leading-relaxed`} />
              </label>
              <div className={`${CARD} flex items-center justify-between gap-3`}>
                <div className="text-xs text-slate-600 dark:text-slate-300">
                  <div className="font-bold text-slate-800 dark:text-slate-100">Design{edited ? ' (changed for this send)' : ''}</div>
                  Add text, buttons, boxes or images, or change colours and fonts - for this send only.
                </div>
                <button type="button" onClick={() => setDesignOpen(true)} className="shrink-0 px-3 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-bold flex items-center gap-1.5"><LayoutTemplate className="w-3.5 h-3.5" />Customise the design</button>
              </div>
              {designOpen && <DesignModal html={body} doc={bodyDoc} onClose={() => setDesignOpen(false)} onApply={(d, h) => { setBodyDoc(d); setBody(h); setEdited(true); }} />}
              <div className={CARD}>
                <div className="text-[11px] font-bold uppercase tracking-wider text-slate-600 dark:text-slate-300 mb-1.5">Personalise - click to insert</div>
                <VariableChips onInsert={insert} />
                <p className="mt-2 text-[11px] text-slate-500">Each person gets one email. Someone with several sponsorships gets them all: {'{beneficiary_name}'} joins the names, {'{sponsorships_list}'} lists each one. Anyone a template can't fill is skipped, never sent a half-filled email.</p>
              </div>
            </div>
            <div className="flex flex-col gap-2 xl:sticky xl:top-0 self-start w-full">
              <div className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-wider text-slate-600 dark:text-slate-300">
                <Eye className="w-3.5 h-3.5" /> Live preview for
                <select value={previewRecipient?.email || ''} onChange={e => setPreviewEmail(e.target.value)} className={`${FIELD} !w-auto px-2 py-1 text-xs normal-case font-normal tracking-normal`}>
                  {chosen.slice(0, 500).map(r => <option key={r.email} value={r.email}>{r.name || r.email}</option>)}
                </select>
              </div>
              <PreviewFrame
                preview={live.preview}
                busy={live.busy}
                height="64vh"
                customVariables={combinedPreviewCustomVars}
                onCustomVariableChange={(p, val) => {
                  setCustomVariables(cv => ({ ...cv, [p]: val }));
                  if (activeEmailKey) {
                    setRecipientCustomizations(rc => ({
                      ...rc,
                      [activeEmailKey]: {
                        ...(rc[activeEmailKey] || {}),
                        custom_variables: { ...((rc[activeEmailKey] || {}).custom_variables || {}), [p]: val }
                      }
                    }));
                  }
                }}
                selectedAllocationId={activeSelectedAllocationId}
                onSelectAllocation={(allocId) => {
                  if (activeEmailKey) {
                    setRecipientCustomizations(rc => ({
                      ...rc,
                      [activeEmailKey]: {
                        ...(rc[activeEmailKey] || {}),
                        selected_allocation_id: allocId
                      }
                    }));
                  }
                }}
              />
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
            <div className="xl:col-span-2 flex flex-col gap-2">
              <div className="flex items-center gap-2 text-xs text-slate-600 dark:text-slate-300">
                <Eye className="w-4 h-4" /> Preview for
                <select value={previewRecipient?.email || ''} onChange={e => setPreviewEmail(e.target.value)} className={`${FIELD} !w-auto px-2 py-1`}>
                  {chosen.slice(0, 500).map(r => <option key={r.email} value={r.email}>{r.name || r.email}</option>)}
                </select>
              </div>
              <PreviewFrame
                preview={live.preview}
                busy={live.busy}
                height="52vh"
                customVariables={combinedPreviewCustomVars}
                onCustomVariableChange={(p, val) => {
                  setCustomVariables(cv => ({ ...cv, [p]: val }));
                  if (activeEmailKey) {
                    setRecipientCustomizations(rc => ({
                      ...rc,
                      [activeEmailKey]: {
                        ...(rc[activeEmailKey] || {}),
                        custom_variables: { ...((rc[activeEmailKey] || {}).custom_variables || {}), [p]: val }
                      }
                    }));
                  }
                }}
                selectedAllocationId={activeSelectedAllocationId}
                onSelectAllocation={(allocId) => {
                  if (activeEmailKey) {
                    setRecipientCustomizations(rc => ({
                      ...rc,
                      [activeEmailKey]: {
                        ...(rc[activeEmailKey] || {}),
                        selected_allocation_id: allocId
                      }
                    }));
                  }
                }}
              />
            </div>
            <div className="flex flex-col gap-3">
              <div className={`${CARD} text-xs flex flex-col gap-2 text-slate-800 dark:text-slate-100`}>
                <div><b>{chosen.length}</b> {chosen.length === 1 ? 'person' : 'people'} · template <b>{templateType.replace(/_/g, ' ')}</b>{edited ? ' (edited)' : ''}</div>
                {segmentChips(seg).length > 0 && <div className="text-slate-500">{segmentChips(seg).map(c => c.text).join(' · ')}</div>}
                <label className="flex items-center gap-2"><input type="checkbox" checked={asCampaign} onChange={e => setAsCampaign(e.target.checked)} /> Queue as a campaign instead of sending now</label>
                {asCampaign ? (
                  <>
                    <input value={campaignName} onChange={e => setCampaignName(e.target.value)} placeholder="Campaign name, e.g. Hafiz donors – Jan update" className={`${FIELD} px-2 py-1.5`} />
                    <button type="button" onClick={queueCampaign} disabled={loading || !chosen.length} className="px-3 py-2 rounded-lg bg-violet-600 hover:bg-violet-500 text-white font-bold disabled:opacity-40 flex items-center justify-center gap-1.5"><ListChecks className="w-4 h-4" /> Add to email queue</button>
                  </>
                ) : (
                  <>
                    <button type="button" onClick={() => runBatches(true)} disabled={!!progress || !chosen.length} className="px-3 py-2 rounded-lg border border-slate-300 dark:border-slate-600 font-bold disabled:opacity-40">Check everyone (no sending)</button>
                    <button type="button"
                      onClick={() => { if (window.confirm(willSkip ? `Send to ${chosen.length - willSkip} people now? ${willSkip} will be skipped (listed below).` : `Send this email to ${chosen.length} people now?`)) runBatches(false); }}
                      disabled={!!progress || !chosen.length || check?.running || willSkip === chosen.length}
                      className="px-3 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 text-white font-bold disabled:opacity-40 flex items-center justify-center gap-1.5">
                      <Send className="w-4 h-4" /> {check?.running ? 'Checking everyone…' : `Send to ${chosen.length - willSkip}`}
                    </button>
                  </>
                )}
                {progress && <div className="text-slate-500">{progress.dryRun ? 'Checking' : 'Sending'}… {progress.done}/{progress.total}</div>}
                {summary && <div><b>{results.dryRun ? 'Check' : 'Done'}:</b> {Object.entries(summary).map(([k, v]) => `${v} ${k === 'ok' ? 'ready' : k}`).join(' · ')}</div>}
                {results?.campaign && <div className="text-violet-700 dark:text-violet-300">Queued {results.campaign.queued} in the email queue (Campaigns tab).</div>}
              </div>
              <div className={`${CARD} text-xs flex flex-col gap-2`}>
                <div className="flex items-center justify-between gap-2">
                  <span className="font-bold text-slate-800 dark:text-slate-100">Every email checked</span>
                  <button type="button" onClick={runCheck} disabled={check?.running} className="flex items-center gap-1 text-sky-600 disabled:opacity-40"><RefreshCw className={`w-3 h-3 ${check?.running ? 'animate-spin' : ''}`} /> Re-check</button>
                </div>
                {!check && <span className="text-slate-500">Checking…</span>}
                {check?.running && <span className="text-slate-500">Checking {check.done.toLocaleString()} / {check.total.toLocaleString()}…</span>}
                {check?.error && <span className="text-rose-600">{check.error}</span>}
                {check && !check.running && !check.error && (
                  <>
                    <span className="flex items-center gap-1 text-emerald-700 dark:text-emerald-400"><CheckCircle2 className="w-3.5 h-3.5" /> {check.ok.toLocaleString()} ready to send</span>
                    {check.problems.length > 0 ? (
                      <div className="rounded-lg border border-amber-300 bg-amber-50 dark:bg-amber-950/30 dark:border-amber-800 p-2 flex flex-col gap-1.5">
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-bold text-amber-800 dark:text-amber-300 flex items-center gap-1"><AlertTriangle className="w-3.5 h-3.5" /> {check.problems.length} will be skipped</span>
                          <button type="button" onClick={() => setSelected(sel => { const n = new Set(sel); check.problems.forEach(p => n.delete(p.email)); return n; })}
                            className="text-[11px] font-semibold text-amber-800 dark:text-amber-300 underline">Leave them out</button>
                        </div>
                        <div className="max-h-64 overflow-y-auto flex flex-col divide-y divide-amber-200 dark:divide-amber-900">
                          {check.problems.map(p => (
                            <div key={p.email} className="py-2 flex flex-col gap-1.5">
                              <div className="flex items-start justify-between gap-2">
                                <span className="min-w-0"><b className="text-slate-800 dark:text-slate-100">{p.name || p.email}</b> <span className="text-slate-500">{p.email}</span>
                                  <span className="block text-[11px] text-amber-800 dark:text-amber-300">{p.issue}</span></span>
                                <button type="button" onClick={() => setRowPreview(chosen.find(r => r.email === p.email) || { email: p.email, name: p.name })} title="Preview and supply missing variable" className="px-2 py-0.5 rounded bg-amber-100 dark:bg-amber-900/60 text-amber-900 dark:text-amber-200 text-[11px] font-semibold flex items-center gap-1 shrink-0"><Eye className="w-3 h-3" /> Supply & Fix</button>
                              </div>
                              {p.missing?.length > 0 && (
                                <div className="flex flex-wrap items-center gap-2 pl-1">
                                  {p.missing.map(m => (
                                    <div key={m} className="flex items-center gap-1 text-[11px]">
                                      <span className="font-mono text-amber-800 dark:text-amber-300">{`{${m}}`}:</span>
                                      <input
                                        type="text"
                                        placeholder={`Value for {${m}}...`}
                                        value={customVariables[m] || ''}
                                        onChange={e => {
                                          const val = e.target.value;
                                          setCustomVariables(cv => ({ ...cv, [m]: val }));
                                        }}
                                        className="text-xs px-2 py-0.5 rounded border border-amber-300 dark:border-amber-700 bg-white dark:bg-slate-900 text-slate-800 dark:text-slate-100 w-32 focus:outline-none focus:ring-1 focus:ring-amber-500"
                                      />
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : <span className="text-slate-500">Nobody will be skipped.</span>}
                  </>
                )}
              </div>
              {results?.rows && results.rows.some(r => r.detail) && (
                <div className={`${CARD} text-[11px] max-h-60 overflow-y-auto text-slate-600 dark:text-slate-300`}>
                  {results.rows.filter(r => r.detail).slice(0, 200).map(r => <div key={r.recipient_email}>{r.recipient_email}: {r.detail}</div>)}
                </div>
              )}
            </div>
          </div>
        )}
        {error && <div className="text-sm rounded-lg px-3 py-2 bg-rose-50 text-rose-700 border border-rose-200 dark:bg-rose-950/40 dark:text-rose-300 dark:border-rose-900">{error}</div>}
      </div>

      <div className={`px-5 py-3 border-t border-slate-200 dark:border-slate-700 flex justify-between bg-white dark:bg-slate-900 ${inline ? 'rounded-b-2xl' : ''}`}>
        <button type="button" onClick={() => setStep(s => Math.max(1, s - 1))} disabled={step === 1} className="px-3 py-2 text-sm rounded-lg font-semibold flex items-center gap-1 disabled:opacity-30 text-slate-600 dark:text-slate-300"><ChevronLeft className="w-4 h-4" /> Back</button>
        {step < 3 && (
          <button type="button" onClick={() => setStep(s => s + 1)} disabled={step === 1 ? !chosen.length : !theme}
            className="px-4 py-2 text-sm rounded-lg font-bold bg-sky-600 hover:bg-sky-500 text-white disabled:opacity-40 flex items-center gap-1">Next <ChevronRight className="w-4 h-4" /></button>
        )}
      </div>

      {rowPreview && createPortal(
        <div className="fixed inset-0 z-[95] flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-label={`Preview for ${rowPreview.name || rowPreview.email}`}>
          <div className="absolute inset-0 bg-black/50" onClick={() => setRowPreview(null)} />
          <div className="relative w-full max-w-3xl rounded-2xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 shadow-2xl p-4 flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2">
              <div className="text-sm font-bold text-slate-900 dark:text-white">What {rowPreview.name || rowPreview.email} would get <span className="font-normal text-slate-500">· template {templateType.replace(/_/g, ' ')}</span></div>
              <button type="button" onClick={() => setRowPreview(null)} aria-label="Close preview" className="w-7 h-7 rounded-full flex items-center justify-center text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"><X className="w-4 h-4" /></button>
            </div>
            <PreviewFrame
              preview={single.preview}
              busy={single.busy}
              height="65vh"
              customVariables={singleCustomVars}
              onCustomVariableChange={(p, val) => {
                setCustomVariables(cv => ({ ...cv, [p]: val }));
                if (singleEmailKey) {
                  setRecipientCustomizations(rc => ({
                    ...rc,
                    [singleEmailKey]: {
                      ...(rc[singleEmailKey] || {}),
                      custom_variables: { ...((rc[singleEmailKey] || {}).custom_variables || {}), [p]: val }
                    }
                  }));
                }
              }}
              selectedAllocationId={singleSelectedAllocationId}
              onSelectAllocation={(allocId) => {
                if (singleEmailKey) {
                  setRecipientCustomizations(rc => ({
                    ...rc,
                    [singleEmailKey]: {
                      ...(rc[singleEmailKey] || {}),
                      selected_allocation_id: allocId
                    }
                  }));
                }
              }}
            />
          </div>
        </div>,
        document.body,
      )}
    </>
  );

  if (inline) {
    return <div className="rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 shadow-sm">{content}</div>;
  }
  return createPortal(
    <div className="fixed inset-0 z-[80] flex items-center justify-center p-2 sm:p-5" role="dialog" aria-modal="true" aria-label="Email many people">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-7xl h-[94vh] flex flex-col rounded-2xl shadow-2xl overflow-hidden border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900">{content}</div>
    </div>,
    document.body,
  );
}
