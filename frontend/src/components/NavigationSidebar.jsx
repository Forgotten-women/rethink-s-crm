import React, { useState } from 'react';
import { TrendingUp, Crown, Columns, Table, Shield, CreditCard, Database, Target, Diamond, DollarSign, ChevronLeft, ChevronRight, HeartHandshake } from 'lucide-react';

const tabs = [
  { id: 'overview', label: 'Dashboard', icon: TrendingUp },
  { id: 'kanban', label: 'Kanban Pipeline', icon: Columns },
  { id: 'ltv', label: 'Lifetime LTV', icon: Crown },
  { id: 'explorer', label: 'Data Explorer', icon: Table },
  { id: 'fundraisers', label: 'Fundraisers', icon: HeartHandshake },
  { id: 'payouts', label: 'Payout Reconciliation', icon: DollarSign },
  { id: 'tracker', label: 'Sponsorship Tracker', icon: Target },
  { id: 'classifications', label: 'Classifications', icon: Shield },
  { id: 'expenses', label: 'Expenses', icon: CreditCard },
  { id: 'admin', label: 'Admin & Data', icon: Database },
];

export default function NavigationSidebar({ 
  activeTab, 
  setActiveTab, 
  accentColor = 'cyan', 
  setAccentColor,
  activeCompany = 'rethink',
  currentCompany,
  companies = []
}) {
  const [isHovered, setIsHovered] = useState(false);
  const showExpanded = isHovered;

  const colors = [
    { id: 'cyan', bg: 'bg-cyan-500' },
    { id: 'emerald', bg: 'bg-emerald-500' },
    { id: 'purple', bg: 'bg-purple-500' },
    { id: 'rose', bg: 'bg-rose-500' },
  ];

  // Map accent colors to tailwind classes for text/border/bg
  const accentClasses = {
    cyan: 'text-cyan-500 border-cyan-500 bg-cyan-500/10',
    emerald: 'text-emerald-500 border-emerald-500 bg-emerald-500/10',
    purple: 'text-purple-500 border-purple-500 bg-purple-500/10',
    rose: 'text-rose-500 border-rose-500 bg-rose-500/10'
  };

  const hoverClasses = {
    cyan: 'hover:bg-cyan-500/5 hover:text-cyan-500',
    emerald: 'hover:bg-emerald-500/5 hover:text-emerald-500',
    purple: 'hover:bg-purple-500/5 hover:text-purple-500',
    rose: 'hover:bg-rose-500/5 hover:text-rose-500'
  };

  const handleMouseEnter = () => {
    setIsHovered(true);
  };

  const handleMouseLeave = () => {
    setIsHovered(false);
  };

  const displayName = currentCompany?.name || (activeCompany === 'all' ? 'All Companies' : 'Rethink Charity');

  return (
    <div 
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      className={`h-full flex flex-col glass-panel border-r border-slate-200 dark:border-white/5 relative z-40 rounded-none rounded-r-2xl transition-all duration-300 ease-in-out ${showExpanded ? 'w-64 shadow-xl' : 'w-20'} flex-shrink-0`}
    >
      {/* Brand / Logo Area */}
      <div className="h-20 flex items-center px-4 md:px-5 border-b border-slate-100 dark:border-white/5 bg-white/80 dark:bg-slate-900/80 backdrop-blur-md sticky top-0 z-50 transition-colors duration-300">
        <div className="flex items-center gap-3 group cursor-pointer overflow-hidden" aria-label="CRM Workspace">
          {/* Logo container with brand logo image or icon */}
          <div className="w-10 h-10 rounded-xl bg-slate-500/10 dark:bg-white/5 border border-slate-200 dark:border-white/10 flex items-center justify-center transition-transform group-hover:scale-105 shrink-0 overflow-hidden shadow-sm">
            {currentCompany?.logo_url ? (
              <img 
                src={currentCompany.logo_url} 
                alt={displayName} 
                className="w-full h-full object-contain p-1 rounded-lg"
                onError={(e) => { e.target.style.display = 'none'; }}
              />
            ) : (
              <Diamond 
                className={`w-5 h-5 ${accentClasses[accentColor].split(' ')[0]} fill-current`} 
                aria-hidden="true"
              />
            )}
          </div>
          
          {showExpanded && (
            <div className="flex flex-col min-w-0">
              <span className="text-base font-black tracking-tight text-slate-700 dark:text-slate-100 group-hover:text-slate-900 dark:group-hover:text-white transition-colors truncate">
                {displayName}
              </span>
              <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 dark:text-slate-500">
                {currentCompany?.short_code || 'Tenant'}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Navigation Links */}
      <div className="flex-1 overflow-y-auto py-6 px-3 flex flex-col gap-1.5 custom-scrollbar">
        {tabs.map(t => {
          const Icon = t.icon;
          const isActive = activeTab === t.id;
          
          return (
            <button
              key={t.id}
              onClick={() => setActiveTab(t.id)}
              title={!showExpanded ? t.label : undefined}
              className={`flex items-center ${!showExpanded ? 'justify-center px-0 py-3' : 'gap-3 px-4 py-3'} rounded-xl transition-all text-sm font-semibold text-left w-full
                ${isActive 
                  ? `shadow-sm ${accentClasses[accentColor]}` 
                  : `text-slate-500 dark:text-slate-400 ${hoverClasses[accentColor]}`
                }
              `}
            >
              <Icon className={`w-5 h-5 ${isActive ? '' : 'opacity-70'} shrink-0`} /> 
              {showExpanded && <span className="truncate">{t.label}</span>}
            </button>
          );
        })}
      </div>
      
      {/* Footer / Version Area */}
      <div className={`p-4 border-t border-slate-100 dark:border-white/5 transition-all duration-300 flex ${showExpanded ? 'justify-between' : 'justify-center'} items-center`}>
        {showExpanded ? (
          <div className="flex items-center gap-1.5 px-3 py-2 rounded-xl bg-slate-100/50 dark:bg-slate-900/50 border border-slate-200 dark:border-white/10 shadow-inner w-full justify-between">
            {colors.map(c => (
              <button
                key={c.id}
                onClick={() => setAccentColor(c.id)}
                className={`w-5 h-5 rounded-full ${c.bg} shadow-sm transition-transform hover:scale-110 ${accentColor === c.id ? 'ring-2 ring-offset-2 ring-slate-400 dark:ring-white/30 dark:ring-offset-slate-900 scale-110' : ''}`}
                title={`Theme: ${c.id}`}
              />
            ))}
          </div>
        ) : (
          <div className="flex flex-col gap-1.5 items-center justify-center p-1.5 rounded-xl bg-slate-100/50 dark:bg-slate-900/50 border border-slate-200 dark:border-white/10 shadow-inner">
            {colors.map(c => (
              <button
                key={c.id}
                onClick={() => setAccentColor(c.id)}
                className={`w-3 h-3 rounded-full ${c.bg} transition-all ${accentColor === c.id ? 'ring-2 ring-offset-1 ring-slate-400 dark:ring-white/30 dark:ring-offset-slate-900 scale-110' : 'opacity-50 hover:opacity-100'}`}
                title={`Theme: ${c.id}`}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
