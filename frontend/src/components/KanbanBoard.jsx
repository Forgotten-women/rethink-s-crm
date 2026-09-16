import React, { useEffect, useState } from 'react';
import { Columns, User, DollarSign, Layers, ChevronRight, Hash } from 'lucide-react';
import { API_BASE_URL } from '../config';

export default function KanbanBoard({ filters, onSelectDonor, activeCompany = 'rethink' }) {
  const [kanbanData, setKanbanData] = useState({});
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
    }

    fetch(`${API_BASE_URL}/api/donors/kanban?${params.toString()}`)
      .then(res => res.json())
      .then(data => {
        setKanbanData(data);
        setLoading(false);
      })
      .catch(err => {
        console.error('Error fetching Kanban pipeline:', err);
        setLoading(false);
      });
  }, [filters, activeCompany]);

  const tierColors = {
    'Super High': 'border-pink-500/50 bg-pink-500/10 text-pink-400',
    'High': 'border-amber-500/50 bg-amber-500/10 text-amber-400',
    'Medium': 'border-emerald-500/50 bg-emerald-500/10 text-emerald-400',
    'Medium Low': 'border-cyan-500/50 bg-cyan-500/10 text-cyan-400',
    'Low End': 'border-slate-500/50 bg-slate-500/10 text-slate-400'
  };

  const columns = ['Super High', 'High', 'Medium', 'Medium Low', 'Low End'];

  return (
    <div className="flex flex-col gap-6">
      {/* Kanban Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-extrabold flex items-center gap-2" style={{ color: 'var(--text-main)' }}>
            <Columns className="w-5 h-5 text-cyan-400" /> Donor Segmentation Kanban Pipeline
          </h2>
          <p className="text-xs" style={{ color: 'var(--text-sub)' }}>Visual pipeline of donors organized by Lifetime Value (LTV) segments with column total sum amounts.</p>
        </div>
      </div>

      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-5 gap-4 animate-pulse">
          {columns.map(tier => (
            <div key={tier} className="glass-panel p-4 min-w-[310px] h-[520px] flex flex-col gap-3">
              <div className="h-8 w-28 rounded-full bg-slate-700/40" />
              <div className="h-5 w-36 rounded-full bg-slate-700/30" />
              <div className="space-y-3 pt-2">
                <div className="h-20 rounded-xl bg-slate-700/25" />
                <div className="h-20 rounded-xl bg-slate-700/25" />
                <div className="h-20 rounded-xl bg-slate-700/25" />
              </div>
            </div>
          ))}
        </div>
      ) : (
        /* Non-Overlapping Horizontal Column Container */
        <div className="flex gap-4 overflow-x-auto pb-6 w-full min-h-[640px]">
          {columns.map(tier => {
            const col = kanbanData[tier] || { total_donors: 0, total_sum_amount: 0.0, cards: [] };
            const badgeClass = tierColors[tier] || 'border-slate-500 bg-slate-500/10 text-slate-400';

            return (
              <div key={tier} className="glass-panel p-4 flex flex-col gap-3 min-w-[310px] w-[310px] shrink-0 border rounded-2xl shadow-xl" style={{ borderColor: 'var(--border-glass)' }}>
                {/* Column Header with TOTAL SUM AMOUNT */}
                <div className="flex flex-col gap-1 pb-3" style={{ borderBottom: '1px solid var(--border-glass)' }}>
                  <div className="flex items-center justify-between">
                    <span className={`text-[10px] font-extrabold px-3 py-1 rounded-full border ${badgeClass}`}>
                      {tier}
                    </span>
                    <span className="text-xs font-bold px-2.5 py-0.5 rounded-md border" style={{ color: 'var(--text-sub)', backgroundColor: 'var(--bg-card-inner)', borderColor: 'var(--border-glass)' }}>
                      {col.total_donors} donors
                    </span>
                  </div>

                  {/* COLUMN TOTAL SUM AMOUNT (£) */}
                  <div className="flex items-center justify-between mt-1 text-xs">
                    <span className="font-semibold" style={{ color: 'var(--text-sub)' }}>Column Total:</span>
                    <span className="font-black text-cyan-400 text-sm">
                      £{col.total_sum_amount?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </span>
                  </div>
                </div>

                {/* Cards Container */}
                <div className="flex flex-col gap-3 max-h-[600px] overflow-y-auto pr-1">
                  {col.cards.length === 0 ? (
                    <div className="py-12 text-center text-xs text-slate-500 italic">No donors match applied filters</div>
                  ) : (
                    col.cards.map((card, idx) => (
                      <button 
                        key={idx}
                        type="button"
                        onClick={() => onSelectDonor(card.email || card.name)}
                        className="glass-panel p-3.5 cursor-pointer transition-all group flex flex-col gap-2 border rounded-xl text-left"
                        style={{ borderColor: 'var(--border-glass)' }}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div className="flex items-center gap-2.5 min-w-0">
                            <div className="w-8 h-8 rounded-lg flex items-center justify-center text-cyan-400 text-xs font-bold shrink-0 border" style={{ backgroundColor: 'var(--input-bg)', borderColor: 'var(--border-glass)' }}>
                              <User className="w-4 h-4" />
                            </div>
                            <div className="truncate min-w-0">
                              <div className="text-xs font-extrabold group-hover:text-cyan-400 transition-colors truncate" style={{ color: 'var(--text-main)' }}>
                                {card.name || 'Anonymous Donor'}
                              </div>
                              <div className="text-[10px] truncate" style={{ color: 'var(--text-sub)' }}>{card.email}</div>
                            </div>
                          </div>

                          <ChevronRight className="w-4 h-4 group-hover:text-cyan-400 transition-colors shrink-0 mt-1" style={{ color: 'var(--text-sub)' }} />
                        </div>

                        <div className="pt-2 flex items-center justify-between text-[11px]" style={{ borderTop: '1px solid var(--border-glass)' }}>
                          <span className="font-medium" style={{ color: 'var(--text-sub)' }}>{card.donation_count} txns</span>
                          <span className="font-black text-cyan-400">£{card.total_ltv?.toLocaleString(undefined, { minimumFractionDigits: 2 })}</span>
                        </div>
                      </button>
                    ))
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
