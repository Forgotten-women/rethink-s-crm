import React from 'react';
import { Globe, ArrowDownLeft, ArrowUpRight, ArrowRight, AlertTriangle } from 'lucide-react';
import { CountryFlag } from './CountryFlag';
import { formatMoney } from './treasuryUtils';

/**
 * Modern, clean, financial fund card component for Treasury Pots.
 * Follows enterprise fintech aesthetic (Stripe / Mercury style):
 * - Clear visual hierarchy: Available Net > Fund Name > Zakat/Non-Zakat > Code/Location > Flows > Details
 * - Refined spacing, subtle elevation, and responsive typography
 * - Accessible contrast in both light and dark themes
 */
export function PotCard({ pot: p, disp = 'USD', onClick }) {
  const isDeficit = (p.current_balance_usd || p.display_balance || 0) < -0.01;
  const isZakat = String(p.pool || '').toLowerCase() === 'zakat';
  const isUnallocated = !p.country || String(p.country).trim().toLowerCase() === 'unallocated';

  const incVal = Number(p.display_income || 0);
  const expVal = Number(p.display_expense || 0);

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onClick && onClick();
        }
      }}
      className={`group relative flex flex-col justify-between h-full rounded-2xl bg-white dark:bg-slate-900/90 border border-slate-200/80 dark:border-slate-800 p-5 shadow-xs hover:shadow-lg hover:-translate-y-0.5 hover:border-indigo-400/50 dark:hover:border-indigo-500/40 transition-all duration-200 cursor-pointer overflow-hidden text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${
        isDeficit ? 'ring-1 ring-rose-500/20' : ''
      }`}
    >
      {/* Subtle Vertical Accent Indicator */}
      <div
        className={`absolute left-0 top-3 bottom-3 w-1 rounded-r-full transition-colors ${
          isDeficit
            ? 'bg-rose-500'
            : isZakat
            ? 'bg-emerald-500'
            : 'bg-purple-500'
        }`}
        aria-hidden="true"
      />

      <div className="flex flex-col gap-3.5">
        {/* Top Section: Reference Code + Location + Zakat/Non-Zakat Badges */}
        <div className="flex items-start justify-between gap-2">
          {/* Reference Number & Location */}
          <div className="flex items-center gap-2 min-w-0 flex-wrap">
            {p.code ? (
              <span
                className="font-mono text-[11px] font-semibold px-2 py-0.5 rounded-md bg-slate-100 dark:bg-slate-800 text-indigo-600 dark:text-indigo-400 border border-slate-200/70 dark:border-slate-700/70 tracking-tight shrink-0 max-w-[170px] truncate"
                title={`Fund Code: ${p.code}`}
              >
                {p.code}
              </span>
            ) : null}

            <div className="flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400 min-w-0">
              {isUnallocated ? (
                <>
                  <Globe className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                  <span className="font-medium text-slate-400 truncate">Unallocated</span>
                </>
              ) : (
                <>
                  <CountryFlag country={p.country} className="w-4 h-2.5 rounded-xs shrink-0 shadow-2xs" />
                  <span className="font-medium truncate max-w-[130px]" title={p.country}>
                    {p.country}
                  </span>
                </>
              )}
            </div>
          </div>

          {/* Badges: Zakat / Non-Zakat + Office Overhead */}
          <div className="flex items-center gap-1.5 shrink-0">
            {Boolean(p.is_overhead) && (
              <span
                className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold tracking-wider uppercase bg-amber-50 text-amber-700 border border-amber-200/90 dark:bg-amber-950/40 dark:text-amber-300 dark:border-amber-800/80 shadow-2xs"
                title="Office / Overhead Cost"
              >
                Office
              </span>
            )}
            <span
              className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-[10px] font-bold tracking-wider uppercase shadow-2xs ${
                isZakat
                  ? 'bg-emerald-50 text-emerald-700 border border-emerald-200/90 dark:bg-emerald-950/40 dark:text-emerald-300 dark:border-emerald-800/80'
                  : 'bg-purple-50 text-purple-700 border border-purple-200/90 dark:bg-purple-950/40 dark:text-purple-300 dark:border-purple-800/80'
              }`}
            >
              {isZakat ? 'ZAKAT' : 'NON-ZAKAT'}
            </span>
          </div>
        </div>

        {/* Fund Information: Name & Category */}
        <div className="min-w-0">
          <h3
            className="font-bold text-[15px] leading-snug text-slate-900 dark:text-slate-100 group-hover:text-indigo-600 dark:group-hover:text-indigo-400 transition-colors line-clamp-1"
            title={p.name}
          >
            {p.name}
          </h3>
          <p
            className="text-xs text-slate-500 dark:text-slate-400 font-medium truncate mt-0.5"
            title={`${p.portfolio || 'General'} · ${p.program || 'General'}`}
          >
            <span>{p.portfolio || 'General'}</span>
            <span className="mx-1 text-slate-300 dark:text-slate-600">·</span>
            <span>{p.program || 'General'}</span>
          </p>
        </div>

        {/* Dedicated Available Balance Section (Highest Visual Hierarchy) */}
        <div
          className={`p-3.5 rounded-xl border transition-all ${
            isDeficit
              ? 'bg-rose-50/60 dark:bg-rose-950/20 border-rose-200/80 dark:border-rose-900/40'
              : 'bg-slate-50/80 dark:bg-slate-900/50 border-slate-200/70 dark:border-slate-800/70 group-hover:border-slate-300 dark:group-hover:border-slate-700'
          } flex items-center justify-between gap-3`}
        >
          <div className="flex flex-col min-w-0">
            <span className="text-[11px] font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
              Available Net
            </span>
            {isDeficit ? (
              <span className="text-[10px] font-bold text-rose-500 dark:text-rose-400 mt-0.5 flex items-center gap-1">
                <AlertTriangle className="w-3 h-3" />
                Deficit
              </span>
            ) : (
              <span className="text-[10px] font-medium text-slate-400 dark:text-slate-500 mt-0.5">
                Current Fund Net
              </span>
            )}
          </div>

          <div className="text-right shrink-0">
            <div
              className={`text-2xl font-black tabular-nums tracking-tight ${
                isDeficit
                  ? 'text-rose-600 dark:text-rose-400'
                  : 'text-emerald-600 dark:text-emerald-400'
              }`}
            >
              {formatMoney(p.display_balance, disp)}
            </div>
            {disp !== 'USD' && p.current_balance_usd != null && (
              <div className="text-[10px] text-slate-400 tabular-nums">
                ≈ {formatMoney(p.current_balance_usd, 'USD')}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Bottom Section: Income & Expense Summary + Details Action */}
      <div className="pt-3 mt-3 border-t border-slate-100 dark:border-slate-800/80 flex items-center justify-between text-xs tabular-nums gap-2">
        {/* Inbound (Income) */}
        <div
          className="flex items-center gap-1.5 min-w-0"
          title={`Jul–Oct Income: ${formatMoney(p.display_income, disp)}`}
        >
          <span className="w-5 h-5 rounded-md bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 flex items-center justify-center shrink-0">
            <ArrowDownLeft className="w-3.5 h-3.5" />
          </span>
          <span className="text-slate-500 dark:text-slate-400 text-[11px] font-medium">In:</span>
          <span
            className={`font-bold truncate ${
              incVal < 0
                ? 'text-amber-600 dark:text-amber-400'
                : 'text-emerald-600 dark:text-emerald-400'
            }`}
          >
            {incVal < 0 ? '−' : '+'}
            {formatMoney(Math.abs(incVal), disp, { compact: true })}
          </span>
        </div>

        {/* Outbound (Expense / Spend) */}
        <div
          className="flex items-center gap-1.5 min-w-0"
          title={`Jul–Oct Spend & Costs: ${formatMoney(p.display_expense, disp)}`}
        >
          <span className="w-5 h-5 rounded-md bg-rose-500/10 text-rose-600 dark:text-rose-400 flex items-center justify-center shrink-0">
            <ArrowUpRight className="w-3.5 h-3.5" />
          </span>
          <span className="text-slate-500 dark:text-slate-400 text-[11px] font-medium">Out:</span>
          <span className="font-bold text-rose-600 dark:text-rose-400 truncate">
            −{formatMoney(Math.abs(expVal), disp, { compact: true })}
          </span>
        </div>

        {/* Details CTA Link */}
        <div className="shrink-0 ml-auto">
          <span className="text-xs font-semibold text-indigo-600 dark:text-indigo-400 group-hover:text-indigo-700 dark:group-hover:text-indigo-300 flex items-center gap-1 transition-colors">
            Details
            <ArrowRight className="w-3.5 h-3.5 group-hover:translate-x-0.5 transition-transform" />
          </span>
        </div>
      </div>
    </div>
  );
}

export default PotCard;
