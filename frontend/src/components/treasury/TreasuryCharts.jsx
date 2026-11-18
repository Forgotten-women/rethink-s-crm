import React, { useMemo, useRef, useState } from 'react';
import { Table2, BarChart3 } from 'lucide-react';
import { formatMoney } from './treasuryUtils';

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
export const monthLabel = (m) => {
  const [y, mm] = String(m || '').split('-');
  return mm ? `${MONTH_NAMES[Number(mm) - 1]} ${y.slice(2)}` : m;
};

function niceMax(v) {
  if (v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  const n = v / p;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * p;
}

/** Small toggle between the chart and the same numbers as a table (accessibility: never chart-only). */
export function ChartTableToggle({ showTable, onChange }) {
  return (
    <div className="flex rounded-lg border border-slate-700/50 p-0.5" role="group" aria-label="Chart or table">
      <button type="button" onClick={() => onChange(false)} title="Chart"
        className={`p-1 rounded-md ${!showTable ? 'bg-blue-600 keep-white' : 'text-slate-400'}`}><BarChart3 className="w-3.5 h-3.5" /></button>
      <button type="button" onClick={() => onChange(true)} title="Table"
        className={`p-1 rounded-md ${showTable ? 'bg-blue-600 keep-white' : 'text-slate-400'}`}><Table2 className="w-3.5 h-3.5" /></button>
    </div>
  );
}

/**
 * Grouped bars per month: money in (slot 1) vs money out (slot 2), one shared axis.
 * Hover any month for the exact figures and the net.
 */
export function FlowChart({ data = [], currency = 'USD', height = 220, inLabel = 'Income', outLabel = 'Spending' }) {
  const [hover, setHover] = useState(null);
  const [showTable, setShowTable] = useState(false);
  const wrap = useRef(null);
  const W = 640;
  const H = height;
  const pad = { l: 56, r: 12, t: 12, b: 28 };
  const max = niceMax(Math.max(1, ...data.flatMap((d) => [d.inc, d.out])));
  const iw = W - pad.l - pad.r;
  const ih = H - pad.t - pad.b;
  const band = data.length ? iw / data.length : iw;
  const bw = Math.max(6, Math.min(26, band * 0.28));
  const y = (v) => pad.t + ih - (v / max) * ih;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * max);

  const bar = (x, v, color) => {
    const top = y(v);
    const h = Math.max(0, pad.t + ih - top);
    const r = Math.min(4, h / 2, bw / 2);
    // rounded data-end, square at the baseline
    return (
      <path d={`M${x},${pad.t + ih} V${top + r} Q${x},${top} ${x + r},${top} H${x + bw - r} Q${x + bw},${top} ${x + bw},${top + r} V${pad.t + ih} Z`}
        fill={color} />
    );
  };

  return (
    <div className="tviz relative" ref={wrap}>
      <div className="flex items-center justify-between mb-2 gap-2">
        <div className="flex items-center gap-4 text-[11px] text-slate-400">
          <span className="flex items-center gap-1.5"><span className="tviz-swatch" style={{ background: 'var(--viz-1)' }} />{inLabel}</span>
          <span className="flex items-center gap-1.5"><span className="tviz-swatch" style={{ background: 'var(--viz-2)' }} />{outLabel}</span>
        </div>
        <ChartTableToggle showTable={showTable} onChange={setShowTable} />
      </div>
      {showTable ? (
        <table className="crm-table text-xs">
          <thead><tr><th>Month</th><th className="text-right">{inLabel}</th><th className="text-right">{outLabel}</th><th className="text-right">Net</th></tr></thead>
          <tbody>
            {data.map((d) => (
              <tr key={d.month}>
                <td>{monthLabel(d.month)}</td>
                <td className="text-right tabular-nums">{formatMoney(d.inc, currency)}</td>
                <td className="text-right tabular-nums">{formatMoney(d.out, currency)}</td>
                <td className="text-right tabular-nums font-semibold">{formatMoney(d.inc - d.out, currency, { signed: true })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height: 'auto' }} role="img"
          aria-label={`${inLabel} and ${outLabel} by month`} onMouseLeave={() => setHover(null)}>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={pad.l} x2={W - pad.r} y1={y(t)} y2={y(t)} stroke={t === 0 ? 'var(--viz-axis)' : 'var(--viz-grid)'} />
              <text x={pad.l - 8} y={y(t) + 3.5} textAnchor="end" fontSize="10" fill="currentColor" className="text-slate-400">
                {formatMoney(t, currency, { compact: true })}
              </text>
            </g>
          ))}
          {data.map((d, i) => {
            const cx = pad.l + band * i + band / 2;
            return (
              <g key={d.month}>
                {hover === i && <rect x={pad.l + band * i + 2} y={pad.t} width={band - 4} height={ih} rx="6" fill="var(--viz-track)" />}
                {bar(cx - bw - 1, d.inc, 'var(--viz-1)')}
                {bar(cx + 1, d.out, 'var(--viz-2)')}
                <text x={cx} y={H - 9} textAnchor="middle" fontSize="10.5" fill="currentColor" className="text-slate-400">{monthLabel(d.month)}</text>
                <rect x={pad.l + band * i} y={pad.t} width={band} height={ih + 20} fill="transparent"
                  onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)} tabIndex={0} />
              </g>
            );
          })}
        </svg>
      )}
      {!showTable && hover !== null && data[hover] && (
        <div className="tviz-tip" style={{
          left: `${Math.min(70, ((pad.l + band * hover + band) / W) * 100)}%`, top: 28,
        }}>
          <div className="font-bold mb-1">{monthLabel(data[hover].month)}</div>
          <div className="flex justify-between gap-3"><span className="flex items-center gap-1.5"><span className="tviz-swatch" style={{ background: 'var(--viz-1)' }} />{inLabel}</span><span className="tabular-nums">{formatMoney(data[hover].inc, currency)}</span></div>
          <div className="flex justify-between gap-3"><span className="flex items-center gap-1.5"><span className="tviz-swatch" style={{ background: 'var(--viz-2)' }} />{outLabel}</span><span className="tabular-nums">{formatMoney(data[hover].out, currency)}</span></div>
          <div className="flex justify-between gap-3 mt-1 pt-1 border-t border-slate-700/40 font-semibold"><span>Net</span><span className="tabular-nums">{formatMoney(data[hover].inc - data[hover].out, currency, { signed: true })}</span></div>
          {data[hover].note && <div className="text-[10px] text-slate-400 mt-1">{data[hover].note}</div>}
        </div>
      )}
    </div>
  );
}

/**
 * Horizontal bars for a ranked list (cash by region, fund balance by country). Positive values in the
 * diverging "pos" hue, negatives in "neg" from a shared zero line; the value is printed beside every bar.
 */
export function BarList({ rows = [], currency = 'USD', onSelect, selected, maxRows = 12, valueKey = 'value' }) {
  const [hover, setHover] = useState(null);
  const shown = rows.slice(0, maxRows);
  const maxPos = Math.max(0, ...shown.map((r) => r[valueKey]));
  const maxNeg = Math.max(0, ...shown.map((r) => -r[valueKey]));
  const span = maxPos + maxNeg || 1;
  const zero = (maxNeg / span) * 100;
  return (
    <div className="tviz space-y-1.5" role="list">
      {shown.map((r, i) => {
        const v = r[valueKey];
        const w = (Math.abs(v) / span) * 100;
        const neg = v < 0;
        const active = selected && selected === r.key;
        return (
          <button type="button" key={r.key} role="listitem" onClick={() => onSelect && onSelect(r.key)}
            onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}
            className={`w-full text-left grid grid-cols-[minmax(0,9rem)_1fr_auto] items-center gap-3 px-2 py-1 rounded-lg transition-colors ${
              active ? 'bg-blue-500/10 ring-1 ring-blue-500/40' : hover === i ? 'bg-slate-500/5' : ''} ${onSelect ? 'cursor-pointer' : 'cursor-default'}`}
            title={r.hint || ''}>
            <span className="text-xs font-semibold truncate">{r.label}</span>
            <span className="relative h-3.5 rounded" style={{ background: 'var(--viz-track)' }}>
              {maxNeg > 0 && <span className="absolute top-[-2px] bottom-[-2px] w-px" style={{ left: `${zero}%`, background: 'var(--viz-axis)' }} />}
              <span className="absolute top-0 bottom-0" style={{
                left: neg ? `${zero - w}%` : `${zero}%`, width: `${Math.max(w, 0.4)}%`,
                background: neg ? 'var(--viz-neg)' : 'var(--viz-pos)',
                borderRadius: neg ? '4px 0 0 4px' : '0 4px 4px 0',
              }} />
            </span>
            <span className="text-xs tabular-nums font-semibold text-right min-w-[5.5rem]">
              {formatMoney(v, currency, { compact: true })}
              {r.sub && <span className="block text-[10px] font-normal text-slate-400">{r.sub}</span>}
            </span>
          </button>
        );
      })}
      {rows.length > maxRows && <div className="text-[11px] text-slate-400 pl-2">+{rows.length - maxRows} more</div>}
    </div>
  );
}

/** Tiny inline monthly spark (in vs out) for a pot or an account; no axis, hover via title. */
export function MiniFlow({ months = {}, currency = 'USD' }) {
  const data = useMemo(() => Object.entries(months).sort(([a], [b]) => a.localeCompare(b))
    .map(([m, v]) => ({ m, inc: Number(v.inc || v.inflow || 0), out: Number(v.exp || v.outflow || 0) })), [months]);
  if (!data.length) return null;
  const max = Math.max(1, ...data.flatMap((d) => [d.inc, d.out]));
  return (
    <div className="tviz flex items-end gap-2 h-14" aria-label="Monthly in and out">
      {data.map((d) => (
        <div key={d.m} className="flex flex-col items-center gap-1" title={`${monthLabel(d.m)}: in ${formatMoney(d.inc, currency)} · out ${formatMoney(d.out, currency)}`}>
          <div className="flex items-end gap-[2px] h-10">
            <span style={{ height: `${Math.max(2, (d.inc / max) * 40)}px`, width: 7, background: 'var(--viz-1)', borderRadius: '3px 3px 0 0' }} />
            <span style={{ height: `${Math.max(2, (d.out / max) * 40)}px`, width: 7, background: 'var(--viz-2)', borderRadius: '3px 3px 0 0' }} />
          </div>
          <span className="text-[9px] text-slate-400">{monthLabel(d.m).split(' ')[0]}</span>
        </div>
      ))}
    </div>
  );
}
