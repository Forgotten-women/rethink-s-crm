import React, { useEffect, useState } from 'react';
import { TrendingUp, PieChart, Award, Tag, Calendar, CheckCircle, Clock, FileText, Gift, Layers, DollarSign, MoreHorizontal } from 'lucide-react';
import { API_BASE_URL } from '../config';

export default function OverviewView({ filters, user, metrics, accentColor, activeCompany = 'rethink' }) {
  const [timeline, setTimeline] = useState([]);
  const [headings, setHeadings] = useState([]);
  const [campaigns, setCampaigns] = useState([]);
  const [subheadings, setSubheadings] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
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
    const queryStr = params.toString() ? `?${params.toString()}` : '';

    Promise.all([
      fetch(`${API_BASE_URL}/api/overview/timeline${queryStr}`).then(r => r.json()),
      fetch(`${API_BASE_URL}/api/overview/headings${queryStr}`).then(r => r.json()),
      fetch(`${API_BASE_URL}/api/overview/campaigns${queryStr}`).then(r => r.json()),
      fetch(`${API_BASE_URL}/api/overview/subheadings${queryStr}`).then(r => r.json()),
    ]).then(([timeData, headData, campData, subData]) => {
      setTimeline(timeData);
      setHeadings(headData);
      setCampaigns(campData);
      setSubheadings(subData);
      setLoading(false);
    }).catch(err => {
      console.error('Error loading overview data:', err);
      setLoading(false);
    });
  }, [filters, activeCompany]);

  if (loading) {
    return (
      <div className="py-24 text-center text-slate-400 font-semibold animate-pulse">
        ⚡ Loading Executive Overview Analytics...
      </div>
    );
  }

  const maxCampaignRaised = campaigns.length > 0 ? Math.max(...campaigns.map(c => c.total_raised)) : 1;

  const colorMaps = {
    cyan: { text: 'text-cyan-500', bg: 'bg-cyan-500', border: 'border-cyan-500' },
    emerald: { text: 'text-emerald-500', bg: 'bg-emerald-500', border: 'border-emerald-500' },
    purple: { text: 'text-purple-500', bg: 'bg-purple-500', border: 'border-purple-500' },
    rose: { text: 'text-rose-500', bg: 'bg-rose-500', border: 'border-rose-500' }
  };
  const tColors = colorMaps[accentColor] || colorMaps.cyan;

  // Format current date
  const now = new Date();
  const dateOptions = { weekday: 'long', day: 'numeric', month: 'long' };
  const formattedDate = now.toLocaleDateString('en-US', dateOptions);
  const hour = now.getHours();
  const greeting = hour < 12 ? 'GOOD MORNING' : hour < 18 ? 'GOOD AFTERNOON' : 'GOOD EVENING';

  const rawName = user?.username || user?.email?.split('@')[0] || 'Admin';
  const displayName = rawName.charAt(0).toUpperCase() + rawName.slice(1);

  return (
    <div className="flex flex-col gap-8 pb-10">
      {/* 1. Minimalist Greeting Header */}
      <div className="flex flex-col gap-1.5 pt-2">
        <span className="text-[10px] font-black uppercase tracking-widest text-slate-400 dark:text-slate-500">
          {greeting}
        </span>
        <h2 className="text-2xl sm:text-3xl font-black text-slate-800 dark:text-white tracking-tight">
          {displayName}, here is your overview
        </h2>
        <p className="text-xs font-semibold text-slate-500 dark:text-slate-400 mt-1">
          {formattedDate} • {Number(metrics?.total_txns || 0).toLocaleString()} donations tracked
        </p>
      </div>



      {/* 3. Two Column Layout for Main Data */}
      <div className="flex flex-col lg:flex-row gap-6 lg:gap-8 items-start">
        
        {/* LEFT COLUMN: Top Campaigns Table (Simulating "THIS MORNING" list) */}
        <div className="w-full lg:flex-[2] bg-white dark:bg-slate-900 border border-slate-200 dark:border-white/10 rounded-2xl shadow-[0_2px_10px_-3px_rgba(6,81,237,0.05)] overflow-hidden">
          <div className="px-6 py-4 border-b border-slate-100 dark:border-white/5">
            <h3 className="text-[11px] font-extrabold uppercase tracking-widest text-slate-500 dark:text-slate-400">Top Performing Campaigns</h3>
          </div>
          
          <div className="w-full overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-slate-100 dark:border-white/5 bg-slate-50/50 dark:bg-slate-900/50">
                  <th className="px-6 py-3 text-[10px] font-extrabold uppercase tracking-wider text-slate-400">Campaign Name</th>
                  <th className="px-6 py-3 text-[10px] font-extrabold uppercase tracking-wider text-slate-400">Total Raised</th>
                  <th className="px-6 py-3 text-[10px] font-extrabold uppercase tracking-wider text-slate-400">Performance</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-white/5">
                {campaigns.slice(0, 8).map((camp, idx) => (
                  <tr key={idx} className="hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors">
                    <td className="px-6 py-3.5">
                      <div className="flex items-center gap-3">
                        <div className={`w-8 h-8 rounded-full ${tColors.bg}/10 flex items-center justify-center ${tColors.text} font-bold text-xs`}>
                          {camp.campaign.substring(0, 1).toUpperCase()}
                        </div>
                        <div className="flex flex-col min-w-0">
                          <span className="text-sm font-bold text-slate-800 dark:text-slate-200 truncate max-w-[250px]">{camp.campaign}</span>
                          <span className="text-[10px] font-semibold text-slate-400 truncate max-w-[250px]">ID: {camp.campaign.substring(0, 8).toUpperCase()}...</span>
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-3.5">
                      <span className="text-sm font-black text-slate-800 dark:text-slate-200">
                        £{camp.total_raised?.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                      </span>
                    </td>
                    <td className="px-6 py-3.5">
                      <div className="flex items-center gap-2">
                        <div className="w-24 h-1.5 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden">
                          <div 
                            className={`h-full ${tColors.bg} rounded-full`}
                            style={{ width: `${(camp.total_raised / maxCampaignRaised) * 100}%` }}
                          />
                        </div>
                        <span className={`text-[10px] font-bold ${tColors.text} px-2 py-0.5 rounded-full ${tColors.bg}/10`}>
                          {Math.round((camp.total_raised / maxCampaignRaised) * 100)}%
                        </span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* RIGHT COLUMN: Widgets */}
        <div className="w-full lg:flex-[1] flex flex-col gap-6 lg:gap-8">
          
          {/* Categories Widget (Simulating "PATIENT ACTIVITY") */}
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-white/10 rounded-2xl p-6 shadow-[0_2px_10px_-3px_rgba(6,81,237,0.05)] flex flex-col gap-6">
            <h3 className="text-[11px] font-extrabold uppercase tracking-widest text-slate-500 dark:text-slate-400">Category Distribution</h3>
            
            <div className="flex flex-col gap-4">
              {headings.slice(0, 5).map((cat, idx) => (
                <div key={idx} className="flex flex-col gap-2">
                  <div className="flex items-center justify-between text-xs font-semibold">
                    <span className="text-slate-700 dark:text-slate-300 truncate">{cat.category}</span>
                    <span className="text-slate-900 dark:text-white font-bold">£{cat.total_raised?.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
                  </div>
                  <div className="w-full h-1.5 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden">
                    <div 
                      className="h-full bg-slate-800 dark:bg-slate-400 rounded-full"
                      style={{ width: `${(cat.total_raised / (headings[0]?.total_raised || 1)) * 100}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Subheadings / Alerts Widget (Simulating "NEEDS YOUR ATTENTION") */}
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-white/10 rounded-2xl p-6 shadow-[0_2px_10px_-3px_rgba(6,81,237,0.05)] flex flex-col gap-5">
            <h3 className="text-[11px] font-extrabold uppercase tracking-widest text-slate-500 dark:text-slate-400">Top Sub-Categories</h3>
            
            <div className="flex flex-col gap-4 divide-y divide-slate-100 dark:divide-white/5">
              {subheadings.slice(0, 4).map((sub, idx) => (
                <div key={idx} className="pt-4 first:pt-0 flex flex-col gap-1">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-bold text-slate-800 dark:text-slate-200">{sub.sub_heading}</span>
                    <span className="text-[10px] font-bold text-slate-600 dark:text-slate-400 bg-slate-100 dark:bg-slate-800 px-2 py-1 rounded-md">
                      £{sub.total_raised?.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                    </span>
                  </div>
                  <span className="text-xs text-slate-500 dark:text-slate-500">Highest performing sub-category grouping</span>
                </div>
              ))}
            </div>
          </div>

        </div>

      </div>
    </div>
  );
}
