import React, { useEffect, useMemo, useState } from 'react';
import { KeyRound, UserPlus, X, ShieldCheck, Save, Copy, Trash2, LogOut, Plus, Check, Minus, Lock } from 'lucide-react';
import { API_BASE_URL } from '../../config';
import { isSuperAdmin, canSomewhere } from '../../access';

// Users & Access: people, their preset per charity, single-permission overrides and record limits, and the
// presets themselves. Everything is enforced by the server (backend/api/rbac.py); this page only edits it.

const inputStyle = { backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' };
const ALL = '*';

async function api(path, method = 'GET', body) {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method, headers: body ? { 'Content-Type': 'application/json' } : undefined, body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Error ${res.status}`);
  return data;
}

const levelOf = (resource, perms) => {
  const read = resource.actions.filter(a => a.level === 'read').map(a => a.permission);
  const write = resource.actions.filter(a => a.level === 'write').map(a => a.permission);
  if (write.length && write.every(p => perms.has(p)) && read.every(p => perms.has(p))) return 'write';
  if (read.length && read.every(p => perms.has(p))) return 'read';
  return 'none';
};

/** Stripe-style editor: None / Read / Write per section plus extra switches. `base` (optional) = what the preset
 *  gives, so overrides show as granted (+) / removed (-) against it. */
function PermissionGrid({ catalogue, perms, onChange, base, readOnly }) {
  const set = (permList, on) => {
    const next = new Set(perms);
    permList.forEach(p => (on ? next.add(p) : next.delete(p)));
    onChange(next);
  };
  const setLevel = (r, level) => {
    const read = r.actions.filter(a => a.level === 'read').map(a => a.permission);
    const write = r.actions.filter(a => a.level === 'write').map(a => a.permission);
    const extra = r.actions.filter(a => a.level === 'extra').map(a => a.permission);
    const next = new Set(perms);
    [...read, ...write].forEach(p => next.delete(p));
    if (level === 'none') extra.forEach(p => next.delete(p));
    if (level === 'read' || level === 'write') read.forEach(p => next.add(p));
    if (level === 'write') write.forEach(p => next.add(p));
    onChange(next);
  };
  return (
    <div className="flex flex-col divide-y rounded-xl border" style={{ borderColor: 'var(--border-glass)' }}>
      {catalogue.map(r => {
        const level = levelOf(r, perms);
        const hasRead = r.actions.some(a => a.level === 'read');
        const hasWrite = r.actions.some(a => a.level === 'write');
        const extras = r.actions.filter(a => a.level === 'extra');
        return (
          <div key={r.key} className="p-3 flex flex-col gap-2" style={{ borderColor: 'var(--border-glass)' }}>
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <div>
                <div className="text-sm font-bold" style={{ color: 'var(--text-main)' }}>{r.label}</div>
                <div className="text-[11px]" style={{ color: 'var(--text-muted)' }}>{r.description}</div>
              </div>
              {(hasRead || hasWrite) && (
                <div className="flex rounded-lg overflow-hidden border text-[11px] font-bold" style={{ borderColor: 'var(--border-glass)' }}>
                  {[['none', 'None'], ...(hasRead ? [['read', 'Read']] : []), ...(hasWrite ? [['write', 'Write']] : [])].map(([v, l]) => (
                    <button key={v} type="button" disabled={readOnly} onClick={() => setLevel(r, v)}
                      className={`px-3 py-1.5 ${level === v ? 'bg-sky-600 text-white' : ''}`}
                      style={level === v ? undefined : { color: 'var(--text-sub)' }}>{l}</button>
                  ))}
                </div>
              )}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {r.actions.map(a => {
                const on = perms.has(a.permission);
                const inBase = base ? base.has(a.permission) : null;
                const changed = base && on !== inBase;
                return (
                  <button key={a.permission} type="button" disabled={readOnly} onClick={() => set([a.permission], !on)}
                    title={`${a.permission}${changed ? (on ? ' - granted to this person' : ' - removed for this person') : ''}`}
                    className={`text-[11px] px-2 py-1 rounded-md border flex items-center gap-1 ${on ? 'bg-emerald-500/10 border-emerald-500/40 text-emerald-700 dark:text-emerald-300' : ''} ${changed ? 'ring-2 ring-amber-400/70' : ''}`}
                    style={on ? undefined : { borderColor: 'var(--border-glass)', color: 'var(--text-muted)' }}>
                    {on ? <Check className="w-3 h-3" /> : <Minus className="w-3 h-3" />}
                    {a.level === 'extra' && <Lock className="w-3 h-3 opacity-60" />}
                    {a.label}
                  </button>
                );
              })}
            </div>
            {extras.length > 0 && level === 'none' && extras.some(a => perms.has(a.permission)) && (
              <div className="text-[10px] text-amber-600">Extra switches are on while the section is set to None.</div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function Modal({ title, onClose, children, footer, wide }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-[85] flex items-center justify-center p-3 sm:p-6" role="dialog" aria-modal="true" aria-label={title}>
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className={`relative w-full ${wide ? 'max-w-5xl' : 'max-w-lg'} max-h-[92vh] flex flex-col rounded-2xl shadow-2xl overflow-hidden border`}
        style={{ backgroundColor: 'var(--bg-card, var(--bg-main))', borderColor: 'var(--border-glass)' }}>
        <div className="px-6 py-4 border-b flex items-center justify-between" style={{ borderColor: 'var(--border-glass)' }}>
          <h2 className="text-base font-black" style={{ color: 'var(--text-main)' }}>{title}</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="w-8 h-8 rounded-full flex items-center justify-center" style={{ color: 'var(--text-sub)' }}><X className="w-4 h-4" /></button>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-5">{children}</div>
        {footer && <div className="px-6 py-3 border-t flex justify-end gap-2" style={{ borderColor: 'var(--border-glass)' }}>{footer}</div>}
      </div>
    </div>
  );
}

const Btn = ({ children, tone = 'primary', ...props }) => {
  const tones = {
    primary: 'bg-sky-600 hover:bg-sky-500 text-white',
    danger: 'bg-rose-600 hover:bg-rose-500 text-white',
    ghost: '',
  };
  return (
    <button type="button" {...props} className={`px-3 py-2 text-xs font-bold rounded-lg flex items-center gap-1.5 disabled:opacity-50 ${tones[tone]}`}
      style={tone === 'ghost' ? { color: 'var(--text-sub)' } : undefined}>{children}</button>
  );
};

// ---------------------------------------------------------------------------------------------------------------
function PersonEditor({ person, me, roles, catalogue, companies, onClose, onSaved }) {
  const actorSuper = isSuperAdmin(me);
  const charityIds = [ALL, ...companies.filter(c => c.id !== 'all').map(c => c.id)];
  const charityName = (id) => (id === ALL ? 'All charities (incl. future ones)' : (companies.find(c => c.id === id)?.name || id));
  const rolePerms = (rid) => new Set(roles.find(r => r.id === Number(rid))?.permissions || []);

  const [details, setDetails] = useState({ display_name: person.display_name, email: person.email, username: person.username, password: '' });
  const [access, setAccess] = useState(() => Object.fromEntries(person.access.map(a => [a.company_id, a.role_id ?? '']))); // company -> role id | '' (custom)
  const [overrides, setOverrides] = useState(() => {
    const m = {};
    person.overrides.forEach(o => { (m[o.company_id] ||= {})[o.permission] = o.effect; });
    return m;
  });
  const [scopes, setScopes] = useState(() => {
    const m = {};
    person.scopes.filter(s => s.resource === 'fundraiser').forEach(s => { (m[s.company_id] ||= []).push(s.record_id); });
    return m;
  });
  const [editing, setEditing] = useState(null); // charity whose permissions are open
  const [scopeOptions, setScopeOptions] = useState({});
  const [scopeSearch, setScopeSearch] = useState({}); // charity -> search text for the fundraiser picker
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  const loadScopeOptions = (comp) => {
    if (comp === ALL || scopeOptions[comp]) return;
    api(`/api/rbac/scope-options?company_id=${encodeURIComponent(comp)}&resource=fundraiser`)
      .then(d => setScopeOptions(o => ({ ...o, [comp]: d.options }))).catch(() => {});
  };

  const effectiveFor = (comp) => {
    const base = access[comp] !== undefined ? rolePerms(access[comp]) : (access[ALL] !== undefined ? rolePerms(access[ALL]) : new Set());
    const out = new Set(base);
    [ALL, comp].forEach(scope => Object.entries(overrides[scope] || {}).forEach(([p, eff]) => (eff === 'grant' ? out.add(p) : out.delete(p))));
    return { base, out };
  };

  const setGridPerms = (comp, next) => {
    // store the difference from the preset as this charity's overrides
    const base = access[comp] !== undefined ? rolePerms(access[comp]) : (access[ALL] !== undefined && comp !== ALL ? rolePerms(access[ALL]) : new Set());
    const inherited = new Set(base);
    if (comp !== ALL) Object.entries(overrides[ALL] || {}).forEach(([p, eff]) => (eff === 'grant' ? inherited.add(p) : inherited.delete(p)));
    const o = {};
    catalogue.flatMap(r => r.actions.map(a => a.permission)).forEach(p => {
      if (next.has(p) && !inherited.has(p)) o[p] = 'grant';
      if (!next.has(p) && inherited.has(p)) o[p] = 'deny';
    });
    ['logs.view', 'status.view'].forEach(p => { const keep = (overrides[comp] || {})[p]; if (keep) o[p] = keep; });
    setOverrides(prev => ({ ...prev, [comp]: o }));
  };

  const saveDetails = async () => {
    setBusy(true); setMsg(null);
    try {
      const body = { display_name: details.display_name, email: details.email, username: details.username };
      if (details.password) body.password = details.password;
      await api(`/api/rbac/users/${person.id}`, 'PUT', body);
      setMsg({ ok: true, text: details.password ? 'Saved. The password was reset and their sessions were ended.' : 'Saved.' });
      setDetails(d => ({ ...d, password: '' }));
      onSaved();
    } catch (e) { setMsg({ ok: false, text: e.message }); } finally { setBusy(false); }
  };

  const saveAccess = async () => {
    setBusy(true); setMsg(null);
    try {
      const body = {
        access: Object.entries(access).map(([company_id, rid]) => ({ company_id, role_id: rid === '' ? null : Number(rid) })),
        overrides: Object.entries(overrides).flatMap(([company_id, m]) => Object.entries(m)
          .filter(([, eff]) => eff).map(([permission, effect]) => ({ company_id, permission, effect }))),
        scopes: Object.entries(scopes).flatMap(([company_id, ids]) => ids.map(record_id => ({ company_id, resource: 'fundraiser', record_id }))),
      };
      await api(`/api/rbac/users/${person.id}/access`, 'PUT', body);
      setMsg({ ok: true, text: 'Access saved. It applies to their open session within a few seconds.' });
      onSaved();
    } catch (e) { setMsg({ ok: false, text: e.message }); } finally { setBusy(false); }
  };

  const simple = async (fn, okText) => {
    setBusy(true); setMsg(null);
    try { await fn(); setMsg({ ok: true, text: okText }); onSaved(); } catch (e) { setMsg({ ok: false, text: e.message }); } finally { setBusy(false); }
  };

  const isSelf = person.id === me?.id;
  const locked = person.is_super_admin && !actorSuper;

  return (
    <Modal wide title={`${person.display_name || person.username} - ${person.email}`} onClose={onClose}
      footer={<><Btn tone="ghost" onClick={onClose}>Close</Btn></>}>
      <div className="flex flex-col gap-5">
        {msg && <div className={`text-xs rounded-lg px-3 py-2 border ${msg.ok ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-500/25' : 'bg-rose-500/10 text-rose-600 border-rose-500/25'}`}>{msg.text}</div>}
        {locked && <div className="text-xs rounded-lg px-3 py-2 bg-amber-500/10 text-amber-700 border border-amber-500/25">Super admin accounts can only be changed by a super admin.</div>}

        <section className="glass-panel p-4 flex flex-col gap-3">
          <div className="text-xs font-black uppercase tracking-wider" style={{ color: 'var(--text-sub)' }}>Account</div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {[['display_name', 'Name'], ['email', 'Email'], ['username', 'Username'], ['password', 'New password (leave empty to keep)']].map(([k, label]) => (
              <label key={k} className="flex flex-col gap-1">
                <span className="text-[11px] font-semibold" style={{ color: 'var(--text-sub)' }}>{label}</span>
                <input type={k === 'password' ? 'password' : 'text'} value={details[k] || ''} disabled={locked} autoComplete="new-password"
                  onChange={e => setDetails(d => ({ ...d, [k]: e.target.value }))} className="px-2.5 py-2 text-sm rounded-lg" style={inputStyle} />
              </label>
            ))}
          </div>
          <div className="flex flex-wrap gap-2 justify-end">
            {!isSelf && !locked && (
              <Btn tone="ghost" disabled={busy} onClick={() => simple(() => api(`/api/rbac/users/${person.id}`, 'PUT', { is_active: !person.is_active }),
                person.is_active ? 'Account disabled - they were signed out.' : 'Account enabled.')}>
                {person.is_active ? 'Disable account' : 'Enable account'}
              </Btn>
            )}
            {!locked && <Btn tone="ghost" disabled={busy} onClick={() => simple(() => api(`/api/rbac/users/${person.id}/sign-out`, 'POST'), 'All their sessions were ended.')}><LogOut className="w-3.5 h-3.5" /> Sign out everywhere</Btn>}
            {actorSuper && !isSelf && (
              <Btn tone="ghost" disabled={busy} onClick={() => {
                if (!window.confirm(person.is_super_admin ? 'Remove super admin from this person?' : 'Make this person a super admin? They will have every permission in every charity.')) return;
                simple(() => api(`/api/rbac/users/${person.id}/super-admin`, 'POST', { is_super_admin: !person.is_super_admin }), 'Saved.');
              }}><ShieldCheck className="w-3.5 h-3.5" /> {person.is_super_admin ? 'Remove super admin' : 'Make super admin'}</Btn>
            )}
            {!locked && <Btn disabled={busy} onClick={saveDetails}><Save className="w-3.5 h-3.5" /> Save account</Btn>}
          </div>
        </section>

        {person.is_super_admin ? (
          <div className="text-sm" style={{ color: 'var(--text-sub)' }}>Super admins have every permission in every charity.</div>
        ) : (
          <section className="glass-panel p-4 flex flex-col gap-3">
            <div className="flex items-center justify-between">
              <div className="text-xs font-black uppercase tracking-wider" style={{ color: 'var(--text-sub)' }}>Access per charity</div>
              <div className="text-[11px]" style={{ color: 'var(--text-muted)' }}>A charity-specific row wins over "All charities".</div>
            </div>
            {isSelf && <div className="text-xs text-amber-600">You can't change your own access.</div>}
            <div className="flex flex-col gap-2">
              {charityIds.map(comp => {
                const has = access[comp] !== undefined;
                const hidden = String(access[comp]) === '0';
                const { base, out } = effectiveFor(comp);
                const nOver = Object.keys(overrides[comp] || {}).length;
                return (
                  <div key={comp} className="rounded-xl border p-3 flex flex-col gap-2" style={{ borderColor: 'var(--border-glass)' }}>
                    <div className="flex items-center gap-3 flex-wrap">
                      <div className="min-w-[200px] text-sm font-bold" style={{ color: 'var(--text-main)' }}>{charityName(comp)}</div>
                      <select value={has ? String(access[comp]) : 'none'} disabled={isSelf}
                        onChange={e => {
                          const v = e.target.value;
                          setAccess(a => { const n = { ...a }; if (v === 'none') delete n[comp]; else n[comp] = v === 'custom' ? '' : v; return n; });
                          if (v === 'none' || v === '0') { setOverrides(o => ({ ...o, [comp]: {} })); setScopes(s => ({ ...s, [comp]: [] })); }
                        }}
                        className="px-2 py-1.5 text-xs rounded-lg" style={inputStyle}>
                        <option value="none">{comp === ALL ? 'Not set' : (access[ALL] !== undefined ? 'Same as "All charities"' : 'No access')}</option>
                        {roles.map(r => <option key={r.id} value={String(r.id)}>{r.name}</option>)}
                        <option value="custom">Custom (only what's switched on below)</option>
                        {comp !== ALL && <option value="0">Hidden - this charity doesn't exist for them</option>}
                      </select>
                      {hidden && <span className="text-[11px] text-rose-600">Hidden: not listed, not reachable, nothing shown.</span>}
                      {!hidden && (has || (comp !== ALL && access[ALL] !== undefined)) && (
                        <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
                          {out.size} permissions{nOver ? ` · ${nOver} changed for this person` : ''}{(scopes[comp] || []).length ? ` · limited to ${scopes[comp].length} fundraiser(s)` : ''}
                        </span>
                      )}
                      {!hidden && (has || (comp !== ALL && access[ALL] !== undefined)) && !isSelf && (
                        <Btn tone="ghost" onClick={() => { setEditing(editing === comp ? null : comp); loadScopeOptions(comp); }}>
                          {editing === comp ? 'Hide permissions' : 'Adjust permissions'}
                        </Btn>
                      )}
                    </div>
                    {editing === comp && !hidden && (
                      <div className="flex flex-col gap-3">
                        <PermissionGrid catalogue={catalogue.filter(r => !['logs', 'status'].includes(r.key))} perms={out} base={base} onChange={next => setGridPerms(comp, next)} />
                        {comp !== ALL && (
                          <div className="rounded-xl border p-3 flex flex-col gap-2" style={{ borderColor: 'var(--border-glass)' }}>
                            <div className="text-xs font-bold" style={{ color: 'var(--text-main)' }}>Limit to specific fundraisers (optional)</div>
                            <div className="text-[11px]" style={{ color: 'var(--text-muted)' }}>When any are picked, this person only sees those fundraisers in {charityName(comp)}.</div>
                            <div className="flex items-center gap-2 flex-wrap">
                              <input type="search" value={scopeSearch[comp] || ''} placeholder="Search fundraisers…"
                                onChange={e => setScopeSearch(q => ({ ...q, [comp]: e.target.value }))}
                                className="px-2.5 py-1.5 text-xs rounded-lg w-64" style={inputStyle} />
                              <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
                                {(scopes[comp] || []).length} picked
                                {(scopes[comp] || []).length > 0 && (
                                  <button type="button" className="ml-2 underline" onClick={() => setScopes(s => ({ ...s, [comp]: [] }))}>clear</button>
                                )}
                              </span>
                            </div>
                            <div className="flex flex-wrap gap-1.5 max-h-48 overflow-y-auto">
                              {(scopeOptions[comp] || [])
                                .filter(o => {
                                  const q = (scopeSearch[comp] || '').trim().toLowerCase();
                                  return !q || (o.label || '').toLowerCase().includes(q) || (scopes[comp] || []).includes(o.id);
                                })
                                .sort((a, b) => Number((scopes[comp] || []).includes(b.id)) - Number((scopes[comp] || []).includes(a.id)))  // picked first
                                .map(o => {
                                const on = (scopes[comp] || []).includes(o.id);
                                return (
                                  <button key={o.id} type="button" onClick={() => setScopes(s => ({ ...s, [comp]: on ? (s[comp] || []).filter(x => x !== o.id) : [...(s[comp] || []), o.id] }))}
                                    className={`text-[11px] px-2 py-1 rounded-md border ${on ? 'bg-violet-500/10 border-violet-500/40 text-violet-700 dark:text-violet-300' : ''}`}
                                    style={on ? undefined : { borderColor: 'var(--border-glass)', color: 'var(--text-muted)' }}>{o.label}</button>
                                );
                              })}
                              {!scopeOptions[comp] && <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>Loading…</span>}
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
            {actorSuper && (
              <div className="rounded-xl border p-3 flex flex-col gap-2 border-amber-400/40 bg-amber-500/5">
                <div className="text-xs font-bold" style={{ color: 'var(--text-main)' }}>Ops console (Ctrl+Alt+O) - only a super admin can change this</div>
                <div className="text-[11px]" style={{ color: 'var(--text-muted)' }}>For the charities ticked (and only where the person also has access).</div>
                {[['logs.view', 'Activity log (who did what)'], ['status.view', 'Service status (integrations, mailboxes, sync, backups)']].map(([perm, label]) => (
                  <div key={perm} className="flex flex-wrap items-center gap-3">
                    <span className="text-xs font-semibold min-w-[260px]" style={{ color: 'var(--text-main)' }}>{label}</span>
                    {charityIds.map(comp => {
                      const on = (overrides[comp] || {})[perm] === 'grant';
                      return (
                        <label key={comp} className="flex items-center gap-1.5 text-xs" style={{ color: 'var(--text-main)' }}>
                          <input type="checkbox" checked={on} onChange={() => setOverrides(o => {
                            const m = { ...(o[comp] || {}) };
                            if (on) delete m[perm]; else m[perm] = 'grant';
                            return { ...o, [comp]: m };
                          })} /> {charityName(comp)}
                        </label>
                      );
                    })}
                  </div>
                ))}
              </div>
            )}
            {!isSelf && <div className="flex justify-end"><Btn disabled={busy} onClick={saveAccess}><Save className="w-3.5 h-3.5" /> Save access</Btn></div>}
          </section>
        )}
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------------------------------------------------------
function PresetEditor({ preset, catalogue, onClose, onSaved, superAdmin }) {
  const [name, setName] = useState(preset?.name || '');
  const [description, setDescription] = useState(preset?.description || '');
  const [perms, setPerms] = useState(new Set(preset?.permissions || []));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const save = async () => {
    setBusy(true); setError('');
    try {
      const body = { name, description, permissions: [...perms] };
      if (preset?.id) await api(`/api/rbac/roles/${preset.id}`, 'PUT', body); else await api('/api/rbac/roles', 'POST', body);
      onSaved(); onClose();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  return (
    <Modal wide title={preset?.id ? `Preset: ${preset.name}` : 'New preset'} onClose={onClose}
      footer={<><Btn tone="ghost" onClick={onClose}>Cancel</Btn><Btn disabled={busy || !name.trim()} onClick={save}><Save className="w-3.5 h-3.5" /> Save preset</Btn></>}>
      <div className="flex flex-col gap-3">
        {preset?.users > 0 && <div className="text-xs rounded-lg px-3 py-2 bg-sky-500/10 text-sky-700 dark:text-sky-300 border border-sky-500/25">{preset.users} people use this preset - saving changes their access straight away.</div>}
        {error && <div className="text-xs rounded-lg px-3 py-2 bg-rose-500/10 text-rose-600 border border-rose-500/25">{error}</div>}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <label className="flex flex-col gap-1"><span className="text-[11px] font-semibold" style={{ color: 'var(--text-sub)' }}>Name</span>
            <input value={name} onChange={e => setName(e.target.value)} className="px-2.5 py-2 text-sm rounded-lg" style={inputStyle} /></label>
          <label className="flex flex-col gap-1"><span className="text-[11px] font-semibold" style={{ color: 'var(--text-sub)' }}>Description</span>
            <input value={description} onChange={e => setDescription(e.target.value)} className="px-2.5 py-2 text-sm rounded-lg" style={inputStyle} /></label>
        </div>
        <PermissionGrid catalogue={superAdmin ? catalogue : catalogue.filter(r => !['logs', 'status'].includes(r.key))} perms={perms} onChange={setPerms} />
      </div>
    </Modal>
  );
}

function NewPerson({ onClose, onCreated }) {
  const [f, setF] = useState({ display_name: '', email: '', password: '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const save = async () => {
    setBusy(true); setError('');
    try { const d = await api('/api/rbac/users', 'POST', f); onCreated(d.id); onClose(); } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  return (
    <Modal title="Add a person" onClose={onClose}
      footer={<><Btn tone="ghost" onClick={onClose}>Cancel</Btn><Btn disabled={busy} onClick={save}><UserPlus className="w-3.5 h-3.5" /> Create</Btn></>}>
      <div className="flex flex-col gap-3">
        <p className="text-xs" style={{ color: 'var(--text-muted)' }}>They get no access until you give them a preset for a charity (next step).</p>
        {error && <div className="text-xs rounded-lg px-3 py-2 bg-rose-500/10 text-rose-600 border border-rose-500/25">{error}</div>}
        {[['display_name', 'Name', 'text'], ['email', 'Email', 'email'], ['password', 'Temporary password (10+ characters)', 'password']].map(([k, l, t]) => (
          <label key={k} className="flex flex-col gap-1"><span className="text-[11px] font-semibold" style={{ color: 'var(--text-sub)' }}>{l}</span>
            <input type={t} value={f[k]} autoComplete="new-password" onChange={e => setF(p => ({ ...p, [k]: e.target.value }))} className="px-2.5 py-2 text-sm rounded-lg" style={inputStyle} /></label>
        ))}
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------------------------------------------------------
export default function AccessView({ user, companies = [], onChanged }) {
  const [tab, setTab] = useState('people');
  const [catalogue, setCatalogue] = useState([]);
  const [roles, setRoles] = useState([]);
  const [people, setPeople] = useState([]);
  const [error, setError] = useState('');
  const [openPerson, setOpenPerson] = useState(null);
  const [openPreset, setOpenPreset] = useState(null); // preset object | 'new'
  const [adding, setAdding] = useState(false);
  const canManage = canSomewhere(user, 'users.manage');
  const canPresets = canSomewhere(user, 'users.presets');

  const load = () => {
    Promise.all([api('/api/rbac/catalogue'), api('/api/rbac/roles'), api('/api/rbac/users')])
      .then(([c, r, u]) => { setCatalogue(c.resources); setRoles(r.roles); setPeople(u.users); setError(''); })
      .catch(e => setError(e.message));
  };
  useEffect(load, []);
  const reloadAll = () => { load(); onChanged?.(); };

  const person = useMemo(() => people.find(p => p.id === openPerson), [people, openPerson]);
  const charityName = (id) => (id === ALL ? 'All charities' : (companies.find(c => c.id === id)?.short_code || id));

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-lg font-black flex items-center gap-2" style={{ color: 'var(--text-main)' }}><KeyRound className="w-5 h-5 text-sky-500" /> Users & Access</h2>
          <p className="text-xs" style={{ color: 'var(--text-muted)' }}>Who can see and do what, per charity. Changes apply to open sessions within seconds and are checked by the server on every request.</p>
        </div>
        <div className="flex gap-2">
          {tab === 'people' && canManage && <Btn onClick={() => setAdding(true)}><UserPlus className="w-4 h-4" /> Add person</Btn>}
          {tab === 'presets' && canPresets && <Btn onClick={() => setOpenPreset('new')}><Plus className="w-4 h-4" /> New preset</Btn>}
        </div>
      </div>
      <div className="flex gap-1 p-1 rounded-xl w-fit border" style={{ borderColor: 'var(--border-glass)' }}>
        {[['people', 'People'], ['presets', 'Presets']].map(([id, label]) => (
          <button key={id} type="button" onClick={() => setTab(id)} className={`px-4 py-1.5 text-xs font-bold rounded-lg ${tab === id ? 'bg-sky-600 text-white' : ''}`}
            style={tab === id ? undefined : { color: 'var(--text-sub)' }}>{label}</button>
        ))}
      </div>
      {error && <div className="text-xs rounded-lg px-3 py-2 bg-rose-500/10 text-rose-600 border border-rose-500/25">{error}</div>}

      {tab === 'people' && (
        <div className="glass-panel overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="text-left text-[11px] uppercase tracking-wider" style={{ color: 'var(--text-sub)' }}>
              <th className="px-4 py-3">Person</th><th className="px-4 py-3">Access</th><th className="px-4 py-3">Status</th><th className="px-4 py-3" />
            </tr></thead>
            <tbody>
              {people.map(p => (
                <tr key={p.id} className="border-t" style={{ borderColor: 'var(--border-glass)' }}>
                  <td className="px-4 py-3">
                    <div className="font-bold" style={{ color: 'var(--text-main)' }}>{p.display_name || p.username}{p.id === user?.id && <span className="ml-2 text-[10px] font-semibold text-sky-500">you</span>}</div>
                    <div className="text-xs" style={{ color: 'var(--text-muted)' }}>{p.email}</div>
                  </td>
                  <td className="px-4 py-3">
                    {p.is_super_admin ? <span className="text-[11px] font-black px-2 py-0.5 rounded-md bg-rose-500/10 text-rose-600">SUPER ADMIN - everything</span> : (
                      <div className="flex flex-wrap gap-1">
                        {p.access.length === 0 && <span className="text-xs text-amber-600">No access yet</span>}
                        {p.access.map(a => (
                          <span key={a.company_id} className="text-[11px] px-2 py-0.5 rounded-md border" style={{ borderColor: 'var(--border-glass)', color: 'var(--text-sub)' }}>
                            {charityName(a.company_id)}: <b>{a.role_id === 0 ? 'Hidden' : (a.role_name || 'Custom')}</b>
                          </span>
                        ))}
                        {p.overrides.length > 0 && <span className="text-[11px] px-2 py-0.5 rounded-md bg-amber-500/10 text-amber-700">{p.overrides.length} adjusted</span>}
                        {p.scopes.length > 0 && <span className="text-[11px] px-2 py-0.5 rounded-md bg-violet-500/10 text-violet-700">{p.scopes.length} fundraiser limit(s)</span>}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3">{p.is_active ? <span className="text-xs text-emerald-600">Active</span> : <span className="text-xs text-rose-600">Disabled</span>}</td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex justify-end gap-1">
                      {canManage && <Btn tone="ghost" onClick={() => setOpenPerson(p.id)}>Manage</Btn>}
                      {isSuperAdmin(user) && p.id !== user?.id && (
                        <Btn tone="ghost" onClick={() => {
                          if (!window.confirm(`Delete ${p.email}? This can't be undone (disabling keeps the account).`)) return;
                          api(`/api/rbac/users/${p.id}`, 'DELETE').then(reloadAll).catch(e => setError(e.message));
                        }}><Trash2 className="w-3.5 h-3.5" /></Btn>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === 'presets' && (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {roles.map(r => (
            <div key={r.id} className="glass-panel p-4 flex flex-col gap-2">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="font-black" style={{ color: 'var(--text-main)' }}>{r.name}</div>
                  <div className="text-xs" style={{ color: 'var(--text-muted)' }}>{r.description}</div>
                </div>
                <span className="text-[10px] px-2 py-0.5 rounded-md border whitespace-nowrap" style={{ borderColor: 'var(--border-glass)', color: 'var(--text-sub)' }}>{r.users} people</span>
              </div>
              <div className="flex flex-wrap gap-1">
                {catalogue.map(res => {
                  const lvl = levelOf(res, new Set(r.permissions));
                  const extras = res.actions.filter(a => a.level === 'extra' && r.permissions.includes(a.permission)).length;
                  if (lvl === 'none' && !extras) return null;
                  return <span key={res.key} className="text-[10px] px-1.5 py-0.5 rounded bg-slate-500/10" style={{ color: 'var(--text-sub)' }}>{res.label}: {lvl === 'none' ? '' : lvl}{extras ? ` +${extras}` : ''}</span>;
                })}
              </div>
              {canPresets && (
                <div className="flex gap-1 justify-end mt-auto">
                  <Btn tone="ghost" onClick={() => setOpenPreset({ ...r, id: null, name: `${r.name} (copy)`, users: 0 })}><Copy className="w-3.5 h-3.5" /> Copy</Btn>
                  {r.users === 0 && <Btn tone="ghost" onClick={() => { if (window.confirm(`Delete preset ${r.name}?`)) api(`/api/rbac/roles/${r.id}`, 'DELETE').then(reloadAll).catch(e => setError(e.message)); }}><Trash2 className="w-3.5 h-3.5" /></Btn>}
                  <Btn onClick={() => setOpenPreset(r)}>Edit</Btn>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {adding && <NewPerson onClose={() => setAdding(false)} onCreated={(id) => { load(); setOpenPerson(id); }} />}
      {person && <PersonEditor person={person} me={user} roles={roles} catalogue={catalogue} companies={companies}
        onClose={() => setOpenPerson(null)} onSaved={reloadAll} />}
      {openPreset && <PresetEditor superAdmin={isSuperAdmin(user)} preset={openPreset === 'new' ? null : openPreset} catalogue={catalogue}
        onClose={() => setOpenPreset(null)} onSaved={reloadAll} />}
    </div>
  );
}
