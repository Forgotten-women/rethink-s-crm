import React, { useEffect, useState } from 'react';
import { Target, ShieldAlert, CheckCircle2, AlertCircle, Edit3, Save, UserCheck, Flame, HeartHandshake } from 'lucide-react';
import { API_BASE_URL } from '../config';

export default function TrackerView({ user, filters, onSelectDonor, activeCompany = 'rethink', companies = [] }) {
  const isConsolidated = activeCompany === 'all';
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  
  // Super Admin Target Configuration State
  const [showEditTargets, setShowEditTargets] = useState(false);
  const [targetInputs, setTargetInputs] = useState({
    Hafiz: 240,
    Orphan: 480,
    Widow: 1080,
    'Ex-Prisoner': 1080
  });
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');

  const loadTrackerData = () => {
    setLoading(true);
    const params = new URLSearchParams();
    params.append('company_id', activeCompany);
    if (filters) {
      if (filters.payment_type) params.append('payment_type', filters.payment_type);
      if (filters.tier) params.append('tier', filters.tier);
      if (filters.source) params.append('source', filters.source);
      if (filters.heading) params.append('heading', filters.heading);
      if (filters.subheading) params.append('subheading', filters.subheading);
      if (filters.country) params.append('country', filters.country);
      if (filters.code) params.append('code', filters.code);
      if (filters.zakat) params.append('zakat', filters.zakat);
      if (filters.donor_country) params.append('donor_country', filters.donor_country);
      if (filters.campaign_search) params.append('campaign_search', filters.campaign_search);
      if (filters.gift_aid) params.append('gift_aid', filters.gift_aid);
      if (filters.start_date) params.append('start_date', filters.start_date);
      if (filters.end_date) params.append('end_date', filters.end_date);
    }

    fetch(`${API_BASE_URL}/api/tracker/stats?${params.toString()}`)
      .then(res => res.json())
      .then(data => {
        setStats(data);
        if (data) {
          setTargetInputs({
            Hafiz: data.Hafiz?.target || 240,
            Orphan: data.Orphan?.target || 480,
            Widow: data.Widow?.target || 1080,
            'Ex-Prisoner': data['Ex-Prisoner']?.target || 1080
          });
        }
        setLoading(false);
      })
      .catch(err => {
        console.error('Error loading tracker stats:', err);
        setLoading(false);
      });
  };

  useEffect(() => {
    loadTrackerData();
  }, [filters, activeCompany]);

  const handleSaveTargets = (e) => {
    e.preventDefault();
    if (user?.role !== 'super_admin') return;
    setSaving(true);
    setMessage('');

    fetch(`${API_BASE_URL}/api/tracker/targets`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        company_id: activeCompany,
        user_role: user?.role,
        targets: {
          Hafiz: parseFloat(targetInputs.Hafiz) || 240,
          Orphan: parseFloat(targetInputs.Orphan) || 480,
          Widow: parseFloat(targetInputs.Widow) || 1080,
          'Ex-Prisoner': parseFloat(targetInputs['Ex-Prisoner']) || 1080
        }
      })
    })
      .then(res => res.json())
      .then(data => {
        setSaving(false);
        if (data?.status === 'success') {
          setMessage('✅ Targets updated successfully!');
          loadTrackerData();
          setTimeout(() => setShowEditTargets(false), 1200);
        } else {
          setMessage(`❌ ${data?.detail || 'Failed to update targets.'}`);
        }
      })
      .catch(err => {
        setSaving(false);
        setMessage(`❌ Error: ${err.message}`);
      });
  };

  const themeClasses = {
    cyan: {
      border: 'border-cyan-500/20',
      bgHeader: 'bg-cyan-500/10 border-cyan-500/20',
      iconBg: 'bg-cyan-500/20 text-cyan-600 dark:text-cyan-400',
      title: 'text-cyan-700 dark:text-cyan-300',
      sub: 'text-cyan-600/80 dark:text-cyan-400/80',
    },
    emerald: {
      border: 'border-emerald-500/20',
      bgHeader: 'bg-emerald-500/10 border-emerald-500/20',
      iconBg: 'bg-emerald-500/20 text-emerald-600 dark:text-emerald-400',
      title: 'text-emerald-700 dark:text-emerald-300',
      sub: 'text-emerald-600/80 dark:text-emerald-400/80',
    },
    purple: {
      border: 'border-purple-500/20',
      bgHeader: 'bg-purple-500/10 border-purple-500/20',
      iconBg: 'bg-purple-500/20 text-purple-600 dark:text-purple-400',
      title: 'text-purple-700 dark:text-purple-300',
      sub: 'text-purple-600/80 dark:text-purple-400/80',
    },
    rose: {
      border: 'border-rose-500/20',
      bgHeader: 'bg-rose-500/10 border-rose-500/20',
      iconBg: 'bg-rose-500/20 text-rose-600 dark:text-rose-400',
      title: 'text-rose-700 dark:text-rose-300',
      sub: 'text-rose-600/80 dark:text-rose-400/80',
    }
  };

  const SPONSORSHIP_METADATA = {
    Hafiz: { theme: 'cyan', icon: HeartHandshake },
    Orphan: { theme: 'emerald', icon: Flame },
    Widow: { theme: 'purple', icon: HeartHandshake },
    'Ex-Prisoner': { theme: 'rose', icon: UserCheck }
  };

  if (loading) {
    return (
      <div className="py-24 text-center text-slate-500 dark:text-slate-400 font-semibold animate-pulse">
        ⚡ Calculating Real-Time Sponsorship Target Statistics...
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {/* Header & Controls */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-extrabold text-slate-800 dark:text-white flex items-center gap-2">
            <Target className="w-5 h-5 text-cyan-500 dark:text-cyan-400" /> Sponsorship Real-Time Target Tracker
          </h2>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Real-time tracking of donors reaching near or above sponsorship threshold limits across all regions.
          </p>
        </div>

        {user?.role === 'super_admin' && (
          <button 
            onClick={() => setShowEditTargets(!showEditTargets)}
            className="btn-secondary text-xs flex items-center gap-1.5 text-cyan-600 dark:text-cyan-400 border-cyan-500/30 hover:bg-cyan-500/10"
          >
            <Edit3 className="w-3.5 h-3.5" /> ⚙️ Configure Target Limits (Super Admin Only)
          </button>
        )}
      </div>

      {/* Super Admin Edit Targets Form */}
      {showEditTargets && user?.role === 'super_admin' && (
        <div className="glass-panel p-5 border-l-4 border-cyan-500 dark:border-cyan-400 flex flex-col gap-4 animate-fadeIn bg-white dark:bg-slate-900">
          <div className="flex items-center justify-between border-b border-slate-200 dark:border-white/10 pb-3">
            <h3 className="text-xs font-extrabold text-slate-800 dark:text-white uppercase tracking-wider flex items-center gap-2">
              <Save className="w-4 h-4 text-cyan-500 dark:text-cyan-400" /> Configure Sponsorship Financial Target Thresholds
            </h3>
            <button onClick={() => setShowEditTargets(false)} className="text-xs text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-white">Close</button>
          </div>

          {message && <div className="text-xs font-bold text-emerald-500 dark:text-emerald-400">{message}</div>}

          <form onSubmit={handleSaveTargets} className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {['Hafiz', 'Orphan', 'Widow', 'Ex-Prisoner'].map((type) => (
              <div key={type} className="flex flex-col gap-1.5 p-3 rounded-xl border border-slate-200 dark:border-white/5 bg-slate-50 dark:bg-slate-900/40">
                <label className="text-[11px] text-cyan-600 dark:text-cyan-400 font-bold uppercase tracking-wider">{type} Target (£)</label>
                <input 
                  type="number"
                  step="1"
                  value={targetInputs[type] || ''}
                  onChange={e => setTargetInputs({ ...targetInputs, [type]: e.target.value })}
                  className="w-full bg-white dark:bg-slate-900 border border-slate-300 dark:border-white/10 rounded-lg p-2 text-xs text-slate-800 dark:text-white focus:outline-none focus:border-cyan-500 dark:focus:border-cyan-400"
                  required
                />
              </div>
            ))}

            <div className="sm:col-span-2 lg:col-span-4 flex justify-end gap-2 mt-2">
              <button type="button" onClick={() => setShowEditTargets(false)} className="btn-secondary text-xs">Cancel</button>
              <button type="submit" disabled={saving} className="btn-primary text-xs">
                {saving ? 'Saving...' : '💾 Update Target Limits'}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Grid of Sponsorship Tracker Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {['Hafiz', 'Orphan', 'Widow', 'Ex-Prisoner'].map((type) => {
          const item = stats?.[type] || { target: 0, total_raised: 0, above_count: 0, near_count: 0, above: [], near: [] };
          const meta = SPONSORSHIP_METADATA[type];
          const tcls = themeClasses[meta.theme];

          return (
            <div key={type} className={`glass-panel overflow-hidden flex flex-col gap-5 border ${tcls.border} rounded-2xl shadow-xl transition-all`}>
              {/* Card Banner */}
              <div className={`p-5 ${tcls.bgHeader} border-b flex items-center justify-between`}>
                <div className="flex items-center gap-3">
                  <div className={`w-10 h-10 rounded-xl ${tcls.iconBg} flex items-center justify-center`}>
                    <meta.icon className="w-5 h-5" />
                  </div>
                  <div>
                    <h3 className={`text-base font-extrabold ${tcls.title} tracking-wide`}>{type} Sponsorship</h3>
                    <p className={`text-xs ${tcls.sub} font-medium`}>
                      Target Threshold: <b className={tcls.title}>£{item.target?.toLocaleString()}</b>
                    </p>
                  </div>
                </div>

                <div className="text-right">
                  <div className={`text-xl font-black ${tcls.title} font-mono`}>£{item.total_raised?.toLocaleString()}</div>
                  <div className={`text-[11px] ${tcls.sub} font-bold uppercase`}>Total Raised</div>
                </div>
              </div>

              {/* Status Counters */}
              <div className="px-5 grid grid-cols-2 gap-3">
                <div className="p-3 rounded-xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-between">
                  <div className="flex items-center gap-2 text-amber-600 dark:text-amber-400 text-xs font-bold">
                    <AlertCircle className="w-4 h-4" /> Near Target (80-100%)
                  </div>
                  <span className="text-sm font-extrabold text-amber-600 dark:text-amber-400 font-mono">{item.near_count}</span>
                </div>

                <div className="p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-between">
                  <div className="flex items-center gap-2 text-emerald-600 dark:text-emerald-400 text-xs font-bold">
                    <CheckCircle2 className="w-4 h-4" /> Target Met (≥100%)
                  </div>
                  <span className="text-sm font-extrabold text-emerald-600 dark:text-emerald-400 font-mono">{item.above_count}</span>
                </div>
              </div>

              {/* Lists Section */}
              <div className="px-5 pb-5 flex flex-col gap-4">
                {/* 1. Near Target Donors */}
                <div className="flex flex-col gap-2">
                  <h4 className="text-xs font-extrabold text-amber-600 dark:text-amber-400 uppercase tracking-wider flex items-center gap-1.5">
                    <AlertCircle className="w-3.5 h-3.5" /> Donors Approaching Target ({item.near?.length || 0})
                  </h4>

                  {item.near?.length === 0 ? (
                    <div className="p-3 text-center text-xs text-slate-500 dark:text-slate-400 bg-slate-50 dark:bg-slate-900/40 rounded-xl border border-slate-200 dark:border-white/5">
                      No donors currently in 80%-100% threshold range.
                    </div>
                  ) : (
                    <div className="flex flex-col gap-2 max-h-[200px] overflow-y-auto pr-1">
                      {item.near?.map((d) => (
                        <div 
                          key={d.donor_id}
                          onClick={() => onSelectDonor(d.donor_id)}
                          className="p-3 rounded-xl border border-amber-500/20 bg-amber-50 dark:bg-amber-500/5 hover:bg-amber-100 dark:hover:bg-amber-500/10 cursor-pointer transition-all flex items-center justify-between gap-3 group"
                        >
                          <div className="min-w-0 flex-1">
                            <div className="text-xs font-bold text-slate-700 dark:text-slate-200 group-hover:text-amber-700 dark:group-hover:text-amber-400 truncate">{d.name}</div>
                            <div className="text-[11px] text-slate-500 dark:text-slate-400 truncate">{d.email}</div>
                          </div>

                          <div className="text-right shrink-0">
                            <div className="text-xs font-mono font-extrabold text-amber-600 dark:text-amber-400">£{d.total_donated.toFixed(2)}</div>
                            <div className="text-[10px] text-amber-600/80 dark:text-amber-400/80 font-bold">{d.progress}% of £{d.target}</div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* 2. Above Target Donors */}
                <div className="flex flex-col gap-2">
                  <h4 className="text-xs font-extrabold text-emerald-600 dark:text-emerald-400 uppercase tracking-wider flex items-center gap-1.5">
                    <CheckCircle2 className="w-3.5 h-3.5" /> Donors Meeting / Exceeding Target ({item.above?.length || 0})
                  </h4>

                  {item.above?.length === 0 ? (
                    <div className="p-3 text-center text-xs text-slate-500 dark:text-slate-400 bg-slate-50 dark:bg-slate-900/40 rounded-xl border border-slate-200 dark:border-white/5">
                      No donors have reached target threshold yet.
                    </div>
                  ) : (
                    <div className="flex flex-col gap-2 max-h-[200px] overflow-y-auto pr-1">
                      {item.above?.map((d) => (
                        <div 
                          key={d.donor_id}
                          onClick={() => onSelectDonor(d.donor_id)}
                          className="p-3 rounded-xl border border-emerald-500/20 bg-emerald-50 dark:bg-emerald-500/5 hover:bg-emerald-100 dark:hover:bg-emerald-500/10 cursor-pointer transition-all flex items-center justify-between gap-3 group"
                        >
                          <div className="min-w-0 flex-1">
                            <div className="text-xs font-bold text-slate-700 dark:text-slate-200 group-hover:text-emerald-700 dark:group-hover:text-emerald-400 truncate">{d.name}</div>
                            <div className="text-[11px] text-slate-500 dark:text-slate-400 truncate">{d.email}</div>
                          </div>

                          <div className="text-right shrink-0">
                            <div className="text-xs font-mono font-extrabold text-emerald-600 dark:text-emerald-400">£{d.total_donated.toFixed(2)}</div>
                            <div className="text-[10px] text-emerald-600/80 dark:text-emerald-400/80 font-bold flex items-center justify-end gap-1">
                              🎉 {d.progress}% of £{d.target}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
