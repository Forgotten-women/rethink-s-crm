import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  CheckCircle2, AlertTriangle, Clock, XCircle, ArrowRightLeft, Building2,
  Wallet, CreditCard, Search, RefreshCw, Check, X, ShieldAlert, ArrowRight, User
} from 'lucide-react';
import { treasuryApi } from './TreasuryPanels';
import { formatMoney } from './treasuryUtils';

export function ApprovalsPanel({
  company = 'rethink',
  canApproveTransfers = false,
  canApproveExpenses = false,
  onOpenAccount,
  onOpenPot,
}) {
  const [data, setData] = useState({ approvals: [], counts: { pending: 0, approved: 0, rejected: 0, total: 0 } });
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');
  const [statusFilter, setStatusFilter] = useState('PENDING'); // 'PENDING' | 'ALL' | 'APPROVED' | 'REJECTED'
  const [typeFilter, setTypeFilter] = useState('ALL'); // 'ALL' | 'account_transfer' | 'pot_reallocation' | 'expense'
  const [search, setSearch] = useState('');
  const [rejectModal, setRejectModal] = useState(null); // approval item to reject
  const [rejectReason, setRejectReason] = useState('');
  const [actionBusy, setActionBusy] = useState(false);
  const [toast, setToast] = useState(null);

  const showToast = (msg, type = 'success') => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 4500);
  };

  const fetchApprovals = useCallback(async () => {
    setLoading(true);
    setErr('');
    try {
      const res = await treasuryApi('/approvals', {
        company,
        params: {
          status: statusFilter,
          transfer_type: typeFilter,
          search: search.trim() || undefined,
        },
      });
      setData(res || { approvals: [], counts: { pending: 0, approved: 0, rejected: 0, total: 0 } });
    } catch (e) {
      setErr(e.message || 'Failed to load approvals.');
    } finally {
      setLoading(false);
    }
  }, [company, statusFilter, typeFilter, search]);

  useEffect(() => {
    fetchApprovals();
  }, [fetchApprovals]);

  const handleReview = async (item, action, reason = '') => {
    setActionBusy(true);
    try {
      const res = await treasuryApi(`/approvals/${encodeURIComponent(item.id)}/review`, {
        method: 'POST',
        company,
        body: { action, reason, company_id: company },
      });
      showToast(res.message || `Transfer ${action.toLowerCase()}ed successfully.`, action === 'APPROVE' ? 'success' : 'error');
      setRejectModal(null);
      setRejectReason('');
      fetchApprovals();
    } catch (e) {
      showToast(e.message || `Failed to ${action.toLowerCase()} transfer.`, 'error');
    } finally {
      setActionBusy(false);
    }
  };

  const pendingVolumeUsd = useMemo(() => {
    return (data.approvals || [])
      .filter((a) => a.status === 'PENDING')
      .reduce((sum, a) => sum + Number(a.amount_usd || 0), 0);
  }, [data.approvals]);

  return (
    <div className="space-y-5">
      {toast && (
        <div
          role="status"
          className={`fixed bottom-6 right-6 z-[70] px-5 py-3 rounded-xl shadow-2xl border flex items-center gap-2.5 keep-white ${
            toast.type === 'error' ? 'bg-rose-600 border-rose-400' : 'bg-emerald-600 border-emerald-400'
          }`}
        >
          {toast.type === 'error' ? <ShieldAlert className="w-4 h-4" /> : <CheckCircle2 className="w-4 h-4" />}
          <span className="font-semibold text-xs">{toast.msg}</span>
        </div>
      )}

      {/* Top KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3.5">
        <div className="glass-panel p-4 flex flex-col justify-between border-l-4 border-l-amber-500 border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/60 shadow-xs">
          <div className="flex items-center justify-between text-xs text-amber-600 dark:text-amber-400 font-bold">
            <span>Pending Review</span>
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-amber-500" />
            </span>
          </div>
          <div className="text-2xl font-black tabular-nums mt-1 text-slate-900 dark:text-slate-100">
            {data.counts?.pending || 0}
          </div>
          <div className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5">
            Pending amounts ≈ {formatMoney(pendingVolumeUsd, 'USD', { compact: true })}
          </div>
        </div>

        <div className="glass-panel p-4 flex flex-col justify-between border-l-4 border-l-emerald-500 border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/60 shadow-xs">
          <div className="flex items-center justify-between text-xs text-emerald-600 dark:text-emerald-400 font-bold">
            <span>Approved</span>
            <CheckCircle2 className="w-4 h-4" />
          </div>
          <div className="text-2xl font-black tabular-nums mt-1 text-slate-900 dark:text-slate-100">
            {data.counts?.approved || 0}
          </div>
          <div className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5">Executed into ledger</div>
        </div>

        <div className="glass-panel p-4 flex flex-col justify-between border-l-4 border-l-rose-500 border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/60 shadow-xs">
          <div className="flex items-center justify-between text-xs text-rose-600 dark:text-rose-400 font-bold">
            <span>Rejected</span>
            <XCircle className="w-4 h-4" />
          </div>
          <div className="text-2xl font-black tabular-nums mt-1 text-slate-900 dark:text-slate-100">
            {data.counts?.rejected || 0}
          </div>
          <div className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5">Declined by manager</div>
        </div>

        <div className="glass-panel p-4 flex flex-col justify-between border-l-4 border-l-blue-500 border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/60 shadow-xs">
          <div className="flex items-center justify-between text-xs text-slate-600 dark:text-slate-400 font-bold">
            <span>Total Requests</span>
            <ArrowRightLeft className="w-4 h-4" />
          </div>
          <div className="text-2xl font-black tabular-nums mt-1 text-slate-900 dark:text-slate-100">
            {data.counts?.total || 0}
          </div>
          <div className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5">Lifetime workflow total</div>
        </div>
      </div>

      {/* Filter and Control Bar */}
      <div className="glass-panel p-4 space-y-3 rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/60 shadow-xs">
        <div className="flex flex-wrap items-center justify-between gap-3">
          {/* Status Pills */}
          <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Status filter">
            {[
              { id: 'PENDING', label: 'Pending Review', count: data.counts?.pending },
              { id: 'ALL', label: 'All Requests', count: data.counts?.total },
              { id: 'APPROVED', label: 'Approved', count: data.counts?.approved },
              { id: 'REJECTED', label: 'Rejected', count: data.counts?.rejected },
            ].map((st) => (
              <button
                key={st.id}
                type="button"
                onClick={() => setStatusFilter(st.id)}
                className={`px-3 py-1.5 rounded-xl text-xs font-bold flex items-center gap-1.5 transition-all ${
                  statusFilter === st.id
                    ? 'bg-blue-600 text-white shadow-xs'
                    : 'bg-slate-100 dark:bg-slate-800/60 text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 border border-slate-200 dark:border-slate-700/50'
                }`}
              >
                <span>{st.label}</span>
                {st.count != null && (
                  <span className={`text-[10px] px-1.5 py-0.2 rounded-full font-black ${
                    statusFilter === st.id ? 'bg-white/25 text-white' : 'bg-slate-200 dark:bg-slate-700 text-slate-600 dark:text-slate-300'
                  }`}>
                    {st.count}
                  </span>
                )}
              </button>
            ))}
          </div>

          {/* Search & Refresh */}
          <div className="flex items-center gap-2">
            <div className="relative">
              <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search by ID, account, code…"
                className="pl-8 pr-3 py-1.5 rounded-xl border border-slate-200 dark:border-slate-700/60 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 text-xs w-56 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>
            <button
              type="button"
              onClick={fetchApprovals}
              className="p-1.5 rounded-xl border border-slate-200 dark:border-slate-700/60 bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100"
              title="Refresh approvals"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin text-blue-500' : ''}`} />
            </button>
          </div>
        </div>

        {/* Transfer Type Filters */}
        <div className="flex flex-wrap items-center gap-1.5 pt-2 border-t border-slate-100 dark:border-slate-800 text-xs">
          <span className="text-slate-500 dark:text-slate-400 text-[11px] font-semibold mr-1">Type:</span>
          {[
            { id: 'ALL', label: 'All Types' },
            { id: 'account_transfer', label: 'Account Transfers' },
            { id: 'pot_reallocation', label: 'Pot Reallocations' },
            { id: 'expense', label: 'Outgoing Expenses' },
          ].map((tp) => (
            <button
              key={tp.id}
              type="button"
              onClick={() => setTypeFilter(tp.id)}
              className={`px-2.5 py-1 rounded-lg text-xs font-semibold transition-colors ${
                typeFilter === tp.id
                  ? 'bg-blue-50 dark:bg-blue-950/40 text-blue-700 dark:text-blue-400 border border-blue-200 dark:border-blue-800'
                  : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200'
              }`}
            >
              {tp.label}
            </button>
          ))}
        </div>
      </div>

      {err && (
        <div className="glass-panel p-4 text-sm text-rose-500 flex items-center gap-2 rounded-2xl border border-rose-200 dark:border-rose-900/50 bg-rose-50 dark:bg-rose-950/20">
          <AlertTriangle className="w-4 h-4" /> {err}
        </div>
      )}

      {/* Approvals List */}
      {data.approvals && data.approvals.length > 0 ? (
        <div className="space-y-3">
          {data.approvals.map((item) => {
            const isPending = item.status === 'PENDING';
            const isApproved = item.status === 'APPROVED';
            const isRejected = item.status === 'REJECTED';
            const isAccTransfer = item.transfer_type === 'account_transfer';
            const isPotRealloc = item.transfer_type === 'pot_reallocation';
            const isExpense = item.transfer_type === 'expense';

            const userCanReviewThis = isExpense ? canApproveExpenses : canApproveTransfers;

            return (
              <div
                key={item.id}
                className={`glass-panel p-4 sm:p-5 rounded-2xl border bg-white dark:bg-slate-900/60 transition-all shadow-xs hover:shadow-md flex flex-col md:flex-row md:items-center justify-between gap-4 ${
                  isPending
                    ? 'border-l-4 border-l-amber-500 border-slate-200 dark:border-slate-800'
                    : isApproved
                    ? 'border-l-4 border-l-emerald-500 border-slate-200 dark:border-slate-800'
                    : 'border-l-4 border-l-rose-500 border-slate-200 dark:border-slate-800 opacity-90'
                }`}
              >
                {/* Left Info Column */}
                <div className="space-y-2.5 min-w-0 flex-1">
                  {/* Badges & ID */}
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-[11px] font-bold px-2 py-0.5 rounded-md bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700/60 shadow-2xs">
                      {item.id}
                    </span>

                    {/* Type Badge */}
                    <span
                      className={`inline-flex items-center gap-1.5 px-2.5 py-0.8 rounded-full text-[10px] font-black uppercase tracking-wider border shadow-2xs ${
                        isAccTransfer
                          ? 'bg-cyan-500/10 text-cyan-700 dark:text-cyan-400 border-cyan-500/25'
                          : isPotRealloc
                          ? 'bg-purple-500/10 text-purple-700 dark:text-purple-400 border-purple-500/25'
                          : 'bg-amber-500/10 text-amber-700 dark:text-amber-400 border-amber-500/25'
                      }`}
                    >
                      {isAccTransfer && <Building2 className="w-3 h-3 text-cyan-600 dark:text-cyan-400" />}
                      {isPotRealloc && <Wallet className="w-3 h-3 text-purple-600 dark:text-purple-400" />}
                      {isExpense && <CreditCard className="w-3 h-3 text-amber-600 dark:text-amber-400" />}
                      <span>{isAccTransfer ? 'Account Transfer' : isPotRealloc ? 'Pot Reallocation' : 'Outgoing Expense'}</span>
                    </span>

                    {/* Status Badge */}
                    <span
                      className={`inline-flex items-center gap-1.5 px-2.5 py-0.8 rounded-full text-[10px] font-black uppercase tracking-wider border shadow-2xs ${
                        isPending
                          ? 'bg-amber-500/10 text-amber-700 dark:text-amber-400 border-amber-500/25'
                          : isApproved
                          ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/25'
                          : 'bg-rose-500/10 text-rose-700 dark:text-rose-400 border-rose-500/25'
                      }`}
                    >
                      {isPending && <Clock className="w-3 h-3 text-amber-500" />}
                      {isApproved && <Check className="w-3 h-3 text-emerald-500 stroke-[2.5]" />}
                      {isRejected && <X className="w-3 h-3 text-rose-500 stroke-[2.5]" />}
                      <span>{isPending ? 'Pending Approval' : isApproved ? 'Approved' : 'Rejected'}</span>
                    </span>

                    {/* Timestamp */}
                    {item.requested_at && (
                      <span className="text-[11px] font-mono text-slate-400 dark:text-slate-500 ml-auto hidden sm:inline">
                        {String(item.requested_at).slice(0, 16)}
                      </span>
                    )}
                  </div>

                  {/* Route & Title */}
                  <div>
                    <h3 className="font-extrabold text-sm sm:text-base text-slate-900 dark:text-slate-100 flex items-center gap-2 flex-wrap">
                      <span>{item.source_name || 'Source'}</span>
                      <ArrowRight className="w-4 h-4 text-slate-400 shrink-0" />
                      <span>{item.destination_name || 'Destination'}</span>
                    </h3>
                    {item.title && (
                      <p className="text-xs font-medium text-slate-600 dark:text-slate-300 mt-1 leading-snug">
                        {item.title}
                      </p>
                    )}
                  </div>

                  {/* Meta / Audit info */}
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-slate-500 dark:text-slate-400 pt-1">
                    <span className="flex items-center gap-1">
                      <User className="w-3 h-3 text-slate-400" />
                      <span>Requested by</span>
                      <strong className="text-slate-800 dark:text-slate-200 font-semibold">{item.requested_by || 'User'}</strong>
                    </span>

                    {item.reviewed_by && (
                      <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-bold ${
                        isApproved
                          ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border border-emerald-500/20'
                          : 'bg-rose-500/10 text-rose-700 dark:text-rose-400 border border-rose-500/20'
                      }`}>
                        {isApproved ? '✓ Approved by ' : '✗ Rejected by '}
                        <strong>{item.reviewed_by}</strong>
                        {item.reviewed_at ? ` on ${String(item.reviewed_at).slice(0, 16)}` : ''}
                      </span>
                    )}
                  </div>

                  {/* Rejection reason box */}
                  {item.rejection_reason && (
                    <div className="p-2 rounded-xl bg-rose-500/5 dark:bg-rose-950/20 border border-rose-500/20 text-xs text-rose-700 dark:text-rose-300 flex items-start gap-1.5">
                      <AlertTriangle className="w-3.5 h-3.5 text-rose-500 shrink-0 mt-0.5" />
                      <div>
                        <span className="font-bold">Rejection reason: </span>
                        <span>{item.rejection_reason}</span>
                      </div>
                    </div>
                  )}
                </div>

                {/* Right Column: Amount & Actions */}
                <div className="flex flex-col md:items-end justify-between gap-3 shrink-0 pt-3 md:pt-0 border-t md:border-t-0 border-slate-100 dark:border-slate-800">
                  <div className="md:text-right">
                    <div className="text-xl font-black font-mono tabular-nums text-slate-900 dark:text-slate-100">
                      {formatMoney(item.amount_native, item.currency || 'USD')}
                    </div>
                    {item.currency !== 'USD' && item.amount_usd != null && (
                      <div className="text-xs font-semibold text-slate-500 dark:text-slate-400 tabular-nums">
                        ≈ {formatMoney(item.amount_usd, 'USD')}
                      </div>
                    )}
                  </div>

                  {/* Review Actions */}
                  {isPending && (
                    <div className="flex items-center gap-2">
                      {userCanReviewThis ? (
                        <>
                          <button
                            type="button"
                            disabled={actionBusy}
                            onClick={() => handleReview(item, 'APPROVE')}
                            className="px-3.5 py-1.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold flex items-center gap-1.5 shadow-sm transition-all disabled:opacity-50"
                          >
                            <Check className="w-3.5 h-3.5 stroke-[2.5]" /> Approve
                          </button>
                          <button
                            type="button"
                            disabled={actionBusy}
                            onClick={() => setRejectModal(item)}
                            className="px-3.5 py-1.5 rounded-xl bg-rose-50 hover:bg-rose-100 dark:bg-rose-950/40 dark:hover:bg-rose-900/40 text-rose-700 dark:text-rose-300 border border-rose-200 dark:border-rose-800 text-xs font-bold flex items-center gap-1.5 transition-all disabled:opacity-50"
                          >
                            <X className="w-3.5 h-3.5 stroke-[2.5]" /> Reject
                          </button>
                        </>
                      ) : (
                        <span className="text-[11px] text-amber-700 dark:text-amber-400 font-semibold flex items-center gap-1 bg-amber-500/10 px-2.5 py-1 rounded-lg border border-amber-500/20">
                          <Clock className="w-3 h-3 text-amber-500" /> Awaiting manager approval
                        </span>
                      )}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="glass-panel p-12 text-center text-slate-500 rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/60 shadow-xs space-y-2">
          <CheckCircle2 className="w-10 h-10 mx-auto text-emerald-500 opacity-80" />
          <h3 className="font-bold text-sm text-slate-900 dark:text-slate-100">No approval requests found</h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 max-w-sm mx-auto">
            {statusFilter === 'PENDING'
              ? 'All pending transfers, pot reallocations, and outgoing expenses have been reviewed.'
              : 'No transfer records match the selected filter criteria.'}
          </p>
        </div>
      )}

      {/* Reject Confirmation Modal */}
      {rejectModal && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-xs animate-fadeIn" onClick={() => setRejectModal(null)} />
          <div className="relative glass-panel max-w-md w-full p-6 rounded-2xl border border-rose-200 dark:border-rose-800/80 bg-white dark:bg-slate-900 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 dark:border-slate-800 pb-3">
              <h3 className="font-bold text-sm text-slate-900 dark:text-slate-100 flex items-center gap-2">
                <XCircle className="w-4 h-4 text-rose-500" /> Reject Transfer Request
              </h3>
              <button
                type="button"
                onClick={() => setRejectModal(null)}
                className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <p className="text-xs text-slate-600 dark:text-slate-300">
              Are you sure you want to reject <strong>{rejectModal.id}</strong>? Funds will not be moved.
            </p>

            <div>
              <label className="block text-[11px] font-semibold text-slate-700 dark:text-slate-300 mb-1">
                Rejection Reason (required)
              </label>
              <textarea
                rows={3}
                required
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
                placeholder="State why this transfer is being rejected…"
                className="w-full p-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/60 text-slate-900 dark:text-slate-100 text-xs focus:ring-1 focus:ring-rose-500 outline-none"
              />
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setRejectModal(null)}
                className="btn-secondary text-xs"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={!rejectReason.trim() || actionBusy}
                onClick={() => handleReview(rejectModal, 'REJECT', rejectReason.trim())}
                className="px-4 py-2 rounded-xl bg-rose-600 hover:bg-rose-500 text-white text-xs font-bold disabled:opacity-40"
              >
                {actionBusy ? 'Rejecting…' : 'Confirm Rejection'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default ApprovalsPanel;
