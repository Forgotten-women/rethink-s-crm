import React, { useEffect, useRef, useState } from 'react';
import { API_BASE_URL } from '../../config';

// Form fields of the email screens: solid background, visible border and a focus ring, in light and dark theme
// (the shared --input-* colours were too close to the card background in the Message step).
export const FIELD = 'w-full rounded-lg border bg-white text-slate-900 border-slate-300 placeholder:text-slate-400 '
  + 'focus:outline-none focus:ring-2 focus:ring-sky-500/40 focus:border-sky-500 '
  + 'dark:bg-slate-950 dark:text-slate-100 dark:border-slate-600 dark:placeholder:text-slate-500';
export const LABEL = 'flex flex-col gap-1 text-[11px] font-bold uppercase tracking-wider text-slate-600 dark:text-slate-300';
export const CARD = 'rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50/80 dark:bg-slate-900/60 p-3';

export const VARIABLES = [
  ['first_name', 'First name'], ['donor_name', 'Full name'], ['total_given', 'Lifetime given'], ['gifts_count', 'Number of gifts'],
  ['average_gift', 'Average gift'], ['lifetime_tier', 'LTV tier'], ['first_gift_date', 'First gift date'],
  ['last_gift_date', 'Last gift date'], ['last_gift_amount', 'Last gift amount'], ['last_gift_cause', 'Last gift cause'],
  ['top_cause', 'Top cause'], ['matching_total', 'Matching donations total'], ['matching_gifts_count', 'Matching donations'],
  ['matching_causes', 'Matching causes'], ['matching_sponsorships', 'Matching sponsorships'], ['sponsorship_types', 'Sponsorship types'],
  ['beneficiary_name', 'Beneficiary (all, joined)'], ['sponsorships_list', 'List of all their sponsorships'],
  ['sponsorships_count', 'Number of sponsorships'], ['sponsorship_type', 'Sponsorship type'], ['location', 'Location'],
  ['profile_link', 'Profile link'], ['video_link', 'Video link'], ['renewal_deadline', 'Renewal date'], ['message_body', 'Your message'],
];

export async function post(path, body) {
  const res = await fetch(`${API_BASE_URL}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Error ${res.status}`);
  return data;
}

export const gbp = (v) => (v == null || v === '' ? '—' : `£${Number(v).toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);

/** Templates of the charity's themes (the tracker's templates). */
export function useTemplates(company) {
  const [state, setState] = useState({ themes: [], templates: [], selected: '' });
  useEffect(() => {
    if (!company || company === 'all') return;
    fetch(`${API_BASE_URL}/api/tracker/email-templates?company_id=${encodeURIComponent(company)}`)
      .then(r => (r.ok ? r.json() : {}))
      .then(d => setState({ themes: d.available_themes || [], templates: d.templates || [], selected: d.selected_theme || (d.available_themes?.[0]?.id ?? '') }))
      .catch(() => {});
  }, [company]);
  return state;
}

/** Rendered email for one recipient, refreshed as the text changes (debounced) - the live preview. */
export function useLivePreview({ company, theme, templateType, subject, body, edited, messageBody, recipient, enabled = true }) {
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const seq = useRef(0);
  const recipientKey = recipient ? `${recipient.email}|${recipient.donor_id || ''}` : '';
  useEffect(() => {
    if (!enabled || !recipient || !theme) { setPreview(null); return undefined; }
    const my = ++seq.current;
    setBusy(true);
    const body_ = {
      company_id: company, theme, template_type: templateType, message_body: messageBody || null,
      subject_template: edited ? subject : null, body_template: edited ? body : null, recipient,
    };
    const t = setTimeout(() => {
      // one quiet retry: a busy moment on the server (e.g. donor data refreshing after a new donation) shouldn't
      // show "Error 502" in the preview
      post('/api/tracker/direct-email/preview', body_)
        .catch(() => new Promise(r => setTimeout(r, 2000)).then(() => post('/api/tracker/direct-email/preview', body_)))
        .then(p => { if (my === seq.current) setPreview(p); })
        .catch(e => { if (my === seq.current) setPreview({ error: `Couldn't render the preview (${e.message}). It refreshes when you change the text, or try again in a moment.` }); })
        .finally(() => { if (my === seq.current) setBusy(false); });
    }, 450);
    return () => clearTimeout(t);
  }, [company, theme, templateType, subject, body, edited, messageBody, recipientKey, enabled]); // eslint-disable-line react-hooks/exhaustive-deps
  return { preview, busy };
}

export function PreviewFrame({ preview, busy, height = '60vh', emptyText = 'Choose a template to see the email.' }) {
  if (!preview) {
    return <div className="rounded-xl border border-dashed border-slate-300 dark:border-slate-700 p-6 text-center text-xs text-slate-500">{busy ? 'Rendering…' : emptyText}</div>;
  }
  if (preview.error) return <div className="rounded-xl border border-rose-300 bg-rose-50 dark:bg-rose-950/40 p-3 text-xs text-rose-600">{preview.error}</div>;
  return (
    <div className="rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden bg-white">
      <div className="px-3 py-2 text-xs border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-slate-800 dark:text-slate-100 flex items-center justify-between gap-2">
        <span className="min-w-0 truncate"><b>{preview.subject || '(no subject)'}</b> <span className="text-slate-500">→ {preview.recipient_email}</span></span>
        {busy && <span className="text-[10px] text-sky-600 shrink-0">updating…</span>}
      </div>
      {preview.unresolved_placeholders?.length > 0 && (
        <div className="px-3 py-1.5 text-[11px] bg-amber-50 text-amber-800 dark:bg-amber-950/40 dark:text-amber-300 border-b border-amber-200 dark:border-amber-900">
          This person would be skipped: the template needs {preview.unresolved_placeholders.map(p => `{${p}}`).join(', ')}
        </div>
      )}
      <iframe title="Email preview" sandbox="" srcDoc={preview.body_html} className="w-full bg-white" style={{ height }} />
    </div>
  );
}

/** Click a variable to insert it at the cursor of the last focused field. */
export function VariableChips({ onInsert }) {
  return (
    <div className="flex flex-wrap gap-1">
      {VARIABLES.map(([v, label]) => (
        <button key={v} type="button" title={label} onMouseDown={e => e.preventDefault()} onClick={() => onInsert(`{${v}}`)}
          className="px-1.5 py-0.5 rounded text-[11px] font-mono bg-sky-100 text-sky-800 hover:bg-sky-200 dark:bg-sky-900/50 dark:text-sky-200 dark:hover:bg-sky-800/60">
          {`{${v}}`}
        </button>
      ))}
    </div>
  );
}

/** Insert text at the cursor of a textarea/input held in a ref; returns the new value. */
export function insertAtCursor(el, value, text) {
  if (!el) return value + text;
  const start = el.selectionStart ?? value.length;
  const end = el.selectionEnd ?? value.length;
  const next = value.slice(0, start) + text + value.slice(end);
  requestAnimationFrame(() => { el.focus(); el.setSelectionRange(start + text.length, start + text.length); });
  return next;
}
