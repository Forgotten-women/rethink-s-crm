import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { CheckCircle2, History, LayoutTemplate, Mail, Send, X } from 'lucide-react';
import { CARD, FIELD, LABEL, PreviewFrame, VariableChips, insertAtCursor, post, useLivePreview, useTemplates } from './emailUi';
import EmailThread from './EmailThread';
import DesignModal from './builder/DesignModal';

/**
 * Write to ONE person (from their donor panel or a sponsorship): their address is fixed, the message is written
 * for them with a live preview, and their earlier emails and replies are shown alongside. Goes from the
 * charity's own mailbox and is recorded in their email thread.
 */
export default function SingleEmailComposer({ company, recipient, onClose, onSent }) {
  const { themes, templates, selected } = useTemplates(company);
  const [theme, setTheme] = useState('');
  const [templateType, setTemplateType] = useState('general_custom');
  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  const [edited, setEdited] = useState(false);
  const [messageBody, setMessageBody] = useState('');
  const [showHtml, setShowHtml] = useState(false); // the builder window
  const [bodyDoc, setBodyDoc] = useState(null);
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [threadKey, setThreadKey] = useState(0);
  const lastField = useRef({ name: 'message', el: null });

  useEffect(() => { if (!theme && selected) setTheme(selected); }, [selected, theme]);
  const themeTemplates = useMemo(() => templates.filter(t => (t.charity_theme || t.company_id) === theme), [templates, theme]);
  useEffect(() => {
    if (edited) return;
    const t = themeTemplates.find(x => x.template_type === templateType) || themeTemplates.find(x => x.template_type === 'general_custom') || themeTemplates[0];
    if (t && t.template_type !== templateType) { setTemplateType(t.template_type); return; }
    setSubject(t?.subject || ''); setBody(t?.body_html || ''); setBodyDoc(t?.builder_json || null);
  }, [themeTemplates, templateType, edited]);

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') { e.stopPropagation(); onClose(); } };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [onClose]);

  const who = useMemo(() => ({ donor_id: recipient.donor_id || recipient.email, email: recipient.email, name: recipient.name || '' }), [recipient]);
  const { preview, busy } = useLivePreview({ company, theme, templateType, subject, body, edited, messageBody, recipient: who });

  const insert = (text) => {
    const f = lastField.current;
    if (f.name === 'subject') { setSubject(v => insertAtCursor(f.el, v, text)); setEdited(true); }
    else if (f.name === 'body') { setBody(v => insertAtCursor(f.el, v, text)); setEdited(true); }
    else setMessageBody(v => insertAtCursor(f.el, v, text));
  };
  const track = (name) => (e) => { lastField.current = { name, el: e.target }; };

  const send = async () => {
    setError(''); setResult(null);
    if (preview?.unresolved_placeholders?.length) { setError(`The template needs ${preview.unresolved_placeholders.join(', ')} for this person.`); return; }
    if (!window.confirm(`Send this email to ${who.name || who.email}?`)) return;
    setSending(true);
    try {
      const d = await post('/api/tracker/direct-email/send', {
        company_id: company, theme, template_type: templateType, message_body: messageBody || null,
        subject_template: edited ? subject : null, body_template: edited ? body : null,
        recipients: [who], dry_run: false, kind: 'single',
      });
      const r = d.results?.[0] || {};
      setResult(r);
      setThreadKey(k => k + 1);
      if (r.status === 'sent') onSent?.();
    } catch (e) { setError(e.message); } finally { setSending(false); }
  };

  return createPortal(
    <div className="fixed inset-0 z-[85] flex items-center justify-center p-2 sm:p-5" role="dialog" aria-modal="true" aria-label={`Email ${who.name || who.email}`}>
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-7xl h-[94vh] flex flex-col rounded-2xl shadow-2xl overflow-hidden border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900">
        <div className="px-5 py-3 border-b border-slate-200 dark:border-slate-700 flex items-center justify-between gap-3 bg-gradient-to-br from-sky-500/10 to-transparent">
          <div className="min-w-0">
            <h2 className="text-base font-black flex items-center gap-2 text-slate-900 dark:text-white"><Mail className="w-5 h-5 text-sky-500" /> Email {who.name || who.email}</h2>
            <div className="text-xs text-slate-500 mt-0.5">To <b className="text-slate-700 dark:text-slate-200">{who.email}</b> · from {company === 'iqra' ? 'Iqra' : 'Rethink'}'s mailbox</div>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="w-8 h-8 rounded-full flex items-center justify-center text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"><X className="w-4 h-4" /></button>
        </div>

        <div className="flex-1 min-h-0 grid grid-cols-1 xl:grid-cols-12 gap-4 p-4 overflow-y-auto xl:overflow-hidden">
          {/* Write */}
          <div className="xl:col-span-4 flex flex-col gap-3 xl:overflow-y-auto pr-1">
            <div className={`${CARD} grid grid-cols-2 gap-2`}>
              <label className={LABEL}>Branding
                <select value={theme} onChange={e => { setTheme(e.target.value); setEdited(false); }} className={`${FIELD} px-2 py-1.5 text-sm normal-case font-normal tracking-normal`}>
                  {themes.map(t => <option key={t.id || t} value={t.id || t}>{t.label || t.name || t.id || t}</option>)}
                </select>
              </label>
              <label className={LABEL}>Start from
                <select value={templateType} onChange={e => { setTemplateType(e.target.value); setEdited(false); }} className={`${FIELD} px-2 py-1.5 text-sm normal-case font-normal tracking-normal`}>
                  {themeTemplates.map(t => <option key={t.template_type} value={t.template_type}>{t.template_type.replace(/_/g, ' ')}</option>)}
                </select>
              </label>
            </div>
            <label className={LABEL}>Subject
              <input value={subject} onFocus={track('subject')} onClick={track('subject')} onChange={e => { setSubject(e.target.value); setEdited(true); track('subject')(e); }}
                className={`${FIELD} px-2.5 py-2 text-sm normal-case font-normal tracking-normal`} />
            </label>
            <label className={LABEL}>Your message to {who.name ? who.name.split(' ')[0] : 'them'}
              <textarea value={messageBody} onFocus={track('message')} onClick={track('message')} onChange={e => { setMessageBody(e.target.value); track('message')(e); }} rows={9}
                placeholder="Write your message here. It appears where the template has {message_body}."
                className={`${FIELD} px-2.5 py-2 text-sm normal-case font-normal tracking-normal leading-relaxed`} />
            </label>
            <button type="button" onClick={() => setShowHtml(true)} className="self-start flex items-center gap-1 text-xs font-semibold text-sky-600 hover:text-sky-500">
              <LayoutTemplate className="w-3.5 h-3.5" /> Customise the design{edited ? ' (changed)' : ''}
            </button>
            {showHtml && <DesignModal html={body} doc={bodyDoc} title="Customise this email" onClose={() => setShowHtml(false)} onApply={(d, h) => { setBodyDoc(d); setBody(h); setEdited(true); }} />}
            <div className={CARD}>
              <div className="text-[11px] font-bold uppercase tracking-wider text-slate-600 dark:text-slate-300 mb-1.5">Insert their details</div>
              <VariableChips onInsert={insert} />
            </div>
            {error && <div className="text-xs rounded-lg px-3 py-2 bg-rose-50 text-rose-700 border border-rose-200 dark:bg-rose-950/40 dark:text-rose-300 dark:border-rose-900">{error}</div>}
            {result && (
              <div className={`text-xs rounded-lg px-3 py-2 border flex items-center gap-1.5 ${result.status === 'sent' ? 'bg-emerald-50 text-emerald-800 border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-300 dark:border-emerald-900' : 'bg-amber-50 text-amber-800 border-amber-200'}`}>
                {result.status === 'sent' ? <><CheckCircle2 className="w-4 h-4" /> Sent to {who.email}. It's in their thread.</> : <>{result.status}: {result.detail}</>}
              </div>
            )}
          </div>

          {/* Live preview */}
          <div className="xl:col-span-5 flex flex-col gap-2 xl:overflow-y-auto">
            <div className="text-[11px] font-bold uppercase tracking-wider text-slate-600 dark:text-slate-300">Live preview - exactly what {who.name ? who.name.split(' ')[0] : 'they'} will get</div>
            <PreviewFrame preview={preview} busy={busy} height="62vh" />
          </div>

          {/* Their thread */}
          <div className="xl:col-span-3 flex flex-col gap-2 xl:overflow-y-auto">
            <div className="text-[11px] font-bold uppercase tracking-wider text-slate-600 dark:text-slate-300 flex items-center gap-1"><History className="w-3.5 h-3.5" /> Their emails & replies</div>
            <EmailThread company={company} email={who.email} reloadKey={threadKey} compact />
          </div>
        </div>

        <div className="px-5 py-3 border-t border-slate-200 dark:border-slate-700 flex items-center justify-end gap-2">
          <button type="button" onClick={onClose} className="px-3 py-2 text-sm rounded-lg font-semibold text-slate-600 dark:text-slate-300">Close</button>
          <button type="button" onClick={send} disabled={sending || !theme || !preview || !!preview?.error}
            className="px-4 py-2 text-sm rounded-lg font-bold bg-sky-600 hover:bg-sky-500 text-white disabled:opacity-40 flex items-center gap-1.5">
            <Send className="w-4 h-4" /> {sending ? 'Sending…' : `Send to ${who.name ? who.name.split(' ')[0] : who.email}`}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
