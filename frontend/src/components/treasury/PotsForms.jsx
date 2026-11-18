import React, { useMemo, useState } from 'react';
import { ArrowRightLeft, Plus, Trash2, AlertTriangle, ArrowRight, Layers, CheckCircle2, Clock } from 'lucide-react';
import { formatMoney } from './treasuryUtils';
import { treasuryApi } from './TreasuryPanels';
import { Modal, SearchPicker, potLabel, potSub } from './TreasuryForms';

const today = () => new Date().toISOString().slice(0, 10);
const blankMove = (from = '') => ({ from_pot_id: from, to_pot_id: '', amount_usd: '', reason: '' });

/**
 * One move or a whole reallocation plan. "Check plan" asks the server for the walls each move crosses and every
 * pot's balance before/after; nothing is saved until "Apply", and then all moves are booked together or none.
 */
export function ReallocationPlanner({ pots, company, defaultFrom, onClose, onDone, canApprove = false }) {
  const [moves, setMoves] = useState([blankMove(defaultFrom)]);
  const [reason, setReason] = useState('');
  const [effDate, setEffDate] = useState(today());
  const [approvedBy, setApprovedBy] = useState('');
  const [confirmWalls, setConfirmWalls] = useState(false);
  const [submitForApproval, setSubmitForApproval] = useState(!canApprove);
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const potById = useMemo(() => Object.fromEntries(pots.map((p) => [p.id, p])), [pots]);
  const ready = moves.every((m) => m.from_pot_id && m.to_pot_id && Number(m.amount_usd) > 0);
  const total = moves.reduce((s, m) => s + (Number(m.amount_usd) || 0), 0);

  const update = (i, patch) => { setMoves((ms) => ms.map((m, j) => (j === i ? { ...m, ...patch } : m))); setPreview(null); setConfirmWalls(false); };
  const payload = () => ({
    moves: moves.map((m) => ({ ...m, amount_usd: Number(m.amount_usd), reason: m.reason || reason })),
    effective_date: effDate, reason, approved_by: approvedBy, confirm_wall_override: confirmWalls,
    submit_for_approval: Boolean(submitForApproval),
  });

  const check = async () => {
    setBusy(true); setErr('');
    try { setPreview(await treasuryApi('/pots/reallocate/preview', { method: 'POST', company, body: payload() })); } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  const apply = async () => {
    setBusy(true); setErr('');
    try {
      const d = await treasuryApi('/pots/reallocate/batch', { method: 'POST', company, body: payload() });
      if (d.status === 'pending_approval') {
        onDone(d.message || 'Reallocation plan submitted for manager approval.');
      } else {
        onDone(`${d.moves === 1 ? 'Reallocation' : `Plan of ${d.moves} moves`} booked (#${d.activity_id}) · ${formatMoney(d.total_usd, 'USD')}`);
      }
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  const walls = preview ? preview.lines.filter((l) => l.walls.length) : [];

  return (
    <Modal title="Reallocate between pots" icon={ArrowRightLeft} onClose={onClose} wide>
      <div className="space-y-4 text-xs">
        <p className="text-slate-400">
          Move money between funds or correct where income was attributed. The zakat wall (zakat → non-zakat, or to UK / Turkey) and the
          country wall need a named approver. Each move is written to the corrections register and can be reversed from Treasury → Activity.
        </p>

        <div className="space-y-2">
          {moves.map((m, i) => {
            const src = potById[m.from_pot_id];
            return (
              <div key={i} className="p-3 rounded-xl bg-slate-900/40 border border-slate-700/40 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="font-bold text-slate-400">Move {i + 1}</span>
                  {moves.length > 1 && <button type="button" onClick={() => { setMoves((ms) => ms.filter((_, j) => j !== i)); setPreview(null); }} className="text-slate-400 hover:text-rose-400" aria-label={`Remove move ${i + 1}`}><Trash2 className="w-3.5 h-3.5" /></button>}
                </div>
                <div className="grid grid-cols-1 md:grid-cols-[1fr_auto_1fr] gap-2 items-center">
                  <SearchPicker ariaLabel={`Move ${i + 1} from`} items={pots} value={m.from_pot_id} onChange={(v) => update(i, { from_pot_id: v })} render={potLabel} sub={potSub} placeholder="From pot" />
                  <ArrowRight className="w-4 h-4 text-slate-400 hidden md:block" />
                  <SearchPicker ariaLabel={`Move ${i + 1} to`} items={pots.filter((p) => p.id !== m.from_pot_id)} value={m.to_pot_id} onChange={(v) => update(i, { to_pot_id: v })} render={potLabel} sub={potSub} placeholder="To pot" />
                </div>
                <div className="grid grid-cols-1 md:grid-cols-[10rem_1fr] gap-2">
                  <div className="relative">
                    <input type="number" step="0.01" min="0" value={m.amount_usd} onChange={(e) => update(i, { amount_usd: e.target.value })} placeholder="USD" aria-label="Amount in USD" className="w-full p-2.5 rounded-lg border" />
                    {src && Number(src.current_balance_usd) > 0 && (
                      <button type="button" className="absolute right-2 top-1/2 -translate-y-1/2 text-[10px] text-cyan-400" onClick={() => update(i, { amount_usd: Number(src.current_balance_usd).toFixed(2) })}>all</button>
                    )}
                  </div>
                  <input value={m.reason} onChange={(e) => update(i, { reason: e.target.value })} placeholder={reason ? `Reason (default: ${reason})` : 'Reason for this move'} className="w-full p-2.5 rounded-lg border" />
                </div>
              </div>
            );
          })}
          <button type="button" onClick={() => { setMoves((ms) => [...ms, blankMove()]); setPreview(null); }} className="text-cyan-400 flex items-center gap-1 font-semibold"><Plus className="w-3.5 h-3.5" /> Add another move</button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <label className="block md:col-span-2"><span className="block font-bold mb-1">Reason for the plan</span>
            <input value={reason} onChange={(e) => { setReason(e.target.value); setPreview(null); }} placeholder="e.g. Close Syria deficits from General Zakat (approved Osman)" className="w-full p-2.5 rounded-lg border" /></label>
          <label className="block"><span className="block font-bold mb-1">Effective date</span>
            <input type="date" value={effDate} onChange={(e) => { setEffDate(e.target.value); setPreview(null); }} className="w-full p-2.5 rounded-lg border" /></label>
        </div>

        {preview && (
          <div className="space-y-3">
            {walls.length > 0 ? (
              <div className="p-3.5 rounded-xl bg-amber-500/10 border border-amber-500/40 space-y-2">
                <div className="font-bold text-amber-400 flex items-center gap-1.5"><AlertTriangle className="w-4 h-4" /> {walls.length} move{walls.length > 1 ? 's cross' : ' crosses'} a wall</div>
                <ul className="list-disc pl-5 space-y-0.5">{walls.map((l) => l.walls.map((w, k) => <li key={`${l.n}-${k}`}>Move {l.n}: {w}</li>))}</ul>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2 pt-1">
                  <input value={approvedBy} onChange={(e) => setApprovedBy(e.target.value)} placeholder="Approved by (e.g. Osman 16 Nov / HS / Board)" aria-label="Approved by" className="p-2.5 rounded-lg border" />
                  <label className="flex items-center gap-2 font-semibold"><input type="checkbox" checked={confirmWalls} onChange={(e) => setConfirmWalls(e.target.checked)} /> I have this approval in writing</label>
                </div>
              </div>
            ) : (
              <div className="p-2.5 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 flex items-center gap-1.5"><CheckCircle2 className="w-4 h-4" /> No zakat or country wall crossed.</div>
            )}
            <div className="overflow-x-auto">
              <table className="crm-table">
                <thead><tr><th>Pot</th><th>Country · pool</th><th className="text-right">Before</th><th className="text-right">After</th></tr></thead>
                <tbody>
                  {preview.impact.map((p) => (
                    <tr key={p.pot_id}>
                      <td className="font-semibold">{p.name}</td>
                      <td className="text-slate-400">{p.country} · {p.pool}</td>
                      <td className="text-right tabular-nums">{formatMoney(p.before_usd, 'USD')}</td>
                      <td className={`text-right tabular-nums font-bold ${p.after_usd < -0.01 ? 'text-rose-400' : ''}`}>{formatMoney(p.after_usd, 'USD')}{p.goes_negative && <span className="badge badge-pink text-[9px] ml-1">goes negative</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Approval Mode Option */}
        {preview && (
          canApprove ? (
            <div className="p-3 rounded-xl bg-slate-900/30 border border-slate-700/40 flex items-center justify-between">
              <div>
                <div className="font-semibold text-slate-200">Execution Mode</div>
                <div className="text-[11px] text-slate-400">You hold approval permission for pot reallocations.</div>
              </div>
              <div className="flex items-center gap-2">
                <label className="flex items-center gap-1.5 cursor-pointer">
                  <input
                    type="radio"
                    name="pot_approval_mode"
                    checked={!submitForApproval}
                    onChange={() => setSubmitForApproval(false)}
                  />
                  <span>Apply immediately</span>
                </label>
                <label className="flex items-center gap-1.5 cursor-pointer">
                  <input
                    type="radio"
                    name="pot_approval_mode"
                    checked={Boolean(submitForApproval)}
                    onChange={() => setSubmitForApproval(true)}
                  />
                  <span>Queue for approval</span>
                </label>
              </div>
            </div>
          ) : (
            <div className="p-2.5 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs flex items-center gap-2">
              <Clock className="w-4 h-4 shrink-0" />
              <span>This plan will be submitted to the Approvals Queue for manager review before balances update.</span>
            </div>
          )
        )}

        {err && <div className="p-2.5 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-400">{err}</div>}

        <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
          <span className="text-slate-400">{moves.length} move{moves.length > 1 ? 's' : ''} · {formatMoney(total, 'USD')}</span>
          <div className="flex gap-2">
            <button type="button" onClick={onClose} className="btn-secondary">Cancel</button>
            {!preview ? (
              <button type="button" disabled={!ready || busy} onClick={check} className="btn-primary keep-white">{busy ? 'Checking…' : 'Check plan'}</button>
            ) : (
              <button
                type="button"
                disabled={busy || !reason.trim() && moves.some((m) => !m.reason.trim()) || (walls.length > 0 && (!confirmWalls || !approvedBy.trim()))}
                onClick={apply}
                className="btn-primary keep-white"
              >
                {busy ? 'Processing…' : submitForApproval ? 'Submit plan for approval' : `Apply ${moves.length > 1 ? `${moves.length} moves` : 'move'}`}
              </button>
            )}
          </div>
        </div>
      </div>
    </Modal>
  );
}

export function PotCreateForm({ company, portfolios, countries, onClose, onDone }) {
  const [f, setF] = useState({ name: '', code: '', portfolio: portfolios[0] || 'General', program: '', country: 'Syria', pool: 'Non-Zakat', is_overhead: false });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const submit = async (e) => {
    e.preventDefault(); setBusy(true); setErr('');
    try {
      const d = await treasuryApi('/pots', { method: 'POST', company, body: f });
      onDone(`Pot ${f.name} opened (#${d.activity_id})`);
    } catch (e2) { setErr(e2.message); } finally { setBusy(false); }
  };
  return (
    <Modal title="Open a new pot" icon={Layers} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4 text-xs">
        <p className="text-slate-400">A pot is one fund in one country and one pool (zakat or not). It starts at zero; fund it with a reallocation or a bank entry.</p>
        <div className="grid grid-cols-3 gap-3">
          <label className="col-span-2"><span className="block font-bold mb-1">Name</span><input required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} className="w-full p-2.5 rounded-lg border" /></label>
          <label><span className="block font-bold mb-1">Code (optional)</span><input value={f.code} onChange={(e) => setF({ ...f, code: e.target.value })} className="w-full p-2.5 rounded-lg border" /></label>
        </div>
        <div className="grid grid-cols-3 gap-3">
          <label><span className="block font-bold mb-1">Country</span><input list="pot-countries" required value={f.country} onChange={(e) => setF({ ...f, country: e.target.value })} className="w-full p-2.5 rounded-lg border" />
            <datalist id="pot-countries">{countries.map((c) => <option key={c} value={c} />)}</datalist></label>
          <label><span className="block font-bold mb-1">Pool</span><select value={f.pool} onChange={(e) => setF({ ...f, pool: e.target.value })} className="w-full p-2.5 rounded-lg border"><option>Non-Zakat</option><option>Zakat</option></select></label>
          <label><span className="block font-bold mb-1">Portfolio</span><input list="pot-portfolios" value={f.portfolio} onChange={(e) => setF({ ...f, portfolio: e.target.value })} className="w-full p-2.5 rounded-lg border" />
            <datalist id="pot-portfolios">{portfolios.map((c) => <option key={c} value={c} />)}</datalist></label>
        </div>
        <label className="flex items-center gap-2"><input type="checkbox" checked={f.is_overhead} onChange={(e) => setF({ ...f, is_overhead: e.target.checked })} /> Office / running-cost pot (overhead)</label>
        {f.pool === 'Zakat' && ['uk', 'united kingdom', 'turkey', 'türkiye'].includes(f.country.toLowerCase()) && (
          <div className="text-amber-400 flex items-center gap-1.5"><AlertTriangle className="w-3.5 h-3.5" /> {f.country} is not a zakat-eligible destination.</div>
        )}
        {err && <div className="p-2.5 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-400">{err}</div>}
        <div className="flex justify-end gap-2"><button type="button" onClick={onClose} className="btn-secondary">Cancel</button>
          <button type="submit" disabled={busy} className="btn-primary keep-white">{busy ? 'Saving…' : 'Open pot'}</button></div>
      </form>
    </Modal>
  );
}
