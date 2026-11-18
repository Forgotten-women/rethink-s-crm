import React, { useState } from 'react';
import {
  Building2, Shield, Coins, CreditCard, Landmark, ArrowDownLeft, ArrowUpRight,
  MoreHorizontal, ShieldAlert, ArrowRightLeft, PlusCircle, Scale, FileText
} from 'lucide-react';
import { CountryFlag } from './CountryFlag';
import { formatMoney } from './treasuryUtils';

export function AccountCard({
  acc,
  disp,
  canWrite,
  canManage,
  regionTotalUsd,
  onOpenAccount,
  onMoveMoney,
  onRecordEntry,
  onUpdateBalance,
}) {
  const [menuOpen, setMenuOpen] = useState(false);

  // Type metadata with native CRM badge classes & clean icons
  const getTypeMeta = (type) => {
    switch (type) {
      case 'bank':
        return { label: 'Bank Account', icon: Building2, badgeClass: 'badge-cyan' };
      case 'cash_safe':
        return { label: 'Regional Cash Safe', icon: Shield, badgeClass: 'badge-emerald' };
      case 'crypto':
        return { label: 'Crypto Wallet', icon: Coins, badgeClass: 'badge-purple' };
      case 'reserve':
        return { label: 'Emergency Reserve', icon: Landmark, badgeClass: 'badge-amber' };
      case 'platform':
        return { label: 'Platform Clearing', icon: CreditCard, badgeClass: 'badge-pink' };
      default:
        return { label: 'Account', icon: Landmark, badgeClass: 'badge-slate' };
    }
  };

  const tMeta = getTypeMeta(acc.account_type);
  const TypeIcon = tMeta.icon;
  const neg = acc.current_balance_native < -0.01;

  // Clean holder formatting (avoids "Humam (Humam)" duplicate)
  const holderText = acc.holder || 'Finance';
  const supervisorText = acc.supervisor && acc.supervisor.trim().toLowerCase() !== holderText.trim().toLowerCase()
    ? ` · supervisor ${acc.supervisor}`
    : '';

  // Inflow / Outflow Flow Bar calculation
  const inflow = Number(acc.inflow_native || 0);
  const outflow = Number(acc.outflow_native || 0);
  const totalFlow = inflow + outflow;
  const inPct = totalFlow > 0 ? Math.round((inflow / totalFlow) * 100) : 50;
  const outPct = totalFlow > 0 ? 100 - inPct : 50;

  // Amanah / Held calculation
  const hasAmanah = Number(acc.amanah_usd || 0) > 0;
  const totalUsd = Math.max(0, Number(acc.active_usd || 0));

  // Region Share
  const regTotal = Number(regionTotalUsd || 0);
  const regSharePct = regTotal > 0 ? ((totalUsd / regTotal) * 100).toFixed(1) : null;

  return (
    <div className="glass-panel p-4 flex flex-col justify-between gap-3 hover:border-blue-400/50 hover:shadow-md transition-all duration-150 rounded-xl relative group">
      
      {/* Header: Flag + Account Name + Badge + Menu */}
      <div className="flex items-start justify-between gap-2">
        <button
          type="button"
          onClick={() => onOpenAccount(acc)}
          className="text-left min-w-0 flex items-start gap-2.5 focus:outline-none"
        >
          <div className="mt-0.5 shrink-0">
            <CountryFlag country={acc.group_name} className="w-5 h-3.5" />
          </div>
          <div className="min-w-0">
            <div className="font-semibold text-sm text-[var(--text-main)] group-hover:text-blue-600 dark:group-hover:text-blue-400 truncate transition-colors">
              {acc.name}
            </div>
            <div className="text-xs text-[var(--text-sub)] truncate mt-0.5">
              {acc.name_ar && <span dir="rtl" className="font-medium text-[var(--text-muted)] mr-1">{acc.name_ar} ·</span>}
              <span>{holderText}{supervisorText}</span>
            </div>
          </div>
        </button>

        <div className="flex items-center gap-1.5 shrink-0">
          <span className={`badge ${tMeta.badgeClass} text-[10px] uppercase font-semibold flex items-center gap-1`}>
            <TypeIcon className="w-3 h-3" />
            {tMeta.label}
          </span>

          {canWrite && (
            <div className="relative">
              <button
                type="button"
                aria-label={`Actions for ${acc.name}`}
                onClick={() => setMenuOpen(!menuOpen)}
                className="p-1 rounded-md text-[var(--text-sub)] hover:text-[var(--text-main)] hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
              >
                <MoreHorizontal className="w-4 h-4" />
              </button>

              {menuOpen && (
                <div
                  className="absolute right-0 z-30 mt-1 w-48 rounded-xl border shadow-xl text-xs py-1"
                  style={{ background: 'var(--drawer-bg, #ffffff)', borderColor: 'var(--border-glass)' }}
                  onMouseLeave={() => setMenuOpen(false)}
                >
                  <button
                    type="button"
                    className="w-full text-left px-3 py-2 hover:bg-blue-50 dark:hover:bg-blue-900/20 flex items-center gap-2 text-[var(--text-main)]"
                    onClick={() => { setMenuOpen(false); onMoveMoney(acc.id); }}
                  >
                    <ArrowRightLeft className="w-3.5 h-3.5 text-blue-500" /> Move money
                  </button>
                  <button
                    type="button"
                    className="w-full text-left px-3 py-2 hover:bg-blue-50 dark:hover:bg-blue-900/20 flex items-center gap-2 text-[var(--text-main)]"
                    onClick={() => { setMenuOpen(false); onRecordEntry(acc.id); }}
                  >
                    <PlusCircle className="w-3.5 h-3.5 text-emerald-500" /> Record entry
                  </button>
                  {canManage && (
                    <button
                      type="button"
                      className="w-full text-left px-3 py-2 hover:bg-blue-50 dark:hover:bg-blue-900/20 flex items-center gap-2 text-[var(--text-main)]"
                      onClick={() => { setMenuOpen(false); onUpdateBalance(acc); }}
                    >
                      <Scale className="w-3.5 h-3.5 text-amber-500" /> Update balance
                    </button>
                  )}
                  <div className="border-t border-[var(--border-glass)] my-1" />
                  <button
                    type="button"
                    className="w-full text-left px-3 py-2 hover:bg-blue-50 dark:hover:bg-blue-900/20 flex items-center gap-2 text-[var(--text-main)]"
                    onClick={() => { setMenuOpen(false); onOpenAccount(acc); }}
                  >
                    <FileText className="w-3.5 h-3.5 text-slate-500" /> Open ledger
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Main Balance Hero Box */}
      <button
        type="button"
        onClick={() => onOpenAccount(acc)}
        className="text-left p-3.5 rounded-xl border border-[var(--border-glass)] hover:border-blue-400/50 transition-colors w-full focus:outline-none"
        style={{ background: 'var(--bg-card-inner, rgba(0,0,0,0.02))' }}
      >
        <div className="flex items-baseline justify-between gap-2">
          <span className={`text-2xl font-black tracking-tight tabular-nums ${neg ? 'text-rose-600 dark:text-rose-400' : 'text-[var(--text-main)]'}`}>
            {formatMoney(acc.current_balance_native, acc.currency)}
          </span>
          <span className="text-[11px] font-bold px-2 py-0.5 rounded border border-[var(--border-glass)] text-[var(--text-sub)] tracking-wider"
                style={{ background: 'var(--bg-card)' }}>
            {acc.currency}
          </span>
        </div>
        {acc.currency !== disp && (
          <div className="text-xs text-[var(--text-sub)] tabular-nums mt-1 flex items-center gap-1.5 font-medium">
            <span>≈ {formatMoney(acc.active_display, disp)}</span>
            {regSharePct && (
              <span className="text-[10px] px-1.5 py-0.2 rounded bg-slate-200/60 dark:bg-slate-800 text-[var(--text-sub)] font-normal">
                {regSharePct}% of {acc.group_name}
              </span>
            )}
          </div>
        )}
      </button>

      {/* Money Held for Others (Amanah) Callout */}
      {hasAmanah && (
        <div className="px-3 py-2 rounded-lg bg-amber-500/10 border border-amber-500/25 flex items-center justify-between text-xs">
          <span className="flex items-center gap-1.5 text-amber-700 dark:text-amber-400 font-medium">
            <ShieldAlert className="w-3.5 h-3.5 text-amber-500 shrink-0" />
            <span>Includes money held for others</span>
          </span>
          <strong className="tabular-nums text-amber-800 dark:text-amber-300 font-bold">
            {formatMoney(acc.amanah_usd, 'USD')}
          </strong>
        </div>
      )}

      {/* Period Activity Flow Bar (In vs Out) */}
      <div className="space-y-1.5 pt-0.5">
        <div className="flex items-center justify-between text-[11px] text-[var(--text-sub)]">
          <span className="font-medium">Period Activity</span>
          <span className="tabular-nums font-medium">
            Total {formatMoney(totalFlow, acc.currency, { compact: true })}
          </span>
        </div>

        {totalFlow > 0 ? (
          <div className="space-y-1">
            {/* The Slender Clean Dual Bar */}
            <div className="w-full h-1.5 rounded-full bg-slate-200 dark:bg-slate-800 overflow-hidden flex">
              <div
                style={{ width: `${inPct}%` }}
                className="h-full bg-emerald-500 transition-all duration-300"
                title={`Money in: ${formatMoney(inflow, acc.currency)} (${inPct}%)`}
              />
              <div
                style={{ width: `${outPct}%` }}
                className="h-full bg-rose-500 transition-all duration-300"
                title={`Money out: ${formatMoney(outflow, acc.currency)} (${outPct}%)`}
              />
            </div>

            {/* Labels below the Flow Bar */}
            <div className="flex items-center justify-between text-[11px] tabular-nums pt-0.5">
              <span className="flex items-center gap-1 text-emerald-600 dark:text-emerald-400 font-medium">
                <ArrowDownLeft className="w-3 h-3 shrink-0" />
                <span>{formatMoney(inflow, acc.currency, { compact: true })}</span>
                <span className="text-[10px] text-[var(--text-sub)]">({inPct}%)</span>
              </span>

              <span className="flex items-center gap-1 text-rose-600 dark:text-rose-400 font-medium">
                <span className="text-[10px] text-[var(--text-sub)]">({outPct}%)</span>
                <span>{formatMoney(outflow, acc.currency, { compact: true })}</span>
                <ArrowUpRight className="w-3 h-3 shrink-0" />
              </span>
            </div>
          </div>
        ) : (
          <div className="text-[11px] text-[var(--text-sub)] italic py-0.5">
            No movements recorded in active period
          </div>
        )}
      </div>

      {/* Note (if present) */}
      {acc.note && (
        <p className="text-[11px] text-[var(--text-sub)] line-clamp-2 border-l-2 border-slate-300 dark:border-slate-700 pl-2 italic">
          {acc.note}
        </p>
      )}

      {/* Footer: Date + Actions */}
      <div className="mt-auto pt-2.5 border-t border-[var(--border-glass)] flex items-center justify-between gap-2 text-xs text-[var(--text-sub)]">
        <div className="text-[10px] tabular-nums truncate">
          <span>as of {acc.balance_as_of}</span>
          {acc.source_last_date && (
            <span className="text-[var(--text-sub)] opacity-75"> · sheet to {acc.source_last_date}</span>
          )}
        </div>

        <div className="flex items-center gap-1.5 shrink-0">
          {canWrite && (
            <>
              <button
                type="button"
                onClick={() => onMoveMoney(acc.id)}
                className="btn-secondary text-[10px] py-0.5 px-2 font-medium"
              >
                Transfer
              </button>
              <button
                type="button"
                onClick={() => onRecordEntry(acc.id)}
                className="btn-secondary text-[10px] py-0.5 px-2 font-medium"
              >
                Entry
              </button>
            </>
          )}
          <button
            type="button"
            onClick={() => onOpenAccount(acc)}
            className="btn-primary keep-white text-[10px] py-0.5 px-2.5 font-semibold"
          >
            Ledger →
          </button>
        </div>
      </div>
    </div>
  );
}

export default AccountCard;
