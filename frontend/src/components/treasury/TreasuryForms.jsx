import React, { useEffect, useMemo, useRef, useState } from 'react';
import { X, ArrowRightLeft, PlusCircle, Scale, ShieldAlert, HandCoins, Building2, Search, ArrowRight, Info } from 'lucide-react';
import { formatMoney } from './treasuryUtils';
import { treasuryApi } from './TreasuryPanels';

const today = () => new Date().toISOString().slice(0, 10);

export function Modal({ title, icon: Icon, onClose, children, wide = false }) {
  useEffect(() => {
    const k = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/75 backdrop-blur-xs p-4 animate-fadeIn" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div role="dialog" aria-modal="true" aria-label={title}
        className={`glass-panel w-full ${wide ? 'max-w-3xl' : 'max-w-xl'} max-h-[92vh] overflow-y-auto custom-scrollbar p-6 space-y-4 shadow-2xl relative z-10`}>
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-bold flex items-center gap-2">{Icon && <Icon className="w-5 h-5 text-cyan-400" />} {title}</h3>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-slate-200" aria-label="Close"><X className="w-5 h-5" /></button>
        </div>
        {children}
      </div>
    </div>
  );
}

const Field = ({ label, hint, children }) => (
  <label className="block text-xs">
    <span className="block font-bold mb-1">{label}</span>
    {children}
    {hint && <span className="block text-[11px] text-slate-400 mt-1">{hint}</span>}
  </label>
);

const ErrorBox = ({ msg }) => (msg ? <div className="p-2.5 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-400 text-xs">{msg}</div> : null);

/** Searchable picker for accounts or pots - 274 pots don't fit a plain <select>. */
export function SearchPicker({ items, value, onChange, placeholder = 'Search…', render, sub, ariaLabel }) {
  const [q, setQ] = useState('');
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const selected = items.find((i) => i.id === value);
  const list = useMemo(() => {
    const s = q.trim().toLowerCase();
    return (s ? items.filter((i) => `${render(i)} ${sub ? sub(i) : ''}`.toLowerCase().includes(s)) : items).slice(0, 60);
  }, [items, q, render, sub]);
  useEffect(() => {
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, []);
  return (
    <div className="relative" ref={ref}>
      <button type="button" aria-label={ariaLabel} onClick={() => setOpen((o) => !o)}
        className="w-full p-2.5 rounded-lg border text-left text-xs flex items-center justify-between gap-2">
        <span className="truncate">{selected ? <><span className="font-semibold">{render(selected)}</span>{sub && <span className="text-slate-400"> · {sub(selected)}</span>}</> : <span className="text-slate-400">{placeholder}</span>}</span>
        <Search className="w-3.5 h-3.5 text-slate-400 shrink-0" />
      </button>
      {open && (
        <div className="absolute z-40 mt-1 w-full rounded-xl border border-slate-700/60 shadow-2xl" style={{ background: 'var(--drawer-bg)' }}>
          <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder={placeholder} className="w-full p-2.5 border-b border-slate-700/40 text-xs bg-transparent" />
          <div className="max-h-64 overflow-y-auto custom-scrollbar">
            {list.map((i) => (
              <button type="button" key={i.id} onClick={() => { onChange(i.id); setOpen(false); setQ(''); }}
                className={`w-full text-left px-3 py-2 text-xs hover:bg-blue-500/10 ${i.id === value ? 'bg-blue-500/10' : ''}`}>
                <div className="font-semibold">{render(i)}</div>
                {sub && <div className="text-slate-400">{sub(i)}</div>}
              </button>
            ))}
            {!list.length && <div className="p-3 text-xs text-slate-400">No match.</div>}
          </div>
        </div>
      )}
    </div>
  );
}

export const accountLabel = (a) => a.name;
export const accountSub = (a) => `${a.group_name} · ${formatMoney(a.current_balance_native, a.currency)}`;
export const potLabel = (p) => p.name;
export const potSub = (p) => `${p.country} · ${p.pool} · ${formatMoney(p.current_balance_usd, 'USD')}`;

function BalanceRow({ acc, delta }) {
  if (!acc) return null;
  const before = Number(acc.current_balance_native || 0);
  const after = before + delta;
  return (
    <div className="flex items-center justify-between text-xs py-1">
      <span className="font-semibold truncate pr-2">{acc.name}</span>
      <span className="tabular-nums flex items-center gap-1.5">
        {formatMoney(before, acc.currency)} <ArrowRight className="w-3 h-3 text-slate-400" />
        <strong className={after < -0.005 ? 'text-rose-400' : ''}>{formatMoney(after, acc.currency)}</strong>
      </span>
    </div>
  );
}

/** Account → account transfer with FX: shows the expected amount at period rates, the FX difference and both balances after. */
export function TransferForm({ accounts, company, onClose, onDone, defaultFrom, canApprove = false }) {
  const [f, setF] = useState({ from_account_id: defaultFrom || accounts[0]?.id || '', to_account_id: '', from_amount_native: '', to_amount_native: '', tx_date: today(), fee_usd: '', description: '', submit_for_approval: !canApprove });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const from = accounts.find((a) => a.id === f.from_account_id);
  const to = accounts.find((a) => a.id === f.to_account_id);
  const sent = Number(f.from_amount_native) || 0;
  const recv = Number(f.to_amount_native) || 0;
  const expected = from && to && sent ? (sent * (from.reconciled_fx_rate || 1)) / (to.reconciled_fx_rate || 1) : 0;
  const sentUsd = from ? sent * (from.reconciled_fx_rate || 1) : 0;
  const recvUsd = to ? recv * (to.reconciled_fx_rate || 1) : 0;
  const fxLoss = sent && recv ? sentUsd - recvUsd : 0;
  const sameCur = from && to && from.currency === to.currency;

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setErr('');
    try {
      const d = await treasuryApi('/transfers', {
        method: 'POST',
        company,
        body: {
          ...f,
          from_amount_native: sent,
          to_amount_native: recv,
          fee_usd: Number(f.fee_usd || 0),
          submit_for_approval: Boolean(f.submit_for_approval),
        },
      });
      if (d.status === 'pending_approval') {
        onDone(d.message || 'Transfer submitted for manager approval.');
      } else {
        onDone(`Transfer recorded (#${d.activity_id}) · realised rate ${d.realized_rate}`);
      }
    } catch (e2) { setErr(e2.message); } finally { setBusy(false); }
  };

  return (
    <Modal title="Move money between accounts" icon={ArrowRightLeft} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4 text-xs">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <Field label="From"><SearchPicker ariaLabel="From account" items={accounts} value={f.from_account_id} onChange={(v) => setF({ ...f, from_account_id: v })} render={accountLabel} sub={accountSub} placeholder="Source account" /></Field>
          <Field label="To"><SearchPicker ariaLabel="To account" items={accounts.filter((a) => a.id !== f.from_account_id)} value={f.to_account_id} onChange={(v) => setF({ ...f, to_account_id: v })} render={accountLabel} sub={accountSub} placeholder="Destination account" /></Field>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <Field label={`Sent (${from?.currency || '—'})`}>
            <input type="number" step="0.01" min="0" required value={f.from_amount_native} className="w-full p-2.5 rounded-lg border"
              onChange={(e) => setF({ ...f, from_amount_native: e.target.value, ...(sameCur ? { to_amount_native: e.target.value } : {}) })} />
          </Field>
          <Field label={`Received (${to?.currency || '—'})`} hint={expected && !sameCur ? <>At period rates ≈ <button type="button" className="text-cyan-400 underline" onClick={() => setF({ ...f, to_amount_native: expected.toFixed(2) })}>{formatMoney(expected, to.currency)}</button> — enter what actually arrived.</> : null}>
            <input type="number" step="0.01" min="0" required value={f.to_amount_native} onChange={(e) => setF({ ...f, to_amount_native: e.target.value })} className="w-full p-2.5 rounded-lg border" />
          </Field>
        </div>

        {from && to && sent > 0 && recv > 0 && (
          <div className="p-3 rounded-xl bg-slate-900/40 border border-slate-700/40 space-y-1">
            <div className="flex justify-between"><span className="text-slate-400">Realised rate</span><span className="tabular-nums font-semibold">1 {from.currency} = {(recv / sent).toFixed(5)} {to.currency}</span></div>
            {Math.abs(fxLoss) >= 0.01 && (
              <div className="flex justify-between items-center"><span className="text-slate-400">Transfer / FX difference at period rates</span>
                <span className="tabular-nums font-semibold">{formatMoney(-fxLoss, 'USD', { signed: true })}
                  {fxLoss > 0.01 && Number(f.fee_usd || 0) === 0 && <button type="button" className="ml-2 text-cyan-400 underline" onClick={() => setF({ ...f, fee_usd: fxLoss.toFixed(2) })}>book as fee</button>}
                </span>
              </div>
            )}
            <div className="pt-1 mt-1 border-t border-slate-700/40">
              <BalanceRow acc={from} delta={-sent} />
              <BalanceRow acc={to} delta={recv} />
            </div>
          </div>
        )}

        <div className="grid grid-cols-2 gap-3">
          <Field label="Date"><input type="date" value={f.tx_date} onChange={(e) => setF({ ...f, tx_date: e.target.value })} className="w-full p-2.5 rounded-lg border" /></Field>
          <Field label="Fee / FX loss (USD)" hint="Booked to Transfer fees · Unallocated · Non-Zakat">
            <input type="number" step="0.01" min="0" value={f.fee_usd} onChange={(e) => setF({ ...f, fee_usd: e.target.value })} className="w-full p-2.5 rounded-lg border" placeholder="0" />
          </Field>
        </div>
        <Field label="Reference"><input value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} placeholder="e.g. October Syria float via Ziraat" className="w-full p-2.5 rounded-lg border" /></Field>

        {/* Approval Workflow Option */}
        {canApprove ? (
          <div className="p-3 rounded-xl bg-slate-900/30 border border-slate-700/40 flex items-center justify-between">
            <div>
              <div className="font-semibold text-slate-200">Execution Mode</div>
              <div className="text-[11px] text-slate-400">You hold approval permission for transfers.</div>
            </div>
            <div className="flex items-center gap-2">
              <label className="flex items-center gap-1.5 cursor-pointer">
                <input
                  type="radio"
                  name="approval_mode"
                  checked={!f.submit_for_approval}
                  onChange={() => setF({ ...f, submit_for_approval: false })}
                />
                <span>Execute now</span>
              </label>
              <label className="flex items-center gap-1.5 cursor-pointer">
                <input
                  type="radio"
                  name="approval_mode"
                  checked={Boolean(f.submit_for_approval)}
                  onChange={() => setF({ ...f, submit_for_approval: true })}
                />
                <span>Queue for approval</span>
              </label>
            </div>
          </div>
        ) : (
          <div className="p-2.5 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs flex items-center gap-2">
            <Clock className="w-4 h-4 shrink-0" />
            <span>This transfer will be submitted to the Approvals Queue for manager review before funds move.</span>
          </div>
        )}

        <ErrorBox msg={err} />
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={onClose} className="btn-secondary">Cancel</button>
          <button type="submit" disabled={busy || !f.to_account_id} className="btn-primary keep-white">
            {busy ? 'Saving…' : f.submit_for_approval ? 'Submit for approval' : 'Record transfer'}
          </button>
        </div>
      </form>
    </Modal>
  );
}

/** Income, expense or amanah (money held for others) on an account, optionally booked to a pot. */
export function EntryForm({ accounts, pots, company, onClose, onDone, defaultAccount }) {
  const [f, setF] = useState({
    account_id: defaultAccount || accounts[0]?.id || '',
    kind: 'income', // 'income' | 'expense' | 'amanah'
    amount_native: '',
    pot_id: '',
    tx_date: today(),
    description: '',
    holder: '',
    record_deposit: true,
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const acc = accounts.find((a) => a.id === f.account_id);
  const pot = pots.find((p) => p.id === f.pot_id);
  const amt = Number(f.amount_native) || 0;
  const usd = acc ? amt * (acc.reconciled_fx_rate || 1) : 0;

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setErr('');
    try {
      if (f.kind === 'amanah') {
        const holderName = (f.holder || '').trim();
        if (!holderName) {
          throw new Error('Please enter who this amanah is held for.');
        }
        const body = {
          holder: holderName,
          account_id: f.account_id || null,
          native_amount: amt,
          currency: acc?.currency || 'USD',
          note: f.description || '',
          as_of_date: f.tx_date,
          record_deposit: Boolean(f.record_deposit && f.account_id),
        };
        const d = await treasuryApi('/trusts', { method: 'POST', company, body });
        onDone(`Amanah recorded for ${body.holder} (#${d.activity_id})${body.record_deposit ? ` · cash deposit added to ${acc?.name || 'account'}` : ''}`);
      } else {
        const d = await treasuryApi('/transactions', { method: 'POST', company, body: { ...f, amount_native: amt, pot_id: f.pot_id || null } });
        onDone(`${f.kind === 'income' ? 'Income' : 'Expense'} recorded (#${d.activity_id}) · ${formatMoney(d.amount_usd, 'USD', { signed: true })}`);
      }
    } catch (e2) { setErr(e2.message); } finally { setBusy(false); }
  };

  const isAmanah = f.kind === 'amanah';

  return (
    <Modal
      title={isAmanah ? 'Record amanah (money held for others)' : 'Record income or spending'}
      icon={isAmanah ? ShieldAlert : PlusCircle}
      onClose={onClose}
    >
      <form onSubmit={submit} className="space-y-4 text-xs">
        {/* Kind Selector */}
        <div className="flex rounded-xl p-1 border border-slate-700/60 bg-slate-900/40 font-bold w-fit flex-wrap gap-1">
          {[
            ['income', 'Money in'],
            ['expense', 'Money out'],
            ['amanah', 'Amanah (held for others)'],
          ].map(([k, l]) => (
            <button
              type="button"
              key={k}
              onClick={() => setF({ ...f, kind: k })}
              className={`px-3.5 py-1.5 rounded-lg transition-colors ${
                f.kind === k
                  ? k === 'income'
                    ? 'bg-blue-600 keep-white shadow-xs'
                    : k === 'expense'
                    ? 'bg-rose-600 keep-white shadow-xs'
                    : 'bg-amber-600 keep-white shadow-xs'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              {l}
            </button>
          ))}
        </div>

        {/* Account Selector */}
        <Field label="Account">
          <SearchPicker
            ariaLabel="Account"
            items={accounts}
            value={f.account_id}
            onChange={(v) => setF({ ...f, account_id: v })}
            render={accountLabel}
            sub={accountSub}
          />
        </Field>

        {/* Held For (for Amanah) */}
        {isAmanah && (
          <Field label="Held for / Owner" hint="Person, organization, or appeal this money belongs to">
            <input
              required
              value={f.holder}
              onChange={(e) => setF({ ...f, holder: e.target.value })}
              placeholder="e.g. Sajjad / OGN / Human Aid"
              className="w-full p-2.5 rounded-lg border bg-amber-500/5 border-amber-500/30 focus:border-amber-500"
            />
          </Field>
        )}

        {/* Amount & Date */}
        <div className="grid grid-cols-2 gap-3">
          <Field
            label={`Amount (${acc?.currency || '—'})`}
            hint={amt && acc?.currency !== 'USD' ? `≈ ${formatMoney(usd, 'USD')} at the period rate` : null}
          >
            <input
              type="number"
              step="0.01"
              min="0"
              required
              value={f.amount_native}
              onChange={(e) => setF({ ...f, amount_native: e.target.value })}
              className="w-full p-2.5 rounded-lg border"
            />
          </Field>
          <Field label="Date">
            <input
              type="date"
              value={f.tx_date}
              onChange={(e) => setF({ ...f, tx_date: e.target.value })}
              className="w-full p-2.5 rounded-lg border"
            />
          </Field>
        </div>

        {/* Pot selector (only for regular income/expense) */}
        {!isAmanah ? (
          <Field
            label="Pot (fund)"
            hint={pot ? `${pot.name}: ${formatMoney(pot.current_balance_usd, 'USD')} → ${formatMoney(Number(pot.current_balance_usd) + (f.kind === 'income' ? usd : -usd), 'USD')}` : 'Leave empty to change the account only.'}
          >
            <SearchPicker
              ariaLabel="Pot"
              items={[{ id: '', name: 'No pot', country: '', pool: '', current_balance_usd: 0 }, ...pots]}
              value={f.pot_id}
              onChange={(v) => setF({ ...f, pot_id: v })}
              render={potLabel}
              sub={(p) => (p.id ? potSub(p) : 'account only')}
              placeholder="Search pots…"
            />
          </Field>
        ) : (
          /* Deposit toggle for Amanah */
          <div className="p-3 rounded-xl bg-slate-900/60 border border-amber-500/30 space-y-1.5">
            <label className="flex items-start gap-2.5 cursor-pointer">
              <input
                type="checkbox"
                className="mt-0.5 rounded border-slate-700 text-amber-600 focus:ring-amber-500"
                checked={f.record_deposit}
                onChange={(e) => setF({ ...f, record_deposit: e.target.checked })}
              />
              <div className="space-y-0.5">
                <span className="font-semibold text-slate-200">Also record as cash deposit entry in this account</span>
                <p className="text-[11px] text-slate-400">
                  {f.record_deposit ? (
                    <span className="text-emerald-400 font-medium">
                      ✓ Increases {acc?.name || 'account'} cash balance by +{formatMoney(amt, acc?.currency || 'USD')} and records an entry in the account statement.
                    </span>
                  ) : (
                    <span>Unticked: Tags existing cash on {acc?.name || 'account'} as held for others without changing total bank balance.</span>
                  )}
                </p>
              </div>
            </label>
          </div>
        )}

        {/* Description */}
        <Field label={isAmanah ? 'Note / Purpose' : 'Description'}>
          <input
            required={!isAmanah}
            value={f.description}
            onChange={(e) => setF({ ...f, description: e.target.value })}
            placeholder={isAmanah ? 'e.g. October surplus & OGN amanahs' : 'Donor / vendor / purpose'}
            className="w-full p-2.5 rounded-lg border"
          />
        </Field>

        {/* Impact Preview */}
        {acc && amt > 0 && (
          <div className="p-3 rounded-xl bg-slate-900/40 border border-slate-700/40 space-y-1 text-xs">
            {isAmanah ? (
              <>
                {f.record_deposit && <BalanceRow acc={acc} delta={amt} />}
                <div className="flex items-center justify-between text-slate-400 pt-0.5">
                  <span>Amanah held for others ({acc.name}):</span>
                  <strong className="text-amber-400 font-mono">+{formatMoney(amt, acc.currency)}</strong>
                </div>
                <p className="text-[11px] text-slate-400">
                  {f.record_deposit
                    ? 'Bank balance increases; spendable cash stays the same because the new deposit is held for others.'
                    : 'Bank balance stays the same; spendable cash is reduced because this portion is held for others.'}
                </p>
              </>
            ) : (
              <BalanceRow acc={acc} delta={f.kind === 'income' ? amt : -amt} />
            )}
          </div>
        )}

        <ErrorBox msg={err} />
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="btn-secondary">Cancel</button>
          <button
            type="submit"
            disabled={busy || !amt}
            className={`btn-primary keep-white ${isAmanah ? 'bg-amber-600 hover:bg-amber-500' : ''}`}
          >
            {busy ? 'Saving…' : isAmanah ? 'Record Amanah' : 'Record'}
          </button>
        </div>
      </form>
    </Modal>
  );
}

/** Month-end balance from the cash position sheet or a bank statement; the difference is shown before saving. */
export function BalanceForm({ account, company, onClose, onDone }) {
  const [val, setVal] = useState(String(account.current_balance_native ?? ''));
  const [asOf, setAsOf] = useState(today());
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const diff = (Number(val) || 0) - Number(account.current_balance_native || 0);
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setErr('');
    try {
      const d = await treasuryApi(`/accounts/${account.id}/balance`, { method: 'POST', company, body: { new_balance_native: Number(val), as_of: asOf, note } });
      onDone(`${account.name} balance updated (#${d.activity_id}) · difference ${formatMoney(d.difference_native, account.currency, { signed: true })}`);
    } catch (e2) { setErr(e2.message); } finally { setBusy(false); }
  };
  return (
    <Modal title={`Update balance — ${account.name}`} icon={Scale} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4 text-xs">
        <p className="text-slate-400">Enter the balance from the month-end cash position sheet or the statement. Use this for reconciling; record individual movements with a transfer or an entry.</p>
        <div className="grid grid-cols-2 gap-3">
          <Field label={`Balance (${account.currency})`}><input type="number" step="0.01" required value={val} onChange={(e) => setVal(e.target.value)} className="w-full p-2.5 rounded-lg border" /></Field>
          <Field label="As of"><input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} className="w-full p-2.5 rounded-lg border" /></Field>
        </div>
        <div className="p-3 rounded-xl bg-slate-900/40 border border-slate-700/40 flex justify-between">
          <span className="text-slate-400">Difference vs CRM</span>
          <strong className={`tabular-nums ${Math.abs(diff) > 0.005 ? 'text-amber-400' : 'text-emerald-400'}`}>
            {formatMoney(diff, account.currency, { signed: true })} {account.currency !== 'USD' && `(${formatMoney(diff * (account.reconciled_fx_rate || 1), 'USD', { signed: true })})`}
          </strong>
        </div>
        <Field label="Note" hint="e.g. Osman's 30 Nov cash sheet / Lloyds statement p.4"><input value={note} onChange={(e) => setNote(e.target.value)} className="w-full p-2.5 rounded-lg border" /></Field>
        <ErrorBox msg={err} />
        <div className="flex justify-end gap-2"><button type="button" onClick={onClose} className="btn-secondary">Cancel</button>
          <button type="submit" disabled={busy} className="btn-primary keep-white">{busy ? 'Saving…' : 'Save balance'}</button></div>
      </form>
    </Modal>
  );
}

const CURRENCIES = ['USD', 'GBP', 'TRY', 'EUR', 'ZAR', 'EGP', 'USDT'];

export function TrustForm({ accounts, company, item, onClose, onDone }) {
  const [f, setF] = useState({
    holder: item?.holder || '',
    account_id: item?.account_id || '',
    native_amount: item?.native_amount ?? '',
    currency: item?.currency || 'USD',
    note: item?.note || '',
    as_of_date: item?.as_of_date || today(),
    record_deposit: false,
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const acc = accounts.find((a) => a.id === f.account_id);

  const submit = async (e) => {
    e.preventDefault(); setBusy(true); setErr('');
    try {
      const body = {
        ...f,
        native_amount: Number(f.native_amount),
        account_id: f.account_id || null,
        record_deposit: !item && !!f.account_id && !!f.record_deposit,
      };
      const d = item ? await treasuryApi(`/trusts/${item.id}`, { method: 'PATCH', company, body }) : await treasuryApi('/trusts', { method: 'POST', company, body });
      onDone(`Amanah ${item ? 'updated' : 'added'} (#${d.activity_id})${body.record_deposit ? ' · cash deposit recorded' : ''}`);
    } catch (e2) { setErr(e2.message); } finally { setBusy(false); }
  };
  return (
    <Modal title={item ? 'Edit amanah' : 'Money held for someone else'} icon={ShieldAlert} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4 text-xs">
        <p className="text-slate-400">Amanahs sit in our accounts but are not ours, so they are deducted from spendable cash.</p>
        <Field label="Held for"><input required value={f.holder} onChange={(e) => setF({ ...f, holder: e.target.value })} className="w-full p-2.5 rounded-lg border" placeholder="e.g. Human Aid" /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Amount"><input type="number" step="0.01" required value={f.native_amount} onChange={(e) => setF({ ...f, native_amount: e.target.value })} className="w-full p-2.5 rounded-lg border" /></Field>
          <Field label="Currency"><select value={f.currency} onChange={(e) => setF({ ...f, currency: e.target.value })} className="w-full p-2.5 rounded-lg border">{CURRENCIES.map((c) => <option key={c}>{c}</option>)}</select></Field>
        </div>
        <Field label="Sitting in account (optional)">
          <SearchPicker
            ariaLabel="Account"
            items={[{ id: '', name: 'Not specified', group_name: '', current_balance_native: 0, currency: '' }, ...accounts]}
            value={f.account_id}
            onChange={(v) => {
              const sel = accounts.find((a) => a.id === v);
              setF({
                ...f,
                account_id: v,
                ...(sel?.currency ? { currency: sel.currency } : {}),
              });
            }}
            render={accountLabel}
            sub={(a) => (a.id ? accountSub(a) : '')}
          />
        </Field>

        {/* Deposit Toggle */}
        {f.account_id && !item && (
          <div className="p-3 rounded-xl bg-slate-900/60 border border-slate-700/60 space-y-1.5">
            <label className="flex items-start gap-2.5 cursor-pointer">
              <input
                type="checkbox"
                className="mt-0.5 rounded border-slate-700 text-blue-600 focus:ring-blue-500"
                checked={f.record_deposit}
                onChange={(e) => setF({ ...f, record_deposit: e.target.checked })}
              />
              <div className="space-y-0.5">
                <span className="font-semibold text-slate-200">Also record as physical cash deposit into this account</span>
                <p className="text-[11px] text-slate-400">
                  {f.record_deposit ? (
                    <span className="text-emerald-400 font-medium">
                      ✓ Will increase {acc?.name || 'account'} balance by +{formatMoney(f.native_amount || 0, f.currency)} and add an entry in its statement ledger.
                    </span>
                  ) : (
                    <span>Unticked: Ring-fences existing cash without changing the account balance.</span>
                  )}
                </p>
              </div>
            </label>
          </div>
        )}

        <Field label="Note"><input value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} className="w-full p-2.5 rounded-lg border" /></Field>
        <ErrorBox msg={err} />
        <div className="flex justify-end gap-2"><button type="button" onClick={onClose} className="btn-secondary">Cancel</button>
          <button type="submit" disabled={busy} className="btn-primary keep-white">{busy ? 'Saving…' : 'Save'}</button></div>
      </form>
    </Modal>
  );
}

export function ReceivableForm({ company, item, onClose, onDone }) {
  const [f, setF] = useState({ name: item?.name || '', category: item?.category || 'partner_settlement', native_amount: item?.native_amount ?? '', currency: item?.currency || 'USD', is_included_in_net_position: item ? !!item.is_included_in_net_position : true, note: item?.note || '', as_of_date: item?.as_of_date || today() });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const submit = async (e) => {
    e.preventDefault(); setBusy(true); setErr('');
    try {
      const body = { ...f, native_amount: Number(f.native_amount) };
      const d = item ? await treasuryApi(`/receivables/${item.id}`, { method: 'PATCH', company, body }) : await treasuryApi('/receivables', { method: 'POST', company, body });
      onDone(`Receivable ${item ? 'updated' : 'added'} (#${d.activity_id})`);
    } catch (e2) { setErr(e2.message); } finally { setBusy(false); }
  };
  return (
    <Modal title={item ? `Edit — ${item.name}` : 'Money owed to us'} icon={HandCoins} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4 text-xs">
        <Field label="Name"><input required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} className="w-full p-2.5 rounded-lg border" placeholder="e.g. One Nation partner settlement" /></Field>
        <div className="grid grid-cols-3 gap-3">
          <Field label="Amount"><input type="number" step="0.01" required value={f.native_amount} onChange={(e) => setF({ ...f, native_amount: e.target.value })} className="w-full p-2.5 rounded-lg border" /></Field>
          <Field label="Currency"><select value={f.currency} onChange={(e) => setF({ ...f, currency: e.target.value })} className="w-full p-2.5 rounded-lg border">{CURRENCIES.map((c) => <option key={c}>{c}</option>)}</select></Field>
          <Field label="As of"><input type="date" value={f.as_of_date} onChange={(e) => setF({ ...f, as_of_date: e.target.value })} className="w-full p-2.5 rounded-lg border" /></Field>
        </div>
        <Field label="Kind">
          <select value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })} className="w-full p-2.5 rounded-lg border">
            <option value="partner_settlement">Partner settlement</option><option value="staff_advance">Staff / work advance</option>
            <option value="amanah_receivable">Amanah paid on someone's behalf</option><option value="in_transit">In transit</option>
            <option value="accrued_liability">Accrued liability (memo)</option><option value="other">Other</option>
          </select>
        </Field>
        <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={f.is_included_in_net_position} onChange={(e) => setF({ ...f, is_included_in_net_position: e.target.checked })} />
          Count in the fund position (untick for a memo-only line, e.g. accrued salaries on a cash basis)</label>
        <Field label="Note"><input value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} className="w-full p-2.5 rounded-lg border" /></Field>
        <ErrorBox msg={err} />
        <div className="flex justify-end gap-2"><button type="button" onClick={onClose} className="btn-secondary">Cancel</button>
          <button type="submit" disabled={busy} className="btn-primary keep-white">{busy ? 'Saving…' : 'Save'}</button></div>
      </form>
    </Modal>
  );
}

export function AccountForm({ company, regions, onClose, onDone }) {
  const [f, setF] = useState({ name: '', name_ar: '', group_name: regions[0] || 'United Kingdom', account_type: 'bank', currency: 'USD', holder: '', supervisor: '', opening_balance_native: '', reconciled_fx_rate: '', note: '' });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const submit = async (e) => {
    e.preventDefault(); setBusy(true); setErr('');
    try {
      const d = await treasuryApi('/accounts', { method: 'POST', company, body: { ...f, opening_balance_native: Number(f.opening_balance_native || 0), reconciled_fx_rate: f.reconciled_fx_rate ? Number(f.reconciled_fx_rate) : null } });
      onDone(`Account ${f.name} opened (#${d.activity_id})`);
    } catch (e2) { setErr(e2.message); } finally { setBusy(false); }
  };
  return (
    <Modal title="Open an account, box or wallet" icon={Building2} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4 text-xs">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Name"><input required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} className="w-full p-2.5 rounded-lg border" /></Field>
          <Field label="Arabic name (as on the cash sheet)"><input dir="rtl" value={f.name_ar} onChange={(e) => setF({ ...f, name_ar: e.target.value })} className="w-full p-2.5 rounded-lg border" /></Field>
        </div>
        <div className="grid grid-cols-3 gap-3">
          <Field label="Region"><input list="treasury-regions" required value={f.group_name} onChange={(e) => setF({ ...f, group_name: e.target.value })} className="w-full p-2.5 rounded-lg border" />
            <datalist id="treasury-regions">{regions.map((r) => <option key={r} value={r} />)}</datalist></Field>
          <Field label="Type"><select value={f.account_type} onChange={(e) => setF({ ...f, account_type: e.target.value })} className="w-full p-2.5 rounded-lg border">
            <option value="bank">Bank</option><option value="cash_safe">Cash box</option><option value="crypto">Crypto wallet</option><option value="platform">Platform</option><option value="reserve">Reserve</option></select></Field>
          <Field label="Currency"><select value={f.currency} onChange={(e) => setF({ ...f, currency: e.target.value })} className="w-full p-2.5 rounded-lg border">{CURRENCIES.map((c) => <option key={c}>{c}</option>)}</select></Field>
        </div>
        <div className="grid grid-cols-3 gap-3">
          <Field label="Opening balance"><input type="number" step="0.01" value={f.opening_balance_native} onChange={(e) => setF({ ...f, opening_balance_native: e.target.value })} className="w-full p-2.5 rounded-lg border" /></Field>
          <Field label="Holder"><input value={f.holder} onChange={(e) => setF({ ...f, holder: e.target.value })} className="w-full p-2.5 rounded-lg border" /></Field>
          <Field label="Supervisor"><input value={f.supervisor} onChange={(e) => setF({ ...f, supervisor: e.target.value })} className="w-full p-2.5 rounded-lg border" /></Field>
        </div>
        <Field label="USD per unit (only if the currency has no period rate)"><input type="number" step="0.000001" value={f.reconciled_fx_rate} onChange={(e) => setF({ ...f, reconciled_fx_rate: e.target.value })} className="w-full p-2.5 rounded-lg border" /></Field>
        <div className="text-[11px] text-slate-400 flex items-start gap-1.5"><Info className="w-3.5 h-3.5 shrink-0 mt-0.5" /> Opening a new account adds its balance to total cash — if the money came from another account, open it at 0 and record a transfer instead.</div>
        <ErrorBox msg={err} />
        <div className="flex justify-end gap-2"><button type="button" onClick={onClose} className="btn-secondary">Cancel</button>
          <button type="submit" disabled={busy} className="btn-primary keep-white">{busy ? 'Saving…' : 'Open account'}</button></div>
      </form>
    </Modal>
  );
}
