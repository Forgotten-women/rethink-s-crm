import React, { useEffect, useState, useRef } from 'react';
import { ChevronDown, RotateCcw, Search, Filter, Calendar } from 'lucide-react';
import { API_BASE_URL } from '../config';

export default function HorizontalFilters({ filters, onFilterChange, onResetFilters, accentColor = 'cyan', activeCompany = 'rethink' }) {
  const [filterOptions, setFilterOptions] = useState({
    sources: [],
    programme_funds: [],
    headings: [],
    subheadings: [],
    countries: [],
    codes: [],
    zakat_statuses: ['Zakat', 'Zakat Eligible', 'Non-Zakat', 'Unassigned'],
    donor_countries: [],
    gift_aid_options: ['All Gift Aid Status', 'Yes', 'No']
  });

  const [activeDropdown, setActiveDropdown] = useState(null); // 'payment', 'tier', 'source', 'programme_fund', 'heading', 'subheading', 'more'
  const dropdownRef = useRef(null);

  // Fetch options dynamically based on current filters
  useEffect(() => {
    const params = new URLSearchParams();
    params.append('company_id', activeCompany);

    if (filters) {
      if (filters.payment_type) params.append('payment_type', filters.payment_type);
      if (filters.tier) params.append('tier', filters.tier);
      if (filters.source) params.append('source', filters.source);
      if (filters.programme_fund) params.append('programme_fund', filters.programme_fund);
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
      .then(data => {
        setFilterOptions(prev => ({
          ...data,
          zakat_statuses: data.zakat_statuses && data.zakat_statuses.length > 0 
            ? data.zakat_statuses 
            : ['Zakat', 'Zakat Eligible', 'Non-Zakat', 'Unassigned'],
          gift_aid_options: data.gift_aid_options && data.gift_aid_options.length > 0 
            ? data.gift_aid_options 
            : ['All Gift Aid Status', 'Yes', 'No']
        }));
      })
      .catch(err => console.error('Error loading filter options:', err));
  }, [filters, activeCompany]);

  // Close dropdown when clicking outside
  useEffect(() => {
    function handleClickOutside(event) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setActiveDropdown(null);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const accentColorClasses = {
    cyan: 'text-cyan-500 bg-cyan-500/10 border-cyan-500/20 focus:ring-cyan-500/20',
    emerald: 'text-emerald-500 bg-emerald-500/10 border-emerald-500/20 focus:ring-emerald-500/20',
    purple: 'text-purple-500 bg-purple-500/10 border-purple-500/20 focus:ring-purple-500/20',
    rose: 'text-rose-500 bg-rose-500/10 border-rose-500/20 focus:ring-rose-500/20'
  };
  const actClass = accentColorClasses[accentColor] || accentColorClasses.cyan;

  const toggleDropdown = (name) => {
    setActiveDropdown(activeDropdown === name ? null : name);
  };

  const handleSelect = (key, value) => {
    onFilterChange(key, value);
    setActiveDropdown(null);
  };

  // Check if any secondary filter inside "More Filters" is active
  const isMoreActive = 
    (filters.country && filters.country !== 'All Project Countries') ||
    (filters.code && filters.code !== 'All Codes') ||
    (filters.zakat && filters.zakat !== 'All Zakat Status') ||
    (filters.donor_country && filters.donor_country !== 'All Donor Countries') ||
    (filters.gift_aid && filters.gift_aid !== 'All Gift Aid Status') ||
    filters.start_date ||
    filters.end_date;

  return (
    <div className="w-full bg-white dark:bg-slate-900 border border-slate-200 dark:border-white/5 rounded-2xl p-4 shadow-[0_2px_10px_-3px_rgba(6,81,237,0.05)] flex flex-col md:flex-row items-center justify-between gap-4 z-30 relative" ref={dropdownRef}>
      
      {/* Pills Container */}
      <div className="flex flex-wrap items-center gap-2.5 w-full md:w-auto">
        
        {/* Search Pill */}
        <div className="relative flex items-center bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-white/10 rounded-xl px-3 py-1.5 focus-within:ring-2 focus-within:ring-slate-200 dark:focus-within:ring-slate-800 transition-all w-full sm:w-60">
          <Search className="w-3.5 h-3.5 text-slate-400 mr-2 shrink-0" />
          <input
            type="text"
            placeholder="Search campaigns..."
            value={filters.campaign_search || ''}
            onChange={(e) => onFilterChange('campaign_search', e.target.value)}
            className="bg-transparent border-none outline-none text-xs text-slate-800 dark:text-slate-100 placeholder-slate-400 dark:placeholder-slate-500 w-full"
          />
        </div>

        {/* Payment Type Pill */}
        <div className="relative">
          <button
            onClick={() => toggleDropdown('payment')}
            className={`flex items-center gap-1.5 px-3 py-2 rounded-xl border text-xs font-semibold transition-all hover:bg-slate-50 dark:hover:bg-slate-800/50 ${
              filters.payment_type !== 'All Payment Types'
                ? `${actClass} font-bold`
                : 'bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-300 border-slate-200 dark:border-white/10'
            }`}
          >
            <span>Payment: {filters.payment_type === 'All Payment Types' ? 'All' : filters.payment_type}</span>
            <ChevronDown className="w-3 h-3 opacity-60" />
          </button>
          
          {activeDropdown === 'payment' && (
            <div className="absolute left-0 mt-2 w-52 bg-white dark:bg-slate-950 border border-slate-200 dark:border-white/10 rounded-xl shadow-xl z-50 py-1.5 animate-in fade-in slide-in-from-top-1 duration-150">
              {['All Payment Types', 'One-time', 'Recurring'].map(opt => (
                <button
                  key={opt}
                  onClick={() => handleSelect('payment_type', opt)}
                  className={`w-full text-left px-4 py-2 text-xs font-semibold hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors ${
                    filters.payment_type === opt ? 'text-cyan-500 font-bold' : 'text-slate-700 dark:text-slate-300'
                  }`}
                >
                  {opt}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Tier Pill */}
        <div className="relative">
          <button
            onClick={() => toggleDropdown('tier')}
            className={`flex items-center gap-1.5 px-3 py-2 rounded-xl border text-xs font-semibold transition-all hover:bg-slate-50 dark:hover:bg-slate-800/50 ${
              filters.tier !== 'All Classifications'
                ? `${actClass} font-bold`
                : 'bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-300 border-slate-200 dark:border-white/10'
            }`}
          >
            <span>Tier: {filters.tier === 'All Classifications' ? 'All' : filters.tier}</span>
            <ChevronDown className="w-3 h-3 opacity-60" />
          </button>
          
          {activeDropdown === 'tier' && (
            <div className="absolute left-0 mt-2 w-52 bg-white dark:bg-slate-950 border border-slate-200 dark:border-white/10 rounded-xl shadow-xl z-50 py-1.5 animate-in fade-in slide-in-from-top-1 duration-150 max-h-60 overflow-y-auto custom-scrollbar">
              {['All Classifications', 'Super High', 'High', 'Medium', 'Medium Low', 'Low End'].map(opt => (
                <button
                  key={opt}
                  onClick={() => handleSelect('tier', opt)}
                  className={`w-full text-left px-4 py-2 text-xs font-semibold hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors ${
                    filters.tier === opt ? 'text-cyan-500 font-bold' : 'text-slate-700 dark:text-slate-300'
                  }`}
                >
                  {opt}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Source Pill */}
        <div className="relative">
          <button
            onClick={() => toggleDropdown('source')}
            className={`flex items-center gap-1.5 px-3 py-2 rounded-xl border text-xs font-semibold transition-all hover:bg-slate-50 dark:hover:bg-slate-800/50 ${
              filters.source !== 'All Sources (Combined)'
                ? `${actClass} font-bold`
                : 'bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-300 border-slate-200 dark:border-white/10'
            }`}
          >
            <span>Source: {filters.source === 'All Sources (Combined)' ? 'All' : filters.source.split(',').length + ' selected'}</span>
            <ChevronDown className="w-3 h-3 opacity-60" />
          </button>
          
          {activeDropdown === 'source' && (
            <div className="absolute left-0 mt-2 w-56 bg-white dark:bg-slate-950 border border-slate-200 dark:border-white/10 rounded-xl shadow-xl z-50 py-2 animate-in fade-in slide-in-from-top-1 duration-150 max-h-60 overflow-y-auto custom-scrollbar">
              <button
                onClick={() => handleSelect('source', 'All Sources (Combined)')}
                className={`w-full text-left px-4 py-2 text-xs font-bold hover:bg-slate-50 dark:hover:bg-slate-800 border-b border-slate-100 dark:border-white/5 pb-2 text-slate-700 dark:text-slate-300`}
              >
                Clear / All Sources
              </button>
              {filterOptions.sources.map(src => {
                const isSel = filters.source !== 'All Sources (Combined)' && filters.source.split(',').includes(src);
                return (
                  <button
                    key={src}
                    onClick={() => {
                      let selected = filters.source === 'All Sources (Combined)' ? [] : filters.source.split(',');
                      if (selected.includes(src)) {
                        selected = selected.filter(s => s !== src);
                      } else {
                        selected.push(src);
                      }
                      onFilterChange('source', selected.length === 0 ? 'All Sources (Combined)' : selected.join(','));
                    }}
                    className={`w-full text-left px-4 py-2 text-xs font-semibold hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors flex items-center justify-between ${
                      isSel ? 'text-cyan-500 font-bold' : 'text-slate-700 dark:text-slate-300'
                    }`}
                  >
                    <span>{src}</span>
                    {isSel && <span className="w-1.5 h-1.5 rounded-full bg-cyan-500" />}
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {/* Programme Fund Pill */}
        <div className="relative">
          <button
            onClick={() => toggleDropdown('programme_fund')}
            className={`flex items-center gap-1.5 px-3 py-2 rounded-xl border text-xs font-semibold transition-all hover:bg-slate-50 dark:hover:bg-slate-800/50 ${
              filters.programme_fund && filters.programme_fund !== 'All Programme Funds'
                ? `${actClass} font-bold`
                : 'bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-300 border-slate-200 dark:border-white/10'
            }`}
          >
            <span>Fund: {!filters.programme_fund || filters.programme_fund === 'All Programme Funds' ? 'All' : filters.programme_fund}</span>
            <ChevronDown className="w-3 h-3 opacity-60" />
          </button>
          
          {activeDropdown === 'programme_fund' && (
            <div className="absolute left-0 mt-2 w-64 bg-white dark:bg-slate-950 border border-slate-200 dark:border-white/10 rounded-xl shadow-xl z-50 py-1.5 animate-in fade-in slide-in-from-top-1 duration-150 max-h-60 overflow-y-auto custom-scrollbar">
              <button
                onClick={() => handleSelect('programme_fund', 'All Programme Funds')}
                className={`w-full text-left px-4 py-2 text-xs hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors ${
                  !filters.programme_fund || filters.programme_fund === 'All Programme Funds' ? 'text-cyan-500 font-bold' : 'text-slate-700 dark:text-slate-300'
                }`}
              >
                All Programme Funds
              </button>
              {(filterOptions.programme_funds || []).map(opt => (
                <button
                  key={opt}
                  onClick={() => handleSelect('programme_fund', opt)}
                  className={`w-full text-left px-4 py-2 text-xs hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors ${
                    filters.programme_fund === opt ? 'text-cyan-500 font-bold' : 'text-slate-700 dark:text-slate-300'
                  }`}
                >
                  {opt}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Department Pill */}
        <div className="relative">
          <button
            onClick={() => toggleDropdown('heading')}
            className={`flex items-center gap-1.5 px-3 py-2 rounded-xl border text-xs font-semibold transition-all hover:bg-slate-50 dark:hover:bg-slate-800/50 ${
              filters.heading !== 'All Headings'
                ? `${actClass} font-bold`
                : 'bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-300 border-slate-200 dark:border-white/10'
            }`}
          >
            <span>Department: {filters.heading === 'All Headings' ? 'All' : filters.heading}</span>
            <ChevronDown className="w-3 h-3 opacity-60" />
          </button>
          
          {activeDropdown === 'heading' && (
            <div className="absolute left-0 mt-2 w-64 bg-white dark:bg-slate-950 border border-slate-200 dark:border-white/10 rounded-xl shadow-xl z-50 py-1.5 animate-in fade-in slide-in-from-top-1 duration-150 max-h-60 overflow-y-auto custom-scrollbar">
              <button
                onClick={() => handleSelect('heading', 'All Headings')}
                className={`w-full text-left px-4 py-2 text-xs hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors ${
                  filters.heading === 'All Headings' ? 'text-cyan-500 font-bold' : 'text-slate-700 dark:text-slate-300'
                }`}
              >
                All Departments
              </button>
              {filterOptions.headings.map(opt => (
                <button
                  key={opt}
                  onClick={() => handleSelect('heading', opt)}
                  className={`w-full text-left px-4 py-2 text-xs hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors ${
                    filters.heading === opt ? 'text-cyan-500 font-bold' : 'text-slate-700 dark:text-slate-300'
                  }`}
                >
                  {opt}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Office Pill */}
        <div className="relative">
          <button
            onClick={() => toggleDropdown('subheading')}
            className={`flex items-center gap-1.5 px-3 py-2 rounded-xl border text-xs font-semibold transition-all hover:bg-slate-50 dark:hover:bg-slate-800/50 ${
              filters.subheading && filters.subheading !== 'All Sub-Headings'
                ? `${actClass} font-bold`
                : 'bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-300 border-slate-200 dark:border-white/10'
            }`}
          >
            <span>Office: {!filters.subheading || filters.subheading === 'All Sub-Headings' ? 'All' : filters.subheading}</span>
            <ChevronDown className="w-3 h-3 opacity-60" />
          </button>
          
          {activeDropdown === 'subheading' && (
            <div className="absolute left-0 mt-2 w-64 bg-white dark:bg-slate-950 border border-slate-200 dark:border-white/10 rounded-xl shadow-xl z-50 py-1.5 animate-in fade-in slide-in-from-top-1 duration-150 max-h-60 overflow-y-auto custom-scrollbar">
              <button
                onClick={() => handleSelect('subheading', 'All Sub-Headings')}
                className={`w-full text-left px-4 py-2 text-xs hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors ${
                  !filters.subheading || filters.subheading === 'All Sub-Headings' ? 'text-cyan-500 font-bold' : 'text-slate-700 dark:text-slate-300'
                }`}
              >
                All Offices
              </button>
              {filterOptions.subheadings.map(opt => (
                <button
                  key={opt}
                  onClick={() => handleSelect('subheading', opt)}
                  className={`w-full text-left px-4 py-2 text-xs hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors ${
                    filters.subheading === opt ? 'text-cyan-500 font-bold' : 'text-slate-700 dark:text-slate-300'
                  }`}
                >
                  {opt}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* More Filters Pill */}
        <div className="relative">
          <button
            onClick={() => toggleDropdown('more')}
            className={`flex items-center gap-1.5 px-3 py-2 rounded-xl border text-xs font-semibold transition-all hover:bg-slate-50 dark:hover:bg-slate-800/50 ${
              isMoreActive
                ? `${actClass} font-bold`
                : 'bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-300 border-slate-200 dark:border-white/10'
            }`}
          >
            <Filter className="w-3.5 h-3.5 opacity-80" />
            <span>More Filters</span>
            <ChevronDown className="w-3 h-3 opacity-60" />
          </button>
          
          {activeDropdown === 'more' && (
            <div className="absolute left-0 mt-2 w-72 bg-white dark:bg-slate-950 border border-slate-200 dark:border-white/10 rounded-xl shadow-xl z-50 p-4 animate-in fade-in slide-in-from-top-1 duration-150 flex flex-col gap-3.5 max-h-[450px] overflow-y-auto custom-scrollbar">
              
              {/* Project Country */}
              <div className="flex flex-col gap-1 text-left">
                <span className="text-[9px] font-black uppercase text-slate-400 tracking-wider">Project Country</span>
                <select
                  value={filters.country}
                  onChange={(e) => onFilterChange('country', e.target.value)}
                  className="w-full text-xs font-semibold p-2 rounded-lg bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-white/5 outline-none text-slate-800 dark:text-slate-100"
                >
                  <option value="All Project Countries">All Project Countries</option>
                  {filterOptions.countries.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>

              {/* Master Link Code */}
              <div className="flex flex-col gap-1 text-left">
                <span className="text-[9px] font-black uppercase text-slate-400 tracking-wider">Master Link Code</span>
                <select
                  value={filters.code}
                  onChange={(e) => onFilterChange('code', e.target.value)}
                  className="w-full text-xs font-semibold p-2 rounded-lg bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-white/5 outline-none text-slate-800 dark:text-slate-100"
                >
                  <option value="All Codes">All Codes</option>
                  {filterOptions.codes.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>

              {/* Zakat Eligibility */}
              <div className="flex flex-col gap-1 text-left">
                <span className="text-[9px] font-black uppercase text-slate-400 tracking-wider">Zakat Status</span>
                <select
                  value={filters.zakat}
                  onChange={(e) => onFilterChange('zakat', e.target.value)}
                  className="w-full text-xs font-semibold p-2 rounded-lg bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-white/5 outline-none text-slate-800 dark:text-slate-100"
                >
                  <option value="All Zakat Status">All Zakat Status</option>
                  {filterOptions.zakat_statuses.map(z => <option key={z} value={z}>{z}</option>)}
                </select>
              </div>

              {/* Gift Aid */}
              <div className="flex flex-col gap-1 text-left">
                <span className="text-[9px] font-black uppercase text-slate-400 tracking-wider">Gift Aid Status</span>
                <select
                  value={filters.gift_aid}
                  onChange={(e) => onFilterChange('gift_aid', e.target.value)}
                  className="w-full text-xs font-semibold p-2 rounded-lg bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-white/5 outline-none text-slate-800 dark:text-slate-100"
                >
                  {filterOptions.gift_aid_options.map(g => <option key={g} value={g}>{g}</option>)}
                </select>
              </div>

              {/* Start Date */}
              <div className="flex flex-col gap-1 text-left">
                <span className="text-[9px] font-black uppercase text-slate-400 tracking-wider">Start Date</span>
                <input
                  type="date"
                  value={filters.start_date || ''}
                  onChange={(e) => onFilterChange('start_date', e.target.value)}
                  className="w-full text-xs font-semibold p-2 rounded-lg bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-white/5 outline-none text-slate-800 dark:text-slate-100"
                />
              </div>

              {/* End Date */}
              <div className="flex flex-col gap-1 text-left">
                <span className="text-[9px] font-black uppercase text-slate-400 tracking-wider">End Date</span>
                <input
                  type="date"
                  value={filters.end_date || ''}
                  onChange={(e) => onFilterChange('end_date', e.target.value)}
                  className="w-full text-xs font-semibold p-2 rounded-lg bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-white/5 outline-none text-slate-800 dark:text-slate-100"
                />
              </div>

            </div>
          )}
        </div>

      </div>

      {/* Reset Controls Button */}
      <button 
        onClick={onResetFilters}
        title="Reset All Active Filters"
        className="btn-secondary text-[11px] px-3.5 py-2 rounded-xl flex items-center gap-1.5 text-cyan-500 border-cyan-500/20 hover:bg-cyan-500/10 font-bold shrink-0 self-stretch sm:self-auto justify-center"
      >
        <RotateCcw className="w-3.5 h-3.5" />
        <span>Reset Filters</span>
      </button>

    </div>
  );
}
