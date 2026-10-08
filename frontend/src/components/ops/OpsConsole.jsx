import React, { useCallback, useEffect, useState } from 'react';
import {
  X, Activity, ScrollText, KeyRound, RefreshCw, Loader2, CheckCircle2, AlertTriangle, XCircle, ChevronDown, ChevronRight, Radio, Upload
} from 'lucide-react';
import { API_BASE_URL } from '../../config';

const STATE_STYLE = {
  ok: { cls: 'text-emerald-600 bg-emerald-50 dark:bg-emerald-950/40 border-emerald-200 dark:border-emerald-900', Icon: CheckCircle2, label: 'Working' },
  warning: { cls: 'text-amber-700 bg-amber-50 dark:bg-amber-950/40 border-amber-200 dark:border-amber-900', Icon: AlertTriangle, label: 'Needs attention' },
  down: { cls: 'text-rose-700 bg-rose-50 dark:bg-rose-950/40 border-rose-200 dark:border-rose-900', Icon: XCircle, label: 'Not working' }
};
const LEVEL_CLS = {
  info: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300',
  warning: 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300',
  error: 'bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300',
  critical: 'bg-rose-600 text-white'
};
const fmtAge = (iso) => {
  if (!iso) return 'never';
  const mins = (Date.now() - new Date(iso).getTime()) / 60000;
  if (mins < 1) return 'just now';
  if (mins < 60) return `${Math.round(mins)} min ago`;
  if (mins < 48 * 60) return `${Math.round(mins / 60)} h ago`;
  return `${Math.round(mins / 1440)} days ago`;
};
const fmtLeft = (mins) => {
  if (mins === null || mins === undefined) return '—';
  if (mins <= 0) return 'expired';
  if (mins < 60) return `${Math.round(mins)} min left`;
  if (mins < 48 * 60) return `${Math.round(mins / 60)} h left`;
  return `${Math.round(mins / 1440)} days left`;
};

const getJson = async (url, opts) => {
  const r = await fetch(`${API_BASE_URL}${url}`, opts);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || `HTTP ${r.status}`);
  return j;
};

function StateBadge({ state }) {
  const s = STATE_STYLE[state] || STATE_STYLE.warning;
  return <span className={`px-2 py-0.5 rounded-full border text-[11px] font-bold inline-flex items-center gap-1 ${s.cls}`}><s.Icon className="w-3 h-3" />{s.label}</span>;
}

function StatusTab() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const load = useCallback((live = false) => {
    setLoading(true); setError('');
    getJson(`/api/ops/status${live ? '?live=true' : ''}`).then(setData).catch(e => setError(e.message)).finally(() => setLoading(false));
  }, []);
  useEffect(() => { load(); const t = setInterval(() => load(), 60000); return () => clearInterval(t); }, [load]);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          {data && <StateBadge state={data.overall} />}
          <span className="text-slate-500">Checked {data ? fmtAge(data.checked_at) : '—'} · refreshes every minute</span>
        </div>
        <div className="flex gap-2">
          <button type="button" onClick={() => load(false)} className="px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 font-semibold flex items-center gap-1.5">
            {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />} Refresh
          </button>
          <button type="button" onClick={() => load(true)} className="px-2.5 py-1.5 rounded-lg bg-blue-600 text-white font-semibold flex items-center gap-1.5" title="Makes one read-only API call to each platform with the stored session">
            <Radio className="w-3.5 h-3.5" /> Live API check
          </button>
        </div>
      </div>
      {error && <div className="p-3 rounded-lg bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300">{error}</div>}
      {data && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {data.platforms.map(p => (
              <div key={p.platform} className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 flex flex-col gap-2">
                <div className="flex items-center justify-between">
                  <span className="font-bold text-sm capitalize">{p.platform === 'givebrite' ? 'GiveBrite (Iqra)' : 'Madinah (Iqra)'}</span>
                  <StateBadge state={p.state} />
                </div>
                {p.issues.length > 0 && (
                  <ul className="list-disc pl-4 text-rose-700 dark:text-rose-300 flex flex-col gap-0.5">{p.issues.map((i, n) => <li key={n}>{i}</li>)}</ul>
                )}
                <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-slate-600 dark:text-slate-300">
                  <span>Last successful sync</span><span className="font-semibold">{fmtAge(p.sync?.last_ok_at)}</span>
                  <span>Failures in a row</span><span className="font-semibold">{p.sync?.consecutive_failures ?? 0}</span>
                  <span>Last API status</span><span className="font-semibold">{p.sync?.last_http_status ?? '—'}</span>
                  <span>Access token</span><span className="font-semibold">{p.token.present ? fmtLeft(p.token.access_minutes_left) : 'missing'}</span>
                  {p.platform === 'madinah' && (<><span>Refresh token</span><span className="font-semibold">{fmtLeft(p.token.refresh_minutes_left)}</span></>)}
                  <span>Session renewed</span><span className="font-semibold">{fmtAge(p.sync?.last_token_refresh_at || p.token.retrieved_at)}</span>
                  <span>Last new donation</span><span className="font-semibold">{fmtAge(p.sync?.last_ingested_at)}</span>
                </div>
                {p.sync?.last_error && <div className="text-[11px] text-slate-500">Last error ({fmtAge(p.sync.last_error_at)}): {p.sync.last_error}</div>}
                {p.live_check && (
                  <div className={`text-[11px] font-semibold ${p.live_check.ok ? 'text-emerald-600' : 'text-rose-600'}`}>
                    Live check: {p.live_check.ok ? 'API answered normally' : `failed (${p.live_check.http_status || 'error'}) ${p.live_check.detail || ''}`}
                  </div>
                )}
              </div>
            ))}
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800">
              <div className="font-bold mb-2">Background services</div>
              {data.services.map(s => (
                <div key={s.name} className="flex justify-between"><span>{s.name}</span>
                  <span className={s.active === 'active' ? 'text-emerald-600 font-bold' : 'text-rose-600 font-bold'}>{s.active}</span></div>
              ))}
              <div className="text-slate-500 mt-1">Heartbeat {fmtAge(data.sync_heartbeat)}</div>
            </div>
            <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800">
              <div className="font-bold mb-2">Outlook mailboxes</div>
              {data.outlook.map(o => (
                <div key={o.company_id} className="flex flex-col mb-1.5">
                  <span className="flex justify-between"><span className="capitalize">{o.company_id}</span>
                    <span className={o.connected ? 'text-emerald-600 font-bold' : 'text-rose-600 font-bold'}>{o.connected ? 'connected' : 'not connected'}</span></span>
                  <span className="text-slate-500 truncate">{o.mailbox || '—'}{o.last_send ? ` · last ${o.last_send.event === 'email.sent' ? 'sent' : 'FAILED'} ${fmtAge(o.last_send.ts)}` : ''}</span>
                </div>
              ))}
            </div>
            <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800">
              <div className="font-bold mb-2">Logging pipeline</div>
              <div className="flex justify-between"><span>Axiom ({data.logging.dataset})</span>
                <span className={data.logging.configured ? 'text-emerald-600 font-bold' : 'text-rose-600 font-bold'}>{data.logging.configured ? 'configured' : 'missing token'}</span></div>
              <div className="text-slate-500">Last shipped {fmtAge(data.logging.axiom_last_ok)} · backlog {data.logging.backlog} · dropped {data.logging.axiom_dropped}</div>
              {data.logging.axiom_last_error && <div className="text-rose-600 text-[11px]">{data.logging.axiom_last_error}</div>}
              <div className="mt-1">Errors in last 24h: <strong className={data.logging.errors_last_24h ? 'text-rose-600' : ''}>{data.logging.errors_last_24h}</strong></div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

const RANGES = { '1h': 1, '24h': 24, '7d': 168, '30d': 720 };

function LogsTab() {
  const [filters, setFilters] = useState({ category: 'all', level: 'all', company_id: 'all', search: '', range: '24h' });
  const [data, setData] = useState({ items: [], total: 0, categories: [] });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState(null);
  const [auto, setAuto] = useState(true);
  const [page, setPage] = useState(0);
  const [source, setSource] = useState('local');
  const [apl, setApl] = useState("['rethink_crm_app_logs'] | where level in ('error', 'critical') | sort by _time desc | take 100");
  const [axiomResult, setAxiomResult] = useState(null);
  const pageSize = 100;

  const load = useCallback(() => {
    if (source !== 'local') return;
    setLoading(true); setError('');
    const p = new URLSearchParams({ limit: pageSize, offset: page * pageSize, since: new Date(Date.now() - RANGES[filters.range] * 3600000).toISOString() });
    ['category', 'level', 'company_id', 'search'].forEach(k => { if (filters[k] && filters[k] !== 'all') p.set(k, filters[k]); });
    getJson(`/api/ops/logs?${p}`).then(setData).catch(e => setError(e.message)).finally(() => setLoading(false));
  }, [filters, page, source]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (!auto || source !== 'local') return undefined; const t = setInterval(load, 15000); return () => clearInterval(t); }, [auto, load, source]);

  const runApl = () => {
    setLoading(true); setError('');
    getJson(`/api/ops/logs?source=axiom&since_hours=${RANGES[filters.range]}&apl=${encodeURIComponent(apl)}`)
      .then(r => setAxiomResult(r.result)).catch(e => setError(e.message)).finally(() => setLoading(false));
  };
  const set = (k, v) => { setPage(0); setFilters(f => ({ ...f, [k]: v })); };
  const axiomRows = axiomResult?.matches || [];

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end gap-2">
        <div className="flex bg-slate-100 dark:bg-slate-800 p-0.5 rounded-lg">
          {['local', 'axiom'].map(s => (
            <button key={s} type="button" onClick={() => setSource(s)} className={`px-2.5 py-1 rounded-md font-semibold ${source === s ? 'bg-white dark:bg-slate-900 text-blue-600 shadow-2xs' : 'text-slate-500'}`}>
              {s === 'local' ? 'This server' : 'Axiom (APL)'}
            </button>
          ))}
        </div>
        <select value={filters.range} onChange={e => set('range', e.target.value)} className="px-2 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900">
          {Object.keys(RANGES).map(r => <option key={r} value={r}>Last {r}</option>)}
        </select>
        {source === 'local' && (
          <>
            <select value={filters.category} onChange={e => set('category', e.target.value)} className="px-2 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900">
              <option value="all">All categories</option>{data.categories.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
            <select value={filters.level} onChange={e => set('level', e.target.value)} className="px-2 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900">
              <option value="all">All levels</option><option value="warning">Warnings + errors</option><option value="error">Errors only</option><option value="info">Info only</option>
            </select>
            <select value={filters.company_id} onChange={e => set('company_id', e.target.value)} className="px-2 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900">
              <option value="all">Both charities</option><option value="rethink">Rethink</option><option value="iqra">Iqra</option>
            </select>
            <input value={filters.search} onChange={e => set('search', e.target.value)} placeholder="Search message, email, event…"
              className="px-2 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 w-56" />
            <label className="flex items-center gap-1.5 ml-auto"><input type="checkbox" checked={auto} onChange={e => setAuto(e.target.checked)} /> Auto-refresh</label>
            <button type="button" onClick={load} className="px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 flex items-center gap-1">
              {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
            </button>
          </>
        )}
      </div>
      {source === 'axiom' && (
        <div className="flex gap-2">
          <input value={apl} onChange={e => setApl(e.target.value)} className="flex-1 px-2 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 font-mono" />
          <button type="button" onClick={runApl} className="px-3 py-1.5 rounded-lg bg-blue-600 text-white font-semibold">{loading ? 'Running…' : 'Run'}</button>
        </div>
      )}
      {error && <div className="p-2 rounded-lg bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300">{error}</div>}

      <div className="rounded-xl border border-slate-200 dark:border-slate-800 overflow-hidden">
        <div className="max-h-[55vh] overflow-y-auto divide-y divide-slate-100 dark:divide-slate-800">
          {(source === 'local' ? data.items : axiomRows.map((m, i) => ({ id: i, ts: m._time, ...m.data, data: m.data }))).map(it => (
            <div key={it.id} className="px-3 py-1.5 hover:bg-slate-50 dark:hover:bg-slate-900/60">
              <button type="button" onClick={() => setExpanded(expanded === it.id ? null : it.id)} className="w-full text-left flex items-center gap-2">
                {expanded === it.id ? <ChevronDown className="w-3 h-3 shrink-0" /> : <ChevronRight className="w-3 h-3 shrink-0" />}
                <span className="font-mono text-[10px] text-slate-500 shrink-0 w-36">{(it.ts || '').replace('T', ' ').slice(0, 19)}</span>
                <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold shrink-0 ${LEVEL_CLS[it.level] || LEVEL_CLS.info}`}>{it.level}</span>
                <span className="font-mono text-[10px] text-blue-600 shrink-0 w-44 truncate">{it.event}</span>
                {it.company_id && <span className="text-[10px] text-slate-500 shrink-0">{it.company_id}</span>}
                <span className="truncate text-slate-700 dark:text-slate-200">{it.message}</span>
                {it.actor && <span className="ml-auto text-[10px] text-slate-400 shrink-0">{it.actor}</span>}
              </button>
              {expanded === it.id && (
                <pre className="mt-1.5 ml-5 p-2 rounded-lg bg-slate-950 text-slate-100 text-[10px] overflow-x-auto">{JSON.stringify({ service: it.service, category: it.category, ...it.data }, null, 2)}</pre>
              )}
            </div>
          ))}
          {source === 'local' && !loading && data.items.length === 0 && <div className="py-10 text-center text-slate-400">No events match.</div>}
        </div>
        {source === 'local' && (
          <div className="px-3 py-2 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between text-slate-500">
            <span>{data.total} event(s)</span>
            <span className="flex gap-2">
              <button type="button" disabled={page === 0} onClick={() => setPage(p => p - 1)} className="px-2 py-0.5 rounded border border-slate-200 dark:border-slate-700 disabled:opacity-40">Newer</button>
              <button type="button" disabled={(page + 1) * pageSize >= data.total} onClick={() => setPage(p => p + 1)} className="px-2 py-0.5 rounded border border-slate-200 dark:border-slate-700 disabled:opacity-40">Older</button>
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

function SessionsTab() {
  const [sessions, setSessions] = useState(null);
  const [form, setForm] = useState({ platform: 'madinah', accessToken: '', refreshToken: '' });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const load = () => getJson('/api/ops/platform-sessions').then(setSessions).catch(e => setMsg({ type: 'error', text: e.message }));
  useEffect(() => { load(); }, []);

  const upload = async () => {
    setBusy(true); setMsg(null);
    try {
      const r = await getJson(`/api/ops/platform-sessions/${form.platform}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ accessToken: form.accessToken, refreshToken: form.refreshToken || null, source: 'ops-console-paste' })
      });
      setMsg({ type: 'ok', text: `Verified and saved. Access token valid until ${new Date(r.access_expires_at).toLocaleString()}.` });
      setForm(f => ({ ...f, accessToken: '', refreshToken: '' }));
      load();
    } catch (e) { setMsg({ type: 'error', text: e.message }); } finally { setBusy(false); }
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {sessions && Object.entries(sessions).map(([p, s]) => (
          <div key={p} className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 grid grid-cols-2 gap-x-3 gap-y-1">
            <span className="col-span-2 font-bold capitalize text-sm mb-1">{p}</span>
            <span>Access token</span><span className="font-semibold">{s.present ? fmtLeft(s.access_minutes_left) : 'missing'}</span>
            {s.refresh_minutes_left !== undefined && (<><span>Refresh token</span><span className="font-semibold">{fmtLeft(s.refresh_minutes_left)}</span></>)}
            <span>Captured</span><span className="font-semibold">{fmtAge(s.retrieved_at)}</span>
            <span>By</span><span className="font-semibold truncate">{s.captured_by || 'automatic renewal'}</span>
          </div>
        ))}
      </div>
      <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 flex flex-col gap-2">
        <div className="font-bold text-sm">Capture a new session (recommended)</div>
        <p className="text-slate-600 dark:text-slate-300">On your own computer, run the capture script. It opens a normal browser window, you log in yourself, and it uploads the session here. The server checks the token against the platform before saving it.</p>
        <pre className="p-2 rounded-lg bg-slate-950 text-slate-100 text-[11px] overflow-x-auto">node scripts/capture_platform_session.js madinah{'\n'}node scripts/capture_platform_session.js givebrite</pre>
      </div>
      <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 flex flex-col gap-2">
        <div className="font-bold text-sm flex items-center gap-1.5"><Upload className="w-4 h-4" /> Or paste tokens manually</div>
        <div className="flex gap-2">
          {['madinah', 'givebrite'].map(p => (
            <button key={p} type="button" onClick={() => setForm(f => ({ ...f, platform: p }))}
              className={`px-2.5 py-1 rounded-md border font-semibold capitalize ${form.platform === p ? 'border-blue-500 text-blue-600' : 'border-slate-200 dark:border-slate-700 text-slate-500'}`}>{p}</button>
          ))}
        </div>
        <textarea value={form.accessToken} onChange={e => setForm(f => ({ ...f, accessToken: e.target.value }))} rows={3} placeholder="Access token (Bearer …)"
          className="px-2 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 font-mono text-[11px]" />
        {form.platform === 'madinah' && (
          <textarea value={form.refreshToken} onChange={e => setForm(f => ({ ...f, refreshToken: e.target.value }))} rows={3} placeholder="Refresh token (Madinah only, keeps the session renewing for 7 days at a time)"
            className="px-2 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 font-mono text-[11px]" />
        )}
        <button type="button" disabled={busy || !form.accessToken.trim()} onClick={upload} className="self-start px-3 py-1.5 rounded-lg bg-blue-600 text-white font-semibold disabled:opacity-50 flex items-center gap-1.5">
          {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />} Verify &amp; save
        </button>
        {msg && <div className={`p-2 rounded-lg ${msg.type === 'ok' ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300' : 'bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300'}`}>{msg.text}</div>}
      </div>
    </div>
  );
}

/** Hidden operations console (super admins). Opened with the key sequence wired in App.jsx. */
export default function OpsConsole({ onClose }) {
  const [tab, setTab] = useState('status');
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  const tabs = [['status', Activity, 'Status'], ['logs', ScrollText, 'Logs'], ['sessions', KeyRound, 'Sessions']];
  return (
    <div className="fixed inset-0 z-[80] bg-black/60 backdrop-blur-xs flex items-center justify-center p-4" onClick={onClose}>
      <div className="w-full max-w-6xl max-h-[92vh] overflow-y-auto rounded-2xl bg-white dark:bg-slate-950 border border-slate-200 dark:border-slate-800 shadow-2xl text-xs text-slate-700 dark:text-slate-200"
        onClick={e => e.stopPropagation()}>
        <div className="sticky top-0 z-10 px-5 py-3 bg-white/95 dark:bg-slate-950/95 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="font-bold text-sm">Ops console</span>
            <div className="flex bg-slate-100 dark:bg-slate-800 p-0.5 rounded-lg">
              {tabs.map(([id, Icon, label]) => (
                <button key={id} type="button" onClick={() => setTab(id)}
                  className={`px-2.5 py-1 rounded-md font-semibold flex items-center gap-1 ${tab === id ? 'bg-white dark:bg-slate-900 text-blue-600 shadow-2xs' : 'text-slate-500'}`}>
                  <Icon className="w-3.5 h-3.5" /> {label}
                </button>
              ))}
            </div>
          </div>
          <button type="button" onClick={onClose} className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800"><X className="w-4 h-4" /></button>
        </div>
        <div className="p-5">
          {tab === 'status' && <StatusTab />}
          {tab === 'logs' && <LogsTab />}
          {tab === 'sessions' && <SessionsTab />}
        </div>
      </div>
    </div>
  );
}
