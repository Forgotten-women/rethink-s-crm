import React, { useEffect, useState } from 'react';
import { Columns, User, ChevronRight, ChevronLeft, Download } from 'lucide-react';
import { API_BASE_URL, downloadFile } from '../config';
import { can } from '../access';

const TIERS = ['Super High', 'High', 'Medium', 'Medium Low', 'Low End'];

const tierColors = {
  'Super High': 'border-pink-500/50 bg-pink-500/10 text-pink-400',
  'High': 'border-amber-500/50 bg-amber-500/10 text-amber-400',
  'Medium': 'border-emerald-500/50 bg-emerald-500/10 text-emerald-400',
  'Medium Low': 'border-cyan-500/50 bg-cyan-500/10 text-cyan-400',
  'Low End': 'border-slate-500/50 bg-slate-500/10 text-slate-400'
};

const activeTabColors = {
  'Super High': 'border-pink-500 text-pink-400',
  'High': 'border-amber-500 text-amber-400',
  'Medium': 'border-emerald-500 text-emerald-400',
  'Medium Low': 'border-cyan-500 text-cyan-400',
  'Low End': 'border-slate-400 text-slate-300'
};

function buildFilterParams(filters, activeCompany) {
  const params = new URLSearchParams();
  params.append('company_id', activeCompany);
  if (filters) {
    ['payment_type', 'tier', 'source', 'heading', 'subheading', 'country', 'code', 'zakat',
      'donor_country', 'campaign_search', 'gift_aid', 'programme_fund', 'special_case',
      'start_date', 'end_date'
    ].forEach(k => { if (filters[k]) params.append(k, filters[k]); });
  }
  return params;
}

export default function KanbanBoard({ filters, onSelectDonor, activeCompany = 'rethink', user }) {
  const [kanbanData, setKanbanData] = useState({});
  const [loading, setLoading] = useState(true);
  const [activeTier, setActiveTier] = useState('Super High');
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 10;

  const canExport = can(user, 'dashboard.export', activeCompany) && can(user, 'donors.contact', activeCompany);

  useEffect(() => { setPage(1); }, [filters, activeCompany, activeTier]);

  useEffect(() => {
    setLoading(true);
    const params = buildFilterParams(filters, activeCompany);
    params.append('board_tier', activeTier);
    params.append('page', String(page));
    params.append('page_size', String(PAGE_SIZE));

    fetch(`${API_BASE_URL}/api/donors/kanban?${params.toString()}`)
      .then(res => res.json())
      .then(data => {
        setKanbanData(data || {});
        setLoading(false);
      })
      .catch(err => {
        console.error('Error fetching Kanban pipeline:', err);
        setLoading(false);
      });
  }, [filters, activeCompany, activeTier, page]);

  const exportTier = () => {
    const params = buildFilterParams(filters, activeCompany);
    params.append('board_tier', activeTier);
    downloadFile(`${API_BASE_URL}/api/donors/kanban/export?${params.toString()}`,
      `pipeline_${activeTier.toLowerCase().replace(/\s+/g, '_')}.csv`);
  };

  const col = kanbanData[activeTier] || { total_donors: 0, total_sum_amount: 0.0, cards: [], page: 1, total_pages: 1 };
  const badgeClass = tierColors[activeTier] || 'border-slate-500 bg-slate-500/10 text-slate-400';
  const totalPages = col.total_pages || 1;
  const curPage = col.page || page;

  return (
    <div className="flex flex-col gap-6">
      {/* Kanban Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-extrabold flex items-center gap-2" style={{ color: 'var(--text-main)' }}>
            <Columns className="w-5 h-5 text-cyan-400" /> Donor Segmentation Kanban Pipeline
          </h2>
          <p className="text-xs" style={{ color: 'var(--text-sub)' }}>Pick a Lifetime Value (LTV) segment tab to see its donors; every donor is reachable through the pages below.</p>
        </div>
        {canExport && (
          <button type="button" onClick={exportTier}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg border text-xs font-bold transition-colors hover:border-cyan-400 hover:text-cyan-400"
            style={{ color: 'var(--text-sub)', borderColor: 'var(--border-glass)' }}>
            <Download className="w-3.5 h-3.5" /> Download {activeTier} CSV
          </button>
        )}
      </div>

      {/* Tier Tabs */}
      <div className="flex gap-1 overflow-x-auto border-b" style={{ borderColor: 'var(--border-glass)' }}>
        {TIERS.map(tier => {
          const t = kanbanData[tier];
          const isActive = tier === activeTier;
          return (
            <button key={tier} type="button" onClick={() => setActiveTier(tier)}
              className={`flex items-center gap-2 px-4 py-2.5 text-xs font-extrabold whitespace-nowrap border-b-2 -mb-px transition-colors ${isActive ? activeTabColors[tier] : 'border-transparent hover:text-cyan-400'}`}
              style={isActive ? {} : { color: 'var(--text-sub)' }}>
              {tier}
              <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-md border" style={{ backgroundColor: 'var(--bg-card-inner)', borderColor: 'var(--border-glass)', color: 'var(--text-sub)' }}>
                {t ? Number(t.total_donors).toLocaleString() : '…'}
              </span>
            </button>
          );
        })}
      </div>

      {loading ? (
        <div className="glass-panel p-4 min-h-[420px] flex flex-col gap-3 animate-pulse rounded-2xl">
          <div className="h-8 w-40 rounded-full bg-slate-700/40" />
          <div className="space-y-3 pt-2">
            <div className="h-16 rounded-xl bg-slate-700/25" />
            <div className="h-16 rounded-xl bg-slate-700/25" />
            <div className="h-16 rounded-xl bg-slate-700/25" />
          </div>
        </div>
      ) : (
        <div className="glass-panel p-5 flex flex-col gap-4 border rounded-2xl shadow-xl" style={{ borderColor: 'var(--border-glass)' }}>
          {/* Tier summary */}
          <div className="flex flex-wrap items-center justify-between gap-3 pb-3" style={{ borderBottom: '1px solid var(--border-glass)' }}>
            <div className="flex items-center gap-3">
              <span className={`text-[10px] font-extrabold px-3 py-1 rounded-full border ${badgeClass}`}>{activeTier}</span>
              <span className="text-xs font-bold" style={{ color: 'var(--text-sub)' }}>
                {Number(col.total_donors).toLocaleString()} donors · {Number(col.total_gifts || 0).toLocaleString()} gifts
              </span>
            </div>
            <div className="flex items-center gap-2 text-xs">
              <span className="font-semibold" style={{ color: 'var(--text-sub)' }}>Segment Total:</span>
              <span className="font-black text-cyan-400 text-sm">
                £{col.total_sum_amount?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </span>
            </div>
          </div>

          {/* Donor cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {col.cards.length === 0 ? (
              <div className="py-12 col-span-full text-center text-xs text-slate-500 italic">No donors match applied filters</div>
            ) : (
              col.cards.map((card, idx) => (
                <button
                  key={idx}
                  type="button"
                  onClick={() => onSelectDonor({ donor_id: card.donor_id || card.email || card.name, email: card.email, name: card.name })}
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
                        {card.email && (
                          <div className="text-[10px] truncate" style={{ color: 'var(--text-sub)' }}>{card.email}</div>
                        )}
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

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-1 pt-2" style={{ borderTop: '1px solid var(--border-glass)' }}>
              <button type="button" disabled={curPage <= 1} onClick={() => setPage(curPage - 1)}
                className="p-1.5 rounded-md border disabled:opacity-40 hover:border-cyan-400" style={{ borderColor: 'var(--border-glass)', color: 'var(--text-sub)' }}>
                <ChevronLeft className="w-3.5 h-3.5" />
              </button>
              {(() => {
                const btns = [];
                for (let p = 1; p <= totalPages; p++) {
                  if (p === 1 || p === totalPages || Math.abs(p - curPage) <= 1) btns.push(p);
                  else if (btns[btns.length - 1] !== '…') btns.push('…');
                }
                return btns.map((p, i) => p === '…' ? (
                  <span key={`e${i}`} className="px-1.5 text-xs" style={{ color: 'var(--text-sub)' }}>…</span>
                ) : (
                  <button key={p} type="button" onClick={() => setPage(p)}
                    className={`min-w-[28px] px-2 py-1 rounded-md text-xs font-bold border ${p === curPage ? 'bg-cyan-500 text-white border-cyan-500' : 'hover:border-cyan-400'}`}
                    style={p === curPage ? {} : { borderColor: 'var(--border-glass)', color: 'var(--text-sub)' }}>
                    {p}
                  </button>
                ));
              })()}
              <button type="button" disabled={curPage >= totalPages} onClick={() => setPage(curPage + 1)}
                className="p-1.5 rounded-md border disabled:opacity-40 hover:border-cyan-400" style={{ borderColor: 'var(--border-glass)', color: 'var(--text-sub)' }}>
                <ChevronRight className="w-3.5 h-3.5" />
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
