import React, { useEffect, useState, useCallback, useRef } from 'react';
import {
  MessageSquare, Users, Layers, Mail, CheckCircle2, Clock, Search, RefreshCw,
  Download, ChevronLeft, ChevronRight, Send, Filter, Tag, Sparkles, AlertCircle, Check
} from 'lucide-react';
import { API_BASE_URL, downloadFile } from '../../config';
import { can } from '../../access';
import { FIELD } from './emailUi';

/**
 * Emails -> General Feedback Eligible
 * Displays all donors & donations falling under campaigns or giving levels tagged as "Requires Feedback"
 * in real time via fast DuckDB queries without choking resources.
 */
export default function GeneralFeedbackEligibleView({ company, user, onSelectDonor, onComposeToDonors }) {
  const [view, setView] = useState('donors'); // 'donors' | 'donations'
  const [platform, setPlatform] = useState('all');
  const [campaign, setCampaign] = useState('all');
  const [emailStatus, setEmailStatus] = useState('all');
  const [consent, setConsent] = useState('all');
  const [sp, setSp] = useState('all'); // 'all' | 'sp' | 'non_sp'
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showRulesDrawer, setShowRulesDrawer] = useState(false);

  // Selected donor IDs for 1-click Email Composer
  const [selectedKeys, setSelectedKeys] = useState(new Set());

  const canSendEmail = can(user, 'email.send', company);
  const canExport = can(user, 'donors.export', company) || can(user, 'email.view', company);

  useEffect(() => {
    const t = setTimeout(() => {
      setDebouncedSearch(search);
      setPage(1);
    }, 250);
    return () => clearTimeout(t);
  }, [search]);

  const abortRef = useRef(null);
  const fetchEligible = useCallback((silent = false) => {
    if (!company || company === 'all') return;
    if (abortRef.current) abortRef.current.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    if (!silent) setLoading(true);
    setError('');

    const qs = new URLSearchParams({
      company_id: company,
      view,
      platform,
      campaign,
      email_status: emailStatus,
      consent,
      sp,
      search: debouncedSearch,
      page: String(page),
      page_size: String(pageSize),
    });

    fetch(`${API_BASE_URL}/api/tracker/direct-email/general-feedback-eligible?${qs}`, { signal: ctrl.signal })
      .then(async r => {
        const j = await r.json();
        if (!r.ok) throw new Error(j.detail || 'Failed to load General Feedback Eligible data.');
        return j;
      })
      .then(res => {
        setData(res);
        setLoading(false);
      })
      .catch(err => {
        if (err.name === 'AbortError') return;
        setError(err.message);
        setLoading(false);
      });
  }, [company, view, platform, campaign, emailStatus, consent, sp, debouncedSearch, page, pageSize]);

  useEffect(() => {
    setPage(1);
    setSelectedKeys(new Set());
  }, [company, view]);

  useEffect(() => {
    fetchEligible(false);
    return () => { if (abortRef.current) abortRef.current.abort(); };
  }, [fetchEligible]);

  // Listen for real-time matrix / donor / email updates via WebSocket
  useEffect(() => {
    let socket = null;
    try {
      const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsHost = API_BASE_URL.replace(/^http(s)?:\/\//, '') || window.location.host;
      const wsUrl = `${wsProtocol}//${wsHost}/ws/events?token=${encodeURIComponent(localStorage.getItem('analytics_token') || '')}`;
      socket = new WebSocket(wsUrl);
      socket.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          if (['MATRIX_UPDATED', 'DONORS_UPDATED'].includes(payload?.event)) {
            fetchEligible(true);
          }
        } catch (e) {}
      };
    } catch (e) {}
    return () => {
      if (socket) {
        try { socket.close(); } catch (e) {}
      }
    };
  }, [fetchEligible]);

  const summary = data?.summary || {
    total_donations: 0,
    total_donors: 0,
    emailable_donors: 0,
    total_amount: 0,
    emailed_donors: 0,
    not_emailed_donors: 0,
    feedback_sent_donors: 0,
    feedback_pending_donors: 0,
    flagged_rules: 0,
    flagged_campaigns: 0,
  };
  const items = data?.items || [];
  const rules = data?.rules || [];
  const campaigns = data?.campaigns || [];
  const total = data?.total || 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const emailableIds = data?.emailable_donor_ids || [];

  const toggleSelectRow = (donorId) => {
    setSelectedKeys(prev => {
      const next = new Set(prev);
      if (next.has(donorId)) next.delete(donorId);
      else next.add(donorId);
      return next;
    });
  };

  const toggleSelectPage = () => {
    const pageIds = items.filter(i => i.has_email && !i.is_unsubscribed).map(i => i.donor_id);
    if (!pageIds.length) return;
    const allChecked = pageIds.every(id => selectedKeys.has(id));
    setSelectedKeys(prev => {
      const next = new Set(prev);
      pageIds.forEach(id => (allChecked ? next.delete(id) : next.add(id)));
      return next;
    });
  };

  const handleExport = () => {
    const qs = new URLSearchParams({
      company_id: company,
      view,
      platform,
      campaign,
      email_status: emailStatus,
      consent,
      sp,
      search: debouncedSearch,
    });
    downloadFile(`${API_BASE_URL}/api/tracker/direct-email/general-feedback-eligible/export?${qs}`);
  };

  return (
    <div className="flex flex-col gap-4">
      {/* KPI Summary Strip */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
        <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4 shadow-xs border-l-4 border-l-violet-500">
          <div className="text-[11px] font-bold uppercase text-slate-500 flex items-center gap-1.5">
            <Users className="w-3.5 h-3.5 text-violet-500" />
            <span>Eligible Donors</span>
          </div>
          <div className="text-2xl font-black text-slate-900 dark:text-white mt-1 tabular-nums">
            {summary.total_donors.toLocaleString()}
          </div>
          <div className="text-[11px] text-slate-500 mt-0.5">
            {summary.emailable_donors.toLocaleString()} emailable (not unsub.)
          </div>
        </div>

        <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4 shadow-xs border-l-4 border-l-sky-500">
          <div className="text-[11px] font-bold uppercase text-slate-500 flex items-center gap-1.5">
            <Layers className="w-3.5 h-3.5 text-sky-500" />
            <span>Eligible Donations</span>
          </div>
          <div className="text-2xl font-black text-slate-900 dark:text-white mt-1 tabular-nums">
            {summary.total_donations.toLocaleString()}
          </div>
          <div className="text-[11px] font-mono font-bold text-sky-600 dark:text-sky-400 mt-0.5">
            £{Number(summary.total_amount || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </div>
        </div>

        <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4 shadow-xs border-l-4 border-l-amber-500">
          <div className="text-[11px] font-bold uppercase text-slate-500 flex items-center gap-1.5">
            <Clock className="w-3.5 h-3.5 text-amber-500" />
            <span>Feedback Pending</span>
          </div>
          <div className="text-2xl font-black text-amber-600 dark:text-amber-400 mt-1 tabular-nums">
            {summary.feedback_pending_donors.toLocaleString()}
          </div>
          <div className="text-[11px] text-slate-500 mt-0.5">
            {summary.not_emailed_donors.toLocaleString()} never emailed at all
          </div>
        </div>

        <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4 shadow-xs border-l-4 border-l-emerald-500">
          <div className="text-[11px] font-bold uppercase text-slate-500 flex items-center gap-1.5">
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />
            <span>Feedback Sent</span>
          </div>
          <div className="text-2xl font-black text-emerald-600 dark:text-emerald-400 mt-1 tabular-nums">
            {summary.feedback_sent_donors.toLocaleString()}
          </div>
          <div className="text-[11px] text-slate-500 mt-0.5">
            {summary.emailed_donors.toLocaleString()} emailed (any campaign)
          </div>
        </div>

        <div
          onClick={() => setShowRulesDrawer(v => !v)}
          className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4 shadow-xs border-l-4 border-l-indigo-500 cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/60 transition-colors"
          title="Click to inspect flagged campaigns & giving levels"
        >
          <div className="text-[11px] font-bold uppercase text-slate-500 flex items-center gap-1.5">
            <Tag className="w-3.5 h-3.5 text-indigo-500" />
            <span>Requires Feedback</span>
          </div>
          <div className="text-2xl font-black text-indigo-600 dark:text-indigo-400 mt-1 tabular-nums">
            {summary.flagged_campaigns.toLocaleString()}
          </div>
          <div className="text-[11px] text-indigo-600 dark:text-indigo-400 font-semibold mt-0.5 underline underline-offset-2">
            {summary.flagged_rules.toLocaleString()} rules flagged · View list
          </div>
        </div>
      </div>

      {/* Expandable Active Rules Pill List */}
      {showRulesDrawer && (
        <div className="rounded-2xl border border-violet-200 dark:border-violet-800/60 bg-violet-50/70 dark:bg-violet-950/20 p-4 space-y-2">
          <div className="flex items-center justify-between">
            <div className="text-xs font-extrabold text-violet-900 dark:text-violet-200 flex items-center gap-1.5">
              <MessageSquare className="w-4 h-4 text-violet-600" />
              <span>Active "Requires Feedback" Campaigns & Giving Levels ({rules.length})</span>
            </div>
            <button type="button" onClick={() => setShowRulesDrawer(false)} className="text-xs font-bold text-slate-500 hover:text-slate-800 dark:hover:text-white cursor-pointer">
              Hide
            </button>
          </div>
          {rules.length === 0 ? (
            <p className="text-xs text-slate-600 dark:text-slate-400">
              No campaigns or giving levels are marked as Requires Feedback yet. Open <b>Classifications</b> and click the <b>Needs Feedback</b> toggle on any campaign or giving level.
            </p>
          ) : (
            <div className="flex flex-wrap gap-1.5 max-h-40 overflow-y-auto pt-1">
              {rules.map((r, i) => (
                <button
                  key={`${r.platform}-${r.campaign_name}-${r.giving_level}-${i}`}
                  type="button"
                  onClick={() => { setCampaign(r.campaign_name); setPage(1); }}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-white dark:bg-slate-900 border border-violet-300 dark:border-violet-700/60 text-[11px] font-semibold text-slate-800 dark:text-slate-200 hover:border-violet-500 cursor-pointer shadow-2xs"
                >
                  <span className="px-1.5 py-0.2 rounded bg-slate-100 dark:bg-slate-800 text-[9px] font-black uppercase text-slate-600 dark:text-slate-400">{r.platform}</span>
                  <span className="font-bold truncate max-w-[180px]">{r.campaign_name}</span>
                  <span className="text-violet-600 dark:text-violet-400">
                    {r.whole_campaign ? '• Whole Campaign' : (r.giving_level ? `• ${r.giving_level}` : '• Default')}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Toolbar: View Switch, Search, Filters, Compose & Export */}
      <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-3.5 shadow-xs space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          {/* View Toggle: Eligible Donors vs Eligible Donations */}
          <div className="flex items-center bg-slate-100 dark:bg-slate-800 p-1 rounded-xl border border-slate-200 dark:border-slate-700 gap-1">
            <button
              type="button"
              onClick={() => setView('donors')}
              className={`px-3 py-1.5 rounded-lg text-xs font-bold flex items-center gap-1.5 cursor-pointer transition-all ${
                view === 'donors'
                  ? 'bg-violet-600 text-white shadow-sm'
                  : 'text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white'
              }`}
            >
              <Users className="w-3.5 h-3.5" />
              <span>Eligible Donors ({summary.total_donors.toLocaleString()})</span>
            </button>
            <button
              type="button"
              onClick={() => setView('donations')}
              className={`px-3 py-1.5 rounded-lg text-xs font-bold flex items-center gap-1.5 cursor-pointer transition-all ${
                view === 'donations'
                  ? 'bg-sky-600 text-white shadow-sm'
                  : 'text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white'
              }`}
            >
              <Layers className="w-3.5 h-3.5" />
              <span>Eligible Donations ({summary.total_donations.toLocaleString()})</span>
            </button>
          </div>

          {/* Action Buttons: Email Selected / All + Export + Refresh */}
          <div className="flex flex-wrap items-center gap-2">
            {canSendEmail && onComposeToDonors && (
              <>
                {selectedKeys.size > 0 && (
                  <button
                    type="button"
                    onClick={() => onComposeToDonors(Array.from(selectedKeys))}
                    className="px-3.5 py-1.5 rounded-xl bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 text-white text-xs font-bold flex items-center gap-1.5 shadow-sm cursor-pointer"
                  >
                    <Send className="w-3.5 h-3.5" />
                    <span>Email Selected ({selectedKeys.size})</span>
                  </button>
                )}
                {emailableIds.length > 0 && (
                  <button
                    type="button"
                    onClick={() => onComposeToDonors(emailableIds)}
                    className="px-3.5 py-1.5 rounded-xl bg-sky-600 hover:bg-sky-700 text-white text-xs font-bold flex items-center gap-1.5 shadow-sm cursor-pointer"
                    title="Open Bulk Email Composer pre-loaded with all matching emailable donors"
                  >
                    <Mail className="w-3.5 h-3.5" />
                    <span>Email All Eligible ({emailableIds.length.toLocaleString()})</span>
                  </button>
                )}
              </>
            )}
            {canExport && (
              <button
                type="button"
                onClick={handleExport}
                disabled={total === 0}
                className="px-3 py-1.5 rounded-xl border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 hover:bg-slate-100 dark:hover:bg-slate-700 text-xs font-bold text-slate-700 dark:text-slate-200 flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
              >
                <Download className="w-3.5 h-3.5" />
                <span>Export CSV</span>
              </button>
            )}
            <button
              type="button"
              onClick={() => fetchEligible(false)}
              className="p-1.5 rounded-xl border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300 cursor-pointer"
              title="Refresh real-time data"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>

        {/* Search & Filter Row */}
        <div className="flex flex-wrap items-center gap-2 pt-1 border-t border-slate-100 dark:border-slate-800">
          <div className="relative flex-1 min-w-[220px] max-w-sm">
            <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search donor, email, campaign, giving level, code..."
              className={`${FIELD} !w-full pl-8 pr-2 py-1.5 text-xs`}
            />
          </div>

          <select
            value={platform}
            onChange={e => { setPlatform(e.target.value); setPage(1); }}
            className={`${FIELD} !w-auto py-1.5 px-2.5 text-xs font-semibold`}
          >
            <option value="all">All Platforms</option>
            <option value="launchgood">LaunchGood</option>
            <option value="givebrite">GiveBrite</option>
            <option value="madinah">Madinah</option>
            <option value="paysuite">Paysuite</option>
            <option value="website">Rethink Website</option>
            <option value="stripe">Stripe</option>
          </select>

          <select
            value={campaign}
            onChange={e => { setCampaign(e.target.value); setPage(1); }}
            className={`${FIELD} !w-auto max-w-[240px] py-1.5 px-2.5 text-xs font-semibold`}
          >
            <option value="all">All Flagged Campaigns ({campaigns.length})</option>
            {campaigns.map(c => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>

          <select
            value={emailStatus}
            onChange={e => { setEmailStatus(e.target.value); setPage(1); }}
            className={`${FIELD} !w-auto py-1.5 px-2.5 text-xs font-semibold`}
          >
            <option value="all">Email Status: All</option>
            <option value="feedback_not_sent">Feedback Email Pending</option>
            <option value="feedback_sent">Feedback Email Sent</option>
            <option value="not_emailed">Never Emailed</option>
            <option value="emailed">Emailed (Any)</option>
          </select>

          <select
            value={consent}
            onChange={e => { setConsent(e.target.value); setPage(1); }}
            className={`${FIELD} !w-auto py-1.5 px-2.5 text-xs font-semibold`}
          >
            <option value="all">Marketing Consent: All</option>
            <option value="yes">Consent: Yes</option>
            <option value="no">Consent: No / Unknown</option>
          </select>

          <select
            value={sp}
            onChange={e => { setSp(e.target.value); setPage(1); }}
            className={`${FIELD} !w-auto py-1.5 px-2.5 text-xs font-semibold`}
          >
            <option value="all">Cause: All (SP & Non-SP)</option>
            <option value="sp">🌸 SP Only (Sisters' Project)</option>
            <option value="non_sp">Non-SP Only</option>
          </select>
        </div>
      </div>

      {/* Main Data Table */}
      <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden shadow-xs">
        {error && (
          <div className="p-4 bg-rose-50 dark:bg-rose-950/30 text-rose-700 dark:text-rose-300 text-xs flex items-center gap-2 border-b border-rose-200 dark:border-rose-800">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {loading && !data ? (
          <div className="p-10 text-center text-xs text-slate-500 flex items-center justify-center gap-2">
            <RefreshCw className="w-4 h-4 animate-spin text-violet-500" />
            <span>Computing eligible donors & donations in real time…</span>
          </div>
        ) : rules.length === 0 ? (
          <div className="p-12 text-center space-y-2">
            <MessageSquare className="w-8 h-8 text-violet-400 mx-auto opacity-80" />
            <div className="text-sm font-bold text-slate-800 dark:text-white">No Campaigns Marked as "Requires Feedback" Yet</div>
            <p className="text-xs text-slate-500 max-w-md mx-auto">
              Go to <b>Classifications</b> across any platform (LaunchGood, GiveBrite, Madinah, Paysuite, Website, or Stripe) and toggle <b>Needs Feedback</b> on a giving level or an entire campaign. Matching donors and donations will appear here immediately.
            </p>
          </div>
        ) : items.length === 0 ? (
          <div className="p-10 text-center text-xs text-slate-500">
            No matching {view} found for the current filters.
          </div>
        ) : view === 'donors' ? (
          <div className="overflow-x-auto max-h-[65vh]">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-slate-50 dark:bg-slate-950 text-slate-500 border-b border-slate-200 dark:border-slate-800 z-10">
                <tr>
                  <th className="px-3 py-2.5 w-8 text-center">
                    <input
                      type="checkbox"
                      checked={items.filter(i => i.has_email && !i.is_unsubscribed).length > 0 && items.filter(i => i.has_email && !i.is_unsubscribed).every(i => selectedKeys.has(i.donor_id))}
                      onChange={toggleSelectPage}
                      className="cursor-pointer rounded"
                      title="Select all emailable donors on this page"
                    />
                  </th>
                  <th className="px-3 py-2.5 text-left font-bold">Donor</th>
                  <th className="px-3 py-2.5 text-left font-bold">Campaigns & Giving Levels</th>
                  <th className="px-3 py-2.5 text-center font-bold">Gifts</th>
                  <th className="px-3 py-2.5 text-right font-bold">Matched Total</th>
                  <th className="px-3 py-2.5 text-center font-bold">Last Gift</th>
                  <th className="px-3 py-2.5 text-center font-bold">Consent</th>
                  <th className="px-3 py-2.5 text-left font-bold">Email Status</th>
                </tr>
              </thead>
              <tbody>
                {items.map((d, idx) => {
                  const selectable = d.has_email && !d.is_unsubscribed;
                  const checked = selectedKeys.has(d.donor_id);
                  return (
                    <tr key={`${d.donor_key}-${idx}`} className="border-t border-slate-100 dark:border-slate-800 hover:bg-violet-50/40 dark:hover:bg-violet-950/20 text-slate-800 dark:text-slate-100">
                      <td className="px-3 py-2 text-center">
                        <input
                          type="checkbox"
                          disabled={!selectable}
                          checked={checked}
                          onChange={() => toggleSelectRow(d.donor_id)}
                          className="cursor-pointer rounded disabled:opacity-30"
                        />
                      </td>
                      <td className="px-3 py-2">
                        <button
                          type="button"
                          onClick={() => onSelectDonor?.({ donor_id: d.donor_id, email: d.email, name: d.donor_name })}
                          className="text-left hover:text-violet-600 dark:hover:text-violet-400 cursor-pointer"
                        >
                          <div className="flex items-center gap-1.5">
                            <span className="font-bold">{d.donor_name}</span>
                            {d.is_sp && (
                              <span className="px-1.5 py-0.2 rounded text-[9px] font-black uppercase tracking-wider bg-fuchsia-100 text-fuchsia-700 dark:bg-fuchsia-950/70 dark:text-fuchsia-300 border border-fuchsia-300/40">
                                🌸 SP
                              </span>
                            )}
                          </div>
                          <div className="text-[11px] text-slate-500">{d.email || 'No email address'}</div>
                        </button>
                      </td>
                      <td className="px-3 py-2 max-w-[300px]">
                        <div className="flex flex-wrap gap-1">
                          {(d.campaigns || []).slice(0, 3).map(cn => (
                            <span key={cn} className="px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-[10px] font-semibold truncate max-w-[200px]" title={cn}>{cn}</span>
                          ))}
                          {d.campaigns?.length > 3 && <span className="text-[10px] text-slate-400">+{d.campaigns.length - 3} more</span>}
                        </div>
                        {d.giving_levels?.length > 0 && (
                          <div className="text-[10px] text-violet-600 dark:text-violet-400 mt-0.5 truncate" title={d.giving_levels.join(', ')}>
                            🎁 {d.giving_levels.join(', ')}
                          </div>
                        )}
                      </td>
                      <td className="px-3 py-2 text-center tabular-nums font-bold">{d.donation_count}</td>
                      <td className="px-3 py-2 text-right tabular-nums font-mono font-bold text-emerald-700 dark:text-emerald-400">
                        £{Number(d.total_amount || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </td>
                      <td className="px-3 py-2 text-center tabular-nums whitespace-nowrap">{d.last_gift_date || '—'}</td>
                      <td className="px-3 py-2 text-center">
                        {d.is_unsubscribed ? (
                          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300">Unsubscribed</span>
                        ) : d.marketing_consent === 'Yes' ? (
                          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300">Yes</span>
                        ) : (
                          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400">{d.marketing_consent || 'No'}</span>
                        )}
                      </td>
                      <td className="px-3 py-2 whitespace-nowrap">
                        {d.feedback_emailed_at ? (
                          <div className="text-emerald-600 dark:text-emerald-400 font-semibold flex items-center gap-1">
                            <Check className="w-3 h-3" />
                            <span>Feedback Sent ({d.feedback_emailed_at.slice(0, 10)})</span>
                          </div>
                        ) : d.emailed_at ? (
                          <div className="text-sky-600 dark:text-sky-400 font-medium">
                            Emailed {d.emailed_at.slice(0, 10)} <span className="text-[10px] text-slate-400">({d.email_template || 'other'})</span>
                          </div>
                        ) : (
                          <span className="text-amber-600 dark:text-amber-400 font-semibold">Not Emailed</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="overflow-x-auto max-h-[65vh]">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-slate-50 dark:bg-slate-950 text-slate-500 border-b border-slate-200 dark:border-slate-800 z-10">
                <tr>
                  <th className="px-3 py-2.5 text-left font-bold">Date</th>
                  <th className="px-3 py-2.5 text-left font-bold">Donor</th>
                  <th className="px-3 py-2.5 text-center font-bold">Cause</th>
                  <th className="px-3 py-2.5 text-left font-bold">Platform</th>
                  <th className="px-3 py-2.5 text-left font-bold">Campaign Name</th>
                  <th className="px-3 py-2.5 text-left font-bold">Giving Level</th>
                  <th className="px-3 py-2.5 text-left font-bold">Code</th>
                  <th className="px-3 py-2.5 text-right font-bold">Amount</th>
                  <th className="px-3 py-2.5 text-left font-bold">Email Status</th>
                </tr>
              </thead>
              <tbody>
                {items.map((d, idx) => (
                  <tr key={`${d.donation_id}-${idx}`} className="border-t border-slate-100 dark:border-slate-800 hover:bg-sky-50/40 dark:hover:bg-sky-950/20 text-slate-800 dark:text-slate-100">
                    <td className="px-3 py-2 tabular-nums whitespace-nowrap">{d.created_date || '—'}</td>
                    <td className="px-3 py-2">
                      <button
                        type="button"
                        onClick={() => onSelectDonor?.({ donor_id: d.donor_id, email: d.email, name: d.donor_name })}
                        className="text-left hover:text-sky-600 dark:hover:text-sky-400 cursor-pointer"
                      >
                        <div className="font-bold">{d.donor_name}</div>
                        <div className="text-[10px] text-slate-500">{d.email || 'No email'}</div>
                      </button>
                    </td>
                    <td className="px-3 py-2 text-center whitespace-nowrap">
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-black uppercase ${d.is_sp ? 'bg-fuchsia-100 text-fuchsia-700 dark:bg-fuchsia-950/70 dark:text-fuchsia-300 border border-fuchsia-300/40' : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400'}`}>
                        {d.is_sp ? '🌸 SP' : 'Non-SP'}
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      <span className="px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-[10px] font-bold">{d.platform}</span>
                    </td>
                    <td className="px-3 py-2 max-w-[220px] truncate font-semibold" title={d.campaign_name}>{d.campaign_name}</td>
                    <td className="px-3 py-2 max-w-[180px] truncate text-violet-600 dark:text-violet-400" title={d.giving_level || 'Default'}>
                      {d.giving_level ? `🎁 ${d.giving_level}` : <span className="text-slate-400 italic">Default</span>}
                    </td>
                    <td className="px-3 py-2 font-mono text-[11px] font-bold text-cyan-700 dark:text-cyan-400">{d.code}</td>
                    <td className="px-3 py-2 text-right tabular-nums font-mono font-bold text-emerald-700 dark:text-emerald-400">
                      £{Number(d.amount || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap">
                      {d.feedback_emailed_at ? (
                        <span className="text-emerald-600 dark:text-emerald-400 font-semibold">Feedback Sent</span>
                      ) : d.emailed_at ? (
                        <span className="text-sky-600 dark:text-sky-400">Emailed ({d.emailed_at.slice(0, 10)})</span>
                      ) : (
                        <span className="text-amber-600 dark:text-amber-400 font-semibold">Not Emailed</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Pagination Footer */}
        {total > 0 && (
          <div className="px-4 py-2.5 border-t border-slate-200 dark:border-slate-800 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
            <div className="flex items-center gap-2">
              <span>
                Showing <b>{((page - 1) * pageSize + 1).toLocaleString()}</b>–<b>{Math.min(page * pageSize, total).toLocaleString()}</b> of <b>{total.toLocaleString()}</b>
              </span>
              <select
                value={pageSize}
                onChange={e => { setPageSize(Number(e.target.value)); setPage(1); }}
                className="bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded px-1.5 py-0.5 text-xs"
              >
                {[25, 50, 100, 250].map(sz => (
                  <option key={sz} value={sz}>{sz} / page</option>
                ))}
              </select>
            </div>
            <div className="flex items-center gap-1">
              <button
                type="button"
                disabled={page <= 1}
                onClick={() => setPage(p => Math.max(1, p - 1))}
                className="px-2.5 py-1 rounded-lg border border-slate-200 dark:border-slate-700 disabled:opacity-40 cursor-pointer flex items-center gap-1"
              >
                <ChevronLeft className="w-3.5 h-3.5" /> Previous
              </button>
              <span className="px-2 font-semibold">Page {page} of {totalPages}</span>
              <button
                type="button"
                disabled={page >= totalPages}
                onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                className="px-2.5 py-1 rounded-lg border border-slate-200 dark:border-slate-700 disabled:opacity-40 cursor-pointer flex items-center gap-1"
              >
                Next <ChevronRight className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
