import React, { useState, useEffect } from 'react';
import { ArrowRightLeft, AlertTriangle, CheckCircle2, X, RefreshCw, ShieldAlert, ArrowRight, CornerDownRight, Wallet } from 'lucide-react';
import { API_BASE_URL } from '../config';

export default function TransferFundsModal({
  isOpen,
  onClose,
  codes = [],
  initialSourceCode = '',
  onSuccess,
  user,
  isSuperAdmin,
  activeCompany = 'rethink'
}) {
  const [sourceCode, setSourceCode] = useState(initialSourceCode || '');
  const [destCode, setDestCode] = useState('');
  const [amount, setAmount] = useState('');
  const [reason, setReason] = useState('');
  const [transferDate, setTransferDate] = useState(new Date().toISOString().split('T')[0]);
  
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');
  const [successMsg, setSuccessMsg] = useState('');

  useEffect(() => {
    if (isOpen) {
      setSourceCode(initialSourceCode || '');
      setDestCode('');
      setAmount('');
      setReason('');
      setTransferDate(new Date().toISOString().split('T')[0]);
      setErrorMsg('');
      setSuccessMsg('');
    }
  }, [isOpen, initialSourceCode]);

  if (!isOpen) return null;

  const sourceObj = codes.find(c => c.code === sourceCode);
  const destObj = codes.find(c => c.code === destCode);

  const sourceBalance = sourceObj ? (sourceObj.net_balance || 0) : 0;
  const destBalance = destObj ? (destObj.net_balance || 0) : 0;

  const numAmount = parseFloat(amount || 0);
  const isOverdraft = numAmount > sourceBalance;
  const isIdentical = sourceCode && destCode && sourceCode === destCode;

  const sourceAfter = sourceBalance - numAmount;
  const destAfter = destBalance + numAmount;

  // Zakat mismatch check
  const sourceZakat = sourceObj?.zakat_eligibility || 'Unknown';
  const destZakat = destObj?.zakat_eligibility || 'Unknown';
  const isZakatMismatch = sourceObj && destObj && sourceZakat !== destZakat;

  const handleSetPercent = (pct) => {
    if (sourceBalance <= 0) return;
    const calc = Math.max(0, (sourceBalance * pct) / 100);
    setAmount(calc.toFixed(2));
  };

  const handleTransfer = (e) => {
    e.preventDefault();
    if (!isSuperAdmin) {
      setErrorMsg('❌ Fund transfers are strictly restricted to Super Admin accounts.');
      return;
    }
    if (!sourceCode || !destCode) {
      setErrorMsg('❌ Please select both Source and Destination project codes.');
      return;
    }
    if (isIdentical) {
      setErrorMsg('❌ Source and Destination project codes cannot be identical.');
      return;
    }
    if (numAmount <= 0 || isNaN(numAmount)) {
      setErrorMsg('❌ Please enter a valid transfer amount greater than £0.00.');
      return;
    }
    if (isOverdraft) {
      setErrorMsg(`❌ Insufficient funds on '${sourceCode}'. Available balance is £${sourceBalance.toLocaleString(undefined, { minimumFractionDigits: 2 })}.`);
      return;
    }
    if (!reason.trim()) {
      setErrorMsg('❌ A reason or reference note is required for financial audit tracking.');
      return;
    }

    setSubmitting(true);
    setErrorMsg('');

    fetch(`${API_BASE_URL}/api/expenses/transfers`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        company_id: activeCompany,
        source_code: sourceCode,
        destination_code: destCode,
        amount: numAmount,
        reason: reason.trim(),
        transfer_date: transferDate,
        user_role: user?.role || 'super_admin',
        can_edit_donors: user?.can_edit_donors === 1,
        transferred_by: user?.email || user?.display_name || 'Super Admin'
      })
    })
      .then(r => r.json())
      .then(res => {
        setSubmitting(false);
        if (res.status === 'success') {
          setSuccessMsg(`✅ ${res.message}`);
          if (onSuccess) onSuccess();
          setTimeout(() => {
            onClose();
          }, 1500);
        } else {
          setErrorMsg(`❌ ${res.detail || 'Failed to complete transfer.'}`);
        }
      })
      .catch(err => {
        setSubmitting(false);
        setErrorMsg(`❌ Error: ${err.message}`);
      });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-fadeIn">
      <div 
        className="w-full max-w-2xl rounded-2xl shadow-2xl border flex flex-col max-h-[92vh] overflow-hidden"
        style={{
          backgroundColor: 'var(--bg-card)',
          borderColor: 'var(--border-glass)',
          color: 'var(--text-main)'
        }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b bg-gradient-to-r from-purple-500/10 via-cyan-500/10 to-transparent" style={{ borderColor: 'var(--border-glass)' }}>
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-xl bg-purple-500/20 text-purple-400 border border-purple-500/30 shadow-inner">
              <ArrowRightLeft className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-base font-black flex items-center gap-2" style={{ color: 'var(--text-main)' }}>
                Transfer Funds Between Project Codes
              </h3>
              <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
                Reallocate available net balance between codes with full audit ledger tracking.
              </p>
            </div>
          </div>
          <button 
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-white/10 transition-colors"
            style={{ color: 'var(--text-sub)' }}
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Form Body */}
        <form onSubmit={handleTransfer} className="p-6 overflow-y-auto flex flex-col gap-4">
          {errorMsg && (
            <div className="text-xs font-bold text-rose-400 bg-rose-500/10 p-3.5 rounded-xl border border-rose-500/30 flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 flex-shrink-0" />
              <span>{errorMsg}</span>
            </div>
          )}

          {successMsg && (
            <div className="text-xs font-bold text-emerald-400 bg-emerald-500/10 p-3.5 rounded-xl border border-emerald-500/30 flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 flex-shrink-0" />
              <span>{successMsg}</span>
            </div>
          )}

          {/* Grid: Source Code & Destination Code */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {/* Source Code */}
            <div className="flex flex-col gap-1.5 p-3.5 rounded-xl border" style={{ backgroundColor: 'var(--bg-card-inner)', borderColor: 'var(--border-glass)' }}>
              <label className="text-xs font-extrabold uppercase tracking-wide flex items-center justify-between" style={{ color: 'var(--text-muted)' }}>
                <span>1. Source Code (From) *</span>
                {sourceObj && (
                  <span className={`text-[10px] font-black px-2 py-0.5 rounded-full ${sourceBalance > 0 ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30' : 'bg-rose-500/15 text-rose-400 border border-rose-500/30'}`}>
                    Avail: £{sourceBalance.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                  </span>
                )}
              </label>
              <select
                required
                value={sourceCode}
                onChange={e => setSourceCode(e.target.value)}
                className="w-full rounded-lg px-3 py-2 text-xs font-mono font-bold focus:outline-none"
                style={{
                  backgroundColor: 'var(--input-bg)',
                  color: 'var(--input-text)',
                  border: '1px solid var(--input-border)'
                }}
              >
                <option value="">-- Select Source Project Code --</option>
                {codes.map(c => (
                  <option key={`src-${c.code}`} value={c.code}>
                    {c.code} — {c.heading} (£{c.net_balance?.toLocaleString(undefined, { minimumFractionDigits: 2 })})
                  </option>
                ))}
              </select>
              {sourceObj && (
                <div className="text-[11px] flex flex-col gap-0.5 mt-1" style={{ color: 'var(--text-sub)' }}>
                  <div className="font-semibold text-slate-300 truncate">{sourceObj.heading} • {sourceObj.sub_heading}</div>
                  <div className="flex items-center gap-2 text-[10px]">
                    <span>Country: <strong className="text-white">{sourceObj.country}</strong></span>
                    <span>•</span>
                    <span className="badge badge-secondary text-[9px]">{sourceObj.zakat_eligibility || 'Non-Zakat'}</span>
                  </div>
                </div>
              )}
            </div>

            {/* Destination Code */}
            <div className="flex flex-col gap-1.5 p-3.5 rounded-xl border" style={{ backgroundColor: 'var(--bg-card-inner)', borderColor: 'var(--border-glass)' }}>
              <label className="text-xs font-extrabold uppercase tracking-wide flex items-center justify-between" style={{ color: 'var(--text-muted)' }}>
                <span>2. Destination Code (To) *</span>
                {destObj && (
                  <span className="text-[10px] font-black px-2 py-0.5 rounded-full bg-cyan-500/15 text-cyan-400 border border-cyan-500/30">
                    Current: £{destBalance.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                  </span>
                )}
              </label>
              <select
                required
                value={destCode}
                onChange={e => setDestCode(e.target.value)}
                className="w-full rounded-lg px-3 py-2 text-xs font-mono font-bold focus:outline-none"
                style={{
                  backgroundColor: 'var(--input-bg)',
                  color: 'var(--input-text)',
                  border: '1px solid var(--input-border)'
                }}
              >
                <option value="">-- Select Destination Code --</option>
                {codes
                  .filter(c => c.code !== sourceCode)
                  .map(c => (
                    <option key={`dst-${c.code}`} value={c.code}>
                      {c.code} — {c.heading} (£{c.net_balance?.toLocaleString(undefined, { minimumFractionDigits: 2 })})
                    </option>
                  ))}
              </select>
              {destObj && (
                <div className="text-[11px] flex flex-col gap-0.5 mt-1" style={{ color: 'var(--text-sub)' }}>
                  <div className="font-semibold text-slate-300 truncate">{destObj.heading} • {destObj.sub_heading}</div>
                  <div className="flex items-center gap-2 text-[10px]">
                    <span>Country: <strong className="text-white">{destObj.country}</strong></span>
                    <span>•</span>
                    <span className="badge badge-secondary text-[9px]">{destObj.zakat_eligibility || 'Non-Zakat'}</span>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Zakat Cross-Transfer Warning Banner */}
          {isZakatMismatch && (
            <div className="p-3.5 rounded-xl border bg-amber-500/10 border-amber-500/30 flex items-start gap-2.5 text-xs text-amber-300 animate-fadeIn">
              <ShieldAlert className="w-4 h-4 flex-shrink-0 text-amber-400 mt-0.5" />
              <div>
                <div className="font-bold">⚠️ Zakat Eligibility Classification Warning</div>
                <div className="text-[11px] text-amber-300/80 mt-0.5">
                  You are transferring funds between <strong>{sourceCode} ({sourceZakat})</strong> and <strong>{destCode} ({destZakat})</strong>. Please ensure this transfer complies with charity fund allocation and Zakat governance rules.
                </div>
              </div>
            </div>
          )}

          {/* Amount & Preset Buttons */}
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <label className="text-xs font-bold" style={{ color: 'var(--text-main)' }}>
                Transfer Amount (£ GBP) *
              </label>
              {sourceObj && sourceBalance > 0 && (
                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] uppercase font-bold" style={{ color: 'var(--text-muted)' }}>Quick:</span>
                  {[25, 50, 75, 100].map(pct => (
                    <button
                      type="button"
                      key={pct}
                      onClick={() => handleSetPercent(pct)}
                      className="text-[10px] font-black px-2 py-0.5 rounded-md border transition-all hover:border-purple-400 hover:text-purple-400"
                      style={{
                        backgroundColor: 'var(--bg-card-inner)',
                        borderColor: 'var(--border-glass)',
                        color: 'var(--text-sub)'
                      }}
                    >
                      {pct === 100 ? 'Max (100%)' : `${pct}%`}
                    </button>
                  ))}
                </div>
              )}
            </div>

            <div className="relative flex items-center">
              <span className="absolute left-3.5 text-sm font-bold text-slate-400">£</span>
              <input
                type="number"
                step="0.01"
                min="0.01"
                max={sourceBalance > 0 ? sourceBalance : undefined}
                required
                placeholder="0.00"
                value={amount}
                onChange={e => setAmount(e.target.value)}
                className={`w-full rounded-xl pl-8 pr-4 py-2.5 text-sm font-black focus:outline-none transition-all ${
                  isOverdraft ? 'border-rose-500 bg-rose-500/10 text-rose-300' : ''
                }`}
                style={{
                  backgroundColor: isOverdraft ? undefined : 'var(--input-bg)',
                  color: isOverdraft ? undefined : 'var(--input-text)',
                  border: isOverdraft ? '1px solid #F43F5E' : '1px solid var(--input-border)'
                }}
              />
            </div>

            {isOverdraft && (
              <div className="text-[11px] font-bold text-rose-400 flex items-center gap-1">
                <AlertTriangle className="w-3.5 h-3.5" /> Amount exceeds source available balance (£{sourceBalance.toLocaleString(undefined, { minimumFractionDigits: 2 })})
              </div>
            )}
          </div>

          {/* Transfer Date & Reason */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div>
              <label className="block text-xs font-bold mb-1" style={{ color: 'var(--text-main)' }}>
                Transfer Date *
              </label>
              <input
                type="date"
                required
                value={transferDate}
                onChange={e => setTransferDate(e.target.value)}
                className="w-full rounded-lg px-3 py-2 text-xs focus:outline-none"
                style={{
                  backgroundColor: 'var(--input-bg)',
                  color: 'var(--input-text)',
                  border: '1px solid var(--input-border)'
                }}
              />
            </div>

            <div className="sm:col-span-2">
              <label className="block text-xs font-bold mb-1" style={{ color: 'var(--text-main)' }}>
                Reason / Audit Reference Notes *
              </label>
              <input
                type="text"
                required
                placeholder="e.g. Reallocation for emergency relief deficit, campaign budget rebalancing"
                value={reason}
                onChange={e => setReason(e.target.value)}
                className="w-full rounded-lg px-3 py-2 text-xs focus:outline-none"
                style={{
                  backgroundColor: 'var(--input-bg)',
                  color: 'var(--input-text)',
                  border: '1px solid var(--input-border)'
                }}
              />
            </div>
          </div>

          {/* Live Impact Preview Card */}
          {sourceObj && destObj && numAmount > 0 && !isOverdraft && (
            <div className="p-4 rounded-xl border flex flex-col gap-2.5 bg-purple-500/5 border-purple-500/20">
              <div className="text-[11px] font-extrabold uppercase tracking-wider text-purple-400 flex items-center gap-1.5">
                <Wallet className="w-3.5 h-3.5" /> Balance Impact Summary (Live Simulation)
              </div>
              
              <div className="grid grid-cols-2 gap-3 text-xs">
                {/* Source Before / After */}
                <div className="p-2.5 rounded-lg border bg-black/20" style={{ borderColor: 'var(--border-glass)' }}>
                  <div className="font-bold text-slate-300">{sourceCode}</div>
                  <div className="flex justify-between text-[11px] mt-1 text-slate-400">
                    <span>Before:</span>
                    <span>£{sourceBalance.toLocaleString(undefined, { minimumFractionDigits: 2 })}</span>
                  </div>
                  <div className="flex justify-between text-[11px] text-rose-400">
                    <span>Transfer Out:</span>
                    <span>-£{numAmount.toLocaleString(undefined, { minimumFractionDigits: 2 })}</span>
                  </div>
                  <div className="flex justify-between text-xs font-black pt-1 border-t border-white/10 mt-1 text-emerald-400">
                    <span>New Balance:</span>
                    <span>£{sourceAfter.toLocaleString(undefined, { minimumFractionDigits: 2 })}</span>
                  </div>
                </div>

                {/* Dest Before / After */}
                <div className="p-2.5 rounded-lg border bg-black/20" style={{ borderColor: 'var(--border-glass)' }}>
                  <div className="font-bold text-slate-300">{destCode}</div>
                  <div className="flex justify-between text-[11px] mt-1 text-slate-400">
                    <span>Before:</span>
                    <span>£{destBalance.toLocaleString(undefined, { minimumFractionDigits: 2 })}</span>
                  </div>
                  <div className="flex justify-between text-[11px] text-cyan-400">
                    <span>Transfer In:</span>
                    <span>+£{numAmount.toLocaleString(undefined, { minimumFractionDigits: 2 })}</span>
                  </div>
                  <div className="flex justify-between text-xs font-black pt-1 border-t border-white/10 mt-1 text-cyan-400">
                    <span>New Balance:</span>
                    <span>£{destAfter.toLocaleString(undefined, { minimumFractionDigits: 2 })}</span>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Footer Actions */}
          <div className="flex items-center justify-end gap-3 border-t pt-4 mt-2" style={{ borderColor: 'var(--border-glass)' }}>
            <button
              type="button"
              onClick={onClose}
              disabled={submitting}
              className="btn-secondary text-xs px-4 py-2"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting || isOverdraft || numAmount <= 0 || !sourceCode || !destCode || isIdentical}
              className="btn-primary text-xs px-5 py-2 flex items-center gap-1.5 shadow-lg shadow-purple-500/20 disabled:opacity-40"
              style={{ background: 'linear-gradient(135deg, #8B5CF6, #06B6D4)' }}
            >
              <ArrowRightLeft className="w-3.5 h-3.5" />
              {submitting ? 'Executing Transfer...' : 'Confirm & Transfer Funds'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
