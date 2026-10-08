import React, { useCallback, useEffect, useState } from 'react';
import {
  X, Activity, ScrollText, KeyRound, RefreshCw, Loader2, CheckCircle2,
  AlertTriangle, XCircle, ChevronDown, ChevronRight, Radio, Upload,
  Database, Trash2, Copy, Check, Terminal
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

const fmtBytes = (b) => (b > 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.round((b || 0) / 1024)} KB`);

const getJson = async (url, opts) => {
  const r = await fetch(`${API_BASE_URL}${url}`, opts);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || `HTTP ${r.status}`);
  return j;
};

function CopyButton({ text, label = 'Copy', className = '' }) {
  const [copied, setCopied] = useState(false);
  const onCopy = (e) => {
    e.stopPropagation();
    navigator.clipboard?.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <button
      type="button"
      onClick={onCopy}
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-semibold transition-all ${
        copied
          ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
          : 'bg-slate-800/90 hover:bg-slate-700 text-slate-300 hover:text-white border border-slate-700/60 shadow-xs'
      } ${className}`}
      title={label}
    >
      {copied ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3 text-slate-400" />}
      <span>{copied ? 'Copied' : label}</span>
    </button>
  );
}

function TerminalBox({ commands }) {
  const allCmds = commands.map(c => c.cmd).join('\n');
  return (
    <div className="rounded-xl border border-slate-800 bg-[#090D16] overflow-hidden shadow-lg font-mono terminal-box">
      <div className="px-3.5 py-2 bg-slate-900/95 border-b border-slate-800 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-rose-500 inline-block" />
            <span className="w-2.5 h-2.5 rounded-full bg-amber-500 inline-block" />
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 inline-block" />
          </div>
          <span className="text-[11px] font-semibold text-slate-300 ml-1.5 flex items-center gap-1.5">
            <Terminal className="w-3.5 h-3.5 text-cyan-400" />
            bash / node
          </span>
        </div>
        <CopyButton text={allCmds} label="Copy all" />
      </div>
      <div className="p-3.5 flex flex-col gap-2.5 text-xs">
        {commands.map((c, i) => (
          <div key={i} className="flex items-center justify-between gap-3 group">
            <div className="flex items-center gap-2 overflow-x-auto select-all">
              <span className="text-emerald-400 font-bold select-none">$</span>
              <span className="text-slate-200">
                node scripts/capture_platform_session.js <span className={c.targetCls || 'text-cyan-400 font-bold'}>{c.platform}</span>
              </span>
            </div>
            <CopyButton text={c.cmd} label={c.platform} className="opacity-80 group-hover:opacity-100 shrink-0" />
          </div>
        ))}
      </div>
    </div>
  );
}

function CodeBlock({ json, title = 'JSON Payload' }) {
  const [copied, setCopied] = useState(false);
  const text = typeof json === 'string' ? json : JSON.stringify(json, null, 2);
  const onCopy = (e) => {
    e.stopPropagation();
    navigator.clipboard?.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <div className="rounded-xl border border-slate-800 bg-[#090D16] overflow-hidden shadow-md code-block">
      <div className="px-3.5 py-1.5 bg-slate-900/90 border-b border-slate-800 flex items-center justify-between">
        <span className="text-[11px] font-mono text-slate-300 font-semibold flex items-center gap-1.5">
          <Database className="w-3 h-3 text-cyan-400" />
          {title}
        </span>
        <button
          type="button"
          onClick={onCopy}
          className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold transition-all ${
            copied ? 'text-emerald-400 bg-emerald-500/10' : 'text-slate-300 hover:text-white bg-slate-800/80 border border-slate-700/60'
          }`}
        >
          {copied ? <Check className="w-2.5 h-2.5 text-emerald-400" /> : <Copy className="w-2.5 h-2.5 text-slate-400" />}
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre
        className="p-3.5 text-[11px] leading-relaxed overflow-x-auto font-mono text-slate-200"
        style={{ backgroundColor: '#090D16', color: '#E2E8F0', margin: 0 }}
      >
        <code style={{ color: '#E2E8F0' }}>{text}</code>
      </pre>
    </div>
  );
}

function StateBadge({ state }) {
  const s = STATE_STYLE[state] || STATE_STYLE.warning;
  return <span className={`px-2.5 py-0.5 rounded-full border text-[11px] font-bold inline-flex items-center gap-1 ${s.cls}`}><s.Icon className="w-3 h-3" />{s.label}</span>;
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
          <span className="text-slate-500 dark:text-slate-400 font-medium">Checked {data ? fmtAge(data.checked_at) : '—'} · refreshes every minute</span>
        </div>
        <div className="flex gap-2">
          <button type="button" onClick={() => load(false)} className="px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800 font-semibold flex items-center gap-1.5 transition-colors">
            {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />} Refresh
          </button>
          <button type="button" onClick={() => load(true)} className="px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-semibold flex items-center gap-1.5 shadow-sm shadow-blue-500/20 transition-colors" title="Makes one read-only API call to each platform with the stored session">
            <Radio className="w-3.5 h-3.5" /> Live API check
          </button>
        </div>
      </div>
      {error && <div className="p-3 rounded-xl bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300 border border-rose-200 dark:border-rose-900">{error}</div>}
      {data && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {data.platforms.map(p => (
              <div key={p.platform} className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/40 flex flex-col gap-2.5 shadow-2xs">
                <div className="flex items-center justify-between">
                  <span className="font-bold text-sm capitalize text-slate-900 dark:text-slate-100">{p.platform === 'givebrite' ? 'GiveBrite (Iqra)' : 'Madinah (Iqra)'}</span>
                  <StateBadge state={p.state} />
                </div>
                {p.issues.length > 0 && (
                  <ul className="list-disc pl-4 text-rose-700 dark:text-rose-300 flex flex-col gap-0.5">{p.issues.map((i, n) => <li key={n}>{i}</li>)}</ul>
                )}
                <div className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-slate-600 dark:text-slate-300 text-xs">
                  <span>Last successful sync</span><span className="font-semibold text-slate-900 dark:text-slate-100">{fmtAge(p.sync?.last_ok_at)}</span>
                  <span>Failures in a row</span><span className="font-semibold text-slate-900 dark:text-slate-100">{p.sync?.consecutive_failures ?? 0}</span>
                  <span>Last API status</span><span className="font-semibold text-slate-900 dark:text-slate-100">{p.sync?.last_http_status ?? '—'}</span>
                  <span>Access token</span><span className="font-semibold text-slate-900 dark:text-slate-100">{p.token.present ? fmtLeft(p.token.access_minutes_left) : 'missing'}</span>
                  {p.platform === 'madinah' && (<><span>Refresh token</span><span className="font-semibold text-slate-900 dark:text-slate-100">{fmtLeft(p.token.refresh_minutes_left)}</span></>)}
                  <span>Session renewed</span><span className="font-semibold text-slate-900 dark:text-slate-100">{fmtAge(p.sync?.last_token_refresh_at || p.token.retrieved_at)}</span>
                  <span>Last new donation</span><span className="font-semibold text-slate-900 dark:text-slate-100">{fmtAge(p.sync?.last_ingested_at)}</span>
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
            <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/40 shadow-2xs">
              <div className="font-bold mb-2 text-slate-900 dark:text-slate-100">Background services</div>
              {data.services.map(s => (
                <div key={s.name} className="flex justify-between py-0.5">
                  <span className="text-slate-600 dark:text-slate-300">{s.name}</span>
                  <span className={s.active === 'active' ? 'text-emerald-600 font-bold' : 'text-rose-600 font-bold'}>{s.active}</span>
                </div>
              ))}
              <div className="text-slate-500 mt-2 text-[11px]">Heartbeat {fmtAge(data.sync_heartbeat)}</div>
            </div>
            <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/40 shadow-2xs">
              <div className="font-bold mb-2 text-slate-900 dark:text-slate-100">Outlook mailboxes</div>
              {data.outlook.map(o => (
                <div key={o.company_id} className="flex flex-col mb-2">
                  <span className="flex justify-between">
                    <span className="capitalize font-semibold text-slate-800 dark:text-slate-200">{o.company_id}</span>
                    <span className={o.connected ? 'text-emerald-600 font-bold' : 'text-rose-600 font-bold'}>{o.connected ? 'connected' : 'not connected'}</span>
                  </span>
                  <span className="text-slate-500 truncate text-[11px]">{o.mailbox || '—'}{o.last_send ? ` · last ${o.last_send.event === 'email.sent' ? 'sent' : 'FAILED'} ${fmtAge(o.last_send.ts)}` : ''}</span>
                </div>
              ))}
            </div>
            <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/40 shadow-2xs">
              <div className="font-bold mb-2 text-slate-900 dark:text-slate-100">Logging pipeline</div>
              <div className="flex justify-between py-0.5">
                <span className="text-slate-600 dark:text-slate-300">Axiom ({data.logging.dataset})</span>
                <span className={data.logging.configured ? 'text-emerald-600 font-bold' : 'text-rose-600 font-bold'}>{data.logging.configured ? 'configured' : 'missing token'}</span>
              </div>
              <div className="text-slate-500 text-[11px] mt-1">Last shipped {fmtAge(data.logging.axiom_last_ok)} · backlog {data.logging.backlog} · dropped {data.logging.axiom_dropped}</div>
              {data.logging.axiom_last_error && <div className="text-rose-600 text-[11px] mt-1">{data.logging.axiom_last_error}</div>}
              <div className="mt-2 text-xs">Errors in last 24h: <strong className={data.logging.errors_last_24h ? 'text-rose-600 font-bold' : 'text-slate-700 dark:text-slate-300'}>{data.logging.errors_last_24h}</strong></div>
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
        <div className="flex bg-slate-100 dark:bg-slate-800 p-0.5 rounded-lg border border-slate-200 dark:border-slate-700/60">
          {['local', 'axiom'].map(s => (
            <button key={s} type="button" onClick={() => setSource(s)} className={`px-2.5 py-1 rounded-md font-semibold ${source === s ? 'bg-white dark:bg-slate-900 text-blue-600 dark:text-blue-400 shadow-2xs' : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-300'}`}>
              {s === 'local' ? 'This server' : 'Axiom (APL)'}
            </button>
          ))}
        </div>
        <select value={filters.range} onChange={e => set('range', e.target.value)} className="px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-800 dark:text-slate-200 text-xs">
          {Object.keys(RANGES).map(r => <option key={r} value={r}>Last {r}</option>)}
        </select>
        {source === 'local' && (
          <>
            <select value={filters.category} onChange={e => set('category', e.target.value)} className="px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-800 dark:text-slate-200 text-xs">
              <option value="all">All categories</option>{data.categories.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
            <select value={filters.level} onChange={e => set('level', e.target.value)} className="px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-800 dark:text-slate-200 text-xs">
              <option value="all">All levels</option><option value="warning">Warnings + errors</option><option value="error">Errors only</option><option value="info">Info only</option>
            </select>
            <select value={filters.company_id} onChange={e => set('company_id', e.target.value)} className="px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-800 dark:text-slate-200 text-xs">
              <option value="all">Both charities</option><option value="rethink">Rethink</option><option value="iqra">Iqra</option>
            </select>
            <input value={filters.search} onChange={e => set('search', e.target.value)} placeholder="Search message, email, event…"
              className="px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-800 dark:text-slate-200 placeholder:text-slate-400 w-56 text-xs" />
            <label className="flex items-center gap-1.5 ml-auto text-slate-600 dark:text-slate-300 text-xs select-none">
              <input type="checkbox" checked={auto} onChange={e => setAuto(e.target.checked)} className="rounded" /> Auto-refresh
            </label>
            <button type="button" onClick={load} className="px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800 flex items-center gap-1 transition-colors">
              {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
            </button>
          </>
        )}
      </div>
      {source === 'axiom' && (
        <div className="flex gap-2">
          <input value={apl} onChange={e => setApl(e.target.value)} className="flex-1 px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 font-mono text-xs text-slate-800 dark:text-slate-200" />
          <button type="button" onClick={runApl} className="px-4 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-semibold transition-colors shadow-sm">{loading ? 'Running…' : 'Run'}</button>
        </div>
      )}
      {error && <div className="p-3 rounded-xl bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300 border border-rose-200 dark:border-rose-900">{error}</div>}

      <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-950 overflow-hidden shadow-2xs">
        <div className="max-h-[55vh] overflow-y-auto divide-y divide-slate-100 dark:divide-slate-800/80">
          {(source === 'local' ? data.items : axiomRows.map((m, i) => ({ id: i, ts: m._time, ...m.data, data: m.data }))).map(it => (
            <div key={it.id} className="px-3 py-2 hover:bg-slate-50 dark:hover:bg-slate-900/60 transition-colors">
              <button type="button" onClick={() => setExpanded(expanded === it.id ? null : it.id)} className="w-full text-left flex items-center gap-2">
                {expanded === it.id ? <ChevronDown className="w-3.5 h-3.5 shrink-0 text-slate-500" /> : <ChevronRight className="w-3.5 h-3.5 shrink-0 text-slate-400" />}
                <span className="font-mono text-[10px] text-slate-500 shrink-0 w-36">{(it.ts || '').replace('T', ' ').slice(0, 19)}</span>
                <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold shrink-0 ${LEVEL_CLS[it.level] || LEVEL_CLS.info}`}>{it.level}</span>
                <span className="font-mono text-[10px] text-blue-600 dark:text-blue-400 font-semibold shrink-0 w-44 truncate">{it.event}</span>
                {it.company_id && <span className="text-[10px] text-slate-500 shrink-0 font-medium capitalize">{it.company_id}</span>}
                <span className="truncate text-slate-800 dark:text-slate-200">{it.message}</span>
                {it.actor && <span className="ml-auto text-[10px] text-slate-400 shrink-0">{it.actor}</span>}
              </button>
              {expanded === it.id && (
                <div className="mt-2 ml-5">
                  <CodeBlock json={{ service: it.service, category: it.category, ...it.data }} title={`${it.event} Payload`} />
                </div>
              )}
            </div>
          ))}
          {source === 'local' && !loading && data.items.length === 0 && <div className="py-12 text-center text-slate-400">No events match the selected filters.</div>}
        </div>
        {source === 'local' && (
          <div className="px-3.5 py-2.5 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between text-slate-500 bg-slate-50/50 dark:bg-slate-900/40 text-xs">
            <span>{data.total} event(s)</span>
            <span className="flex gap-2">
              <button type="button" disabled={page === 0} onClick={() => setPage(p => p - 1)} className="px-2.5 py-1 rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 disabled:opacity-40 font-medium transition-colors">Newer</button>
              <button type="button" disabled={(page + 1) * pageSize >= data.total} onClick={() => setPage(p => p + 1)} className="px-2.5 py-1 rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 disabled:opacity-40 font-medium transition-colors">Older</button>
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
    if (!form.accessToken.trim()) return;
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

  const captureCommands = [
    { platform: 'madinah', cmd: 'node scripts/capture_platform_session.js madinah', targetCls: 'text-cyan-400 font-bold' },
    { platform: 'givebrite', cmd: 'node scripts/capture_platform_session.js givebrite', targetCls: 'text-emerald-400 font-bold' }
  ];

  return (
    <div className="flex flex-col gap-4">
      {/* Session overview cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {sessions && Object.entries(sessions).map(([p, s]) => (
          <div key={p} className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/40 grid grid-cols-2 gap-x-3 gap-y-1.5 shadow-2xs text-xs">
            <div className="col-span-2 flex items-center justify-between mb-1">
              <span className="font-bold capitalize text-sm text-slate-900 dark:text-slate-100 flex items-center gap-1.5">
                <span className={`w-2 h-2 rounded-full ${s.present ? 'bg-emerald-500' : 'bg-rose-500'}`} />
                {p}
              </span>
              <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${s.present ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-900' : 'bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300 border border-rose-200 dark:border-rose-900'}`}>
                {s.present ? 'Active Session' : 'Missing'}
              </span>
            </div>
            <span className="text-slate-500 dark:text-slate-400 font-medium">Access token</span>
            <span className={`font-semibold ${s.access_minutes_left > 120 ? 'text-emerald-600 dark:text-emerald-400' : s.access_minutes_left > 0 ? 'text-amber-600 dark:text-amber-400' : 'text-slate-700 dark:text-slate-300'}`}>
              {s.present ? fmtLeft(s.access_minutes_left) : 'missing'}
            </span>
            {s.refresh_minutes_left !== undefined && (
              <>
                <span className="text-slate-500 dark:text-slate-400 font-medium">Refresh token</span>
                <span className="font-semibold text-slate-800 dark:text-slate-200">{fmtLeft(s.refresh_minutes_left)}</span>
              </>
            )}
            <span className="text-slate-500 dark:text-slate-400 font-medium">Captured</span>
            <span className="font-semibold text-slate-800 dark:text-slate-200">{fmtAge(s.retrieved_at)}</span>
            <span className="text-slate-500 dark:text-slate-400 font-medium">By</span>
            <span className="font-semibold truncate text-slate-800 dark:text-slate-200">{s.captured_by || 'automatic renewal'}</span>
          </div>
        ))}
      </div>

      {/* Recommended interactive capture commands */}
      <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/40 flex flex-col gap-2.5 shadow-2xs">
        <div className="font-bold text-sm text-slate-900 dark:text-slate-100 flex items-center gap-1.5">
          <Terminal className="w-4 h-4 text-blue-500" />
          Capture a new session (recommended)
        </div>
        <p className="text-slate-600 dark:text-slate-300 text-xs leading-relaxed">
          On your own computer, run the capture script. It opens a normal browser window, you log in yourself, and it uploads the session here. The server checks the token against the platform before saving it.
        </p>
        <TerminalBox commands={captureCommands} />
      </div>

      {/* Manual token paste */}
      <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/40 flex flex-col gap-3 shadow-2xs">
        <div className="font-bold text-sm text-slate-900 dark:text-slate-100 flex items-center gap-1.5">
          <Upload className="w-4 h-4 text-blue-500" />
          Or paste tokens manually
        </div>
        <div className="flex gap-2">
          {['madinah', 'givebrite'].map(p => (
            <button
              key={p}
              type="button"
              onClick={() => setForm(f => ({ ...f, platform: p }))}
              className={`px-3 py-1.5 rounded-lg font-bold text-xs capitalize transition-all ${
                form.platform === p
                  ? 'bg-blue-600 text-white shadow-sm shadow-blue-500/20'
                  : 'bg-slate-100 dark:bg-slate-800/80 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700'
              }`}
            >
              {p}
            </button>
          ))}
        </div>
        <div className="flex flex-col gap-1.5">
          <label className="text-[11px] font-semibold text-slate-700 dark:text-slate-300">
            Access token (Bearer string)
          </label>
          <textarea
            value={form.accessToken}
            onChange={e => setForm(f => ({ ...f, accessToken: e.target.value }))}
            rows={3}
            placeholder="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
            className="w-full px-3 py-2 rounded-xl border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-slate-100 placeholder:text-slate-400 dark:placeholder:text-slate-500 font-mono text-xs focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 outline-none transition-all"
          />
        </div>
        {form.platform === 'madinah' && (
          <div className="flex flex-col gap-1.5">
            <label className="text-[11px] font-semibold text-slate-700 dark:text-slate-300">
              Refresh token (Madinah only — keeps session renewing for 7 days at a time)
            </label>
            <textarea
              value={form.refreshToken}
              onChange={e => setForm(f => ({ ...f, refreshToken: e.target.value }))}
              rows={3}
              placeholder="Paste refresh token here..."
              className="w-full px-3 py-2 rounded-xl border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-slate-100 placeholder:text-slate-400 dark:placeholder:text-slate-500 font-mono text-xs focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 outline-none transition-all"
            />
          </div>
        )}
        <button
          type="button"
          disabled={busy || !form.accessToken.trim()}
          onClick={upload}
          className={`self-start px-4 py-2 rounded-xl font-bold text-xs flex items-center gap-2 transition-all ${
            !form.accessToken.trim() || busy
              ? 'bg-slate-200 dark:bg-slate-800 text-slate-400 dark:text-slate-500 cursor-not-allowed border border-slate-300/40 dark:border-slate-700/40'
              : 'bg-blue-600 hover:bg-blue-700 active:scale-[0.98] text-white shadow-md shadow-blue-500/25 cursor-pointer'
          }`}
        >
          {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin text-white" /> : <KeyRound className="w-3.5 h-3.5" />}
          <span>Verify &amp; save</span>
        </button>
        {msg && (
          <div className={`p-3 rounded-xl text-xs font-medium border ${msg.type === 'ok' ? 'bg-emerald-50 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300 border-emerald-200 dark:border-emerald-900' : 'bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300 border-rose-200 dark:border-rose-900'}`}>
            {msg.text}
          </div>
        )}
      </div>
    </div>
  );
}

function CacheTab() {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const load = useCallback(() => { getJson('/api/ops/cache').then(setData).catch(e => setError(e.message)); }, []);
  useEffect(() => { load(); const t = setInterval(load, 15000); return () => clearInterval(t); }, [load]);
  const clear = async () => {
    if (!window.confirm('Clear the whole response cache? Pages will be recomputed on their next visit.')) return;
    setBusy(true);
    try { await getJson('/api/ops/cache/clear', { method: 'POST' }); load(); } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  if (error) return <div className="p-3 rounded-xl bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300 border border-rose-200 dark:border-rose-900">{error}</div>;
  if (!data) return <div className="py-12 flex justify-center"><Loader2 className="w-5 h-5 animate-spin text-slate-400" /></div>;
  const worker = data.this_worker || {};
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div className="text-slate-600 dark:text-slate-300 text-xs">
          {data.enabled ? <span className="font-bold text-emerald-600 dark:text-emerald-400">Cache Enabled</span> : <span className="text-rose-600 font-bold">Disabled (CACHE_ENABLED=0)</span>} · {data.entries} entries · {fmtBytes(data.bytes)} of {fmtBytes(data.max_bytes)}
          <span className="text-slate-400 hidden sm:inline"> · invalidated automatically by DB triggers and timestamps</span>
        </div>
        <button type="button" disabled={busy} onClick={clear} className="px-3 py-1.5 rounded-xl border border-rose-200 dark:border-rose-900/60 bg-rose-50/50 dark:bg-rose-950/30 text-rose-600 dark:text-rose-400 hover:bg-rose-100 dark:hover:bg-rose-900/40 font-bold text-xs flex items-center gap-1.5 transition-colors disabled:opacity-50">
          <Trash2 className="w-3.5 h-3.5" /> Clear cache
        </button>
      </div>

      {/* Endpoints Table with sticky header */}
      <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-950 overflow-hidden shadow-2xs">
        <div className="max-h-[50vh] overflow-y-auto">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-slate-100 dark:bg-slate-900 text-slate-700 dark:text-slate-300 text-left font-bold text-[11px] uppercase tracking-wider border-b border-slate-200 dark:border-slate-800 z-10 shadow-2xs">
              <tr>
                {['Endpoint', 'Cached variants', 'Size', 'Hits (stored)', 'Avg compute', 'This worker: hits / misses'].map(h => (
                  <th key={h} className="px-3 py-2.5 font-bold">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800/80">
              {data.endpoints.sort((a, b) => b.avg_compute_ms - a.avg_compute_ms).map(e => (
                <tr key={e.endpoint} className="hover:bg-slate-50/80 dark:hover:bg-slate-900/60 transition-colors">
                  <td className="px-3 py-2 font-mono font-semibold text-slate-900 dark:text-slate-100">{e.endpoint}</td>
                  <td className="px-3 py-2 text-slate-700 dark:text-slate-300">{e.entries}</td>
                  <td className="px-3 py-2 text-slate-600 dark:text-slate-400 font-mono">{fmtBytes(e.bytes)}</td>
                  <td className="px-3 py-2 font-bold font-mono text-emerald-600 dark:text-emerald-400">{e.hits}</td>
                  <td className="px-3 py-2">
                    <span className={`px-2 py-0.5 rounded font-mono font-bold text-[11px] ${e.avg_compute_ms >= 500 ? 'bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300' : 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300'}`}>
                      {e.avg_compute_ms >= 1000 ? `${(e.avg_compute_ms / 1000).toFixed(1)} s` : `${e.avg_compute_ms} ms`}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-slate-600 dark:text-slate-400 font-mono">{worker[e.endpoint] ? `${worker[e.endpoint].hits} / ${worker[e.endpoint].misses}` : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Data versions accordion */}
      <details className="group rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/40 p-3.5 shadow-2xs">
        <summary className="cursor-pointer font-bold text-slate-800 dark:text-slate-200 flex items-center justify-between select-none">
          <span className="flex items-center gap-2 text-xs">
            <Database className="w-4 h-4 text-cyan-500" />
            Data versions cache
            <span className="text-[11px] font-normal text-slate-500 dark:text-slate-400">
              ({Object.keys(data.versions || {}).length} entities)
            </span>
          </span>
          <span className="text-[11px] text-blue-600 dark:text-blue-400 group-open:hidden font-semibold">Click to expand</span>
        </summary>
        <div className="mt-3">
          <CodeBlock json={data.versions} title="Cache Epoch & Data Versions" />
        </div>
      </details>
    </div>
  );
}

/** Hidden operations console (super admins). Opened with Ctrl+Alt+O or URL hash #ops */
export default function OpsConsole({ onClose, initialTab = 'status' }) {
  const [tab, setTab] = useState(['status', 'logs', 'sessions', 'cache'].includes(initialTab) ? initialTab : 'status');
  useEffect(() => {
    if (['status', 'logs', 'sessions', 'cache'].includes(initialTab)) setTab(initialTab);
  }, [initialTab]);
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  const tabs = [
    ['status', Activity, 'Status'],
    ['logs', ScrollText, 'Logs'],
    ['sessions', KeyRound, 'Sessions'],
    ['cache', Database, 'Cache']
  ];
  return (
    <div className="fixed inset-0 z-[80] bg-black/60 backdrop-blur-xs flex items-center justify-center p-4 animate-in fade-in duration-150" onClick={onClose}>
      <div
        className="w-full max-w-6xl max-h-[92vh] overflow-y-auto rounded-2xl bg-white dark:bg-slate-950 border border-slate-200 dark:border-slate-800 shadow-2xl text-xs text-slate-700 dark:text-slate-200"
        onClick={e => e.stopPropagation()}
      >
        {/* Solid opaque sticky header — completely blocks background bleed-through when scrolling */}
        <div className="sticky top-0 z-30 px-5 py-3.5 bg-white dark:bg-slate-950 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between shadow-xs">
          <div className="flex items-center gap-3">
            <span className="font-bold text-sm text-slate-900 dark:text-slate-100">Ops console</span>
            <div className="flex bg-slate-100 dark:bg-slate-800 p-0.5 rounded-lg border border-slate-200 dark:border-slate-700/60">
              {tabs.map(([id, Icon, label]) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => setTab(id)}
                  className={`px-3 py-1 rounded-md font-bold flex items-center gap-1.5 transition-all text-xs ${
                    tab === id
                      ? 'bg-white dark:bg-slate-900 text-blue-600 dark:text-blue-400 shadow-2xs'
                      : 'text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200'
                  }`}
                >
                  <Icon className="w-3.5 h-3.5" /> {label}
                </button>
              ))}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 transition-colors"
            title="Close (Esc)"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="p-5">
          {tab === 'status' && <StatusTab />}
          {tab === 'logs' && <LogsTab />}
          {tab === 'sessions' && <SessionsTab />}
          {tab === 'cache' && <CacheTab />}
        </div>
      </div>
    </div>
  );
}
