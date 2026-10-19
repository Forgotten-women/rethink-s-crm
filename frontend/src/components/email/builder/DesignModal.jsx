import React, { useState } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import EmailBuilder from './EmailBuilder';
import { VARIABLES } from '../emailUi';

const VARS = VARIABLES.map(([k, label]) => ({ tag: `{${k}}`, label }));

/** The email builder in a full-screen window, for changing the design of one send (bulk or single email). */
export default function DesignModal({ html, doc, onApply, onClose, title = 'Customise this email' }) {
  const [draft, setDraft] = useState(null);
  return createPortal(
    <div className="fixed inset-0 z-[95] flex items-stretch justify-center bg-black/50 p-2 md:p-4" role="dialog" aria-modal="true" aria-label={title}>
      <div className="w-full max-w-7xl bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-700 flex flex-col overflow-hidden">
        <div className="flex items-center justify-between gap-2 px-4 py-3 border-b border-slate-200 dark:border-slate-700">
          <div>
            <div className="text-sm font-black text-slate-900 dark:text-white">{title}</div>
            <div className="text-[11px] text-slate-500">Changes apply to this send only - the saved template stays as it is.</div>
          </div>
          <div className="flex items-center gap-2">
            <button type="button" onClick={onClose} className="px-3 py-1.5 rounded-lg text-xs font-bold text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800">Cancel</button>
            <button type="button" disabled={!draft} onClick={() => { onApply(draft.doc, draft.html); onClose(); }}
              className="px-4 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-bold disabled:opacity-50">Use this design</button>
            <button type="button" onClick={onClose} aria-label="Close" className="p-1.5 rounded-lg text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"><X className="w-4 h-4" /></button>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto p-3">
          <EmailBuilder html={html} doc={doc} variables={VARS} onChange={(d, h) => setDraft({ doc: d, html: h })} />
        </div>
      </div>
    </div>,
    document.body,
  );
}
