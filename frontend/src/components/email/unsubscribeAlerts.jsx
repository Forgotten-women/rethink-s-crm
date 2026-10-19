import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { UserMinus, X } from 'lucide-react';
import { API_BASE_URL } from '../../config';

// Tells admins when someone presses Unsubscribe in one of our emails: a count on the Email item in the sidebar
// and a toast when a new one comes in (checked every minute). The list lives in Email > Unsubscribed.
export const OPEN_UNSUBSCRIBES_EVENT = 'crm:open-unsubscribes';
export const UNSUBSCRIBES_SEEN_EVENT = 'crm:unsubscribes-seen';
let pendingOpen = false;
export const takePendingOpen = () => { const p = pendingOpen; pendingOpen = false; return p; };

export function useUnsubscribeAlerts(company) {
  const [state, setState] = useState({ unseen: 0, latest: [] });
  const [toast, setToast] = useState(null);
  const known = useRef(null);
  useEffect(() => {
    known.current = null;
    setState({ unseen: 0, latest: [] });
    if (!company || company === 'all') return undefined;
    let alive = true;
    const load = () => fetch(`${API_BASE_URL}/api/email/unsubscribes/unseen?company_id=${encodeURIComponent(company)}`)
      .then(r => (r.ok ? r.json() : null))
      .then(d => {
        if (!alive || !d) return;
        const keys = (d.latest || []).map(x => `${x.email}|${x.unsubscribed_at}`);
        if (known.current) {
          const fresh = (d.latest || []).filter((x, i) => !known.current.has(keys[i]));
          if (fresh.length) setToast({ people: fresh, at: Date.now() });
        }
        known.current = new Set(keys);
        setState({ unseen: d.unseen || 0, latest: d.latest || [] });
      })
      .catch(() => {});
    load();
    const t = setInterval(load, 60000);
    const onSeen = () => load();
    window.addEventListener(UNSUBSCRIBES_SEEN_EVENT, onSeen);
    return () => { alive = false; clearInterval(t); window.removeEventListener(UNSUBSCRIBES_SEEN_EVENT, onSeen); };
  }, [company]);
  return { ...state, toast, clearToast: () => setToast(null) };
}

export function UnsubscribeToast({ toast, onClose, onOpen }) {
  useEffect(() => {
    if (!toast) return undefined;
    const t = setTimeout(onClose, 15000);
    return () => clearTimeout(t);
  }, [toast]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!toast) return null;
  const first = toast.people[0];
  const who = first.name || first.email;
  const more = toast.people.length - 1;
  return createPortal(
    <div role="status" className="fixed bottom-4 right-4 z-[120] w-[min(22rem,calc(100vw-2rem))] rounded-xl border border-amber-300 dark:border-amber-800 bg-white dark:bg-slate-900 shadow-lg p-3 flex gap-3 items-start">
      <div className="p-2 rounded-lg bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300 shrink-0"><UserMinus className="w-4 h-4" /></div>
      <button type="button" onClick={() => { pendingOpen = true; onOpen?.(); window.dispatchEvent(new Event(OPEN_UNSUBSCRIBES_EVENT)); onClose(); }} className="min-w-0 flex-1 text-left">
        <div className="text-sm font-bold text-slate-900 dark:text-white truncate">{who} unsubscribed{more > 0 ? ` (+${more} more)` : ''}</div>
        <div className="text-xs text-slate-500 dark:text-slate-400">Marketing consent set to No. Click to see who.</div>
      </button>
      <button type="button" onClick={onClose} aria-label="Dismiss" className="p-1 rounded text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800"><X className="w-4 h-4" /></button>
    </div>,
    document.body,
  );
}
