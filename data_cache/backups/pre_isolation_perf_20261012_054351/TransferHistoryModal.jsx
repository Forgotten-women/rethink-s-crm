import React, { useState, useEffect } from 'react';
import { History, Search, Download, Trash2, X, RefreshCw, AlertTriangle, CheckCircle2, ArrowRight, FileSpreadsheet, ArrowRightLeft } from 'lucide-react';
import { API_BASE_URL } from '../config';

export default function TransferHistoryModal({
  isOpen,
  onClose,
  user,
  isSuperAdmin,
  onTransfersUpdated,
  filterCode = '',
  activeCompany = 'rethink'
}) {
  const [transfers, setTransfers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [totalCount, setTotalCount] = useState(0);
  const [totalAmount, setTotalAmount] = useState(0);
  const [actionMsg, setActionMsg] = useState('');
  const [voidingId, setVoidingId] = useState(null);
  const [confirmVoidId, setConfirmVoidId] = useState(null);

  const fetchTransfers = () => {
    setLoading(true);
    const codeParam = filterCode ? `&code=${encodeURIComponent(filterCode)}` : '';
    const searchParam = search ? `&search=${encodeURIComponent(search)}` : '';
    fetch(`${API_BASE_URL}/api/expenses/transfers?limit=500${codeParam}${searchParam}&company_id=${encodeURIComponent(activeCompany)}`)
      .then(r => r.json())
      .then(res => {
        setTransfers(res.transfers || []);
        setTotalCount(res.total_count || 0);
        setTotalAmount(res.total_amount || 0);
        setLoading(false);
      })
      .catch(err => {
        console.error('Error fetching transfers:', err);
        setLoading(false);
      });
  };

  useEffect(() => {
    if (isOpen) {
      fetchTransfers();
      setActionMsg('');
      setConfirmVoidId(null);
    }
  }, [isOpen, filterCode]);

  useEffect(() => {
    if (isOpen) {
      const timer = setTimeout(() => {
        fetchTransfers();
      }, 300);
      return () => clearTimeout(timer);
    }
  }, [search]);

  if (!isOpen) return null;

  const handleVoidTransfer = (transferId) => {
    setVoidingId(transferId);
    setActionMsg('');

    fetch(`${API_BASE_URL}/api/expenses/transfers/${transferId}?user_role=${user?.role || 'super_admin'}&can_edit_donors=${user?.can_edit_donors === 1}&company_id=${encodeURIComponent(activeCompany)}`, {
      method: 'DELETE'
    })
      .then(r => r.json())
      .then(res => {
        setVoidingId(null);
        setConfirmVoidId(null);
        if (res.status === 'success') {
          setActionMsg(`✅ ${res.message}`);
          fetchTransfers();
          if (onTransfersUpdated) onTransfersUpdated();
          setTimeout(() => setActionMsg(''), 4000);
        } else {
          setActionMsg(`❌ ${res.detail || 'Failed to void transfer.'}`);
        }
      })
      .catch(err => {
        setVoidingId(null);
        setConfirmVoidId(null);
        setActionMsg(`❌ Error: ${err.message}`);
      });
  };

  const handleExport = (format = 'csv') => {
    const codeParam = filterCode ? `&code=${encodeURIComponent(filterCode)}` : '';
    window.open(`${API_BASE_URL}/api/expenses/transfers/export?format=${format}${codeParam}&company_id=${encodeURIComponent(activeCompany)}`, '_blank');
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-fadeIn">
      <div 
        className="w-full max-w-5xl rounded-2xl shadow-2xl border flex flex-col max-h-[92vh] overflow-hidden"
        style={{
          backgroundColor: 'var(--bg-card)',
          borderColor: 'var(--border-glass)',
          color: 'var(--text-main)'
        }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b bg-gradient-to-r from-purple-500/10 via-cyan-500/10 to-transparent" style={{ borderColor: 'var(--border-glass)' }}>
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-xl bg-purple-500/20 text-purple-400 border border-purple-500/30">
              <History className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-base font-black flex items-center gap-2" style={{ color: 'var(--text-main)' }}>
                Internal Fund Transfers Audit Ledger
                {filterCode && <span className="text-xs px-2 py-0.5 rounded-full bg-cyan-500/20 text-cyan-400 font-mono">Filtered: {filterCode}</span>}
              </h3>
              <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
                Comprehensive ledger of all fund transfers between project codes.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1.5">
              <button
                onClick={() => handleExport('csv')}
                className="btn-secondary text-xs px-2.5 py-1.5 flex items-center gap-1"
                title="Export to CSV"
              >
                <Download className="w-3.5 h-3.5" /> CSV
              </button>
              <button
                onClick={() => handleExport('xlsx')}
                className="btn-secondary text-xs px-2.5 py-1.5 flex items-center gap-1 text-emerald-400"
                title="Export to Excel"
              >
                <FileSpreadsheet className="w-3.5 h-3.5" /> Excel
              </button>
            </div>

            <button 
              onClick={onClose}
              className="p-1.5 rounded-lg hover:bg-white/10 transition-colors ml-2"
              style={{ color: 'var(--text-sub)' }}
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Toolbar & KPI Summary */}
        <div className="p-5 border-b flex flex-wrap items-center justify-between gap-4" style={{ borderColor: 'var(--border-glass)', backgroundColor: 'var(--bg-card-inner)' }}>
          {/* Summary Stats */}
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <span className="text-xs font-bold" style={{ color: 'var(--text-muted)' }}>Total Transfers:</span>
              <span className="text-sm font-black text-white">{totalCount}</span>
            </div>
            <span className="text-slate-600">|</span>
            <div className="flex items-center gap-2">
              <span className="text-xs font-bold" style={{ color: 'var(--text-muted)' }}>Total Amount Reallocated:</span>
              <span className="text-sm font-black text-purple-400">£{totalAmount.toLocaleString(undefined, { minimumFractionDigits: 2 })}</span>
            </div>
          </div>

          {/* Search Input */}
          <div className="relative flex items-center">
            <Search className="w-3.5 h-3.5 absolute left-3" style={{ color: 'var(--text-sub)' }} />
            <input
              type="text"
              placeholder="Search code, reason, ID, author..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="pl-8 pr-3 py-1.5 rounded-xl text-xs font-medium w-72 focus:outline-none"
              style={{
                backgroundColor: 'var(--input-bg)',
                color: 'var(--input-text)',
                border: '1px solid var(--input-border)'
              }}
            />
            {search && (
              <button onClick={() => setSearch('')} className="absolute right-2.5 text-xs text-slate-400 hover:text-white">✕</button>
            )}
          </div>
        </div>

        {/* Status Notification */}
        {actionMsg && (
          <div className="mx-6 mt-4 p-3 rounded-xl border text-xs font-bold" style={{
            backgroundColor: actionMsg.startsWith('✅') ? 'rgba(16, 185, 129, 0.1)' : 'rgba(244, 63, 94, 0.1)',
            borderColor: actionMsg.startsWith('✅') ? 'rgba(16, 185, 129, 0.3)' : 'rgba(244, 63, 94, 0.3)',
            color: actionMsg.startsWith('✅') ? '#34D399' : '#FB7185'
          }}>
            {actionMsg}
          </div>
        )}

        {/* Table Content */}
        <div className="p-6 overflow-y-auto flex-1">
          {loading ? (
            <div className="py-12 flex flex-col items-center justify-center gap-3" style={{ color: 'var(--text-muted)' }}>
              <RefreshCw className="w-6 h-6 animate-spin text-purple-400" />
              <span className="text-xs font-semibold">Loading transfer audit ledger...</span>
            </div>
          ) : transfers.length === 0 ? (
            <div className="py-12 text-center rounded-xl border p-8 flex flex-col items-center gap-2" style={{ backgroundColor: 'var(--bg-card-inner)', borderColor: 'var(--border-glass)', color: 'var(--text-muted)' }}>
              <ArrowRightLeft className="w-8 h-8 text-purple-400/50" />
              <span className="text-sm font-bold text-slate-300">No Fund Transfers Found</span>
              <span className="text-xs">No internal balance reallocations match your current filters.</span>
            </div>
          ) : (
            <div className="overflow-x-auto rounded-xl border shadow-sm" style={{ borderColor: 'var(--border-glass)' }}>
              <table className="crm-table w-full">
                <thead>
                  <tr>
                    <th>Transfer ID</th>
                    <th>Date</th>
                    <th>Source (From)</th>
                    <th className="text-center">Flow</th>
                    <th>Destination (To)</th>
                    <th>Amount (£)</th>
                    <th>Reason / Notes</th>
                    <th>Transferred By</th>
                    {isSuperAdmin && <th>Actions</th>}
                  </tr>
                </thead>
                <tbody>
                  {transfers.map(trf => (
                    <tr key={trf.id} className="hover:bg-purple-500/5 transition-colors">
                      <td className="font-mono text-xs font-bold text-cyan-400">{trf.id}</td>
                      <td className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>
                        {trf.transfer_date || trf.created_at?.split('T')[0] || 'N/A'}
                      </td>
                      <td>
                        <span className="font-mono text-xs font-black px-2 py-0.5 rounded-md bg-rose-500/15 text-rose-400 border border-rose-500/30">
                          {trf.source_code}
                        </span>
                      </td>
                      <td className="text-center">
                        <ArrowRight className="w-4 h-4 text-purple-400 mx-auto" />
                      </td>
                      <td>
                        <span className="font-mono text-xs font-black px-2 py-0.5 rounded-md bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                          {trf.destination_code}
                        </span>
                      </td>
                      <td className="text-xs font-extrabold text-white">
                        £{trf.amount?.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                      </td>
                      <td className="text-xs max-w-xs truncate" title={trf.reason} style={{ color: 'var(--text-main)' }}>
                        {trf.reason}
                      </td>
                      <td className="text-xs" style={{ color: 'var(--text-muted)' }}>
                        {trf.transferred_by || 'Super Admin'}
                      </td>
                      {isSuperAdmin && (
                        <td>
                          {confirmVoidId === trf.id ? (
                            <div className="flex items-center gap-1.5 animate-fadeIn">
                              <button
                                onClick={() => handleVoidTransfer(trf.id)}
                                disabled={voidingId === trf.id}
                                className="px-2 py-1 rounded bg-rose-600 text-white font-bold text-[10px] hover:bg-rose-500"
                              >
                                {voidingId === trf.id ? 'Voiding...' : 'Confirm Void'}
                              </button>
                              <button
                                onClick={() => setConfirmVoidId(null)}
                                className="px-2 py-1 rounded bg-slate-700 text-slate-300 text-[10px] hover:bg-slate-600"
                              >
                                Cancel
                              </button>
                            </div>
                          ) : (
                            <button
                              onClick={() => setConfirmVoidId(trf.id)}
                              className="p-1.5 rounded bg-slate-800 text-slate-400 hover:bg-rose-500/20 hover:text-rose-400 transition-colors"
                              title="Void / Rollback Transfer"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          )}
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-between items-center px-6 py-4 border-t" style={{ borderColor: 'var(--border-glass)', backgroundColor: 'var(--bg-card-inner)' }}>
          <div className="text-xs" style={{ color: 'var(--text-muted)' }}>
            Showing {transfers.length} records. Transfers directly adjust available balances without modifying donation codes.
          </div>
          <button onClick={onClose} className="btn-secondary text-xs px-4 py-2">
            Close Ledger
          </button>
        </div>
      </div>
    </div>
  );
}
