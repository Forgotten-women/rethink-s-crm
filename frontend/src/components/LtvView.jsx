import React, { useEffect, useState } from 'react';
import { Crown, DollarSign, Users, Award } from 'lucide-react';
import { API_BASE_URL } from '../config';

export default function LtvView({ filters, activeCompany = 'rethink' }) {
  const [summary, setSummary] = useState([]);
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

    fetch(`${API_BASE_URL}/api/ltv/summary?${params.toString()}`)
      .then(res => res.json())
      .then(data => {
        setSummary(data);
        setLoading(false);
      })
      .catch(err => {
        console.error('Error loading LTV summary:', err);
        setLoading(false);
      });
  }, [filters, activeCompany]);

  if (loading) {
    return (
      <div className="py-24 text-center text-slate-400 font-semibold animate-pulse">
        ⚡ Loading Lifetime LTV Analytics...
      </div>
    );
  }

  const maxTierRaised = summary.length > 0 ? Math.max(...summary.map(s => s.total_raised)) : 1;

  const tierBadges = {
    'Super High': 'badge-pink',
    'High': 'badge-amber',
    'Medium': 'badge-emerald',
    'Medium Low': 'badge-cyan',
    'Low End': 'badge-slate'
  };

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="text-xl font-extrabold flex items-center gap-2" style={{ color: 'var(--text-main)' }}>
          <Crown className="w-5 h-5 text-purple-400" /> Lifetime Donor Value (LTV) & Segmentation
        </h2>
        <p className="text-xs" style={{ color: 'var(--text-sub)' }}>Donors are classified into tiers based on their cumulative Total Lifetime Raised across all campaigns.</p>
      </div>

      {/* Tier Visual Breakdown */}
      <div className="glass-panel p-5 border-l-4 border-purple-400 flex flex-col gap-5">
        <h3 className="text-sm font-bold text-slate-200 flex items-center gap-2">
          <DollarSign className="w-4 h-4 text-purple-400" /> Revenue Contribution by Donor Tier
        </h3>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
          {summary.map((item, idx) => (
            <div key={idx} className="glass-panel p-4 flex flex-col gap-2 border-t-2 border-cyan-400">
              <span className={`badge ${tierBadges[item.tier] || 'badge-cyan'} w-fit`}>{item.tier}</span>
              <div className="text-xl font-black mt-1" style={{ color: 'var(--text-main)' }}>£{item.total_raised?.toLocaleString(undefined, { minimumFractionDigits: 2 })}</div>
              <div className="text-xs font-semibold flex items-center justify-between" style={{ color: 'var(--text-sub)' }}>
                <span>{item.donation_count} donations</span>
                <span className="text-emerald-400">Avg £{item.avg_donation?.toFixed(2)}</span>
              </div>
              <div className="w-full h-1.5 rounded-full bg-slate-800 mt-1 overflow-hidden">
                <div 
                  className="h-full bg-gradient-to-r from-cyan-400 to-purple-500 rounded-full"
                  style={{ width: `${(item.total_raised / maxTierRaised) * 100}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Detailed Table */}
      <div className="glass-panel p-5 flex flex-col gap-4">
          <h3 className="text-sm font-bold flex items-center gap-2" style={{ color: 'var(--text-main)' }}>
          <Award className="w-4 h-4 text-cyan-400" /> Detailed LTV Tier Breakdown Table
        </h3>

        <div className="overflow-x-auto">
          <table className="crm-table">
            <thead>
              <tr>
                <th>Donor Tier</th>
                <th>Total Raised (£)</th>
                <th>Donation Count</th>
                <th>Average Donation (£)</th>
              </tr>
            </thead>
            <tbody>
              {summary.map((item, idx) => (
                <tr key={idx}>
                  <td>
                    <span className={`badge ${tierBadges[item.tier] || 'badge-cyan'}`}>{item.tier}</span>
                  </td>
                  <td className="font-extrabold text-cyan-400">£{item.total_raised?.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                  <td className="font-semibold text-slate-200">{item.donation_count?.toLocaleString()}</td>
                  <td className="font-bold text-emerald-400">£{item.avg_donation?.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
