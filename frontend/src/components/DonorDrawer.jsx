import React, { useEffect, useState } from 'react';
import { X, User, DollarSign, Calendar, MapPin, Tag, CreditCard, ShieldCheck, Mail, Phone, Globe, FileText, Gift, CheckCircle, PieChart, Layers } from 'lucide-react';
import { API_BASE_URL } from '../config';

export default function DonorDrawer({ donorId, onClose, activeCompany }) {
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const resolvedDonorId = typeof donorId === 'object' && donorId !== null 
    ? (donorId.donor_id || donorId.email || donorId.name || '')
    : (donorId || '');

  const fallbackDisplayName = typeof donorId === 'object' && donorId !== null
    ? (donorId.name || donorId.email || donorId.donor_id || 'Donor Profile')
    : (String(donorId || 'Donor Profile'));

  // Pagination State for Transaction History
  const [historyPage, setHistoryPage] = useState(1);
  const [historyPageSize, setHistoryPageSize] = useState(20);
  const [historyRecords, setHistoryRecords] = useState([]);
  const [historyTotalRecords, setHistoryTotalRecords] = useState(0);
  const [historyTotalPages, setHistoryTotalPages] = useState(1);
  const [historyLoading, setHistoryLoading] = useState(false);

  useEffect(() => {
    if (!resolvedDonorId) return;
    setLoading(true);
    setError('');
    setHistoryPage(1);
    const compQuery = activeCompany ? `?company_id=${encodeURIComponent(activeCompany)}` : '';
    fetch(`${API_BASE_URL}/api/donors/profile/${encodeURIComponent(resolvedDonorId)}${compQuery}`)
      .then(res => {
        if (!res.ok) throw new Error('Donor profile not found');
        return res.json();
      })
      .then(data => {
        setProfile(data);
        setHistoryTotalRecords(data.total_donations_count || 0);
        if (data.history) {
          setHistoryRecords(data.history.slice(0, 20));
          setHistoryTotalPages(Math.ceil((data.total_donations_count || 0) / 20) || 1);
        }
        setLoading(false);
      })
      .catch(err => {
        console.error('Error fetching donor profile:', err);
        setError('Unable to load donor profile. Please try again.');
        setLoading(false);
      });
  }, [resolvedDonorId, activeCompany]);

  // Fetch specific history pages for massive donor accounts
  const fetchHistoryPage = (p, ps) => {
    if (!resolvedDonorId) return;
    setHistoryLoading(true);
    const compParam = activeCompany ? `&company_id=${encodeURIComponent(activeCompany)}` : '';
    fetch(`${API_BASE_URL}/api/donors/history?donor_id=${encodeURIComponent(resolvedDonorId)}${compParam}&page=${p}&page_size=${ps}`)
      .then(res => res.json())
      .then(data => {
        setHistoryRecords(data.records || []);
        setHistoryTotalRecords(data.total_records || 0);
        setHistoryTotalPages(data.total_pages || 1);
        setHistoryLoading(false);
      })
      .catch(err => {
        console.error('Error fetching donor history page:', err);
        setHistoryLoading(false);
      });
  };

  const handlePageChange = (newPage) => {
    setHistoryPage(newPage);
    fetchHistoryPage(newPage, historyPageSize);
  };

  const handlePageSizeChange = (newSize) => {
    setHistoryPageSize(newSize);
    setHistoryPage(1);
    fetchHistoryPage(1, newSize);
  };

  useEffect(() => {
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') onClose();
    };

    if (donorId) {
      window.addEventListener('keydown', handleKeyDown);
    }

    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [donorId, onClose]);

  if (!donorId) return null;

  const getTierBadge = (tier) => {
    switch (tier) {
      case 'Super High': return 'badge-pink';
      case 'High': return 'badge-amber';
      case 'Medium': return 'badge-emerald';
      case 'Medium Low': return 'badge-cyan';
      default: return 'badge-slate';
    }
  };

  return (
    <>
      {/* Backdrop */}
      <div className="drawer-backdrop" onClick={onClose} />

      {/* Drawer Panel */}
      <div className="drawer-content p-6 flex flex-col gap-6 w-full max-w-2xl panel-pop" role="dialog" aria-modal="true" aria-label="Donor profile drawer">
        {/* Header */}
        <div className="flex items-center justify-between pb-4" style={{ borderBottom: '1px solid var(--border-glass)' }}>
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-cyan-400/20 to-purple-500/20 border border-cyan-500/30 flex items-center justify-center text-cyan-400 font-extrabold text-lg">
              <User className="w-6 h-6" />
            </div>
            <div>
              <h2 className="text-xl font-extrabold" style={{ color: 'var(--text-main)' }}>{profile?.display_name || fallbackDisplayName}</h2>
              <div className="flex flex-wrap items-center gap-2 mt-1">
                <span className={`badge ${getTierBadge(profile?.lifetime_tier)}`}>Lifetime: {profile?.lifetime_tier}</span>
                <span className={`badge ${getTierBadge(profile?.transaction_tier)}`}>Transaction: {profile?.transaction_tier}</span>
              </div>
            </div>
          </div>

          <button 
            onClick={onClose}
            className="w-8 h-8 rounded-full flex items-center justify-center transition-all"
            style={{ backgroundColor: 'var(--input-bg)', color: 'var(--text-sub)' }}
            aria-label="Close donor drawer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {loading ? (
          <div className="glass-panel p-6 animate-pulse">
            <div className="h-6 w-56 rounded-full bg-slate-700/30 mb-4" />
            <div className="grid grid-cols-3 gap-3">
              <div className="h-24 rounded-xl bg-slate-700/25" />
              <div className="h-24 rounded-xl bg-slate-700/25" />
              <div className="h-24 rounded-xl bg-slate-700/25" />
            </div>
          </div>
        ) : error ? (
          <div className="glass-panel p-5 border border-rose-500/20 text-sm font-semibold text-rose-400">{error}</div>
        ) : (
          <div className="flex flex-col gap-6 overflow-y-auto pr-1">
            {/* Key Metrics Cards */}
            <div className="grid grid-cols-3 gap-3">
              <div className="glass-panel p-3.5 border-l-4 border-cyan-400">
                <div className="text-[10px] font-bold uppercase" style={{ color: 'var(--text-sub)' }}>Total Lifetime Raised</div>
                <div className="text-xl font-black text-cyan-400 mt-1">£{profile?.total_ltv?.toLocaleString(undefined, { minimumFractionDigits: 2 })}</div>
                <div className="text-[10px] mt-0.5" style={{ color: 'var(--text-sub)' }}>{profile?.total_donations_count?.toLocaleString()} total donations</div>
              </div>

              <div className="glass-panel p-3.5 border-l-4 border-purple-400">
                <div className="text-[10px] font-bold uppercase" style={{ color: 'var(--text-sub)' }}>Average Donation</div>
                <div className="text-xl font-black text-purple-400 mt-1">£{profile?.avg_donation?.toLocaleString(undefined, { minimumFractionDigits: 2 })}</div>
                <div className="text-[10px] mt-0.5" style={{ color: 'var(--text-sub)' }}>per transaction</div>
              </div>

              <div className="glass-panel p-3.5 border-l-4 border-emerald-400">
                <div className="text-[10px] font-bold uppercase" style={{ color: 'var(--text-sub)' }}>Payment Frequency</div>
                <div className="text-sm font-black text-emerald-400 mt-1 truncate">{profile?.payment_frequency}</div>
                <div className="text-[10px] mt-0.5" style={{ color: 'var(--text-sub)' }}>{profile?.payment_type}</div>
              </div>
            </div>

            {/* Category & Sub-Heading Breakdown */}
            {profile?.category_breakdown?.length > 0 && (
              <div>
                <h3 className="text-xs font-extrabold text-white mb-3 uppercase tracking-wider flex items-center gap-2">
                  <PieChart className="w-4 h-4 text-purple-400" /> Category Breakdown
                </h3>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                  {profile.category_breakdown.map((cat, idx) => (
                    <div key={idx} className="glass-panel p-3 flex items-center justify-between border-l-2 border-purple-500/50">
                      <div>
                        <div className="text-xs font-bold text-white truncate max-w-[170px]">{cat.subheading}</div>
                        <div className="text-[10px] text-purple-300 font-medium">{cat.heading} • {cat.count} txns</div>
                      </div>
                      <div className="text-right">
                        <div className="text-xs font-extrabold text-cyan-400">£{cat.total_amount?.toLocaleString(undefined, { minimumFractionDigits: 2 })}</div>
                        <div className="text-[10px] text-slate-400 font-bold">{cat.percentage}%</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Compliance, Tax, & Address Details */}
            <div className="glass-panel p-4 flex flex-col gap-3">
              <h3 className="text-xs font-extrabold text-white uppercase tracking-wider flex items-center gap-2 border-b border-white/10 pb-2">
                <ShieldCheck className="w-4 h-4 text-emerald-400" /> Compliance & Tax Declarations
              </h3>

              <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs">
                <div className="flex justify-between py-1 border-b border-white/5">
                  <span className="text-slate-400">Gift Aid Claimed</span>
                  <span className="font-semibold text-slate-200">{profile?.gift_aid}</span>
                </div>
                <div className="flex justify-between py-1 border-b border-white/5">
                  <span className="text-slate-400">Marketing Consent</span>
                  <span className="font-semibold text-slate-200">{profile?.marketing_consent}</span>
                </div>
                <div className="flex justify-between py-1 border-b border-white/5">
                  <span className="text-slate-400">Tax Receipt Requested</span>
                  <span className="font-semibold text-slate-200">{profile?.tax_receipt_requested}</span>
                </div>
                <div className="flex justify-between py-1 border-b border-white/5">
                  <span className="text-slate-400">Visibility Flag</span>
                  <span className="font-semibold text-slate-200">{profile?.anonymous_public}</span>
                </div>
                <div className="flex justify-between py-1 border-b border-white/5">
                  <span className="text-slate-400">Data Source</span>
                  <span className="font-semibold text-cyan-400">{profile?.source}</span>
                </div>
                <div className="flex justify-between py-1 border-b border-white/5">
                  <span className="text-slate-400">Platform</span>
                  <span className="font-semibold text-purple-300">{profile?.platform}</span>
                </div>
              </div>
            </div>

            {/* Complete Transaction History Table with High-Performance Pagination */}
            <div>
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-xs font-extrabold text-white uppercase tracking-wider flex items-center gap-2">
                  <Calendar className="w-4 h-4 text-cyan-400" /> Transaction History ({historyTotalRecords.toLocaleString()})
                </h3>

                <div className="flex items-center gap-2">
                  <span className="text-[10px] text-slate-400 font-bold">Rows:</span>
                  <select
                    value={historyPageSize}
                    onChange={e => handlePageSizeChange(Number(e.target.value))}
                    className="bg-slate-900 border border-white/10 rounded-lg px-2 py-1 text-[11px] text-white focus:outline-none focus:border-cyan-500 cursor-pointer"
                  >
                    <option value={10}>10</option>
                    <option value={20}>20</option>
                    <option value={50}>50</option>
                    <option value={100}>100</option>
                  </select>
                </div>
              </div>

              <div className="glass-panel overflow-hidden border border-white/10 rounded-xl">
                <div className="overflow-x-auto max-h-[320px]">
                  {historyLoading ? (
                    <div className="py-12 text-center text-xs text-slate-400 font-semibold animate-pulse">
                      ⚡ Loading history page...
                    </div>
                  ) : (
                    <table className="crm-table">
                      <thead className="sticky top-0 z-10 bg-slate-900 border-b border-white/10">
                        <tr>
                          <th>Date (UTC)</th>
                          <th>Platform</th>
                          <th>Campaign / Ref</th>
                          <th>Category Heading</th>
                          <th>Sub-Heading</th>
                          <th>Net Settled Amount</th>
                        </tr>
                      </thead>
                      <tbody>
                        {historyRecords.map((txn, i) => {
                          const isPaysuite = (txn['Platform'] || '').toLowerCase() === 'paysuite' || String(txn['Campaign Name'] || '').startsWith('REC-');
                          const platName = txn['Platform'] || (isPaysuite ? 'Paysuite' : 'LaunchGood');
                          return (
                            <tr key={i}>
                              <td className="text-xs text-slate-400 font-mono whitespace-nowrap">{txn['Created Date (UTC)'] ? String(txn['Created Date (UTC)']).split('T')[0] : 'N/A'}</td>
                              <td className="text-xs whitespace-nowrap">
                                <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold ${
                                  isPaysuite ? 'bg-purple-500/20 text-purple-300 border border-purple-500/30' :
                                  platName === 'GiveBright' ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30' :
                                  'bg-cyan-500/20 text-cyan-300 border border-cyan-500/30'
                                }`}>
                                  {platName}
                                </span>
                              </td>
                              <td className="text-xs font-bold text-slate-200 max-w-[200px]" title={txn['Campaign Name']}>
                                {isPaysuite ? (
                                  <div className="flex items-center gap-1.5 truncate">
                                    <span className="font-mono text-purple-200 truncate">{txn['Campaign Name']}</span>
                                    <span className="text-[9px] px-1 py-0.2 rounded bg-purple-950 text-purple-300 border border-purple-500/40 shrink-0 font-sans">
                                      Bank Ref
                                    </span>
                                  </div>
                                ) : (
                                  <div className="truncate">{txn['Campaign Name'] || 'N/A'}</div>
                                )}
                              </td>
                              <td className="text-xs text-cyan-400 font-semibold">{txn['Heading'] || 'Unassigned'}</td>
                              <td className="text-xs text-purple-300">{txn['Sub-Heading'] || 'Unassigned'}</td>
                              <td className="text-xs font-black text-cyan-400">£{txn['Total Online Donations Net Amount in Settled Currency']?.toFixed(2) || '0.00'}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  )}
                </div>

                {/* History Pagination Bar */}
                {historyTotalPages > 1 && (
                  <div className="p-3 border-t border-white/10 flex items-center justify-between text-xs bg-slate-900/60">
                    <button
                      disabled={historyPage <= 1 || historyLoading}
                      onClick={() => handlePageChange(Math.max(1, historyPage - 1))}
                      className="btn-secondary text-xs px-3 py-1 disabled:opacity-40"
                    >
                      Prev
                    </button>
                    <span className="text-xs text-slate-400 font-medium">
                      Page <b className="text-cyan-400">{historyPage}</b> of <b className="text-white">{historyTotalPages}</b>
                    </span>
                    <button
                      disabled={historyPage >= historyTotalPages || historyLoading}
                      onClick={() => handlePageChange(Math.min(historyTotalPages, historyPage + 1))}
                      className="btn-secondary text-xs px-3 py-1 disabled:opacity-40"
                    >
                      Next
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
