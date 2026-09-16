import React, { useEffect, useState } from 'react';
import { CreditCard, PlusCircle, Check, X, Mail, Filter, Wallet, Search, ChevronLeft, ChevronRight, LayoutGrid, List, Trash2, AlertTriangle, Settings, Eye, EyeOff, SendHorizonal, ChevronDown, ChevronUp, ShieldCheck, Wifi, WifiOff, RefreshCw, Download, FileSpreadsheet, ArrowRightLeft, History } from 'lucide-react';
import { API_BASE_URL } from '../config';
import TransferFundsModal from './TransferFundsModal';
import TransferHistoryModal from './TransferHistoryModal';

export default function ExpenseView({ user, activeCompany = 'rethink', companies = [] }) {
  const isConsolidated = activeCompany === 'all';
  const formatDate = (val) => {
    if (!val) return 'N/A';
    try {
      const d = new Date(val);
      if (isNaN(d.getTime())) return val;
      return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
    } catch (e) {
      return val;
    }
  };

  const getStatusBadge = (status) => {
    switch (status) {
      case 'APPROVED':
        return <span className="badge badge-emerald text-[10px] font-bold">APPROVED</span>;
      case 'REJECTED':
        return <span className="badge badge-rose text-[10px] font-bold">REJECTED</span>;
      case 'PENDING_APPROVAL':
        return <span className="badge badge-amber text-[10px] font-bold animate-pulse">PENDING APPROVAL</span>;
      default:
        return <span className="badge badge-secondary text-[10px] font-bold">{status}</span>;
    }
  };

  const [codes, setCodes] = useState([]);
  const [codesLoading, setCodesLoading] = useState(true);
  const [expensesData, setExpensesData] = useState({ summary: {}, expenses: [] });
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState('ALL');
  const [showSubmitModal, setShowSubmitModal] = useState(false);

  // Search & Pagination State for Code Balances
  const [codeSearch, setCodeSearch] = useState('');
  const [selectedCodeDetail, setSelectedCodeDetail] = useState(null);
  const [codePage, setCodePage] = useState(1);
  const [codePageSize, setCodePageSize] = useState(6);

  // Transfer Funds State (Super Admin)
  const [showTransferModal, setShowTransferModal] = useState(false);
  const [transferInitialSource, setTransferInitialSource] = useState('');
  const [showTransferHistoryModal, setShowTransferHistoryModal] = useState(false);
  const [historyFilterCode, setHistoryFilterCode] = useState('');

  // Form State
  const [selectedCode, setSelectedCode] = useState('');
  const [heading, setHeading] = useState('');
  const [subHeading, setSubHeading] = useState('');
  const [country, setCountry] = useState('');
  const [title, setTitle] = useState('');
  const [vendor, setVendor] = useState('');
  const [amount, setAmount] = useState('');
  const [paymentDate, setPaymentDate] = useState(new Date().toISOString().split('T')[0]);
  const [notes, setNotes] = useState('');
  const [isZakat, setIsZakat] = useState(false);

  const [formMsg, setFormMsg] = useState('');
  const [reviewMsg, setReviewMsg] = useState('');
  const [submitting, setSubmitting] = useState(false);

  // Delete confirmation state
  const [deleteConfirm, setDeleteConfirm] = useState(null);
  const [deleting, setDeleting] = useState(false);

  // SMTP / Email Settings State (Super Admin only)
  const [showSettings, setShowSettings] = useState(false);
  const [smtpSettings, setSmtpSettings] = useState({
    approval_email: '',
    smtp_host: 'smtp.gmail.com',
    smtp_port: 587,
    smtp_user: '',
    smtp_password: '',
    smtp_from_name: 'Rethink Charity CRM',
    smtp_from_email: '',
  });
  const [smtpPasswordSet, setSmtpPasswordSet] = useState(false);
  const [smtpConfigured, setSmtpConfigured] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [settingsMsg, setSettingsMsg] = useState('');
  const [savingSettings, setSavingSettings] = useState(false);
  const [testingEmail, setTestingEmail] = useState(false);

  const isSuperAdmin = user?.role === 'super_admin' || user?.can_edit_donors === 1;

  const loadSettings = () => {
    fetch(`${API_BASE_URL}/api/expenses/settings`)
      .then(r => r.json())
      .then(data => {
        setSmtpSettings({
          approval_email: data.approval_email || '',
          smtp_host: data.smtp_host || 'smtp.gmail.com',
          smtp_port: data.smtp_port || 587,
          smtp_user: data.smtp_user || '',
          smtp_password: '',  // never pre-fill password
          smtp_from_name: data.smtp_from_name || 'Rethink Charity CRM',
          smtp_from_email: data.smtp_from_email || '',
        });
        setSmtpPasswordSet(data.smtp_password_set || false);
        setSmtpConfigured(data.smtp_configured || false);
      })
      .catch(() => {});
  };

  const handleSaveSettings = (e) => {
    e.preventDefault();
    setSavingSettings(true);
    setSettingsMsg('');
    fetch(`${API_BASE_URL}/api/expenses/settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...smtpSettings, user_role: user?.role })
    })
      .then(r => r.json())
      .then(res => {
        setSavingSettings(false);
        if (res?.status === 'success') {
          setSettingsMsg('✅ ' + res.message);
          loadSettings();
          setTimeout(() => setSettingsMsg(''), 4000);
        } else {
          setSettingsMsg('❌ ' + (res?.detail || 'Failed to save settings.'));
        }
      })
      .catch(err => { setSavingSettings(false); setSettingsMsg('❌ ' + err.message); });
  };

  const handleTestEmail = () => {
    setTestingEmail(true);
    setSettingsMsg('');
    fetch(`${API_BASE_URL}/api/expenses/test-email`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_role: user?.role, can_edit_donors: true })
    })
      .then(r => r.json())
      .then(res => {
        setTestingEmail(false);
        if (res?.status === 'success') {
          setSettingsMsg('✅ ' + res.message);
        } else {
          setSettingsMsg('❌ ' + (res?.detail || 'Test email failed.'));
        }
        setTimeout(() => setSettingsMsg(''), 6000);
      })
      .catch(err => { setTestingEmail(false); setSettingsMsg('❌ ' + err.message); });
  };

  const loadCodes = (force = false) => {
    setCodesLoading(true);
    fetch(`${API_BASE_URL}/api/expenses/codes?company_id=${encodeURIComponent(activeCompany)}${force ? '&force_reload=true' : ''}`)
      .then(res => res.json())
      .then(data => { setCodes(Array.isArray(data) ? data : []); setCodesLoading(false); })
      .catch(err => { console.error('Error fetching project codes:', err); setCodesLoading(false); });
  };

  const loadExpenses = () => {
    setLoading(true);
    fetch(`${API_BASE_URL}/api/expenses/requests?status_filter=${statusFilter}&company_id=${encodeURIComponent(activeCompany)}`)
      .then(res => res.json())
      .then(data => {
        setExpensesData(data);
        setLoading(false);
      })
      .catch(err => {
        console.error('Error fetching expense requests:', err);
        setLoading(false);
      });
  };

  useEffect(() => {
    loadCodes(false);  // Use cache on mount for fast initial paint — force_reload on refresh/events
    loadExpenses();
    if (isSuperAdmin) loadSettings();

    // WebSocket real-time events listener with HTTP polling fallback for Vercel Serverless
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsHost = API_BASE_URL
      ? API_BASE_URL.replace(/^https?:\/\//, '')
      : window.location.host;
    const wsUrl = `${wsProtocol}//${wsHost}/ws/events`;

    let socket = null;
    let fallbackInterval = null;

    const startPollingFallback = () => {
      if (!fallbackInterval) {
        fallbackInterval = setInterval(() => {
          loadExpenses();
          loadCodes(true);
        }, 15000);
      }
    };

    try {
      socket = new WebSocket(wsUrl);
      socket.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          if ([
            'EXPENSE_SUBMITTED', 'EXPENSE_REVIEWED', 'EXPENSE_DELETED',
            'DONORS_UPDATED', 'DONOR_RECORD_UPDATED', 'BULK_DONORS_UPDATED',
            'MATRIX_UPDATED', 'PAYOUTS_UPDATED', 'BALANCE_TRANSFERRED'
          ].includes(payload?.event)) {
            loadExpenses();
            loadCodes(true);
          }
        } catch (e) {}
      };
      socket.onerror = () => {
        startPollingFallback();
      };
      socket.onclose = () => {
        startPollingFallback();
      };
    } catch (e) {
      startPollingFallback();
    }

    const handleFocus = () => {
      loadCodes(true);
      loadExpenses();
    };
    window.addEventListener('focus', handleFocus);

    return () => {
      if (socket) {
        socket.onclose = null;
        socket.onerror = null;
        try { socket.close(); } catch (e) {}
      }
      if (fallbackInterval) clearInterval(fallbackInterval);
      window.removeEventListener('focus', handleFocus);
    };
  }, [statusFilter, activeCompany]);

  // Handle Code Selection & Auto-Fill Heading, Sub-Heading, Country
  const handleCodeSelect = (e) => {
    const codeVal = e.target.value;
    setSelectedCode(codeVal);
    const matched = codes.find(c => c.code === codeVal);
    if (matched) {
      setHeading(matched.heading || 'Unassigned');
      setSubHeading(matched.sub_heading || 'Unassigned');
      setCountry(matched.country || 'Unassigned');
    } else {
      setHeading('');
      setSubHeading('');
      setCountry('');
    }
  };

  // Submit Expense Request
  const matchedSelected = codes.find(c => c.code === selectedCode);
  const previewGlCode = matchedSelected 
    ? (isZakat 
        ? (matchedSelected.legacy_zakat_code || matchedSelected.legacy_non_zakat_code || '') 
        : (matchedSelected.legacy_non_zakat_code || matchedSelected.legacy_zakat_code || ''))
    : '';

  const handleSubmitExpense = (e) => {
    e.preventDefault();
    if (isConsolidated) {
      setFormMsg('❌ Submitting expenses is disabled in Consolidated (All Companies) mode. Please switch to a specific company.');
      return;
    }
    if (!selectedCode || !amount || !title) {
      setFormMsg('❌ Please fill in all required fields (Code, Title, Amount).');
      return;
    }
    setSubmitting(true);
    setFormMsg('');

    fetch(`${API_BASE_URL}/api/expenses/submit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        company_id: activeCompany,
        code: selectedCode,
        title: title,
        vendor: vendor || 'Unassigned Vendor',
        amount: parseFloat(amount),
        payment_date: paymentDate,
        notes: notes,
        is_zakat: isZakat,
        gl_code: previewGlCode,
        requested_by: user?.email || user?.display_name || 'Admin User'
      })
    })
      .then(r => {
        if (r.status === 409) {
          return r.json().then(data => {
            setSubmitting(false);
            setFormMsg(`⚠️ ${data.detail || 'Duplicate expense detected. Please wait or modify the details.'}`);
            return null;
          });
        }
        return r.json();
      })
      .then(res => {
        if (!res) return;
        setSubmitting(false);
        if (res?.status === 'success') {
          let msg = `✅ ${res.message}`;
          if (res.email_warning) {
            msg += ` ⚠️ ${res.email_warning}`;
          }
          setFormMsg(msg);
          setTimeout(() => {
            setShowSubmitModal(false);
            setFormMsg('');
            setSelectedCode('');
            setIsZakat(false);
            setHeading('');
            setSubHeading('');
            setCountry('');
            setTitle('');
            setVendor('');
            setAmount('');
            setNotes('');
            loadExpenses();
            loadCodes();
          }, 2000);
        } else {
          setFormMsg(`❌ ${res?.detail || 'Failed to submit expense.'}`);
        }
      })
      .catch(err => {
        setSubmitting(false);
        setFormMsg(`❌ Error: ${err.message}`);
      });
  };

  // Review Expense (Approve / Reject)
  const handleReview = (expenseId, action) => {
    if (!isSuperAdmin) return;
    setReviewMsg('');

    fetch(`${API_BASE_URL}/api/expenses/review`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        expense_id: expenseId,
        user_role: user?.role,
        action: action,
        can_edit_donors: true,
        review_notes: `Reviewed via CRM Dashboard by ${user?.email}`
      })
    })
      .then(r => r.json())
      .then(res => {
        if (res?.status === 'success') {
          setReviewMsg(`✅ ${res.message}`);
          loadExpenses();
          loadCodes();
          setTimeout(() => setReviewMsg(''), 3000);
        } else {
          setReviewMsg(`❌ ${res?.detail || 'Review failed.'}`);
        }
      });
  };

  // Delete Expense
  const handleDelete = (expenseId) => {
    if (!isSuperAdmin) return;
    setDeleting(true);

    fetch(`${API_BASE_URL}/api/expenses/delete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        expense_id: expenseId,
        user_role: user?.role,
        can_edit_donors: true
      })
    })
      .then(r => r.json())
      .then(res => {
        setDeleting(false);
        setDeleteConfirm(null);
        if (res?.status === 'success') {
          setReviewMsg(`🗑️ ${res.message}`);
          loadExpenses();
          loadCodes();
          setTimeout(() => setReviewMsg(''), 4000);
        } else {
          setReviewMsg(`❌ ${res?.detail || 'Delete failed.'}`);
        }
      })
      .catch(err => {
        setDeleting(false);
        setDeleteConfirm(null);
        setReviewMsg(`❌ Error: ${err.message}`);
      });
  };

  // Filter & Paginate Code Balances
  const filteredCodes = codes.filter(c => {
    if (!codeSearch) return true;
    const term = codeSearch.toLowerCase();
    const code = (c.code || '').toLowerCase();
    const heading = (c.heading || '').toLowerCase();
    const sub_heading = (c.sub_heading || '').toLowerCase();
    const country = (c.country || '').toLowerCase();
    return (
      code.includes(term) ||
      heading.includes(term) ||
      sub_heading.includes(term) ||
      country.includes(term)
    );
  });

  const totalCodePages = Math.ceil(filteredCodes.length / codePageSize) || 1;
  const paginatedCodes = filteredCodes.slice((codePage - 1) * codePageSize, codePage * codePageSize);

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h2 className="text-xl font-extrabold flex items-center gap-2" style={{ color: 'var(--text-main)' }}>
            <CreditCard className="w-5 h-5 text-cyan-400" /> Category Expense & Payment Tracker
          </h2>
          <p className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>Approved expenses automatically deduct from total category/code donations in real time (singleton state).</p>
        </div>

        <div className="flex items-center gap-2.5 flex-wrap">
          <button 
            onClick={() => { loadCodes(true); loadExpenses(); }}
            className="btn-secondary text-xs flex items-center gap-1.5"
            title="Refresh live project codes and fund balances"
          >
            <RefreshCw className="w-3.5 h-3.5" /> Refresh Balances
          </button>
          
          <button
            onClick={() => { setHistoryFilterCode(''); setShowTransferHistoryModal(true); }}
            className="btn-secondary text-xs flex items-center gap-1.5 border-purple-500/30 text-purple-300 hover:bg-purple-500/10"
            title="View internal fund transfer audit history"
          >
            <History className="w-3.5 h-3.5 text-purple-400" /> Transfer History
          </button>

          {isSuperAdmin && (
            <button
              onClick={() => { 
                if (isConsolidated) {
                  alert('Transferring funds is disabled in Consolidated (All Companies) mode. Please select a specific company.');
                  return;
                }
                setTransferInitialSource(''); 
                setShowTransferModal(true); 
                loadCodes(true); 
              }}
              disabled={isConsolidated}
              className={`btn-primary text-xs flex items-center gap-1.5 shadow-lg ${
                isConsolidated ? 'opacity-60 cursor-not-allowed bg-slate-600' : 'shadow-purple-500/20'
              }`}
              style={isConsolidated ? {} : { background: 'linear-gradient(135deg, #8B5CF6, #06B6D4)' }}
              title={isConsolidated ? "Transfers disabled in consolidated mode" : "Transfer funds between project codes"}
            >
              <ArrowRightLeft className="w-3.5 h-3.5" /> Transfer Funds
            </button>
          )}

          <button 
            onClick={() => { 
              if (isConsolidated) {
                alert('Submitting expenses is disabled in Consolidated (All Companies) mode. Please select a specific company.');
                return;
              }
              setShowSubmitModal(true); 
              loadCodes(true); 
            }}
            disabled={isConsolidated}
            className={`btn-primary text-xs flex items-center gap-1.5 shadow-lg ${
              isConsolidated ? 'opacity-60 cursor-not-allowed bg-slate-600' : 'shadow-cyan-500/20'
            }`}
            title={isConsolidated ? "Submissions disabled in consolidated mode" : "Submit Expense Request"}
          >
            <PlusCircle className="w-4 h-4" /> Submit Expense Request
          </button>
        </div>
      </div>

      {isConsolidated && (
        <div className="flex items-center gap-3 p-3.5 rounded-2xl bg-amber-500/10 border border-amber-500/30 text-amber-900 dark:text-amber-200 animate-fadeIn">
          <AlertTriangle className="w-5 h-5 text-amber-500 shrink-0" />
          <div className="text-xs">
            <span className="font-bold">Consolidated Mode (All Companies):</span> Showing aggregated expenses and fund balances across all organizations. Expense claims and fund transfers can only be submitted when a specific company is selected.
          </div>
        </div>
      )}

      {reviewMsg && <div className="text-xs font-bold text-emerald-400 bg-emerald-500/10 p-3 rounded-lg border border-emerald-500/20">{reviewMsg}</div>}

      {/* ── Super Admin: Email & SMTP Settings Panel ───────────────── */}
      {isSuperAdmin && (
        <div className="glass-panel border-l-4 border-amber-400 overflow-hidden">
          {/* Collapsible Header */}
          <button
            onClick={() => setShowSettings(s => !s)}
            className="w-full flex items-center justify-between p-4 transition-colors hover:bg-amber-500/5"
          >
            <div className="flex items-center gap-3">
              <div className="p-1.5 rounded-lg bg-amber-500/15">
                <Settings className="w-4 h-4 text-amber-400" />
              </div>
              <div className="text-left">
                <div className="text-sm font-bold flex items-center gap-2" style={{ color: 'var(--text-main)' }}>
                  Email &amp; SMTP Settings
                  <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-black border ${
                    smtpConfigured
                      ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
                      : 'bg-rose-500/15 text-rose-400 border-rose-500/30'
                  }`}>
                    {smtpConfigured ? <><Wifi className="w-2.5 h-2.5" /> SMTP LIVE</> : <><WifiOff className="w-2.5 h-2.5" /> NOT CONFIGURED</>}
                  </span>
                </div>
                <div className="text-[11px]" style={{ color: 'var(--text-muted)' }}>Configure SMTP server for approval email delivery</div>
              </div>
            </div>
            {showSettings ? <ChevronUp className="w-4 h-4" style={{ color: 'var(--text-muted)' }} /> : <ChevronDown className="w-4 h-4" style={{ color: 'var(--text-muted)' }} />}
          </button>

          {/* Expanded Settings Form */}
          {showSettings && (
            <div className="p-5 pt-0 border-t" style={{ borderColor: 'var(--border-glass)' }}>
              {settingsMsg && (
                <div className={`mt-4 mb-3 text-xs font-bold p-3 rounded-lg border ${
                  settingsMsg.startsWith('✅') ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30' : 'text-rose-400 bg-rose-500/10 border-rose-500/30'
                }`}>
                  {settingsMsg}
                </div>
              )}

              <form onSubmit={handleSaveSettings} className="flex flex-col gap-4 mt-4">
                {/* Row 1: Approval Recipient */}
                <div>
                  <label className="block text-xs font-bold mb-1" style={{ color: 'var(--text-main)' }}>
                    <Mail className="w-3.5 h-3.5 inline mr-1 text-amber-400" />Approval Email Recipient *
                  </label>
                  <input
                    type="email" required
                    placeholder="office@rethinkcharity.org.uk"
                    value={smtpSettings.approval_email}
                    onChange={e => setSmtpSettings(s => ({ ...s, approval_email: e.target.value }))}
                    className="w-full rounded-lg px-3 py-2 text-xs focus:outline-none"
                    style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' }}
                  />
                  <p className="text-[10px] mt-1" style={{ color: 'var(--text-sub)' }}>Email address that receives expense approval notifications</p>
                </div>

                <div className="border-t pt-4" style={{ borderColor: 'var(--border-glass)' }}>
                  <div className="text-xs font-bold uppercase tracking-wider mb-3 flex items-center gap-1.5" style={{ color: 'var(--text-muted)' }}>
                    <ShieldCheck className="w-3.5 h-3.5 text-amber-400" /> SMTP Server Configuration
                  </div>

                  {/* SMTP Host + Port */}
                  <div className="grid grid-cols-3 gap-3 mb-3">
                    <div className="col-span-2">
                      <label className="block text-xs font-bold mb-1" style={{ color: 'var(--text-main)' }}>SMTP Host</label>
                      <input
                        type="text" required
                        placeholder="smtp.gmail.com"
                        value={smtpSettings.smtp_host}
                        onChange={e => setSmtpSettings(s => ({ ...s, smtp_host: e.target.value }))}
                        className="w-full rounded-lg px-3 py-2 text-xs font-mono focus:outline-none"
                        style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' }}
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-bold mb-1" style={{ color: 'var(--text-main)' }}>Port</label>
                      <input
                        type="number" required min="1" max="65535"
                        value={smtpSettings.smtp_port}
                        onChange={e => setSmtpSettings(s => ({ ...s, smtp_port: parseInt(e.target.value) || 587 }))}
                        className="w-full rounded-lg px-3 py-2 text-xs font-mono focus:outline-none"
                        style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' }}
                      />
                    </div>
                  </div>

                  {/* SMTP User + Password */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-3">
                    <div>
                      <label className="block text-xs font-bold mb-1" style={{ color: 'var(--text-main)' }}>SMTP Username / Email</label>
                      <input
                        type="email"
                        placeholder="your@gmail.com"
                        value={smtpSettings.smtp_user}
                        onChange={e => setSmtpSettings(s => ({ ...s, smtp_user: e.target.value }))}
                        className="w-full rounded-lg px-3 py-2 text-xs focus:outline-none"
                        style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' }}
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-bold mb-1" style={{ color: 'var(--text-main)' }}>
                        SMTP Password / App Password
                        {smtpPasswordSet && <span className="ml-2 text-emerald-400 font-bold">● saved</span>}
                      </label>
                      <div className="relative">
                        <input
                          type={showPassword ? 'text' : 'password'}
                          placeholder={smtpPasswordSet ? '••••••••• (leave blank to keep)' : 'Enter App Password'}
                          value={smtpSettings.smtp_password}
                          onChange={e => setSmtpSettings(s => ({ ...s, smtp_password: e.target.value }))}
                          className="w-full rounded-lg px-3 pr-8 py-2 text-xs focus:outline-none"
                          style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' }}
                        />
                        <button
                          type="button"
                          onClick={() => setShowPassword(v => !v)}
                          className="absolute right-2.5 top-1/2 -translate-y-1/2"
                          style={{ color: 'var(--text-sub)' }}
                        >
                          {showPassword ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                        </button>
                      </div>
                      <p className="text-[10px] mt-1" style={{ color: 'var(--text-sub)' }}>
                        Gmail: generate at <a href="https://myaccount.google.com/apppasswords" target="_blank" rel="noreferrer" className="text-cyan-400 underline">myaccount.google.com/apppasswords</a>
                      </p>
                    </div>
                  </div>

                  {/* Sender Name + From Email */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div>
                      <label className="block text-xs font-bold mb-1" style={{ color: 'var(--text-main)' }}>Sender Display Name</label>
                      <input
                        type="text"
                        placeholder="Rethink Charity CRM"
                        value={smtpSettings.smtp_from_name}
                        onChange={e => setSmtpSettings(s => ({ ...s, smtp_from_name: e.target.value }))}
                        className="w-full rounded-lg px-3 py-2 text-xs focus:outline-none"
                        style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' }}
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-bold mb-1" style={{ color: 'var(--text-main)' }}>From Email Address</label>
                      <input
                        type="email"
                        placeholder="Same as SMTP user if left blank"
                        value={smtpSettings.smtp_from_email}
                        onChange={e => setSmtpSettings(s => ({ ...s, smtp_from_email: e.target.value }))}
                        className="w-full rounded-lg px-3 py-2 text-xs focus:outline-none"
                        style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' }}
                      />
                    </div>
                  </div>
                </div>

                {/* Action Buttons */}
                <div className="flex items-center justify-between gap-3 pt-2 border-t" style={{ borderColor: 'var(--border-glass)' }}>
                  <button
                    type="button"
                    onClick={handleTestEmail}
                    disabled={testingEmail || !smtpConfigured}
                    title={!smtpConfigured ? 'Save SMTP credentials first to enable test' : 'Send a test email to the approval recipient'}
                    className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-bold border transition-all disabled:opacity-40"
                    style={{
                      color: smtpConfigured ? 'var(--accent-cyan)' : 'var(--text-sub)',
                      borderColor: smtpConfigured ? 'var(--accent-cyan)' : 'var(--border-glass)',
                      backgroundColor: 'transparent'
                    }}
                  >
                    <SendHorizonal className="w-3.5 h-3.5" />
                    {testingEmail ? 'Sending...' : 'Send Test Email'}
                  </button>

                  <button
                    type="submit"
                    disabled={savingSettings}
                    className="btn-primary text-xs flex items-center gap-1.5"
                  >
                    <Settings className="w-3.5 h-3.5" />
                    {savingSettings ? 'Saving...' : 'Save Settings'}
                  </button>
                </div>
              </form>
            </div>
          )}
        </div>
      )}

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4">
        <div className="glass-panel p-4 border-l-4 border-cyan-400">
          <div className="text-xs font-bold uppercase" style={{ color: 'var(--text-muted)' }}>Total Requested</div>
          <div className="text-2xl font-black text-cyan-400 mt-1">£{expensesData.summary?.total_requested?.toLocaleString(undefined, { minimumFractionDigits: 2 })}</div>
          <div className="text-[11px] font-medium mt-0.5" style={{ color: 'var(--text-sub)' }}>{expensesData.summary?.total_count || 0} Total Claims Submitted</div>
        </div>

        <div className="glass-panel p-4 border-l-4 border-emerald-400">
          <div className="text-xs font-bold uppercase" style={{ color: 'var(--text-muted)' }}>Approved Amount</div>
          <div className="text-2xl font-black text-emerald-400 mt-1">£{expensesData.summary?.total_approved?.toLocaleString(undefined, { minimumFractionDigits: 2 })}</div>
          <div className="text-[11px] text-emerald-500 font-bold mt-0.5">{expensesData.summary?.count_approved || 0} Approved Expenses</div>
        </div>

        <div className="glass-panel p-4 border-l-4 border-amber-400">
          <div className="text-xs font-bold uppercase" style={{ color: 'var(--text-muted)' }}>Pending Approval</div>
          <div className="text-2xl font-black text-amber-400 mt-1">£{expensesData.summary?.total_pending?.toLocaleString(undefined, { minimumFractionDigits: 2 })}</div>
          <div className="text-[11px] text-amber-500 font-bold mt-0.5">{expensesData.summary?.count_pending || 0} Awaiting Review</div>
        </div>

        <div className="glass-panel p-4 border-l-4 border-rose-400">
          <div className="text-xs font-bold uppercase" style={{ color: 'var(--text-muted)' }}>Rejected Amount</div>
          <div className="text-2xl font-black text-rose-400 mt-1">£{expensesData.summary?.total_rejected?.toLocaleString(undefined, { minimumFractionDigits: 2 })}</div>
          <div className="text-[11px] text-rose-500 font-bold mt-0.5">{expensesData.summary?.count_rejected || 0} Declined Requests</div>
        </div>
      </div>

      {/* Code Net Available Balance Tracker (Paginated & Theme-Safe UX) */}
      <div className="glass-panel p-5 border-l-4 border-purple-400 flex flex-col gap-4">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <h3 className="text-sm font-bold flex items-center gap-2" style={{ color: 'var(--text-main)' }}>
              <Wallet className="w-4 h-4 text-purple-400" /> Project Code Net Balances (Donations - Approved Expenses)
            </h3>
            <p className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>Live gross donation revenue minus approved category expenses per project code.</p>
          </div>

          {/* Search Bar */}
          <div className="flex items-center gap-3">
            <div className="relative flex items-center">
              <Search className="w-3.5 h-3.5 absolute left-3" style={{ color: 'var(--text-sub)' }} />
              <input 
                type="text"
                placeholder="Search code, country, heading..."
                value={codeSearch}
                onChange={e => {
                  setCodeSearch(e.target.value);
                  setCodePage(1);
                }}
                className="pl-8 pr-3 py-1.5 rounded-xl text-xs font-medium w-64 transition-all focus:outline-none"
                style={{
                  backgroundColor: 'var(--input-bg)',
                  color: 'var(--input-text)',
                  borderColor: 'var(--input-border)',
                  borderWidth: '1px',
                  borderStyle: 'solid'
                }}
              />
              {codeSearch && (
                <button 
                  onClick={() => setCodeSearch('')}
                  className="absolute right-2.5 text-xs font-bold"
                  style={{ color: 'var(--text-sub)' }}
                >
                  ✕
                </button>
              )}
            </div>
          </div>
        </div>

        {/* Paginated Balances Display - Cards Grid */}
        {codesLoading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="p-4 rounded-xl border flex flex-col gap-3 animate-pulse" style={{ backgroundColor: 'var(--bg-card-inner)', borderColor: 'var(--border-glass)' }}>
                <div className="flex items-center justify-between">
                  <div className="h-3 w-28 rounded-full" style={{ backgroundColor: 'var(--border-glass)' }} />
                  <div className="h-4 w-16 rounded-full" style={{ backgroundColor: 'var(--border-glass)' }} />
                </div>
                <div className="h-3 w-3/4 rounded-full" style={{ backgroundColor: 'var(--border-glass)' }} />
                <div className="h-2.5 w-1/2 rounded-full" style={{ backgroundColor: 'var(--border-glass)' }} />
                <div className="border-t pt-2.5 mt-1 flex flex-col gap-2" style={{ borderColor: 'var(--border-glass)' }}>
                  <div className="flex justify-between"><div className="h-2.5 w-20 rounded-full" style={{ backgroundColor: 'var(--border-glass)' }} /><div className="h-2.5 w-16 rounded-full" style={{ backgroundColor: 'var(--border-glass)' }} /></div>
                  <div className="flex justify-between"><div className="h-2.5 w-24 rounded-full" style={{ backgroundColor: 'var(--border-glass)' }} /><div className="h-2.5 w-12 rounded-full" style={{ backgroundColor: 'var(--border-glass)' }} /></div>
                  <div className="flex justify-between border-t pt-1.5" style={{ borderColor: 'var(--border-glass)' }}><div className="h-3 w-20 rounded-full" style={{ backgroundColor: 'var(--border-glass)' }} /><div className="h-3 w-20 rounded-full" style={{ backgroundColor: 'var(--border-glass)' }} /></div>
                </div>
              </div>
            ))}
          </div>
        ) : filteredCodes.length === 0 ? (
          <div className="py-8 text-center text-xs font-semibold" style={{ color: 'var(--text-muted)' }}>
            {codeSearch ? `No project codes found matching '${codeSearch}'.` : 'No project codes available.'}
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {paginatedCodes.map(b => (
              <div 
                key={b.code} 
                onClick={() => setSelectedCodeDetail(b)}
                className="p-4 rounded-xl border flex flex-col gap-2 transition-all shadow-sm hover:border-cyan-400 hover:scale-[1.01] cursor-pointer group relative"
                style={{
                  backgroundColor: 'var(--bg-card-inner)',
                  borderColor: 'var(--border-glass)'
                }}
                title="Click to view code details & related expense claims"
              >
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs font-black text-cyan-400 tracking-wide flex items-center gap-1 group-hover:underline">
                    {b.code} <Eye className="w-3 h-3 opacity-0 group-hover:opacity-100 transition-opacity" />
                  </span>
                  <div className="flex items-center gap-1.5">
                    {isSuperAdmin && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setTransferInitialSource(b.code);
                          setShowTransferModal(true);
                        }}
                        className="opacity-80 hover:opacity-100 p-1 rounded-md bg-purple-500/15 text-purple-300 hover:bg-purple-500/25 border border-purple-500/30 text-[10px] font-bold flex items-center gap-1 transition-all"
                        title={`Transfer funds out of ${b.code}`}
                      >
                        <ArrowRightLeft className="w-2.5 h-2.5" /> Transfer
                      </button>
                    )}
                    <span className="badge badge-emerald">{b.country}</span>
                  </div>
                </div>

                <div className="text-xs font-bold truncate mt-0.5" style={{ color: 'var(--text-main)' }} title={b.heading}>{b.heading}</div>
                <div className="text-[11px] truncate" style={{ color: 'var(--text-muted)' }} title={b.sub_heading}>{b.sub_heading}</div>

                <div className="border-t pt-2.5 mt-1 flex flex-col gap-1.5" style={{ borderColor: 'var(--border-glass)' }}>
                  <div className="flex justify-between text-xs">
                    <span style={{ color: 'var(--text-muted)' }}>Gross Raised:</span>
                    <span className="font-bold" style={{ color: 'var(--text-main)' }}>£{b.gross_raised?.toLocaleString(undefined, { minimumFractionDigits: 2 })}</span>
                  </div>

                  <div className="flex justify-between text-xs">
                    <span style={{ color: 'var(--text-muted)' }}>Approved Deductions:</span>
                    <span className={b.approved_expenses > 0 ? 'font-bold text-rose-400' : ''} style={{ color: b.approved_expenses > 0 ? '#F87171' : 'var(--text-muted)' }}>
                      {b.approved_expenses > 0 ? `-£${b.approved_expenses?.toLocaleString(undefined, { minimumFractionDigits: 2 })}` : '£0.00'}
                    </span>
                  </div>

                  {(b.transfers_in > 0 || b.transfers_out > 0) && (
                    <div className="flex justify-between text-xs">
                      <span style={{ color: 'var(--text-muted)' }}>Net Transfers:</span>
                      <span className={`font-bold ${b.net_transfers >= 0 ? 'text-cyan-400' : 'text-amber-400'}`}>
                        {b.net_transfers >= 0 ? `+£${b.net_transfers?.toLocaleString(undefined, { minimumFractionDigits: 2 })}` : `-£${Math.abs(b.net_transfers)?.toLocaleString(undefined, { minimumFractionDigits: 2 })}`}
                      </span>
                    </div>
                  )}

                  <div className="flex justify-between text-xs border-t pt-1.5 font-black" style={{ borderColor: 'var(--border-glass)' }}>
                    <span className="text-purple-400 font-bold">Net Remaining:</span>
                    <span className={b.net_balance >= 0 ? 'text-emerald-400 font-extrabold' : 'text-rose-400 font-extrabold'}>
                      £{b.net_balance?.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                    </span>
                  </div>
                </div>

                <div className="text-[10px] text-cyan-400/70 font-semibold text-right pt-1 group-hover:text-cyan-400 flex items-center justify-between">
                  <span className="text-[9px] text-slate-500 font-normal">{b.zakat_eligibility || 'Non-Zakat'}</span>
                  <span>Click for full details ➔</span>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Pagination Bar for Code Balances */}
        <div className="flex items-center justify-between pt-2 flex-wrap gap-3 border-t" style={{ borderColor: 'var(--border-glass)' }}>
          <div className="text-xs font-semibold" style={{ color: 'var(--text-muted)' }}>
            Showing {filteredCodes.length === 0 ? 0 : (codePage - 1) * codePageSize + 1} - {Math.min(codePage * codePageSize, filteredCodes.length)} of <span className="font-bold" style={{ color: 'var(--text-main)' }}>{filteredCodes.length}</span> project codes
          </div>

          <div className="flex items-center gap-2">
            <button
              disabled={codePage <= 1}
              onClick={() => setCodePage(prev => Math.max(prev - 1, 1))}
              className="btn-secondary text-xs px-2.5 py-1 rounded-lg flex items-center gap-1 disabled:opacity-40"
            >
              <ChevronLeft className="w-3.5 h-3.5" /> Prev
            </button>
            <span className="text-xs font-bold px-2" style={{ color: 'var(--text-main)' }}>
              Page {codePage} of {totalCodePages}
            </span>
            <button
              disabled={codePage >= totalCodePages}
              onClick={() => setCodePage(prev => Math.min(prev + 1, totalCodePages))}
              className="btn-secondary text-xs px-2.5 py-1 rounded-lg flex items-center gap-1 disabled:opacity-40"
            >
              Next <ChevronRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </div>

      {/* Filter Tabs & Export */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b pb-3" style={{ borderColor: 'var(--border-glass)' }}>
        <div className="flex items-center gap-2 flex-wrap">
          <Filter className="w-4 h-4 ml-1" style={{ color: 'var(--text-muted)' }} />
          <span className="text-xs font-bold mr-1" style={{ color: 'var(--text-muted)' }}>Filter Claims:</span>
          {['ALL', 'PENDING_APPROVAL', 'APPROVED', 'REJECTED'].map(st => (
            <button
              key={st}
              onClick={() => setStatusFilter(st)}
              className={`btn-secondary text-xs px-3 py-1.5 rounded-lg font-bold transition-all ${
                statusFilter === st 
                  ? 'bg-cyan-500/20 text-cyan-400 border-cyan-400 shadow-md shadow-cyan-500/10' 
                  : 'border-transparent'
              }`}
              style={{ color: statusFilter === st ? '' : 'var(--text-muted)' }}
            >
              {st === 'ALL' ? 'All Expenses' : st === 'PENDING_APPROVAL' ? '⏳ Pending' : st === 'APPROVED' ? '✓ Approved' : '✗ Rejected'}
            </button>
          ))}
        </div>

        {/* Download CSV / Excel Export */}
        <div className="flex items-center gap-2">
          <a
            href={`${API_BASE_URL}/api/expenses/export?status_filter=${statusFilter}&format=csv&company_id=${encodeURIComponent(activeCompany)}`}
            download
            className="px-2.5 py-1.5 rounded-lg text-xs font-bold flex items-center gap-1.5 bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 border border-emerald-500/30 transition-all cursor-pointer"
            title="Export filtered expense claims as CSV"
          >
            <Download className="w-3.5 h-3.5" /> CSV
          </a>
          <a
            href={`${API_BASE_URL}/api/expenses/export?status_filter=${statusFilter}&format=xlsx&company_id=${encodeURIComponent(activeCompany)}`}
            download
            className="px-2.5 py-1.5 rounded-lg text-xs font-bold flex items-center gap-1.5 bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 border border-emerald-500/30 transition-all cursor-pointer"
            title="Export filtered expense claims as Excel (.xlsx)"
          >
            <FileSpreadsheet className="w-3.5 h-3.5" /> Excel
          </a>
        </div>
      </div>

      {/* Expense Log Table */}
      {loading ? (
        <div className="glass-panel overflow-hidden">
          <div className="overflow-x-auto">
            <table className="crm-table">
              <thead>
                <tr>
                  <th>Expense ID</th><th>Date</th><th>Project Code</th><th>GL Ledger Code</th>
                  <th>Zakat</th><th>Department</th><th>Office</th><th>Amount</th><th>Status</th>
                </tr>
              </thead>
              <tbody>
                {Array.from({ length: 5 }).map((_, i) => (
                  <tr key={i} className="animate-pulse">
                    <td><div className="h-3 w-28 rounded-full" style={{ backgroundColor: 'var(--border-glass)' }} /></td>
                    <td><div className="h-3 w-20 rounded-full" style={{ backgroundColor: 'var(--border-glass)' }} /></td>
                    <td><div className="h-3 w-24 rounded-full" style={{ backgroundColor: 'var(--border-glass)' }} /></td>
                    <td><div className="h-3 w-20 rounded-full" style={{ backgroundColor: 'var(--border-glass)' }} /></td>
                    <td><div className="h-4 w-14 rounded-full" style={{ backgroundColor: 'var(--border-glass)' }} /></td>
                    <td><div className="h-3 w-20 rounded-full" style={{ backgroundColor: 'var(--border-glass)' }} /></td>
                    <td><div className="h-3 w-20 rounded-full" style={{ backgroundColor: 'var(--border-glass)' }} /></td>
                    <td><div className="h-3 w-14 rounded-full" style={{ backgroundColor: 'var(--border-glass)' }} /></td>
                    <td><div className="h-4 w-16 rounded-full" style={{ backgroundColor: 'var(--border-glass)' }} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <div className="glass-panel overflow-hidden">
          <div className="overflow-x-auto max-h-[580px] custom-scrollbar">
            <table className="crm-table">
              <thead>
                <tr>
                  <th>Expense ID</th>
                  <th>Date</th>
                  <th>Project Code</th>
                  <th>GL Ledger Code</th>
                  <th>Zakat</th>
                  <th>Department</th>
                  <th>Office</th>
                  <th>Country</th>
                  <th>Title & Vendor</th>
                  <th>Amount</th>
                  <th>Status</th>
                  {isSuperAdmin && <th className="text-right">Actions</th>}
                </tr>
              </thead>
              <tbody>
                {expensesData.expenses?.length === 0 ? (
                  <tr>
                    <td colSpan={isSuperAdmin ? 12 : 11} className="text-center py-12 text-xs font-semibold" style={{ color: 'var(--text-muted)' }}>
                      No expense claims found matching filter '{statusFilter}'.
                    </td>
                  </tr>
                ) : (
                  expensesData.expenses?.map(exp => (
                    <tr key={exp.id} className="hover:bg-cyan-500/5 transition-colors">
                      <td className="font-mono text-xs font-bold text-cyan-400">{exp.id}</td>
                      <td className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>{exp.payment_date}</td>
                      <td className="font-mono text-xs font-bold text-purple-400">{exp.code}</td>
                      <td>
                        {exp.gl_code ? (
                          <span className="font-mono text-xs font-bold px-2 py-0.5 rounded bg-slate-900/90 text-cyan-300 border border-cyan-500/30 shadow-xs">
                            {exp.gl_code}
                          </span>
                        ) : (
                          <span className="text-slate-500 text-xs italic">—</span>
                        )}
                      </td>
                      <td>
                        {exp.is_zakat in [1, true, '1'] ? (
                          <span className="badge badge-emerald text-[10px] font-bold">Zakat</span>
                        ) : (
                          <span className="badge badge-secondary text-[10px] font-bold">Non-Zakat</span>
                        )}
                      </td>
                      <td className="text-xs font-semibold" style={{ color: 'var(--text-main)' }}>{exp.heading}</td>
                      <td className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>{exp.sub_heading}</td>
                      <td className="text-xs font-medium">
                        <span className="badge badge-emerald">{exp.country}</span>
                      </td>
                      <td>
                        <div className="text-xs font-bold" style={{ color: 'var(--text-main)' }}>{exp.title}</div>
                        <div className="text-[11px]" style={{ color: 'var(--text-muted)' }}>{exp.vendor}</div>
                      </td>
                      <td className="font-black text-sm text-cyan-400">
                        £{exp.amount?.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                      </td>
                      <td>
                        <span className={`badge ${
                          exp.status === 'APPROVED' ? 'badge-emerald' : exp.status === 'PENDING_APPROVAL' ? 'badge-amber' : 'badge-pink'
                        }`}>
                          {exp.status === 'APPROVED' ? '✓ APPROVED' : exp.status === 'PENDING_APPROVAL' ? '⏳ PENDING' : '✗ REJECTED'}
                        </span>
                      </td>

                      {isSuperAdmin && (
                        <td className="text-right">
                          <div className="flex items-center justify-end gap-2">
                            {exp.status === 'PENDING_APPROVAL' && (
                              <>
                                <button
                                  onClick={() => handleReview(exp.id, 'APPROVED')}
                                  className="px-2.5 py-1 bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-400 border border-emerald-500/40 rounded text-xs font-bold flex items-center gap-1 transition-all"
                                >
                                  <Check className="w-3.5 h-3.5" /> Approve
                                </button>
                                <button
                                  onClick={() => handleReview(exp.id, 'REJECTED')}
                                  className="px-2.5 py-1 bg-rose-500/20 hover:bg-rose-500/30 text-rose-400 border border-rose-500/40 rounded text-xs font-bold flex items-center gap-1 transition-all"
                                >
                                  <X className="w-3.5 h-3.5" /> Reject
                                </button>
                              </>
                            )}
                            {exp.status !== 'PENDING_APPROVAL' && (
                              <span className="text-[11px] font-semibold italic mr-2" style={{ color: 'var(--text-sub)' }}>
                                {exp.reviewed_by || 'Super Admin'}
                              </span>
                            )}
                            {/* Delete Button */}
                            {deleteConfirm === exp.id ? (
                              <div className="flex items-center gap-1.5">
                                <button
                                  onClick={() => handleDelete(exp.id)}
                                  disabled={deleting}
                                  className="px-2 py-1 bg-red-600/30 hover:bg-red-600/50 text-red-300 border border-red-500/50 rounded text-[11px] font-bold flex items-center gap-1 transition-all"
                                >
                                  <AlertTriangle className="w-3 h-3" /> {deleting ? 'Deleting...' : 'Confirm'}
                                </button>
                                <button
                                  onClick={() => setDeleteConfirm(null)}
                                  className="px-2 py-1 rounded text-[11px] font-bold transition-all"
                                  style={{ color: 'var(--text-muted)' }}
                                >
                                  Cancel
                                </button>
                              </div>
                            ) : (
                              <button
                                onClick={() => setDeleteConfirm(exp.id)}
                                className="px-2 py-1 bg-slate-500/10 hover:bg-red-500/15 hover:text-red-400 border border-transparent hover:border-red-500/30 rounded text-[11px] font-bold flex items-center gap-1 transition-all"
                                style={{ color: 'var(--text-sub)' }}
                                title="Delete this expense"
                              >
                                <Trash2 className="w-3 h-3" />
                              </button>
                            )}
                          </div>
                        </td>
                      )}
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Submit Expense Request Modal */}
      {showSubmitModal && (
        <div className="drawer-backdrop flex items-center justify-center p-4">
          <div className="glass-panel p-6 w-full max-w-xl border-l-4 border-cyan-400 flex flex-col gap-5 shadow-2xl panel-pop">
            <div className="flex items-center justify-between border-b pb-3" style={{ borderColor: 'var(--border-glass)' }}>
              <h3 className="text-base font-extrabold flex items-center gap-2" style={{ color: 'var(--text-main)' }}>
                <PlusCircle className="w-5 h-5 text-cyan-400" /> New Category Expense Claim Request
              </h3>
              <button 
                onClick={() => setShowSubmitModal(false)}
                className="text-lg font-bold transition-colors"
                style={{ color: 'var(--text-muted)' }}
              >
                ✕
              </button>
            </div>

            {formMsg && (
              <div className={`text-xs font-bold p-3 rounded-lg border ${
                formMsg.startsWith('⚠️') 
                  ? 'text-amber-400 bg-amber-500/10 border-amber-500/30' 
                  : formMsg.startsWith('❌') 
                    ? 'text-rose-400 bg-rose-500/10 border-rose-500/30'
                    : 'text-cyan-400 bg-cyan-500/10 border-cyan-500/30'
              }`}>
                {formMsg}
              </div>
            )}

            <form onSubmit={handleSubmitExpense} className="flex flex-col gap-4">
              {/* Select Project Code Dropdown */}
              <div>
                <label className="block text-xs font-bold mb-1" style={{ color: 'var(--text-main)' }}>
                  1. Select Project Code * <span className="text-cyan-400 font-normal">(Auto-fills Category Details)</span>
                </label>
                <select
                  required
                  value={selectedCode}
                  onChange={handleCodeSelect}
                  className="w-full rounded-lg px-3 py-2 text-xs font-mono focus:outline-none"
                  style={{
                    backgroundColor: 'var(--input-bg)',
                    color: 'var(--input-text)',
                    borderColor: 'var(--input-border)',
                    borderWidth: '1px',
                    borderStyle: 'solid'
                  }}
                >
                  <option value="">-- Choose Campaign Code --</option>
                  {codes.map(c => (
                    <option key={c.code} value={c.code}>
                      {c.code} — {c.heading} ({c.country})
                    </option>
                  ))}
                </select>
              </div>

              {/* Auto-Filled Details Readonly Group */}
              {selectedCode && (
                <div className="grid grid-cols-3 gap-3 p-3 rounded-lg border" style={{ backgroundColor: 'var(--bg-card-inner)', borderColor: 'var(--border-glass)' }}>
                  <div>
                    <span className="block text-[10px] font-bold uppercase" style={{ color: 'var(--text-muted)' }}>Department</span>
                    <span className="text-xs font-extrabold text-cyan-400 truncate block">{heading || 'N/A'}</span>
                  </div>
                  <div>
                    <span className="block text-[10px] font-bold uppercase" style={{ color: 'var(--text-muted)' }}>Office</span>
                    <span className="text-xs font-extrabold text-purple-400 truncate block">{subHeading || 'N/A'}</span>
                  </div>
                  <div>
                    <span className="block text-[10px] font-bold uppercase" style={{ color: 'var(--text-muted)' }}>Project Country</span>
                    <span className="text-xs font-extrabold text-emerald-400 truncate block">{country || 'N/A'}</span>
                  </div>
                </div>
              )}

              {/* Zakat Expense Toggle & Auto-Tagged GL Code */}
              <div className="p-3.5 rounded-xl border flex flex-col gap-2.5" style={{ backgroundColor: 'var(--bg-card-inner)', borderColor: isZakat ? 'rgba(16, 185, 129, 0.4)' : 'var(--border-glass)' }}>
                <div className="flex items-center justify-between">
                  <label className="flex items-center gap-2 cursor-pointer select-none">
                    <input 
                      type="checkbox" 
                      checked={isZakat} 
                      onChange={e => setIsZakat(e.target.checked)}
                      className="w-4 h-4 rounded text-emerald-500 focus:ring-emerald-400 cursor-pointer accent-emerald-500"
                    />
                    <span className="text-xs font-bold" style={{ color: 'var(--text-main)' }}>
                      This is a Zakat-Eligible Expense
                    </span>
                  </label>
                  <span className={`text-[10px] font-extrabold uppercase px-2 py-0.5 rounded-full ${isZakat ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40' : 'bg-slate-500/20 text-slate-400 border border-slate-500/30'}`}>
                    {isZakat ? 'Zakat Fund' : 'Non-Zakat / General'}
                  </span>
                </div>

                {/* Auto-Assigned GL Ledger Code Preview */}
                <div className="flex items-center justify-between text-xs pt-1 border-t border-white/5">
                  <span className="text-[11px] font-semibold" style={{ color: 'var(--text-muted)' }}>Auto-Assigned GL Ledger Code:</span>
                  <span className="font-mono font-bold text-xs px-2.5 py-1 rounded bg-slate-900 text-cyan-300 border border-cyan-500/30 shadow-xs">
                    {previewGlCode ? `GL: ${previewGlCode}` : '— (Auto-resolved from Code)'}
                  </span>
                </div>
              </div>

              {/* Title & Vendor */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold mb-1" style={{ color: 'var(--text-main)' }}>Expense Title / Purpose *</label>
                  <input 
                    type="text" 
                    required
                    placeholder="e.g. Water Well Drilling Phase 1"
                    value={title}
                    onChange={e => setTitle(e.target.value)}
                    className="w-full rounded-lg px-3 py-2 text-xs focus:outline-none"
                    style={{
                      backgroundColor: 'var(--input-bg)',
                      color: 'var(--input-text)',
                      borderColor: 'var(--input-border)',
                      borderWidth: '1px',
                      borderStyle: 'solid'
                    }}
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold mb-1" style={{ color: 'var(--text-main)' }}>Vendor / Payee Name</label>
                  <input 
                    type="text" 
                    placeholder="e.g. Global Water Logistics"
                    value={vendor}
                    onChange={e => setVendor(e.target.value)}
                    className="w-full rounded-lg px-3 py-2 text-xs focus:outline-none"
                    style={{
                      backgroundColor: 'var(--input-bg)',
                      color: 'var(--input-text)',
                      borderColor: 'var(--input-border)',
                      borderWidth: '1px',
                      borderStyle: 'solid'
                    }}
                  />
                </div>
              </div>

              {/* Amount & Date */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold mb-1" style={{ color: 'var(--text-main)' }}>Requested Amount (£) *</label>
                  <input 
                    type="number" 
                    step="0.01"
                    required
                    placeholder="0.00"
                    value={amount}
                    onChange={e => setAmount(e.target.value)}
                    className="w-full rounded-lg px-3 py-2 text-xs text-cyan-400 font-bold focus:outline-none"
                    style={{
                      backgroundColor: 'var(--input-bg)',
                      borderColor: 'var(--input-border)',
                      borderWidth: '1px',
                      borderStyle: 'solid'
                    }}
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold mb-1" style={{ color: 'var(--text-main)' }}>Payment Date</label>
                  <input 
                    type="date" 
                    required
                    value={paymentDate}
                    onChange={e => setPaymentDate(e.target.value)}
                    className="w-full rounded-lg px-3 py-2 text-xs focus:outline-none"
                    style={{
                      backgroundColor: 'var(--input-bg)',
                      color: 'var(--input-text)',
                      borderColor: 'var(--input-border)',
                      borderWidth: '1px',
                      borderStyle: 'solid'
                    }}
                  />
                </div>
              </div>

              {/* Notes */}
              <div>
                <label className="block text-xs font-bold mb-1" style={{ color: 'var(--text-main)' }}>Additional Notes / Memo</label>
                <textarea 
                  rows="2"
                  placeholder="Provide any additional context or reference invoice number..."
                  value={notes}
                  onChange={e => setNotes(e.target.value)}
                  className="w-full rounded-lg px-3 py-2 text-xs focus:outline-none"
                  style={{
                    backgroundColor: 'var(--input-bg)',
                    color: 'var(--input-text)',
                    borderColor: 'var(--input-border)',
                    borderWidth: '1px',
                    borderStyle: 'solid'
                  }}
                ></textarea>
              </div>

              {/* Form Buttons */}
              <div className="flex items-center justify-end gap-3 mt-2">
                <button
                  type="button"
                  onClick={() => setShowSubmitModal(false)}
                  className="btn-secondary text-xs"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submitting}
                  className="btn-primary text-xs flex items-center gap-1.5"
                >
                  <PlusCircle className="w-4 h-4" /> {submitting ? 'Submitting Claim...' : 'Submit for Approval'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Project Code Details & Related Expenses Modal Overlay */}
      {selectedCodeDetail && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-md animate-fadeIn">
          <div 
            className="glass-panel p-6 rounded-2xl w-full max-w-4xl max-h-[90vh] flex flex-col gap-5 overflow-y-auto border-t-4 border-purple-500 shadow-2xl relative"
            style={{ backgroundColor: 'var(--drawer-bg)', borderColor: 'var(--border-glass)' }}
          >
            {/* Header */}
            <div className="flex items-start justify-between border-b pb-4" style={{ borderColor: 'var(--border-glass)' }}>
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-mono text-lg font-black text-cyan-400">{selectedCodeDetail.code}</span>
                  <span className="badge badge-emerald">{selectedCodeDetail.country}</span>
                </div>
                <h3 className="text-base font-bold mt-1" style={{ color: 'var(--text-main)' }}>{selectedCodeDetail.heading}</h3>
                <p className="text-xs" style={{ color: 'var(--text-muted)' }}>{selectedCodeDetail.sub_heading}</p>
              </div>
              <button 
                onClick={() => setSelectedCodeDetail(null)}
                className="p-1.5 rounded-full hover:bg-white/10 text-slate-400 hover:text-white transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Financial Overview Stat Cards */}
            {/* Financial Balance Summary */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <div className="p-3.5 rounded-xl border flex flex-col gap-1" style={{ backgroundColor: 'var(--bg-card-inner)', borderColor: 'var(--border-glass)' }}>
                <span className="text-[10px] font-bold uppercase" style={{ color: 'var(--text-muted)' }}>Gross Raised</span>
                <span className="text-lg font-black text-white">£{selectedCodeDetail.gross_raised?.toLocaleString(undefined, { minimumFractionDigits: 2 })}</span>
              </div>
              <div className="p-3.5 rounded-xl border flex flex-col gap-1" style={{ backgroundColor: 'var(--bg-card-inner)', borderColor: 'var(--border-glass)' }}>
                <span className="text-[10px] font-bold uppercase text-rose-400">Approved Deductions</span>
                <span className="text-lg font-black text-rose-400">£{selectedCodeDetail.approved_expenses?.toLocaleString(undefined, { minimumFractionDigits: 2 })}</span>
              </div>
              <div className="p-3.5 rounded-xl border flex flex-col gap-1" style={{ backgroundColor: 'var(--bg-card-inner)', borderColor: 'var(--border-glass)' }}>
                <span className="text-[10px] font-bold uppercase text-cyan-400">Net Transfers</span>
                <span className="text-lg font-black text-cyan-400">
                  {selectedCodeDetail.net_transfers >= 0 ? `+£${selectedCodeDetail.net_transfers?.toLocaleString(undefined, { minimumFractionDigits: 2 })}` : `-£${Math.abs(selectedCodeDetail.net_transfers)?.toLocaleString(undefined, { minimumFractionDigits: 2 })}`}
                </span>
                <span className="text-[9px] text-slate-400">In: £{selectedCodeDetail.transfers_in || 0} • Out: £{selectedCodeDetail.transfers_out || 0}</span>
              </div>
              <div className="p-3.5 rounded-xl border flex flex-col gap-1" style={{ backgroundColor: 'var(--bg-card-inner)', borderColor: 'var(--border-glass)' }}>
                <span className="text-[10px] font-bold uppercase text-purple-400">Net Remaining</span>
                <span className={`text-lg font-black ${selectedCodeDetail.net_balance >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                  £{selectedCodeDetail.net_balance?.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                </span>
              </div>
            </div>

            {/* Quick Actions for Selected Code */}
            <div className="flex items-center gap-2 pt-1">
              {isSuperAdmin && (
                <button
                  onClick={() => {
                    const code = selectedCodeDetail.code;
                    setSelectedCodeDetail(null);
                    setTransferInitialSource(code);
                    setShowTransferModal(true);
                  }}
                  className="btn-primary text-xs px-3 py-1.5 flex items-center gap-1.5 shadow-lg shadow-purple-500/20"
                  style={{ background: 'linear-gradient(135deg, #8B5CF6, #06B6D4)' }}
                >
                  <ArrowRightLeft className="w-3.5 h-3.5" /> Transfer Funds From {selectedCodeDetail.code}
                </button>
              )}

              <button
                onClick={() => {
                  const code = selectedCodeDetail.code;
                  setSelectedCodeDetail(null);
                  setHistoryFilterCode(code);
                  setShowTransferHistoryModal(true);
                }}
                className="btn-secondary text-xs px-3 py-1.5 flex items-center gap-1.5"
              >
                <History className="w-3.5 h-3.5 text-purple-400" /> View Transfer Ledger for {selectedCodeDetail.code}
              </button>
            </div>

            {/* Related Expenses Table */}
            <div className="flex flex-col gap-3 mt-2">
              <div className="flex items-center justify-between">
                <h4 className="text-xs font-extrabold uppercase tracking-wider text-slate-300 flex items-center gap-2">
                  <CreditCard className="w-4 h-4 text-purple-400" /> Expense Claims under {selectedCodeDetail.code}
                </h4>
                <span className="text-xs font-bold text-slate-400">
                  {expensesData.expenses.filter(e => e.code === selectedCodeDetail.code).length} total claims
                </span>
              </div>

              {expensesData.expenses.filter(e => e.code === selectedCodeDetail.code).length === 0 ? (
                <div className="py-8 text-center text-xs font-semibold rounded-xl border p-6" style={{ backgroundColor: 'var(--bg-card-inner)', borderColor: 'var(--border-glass)', color: 'var(--text-muted)' }}>
                  💳 No expense claims have been submitted under code <span className="font-mono font-bold text-cyan-400">{selectedCodeDetail.code}</span> yet.
                </div>
              ) : (
                <div className="overflow-x-auto rounded-xl border" style={{ borderColor: 'var(--border-glass)' }}>
                  <table className="crm-table w-full">
                    <thead>
                      <tr>
                        <th>Claim ID</th>
                        <th>Title & Vendor</th>
                        <th>Date</th>
                        <th>Amount</th>
                        <th>Status</th>
                        <th>Requested By</th>
                        {(user?.role === 'super_admin' || user?.can_edit_donors === 1) && <th>Actions</th>}
                      </tr>
                    </thead>
                    <tbody>
                      {expensesData.expenses
                        .filter(e => e.code === selectedCodeDetail.code)
                        .map(exp => (
                          <tr key={exp.expense_id} className="hover:bg-cyan-500/5 transition-colors">
                            <td className="font-mono text-xs font-bold text-cyan-400">{exp.expense_id}</td>
                            <td>
                              <div className="text-xs font-bold" style={{ color: 'var(--text-main)' }}>{exp.title}</div>
                              {exp.vendor && <div className="text-[11px]" style={{ color: 'var(--text-muted)' }}>Vendor: {exp.vendor}</div>}
                            </td>
                            <td className="text-xs" style={{ color: 'var(--text-muted)' }}>{formatDate(exp.created_at)}</td>
                            <td className="text-xs font-black text-white">£{exp.amount?.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                            <td>{getStatusBadge(exp.status)}</td>
                            <td className="text-xs" style={{ color: 'var(--text-main)' }}>{exp.requested_by}</td>
                            {(user?.role === 'super_admin' || user?.can_edit_donors === 1) && (
                              <td>
                                <div className="flex items-center gap-1.5">
                                  {exp.status === 'PENDING_APPROVAL' && (
                                    <>
                                      <button 
                                        onClick={() => handleReviewExpense(exp.expense_id, 'APPROVED')}
                                        className="p-1 rounded bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30 transition-colors"
                                        title="Approve Claim"
                                      >
                                        <Check className="w-3.5 h-3.5" />
                                      </button>
                                      <button 
                                        onClick={() => handleReviewExpense(exp.expense_id, 'REJECTED')}
                                        className="p-1 rounded bg-rose-500/20 text-rose-400 hover:bg-rose-500/30 transition-colors"
                                        title="Reject Claim"
                                      >
                                        <X className="w-3.5 h-3.5" />
                                      </button>
                                    </>
                                  )}
                                  <button 
                                    onClick={() => handleDeleteExpense(exp.expense_id)}
                                    className="p-1 rounded bg-slate-700/50 text-slate-400 hover:bg-rose-500/20 hover:text-rose-400 transition-colors"
                                    title="Delete Claim"
                                  >
                                    <Trash2 className="w-3.5 h-3.5" />
                                  </button>
                                </div>
                              </td>
                            )}
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            <div className="flex justify-end border-t pt-4" style={{ borderColor: 'var(--border-glass)' }}>
              <button 
                onClick={() => setSelectedCodeDetail(null)}
                className="btn-secondary text-xs"
              >
                Close Details
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Internal Fund Transfers Modals ───────────────────────── */}
      <TransferFundsModal
        isOpen={showTransferModal}
        onClose={() => {
          setShowTransferModal(false);
          setTransferInitialSource('');
        }}
        codes={codes}
        initialSourceCode={transferInitialSource}
        onSuccess={() => {
          loadCodes(true);
          loadExpenses();
        }}
        user={user}
        isSuperAdmin={isSuperAdmin}
        activeCompany={activeCompany}
      />

      <TransferHistoryModal
        isOpen={showTransferHistoryModal}
        onClose={() => {
          setShowTransferHistoryModal(false);
          setHistoryFilterCode('');
        }}
        user={user}
        isSuperAdmin={isSuperAdmin}
        filterCode={historyFilterCode}
        activeCompany={activeCompany}
        onTransfersUpdated={() => {
          loadCodes(true);
          loadExpenses();
        }}
      />
    </div>
  );
}
