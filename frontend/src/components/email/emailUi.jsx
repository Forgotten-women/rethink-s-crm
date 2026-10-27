import React, { useEffect, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, Users } from 'lucide-react';
import { API_BASE_URL } from '../../config';

// Form fields of the email screens: solid background, visible border and a focus ring, in light and dark theme
// (the shared --input-* colours were too close to the card background in the Message step).
export const FIELD = 'w-full rounded-lg border bg-white text-slate-900 border-slate-300 placeholder:text-slate-400 '
  + 'focus:outline-none focus:ring-2 focus:ring-sky-500/40 focus:border-sky-500 '
  + 'dark:bg-slate-950 dark:text-slate-100 dark:border-slate-600 dark:placeholder:text-slate-500';
export const LABEL = 'flex flex-col gap-1 text-[11px] font-bold uppercase tracking-wider text-slate-600 dark:text-slate-300';
export const CARD = 'rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50/80 dark:bg-slate-900/60 p-3';

export const VARIABLES = [
  ['first_name', 'First name'], ['last_name', 'Last name'], ['donor_name', 'Full name'], ['total_given', 'Lifetime given'], ['gifts_count', 'Number of gifts'],
  ['average_gift', 'Average gift'], ['lifetime_tier', 'LTV tier'], ['first_gift_date', 'First gift date'],
  ['last_gift_date', 'Last gift date'], ['last_gift_amount', 'Last gift amount'], ['last_gift_cause', 'Last gift cause'],
  ['top_cause', 'Top cause'], ['matching_total', 'Matching donations total'], ['matching_gifts_count', 'Matching donations'],
  ['matching_causes', 'Matching causes'], ['matching_sponsorships', 'Matching sponsorships'], ['sponsorship_types', 'Sponsorship types'],
  ['beneficiary_name', 'Beneficiary (all, joined)'], ['beneficiary_first_name', 'Beneficiary first name'], ['beneficiary_last_name', 'Beneficiary last name'], ['sponsorships_list', 'List of all their sponsorships'],
  ['sponsorships_count', 'Number of sponsorships'], ['sponsorship_type', 'Sponsorship type'], ['location', 'Location'],
  ['profile_link', 'Profile link'], ['video_link', 'Video link'], ['renewal_deadline', 'Renewal date'],
  ['days_remaining', 'Days remaining'], ['message_body', 'Your message'],
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
export function useLivePreview({
  company, theme, templateType, subject, body, edited, messageBody, recipient,
  customVariables = null, selectedAllocationId = null, enabled = true
}) {
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const seq = useRef(0);
  const recipientKey = recipient ? `${recipient.email}|${recipient.donor_id || ''}` : '';
  const customVarsKey = customVariables ? JSON.stringify(customVariables) : '';
  useEffect(() => {
    if (!enabled || !recipient || !theme) { setPreview(null); return undefined; }
    const my = ++seq.current;
    setBusy(true);
    const body_ = {
      company_id: company, theme, template_type: templateType, message_body: messageBody || null,
      subject_template: edited ? subject : null, body_template: edited ? body : null, recipient,
      custom_variables: customVariables,
      selected_allocation_id: selectedAllocationId,
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
  }, [company, theme, templateType, subject, body, edited, messageBody, recipientKey, customVarsKey, selectedAllocationId, enabled]); // eslint-disable-line react-hooks/exhaustive-deps
  return { preview, busy };
}

export function PreviewFrame({
  preview,
  busy,
  height = '60vh',
  emptyText = 'Choose a template to see the email.',
  customVariables = {},
  onCustomVariableChange,
  selectedAllocationId = null,
  onSelectAllocation,
}) {
  if (!preview) {
    return <div className="rounded-xl border border-dashed border-slate-300 dark:border-slate-700 p-6 text-center text-xs text-slate-500">{busy ? 'Rendering…' : emptyText}</div>;
  }
  if (preview.error) return <div className="rounded-xl border border-rose-300 bg-rose-50 dark:bg-rose-950/40 p-3 text-xs text-rose-600">{preview.error}</div>;

  const hasMissing = preview.unresolved_placeholders && preview.unresolved_placeholders.length > 0;
  const hasSupplied = customVariables && Object.keys(customVariables).length > 0;
  const hasMultipleBeneficiaries = preview.has_multiple_beneficiaries || (preview.sponsorships && preview.sponsorships.length > 1);

  return (
    <div className="rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden bg-white dark:bg-slate-900 shadow-sm flex flex-col">
      <div className="px-3 py-2 text-xs border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-slate-800 dark:text-slate-100 flex items-center justify-between gap-2">
        <span className="min-w-0 truncate"><b>{preview.subject || '(no subject)'}</b> <span className="text-slate-500">→ {preview.recipient_email}</span></span>
        {busy && <span className="text-[10px] text-sky-600 font-semibold shrink-0">updating…</span>}
      </div>

      {/* Multiple Beneficiaries Detected */}
      {hasMultipleBeneficiaries && (
        <div className="p-3 bg-violet-50/90 dark:bg-violet-950/40 border-b border-violet-200 dark:border-violet-800 flex flex-col gap-2">
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <div className="flex items-center gap-1.5 text-xs font-bold text-violet-950 dark:text-violet-200">
              <Users className="w-4 h-4 text-violet-600 shrink-0" />
              <span>Multiple Beneficiaries Detected ({preview.sponsorships.length} sponsorships)</span>
            </div>
            <span className="text-[11px] text-violet-700 dark:text-violet-300 font-medium">
              Choose a specific beneficiary to feature, or feature all combined:
            </span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            <button
              type="button"
              onClick={() => onSelectAllocation?.(null)}
              className={`px-2.5 py-1.5 rounded-lg text-xs font-semibold border transition-all ${
                !selectedAllocationId
                  ? 'bg-violet-600 text-white border-violet-600 shadow-xs'
                  : 'bg-white dark:bg-slate-900 text-slate-700 dark:text-slate-300 border-slate-200 dark:border-slate-700 hover:border-violet-400'
              }`}
            >
              All Beneficiaries (Combined)
            </button>
            {preview.sponsorships.map(s => {
              const active = selectedAllocationId === s.id;
              return (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => onSelectAllocation?.(s.id)}
                  className={`px-2.5 py-1.5 rounded-lg text-xs border flex items-center gap-1.5 transition-all ${
                    active
                      ? 'bg-violet-600 text-white border-violet-600 font-bold shadow-xs'
                      : 'bg-white dark:bg-slate-900 text-slate-700 dark:text-slate-300 border-slate-200 dark:border-slate-700 hover:border-violet-400'
                  }`}
                >
                  <span>{s.beneficiary_name}</span>
                  {s.project_code && (
                    <span className={`text-[10px] px-1 py-0.5 rounded font-mono ${active ? 'bg-violet-700 text-white' : 'bg-slate-100 dark:bg-slate-800 text-slate-500'}`}>
                      {s.project_code}
                    </span>
                  )}
                  {s.sponsorship_type && <span className="text-[10px] opacity-75">({s.sponsorship_type})</span>}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Missing Variables Prompts */}
      {hasMissing && (
        <div className="p-3 bg-amber-50 dark:bg-amber-950/40 border-b border-amber-200 dark:border-amber-900 flex flex-col gap-2">
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <div className="flex items-center gap-1.5 text-xs font-bold text-amber-900 dark:text-amber-200">
              <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0" />
              <span>Missing template variable{preview.unresolved_placeholders.length > 1 ? 's' : ''}: enter below so recipient is not skipped</span>
            </div>
            <span className="text-[11px] text-amber-700 dark:text-amber-400">Required to send</span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {preview.unresolved_placeholders.map(p => (
              <div key={p} className="flex flex-col gap-1 bg-white dark:bg-slate-950 p-2 rounded-lg border border-amber-300 dark:border-amber-800">
                <div className="flex items-center justify-between text-[11px]">
                  <span className="font-mono font-bold text-amber-900 dark:text-amber-300">{`{${p}}`}</span>
                  {p.toLowerCase().includes('days') && (
                    <div className="flex gap-1 text-[10px]">
                      {['7 days', '14 days', '30 days'].map(opt => (
                        <button
                          key={opt}
                          type="button"
                          onClick={() => onCustomVariableChange?.(p, opt)}
                          className="px-1.5 py-0.5 rounded bg-amber-100 hover:bg-amber-200 dark:bg-amber-900/60 text-amber-800 dark:text-amber-200 font-semibold"
                        >
                          {opt}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                <input
                  type="text"
                  placeholder={`Enter value for {${p}}...`}
                  value={customVariables?.[p] || ''}
                  onChange={e => onCustomVariableChange?.(p, e.target.value)}
                  className="w-full text-xs px-2.5 py-1.5 rounded border border-amber-300 dark:border-amber-700 bg-white dark:bg-slate-900 text-slate-800 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-amber-500/50"
                />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Supplied Variables Indicator */}
      {!hasMissing && hasSupplied && (
        <div className="px-3 py-1.5 bg-emerald-50 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300 border-b border-emerald-200 dark:border-emerald-800 flex items-center justify-between text-xs">
          <span className="flex items-center gap-1.5 font-medium">
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
            Variables supplied by sender: {Object.entries(customVariables).filter(([_, v]) => v).map(([k, v]) => `${k}="${v}"`).join(', ')} — recipient ready to send!
          </span>
          <button
            type="button"
            onClick={() => {
              Object.keys(customVariables).forEach(k => onCustomVariableChange?.(k, ''));
            }}
            className="text-[11px] underline font-medium hover:text-emerald-950 dark:hover:text-emerald-100"
          >
            Clear
          </button>
        </div>
      )}

      <iframe title="Email preview" sandbox="" srcDoc={preview.body_html} className="w-full bg-white flex-1 min-h-0" style={{ height }} />
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
