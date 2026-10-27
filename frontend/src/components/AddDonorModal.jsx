import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { UserPlus, X } from 'lucide-react';
import { API_BASE_URL } from '../config';

const inputStyle = { backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' };

/** The charity's agents (for the pickers and the Agent filter). */
export function useAgents(company, tick = 0) {
  const [agents, setAgents] = useState([]);
  useEffect(() => {
    if (!company || company === 'all') { setAgents([]); return; }
    fetch(`${API_BASE_URL}/api/donors/agents?company_id=${encodeURIComponent(company)}`)
      .then(r => (r.ok ? r.json() : { agents: [] })).then(d => setAgents(d.agents || [])).catch(() => setAgents([]));
  }, [company, tick]);
  return agents;
}

function Field({ label, children, wide }) {
  return (
    <label className={`flex flex-col gap-1 ${wide ? 'sm:col-span-2' : ''}`}>
      <span className="text-[11px] font-semibold" style={{ color: 'var(--text-sub)' }}>{label}</span>
      {children}
    </label>
  );
}

/** Agent: pick one of the charity's agents or type a new name. */
export function AgentInput({ value, onChange, agents, id = 'agent-input' }) {
  return (
    <>
      <input list={`${id}-list`} value={value} onChange={e => onChange(e.target.value)} placeholder="Choose or type an agent"
        className="w-full px-2.5 py-2 text-sm rounded-lg" style={inputStyle} />
      <datalist id={`${id}-list`}>{agents.map(a => <option key={a.name} value={a.name} />)}</datalist>
    </>
  );
}

/**
 * Adds a donor who has no donation yet (e.g. Iqra's SA donors). If the email already belongs to a donor of this
 * charity, the agent / group / interests are added to that donor instead of creating a second one.
 */
export default function AddDonorModal({ company, onClose, onCreated }) {
  const agents = useAgents(company);
  const [f, setF] = useState({ first_name: '', last_name: '', email: '', phone: '', city: '', country: '', agent: '', donor_group: '', interests: '', notes: '' });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const set = (k, v) => setF(p => ({ ...p, [k]: v }));
  const input = (k, props = {}) => <input value={f[k]} onChange={e => set(k, e.target.value)} className="w-full px-2.5 py-2 text-sm rounded-lg" style={inputStyle} {...props} />;

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') { e.stopPropagation(); onClose(); } };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [onClose]);

  const save = async () => {
    setError('');
    if (!f.email.trim() && !`${f.first_name}${f.last_name}`.trim()) { setError("Enter the donor's name or email."); return; }
    setSaving(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/donors/manual-donor`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...f, company_id: company }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `Error ${res.status}`);
      onCreated?.(data);
      onClose();
    } catch (e) { setError(e.message); } finally { setSaving(false); }
  };

  return createPortal(
    <div className="fixed inset-0 z-[85] flex items-center justify-center p-3 sm:p-6" role="dialog" aria-modal="true" aria-label="Add donor">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-2xl max-h-[92vh] flex flex-col rounded-2xl shadow-2xl overflow-hidden border" style={{ backgroundColor: 'var(--bg-card, var(--bg-main))', borderColor: 'var(--border-glass)' }}>
        <div className="px-6 py-4 border-b flex items-center justify-between bg-gradient-to-br from-sky-500/10 to-transparent" style={{ borderColor: 'var(--border-glass)' }}>
          <div>
            <h2 className="text-base font-black flex items-center gap-2" style={{ color: 'var(--text-main)' }}><UserPlus className="w-5 h-5 text-sky-500" /> Add donor</h2>
            <p className="text-xs" style={{ color: 'var(--text-muted)' }}>A person without a donation yet. Add donations to them later with “Add donation”.</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="w-8 h-8 rounded-full flex items-center justify-center" style={{ color: 'var(--text-sub)' }}><X className="w-4 h-4" /></button>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-5 grid grid-cols-1 sm:grid-cols-2 gap-3">
          <Field label="First name">{input('first_name')}</Field>
          <Field label="Last name">{input('last_name')}</Field>
          <Field label="Email">{input('email', { type: 'email' })}</Field>
          <Field label="Phone">{input('phone', { placeholder: '+27…' })}</Field>
          <Field label="City">{input('city')}</Field>
          <Field label="Country">{input('country')}</Field>
          <Field label="Agent"><AgentInput value={f.agent} onChange={v => set('agent', v)} agents={agents} id="new-donor-agent" /></Field>
          <Field label="Donor group">
            <label className="flex items-center gap-2 text-sm py-2" style={{ color: 'var(--text-main)' }}>
              <input type="checkbox" checked={f.donor_group === 'SA'} onChange={e => set('donor_group', e.target.checked ? 'SA' : '')} /> SA donor
            </label>
          </Field>
          <Field label="Interested in (projects)" wide>{input('interests', { placeholder: 'e.g. Iftar / Hafidh / Gaza feeding' })}</Field>
          <Field label="Notes" wide><textarea value={f.notes} onChange={e => set('notes', e.target.value)} rows={3} className="w-full px-2.5 py-2 text-sm rounded-lg" style={inputStyle} /></Field>
          {error && <div className="sm:col-span-2 text-xs rounded-lg px-3 py-2 bg-rose-500/10 text-rose-600 border border-rose-500/25">{error}</div>}
        </div>
        <div className="px-6 py-3 border-t flex justify-end gap-2" style={{ borderColor: 'var(--border-glass)' }}>
          <button type="button" onClick={onClose} className="px-3 py-2 text-xs font-semibold rounded-lg" style={{ color: 'var(--text-sub)' }}>Cancel</button>
          <button type="button" disabled={saving} onClick={save} className="px-4 py-2 text-xs font-bold rounded-lg bg-sky-600 hover:bg-sky-500 text-white disabled:opacity-50">{saving ? 'Saving…' : 'Add donor'}</button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
