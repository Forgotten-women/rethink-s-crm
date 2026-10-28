import React, { useCallback, useEffect, useState } from 'react';
import {
  X, Activity, ScrollText, KeyRound, RefreshCw, Loader2, CheckCircle2,
  AlertTriangle, XCircle, ChevronDown, ChevronRight, Radio, Upload,
  Database, Trash2, Copy, Check, Terminal, Bookmark, Zap, ExternalLink
} from 'lucide-react';
import { API_BASE_URL } from '../../config';

const STATE_STYLE = {
  ok: { cls: 'text-emerald-600 bg-emerald-50 dark:bg-emerald-950/40 border-emerald-200 dark:border-emerald-900', Icon: CheckCircle2, label: 'Working' },
  warning: { cls: 'text-amber-700 bg-amber-50 dark:bg-amber-950/40 border-amber-200 dark:border-amber-900', Icon: AlertTriangle, label: 'Needs attention' },
  down: { cls: 'text-rose-700 bg-rose-50 dark:bg-rose-950/40 border-rose-200 dark:border-rose-900', Icon: XCircle, label: 'Not working' },
  not_configured: { cls: 'text-slate-600 bg-slate-100 dark:bg-slate-800 dark:text-slate-300 border-slate-200 dark:border-slate-700', Icon: AlertTriangle, label: 'Not set up' }
};
const ISSUE_CLS = { down: 'text-rose-700 dark:text-rose-300', warning: 'text-amber-700 dark:text-amber-300', ok: 'text-amber-700 dark:text-amber-300', not_configured: 'text-slate-600 dark:text-slate-300' };
// `command` in an issue becomes a copyable code chip
const IssueText = ({ text }) => String(text).split(/(`[^`]+`)/).map((part, i) => (part.startsWith('`') && part.endsWith('`')
  ? <code key={i} className="px-1 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-800 dark:text-slate-100 font-mono text-[10.5px] break-all select-all">{part.slice(1, -1)}</code>
  : <span key={i}>{part}</span>));
const OLD_ISSUE_MS = 24 * 60 * 60 * 1000;

const LEVEL_CLS = {
  info: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300',
  warning: 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300',
  error: 'bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300',
  critical: 'bg-rose-600 text-white'
};

const fmtAge = (iso) => {
  if (!iso || iso === 'nan' || iso === 'never') return 'never';
  const t = new Date(iso).getTime();
  if (isNaN(t)) return 'never';
  const mins = (Date.now() - t) / 60000;
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
  return <span className={`px-2.5 py-0.5 rounded-full border text-[11px] font-bold inline-flex items-center gap-1 shrink-0 whitespace-nowrap ${s.cls}`}><s.Icon className="w-3 h-3" />{s.label}</span>;
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
          {/* At most 4 per row: the console is a fixed-width window, so viewport breakpoints for 7 columns squeezed the cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
            {data.platforms.map(p => {
              const label = p.name || (
                            p.platform === 'givebrite_rethink' ? 'GiveBrite (Rethink)' :
                            (p.platform === 'givebrite_iqra' || p.platform === 'givebrite') ? 'GiveBrite (Iqra)' :
                            p.platform === 'paysuite' ? 'Access PaySuite (Rethink)' :
                            p.platform === 'stripe_rethink' ? 'Stripe (Rethink)' :
                            p.platform === 'launchgood_rethink' ? 'LaunchGood (Rethink)' :
                            p.platform === 'launchgood_iqra' ? 'LaunchGood (Iqra)' :
                            p.platform === 'madinah' ? 'Madinah (Iqra)' :
                            (p.platform || 'Unknown Platform'));
              return (
              <div key={p.platform} className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/40 flex flex-col gap-2.5 shadow-2xs min-w-0">
                <div className="flex items-start justify-between gap-2">
                  <span className="font-bold text-sm leading-snug text-slate-900 dark:text-slate-100 min-w-0 truncate" title={label}>{label}</span>
                  <StateBadge state={p.state} />
                </div>
                {p.issues.length > 0 && (
                  <ul className={`list-disc pl-4 flex flex-col gap-1 text-xs leading-relaxed ${ISSUE_CLS[p.state] || ISSUE_CLS.down}`}>{p.issues.map((i, n) => <li key={n}><IssueText text={i} /></li>)}</ul>
                )}
                <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-1.5 text-slate-600 dark:text-slate-300 text-xs items-center">
                  <span className="truncate pr-1 text-slate-500 dark:text-slate-400">Last successful sync</span>
                  <span className="font-semibold text-slate-900 dark:text-slate-100 text-right whitespace-nowrap">{fmtAge(p.sync?.last_ok_at || p.sync?.last_sync_at)}</span>
                  
                  <span className="truncate pr-1 text-slate-500 dark:text-slate-400">Failures in a row</span>
                  <span className="font-semibold text-slate-900 dark:text-slate-100 text-right whitespace-nowrap">{p.sync?.consecutive_failures ?? 0}</span>
                  
                  <span className="truncate pr-1 text-slate-500 dark:text-slate-400">Last API status</span>
                  <span className="font-semibold text-slate-900 dark:text-slate-100 text-right whitespace-nowrap">{p.sync?.last_http_status ?? '—'}</span>
                  
                  <span className="truncate pr-1 text-slate-500 dark:text-slate-400">{['paysuite', 'stripe_rethink'].includes(p.platform) ? 'Auth Mode' : 'Access token'}</span>
                  <span className="font-semibold text-slate-900 dark:text-slate-100 text-right whitespace-nowrap">
                    {['paysuite', 'stripe_rethink'].includes(p.platform) ? (p.token?.present ? 'API Key (Active)' : 'Missing Key') : (p.token?.present ? (p.token.status_text || (p.token.has_refresh && (p.token.access_minutes_left == null || p.token.access_minutes_left <= 0) ? 'Active' : fmtLeft(p.token.access_minutes_left))) : 'missing')}
                  </span>
                  {p.platform === 'madinah' && (
                    <>
                      <span className="truncate pr-1 text-slate-500 dark:text-slate-400">Refresh token</span>
                      <span className="font-semibold text-slate-900 dark:text-slate-100 text-right whitespace-nowrap">{fmtLeft(p.token.refresh_minutes_left)}</span>
                    </>
                  )}
                  {!['paysuite', 'stripe_rethink'].includes(p.platform) && !p.platform?.startsWith('launchgood') && (
                    <>
                      <span className="truncate pr-1 text-slate-500 dark:text-slate-400">Session renewed</span>
                      <span className="font-semibold text-slate-900 dark:text-slate-100 text-right whitespace-nowrap">{fmtAge(p.sync?.last_token_refresh_at || p.token.retrieved_at)}</span>
                      <span className="truncate pr-1 text-slate-500 dark:text-slate-400">Last new donation</span>
                      <span className="font-semibold text-slate-900 dark:text-slate-100 text-right whitespace-nowrap">{fmtAge(p.sync?.last_ingested_at)}</span>
                    </>
                  )}
                  {p.platform === 'paysuite' && (
                    <>
                      <span className="truncate pr-1 text-slate-500 dark:text-slate-400">Schedule</span>
                      <span className="font-semibold text-slate-900 dark:text-slate-100 text-right whitespace-nowrap">Hourly (30 days)</span>
                      <span className="truncate pr-1 text-slate-500 dark:text-slate-400">Last sync</span>
                      <span className="font-semibold text-slate-900 dark:text-slate-100 text-right whitespace-nowrap">{fmtAge(p.sync?.last_sync_at)}</span>
                    </>
                  )}
                  {p.platform === 'stripe_rethink' && (
                    <>
                      <span className="truncate pr-1 text-slate-500 dark:text-slate-400">Integration</span>
                      <span className="font-semibold text-slate-900 dark:text-slate-100 text-right whitespace-nowrap">Direct API (.env)</span>
                      <span className="truncate pr-1 text-slate-500 dark:text-slate-400">Last reconciled</span>
                      <span className="font-semibold text-slate-900 dark:text-slate-100 text-right whitespace-nowrap">{fmtAge(p.sync?.last_payout_reconciled_at)}</span>
                    </>
                  )}
                  {p.platform?.startsWith('launchgood') && (
                    <>
                      <span className="truncate pr-1 text-slate-500 dark:text-slate-400">Integration</span>
                      <span className="font-semibold text-slate-900 dark:text-slate-100 text-right whitespace-nowrap">API Gateway v4</span>
                      <span className="truncate pr-1 text-slate-500 dark:text-slate-400">Session captured</span>
                      <span className="font-semibold text-slate-900 dark:text-slate-100 text-right whitespace-nowrap">{p.token?.captured_at ? fmtAge(p.token.captured_at) : '—'}</span>
                      <span className="truncate pr-1 text-slate-500 dark:text-slate-400">Auto-renewal</span>
                      <span className="font-semibold text-slate-900 dark:text-slate-100 text-right whitespace-nowrap">{p.token?.has_refresh ? (p.platform?.startsWith('launchgood') ? 'automatic (rolling)' : (p.token.refresh_expires_at ? `until ${new Date(p.token.refresh_expires_at).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })}` : 'yes')) : 'needs refreshToken'}</span>
                      <span className="truncate pr-1 text-slate-500 dark:text-slate-400">Last new donation</span>
                      <span className="font-semibold text-slate-900 dark:text-slate-100 text-right whitespace-nowrap">{fmtAge(p.sync?.last_ingested_at)}</span>
                    </>
                  )}
                </div>
                {p.sync?.last_error && !(p.sync?.consecutive_failures === 0 && Date.now() - new Date(p.sync.last_error_at).getTime() > OLD_ISSUE_MS) && (
                  <div className="text-[11px] line-clamp-3 break-words" title={p.sync.last_error}>
                    {p.sync?.consecutive_failures === 0 ? (
                      <span className="text-slate-400 dark:text-slate-500">
                        Resolved · Last transient issue ({fmtAge(p.sync.last_error_at)}): {p.sync.last_error}
                      </span>
                    ) : (
                      <span className="text-rose-600 dark:text-rose-400 font-medium">
                        Last error ({fmtAge(p.sync.last_error_at)}): {p.sync.last_error}
                      </span>
                    )}
                  </div>
                )}
                {p.live_check && (
                  <div className={`text-[11px] font-semibold ${p.live_check.ok ? 'text-emerald-600' : 'text-rose-600'}`}>
                    Live check: {p.live_check.ok ? (p.live_check.detail || 'API answered normally') : `failed (${p.live_check.http_status || 'error'}) ${p.live_check.detail || ''}`}
                  </div>
                )}
              </div>
            );})}
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
              <div className="font-bold mb-2 text-slate-900 dark:text-slate-100">Mailboxes</div>
              {data.outlook.map(o => (
                <div key={o.company_id} className="flex flex-col mb-2">
                  <span className="flex justify-between">
                    <span className="capitalize font-semibold text-slate-800 dark:text-slate-200">{o.company_id} <span className="font-normal text-slate-500">· {o.provider === 'gmail' ? 'Gmail' : 'Microsoft 365'}</span></span>
                    <span className={o.connected ? 'text-emerald-600 font-bold' : 'text-rose-600 font-bold'}>{o.connected ? 'connected' : 'not connected'}</span>
                  </span>
                  <span className="text-slate-500 truncate text-[11px]">{o.mailbox || '—'}{o.last_send ? ` · last ${o.last_send.event === 'email.sent' ? 'sent' : 'FAILED'} ${fmtAge(o.last_send.ts)}` : ''}</span>
                  {o.last_error && <span className="text-rose-600 text-[11px]">{o.last_error}</span>}
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

function LogsTab({ logsOnly = false, companies = [] }) {
  const [filters, setFilters] = useState({ category: 'all', level: 'all', company_id: 'all', actor: 'all', search: '', range: '24h' });
  const [data, setData] = useState({ items: [], total: 0, categories: [], actors: [] });
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
    ['category', 'level', 'company_id', 'actor', 'search'].forEach(k => { if (filters[k] && filters[k] !== 'all') p.set(k, filters[k]); });
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
          {(logsOnly ? ['local'] : ['local', 'axiom']).map(s => (
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
              <option value="all">{logsOnly ? 'All my charities' : 'All charities'}</option>
              {(companies.length ? companies.filter(c => c.id !== 'all') : [{ id: 'rethink', short_code: 'Rethink' }, { id: 'iqra', short_code: 'Iqra' }])
                .map(c => <option key={c.id} value={c.id}>{c.short_code || c.name || c.id}</option>)}
            </select>
            {/* who did what: one employee's actions */}
            <select value={filters.actor} onChange={e => set('actor', e.target.value)} className="px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-800 dark:text-slate-200 text-xs">
              <option value="all">All employees</option>
              {(data.actors || []).map(a => <option key={a} value={a}>{a}</option>)}
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
  const [copiedBookmarklet, setCopiedBookmarklet] = useState(false);
  const load = () => getJson('/api/ops/platform-sessions').then(setSessions).catch(e => setMsg({ type: 'error', text: e.message }));
  const [syncKey, setSyncKey] = useState('');
  useEffect(() => { load(); getJson('/api/ops/sync-helper-key').then(d => setSyncKey(d.key || '')).catch(() => {}); }, []);

  // the key comes from the server (super admins only); it is never written in the code
  const bookmarkletCode = `javascript:(function(){const CRM='${window.location.origin}';const KEY='${syncKey}';if(!location.hostname.includes('launchgood.com')){alert('Please open launchgood.com first before clicking this bookmarklet!');return;}let b=document.getElementById('lg-sync-box');if(!b){b=document.createElement('div');b.id='lg-sync-box';b.style.cssText='position:fixed;top:18px;right:18px;z-index:9999999;padding:13px 18px;background:#0f172a;color:#f8fafc;border-radius:12px;box-shadow:0 12px 30px rgba(0,0,0,0.4);font-family:system-ui,-apple-system,sans-serif;font-size:13px;display:flex;align-items:center;gap:10px;border:1px solid #334155;';document.body.appendChild(b);}b.innerHTML='🔄 Connecting LaunchGood session to CRM...';function getTok(){let m=(document.cookie||'').match(/(?:^|;\\s*)token=([^;]+)/);if(m)return m[1];try{for(let i=0;i<localStorage.length;i++){let v=localStorage.getItem(localStorage.key(i));if(typeof v==='string'&&/^(Bearer\\s+)?eyJ[\\w-]+\\.[\\w-]+\\.[\\w-]+$/.test(v.trim()))return v.trim();}}catch(e){}return'';}function sync(){const t=getTok();if(!t){b.innerHTML='⚠️ Not signed in to LaunchGood. Please log in first.';setTimeout(()=>b.remove(),5000);return;}fetch(CRM+'/api/ops/sync-helper/launchgood_rethink',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({accessToken:t,rawCookie:document.cookie||'',source:'bookmarklet-1click',syncKey:KEY})}).then(r=>r.json()).then(res=>{if(res.ok){b.innerHTML='🟢 <b style=\"color:#34d399;\">LaunchGood Synced!</b> Auto-sync active (every 5m).';b.style.background='#064e3b';b.style.borderColor='#059669';if(!window.__lgInt){window.__lgInt=setInterval(sync,300000);}setTimeout(()=>{b.style.opacity='0.6';},4000);}else{b.innerHTML='⚠️ Notice: '+(res.detail||'Check connection');setTimeout(()=>b.remove(),6000);}}).catch(e=>{b.innerHTML='❌ Error: '+e.message;setTimeout(()=>b.remove(),6000);});}sync();})();`;

  const upload = async () => {
    let token = form.accessToken.trim();
    let rawCookie = (form.rawCookie || '').trim();
    let refreshToken = (form.refreshToken || '').trim();

    // Smart auto-parse if user pasted full JSON from browser network tab or tokens file
    if (token.startsWith('{') && token.endsWith('}')) {
      try {
        const parsed = JSON.parse(token);
        token = parsed.bearerToken || parsed.accessToken || (parsed.headers?.authorization || parsed.headers?.Authorization) || token;
        if (!rawCookie) {
          rawCookie = parsed.rawCookie || parsed.headers?.cookie || parsed.headers?.Cookie || '';
        }
        if (!refreshToken) {
          refreshToken = parsed.refreshToken || '';
        }
      } catch {}
    }

    const isLg = form.platform?.startsWith('launchgood');
    if (!token && !(isLg && refreshToken)) return;
    setBusy(true); setMsg(null);
    try {
      const r = await getJson(`/api/ops/platform-sessions/${form.platform}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ accessToken: token, rawCookie: rawCookie || null, refreshToken: refreshToken || null, source: 'ops-console-paste' })
      });
      setMsg({ type: 'ok', text: r.status === 'pending' ? r.message : r.has_refresh
        ? 'Verified and saved. The session now renews itself automatically - no need to sign in again unless LaunchGood signs you out.'
        : `Verified and saved. Access token valid until ${new Date(r.access_expires_at).toLocaleString()}.` });
      setForm(f => ({ ...f, accessToken: '', refreshToken: '', rawCookie: '' }));
      load();
    } catch (e) { setMsg({ type: 'error', text: e.message }); } finally { setBusy(false); }
  };

  const captureCommands = [
    { platform: 'madinah (iqra)', cmd: 'node scripts/capture_platform_session.js madinah', targetCls: 'text-cyan-400 font-bold' },
    { platform: 'givebrite (iqra)', cmd: 'node scripts/capture_platform_session.js iqra', targetCls: 'text-emerald-400 font-bold' },
    { platform: 'givebrite (rethink)', cmd: 'node scripts/capture_platform_session.js rethink', targetCls: 'text-purple-400 font-bold' },
    { platform: 'launchgood (rethink)', cmd: 'node scripts/capture_platform_session.js launchgood_rethink', targetCls: 'text-emerald-500 font-bold' },
    { platform: 'launchgood (iqra)', cmd: 'node scripts/capture_platform_session.js launchgood_iqra', targetCls: 'text-teal-400 font-bold' }
  ];

  return (
    <div className="flex flex-col gap-4">
      {/* Session overview cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-3">
        {sessions && Object.entries(sessions).map(([p, s]) => {
          const sessionLabel = p === 'givebrite_rethink' ? 'GiveBrite (Rethink)' :
                               (p === 'givebrite_iqra' || p === 'givebrite') ? 'GiveBrite (Iqra)' :
                               p === 'launchgood_rethink' ? 'LaunchGood (Rethink)' :
                               p === 'launchgood_iqra' ? 'LaunchGood (Iqra)' :
                               'Madinah (Iqra)';
          return (
          <div key={p} className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/40 grid grid-cols-2 gap-x-3 gap-y-1.5 shadow-2xs text-xs">
            <div className="col-span-2 flex items-center justify-between mb-1">
              <span className="font-bold capitalize text-sm text-slate-900 dark:text-slate-100 flex items-center gap-1.5">
                <span className={`w-2 h-2 rounded-full ${s.present ? 'bg-emerald-500' : 'bg-rose-500'}`} />
                {sessionLabel}
              </span>
              <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${s.present ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-900' : 'bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300 border border-rose-200 dark:border-rose-900'}`}>
                {s.present ? 'Active Session' : 'Missing'}
              </span>
            </div>
            <span className="text-slate-500 dark:text-slate-400 font-medium">Access token</span>
            <span className={`font-semibold ${s.access_minutes_left > 120 ? 'text-emerald-600 dark:text-emerald-400' : s.access_minutes_left > 0 ? 'text-amber-600 dark:text-amber-400' : 'text-slate-700 dark:text-slate-300'}`}>
              {s.present ? (s.status_text || (s.has_refresh && (s.access_minutes_left == null || s.access_minutes_left <= 0) ? 'Active' : fmtLeft(s.access_minutes_left))) : 'missing'}
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
        );})}
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

      {/* 1-Click LaunchGood Bookmarklet Sync (Recommended) */}
      <div className="p-4 rounded-xl border border-emerald-200 dark:border-emerald-900 bg-emerald-50/60 dark:bg-emerald-950/20 flex flex-col gap-3 shadow-2xs">
        <div className="flex items-center justify-between">
          <div className="font-bold text-sm text-emerald-950 dark:text-emerald-100 flex items-center gap-2">
            <Zap className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
            1-Click LaunchGood Sync Bookmarklet (Recommended)
          </div>
          <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-900/60 text-emerald-800 dark:text-emerald-300 uppercase tracking-wide">
            Zero DevTools / Zero Typing
          </span>
        </div>
        <p className="text-slate-700 dark:text-slate-300 text-xs leading-relaxed">
          Because LaunchGood uses 15-minute expiring tokens, you no longer need to copy/paste tokens manually. Drag the button below to your browser’s bookmarks bar. Whenever you are on LaunchGood, click it once — it syncs your active session and keeps it alive in the background every 5 minutes.
        </p>

        <div className="flex flex-wrap items-center gap-3 pt-1">
          <a
            href={bookmarkletCode}
            onClick={(e) => {
              alert('Drag this button directly to your browser\'s Bookmarks bar! Then click it whenever you are on launchgood.com.');
              e.preventDefault();
            }}
            className="px-4 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-700 active:scale-[0.98] text-white font-bold text-xs shadow-md shadow-emerald-600/25 flex items-center gap-2 cursor-grab select-none transition-all"
            title="Drag to your Bookmarks toolbar"
          >
            <Bookmark className="w-4 h-4" />
            <span>🚀 Drag to Bookmarks: Sync LaunchGood</span>
          </a>

          <button
            type="button"
            onClick={() => {
              navigator.clipboard.writeText(bookmarkletCode);
              setCopiedBookmarklet(true);
              setTimeout(() => setCopiedBookmarklet(false), 2500);
            }}
            className="px-3.5 py-2 rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 hover:bg-slate-50 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-200 text-xs font-semibold flex items-center gap-1.5 transition-all cursor-pointer"
          >
            {copiedBookmarklet ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : <Copy className="w-3.5 h-3.5" />}
            <span>{copiedBookmarklet ? 'Copied code!' : 'Copy bookmarklet code'}</span>
          </button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-2 pt-1 text-[11px] text-slate-600 dark:text-slate-400">
          <div className="flex items-start gap-1.5 p-2 rounded-lg bg-white/70 dark:bg-slate-900/60 border border-emerald-100 dark:border-emerald-900/50">
            <span className="font-bold text-emerald-600 dark:text-emerald-400">1.</span>
            <span>Drag the <b>🚀 Sync LaunchGood</b> button into your browser’s bookmarks bar.</span>
          </div>
          <div className="flex items-start gap-1.5 p-2 rounded-lg bg-white/70 dark:bg-slate-900/60 border border-emerald-100 dark:border-emerald-900/50">
            <span className="font-bold text-emerald-600 dark:text-emerald-400">2.</span>
            <span>Go to <a href="https://www.launchgood.com" target="_blank" rel="noreferrer" className="text-emerald-600 dark:text-emerald-400 underline font-semibold">launchgood.com</a> and sign in.</span>
          </div>
          <div className="flex items-start gap-1.5 p-2 rounded-lg bg-white/70 dark:bg-slate-900/60 border border-emerald-100 dark:border-emerald-900/50">
            <span className="font-bold text-emerald-600 dark:text-emerald-400">3.</span>
            <span>Click the bookmark! A green badge confirms connection and auto-renews every 5m.</span>
          </div>
        </div>
      </div>

      {/* Manual token paste */}
      <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/40 flex flex-col gap-3 shadow-2xs">
        <div className="font-bold text-sm text-slate-900 dark:text-slate-100 flex items-center gap-1.5">
          <Upload className="w-4 h-4 text-blue-500" />
          Or paste tokens manually
        </div>
        <div className="flex flex-wrap gap-2">
          {['givebrite_iqra', 'givebrite_rethink', 'madinah', 'launchgood_rethink', 'launchgood_iqra'].map(p => {
            const btnLabel = p === 'givebrite_rethink' ? 'GiveBrite (Rethink)' :
                             p === 'givebrite_iqra' ? 'GiveBrite (Iqra)' :
                             p === 'launchgood_rethink' ? 'LaunchGood (Rethink)' :
                             p === 'launchgood_iqra' ? 'LaunchGood (Iqra)' :
                             'Madinah (Iqra)';
            return (
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
                {btnLabel}
              </button>
            );
          })}
        </div>
        <div className={`flex flex-col gap-1.5 ${form.platform?.startsWith('launchgood') ? 'hidden' : ''}`}>
          <label className="text-[11px] font-semibold text-slate-700 dark:text-slate-300">
            {form.platform?.startsWith('launchgood') ? 'Access token (optional when you paste the refresh token)' : 'Access token (Bearer string or full JSON)'}
          </label>
          <textarea
            value={form.accessToken}
            onChange={e => setForm(f => ({ ...f, accessToken: e.target.value }))}
            rows={3}
            placeholder={form.platform?.startsWith('launchgood') ? 'Bearer eyJhbGci... or paste full JSON with headers/cookies' : 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...'}
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
        {form.platform?.startsWith('launchgood') && (
          <div className="flex flex-col gap-1.5 rounded-xl border border-emerald-200 dark:border-emerald-900 bg-emerald-50/60 dark:bg-emerald-950/20 p-3">
            <label className="text-[11px] font-bold text-emerald-900 dark:text-emerald-200">
              Refresh token - the one that stops LaunchGood signing out (the access token alone lasts only 15 minutes)
            </label>
            <ol className="text-[11px] text-emerald-900/80 dark:text-emerald-200/80 list-decimal pl-4 space-y-0.5">
              <li>Open <b>launchgood.com</b> in Chrome or Edge, signed in to {form.platform === 'launchgood_iqra' ? "Iqra's" : "Rethink's"} account.</li>
              <li>Press <b>F12</b>, open the <b>Console</b> tab, type <code className="select-all px-1 rounded bg-white dark:bg-slate-800 !text-slate-900 dark:!text-slate-100">copy(localStorage.refreshToken)</code> and press Enter (if Chrome asks, type <i>allow pasting</i> first).</li>
              <li>Paste here (Ctrl+V) and press <b>Verify &amp; save</b>. The CRM then renews the session by itself - no more sign-ins until LaunchGood ends it (shown on the card as “Auto-renewal until …”).</li>
            </ol>
            <textarea
              value={form.refreshToken}
              onChange={e => setForm(f => ({ ...f, refreshToken: e.target.value }))}
              rows={3}
              placeholder="eyJhbGciOi... (value of refreshToken)"
              className="w-full px-3 py-2 rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 placeholder:text-slate-400 dark:placeholder:text-slate-500 font-mono text-xs focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 outline-none transition-all"
            />
          </div>
        )}
        <button
          type="button"
          disabled={busy || !(form.accessToken.trim() || (form.platform?.startsWith('launchgood') && (form.refreshToken || '').trim()))}
          onClick={upload}
          className={`self-start px-4 py-2 rounded-xl font-bold text-xs flex items-center gap-2 transition-all ${
            !(form.accessToken.trim() || (form.platform?.startsWith('launchgood') && (form.refreshToken || '').trim())) || busy
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
export default function OpsConsole({ onClose, initialTab = 'status', logsOnly = false, companies = [] }) {
  const [tab, setTab] = useState(['status', 'logs', 'sessions', 'cache'].includes(initialTab) ? initialTab : 'status');
  useEffect(() => {
    if (['status', 'logs', 'sessions', 'cache'].includes(initialTab)) setTab(initialTab);
  }, [initialTab]);
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  // people given the activity log (not super admins) see only the log, for their charities (server-filtered)
  const tabs = logsOnly ? [['logs', ScrollText, 'Activity log']] : [
    ['status', Activity, 'Status'],
    ['logs', ScrollText, 'Logs'],
    ['sessions', KeyRound, 'Sessions'],
    ['cache', Database, 'Cache']
  ];
  return (
    <div className="fixed inset-0 z-[80] bg-black/60 backdrop-blur-xs flex items-center justify-center p-4 animate-in fade-in duration-150" onClick={onClose}>
      <div
        className="w-full max-w-7xl max-h-[92vh] overflow-y-auto overflow-x-hidden rounded-2xl bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 shadow-2xl text-xs text-slate-800 dark:text-slate-200"
        onClick={e => e.stopPropagation()}
      >
        {/* Solid opaque sticky header — completely blocks background bleed-through when scrolling */}
        <div className="sticky top-0 z-30 px-5 py-3.5 bg-slate-50 dark:bg-slate-950 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between shadow-xs">
          <div className="flex items-center gap-3">
            <span className="font-bold text-sm text-slate-900 dark:text-slate-100">{logsOnly ? 'Activity log' : 'Ops console'}</span>
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
          {tab === 'status' && !logsOnly && <StatusTab />}
          {(tab === 'logs' || logsOnly) && <LogsTab logsOnly={logsOnly} companies={companies} />}
          {tab === 'sessions' && !logsOnly && <SessionsTab />}
          {tab === 'cache' && !logsOnly && <CacheTab />}
        </div>
      </div>
    </div>
  );
}
