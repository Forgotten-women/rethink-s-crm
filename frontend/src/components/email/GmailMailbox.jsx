import React, { useEffect, useState } from 'react';
import { CheckCircle2, ExternalLink, Mail, RefreshCw, Send, Unplug, XCircle } from 'lucide-react';
import { API_BASE_URL } from '../../config';
import { can } from '../../access';
import { FIELD, LABEL, post } from './emailUi';
import { localTime } from './EmailThread';

export const GMAIL_REDIRECT_PATH = '/gmail-callback';
const redirectUri = () => `${window.location.origin}${GMAIL_REDIRECT_PATH}`;

/** Email > Mailbox for a charity that uses Google: connect its Gmail account (OAuth), test it, see reply syncing. */
export default function GmailMailbox({ company, user }) {
  const [st, setSt] = useState(null);
  const [creds, setCreds] = useState({ client_id: '', client_secret: '' });
  const [testTo, setTestTo] = useState('office@rethinkcharity.org.uk');
  const [busy, setBusy] = useState('');
  const [msg, setMsg] = useState(null);
  const isSuper = can(user, 'mailbox.configure', company); // name kept: gates connect / disconnect
  const load = () => fetch(`${API_BASE_URL}/api/mailbox/status?company_id=${encodeURIComponent(company)}`)
    .then(r => (r.ok ? r.json() : null)).then(setSt).catch(() => setSt(null));
  useEffect(() => { load(); }, [company]); // eslint-disable-line react-hooks/exhaustive-deps

  const run = async (name, fn) => {
    setBusy(name); setMsg(null);
    try { await fn(); } catch (e) { setMsg({ type: 'error', text: e.message }); } finally { setBusy(''); load(); }
  };
  const connect = () => run('connect', async () => {
    const r = await fetch(`${API_BASE_URL}/api/mailbox/gmail/auth-url?company_id=${company}&redirect_uri=${encodeURIComponent(redirectUri())}`);
    const d = await r.json().catch(() => ({}));
    if (!r.ok || !d.auth_url) throw new Error(d.detail || `Error ${r.status}`);
    window.location.href = d.auth_url;
  });

  const card = 'rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-5';
  const btn = 'px-3 py-2 rounded-lg text-xs font-bold flex items-center gap-1.5 disabled:opacity-50';
  if (!st) return <div className={`${card} text-xs text-slate-500`}>Loading…</div>;

  return (
    <div className="flex flex-col gap-4">
      <div className={`${card} flex flex-col md:flex-row md:items-center justify-between gap-4`}>
        <div className="flex items-center gap-4">
          <div className={`p-3.5 rounded-2xl ${st.connected ? 'bg-rose-500 text-white' : 'bg-slate-100 dark:bg-slate-800 text-slate-400'}`}><Mail className="w-7 h-7" /></div>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="text-lg font-black text-slate-800 dark:text-white">Gmail (Google Workspace)</h3>
              <span className={`px-2.5 py-0.5 rounded-full text-xs font-bold ${st.connected ? 'bg-emerald-50 text-emerald-700 border border-emerald-200 dark:bg-emerald-950/50 dark:text-emerald-300 dark:border-emerald-800' : 'bg-slate-100 text-slate-500 dark:bg-slate-800'}`}>{st.connected ? 'Connected' : 'Not connected'}</span>
            </div>
            <p className="text-xs text-slate-500 mt-1">
              {st.connected
                ? <>Emails to donors are sent from <b className="text-slate-800 dark:text-slate-100">{st.connected_email}</b>; replies are picked up from its inbox every minute{st.last_reply_sync_at ? ` (last check ${localTime(st.last_reply_sync_at)})` : ''}.</>
                : `${company.toUpperCase()} sends with Gmail. Configured mailbox: ${st.connected_email || 'donorcare@iqracharity.org'}. Press Connect with Google to sign in.`}
            </p>
            {st.last_error && <p className="text-xs text-rose-600 mt-1">{st.last_error}</p>}
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {st.connected && <button type="button" disabled={!!busy} onClick={() => run('sync', async () => { const r = await post(`/api/mailbox/sync-replies?company_id=${company}`, {}); setMsg({ type: 'ok', text: `Inbox checked: ${r.synced_new_replies || 0} new repl${r.synced_new_replies === 1 ? 'y' : 'ies'}.` }); })}
            className={`${btn} border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-200`}><RefreshCw className={`w-3.5 h-3.5 ${busy === 'sync' ? 'animate-spin' : ''}`} />Check for replies</button>}
          {isSuper && st.client_id_set && <button type="button" disabled={!!busy} onClick={connect} className={`${btn} bg-sky-600 hover:bg-sky-700 text-white`}><ExternalLink className="w-3.5 h-3.5" />{st.connected ? 'Reconnect' : 'Connect with Google'}</button>}
          {isSuper && st.connected && <button type="button" disabled={!!busy} onClick={() => { if (window.confirm('Disconnect this Gmail account? The CRM stops sending and reading replies until it is connected again.')) run('disc', () => post(`/api/mailbox/gmail/disconnect?company_id=${company}`, {})); }}
            className={`${btn} border border-rose-200 text-rose-600 dark:border-rose-900`}><Unplug className="w-3.5 h-3.5" />Disconnect</button>}
        </div>
      </div>

      {msg && <div className={`rounded-xl px-3 py-2 text-xs border ${msg.type === 'ok' ? 'bg-emerald-50 text-emerald-800 border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-300 dark:border-emerald-900' : 'bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-950/40 dark:text-rose-300 dark:border-rose-900'}`}>{msg.text}</div>}

      {st.connected && isSuper && (
        <div className={`${card} flex flex-col sm:flex-row sm:items-end gap-2`}>
          <label className={`${LABEL} flex-1`}>Send a test email to
            <input value={testTo} onChange={e => setTestTo(e.target.value)} className={`${FIELD} px-2.5 py-2 text-sm normal-case font-normal tracking-normal`} />
          </label>
          <button type="button" disabled={!!busy || !testTo.includes('@')} onClick={() => run('test', async () => { const r = await post('/api/mailbox/test-send', { company_id: company, recipient_email: testTo }); setMsg({ type: 'ok', text: r.message }); })}
            className={`${btn} bg-emerald-600 hover:bg-emerald-700 text-white`}><Send className="w-3.5 h-3.5" />Send test</button>
        </div>
      )}

      {isSuper && (
        <div className={card}>
          <div className="text-sm font-black text-slate-800 dark:text-white mb-1">{st.client_id_set ? 'Google app (OAuth client)' : 'Set up - one time'}</div>
          {st.client_id_set && (
            <div className="text-xs text-slate-500 mb-3 space-y-1">
              <div>Saved client: <code>{st.client_id}</code>. Replace it only if you created a new one.</div>
              {st.service_account_id && <div>Service account: <code>{st.service_account_id}</code></div>}
              {st.connected_email && <div>Sending mailbox: <b>{st.connected_email}</b></div>}
            </div>
          )}
          <ol className="text-xs text-slate-600 dark:text-slate-300 list-decimal pl-5 space-y-1.5 mb-4">
            <li>Signed in as an admin of {company.toUpperCase()}'s Google account, open <a className="text-sky-600 underline" href="https://console.cloud.google.com/projectcreate" target="_blank" rel="noreferrer">Google Cloud</a> and create a project (e.g. “{company.toUpperCase()} CRM”).</li>
            <li>APIs &amp; Services → Library → enable the <b>Gmail API</b>.</li>
            <li>OAuth consent screen → User type <b>Internal</b> if {company.toUpperCase()} uses Google Workspace (then nothing else is needed); for a plain @gmail.com account choose External, add the account as a test user, then <b>Publish app</b> - otherwise Google signs the CRM out every 7 days.</li>
            <li>Credentials → Create credentials → <b>OAuth client ID</b> → type <b>Web application</b>. Under “Authorised redirect URIs” add exactly:<br /><code className="select-all inline-block mt-1 px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 !text-slate-900 dark:!text-slate-100 font-mono">{redirectUri()}</code></li>
            <li>Copy the Client ID and Client secret below, save, then press <b>Connect with Google</b> and sign in with the mailbox emails should come from. Allow both permissions (send email, read inbox for replies).</li>
          </ol>
          <div className="grid grid-cols-1 md:grid-cols-[1fr_1fr_auto] gap-2 items-end">
            <label className={LABEL}>Client ID<input value={creds.client_id} onChange={e => setCreds(c => ({ ...c, client_id: e.target.value }))} placeholder="…apps.googleusercontent.com" className={`${FIELD} px-2.5 py-2 text-xs font-mono normal-case font-normal tracking-normal`} /></label>
            <label className={LABEL}>Client secret<input type="password" autoComplete="off" value={creds.client_secret} onChange={e => setCreds(c => ({ ...c, client_secret: e.target.value }))} className={`${FIELD} px-2.5 py-2 text-xs font-mono normal-case font-normal tracking-normal`} /></label>
            <button type="button" disabled={!!busy || !creds.client_id.trim() || !creds.client_secret.trim()}
              onClick={() => run('creds', async () => { await post('/api/mailbox/gmail/credentials', { company_id: company, ...creds }); setCreds({ client_id: '', client_secret: '' }); setMsg({ type: 'ok', text: 'Saved. Now press Connect with Google.' }); })}
              className={`${btn} bg-slate-900 dark:bg-white dark:text-slate-900 text-white`}>Save</button>
          </div>
          <p className="text-[11px] text-slate-500 mt-3">Gmail sends up to 2,000 emails a day on Google Workspace (500 on a free @gmail.com account); bulk sends stop with a clear error once the limit is reached. The secret and sign-in are stored encrypted and never shown again.</p>
        </div>
      )}
      {!isSuper && !st.connected && <div className={`${card} text-xs text-slate-500 flex items-center gap-2`}><XCircle className="w-4 h-4 text-slate-400" />A super admin needs to connect {company.toUpperCase()}'s Gmail account.</div>}
      {st.connected && <div className="text-[11px] text-slate-500 flex items-center gap-1.5"><CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />Connected {st.connected_at ? localTime(st.connected_at) : ''}{st.connected_by ? ` by ${st.connected_by}` : ''}. Permissions: {st.scopes}.</div>}
    </div>
  );
}
