import React, { useEffect, useState } from 'react';
import { Filter, RotateCcw, CreditCard, Crown, Tag, Globe, Folder, ChevronDown, Check, CheckSquare, Square, Shield, Search, Gift, Calendar } from 'lucide-react';
import { API_BASE_URL } from '../config';

export default function Sidebar({ filters, onFilterChange, onResetFilters }) {
  const [filterOptions, setFilterOptions] = useState({
    sources: [],
    headings: [],
    subheadings: [],
    countries: [],
    codes: [],
    zakat_statuses: ['Zakat', 'Zakat Eligible', 'Non-Zakat', 'Unassigned'],
    donor_countries: [],
    gift_aid_options: ['All Gift Aid Status', 'Yes', 'No']
  });

  const [showSourceDropdown, setShowSourceDropdown] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams();
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

    fetch(`${API_BASE_URL}/api/filters/options?${params.toString()}`)
      .then(res => res.json())
      .then(data => setFilterOptions(data))
      .catch(err => console.error('Error loading filter options:', err));
  }, [filters]);

  const selectedSources = filters?.source && filters.source !== 'All Sources (Combined)'
    ? String(filters.source).split(',').map(s => s.trim())
    : [];

  const activeFilterSummary = [
    filters.payment_type && filters.payment_type !== 'All Payment Types' ? { label: 'Payment', value: filters.payment_type } : null,
    filters.tier && filters.tier !== 'All Classifications' ? { label: 'Tier', value: filters.tier } : null,
    filters.source && filters.source !== 'All Sources (Combined)' ? { label: 'Source', value: selectedSources.length > 0 ? `${selectedSources.length} selected` : filters.source } : null,
    filters.heading && filters.heading !== 'All Headings' ? { label: 'Heading', value: filters.heading } : null,
    filters.subheading && filters.subheading !== 'All Sub-Headings' ? { label: 'Sub', value: filters.subheading } : null,
    filters.country && filters.country !== 'All Project Countries' ? { label: 'Country', value: filters.country } : null,
    filters.donor_country && filters.donor_country !== 'All Donor Countries' ? { label: 'Donor Country', value: filters.donor_country } : null,
    filters.code && filters.code !== 'All Codes' ? { label: 'Code', value: filters.code } : null,
    filters.zakat && filters.zakat !== 'All Zakat Status' ? { label: 'Zakat', value: filters.zakat } : null,
    filters.campaign_search ? { label: 'Search', value: filters.campaign_search } : null,
    filters.gift_aid && filters.gift_aid !== 'All Gift Aid Status' ? { label: 'Gift Aid', value: filters.gift_aid } : null,
    filters.start_date ? { label: 'Start', value: filters.start_date } : null,
    filters.end_date ? { label: 'End', value: filters.end_date } : null,
  ].filter(Boolean);

  const handleToggleSource = (sourceName) => {
    let current = [...selectedSources];
    if (current.includes(sourceName)) {
      current = current.filter(s => s !== sourceName);
    } else {
      current.push(sourceName);
    }

    if (current.length === 0) {
      onFilterChange('source', 'All Sources (Combined)');
    } else {
      onFilterChange('source', current.join(','));
    }
  };

  const handleSelectAllSources = () => {
    onFilterChange('source', 'All Sources (Combined)');
  };

  return (
    <aside className="glass-panel p-4 flex flex-col gap-4 w-full lg:w-72 shrink-0 rounded-2xl h-fit sticky top-20" aria-label="Global filters">
      <div className="flex items-center justify-between border-b pb-3" style={{ borderColor: 'var(--border-glass)' }}>
        <h3 className="text-xs font-black uppercase tracking-wider flex items-center gap-2" style={{ color: 'var(--text-main)' }}>
          <Filter className="w-4 h-4 text-cyan-400" /> Interactive Filter Controls
        </h3>

        <button 
          onClick={onResetFilters}
          title="Reset All Filters"
          className="btn-secondary text-[11px] px-2.5 py-1 flex items-center gap-1 text-cyan-400 border-cyan-500/30 hover:bg-cyan-500/10"
        >
          <RotateCcw className="w-3 h-3" /> Reset
        </button>
      </div>

      {activeFilterSummary.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {activeFilterSummary.map((item) => (
            <span key={`${item.label}-${item.value}`} className="badge badge-cyan text-[10px] normal-case px-2 py-1" title={item.value}>
              {item.label}: {item.value}
            </span>
          ))}
        </div>
      )}

      <details open className="glass-panel p-3 rounded-2xl" style={{ borderColor: 'var(--border-glass)' }}>
        <summary className="cursor-pointer list-none text-[11px] font-black uppercase tracking-wider flex items-center gap-1.5" style={{ color: 'var(--text-main)' }}>
          <Calendar className="w-3.5 h-3.5 text-orange-400" /> Date Range Filter
        </summary>
        <div className="pt-3 flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <label className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
              Start Date
            </label>
            <input 
              type="date"
              value={filters.start_date || ''}
              onChange={e => onFilterChange('start_date', e.target.value)}
              className="w-full border rounded-xl px-3 py-2 text-xs focus:outline-none focus:border-cyan-500 transition-all"
              style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', borderColor: 'var(--input-border)' }}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <label className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
              End Date
            </label>
            <input 
              type="date"
              value={filters.end_date || ''}
              onChange={e => onFilterChange('end_date', e.target.value)}
              className="w-full border rounded-xl px-3 py-2 text-xs focus:outline-none focus:border-cyan-500 transition-all"
              style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', borderColor: 'var(--input-border)' }}
            />
          </div>
        </div>
      </details>

      <details open className="glass-panel p-3 rounded-2xl" style={{ borderColor: 'var(--border-glass)' }}>
        <summary className="cursor-pointer list-none text-[11px] font-black uppercase tracking-wider flex items-center gap-1.5" style={{ color: 'var(--text-main)' }}>
          <CreditCard className="w-3.5 h-3.5 text-purple-400" /> Payment & Classification
        </summary>
        <div className="pt-3 flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label className="text-[11px] font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
              Payment Frequency
            </label>
            <select 
              value={filters.payment_type || 'All Payment Types'} 
              onChange={e => onFilterChange('payment_type', e.target.value)}
              className="w-full border rounded-xl px-3 py-2 text-xs focus:outline-none focus:border-cyan-500 transition-all cursor-pointer"
              style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', borderColor: 'var(--input-border)' }}
            >
              <option value="All Payment Types">All Payment Types</option>
              <option value="One-Time Payment">One-Time Payment</option>
              <option value="Recurring Payment">Recurring Payment</option>
            </select>
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-[11px] font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
              Lifetime LTV Tier
            </label>
            <select 
              value={filters.tier || 'All Classifications'} 
              onChange={e => onFilterChange('tier', e.target.value)}
              className="w-full border rounded-xl px-3 py-2 text-xs focus:outline-none focus:border-cyan-500 transition-all cursor-pointer"
              style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', borderColor: 'var(--input-border)' }}
            >
              <option value="All Classifications">All Classifications</option>
              <option value="Super High">Super High (&gt; £3,000)</option>
              <option value="High">High (£1,000 - £3,000)</option>
              <option value="Medium">Medium (£600 - £1,000)</option>
              <option value="Medium Low">Medium Low (£200 - £600)</option>
              <option value="Low End">Low End (&lt; £200)</option>
            </select>
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-[11px] font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
              <Shield className="w-3.5 h-3.5 text-emerald-400" /> Filter by Zakat Eligibility
            </label>
            <select 
              value={filters.zakat || 'All Zakat Status'} 
              onChange={e => onFilterChange('zakat', e.target.value)}
              className="w-full border rounded-xl px-3 py-2 text-xs focus:outline-none focus:border-cyan-500 transition-all cursor-pointer"
              style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', borderColor: 'var(--input-border)' }}
            >
              <option value="All Zakat Status">All Zakat Status</option>
              {filterOptions.zakat_statuses?.map((zk, idx) => (
                <option key={idx} value={zk}>{zk}</option>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-[11px] font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
              <Tag className="w-3.5 h-3.5 text-cyan-400" /> Filter by Code
            </label>
            <select 
              value={filters.code || 'All Codes'} 
              onChange={e => onFilterChange('code', e.target.value)}
              className="w-full border rounded-xl px-3 py-2 text-xs font-mono text-cyan-400 focus:outline-none focus:border-cyan-500 transition-all cursor-pointer"
              style={{ backgroundColor: 'var(--input-bg)', borderColor: 'var(--input-border)' }}
            >
              <option value="All Codes">All Codes</option>
              {filterOptions.codes?.map((cd, idx) => (
                <option key={idx} value={cd}>{cd}</option>
              ))}
            </select>
          </div>
        </div>
      </details>

      <details open className="glass-panel p-3 rounded-2xl" style={{ borderColor: 'var(--border-glass)' }}>
        <summary className="cursor-pointer list-none text-[11px] font-black uppercase tracking-wider flex items-center gap-1.5" style={{ color: 'var(--text-main)' }}>
          <Folder className="w-3.5 h-3.5 text-cyan-400" /> Data Source & Categories
        </summary>
        <div className="pt-3 flex flex-col gap-4">
          <div className="flex flex-col gap-1.5 relative">
            <label className="text-[11px] font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
              Filter by Source (Multi-Select)
            </label>

            <button
              type="button"
              onClick={() => setShowSourceDropdown(!showSourceDropdown)}
              className="w-full border rounded-xl px-3 py-2 text-xs flex items-center justify-between transition-all cursor-pointer"
              style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', borderColor: 'var(--input-border)' }}
              aria-expanded={showSourceDropdown}
            >
              <span className="truncate">
                {selectedSources.length === 0 
                  ? 'All Sources (Combined)' 
                  : `${selectedSources.length} Source${selectedSources.length > 1 ? 's' : ''} Selected`}
              </span>
              <ChevronDown className="w-3.5 h-3.5 text-slate-400 shrink-0 ml-1" />
            </button>

            {showSourceDropdown && (
              <div 
                className="absolute top-full left-0 right-0 mt-1 z-30 p-3 border border-cyan-500/40 rounded-xl shadow-2xl flex flex-col gap-2 max-h-60 overflow-y-auto"
                style={{ backgroundColor: 'var(--drawer-bg)' }}
              >
                <button 
                  type="button"
                  onClick={handleSelectAllSources}
                  className={`p-2 rounded-lg border text-xs flex items-center justify-between transition-all text-left ${
                    selectedSources.length === 0 ? 'border-cyan-400/50 bg-cyan-500/10 text-cyan-400 font-bold' : 'border-white/10 hover:bg-cyan-500/5'
                  }`}
                  style={{ color: selectedSources.length === 0 ? '' : 'var(--text-main)' }}
                >
                  <span>All Sources (Combined)</span>
                  {selectedSources.length === 0 && <Check className="w-3.5 h-3.5 text-cyan-400" />}
                </button>

                <div className="border-t border-white/10 pt-1 flex flex-col gap-1">
                  {filterOptions.sources?.map((s, idx) => {
                    const isSelected = selectedSources.includes(s);
                    return (
                      <button 
                        key={idx}
                        type="button"
                        onClick={() => handleToggleSource(s)}
                        className={`p-2 rounded-lg border text-xs flex items-center gap-2 transition-all text-left ${
                          isSelected ? 'border-cyan-400/50 bg-cyan-500/15 text-cyan-400 font-bold' : 'border-white/10 hover:bg-cyan-500/5'
                        }`}
                        style={{ color: isSelected ? '' : 'var(--text-muted)' }}
                      >
                        {isSelected ? <CheckSquare className="w-3.5 h-3.5 text-cyan-400 shrink-0" /> : <Square className="w-3.5 h-3.5 text-slate-400 shrink-0" />}
                        <span className="truncate text-[11px]">{s}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-[11px] font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
              <Tag className="w-3.5 h-3.5 text-emerald-400" /> Category Heading
            </label>
            <select 
              value={filters.heading || 'All Headings'} 
              onChange={e => onFilterChange('heading', e.target.value)}
              className="w-full border rounded-xl px-3 py-2 text-xs focus:outline-none focus:border-cyan-500 transition-all cursor-pointer"
              style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', borderColor: 'var(--input-border)' }}
            >
              <option value="All Headings">All Headings</option>
              {filterOptions.headings?.map((h, idx) => (
                <option key={idx} value={h}>{h}</option>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-[11px] font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
              <Tag className="w-3.5 h-3.5 text-pink-400" /> Sub-Heading
            </label>
            <select 
              value={filters.subheading || 'All Sub-Headings'} 
              onChange={e => onFilterChange('subheading', e.target.value)}
              className="w-full border rounded-xl px-3 py-2 text-xs focus:outline-none focus:border-cyan-500 transition-all cursor-pointer"
              style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', borderColor: 'var(--input-border)' }}
            >
              <option value="All Sub-Headings">All Sub-Headings</option>
              {filterOptions.subheadings?.map((sh, idx) => (
                <option key={idx} value={sh}>{sh}</option>
              ))}
            </select>
          </div>
        </div>
      </details>

      <details open className="glass-panel p-3 rounded-2xl" style={{ borderColor: 'var(--border-glass)' }}>
        <summary className="cursor-pointer list-none text-[11px] font-black uppercase tracking-wider flex items-center gap-1.5" style={{ color: 'var(--text-main)' }}>
          <Globe className="w-3.5 h-3.5 text-cyan-400" /> Location, Search & Gift Aid
        </summary>
        <div className="pt-3 flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label className="text-[11px] font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
              <Globe className="w-3.5 h-3.5 text-cyan-400" /> Project Country
            </label>
            <select 
              value={filters.country || 'All Project Countries'} 
              onChange={e => onFilterChange('country', e.target.value)}
              className="w-full border rounded-xl px-3 py-2 text-xs focus:outline-none focus:border-cyan-500 transition-all cursor-pointer"
              style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', borderColor: 'var(--input-border)' }}
            >
              <option value="All Project Countries">All Project Countries</option>
              {filterOptions.countries?.map((c, idx) => (
                <option key={idx} value={c}>{c}</option>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-[11px] font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
              <Globe className="w-3.5 h-3.5 text-purple-400" /> Donor Billing Country
            </label>
            <select 
              value={filters.donor_country || 'All Donor Countries'} 
              onChange={e => onFilterChange('donor_country', e.target.value)}
              className="w-full border rounded-xl px-3 py-2 text-xs focus:outline-none focus:border-cyan-500 transition-all cursor-pointer"
              style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', borderColor: 'var(--input-border)' }}
            >
              <option value="All Donor Countries">All Donor Countries</option>
              {filterOptions.donor_countries?.map((dc, idx) => (
                <option key={idx} value={dc}>{dc}</option>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-[11px] font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
              <Search className="w-3.5 h-3.5 text-amber-400" /> Search Campaign / Community
            </label>
            <input 
              type="text"
              placeholder="Search campaign or community..."
              value={filters.campaign_search || ''}
              onChange={e => onFilterChange('campaign_search', e.target.value)}
              className="w-full border rounded-xl px-3 py-2 text-xs focus:outline-none focus:border-cyan-500 transition-all"
              style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', borderColor: 'var(--input-border)' }}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-[11px] font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
              <Gift className="w-3.5 h-3.5 text-rose-400" /> Gift Aid (Yes / No)
            </label>
            <select 
              value={filters.gift_aid || 'All Gift Aid Status'} 
              onChange={e => onFilterChange('gift_aid', e.target.value)}
              className="w-full border rounded-xl px-3 py-2 text-xs focus:outline-none focus:border-cyan-500 transition-all cursor-pointer"
              style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', borderColor: 'var(--input-border)' }}
            >
              <option value="All Gift Aid Status">All Gift Aid Status</option>
              <option value="Yes">Yes (Gift Aid Claimed)</option>
              <option value="No">No (Non-Gift Aid)</option>
            </select>
          </div>
        </div>
      </details>
    </aside>
  );
}
