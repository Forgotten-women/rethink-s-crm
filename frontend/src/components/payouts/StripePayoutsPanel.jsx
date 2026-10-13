import React, { useState, useEffect } from 'react';
import {
  CreditCard,
  RefreshCw,
  CheckCircle2,
  AlertCircle,
  Send,
  Download,
  Search,
  Filter,
  ArrowUpRight,
  FileSpreadsheet,
  Layers,
  ExternalLink,
  ShieldCheck,
  Clock,
  Sparkles,
  DollarSign,
  Check,
  Copy,
  ChevronDown,
  ChevronUp,
  ChevronRight,
  Info,
  Calendar,
  Zap,
  RotateCcw,
  UserCheck,
  Building,
  Hash,
  X
} from 'lucide-react';
import { API_BASE_URL } from '../../config';

export default function StripePayoutsPanel({ user, isSuperAdmin = true, activeCompany = 'rethink' }) {
  const [payouts, setPayouts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [copiedId, setCopiedId] = useState(null);

  // Per-payout action loading indicators
  const [reconcilingId, setReconcilingId] = useState(null);
  const [resyncingId, setResyncingId] = useState(null);
  const [sendingSlackId, setSendingSlackId] = useState(null);

  // Approval Modal State
  const [approvalModalPayout, setApprovalModalPayout] = useState(null);
  const [approverName, setApproverName] = useState(user?.name || user?.email || 'Finance Director');
  const [approvalLoading, setApprovalLoading] = useState(false);

  // Itemized Drawer / Modal State
  const [itemsModalPayout, setItemsModalPayout] = useState(null);
  const [itemsData, setItemsData] = useState({ items: [], total: 0, page: 1, total_pages: 1 });
  const [itemsLoading, setItemsLoading] = useState(false);
  const [sourceTypeFilter, setSourceTypeFilter] = useState('ALL');
  const [itemsPage, setItemsPage] = useState(1);

  // Toast / Feedback message
  const [feedback, setFeedback] = useState(null);

  const showFeedback = (type, message) => {
    setFeedback({ type, message });
    setTimeout(() => setFeedback(null), 5000);
  };

  const getAuthHeaders = () => {
    const token = localStorage.getItem('analytics_token');
    return token ? { 'Authorization': `Bearer ${token}` } : {};
  };

  const fetchPayouts = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE_URL}/api/payouts/stripe/list?limit=30`, {
        headers: getAuthHeaders()
      });
      if (!res.ok) {
        throw new Error(`Failed to load payouts (HTTP ${res.status})`);
      }
      const data = await res.json();
      setPayouts(data.payouts || []);
    } catch (err) {
      setError(err.message || 'Error communicating with Stripe Reconciliation API');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPayouts();
  }, []);

  const handleCopy = (text, id) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  // 1. Reconcile Payout (Read-only Stripe query + CRM match)
  const handleReconcile = async (payoutId) => {
    setReconcilingId(payoutId);
    try {
      const res = await fetch(`${API_BASE_URL}/api/payouts/stripe/reconcile`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders()
        },
        body: JSON.stringify({ payout_id: payoutId, company_id: activeCompany })
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || 'Failed to reconcile payout');
      }
      showFeedback('success', `Payout ${payoutId} reconciled! ${data.summary?.total_rows || 0} transactions classified.`);
      await fetchPayouts();
    } catch (err) {
      showFeedback('error', err.message);
    } finally {
      setReconcilingId(null);
    }
  };

  // 2. Re-sync with CRM (handles cases when donation codes or classifications were modified in CRM)
  const handleResyncWithCRM = async (payoutId) => {
    setResyncingId(payoutId);
    try {
      const res = await fetch(`${API_BASE_URL}/api/payouts/stripe/resync`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders()
        },
        body: JSON.stringify({ payout_id: payoutId, company_id: activeCompany })
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || 'Failed to re-sync with CRM');
      }
      showFeedback('success', `Re-sync complete: ${data.result?.refreshed_items || 0} transactions refreshed against CRM tables.`);
      await fetchPayouts();
    } catch (err) {
      showFeedback('error', err.message);
    } finally {
      setResyncingId(null);
    }
  };

  // 3. Approve and Send to Slack
  const handleApproveAndSend = async () => {
    if (!approvalModalPayout) return;
    setApprovalLoading(true);
    const pid = approvalModalPayout.payout_id;
    try {
      const res = await fetch(`${API_BASE_URL}/api/payouts/stripe/approve`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders()
        },
        body: JSON.stringify({ payout_id: pid, approved_by: approverName })
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || 'Approval request failed');
      }
      showFeedback('success', `Payout ${pid} approved and delivered to Slack #rt-payouts!`);
      setApprovalModalPayout(null);
      await fetchPayouts();
    } catch (err) {
      showFeedback('error', err.message);
    } finally {
      setApprovalLoading(false);
    }
  };

  // 4. Resend to Slack (for approved payouts)
  const handleResendToSlack = async (payoutId) => {
    setSendingSlackId(payoutId);
    try {
      const res = await fetch(`${API_BASE_URL}/api/payouts/stripe/resend`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders()
        },
        body: JSON.stringify({ payout_id: payoutId })
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || 'Failed to resend to Slack');
      }
      showFeedback('success', `Payout report for ${payoutId} resent to Slack #rt-payouts!`);
      await fetchPayouts();
    } catch (err) {
      showFeedback('error', err.message);
    } finally {
      setSendingSlackId(null);
    }
  };

  // 5. Fetch Itemized Transactions
  const fetchPayoutItems = async (payoutId, page = 1, srcType = sourceTypeFilter) => {
    setItemsLoading(true);
    try {
      const srcParam = srcType && srcType !== 'ALL' ? `&source_type=${srcType}` : '';
      const res = await fetch(`${API_BASE_URL}/api/payouts/stripe/items?payout_id=${encodeURIComponent(payoutId)}&page=${page}&page_size=50${srcParam}`, {
        headers: getAuthHeaders()
      });
      if (!res.ok) throw new Error('Failed to load itemized transactions');
      const data = await res.json();
      setItemsData(data);
    } catch (err) {
      showFeedback('error', err.message);
    } finally {
      setItemsLoading(false);
    }
  };

  const openItemsModal = (payout) => {
    setItemsModalPayout(payout);
    setSourceTypeFilter('ALL');
    setItemsPage(1);
    fetchPayoutItems(payout.payout_id, 1, 'ALL');
  };

  // Aggregated Stats
  const totalVolume = payouts.reduce((acc, p) => acc + (p.amount || 0), 0);
  const reconciledCount = payouts.filter(p => p.is_reconciled).length;
  const approvedCount = payouts.filter(p => p.approval_status === 'approved').length;

  return (
    <div className="space-y-6">
      {/* Toast Feedback */}
      {feedback && (
        <div className={`p-4 rounded-2xl border shadow-lg flex items-center justify-between gap-3 animate-fade-in ${
          feedback.type === 'success'
            ? 'bg-emerald-900/40 border-emerald-500/40 text-emerald-200'
            : 'bg-rose-900/40 border-rose-500/40 text-rose-200'
        }`}>
          <div className="flex items-center gap-2.5">
            {feedback.type === 'success' ? <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" /> : <AlertCircle className="w-5 h-5 text-rose-400 shrink-0" />}
            <span className="text-xs font-semibold">{feedback.message}</span>
          </div>
          <button onClick={() => setFeedback(null)} className="text-slate-400 hover:text-white p-1">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Settlement & Read-Only Notice Banner */}
      <div className="p-4 rounded-2xl bg-gradient-to-br from-cyan-950/40 via-slate-900/60 to-slate-900/80 border border-cyan-500/30 backdrop-blur-xl shadow-md">
        <div className="flex items-start gap-3">
          <div className="p-2 rounded-xl bg-cyan-500/20 text-cyan-400 shrink-0 mt-0.5">
            <ShieldCheck className="w-5 h-5" />
          </div>
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <span className="font-bold text-white text-xs">Exact Bank Settlement & Zero Drift</span>
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-cyan-500/20 text-cyan-300 font-mono font-bold">
                100% Read-Only Stripe Mode
              </span>
            </div>
            <p className="text-slate-300 text-[11px] mt-1 leading-relaxed">
              Automated reconciliation matches against <b>exact bank settlement pennies in GBP</b> as disbursed by Stripe.
              Classifications are queried directly from the CRM's master classification and project code tables.
              The Stripe integration operates in strictly <b>100% read-only mode</b> with zero write actions.
            </p>
          </div>
        </div>
      </div>

      {/* KPI Overview Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3.5">
        <div className="p-4 rounded-2xl bg-white/80 dark:bg-slate-900/80 border border-slate-200 dark:border-white/10 shadow-sm backdrop-blur-md">
          <div className="text-[11px] font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400 flex items-center gap-1.5">
            <CreditCard className="w-3.5 h-3.5 text-cyan-500" />
            <span>Recent Stripe Volume</span>
          </div>
          <div className="mt-2 text-xl font-black text-slate-900 dark:text-white font-mono">
            £{totalVolume.toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </div>
          <div className="text-[10px] text-slate-400 mt-0.5">{payouts.length} payout batches tracked</div>
        </div>

        <div className="p-4 rounded-2xl bg-white/80 dark:bg-slate-900/80 border border-slate-200 dark:border-white/10 shadow-sm backdrop-blur-md">
          <div className="text-[11px] font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400 flex items-center gap-1.5">
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />
            <span>Reconciled Batches</span>
          </div>
          <div className="mt-2 text-xl font-black text-emerald-600 dark:text-emerald-400 font-mono">
            {reconciledCount} <span className="text-xs font-normal text-slate-400">/ {payouts.length}</span>
          </div>
          <div className="text-[10px] text-slate-400 mt-0.5">Matched against CRM tables</div>
        </div>

        <div className="p-4 rounded-2xl bg-white/80 dark:bg-slate-900/80 border border-slate-200 dark:border-white/10 shadow-sm backdrop-blur-md">
          <div className="text-[11px] font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400 flex items-center gap-1.5">
            <ShieldCheck className="w-3.5 h-3.5 text-amber-500" />
            <span>Approval Status</span>
          </div>
          <div className="mt-2 text-xl font-black text-amber-600 dark:text-amber-400 font-mono">
            {approvedCount} <span className="text-xs font-normal text-slate-400">Approved</span>
          </div>
          <div className="text-[10px] text-slate-400 mt-0.5">{reconciledCount - approvedCount} awaiting approval</div>
        </div>

        <div className="p-4 rounded-2xl bg-white/80 dark:bg-slate-900/80 border border-slate-200 dark:border-white/10 shadow-sm backdrop-blur-md">
          <div className="text-[11px] font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400 flex items-center gap-1.5">
            <Send className="w-3.5 h-3.5 text-indigo-500" />
            <span>Slack Channel</span>
          </div>
          <div className="mt-2 text-sm font-bold text-slate-900 dark:text-white flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-emerald-500"></span>
            <span className="font-mono">#rt-payouts</span>
          </div>
          <div className="text-[10px] text-slate-400 mt-0.5">Reports delivered via uploadV2</div>
        </div>
      </div>

      {/* Payouts Table Card */}
      <div className="rounded-2xl border border-slate-200 dark:border-white/10 bg-white/90 dark:bg-slate-900/90 shadow-sm overflow-hidden backdrop-blur-xl">
        <div className="p-4 border-b border-slate-200 dark:border-white/10 flex items-center justify-between flex-wrap gap-3">
          <div className="flex items-center gap-2">
            <CreditCard className="w-4 h-4 text-cyan-500" />
            <h2 className="text-sm font-bold text-slate-900 dark:text-white">Stripe Bank Payout Batches</h2>
            <span className="text-xs px-2.5 py-0.5 rounded-full bg-cyan-500/10 text-cyan-600 dark:text-cyan-400 font-semibold">
              Rethink Charity Payouts
            </span>
          </div>

          <button
            onClick={fetchPayouts}
            disabled={loading}
            className="px-3 py-1.5 text-xs font-bold text-slate-700 dark:text-slate-200 bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 rounded-xl border border-slate-300 dark:border-white/10 transition-all flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin text-cyan-500' : ''}`} />
            <span>Refresh Stripe Payouts</span>
          </button>
        </div>

        {/* Payouts Listing */}
        <div className="divide-y divide-slate-200 dark:divide-white/5">
          {payouts.length === 0 && !loading && (
            <div className="p-12 text-center text-slate-400 text-xs">
              No recent Stripe payouts found. Click refresh to query Stripe.
            </div>
          )}

          {payouts.map((p) => {
            const isReconciled = p.is_reconciled;
            const isApproved = p.approval_status === 'approved';
            const isReconciling = reconcilingId === p.payout_id;
            const isResyncing = resyncingId === p.payout_id;
            const isSendingSlack = sendingSlackId === p.payout_id;

            return (
              <div key={p.payout_id} className="p-4 hover:bg-slate-50/50 dark:hover:bg-slate-800/30 transition-all">
                <div className="flex items-start justify-between flex-wrap gap-4">
                  {/* Left Column: Payout Info */}
                  <div className="space-y-1.5">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-mono font-black text-sm text-slate-900 dark:text-white">
                        £{Number(p.amount || 0).toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </span>
                      <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-500 font-bold">
                        {p.currency}
                      </span>
                      <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full uppercase tracking-wider ${
                        p.status === 'paid' ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400' : 'bg-slate-500/10 text-slate-400'
                      }`}>
                        {p.status}
                      </span>

                      {/* Reconciliation State Badge */}
                      {isReconciled ? (
                        <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-600 dark:text-emerald-400 flex items-center gap-1">
                          <CheckCircle2 className="w-3 h-3" /> Reconciled ({p.total_transactions} txns)
                        </span>
                      ) : (
                        <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-600 dark:text-amber-400 flex items-center gap-1">
                          <Clock className="w-3 h-3" /> Pending Reconcile
                        </span>
                      )}

                      {/* Approval State Badge */}
                      {isReconciled && (
                        isApproved ? (
                          <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-teal-500/20 text-teal-600 dark:text-teal-400 flex items-center gap-1">
                            <ShieldCheck className="w-3 h-3" /> Approved & Sent to Slack
                          </span>
                        ) : (
                          <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-orange-500/20 text-orange-600 dark:text-orange-400 flex items-center gap-1">
                            <AlertCircle className="w-3 h-3" /> Awaiting Approval
                          </span>
                        )
                      )}
                    </div>

                    <div className="flex items-center gap-3 text-xs text-slate-500 dark:text-slate-400 flex-wrap">
                      <div className="flex items-center gap-1">
                        <span className="text-slate-400 font-mono">ID:</span>
                        <code className="bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 rounded text-[11px] font-mono font-medium text-slate-700 dark:text-slate-300">
                          {p.payout_id}
                        </code>
                        <button
                          onClick={() => handleCopy(p.payout_id, p.payout_id)}
                          className="p-1 hover:text-cyan-500 transition-colors"
                          title="Copy Payout ID"
                        >
                          {copiedId === p.payout_id ? <Check className="w-3 h-3 text-emerald-500" /> : <Copy className="w-3 h-3" />}
                        </button>
                      </div>

                      <div className="flex items-center gap-1">
                        <Calendar className="w-3 h-3 text-slate-400" />
                        <span>Arrival: <b>{p.arrival_date || 'N/A'}</b></span>
                      </div>

                      {p.approved_by && (
                        <div className="flex items-center gap-1 text-[11px] text-teal-600 dark:text-teal-400">
                          <UserCheck className="w-3 h-3" />
                          <span>Approved by <b>{p.approved_by}</b></span>
                        </div>
                      )}
                    </div>

                    {/* Financial Summary Strip (When Reconciled) */}
                    {isReconciled && (
                      <div className="pt-2 flex items-center gap-4 text-xs flex-wrap">
                        <div className="flex items-center gap-1 text-slate-600 dark:text-slate-300">
                          <span className="text-slate-400">Gross:</span>
                          <b className="font-mono">£{Number(p.total_gross || 0).toLocaleString('en-GB', { minimumFractionDigits: 2 })}</b>
                        </div>
                        <div className="flex items-center gap-1 text-rose-600 dark:text-rose-400">
                          <span className="text-slate-400">Stripe Fees:</span>
                          <b className="font-mono">£{Number(p.total_fees || 0).toLocaleString('en-GB', { minimumFractionDigits: 2 })}</b>
                        </div>
                        <div className="flex items-center gap-1 text-emerald-600 dark:text-emerald-400">
                          <span className="text-slate-400">Net Settled:</span>
                          <b className="font-mono">£{Number(p.total_net || 0).toLocaleString('en-GB', { minimumFractionDigits: 2 })}</b>
                        </div>

                        {/* Fund Breakdown Chips */}
                        {p.funds_summary && Object.keys(p.funds_summary).length > 0 && (
                          <div className="flex items-center gap-1.5 flex-wrap">
                            <span className="text-slate-400 text-[10px] uppercase font-bold">Funds:</span>
                            {Object.entries(p.funds_summary).slice(0, 4).map(([fCode, amt]) => (
                              <span key={fCode} className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 font-mono font-bold">
                                {fCode}: £{amt.toFixed(2)}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>

                  {/* Right Column: Action Buttons */}
                  <div className="flex items-center gap-2 flex-wrap self-center">
                    {/* 1. Reconcile Button */}
                    <button
                      onClick={() => handleReconcile(p.payout_id)}
                      disabled={isReconciling}
                      className={`px-3 py-1.5 text-xs font-bold rounded-xl transition-all flex items-center gap-1.5 cursor-pointer shadow-sm ${
                        !isReconciled
                          ? 'bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-white shadow-cyan-500/20'
                          : 'bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700 border border-slate-300 dark:border-white/10'
                      }`}
                      title={isReconciled ? "Re-run read-only reconciliation from Stripe" : "Run read-only reconciliation for this payout"}
                    >
                      <RefreshCw className={`w-3.5 h-3.5 ${isReconciling ? 'animate-spin text-cyan-400' : ''}`} />
                      <span>{isReconciling ? 'Reconciling...' : isReconciled ? 'Re-reconcile' : 'Reconcile'}</span>
                    </button>

                    {/* 2. Re-sync with CRM (solves out-of-sync cases if donation code or campaign classification changed) */}
                    {isReconciled && (
                      <button
                        onClick={() => handleResyncWithCRM(p.payout_id)}
                        disabled={isResyncing}
                        className="px-3 py-1.5 text-xs font-bold rounded-xl bg-indigo-50 dark:bg-indigo-950/40 text-indigo-700 dark:text-indigo-300 hover:bg-indigo-100 dark:hover:bg-indigo-900/60 border border-indigo-500/30 transition-all flex items-center gap-1.5 cursor-pointer shadow-sm"
                        title="Re-query CRM tables (donations, platform_campaign_mappings, master_project_codes) to refresh codes and fund allocations"
                      >
                        <RotateCcw className={`w-3.5 h-3.5 ${isResyncing ? 'animate-spin text-indigo-400' : ''}`} />
                        <span>{isResyncing ? 'Re-syncing...' : 'Re-sync with CRM'}</span>
                      </button>
                    )}

                    {/* 3. Review & Approve Modal Button */}
                    {isReconciled && !isApproved && (
                      <button
                        onClick={() => setApprovalModalPayout(p)}
                        className="px-3 py-1.5 text-xs font-bold rounded-xl bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white shadow-md shadow-emerald-500/20 transition-all flex items-center gap-1.5 cursor-pointer"
                        title="Review fund allocations and post approved payout to Slack #rt-payouts"
                      >
                        <Send className="w-3.5 h-3.5" />
                        <span>Review & Approve</span>
                      </button>
                    )}

                    {/* 4. Resend to Slack Button (for already approved payouts) */}
                    {isReconciled && isApproved && (
                      <button
                        onClick={() => handleResendToSlack(p.payout_id)}
                        disabled={isSendingSlack}
                        className="px-3 py-1.5 text-xs font-bold rounded-xl bg-teal-50 dark:bg-teal-950/40 text-teal-700 dark:text-teal-300 hover:bg-teal-100 dark:hover:bg-teal-900/60 border border-teal-500/30 transition-all flex items-center gap-1.5 cursor-pointer shadow-sm"
                        title="Resend approved payout breakdown and CSV file to Slack #rt-payouts"
                      >
                        <Send className={`w-3.5 h-3.5 ${isSendingSlack ? 'animate-spin text-teal-400' : ''}`} />
                        <span>{isSendingSlack ? 'Sending...' : 'Resend to Slack'}</span>
                      </button>
                    )}

                    {/* 5. View Itemized Transactions */}
                    {isReconciled && (
                      <button
                        onClick={() => openItemsModal(p)}
                        className="px-2.5 py-1.5 text-xs font-bold rounded-xl bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700 border border-slate-300 dark:border-white/10 transition-all flex items-center gap-1 cursor-pointer"
                        title="View itemized transactions in this payout"
                      >
                        <Layers className="w-3.5 h-3.5" />
                        <span>Items</span>
                      </button>
                    )}

                    {/* 6. Download Enriched CSV */}
                    {isReconciled && (
                      <a
                        href={`${API_BASE_URL}/api/payouts/stripe/download?payout_id=${encodeURIComponent(p.payout_id)}`}
                        download
                        className="px-2.5 py-1.5 text-xs font-bold rounded-xl bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700 border border-slate-300 dark:border-white/10 transition-all flex items-center gap-1"
                        title="Download enriched reconciliation CSV with all 8 accounting dimensions"
                      >
                        <Download className="w-3.5 h-3.5" />
                        <span>CSV</span>
                      </a>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* APPROVAL MODAL */}
      {approvalModalPayout && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white dark:bg-slate-900 rounded-3xl border border-slate-200 dark:border-white/10 max-w-xl w-full p-6 shadow-2xl space-y-5 animate-scale-in">
            <div className="flex items-center justify-between border-b border-slate-200 dark:border-white/10 pb-4">
              <div className="flex items-center gap-2.5">
                <div className="p-2 rounded-xl bg-emerald-500/20 text-emerald-500">
                  <ShieldCheck className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-slate-900 dark:text-white">Approve Stripe Payout & Deliver to Slack</h3>
                  <p className="text-xs text-slate-500 dark:text-slate-400 font-mono">
                    Payout ID: {approvalModalPayout.payout_id}
                  </p>
                </div>
              </div>
              <button
                onClick={() => setApprovalModalPayout(null)}
                className="text-slate-400 hover:text-white p-1"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Financial Overview */}
            <div className="grid grid-cols-3 gap-3 p-3.5 rounded-2xl bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-white/5 font-mono text-center">
              <div>
                <span className="text-[10px] text-slate-500 dark:text-slate-400 block font-sans">Gross Volume</span>
                <span className="text-sm font-bold text-slate-900 dark:text-white">
                  £{Number(approvalModalPayout.total_gross || 0).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                </span>
              </div>
              <div>
                <span className="text-[10px] text-rose-500 block font-sans">Stripe Fees</span>
                <span className="text-sm font-bold text-rose-600 dark:text-rose-400">
                  £{Number(approvalModalPayout.total_fees || 0).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                </span>
              </div>
              <div>
                <span className="text-[10px] text-emerald-500 block font-sans">Net Payout</span>
                <span className="text-sm font-bold text-emerald-600 dark:text-emerald-400">
                  £{Number(approvalModalPayout.total_net || 0).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                </span>
              </div>
            </div>

            {/* Fund Breakdown Table */}
            {approvalModalPayout.funds_summary && Object.keys(approvalModalPayout.funds_summary).length > 0 && (
              <div>
                <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-2">
                  Worked-Out Fund Code Allocations (Net Settlement)
                </h4>
                <div className="rounded-xl border border-slate-200 dark:border-white/10 overflow-hidden divide-y divide-slate-200 dark:divide-white/5 text-xs">
                  {Object.entries(approvalModalPayout.funds_summary).map(([fCode, amt]) => (
                    <div key={fCode} className="flex items-center justify-between p-2.5 bg-slate-50/50 dark:bg-slate-800/30">
                      <span className="font-mono font-bold text-indigo-600 dark:text-indigo-400">{fCode}</span>
                      <span className="font-mono font-bold text-slate-900 dark:text-white">£{amt.toFixed(2)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Approver Name Input */}
            <div>
              <label className="block text-xs font-bold text-slate-700 dark:text-slate-300 mb-1.5">
                Sign-off Officer / Approver Name
              </label>
              <input
                type="text"
                value={approverName}
                onChange={(e) => setApproverName(e.target.value)}
                placeholder="e.g. Osman (Finance Director)"
                className="w-full px-3.5 py-2 rounded-xl text-xs bg-slate-100 dark:bg-slate-800 border border-slate-300 dark:border-white/10 text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-emerald-500"
              />
            </div>

            {/* Modal Actions */}
            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                onClick={() => setApprovalModalPayout(null)}
                className="px-4 py-2 text-xs font-bold rounded-xl text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-all cursor-pointer"
              >
                Cancel
              </button>
              <button
                onClick={handleApproveAndSend}
                disabled={approvalLoading || !approverName.trim()}
                className="px-5 py-2 text-xs font-bold text-white bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 rounded-xl shadow-md shadow-emerald-500/20 transition-all flex items-center gap-2 cursor-pointer disabled:opacity-50"
              >
                <Send className={`w-3.5 h-3.5 ${approvalLoading ? 'animate-spin' : ''}`} />
                <span>{approvalLoading ? 'Broadcasting to Slack...' : 'Confirm Approval & Post to Slack'}</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ITEMIZED TRANSACTIONS MODAL */}
      {itemsModalPayout && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white dark:bg-slate-900 rounded-3xl border border-slate-200 dark:border-white/10 max-w-6xl w-full h-[85vh] flex flex-col p-6 shadow-2xl space-y-4 animate-scale-in">
            {/* Header */}
            <div className="flex items-center justify-between border-b border-slate-200 dark:border-white/10 pb-4 shrink-0">
              <div className="flex items-center gap-3">
                <div className="p-2 rounded-xl bg-cyan-500/20 text-cyan-500">
                  <Layers className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-slate-900 dark:text-white">Itemized Transactions</h3>
                  <p className="text-xs text-slate-500 dark:text-slate-400 font-mono">
                    Payout ID: {itemsModalPayout.payout_id} · {itemsData.total} Total Records
                  </p>
                </div>
              </div>
              <button
                onClick={() => setItemsModalPayout(null)}
                className="text-slate-400 hover:text-white p-1"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Filter Tabs */}
            <div className="flex items-center gap-2 shrink-0">
              <span className="text-xs font-bold text-slate-500 dark:text-slate-400 mr-1 flex items-center gap-1">
                <Filter className="w-3.5 h-3.5" /> Source:
              </span>
              {[
                { id: 'ALL', label: 'All Transactions' },
                { id: 'website', label: 'Website Only' },
                { id: 'givebrite', label: 'GiveBrite Only' },
                { id: 'fee', label: 'System Fees' }
              ].map(st => (
                <button
                  key={st.id}
                  onClick={() => {
                    setSourceTypeFilter(st.id);
                    setItemsPage(1);
                    fetchPayoutItems(itemsModalPayout.payout_id, 1, st.id);
                  }}
                  className={`px-3 py-1.5 text-xs font-bold rounded-xl transition-all cursor-pointer ${
                    sourceTypeFilter === st.id
                      ? 'bg-cyan-600 text-white shadow-sm'
                      : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:text-white'
                  }`}
                >
                  {st.label}
                </button>
              ))}
            </div>

            {/* Items Table */}
            <div className="flex-1 overflow-auto rounded-2xl border border-slate-200 dark:border-white/10 bg-slate-50/50 dark:bg-slate-900/50">
              <table className="w-full text-left text-xs border-collapse">
                <thead className="sticky top-0 bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border-b border-slate-200 dark:border-white/10">
                  <tr>
                    <th className="p-3 font-bold">Source</th>
                    <th className="p-3 font-bold">Date</th>
                    <th className="p-3 font-bold">Donor / Project</th>
                    <th className="p-3 font-bold text-right">Gross</th>
                    <th className="p-3 font-bold text-right">Fee</th>
                    <th className="p-3 font-bold text-right">Net</th>
                    <th className="p-3 font-bold">Code</th>
                    <th className="p-3 font-bold">Heading</th>
                    <th className="p-3 font-bold">Sub-Heading</th>
                    <th className="p-3 font-bold">Fund Code</th>
                    <th className="p-3 font-bold">Zakat</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200 dark:divide-white/5">
                  {itemsLoading && (
                    <tr>
                      <td colSpan="11" className="p-8 text-center text-slate-400">
                        <RefreshCw className="w-5 h-5 animate-spin mx-auto text-cyan-500 mb-2" />
                        Loading transaction items...
                      </td>
                    </tr>
                  )}

                  {!itemsLoading && itemsData.items.length === 0 && (
                    <tr>
                      <td colSpan="11" className="p-8 text-center text-slate-400">
                        No transactions found matching this filter.
                      </td>
                    </tr>
                  )}

                  {!itemsLoading && itemsData.items.map((it, idx) => (
                    <tr key={idx} className="hover:bg-slate-100/50 dark:hover:bg-slate-800/40">
                      <td className="p-3">
                        <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full uppercase ${
                          it.source_type === 'givebrite'
                            ? 'bg-indigo-500/20 text-indigo-400'
                            : it.source_type === 'website'
                            ? 'bg-emerald-500/20 text-emerald-400'
                            : 'bg-slate-500/20 text-slate-400'
                        }`}>
                          {it.source_type || 'Website'}
                        </span>
                      </td>
                      <td className="p-3 font-mono text-[11px] text-slate-500 dark:text-slate-400 whitespace-nowrap">
                        {it.created_at?.slice(0, 10)}
                      </td>
                      <td className="p-3 max-w-xs truncate">
                        <div className="font-semibold text-slate-900 dark:text-white truncate">
                          {it.donor_name || it.project_name || 'Anonymous Donor'}
                        </div>
                        <div className="text-[10px] text-slate-400 truncate">
                          {it.project_name}
                        </div>
                      </td>
                      <td className="p-3 text-right font-mono font-bold text-slate-900 dark:text-white">
                        £{Number(it.gross || 0).toFixed(2)}
                      </td>
                      <td className="p-3 text-right font-mono text-rose-500">
                        £{Number(it.fee || 0).toFixed(2)}
                      </td>
                      <td className="p-3 text-right font-mono font-bold text-emerald-600 dark:text-emerald-400">
                        £{Number(it.net || 0).toFixed(2)}
                      </td>
                      <td className="p-3 font-mono font-bold text-[11px] text-cyan-600 dark:text-cyan-400 whitespace-nowrap">
                        {it.code || 'Unassigned'}
                      </td>
                      <td className="p-3 text-[11px] text-slate-700 dark:text-slate-300 font-medium whitespace-nowrap">
                        {it.heading || it.department || '—'}
                      </td>
                      <td className="p-3 text-[11px] text-slate-500 dark:text-slate-400 whitespace-nowrap">
                        {it.subheading || it.office || '—'}
                      </td>
                      <td className="p-3 font-mono text-[11px] text-indigo-600 dark:text-indigo-400 whitespace-nowrap">
                        {it.fund_code || 'F1-EMR'}
                      </td>
                      <td className="p-3">
                        <span className={`text-[10px] px-1.5 py-0.5 rounded font-bold ${
                          it.zakat_eligibility === 'Zakat'
                            ? 'bg-emerald-500/10 text-emerald-500'
                            : 'bg-slate-500/10 text-slate-400'
                        }`}>
                          {it.zakat_eligibility || 'Zakat'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination Controls */}
            {itemsData.total_pages > 1 && (
              <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400 shrink-0 pt-2">
                <span>Page {itemsData.page} of {itemsData.total_pages}</span>
                <div className="flex items-center gap-2">
                  <button
                    disabled={itemsData.page <= 1 || itemsLoading}
                    onClick={() => {
                      const nextP = itemsData.page - 1;
                      setItemsPage(nextP);
                      fetchPayoutItems(itemsModalPayout.payout_id, nextP);
                    }}
                    className="px-3 py-1 rounded-lg bg-slate-100 dark:bg-slate-800 disabled:opacity-40"
                  >
                    Previous
                  </button>
                  <button
                    disabled={itemsData.page >= itemsData.total_pages || itemsLoading}
                    onClick={() => {
                      const nextP = itemsData.page + 1;
                      setItemsPage(nextP);
                      fetchPayoutItems(itemsModalPayout.payout_id, nextP);
                    }}
                    className="px-3 py-1 rounded-lg bg-slate-100 dark:bg-slate-800 disabled:opacity-40"
                  >
                    Next
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
