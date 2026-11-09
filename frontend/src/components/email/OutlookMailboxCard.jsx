import React, { useEffect, useState } from 'react';
import { Mail, RefreshCw, Send } from 'lucide-react';
import { API_BASE_URL } from '../../config';
import { can } from '../../access';

/**
 * A Microsoft 365 mailbox of its own inside a charity, e.g. Sisters' Project in Rethink's workspace: emails with the
 * SP templates are sent from it (never from Rethink's mailbox), and replies to it are recorded under the charity.
 * Connecting / switching / disconnecting needs mailbox.configure; it signs in through the charity's Azure app.
 */
export default function OutlookMailboxCard({ mailbox = 'sp_rethink', label = "Sisters' Project", company = 'rethink', user }) {
  const [st, setSt] = useState(null);
  const [busy, setBusy] = useState('');
  const [testTo, setTestTo] = useState('');
  const [msg, setMsg] = useState(null);
  const canConfigure = can(user, 'mailbox.configure', company);

  const load = () => fetch(`${API_BASE_URL}/api/tracker/outlook/status?company_id=${mailbox}`)
    .then(r => r.json()).then(setSt).catch(e => setSt({ error: e.message }));
  useEffect(() => { load(); }, [mailbox]); // eslint-disable-line react-hooks/exhaustive-deps

  const run = async (key, fn) => {
    setBusy(key); setMsg(null);
    try { await fn(); } catch (e) { setMsg({ type: 'err', text: e.message }); } finally { setBusy(''); load(); }
  };
  const post = async (url, body) => {
    const r = await fetch(`${API_BASE_URL}${url}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
    const d = await r.json().catch(() => ({}));
    if (!r.ok || d.status === 'failed') throw new Error(d.detail || d.message || `Request failed (${r.status})`);
    return d;
  };
  const connect = () => run('connect', async () => {
    const r = await fetch(`${API_BASE_URL}/api/tracker/outlook/auth-url?company_id=${mailbox}&redirect_uri=${encodeURIComponent(`${window.location.origin}/sponsorship-tracker`)}`);
    const d = await r.json().catch(() => ({}));
    if (!d.auth_url) throw new Error(d.detail || "Couldn't start the Microsoft sign-in.");
    window.location.href = d.auth_url;
  });

  const connected = !!st?.connected;
  return (
    <div className="bg-white dark:bg-slate-900 p-5 rounded-2xl border-2 border-pink-200 dark:border-pink-900 shadow-sm flex flex-col gap-3">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <div className={`p-3.5 rounded-2xl ${connected ? 'bg-pink-600 text-white shadow-lg shadow-pink-500/20' : 'bg-slate-100 dark:bg-slate-800 text-slate-400'}`}>
            <Mail className="w-7 h-7" />
          </div>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="text-lg font-black text-slate-800 dark:text-white">{label} mailbox</h3>
              <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-pink-50 text-pink-700 border border-pink-200 dark:bg-pink-950/50 dark:text-pink-300 dark:border-pink-800">Microsoft 365 · separate account</span>
              <span className={`px-2.5 py-0.5 rounded-full text-xs font-bold ${connected
                ? 'bg-emerald-50 text-emerald-600 dark:bg-emerald-950/60 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800'
                : 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400'}`}>{connected ? 'Connected' : 'Not connected'}</span>
            </div>
            <p className="text-xs md:text-sm text-slate-500 dark:text-slate-400 mt-1">
              {connected
                ? <>Emails using the <b>{label}</b> templates are sent from <b className="font-mono text-pink-700 dark:text-pink-300">{st.connected_email}</b>. Replies to it are tracked too.</>
                : <>Emails using the <b>{label}</b> templates are sent from this account only - they won't go out until it is connected (they never fall back to the main mailbox).</>}
            </p>
            {st?.error && <p className="text-xs text-rose-600 mt-1">{st.error}</p>}
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <button type="button" onClick={load} title="Refresh" className="p-2 rounded-xl border border-slate-200 dark:border-slate-700 text-slate-500 hover:text-pink-600"><RefreshCw className="w-4 h-4" /></button>
          {canConfigure && (connected ? <>
            <button type="button" disabled={!!busy} onClick={connect} title="Sign in with a different Microsoft account for this mailbox"
              className="px-4 py-2 rounded-xl bg-pink-600 hover:bg-pink-700 disabled:opacity-60 text-white font-bold text-xs shadow-md flex items-center gap-2">
              <Mail className="w-4 h-4" /> Switch / Change Account
            </button>
            <button type="button" disabled={!!busy}
              onClick={() => { if (window.confirm(`Disconnect the ${label} mailbox? ${label} emails can't be sent until an account is connected again.`)) run('disc', () => post(`/api/tracker/outlook/disconnect?company_id=${mailbox}`)); }}
              className="px-4 py-2 rounded-xl bg-rose-50 dark:bg-rose-950/60 text-rose-600 dark:text-rose-400 border border-rose-200 dark:border-rose-800 text-xs font-bold hover:bg-rose-100">
              Disconnect
            </button>
          </> : (
            <button type="button" disabled={!!busy} onClick={connect}
              className="px-5 py-2.5 rounded-xl bg-pink-600 hover:bg-pink-700 disabled:opacity-60 text-white font-bold text-xs md:text-sm shadow-md flex items-center gap-2">
              <Mail className="w-4 h-4" /> Connect {label} Microsoft 365
            </button>
          ))}
        </div>
      </div>
      {canConfigure && connected && (
        <div className="flex items-center gap-2 flex-wrap text-xs">
          <input type="email" value={testTo} onChange={e => setTestTo(e.target.value)} placeholder="Send a test email to…"
            className="px-3 py-1.5 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-950 text-slate-900 dark:text-slate-100 w-64" />
          <button type="button" disabled={!!busy || !testTo.includes('@')}
            onClick={() => run('test', async () => { const d = await post('/api/tracker/outlook/test-send', { company_id: mailbox, recipient_email: testTo }); setMsg({ type: 'ok', text: d.message }); })}
            className="px-3 py-1.5 rounded-lg border border-pink-300 text-pink-700 dark:text-pink-300 dark:border-pink-800 font-semibold disabled:opacity-50 flex items-center gap-1">
            <Send className="w-3.5 h-3.5" /> {busy === 'test' ? 'Sending…' : 'Send test'}
          </button>
        </div>
      )}
      {canConfigure && <p className="text-[11px] text-slate-500 dark:text-slate-400">Signs in through Rethink's Azure app - on Microsoft's page, pick the {label} account (not Rethink's).</p>}
      {msg && <div className={`text-xs rounded-lg px-3 py-2 ${msg.type === 'ok' ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300' : 'bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300'}`}>{msg.text}</div>}
    </div>
  );
}
