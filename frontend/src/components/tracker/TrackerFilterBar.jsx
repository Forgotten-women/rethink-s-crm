import React, { useEffect, useState } from 'react';
import { Search, X, SlidersHorizontal, Mail, ChevronDown, ChevronUp } from 'lucide-react';

/**
 * Filter bar shared by tracker tabs. Supports primary fields, communications section, and toggle chips.
 *   text fields: { key, label, placeholder, section? }
 *   select fields: { key, label, type: 'select', options, section? }
 *   daterange: { key, label, type: 'daterange', section? }
 *   toggle: { key, label, type: 'toggle' }
 */
export default function TrackerFilterBar({ fields, values, onChange, resultCount }) {
  const [local, setLocal] = useState(values);
  const [showComms, setShowComms] = useState(true);

  useEffect(() => setLocal(values), [values]);

  // Debounce free-text inputs so typing does not hammer the API
  useEffect(() => {
    const textKeys = fields.filter(f => !f.type || f.type === 'text').map(f => f.key);
    if (!textKeys.some(k => (local[k] || '') !== (values[k] || ''))) return undefined;
    const t = setTimeout(() => onChange({ ...values, ...Object.fromEntries(textKeys.map(k => [k, local[k] || ''])) }), 350);
    return () => clearTimeout(t);
  }, [local]);

  const set = (k, v) => onChange({ ...values, [k]: v });
  const active = Object.entries(values).filter(([, v]) => v !== '' && v !== undefined && v !== null && v !== 'all' && v !== false);

  const commsFields = fields.filter(f => f.section === 'comms');
  const toggleFields = fields.filter(f => f.type === 'toggle');
  const generalFields = fields.filter(f => f.type !== 'toggle' && f.section !== 'comms');

  const activeCommsCount = commsFields.filter(f => {
    if (f.type === 'daterange') {
      return Boolean(values[`${f.key}_from`] || values[`${f.key}_to`]);
    }
    const val = values[f.key];
    return val !== '' && val !== undefined && val !== null && val !== 'all' && val !== false;
  }).length;

  // Auto-expand comms tray if any comms filter is actively set
  useEffect(() => {
    if (activeCommsCount > 0) {
      setShowComms(true);
    }
  }, [activeCommsCount]);

  const renderField = (f) => {
    if (f.type === 'select') {
      return (
        <label key={f.key} className="flex flex-col gap-0.5">
          <span className="text-[10px] font-semibold text-slate-500 dark:text-slate-400">{f.label}</span>
          <select
            value={values[f.key] ?? 'all'}
            onChange={e => set(f.key, e.target.value)}
            className="px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-xs text-slate-800 dark:text-slate-200 font-medium min-w-[7.5rem] focus:outline-none focus:ring-1 focus:ring-blue-500 cursor-pointer"
          >
            {f.options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </label>
      );
    }
    if (f.type === 'daterange') {
      return (
        <label key={f.key} className="flex flex-col gap-0.5">
          <span className="text-[10px] font-semibold text-slate-500 dark:text-slate-400">{f.label}</span>
          <span className="flex items-center gap-1">
            <input
              type="date"
              value={values[`${f.key}_from`] || ''}
              onChange={e => set(`${f.key}_from`, e.target.value)}
              className="px-2 py-1 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-xs text-slate-800 dark:text-slate-200 font-mono"
            />
            <span className="text-slate-400">→</span>
            <input
              type="date"
              value={values[`${f.key}_to`] || ''}
              onChange={e => set(`${f.key}_to`, e.target.value)}
              className="px-2 py-1 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-xs text-slate-800 dark:text-slate-200 font-mono"
            />
          </span>
        </label>
      );
    }
    if (f.type === 'toggle') {
      const isChecked = Boolean(values[f.key]);
      return (
        <label
          key={f.key}
          className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border cursor-pointer select-none transition-all ${
            isChecked
              ? 'border-blue-500 bg-blue-50 dark:bg-blue-950/60 text-blue-700 dark:text-blue-300 font-bold shadow-xs'
              : 'border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-750 font-medium'
          }`}
        >
          <input
            type="checkbox"
            checked={isChecked}
            onChange={e => set(f.key, e.target.checked || undefined)}
            className="rounded border-slate-300 text-blue-600 focus:ring-blue-500"
          />
          <span className="text-xs">{f.label}</span>
        </label>
      );
    }
    return (
      <label key={f.key} className="flex flex-col gap-0.5">
        <span className="text-[10px] font-semibold text-slate-500 dark:text-slate-400">{f.label}</span>
        <span className="relative">
          <Search className="w-3.5 h-3.5 absolute left-2.5 top-2 text-slate-400" />
          <input
            value={local[f.key] || ''}
            placeholder={f.placeholder}
            onChange={e => setLocal({ ...local, [f.key]: e.target.value })}
            className="pl-8 pr-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-xs text-slate-800 dark:text-slate-200 placeholder-slate-400 w-44 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </span>
      </label>
    );
  };

  return (
    <div className="flex flex-col gap-3 p-3.5 rounded-xl border border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 text-xs shadow-xs">
      {/* 1. General Primary Filters Row */}
      <div className="flex flex-wrap items-end gap-2.5">
        <div className="flex items-center gap-1.5 mb-2 mr-1 text-slate-400">
          <SlidersHorizontal className="w-4 h-4 text-slate-500 dark:text-slate-400" />
          <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400">Filters:</span>
        </div>
        {generalFields.map(renderField)}
      </div>

      {/* 2. Communication & Email Filters Row (if present) */}
      {commsFields.length > 0 && (
        <div className="pt-2.5 border-t border-slate-100 dark:border-slate-800/80">
          <div className="flex items-center justify-between mb-2">
            <button
              type="button"
              onClick={() => setShowComms(!showComms)}
              className="flex items-center gap-1.5 text-xs font-bold text-slate-600 dark:text-slate-300 hover:text-blue-600 dark:hover:text-blue-400 transition-colors"
            >
              <Mail className="w-3.5 h-3.5 text-blue-500" />
              <span>Outreach & Email Lifecycle Filters</span>
              {activeCommsCount > 0 && (
                <span className="px-1.5 py-0.2 rounded-full text-[10px] font-bold bg-blue-100 dark:bg-blue-900/60 text-blue-600 dark:text-blue-300">
                  {activeCommsCount} active
                </span>
              )}
              {showComms ? <ChevronUp className="w-3.5 h-3.5 text-slate-400" /> : <ChevronDown className="w-3.5 h-3.5 text-slate-400" />}
            </button>
          </div>

          {showComms && (
            <div className="flex flex-wrap items-end gap-2.5 p-2.5 rounded-lg bg-slate-50/70 dark:bg-slate-800/40 border border-slate-100 dark:border-slate-800 animate-in fade-in duration-150">
              {commsFields.map(renderField)}
            </div>
          )}
        </div>
      )}

      {/* 3. Bottom Row: Quick Toggles, Clear Button, Result Count */}
      <div className="flex flex-wrap items-center justify-between gap-3 pt-2.5 border-t border-slate-100 dark:border-slate-800">
        <div className="flex flex-wrap items-center gap-2">
          {toggleFields.map(renderField)}

          {active.length > 0 && (
            <button
              type="button"
              onClick={() => onChange({})}
              className="px-2.5 py-1.5 rounded-lg text-slate-500 hover:text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950/40 font-semibold flex items-center gap-1 text-xs transition-colors"
            >
              <X className="w-3.5 h-3.5" /> Clear all ({active.length})
            </button>
          )}
        </div>

        {resultCount !== undefined && (
          <span className="text-xs text-slate-500 dark:text-slate-400 font-bold ml-auto">
            {resultCount} {resultCount === 1 ? 'allocation result' : 'allocation results'}
          </span>
        )}
      </div>
    </div>
  );
}
