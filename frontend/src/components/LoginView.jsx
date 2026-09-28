import React, { useState } from 'react';
import { ShieldCheck, Lock, User, KeyRound, Sun, Moon } from 'lucide-react';
import { API_BASE_URL } from '../config';

export default function LoginView({ theme, onToggleTheme, onLoginSuccess }) {
  const [identity, setIdentity] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [isResetting, setIsResetting] = useState(false);
  const [resetSuccess, setResetSuccess] = useState(false);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!identity.trim() || !password.trim()) {
      setError('Please enter both email/username and password.');
      return;
    }

    setLoading(true);
    setError('');

    fetch(`${API_BASE_URL}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ identity, password })
    })
      .then(r => r.json())
      .then(res => {
        setLoading(false);
        if (res?.status === 'success') {
          onLoginSuccess(res.user, res.access_token);
        } else {
          setError(res?.detail || 'Invalid credentials or user not found.');
        }
      })
      .catch(err => {
        setLoading(false);
        setError(`Connection error: ${err.message}`);
      });
  };

  const handleReset = (e) => {
    e.preventDefault();
    if (!identity.trim()) {
      setError('Please enter your email/username to reset password.');
      return;
    }
    setLoading(true);
    setError('');
    // Simulate password reset request
    setTimeout(() => {
      setLoading(false);
      setResetSuccess(true);
      setTimeout(() => {
        setIsResetting(false);
        setResetSuccess(false);
      }, 3000);
    }, 1200);
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <div className="glass-panel p-8 w-full max-w-md border-l-4 border-cyan-400 flex flex-col gap-6 shadow-2xl relative">
        <button
          type="button"
          onClick={onToggleTheme}
          title={`Switch to ${theme === 'dark' ? 'Light Mode' : 'Dark Mode'}`}
          className="absolute top-4 right-4 p-2 rounded-xl border transition-all"
          style={{
            backgroundColor: 'var(--input-bg)',
            color: 'var(--text-main)',
            borderColor: 'var(--border-glass)'
          }}
        >
          {theme === 'dark' ? <Sun className="w-4 h-4 text-amber-400" /> : <Moon className="w-4 h-4 text-indigo-400" />}
        </button>

        <div className="text-center flex flex-col items-center gap-2">
          <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-cyan-400 to-blue-600 flex items-center justify-center text-slate-950 font-black shadow-xl shadow-cyan-500/20">
            <ShieldCheck className="w-8 h-8 fill-current" />
          </div>
          <h2 className="text-2xl font-black" style={{ color: 'var(--text-main)' }}>
            {isResetting ? 'Reset Password' : 'Secure Access Control'}
          </h2>
          <p className="text-xs" style={{ color: 'var(--text-sub)' }}>
            {isResetting ? 'Request a password reset.' : 'Please log in to access the Crowdfunding Analytics Platform.'}
          </p>
        </div>

        {error && <div className="p-3 rounded-xl bg-rose-500/10 border border-rose-500/30 text-xs font-bold text-rose-400 text-center">{error}</div>}

        {isResetting ? (
          <div className="flex flex-col gap-5 text-center py-4 bg-slate-950/40 rounded-2xl border border-white/5 p-5">
            <p className="text-xs text-slate-400 font-bold leading-relaxed">
              🔒 ONLY A SUPER ADMIN CAN RESET OR CHANGE USER PASSWORDS.
            </p>
            <p className="text-xs text-slate-300 font-semibold leading-relaxed">
              To request a password reset, please contact your Super Admin directly with your username or registered email address.
            </p>
            <button 
              type="button" 
              onClick={() => { setIsResetting(false); setError(''); }}
              className="btn-primary py-2.5 text-xs mt-3 flex items-center justify-center gap-1.5"
            >
              Back to Login
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div>
              <label className="text-xs font-bold mb-1.5 block" style={{ color: 'var(--text-sub)' }}>Email or Username</label>
              <div className="relative">
                <User className="w-4 h-4 absolute left-3 top-3" style={{ color: 'var(--text-sub)' }} />
                <input 
                  type="text"
                  placeholder="e.g. superadmin@analytics.com"
                  value={identity}
                  onChange={e => setIdentity(e.target.value)}
                  className="w-full rounded-xl pl-9 pr-4 py-2.5 text-xs placeholder-slate-500 focus:outline-none focus:border-cyan-500 transition-colors"
                  style={{
                    backgroundColor: 'var(--input-bg)',
                    color: 'var(--input-text)',
                    border: '1px solid var(--input-border)'
                  }}
                />
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="text-xs font-bold block" style={{ color: 'var(--text-sub)' }}>Password</label>
                <button 
                  type="button" 
                  onClick={() => { setIsResetting(true); setError(''); }}
                  className="text-[10px] font-bold text-cyan-500 hover:text-cyan-400 transition-colors"
                >
                  Forgot Password?
                </button>
              </div>
              <div className="relative">
                <Lock className="w-4 h-4 absolute left-3 top-3" style={{ color: 'var(--text-sub)' }} />
                <input 
                  type="password"
                  placeholder="Enter your password..."
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  className="w-full rounded-xl pl-9 pr-4 py-2.5 text-xs placeholder-slate-500 focus:outline-none focus:border-cyan-500"
                  style={{
                    backgroundColor: 'var(--input-bg)',
                    color: 'var(--input-text)',
                    border: '1px solid var(--input-border)'
                  }}
                />
              </div>
            </div>

            <button 
              type="submit" 
              disabled={loading}
              className="btn-primary py-3 text-sm flex items-center justify-center gap-2 mt-2 transition-transform active:scale-[0.98]"
            >
              <KeyRound className="w-4 h-4" /> {loading ? 'Authenticating...' : '🚀 Log In to Dashboard'}
            </button>
          </form>
        )}

        <div className="text-center text-[11px] border-t pt-4" style={{ color: 'var(--text-sub)', borderColor: 'var(--border-glass)' }}>
          Contact your administrator for access.
        </div>
      </div>
    </div>
  );
}
