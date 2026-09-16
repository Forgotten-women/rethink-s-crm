import React, { useState, useRef, useEffect } from 'react';
import { Zap, LogOut, User, Sun, Moon, TrendingUp, Gift, Layers, Euro, ChevronDown, Check, Building2, Globe } from 'lucide-react';

export default function Navbar({ 
  user, 
  theme, 
  onToggleTheme, 
  onSignOut, 
  accentColor, 
  setAccentColor, 
  metrics,
  activeCompany = 'rethink',
  onSwitchCompany,
  companies = [],
  currentCompany
}) {
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const dropdownRef = useRef(null);

  useEffect(() => {
    function handleClickOutside(event) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setDropdownOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const roleBadge = user?.role === 'super_admin' ? '⚡ SUPER ADMIN' : '👤 ADMIN';
  
  const colors = [
    { id: 'cyan', bg: 'bg-cyan-500' },
    { id: 'emerald', bg: 'bg-emerald-500' },
    { id: 'purple', bg: 'bg-purple-500' },
    { id: 'rose', bg: 'bg-rose-500' },
  ];

  const colorMaps = {
    cyan: {
      bgSubtle: 'bg-cyan-500/10',
      textMain: 'text-cyan-600 dark:text-cyan-300',
      borderSubtle: 'border-cyan-500/20',
      textAccent: 'text-cyan-500',
      bgMuted: 'bg-cyan-500/20',
      textMuted: 'text-cyan-600 dark:text-cyan-400'
    },
    emerald: {
      bgSubtle: 'bg-emerald-500/10',
      textMain: 'text-emerald-600 dark:text-emerald-300',
      borderSubtle: 'border-emerald-500/20',
      textAccent: 'text-emerald-500',
      bgMuted: 'bg-emerald-500/20',
      textMuted: 'text-emerald-600 dark:text-emerald-400'
    },
    purple: {
      bgSubtle: 'bg-purple-500/10',
      textMain: 'text-purple-600 dark:text-purple-300',
      borderSubtle: 'border-purple-500/20',
      textAccent: 'text-purple-500',
      bgMuted: 'bg-purple-500/20',
      textMuted: 'text-purple-600 dark:text-purple-400'
    },
    rose: {
      bgSubtle: 'bg-rose-500/10',
      textMain: 'text-rose-600 dark:text-rose-300',
      borderSubtle: 'border-rose-500/20',
      textAccent: 'text-rose-500',
      bgMuted: 'bg-rose-500/20',
      textMuted: 'text-rose-600 dark:text-rose-400'
    }
  };
  
  const tColors = colorMaps[accentColor] || colorMaps.cyan;

  // Determine allowed companies for user
  const userAllowed = user?.allowed_companies || ['ALL'];
  const canAccessAll = user?.role === 'super_admin' || userAllowed.includes('ALL');

  const isCompanySelectable = (cid) => {
    if (canAccessAll) return true;
    return userAllowed.map(c => c.toLowerCase()).includes(cid.toLowerCase());
  };

  const getCompanyColorBadge = (colorName) => {
    switch (colorName?.toLowerCase()) {
      case 'emerald': return 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20';
      case 'purple': return 'bg-purple-500/10 text-purple-600 dark:text-purple-400 border-purple-500/20';
      case 'rose': return 'bg-rose-500/10 text-rose-600 dark:text-rose-400 border-rose-500/20';
      default: return 'bg-cyan-500/10 text-cyan-600 dark:text-cyan-400 border-cyan-500/20';
    }
  };

  return (
    <header className="sticky top-0 z-40 w-full glass-panel border-b border-slate-200 dark:border-white/5 rounded-none rounded-b-xl shadow-sm">
      <div className="px-6 py-3.5 flex items-center justify-between gap-4">
        
        {/* Left: Brand Identity & Multi-Company Switcher */}
        <div className="flex items-center gap-3.5" ref={dropdownRef}>
          {/* Brand Logo Container */}
          <div className="relative group">
            <div className={`absolute -inset-0.5 rounded-2xl blur opacity-60 group-hover:opacity-100 transition duration-300 ${colors.find(c => c.id === accentColor)?.bg || 'bg-cyan-500'}`}></div>
            <div className="relative w-11 h-11 rounded-2xl bg-white dark:bg-slate-950 flex items-center justify-center text-slate-900 dark:text-white font-black shadow-sm border border-slate-200 dark:border-white/10 overflow-hidden">
              {currentCompany?.logo_url ? (
                <img 
                  src={currentCompany.logo_url} 
                  alt={currentCompany.name} 
                  className="w-full h-full object-contain p-1 rounded-xl"
                  onError={(e) => { e.target.style.display = 'none'; }}
                />
              ) : activeCompany === 'all' ? (
                <Globe className={`w-6 h-6 ${tColors.textAccent}`} />
              ) : (
                <span className={`text-sm font-black tracking-tight ${tColors.textAccent}`}>
                  {currentCompany?.short_code?.slice(0, 3).toUpperCase() || 'CRM'}
                </span>
              )}
            </div>
          </div>

          {/* Company Switcher Dropdown */}
          <div className="relative">
            <button
              onClick={() => setDropdownOpen(!dropdownOpen)}
              className="flex items-center gap-2.5 px-3 py-1.5 rounded-xl hover:bg-slate-100 dark:hover:bg-slate-800/60 border border-transparent hover:border-slate-200 dark:hover:border-white/10 transition-all text-left cursor-pointer group"
              title="Click to Switch Company Workspace"
            >
              <div>
                <div className="flex items-center gap-2">
                  <h1 className="text-base font-black tracking-tight text-slate-800 dark:text-white flex items-center gap-1.5">
                    {currentCompany?.name || 'Rethink Charity'}
                  </h1>
                  <span className={`text-[10px] font-extrabold px-2 py-0.5 rounded-full border shadow-sm ${getCompanyColorBadge(currentCompany?.accent_color)}`}>
                    {currentCompany?.short_code || 'Tenant'}
                  </span>
                  <ChevronDown className={`w-3.5 h-3.5 text-slate-400 group-hover:text-slate-600 dark:group-hover:text-slate-200 transition-transform duration-200 ${dropdownOpen ? 'rotate-180' : ''}`} />
                </div>
                <div className="flex items-center gap-2 text-xs text-slate-400 dark:text-slate-500">
                  <span className="text-[11px] font-medium flex items-center gap-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 inline-block animate-pulse" />
                    {activeCompany === 'all' ? 'Consolidated Aggregated Mode' : 'Isolated Multi-Tenant Workspace'}
                  </span>
                </div>
              </div>
            </button>

            {/* Dropdown Popover */}
            {dropdownOpen && (
              <div className="absolute left-0 top-full mt-2 w-72 rounded-2xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-white/10 shadow-2xl z-50 p-2 animate-in fade-in zoom-in-95 duration-150">
                <div className="px-3 py-2 text-[10px] font-black uppercase tracking-wider text-slate-400 dark:text-slate-500 border-b border-slate-100 dark:border-white/5 mb-1">
                  Select Organization
                </div>

                <div className="space-y-1">
                  {companies.map((comp) => {
                    const isSelected = activeCompany === comp.id;
                    const selectable = isCompanySelectable(comp.id);

                    return (
                      <button
                        key={comp.id}
                        disabled={!selectable}
                        onClick={() => {
                          if (onSwitchCompany) onSwitchCompany(comp.id);
                          setDropdownOpen(false);
                        }}
                        className={`w-full flex items-center justify-between px-3 py-2.5 rounded-xl text-left transition-all ${
                          !selectable 
                            ? 'opacity-40 cursor-not-allowed' 
                            : isSelected
                              ? 'bg-slate-100 dark:bg-slate-800 text-slate-900 dark:text-white font-bold'
                              : 'hover:bg-slate-50 dark:hover:bg-slate-800/50 text-slate-700 dark:text-slate-300'
                        }`}
                      >
                        <div className="flex items-center gap-2.5 min-w-0">
                          <div className="w-7 h-7 rounded-lg bg-slate-100 dark:bg-slate-800 flex items-center justify-center text-xs font-black shrink-0 overflow-hidden border border-slate-200 dark:border-white/5">
                            {comp.logo_url ? (
                              <img src={comp.logo_url} alt="" className="w-full h-full object-contain p-0.5" />
                            ) : (
                              <Building2 className="w-4 h-4 text-slate-500" />
                            )}
                          </div>
                          <div className="min-w-0">
                            <div className="text-xs font-bold truncate">{comp.name}</div>
                            <span className={`text-[9px] font-semibold px-1.5 py-0.2 rounded border ${getCompanyColorBadge(comp.accent_color)}`}>
                              {comp.short_code}
                            </span>
                          </div>
                        </div>

                        {isSelected && (
                          <Check className={`w-4 h-4 ${tColors.textAccent} shrink-0`} />
                        )}
                      </button>
                    );
                  })}

                  {/* Consolidated All Companies Option */}
                  {canAccessAll && (
                    <>
                      <div className="h-px bg-slate-100 dark:bg-white/5 my-1.5" />
                      <button
                        onClick={() => {
                          if (onSwitchCompany) onSwitchCompany('all');
                          setDropdownOpen(false);
                        }}
                        className={`w-full flex items-center justify-between px-3 py-2.5 rounded-xl text-left transition-all ${
                          activeCompany === 'all'
                            ? 'bg-slate-100 dark:bg-slate-800 text-slate-900 dark:text-white font-bold'
                            : 'hover:bg-slate-50 dark:hover:bg-slate-800/50 text-slate-700 dark:text-slate-300'
                        }`}
                      >
                        <div className="flex items-center gap-2.5 min-w-0">
                          <div className="w-7 h-7 rounded-lg bg-indigo-500/10 dark:bg-indigo-500/20 text-indigo-500 flex items-center justify-center shrink-0 border border-indigo-500/20">
                            <Layers className="w-4 h-4" />
                          </div>
                          <div className="min-w-0">
                            <div className="text-xs font-bold truncate">All Companies</div>
                            <span className="text-[9px] font-medium text-slate-400 dark:text-slate-500">
                              Consolidated Read-Only
                            </span>
                          </div>
                        </div>

                        {activeCompany === 'all' && (
                          <Check className={`w-4 h-4 ${tColors.textAccent} shrink-0`} />
                        )}
                      </button>
                    </>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Center: Live Fundraising Metrics */}
        {metrics && (
          <div className="hidden lg:flex flex-1 max-w-3xl mx-6 items-center justify-center">
            <div className="flex items-center gap-6 bg-slate-50/50 dark:bg-slate-900/50 border border-slate-200 dark:border-white/10 rounded-xl px-6 py-2 shadow-sm w-full divide-x divide-slate-200 dark:divide-white/10">
              
              {/* Total Raised */}
              <div className="flex flex-col flex-1 pl-0 pr-4">
                <div className="flex items-center justify-between mb-0.5">
                  <span className="text-[9px] font-extrabold uppercase tracking-widest text-slate-400 dark:text-slate-500">Total Raised</span>
                  <TrendingUp className="w-3 h-3 text-slate-300 dark:text-slate-600" />
                </div>
                <span className={`text-sm font-black ${accentColor === 'cyan' ? 'text-cyan-500' : accentColor === 'emerald' ? 'text-emerald-500' : accentColor === 'purple' ? 'text-purple-500' : 'text-rose-500'} font-mono tracking-tight`}>
                  £{Number(metrics.total_raised || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </span>
              </div>

              {/* Gift Aid */}
              <div className="flex flex-col flex-1 px-4">
                <div className="flex items-center justify-between mb-0.5">
                  <span className="text-[9px] font-extrabold uppercase tracking-widest text-slate-400 dark:text-slate-500">Gift Aid Est.</span>
                  <Gift className="w-3 h-3 text-slate-300 dark:text-slate-600" />
                </div>
                <span className="text-sm font-black text-amber-500 font-mono tracking-tight">
                  £{Number(metrics.gift_aid_estimate || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </span>
              </div>

              {/* Donations */}
              <div className="flex flex-col flex-1 px-4">
                <div className="flex items-center justify-between mb-0.5">
                  <span className="text-[9px] font-extrabold uppercase tracking-widest text-slate-400 dark:text-slate-500">Donations</span>
                  <Layers className="w-3 h-3 text-slate-300 dark:text-slate-600" />
                </div>
                <span className="text-sm font-black text-purple-500 font-mono tracking-tight">
                  {Number(metrics.total_txns || 0).toLocaleString()}
                </span>
              </div>

              {/* Avg Donation */}
              <div className="flex flex-col flex-1 pl-4 pr-0">
                <div className="flex items-center justify-between mb-0.5">
                  <span className="text-[9px] font-extrabold uppercase tracking-widest text-slate-400 dark:text-slate-500">Avg Donation</span>
                  <Euro className="w-3 h-3 text-slate-300 dark:text-slate-600" />
                </div>
                <span className="text-sm font-black text-emerald-500 font-mono tracking-tight">
                  €{Number(metrics.avg_donation || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </span>
              </div>

            </div>
          </div>
        )}

        {/* Right: User Profile & Actions */}
        <div className="flex items-center gap-3">
          {/* Theme Toggle Button */}
          <button 
            onClick={onToggleTheme}
            title={`Switch to ${theme === 'dark' ? 'Light Mode' : 'Dark Mode'}`}
            className="p-2.5 rounded-xl bg-white/50 dark:bg-slate-800/80 hover:bg-slate-100 dark:hover:bg-slate-700/80 border border-slate-200 dark:border-white/10 text-slate-700 dark:text-slate-200 text-xs font-bold transition-all flex items-center gap-1.5 shadow-sm active:scale-95 cursor-pointer"
          >
            {theme === 'dark' ? <Sun className="w-4 h-4 text-amber-500" /> : <Moon className="w-4 h-4 text-indigo-500" />}
          </button>

          {/* User Account Badge */}
          <div className="flex items-center gap-2.5 px-3 py-1.5 rounded-xl bg-white/60 dark:bg-slate-950/70 border border-slate-200 dark:border-white/10 shadow-sm">
            <div className={`w-7 h-7 rounded-lg ${tColors.bgMuted} flex items-center justify-center ${tColors.textMuted} font-bold shadow-sm border ${tColors.borderSubtle}`}>
              <User className="w-4 h-4" />
            </div>
            <div className="text-left min-w-0">
              <div className="text-xs font-extrabold text-slate-800 dark:text-white truncate max-w-[140px]">
                {(user?.email || user?.username || 'Admin').charAt(0).toUpperCase() + (user?.email || user?.username || 'Admin').slice(1)}
              </div>
              <span className={`text-[9px] font-black uppercase ${tColors.textMuted} tracking-wider block`}>
                {roleBadge}
              </span>
            </div>
          </div>

          {/* Sign Out Button */}
          <button 
            onClick={onSignOut}
            title="Sign Out of Session"
            className="p-2.5 sm:px-3.5 sm:py-2.5 rounded-xl bg-rose-50 dark:bg-rose-500/10 hover:bg-rose-100 dark:hover:bg-rose-500/20 border border-rose-200 dark:border-rose-500/30 text-rose-600 dark:text-rose-400 text-xs font-bold transition-all flex items-center gap-1.5 active:scale-95 shadow-sm cursor-pointer ml-1"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>

      </div>
    </header>
  );
}
