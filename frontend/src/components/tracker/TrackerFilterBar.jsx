import React, { useEffect, useState } from 'react';
import { Search, X, SlidersHorizontal } from 'lucide-react';

/**
 * Compact filter bar shared by the tracker tabs. `fields` picks which controls show:
 *   text fields: { key, label, placeholder }               -> free-text (debounced)
 *   select fields: { key, label, type: 'select', options }  -> [{ value, label }]
 *   date range: { key: 'end', label, type: 'daterange' }    -> writes `${key}_from` / `${key}_to`
 *   toggle: { key, label, type: 'toggle' }                  -> true / undefined
 */
export default function TrackerFilterBar({ fields, values, onChange, resultCount }) {
  const [local, setLocal] = useState(values);
  useEffect(() => setLocal(values), [values]);

  // Debounce free-text so typing does not hammer the API.
  useEffect(() => {
    const textKeys = fields.filter(f => !f.type || f.type === 'text').map(f => f.key);
    if (!textKeys.some(k => (local[k] || '') !== (values[k] || ''))) return undefined;
    const t = setTimeout(() => onChange({ ...values, ...Object.fromEntries(textKeys.map(k => [k, local[k] || ''])) }), 350);
    return () => clearTimeout(t);
  }, [local]); // eslint-disable-line react-hooks/exhaustive-deps

  const set = (k, v) => onChange({ ...values, [k]: v });
  const active = Object.entries(values).filter(([, v]) => v !== '' && v !== undefined && v !== null && v !== 'all' && v !== false);

  return (
    <div className="flex flex-col gap-2 p-3 rounded-xl border border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 text-xs">
      <div className="flex flex-wrap items-end gap-2">
        <SlidersHorizontal className="w-4 h-4 text-slate-400 mb-2" />
        {fields.map(f => {
          if (f.type === 'select') {
            return (
              <label key={f.key} className="flex flex-col gap-0.5">
                <span className="text-[10px] font-semibold text-slate-500">{f.label}</span>
                <select value={values[f.key] ?? 'all'} onChange={e => set(f.key, e.target.value)}
                  className="px-2 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 min-w-[7rem]">
                  {f.options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              </label>
            );
          }
          if (f.type === 'daterange') {
            return (
              <label key={f.key} className="flex flex-col gap-0.5">
                <span className="text-[10px] font-semibold text-slate-500">{f.label}</span>
                <span className="flex items-center gap-1">
                  <input type="date" value={values[`${f.key}_from`] || ''} onChange={e => set(`${f.key}_from`, e.target.value)}
                    className="px-2 py-1 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800" />
                  <span className="text-slate-400">→</span>
                  <input type="date" value={values[`${f.key}_to`] || ''} onChange={e => set(`${f.key}_to`, e.target.value)}
                    className="px-2 py-1 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800" />
                </span>
              </label>
            );
          }
          if (f.type === 'toggle') {
            return (
              <label key={f.key} className="flex items-center gap-1.5 px-2 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 cursor-pointer">
                <input type="checkbox" checked={Boolean(values[f.key])} onChange={e => set(f.key, e.target.checked || undefined)} />
                <span className="font-semibold text-slate-600 dark:text-slate-300">{f.label}</span>
              </label>
            );
          }
          return (
            <label key={f.key} className="flex flex-col gap-0.5">
              <span className="text-[10px] font-semibold text-slate-500">{f.label}</span>
              <span className="relative">
                <Search className="w-3 h-3 absolute left-2 top-2 text-slate-400" />
                <input value={local[f.key] || ''} placeholder={f.placeholder} onChange={e => setLocal({ ...local, [f.key]: e.target.value })}
                  className="pl-6 pr-2 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 w-40" />
              </span>
            </label>
          );
        })}
        {active.length > 0 && (
          <button type="button" onClick={() => onChange({})}
            className="mb-0.5 px-2 py-1.5 rounded-lg text-slate-500 hover:text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950/40 font-semibold flex items-center gap-1">
            <X className="w-3 h-3" /> Clear ({active.length})
          </button>
        )}
        {resultCount !== undefined && <span className="ml-auto mb-2 text-slate-500 font-semibold">{resultCount} result{resultCount === 1 ? '' : 's'}</span>}
      </div>
    </div>
  );
}
