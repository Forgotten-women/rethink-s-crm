import React, { useState, useRef, useEffect, useMemo } from 'react';
import { createPortal } from 'react-dom';
import { Search, ChevronDown, Check, X, Sparkles, Plus, Tag } from 'lucide-react';

export const ALL_SHEET10_SPECIAL_CASES = [
  'Zarang bike',
  'Umm Abdullah',
  'Umm Alaa',
  'Umm Habib',
  'Umm Suleiman',
  'Umm Hamza',
  'Aunt Sahr',
  'Umm Lofti',
  'Umm Muhammad',
  'Umm Saeed',
  'Eid Clothes',
  'Eid Party',
  'LUFS',
  'Most Needy',
  'Qurbani',
  'Tent2Home',
  'Special Case'
];

export function canonicalizeSpecialCase(scStr) {
  if (!scStr) return '';
  const trimmed = String(scStr).trim();
  if (['none', 'none (standard)', 'unassigned', 'nan', 'null', 'n/a', ''].includes(trimmed.toLowerCase())) {
    return '';
  }
  const match = ALL_SHEET10_SPECIAL_CASES.find(c => c.toLowerCase() === trimmed.toLowerCase());
  return match || trimmed;
}

export default function SpecialCaseCombobox({
  value = '',
  onChange,
  code = '',
  codeMap = {},
  allCases = [],
  disabled = false,
  compact = false,
  title = 'Select special case beneficiary or case name'
}) {
  const [isOpen, setIsOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [coords, setCoords] = useState({ top: 0, left: 0, width: 220, placement: 'bottom' });

  const triggerRef = useRef(null);
  const popupRef = useRef(null);
  const searchInputRef = useRef(null);

  const cleanVal = canonicalizeSpecialCase(value);

  // Compute recommended cases for current code
  const recommendedCases = useMemo(() => {
    const cLower = String(code || '').trim().toLowerCase();
    const mapped = codeMap[cLower];
    let list = [];
    if (mapped && Array.isArray(mapped['Special Cases']) && mapped['Special Cases'].length > 0) {
      list = mapped['Special Cases'].map(canonicalizeSpecialCase);
    } else if (mapped && (mapped['Special Case'] || mapped['Special Treatment'])) {
      list = [canonicalizeSpecialCase(mapped['Special Case'] || mapped['Special Treatment'])];
    } else if (cLower === 'afg-soc-aid-gen') {
      list = ['Zarang bike'];
    } else if (cLower === 'shm-soc-aid-gen') {
      list = ['Aunt Sahr', 'Umm Abdullah', 'Umm Alaa', 'Umm Habib', 'Umm Hamza', 'Umm Lofti', 'Umm Muhammad', 'Umm Saeed', 'Umm Suleiman'];
    } else if (cLower === 'shm-soc-aid-luf') {
      list = ['LUFS'];
    } else if (cLower === 'shm-soc-aid-t2h') {
      list = ['Tent2Home'];
    } else if (cLower === 'shm-soc-aid-ecl') {
      list = ['Eid Clothes'];
    } else if (cLower === 'shm-soc-aid-eid') {
      list = ['Eid Party'];
    } else if (cLower === 'shm-soc-aid-mne') {
      list = ['Most Needy'];
    } else if (cLower === 'shm-soc-aid-qur') {
      list = ['Qurbani'];
    } else if (cLower === 'shm-soc-aid-spc' || cLower === 'tur-soc-aid-spc') {
      list = ['Special Case'];
    }
    return Array.from(new Set(list.filter(Boolean)));
  }, [code, codeMap]);

  // Compute all available special cases
  const allAvailableCases = useMemo(() => {
    const set = new Set(ALL_SHEET10_SPECIAL_CASES);
    (allCases || []).forEach(c => {
      const canon = canonicalizeSpecialCase(c);
      if (canon) set.add(canon);
    });
    Object.values(codeMap || {}).forEach(item => {
      if (item && Array.isArray(item['Special Cases'])) {
        item['Special Cases'].forEach(sc => {
          const canon = canonicalizeSpecialCase(sc);
          if (canon) set.add(canon);
        });
      }
      if (item && item['Special Case']) {
        const canon = canonicalizeSpecialCase(item['Special Case']);
        if (canon) set.add(canon);
      }
    });
    if (cleanVal) set.add(cleanVal);
    return Array.from(set).sort((a, b) => a.localeCompare(b));
  }, [allCases, codeMap, cleanVal]);

  // Filter based on search query
  const searchLower = search.trim().toLowerCase();
  const filteredRecommended = useMemo(() => {
    if (!searchLower) return recommendedCases;
    return recommendedCases.filter(c => c.toLowerCase().includes(searchLower));
  }, [recommendedCases, searchLower]);

  const filteredOthers = useMemo(() => {
    const recSet = new Set(recommendedCases);
    const others = allAvailableCases.filter(c => !recSet.has(c));
    if (!searchLower) return others;
    return others.filter(c => c.toLowerCase().includes(searchLower));
  }, [allAvailableCases, recommendedCases, searchLower]);

  const exactMatchExists = useMemo(() => {
    if (!searchLower) return true;
    return allAvailableCases.some(c => c.toLowerCase() === searchLower);
  }, [allAvailableCases, searchLower]);

  // Calculate coordinates when opening
  const updatePosition = () => {
    if (!triggerRef.current) return;
    const rect = triggerRef.current.getBoundingClientRect();
    const dropdownHeight = 320;
    const spaceBelow = window.innerHeight - rect.bottom;
    const placement = spaceBelow < dropdownHeight && rect.top > dropdownHeight ? 'top' : 'bottom';
    
    setCoords({
      top: placement === 'bottom' ? rect.bottom + 4 : rect.top - dropdownHeight - 4,
      left: Math.max(8, Math.min(rect.left, window.innerWidth - 270)),
      width: Math.max(rect.width, 240),
      placement
    });
  };

  const handleToggle = () => {
    if (disabled) return;
    if (!isOpen) {
      updatePosition();
      setIsOpen(true);
      setSearch('');
      setTimeout(() => {
        searchInputRef.current?.focus();
      }, 50);
    } else {
      setIsOpen(false);
    }
  };

  const handleSelect = (selectedCase) => {
    const canonical = canonicalizeSpecialCase(selectedCase);
    onChange(canonical);
    setIsOpen(false);
    setSearch('');
  };

  const handleCustomPrompt = () => {
    const custom = window.prompt('Enter custom special case name:', cleanVal);
    if (custom !== null) {
      handleSelect(custom.trim());
    }
  };

  // Close when clicking outside or pressing Escape
  useEffect(() => {
    if (!isOpen) return;

    const handleClickOutside = (e) => {
      if (
        triggerRef.current && !triggerRef.current.contains(e.target) &&
        popupRef.current && !popupRef.current.contains(e.target)
      ) {
        setIsOpen(false);
      }
    };

    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        setIsOpen(false);
      } else if (e.key === 'Enter' && searchLower && !exactMatchExists) {
        e.preventDefault();
        handleSelect(search.trim());
      }
    };

    const handleScrollOrResize = () => {
      updatePosition();
    };

    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleKeyDown);
    window.addEventListener('scroll', handleScrollOrResize, true);
    window.addEventListener('resize', handleScrollOrResize);

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('scroll', handleScrollOrResize, true);
      window.removeEventListener('resize', handleScrollOrResize);
    };
  }, [isOpen, searchLower, exactMatchExists, search]);

  return (
    <div className="relative w-full">
      {/* Trigger Button */}
      <button
        ref={triggerRef}
        type="button"
        disabled={disabled}
        onClick={handleToggle}
        title={title}
        className={`w-full flex items-center justify-between gap-1.5 rounded-lg border text-xs font-semibold transition-all select-none ${
          compact ? 'px-2 py-1' : 'px-2.5 py-1.5'
        } ${
          cleanVal
            ? 'bg-amber-50 dark:bg-amber-950/60 border-amber-300 dark:border-amber-500/50 text-amber-900 dark:text-amber-200 hover:border-amber-400 dark:hover:border-amber-400 shadow-xs'
            : 'bg-white dark:bg-slate-900/90 border-slate-300 dark:border-white/10 text-slate-700 dark:text-slate-300 hover:border-slate-400 dark:hover:border-white/20'
        } ${disabled ? 'opacity-60 cursor-not-allowed' : 'cursor-pointer'}`}
      >
        <span className="truncate flex items-center gap-1.5">
          {cleanVal ? (
            <>
              <span className="text-amber-600 dark:text-amber-400 text-[11px]">🎯</span>
              <span className="font-bold truncate">{cleanVal}</span>
            </>
          ) : (
            <span className="text-slate-400 dark:text-slate-500 font-medium">None (Standard)</span>
          )}
        </span>

        <span className="flex items-center gap-1 shrink-0">
          {cleanVal && !disabled && (
            <span
              role="button"
              tabIndex={0}
              onClick={(e) => {
                e.stopPropagation();
                handleSelect('');
              }}
              title="Reset to None (Standard)"
              className="p-0.5 rounded text-amber-700 dark:text-amber-300 hover:bg-amber-200/50 dark:hover:bg-amber-900/50 transition-colors"
            >
              <X className="w-3 h-3" />
            </span>
          )}
          <ChevronDown className={`w-3.5 h-3.5 text-slate-400 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
        </span>
      </button>

      {/* Searchable Combobox Popup rendered in Portal */}
      {isOpen &&
        createPortal(
          <div
            ref={popupRef}
            style={{
              position: 'fixed',
              top: `${coords.top}px`,
              left: `${coords.left}px`,
              width: `${coords.width}px`,
              zIndex: 999999
            }}
            className="panel-pop rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 shadow-2xl overflow-hidden flex flex-col text-xs font-sans text-slate-800 dark:text-slate-100"
          >
            {/* Search Input Bar */}
            <div className="p-2 border-b border-slate-100 dark:border-white/10 bg-slate-50 dark:bg-slate-800/60 flex items-center gap-2">
              <Search className="w-3.5 h-3.5 text-slate-400 shrink-0 ml-1" />
              <input
                ref={searchInputRef}
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search special case (e.g. Umm, Zarang, Eid)..."
                className="w-full bg-transparent text-xs text-slate-900 dark:text-white placeholder-slate-400 focus:outline-none font-medium"
              />
              {search && (
                <button
                  type="button"
                  onClick={() => setSearch('')}
                  className="p-1 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
                >
                  <X className="w-3 h-3" />
                </button>
              )}
            </div>

            {/* Scrollable Options List */}
            <div className="max-h-60 overflow-y-auto p-1.5 flex flex-col gap-0.5">
              {/* Option: None (Standard) */}
              <button
                type="button"
                onClick={() => handleSelect('')}
                className={`w-full px-2.5 py-1.5 rounded-lg text-left flex items-center justify-between transition-colors ${
                  !cleanVal
                    ? 'bg-slate-200/70 dark:bg-slate-800 font-bold text-slate-900 dark:text-white'
                    : 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800/50'
                }`}
              >
                <span className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-slate-400"></span>
                  <span>None (Standard)</span>
                </span>
                {!cleanVal && <Check className="w-3.5 h-3.5 text-slate-600 dark:text-slate-300" />}
              </button>

              {/* Dynamic Add Custom Case from Search */}
              {searchLower && !exactMatchExists && (
                <button
                  type="button"
                  onClick={() => handleSelect(search.trim())}
                  className="w-full px-2.5 py-1.5 rounded-lg text-left flex items-center justify-between bg-indigo-50 dark:bg-indigo-950/50 border border-indigo-200 dark:border-indigo-800/60 text-indigo-700 dark:text-indigo-300 font-bold hover:bg-indigo-100 dark:hover:bg-indigo-900/50 transition-colors my-1"
                >
                  <span className="flex items-center gap-2 truncate">
                    <Plus className="w-3.5 h-3.5 text-indigo-500" />
                    <span>Use &ldquo;{search.trim()}&rdquo; (Custom)</span>
                  </span>
                </button>
              )}

              {/* Recommended Group */}
              {filteredRecommended.length > 0 && (
                <div className="mt-1">
                  <div className="px-2 py-1 text-[10px] font-extrabold uppercase tracking-wider text-amber-700 dark:text-amber-400 flex items-center gap-1.5">
                    <Sparkles className="w-3 h-3" />
                    <span>Recommended for {code || 'Code'}</span>
                  </div>
                  {filteredRecommended.map((sc) => {
                    const isSelected = cleanVal.toLowerCase() === sc.toLowerCase();
                    return (
                      <button
                        key={sc}
                        type="button"
                        onClick={() => handleSelect(sc)}
                        className={`w-full px-2.5 py-1.5 rounded-lg text-left flex items-center justify-between transition-colors ${
                          isSelected
                            ? 'bg-amber-100 dark:bg-amber-950/80 font-bold text-amber-900 dark:text-amber-200 border border-amber-300/60 dark:border-amber-600/40'
                            : 'hover:bg-amber-50/60 dark:hover:bg-amber-950/30 text-slate-800 dark:text-slate-200'
                        }`}
                      >
                        <span className="flex items-center gap-2 font-medium">
                          <Tag className="w-3 h-3 text-amber-500 shrink-0" />
                          <span className="truncate">{sc}</span>
                        </span>
                        {isSelected && <Check className="w-3.5 h-3.5 text-amber-600 dark:text-amber-400" />}
                      </button>
                    );
                  })}
                </div>
              )}

              {/* Other Known Cases */}
              {filteredOthers.length > 0 && (
                <div className="mt-1 border-t border-slate-100 dark:border-white/5 pt-1">
                  <div className="px-2 py-1 text-[10px] font-extrabold uppercase tracking-wider text-slate-400 dark:text-slate-500">
                    {filteredRecommended.length > 0 ? 'Other Special Cases' : 'All Special Cases'}
                  </div>
                  {filteredOthers.map((sc) => {
                    const isSelected = cleanVal.toLowerCase() === sc.toLowerCase();
                    return (
                      <button
                        key={sc}
                        type="button"
                        onClick={() => handleSelect(sc)}
                        className={`w-full px-2.5 py-1.5 rounded-lg text-left flex items-center justify-between transition-colors ${
                          isSelected
                            ? 'bg-cyan-100 dark:bg-cyan-950/80 font-bold text-cyan-900 dark:text-cyan-200 border border-cyan-300/60 dark:border-cyan-600/40'
                            : 'hover:bg-slate-100 dark:hover:bg-slate-800/60 text-slate-800 dark:text-slate-200'
                        }`}
                      >
                        <span className="flex items-center gap-2">
                          <span className="w-1.5 h-1.5 rounded-full bg-slate-400"></span>
                          <span className="truncate">{sc}</span>
                        </span>
                        {isSelected && <Check className="w-3.5 h-3.5 text-cyan-600 dark:text-cyan-400" />}
                      </button>
                    );
                  })}
                </div>
              )}

              {/* No search matches */}
              {filteredRecommended.length === 0 && filteredOthers.length === 0 && !searchLower && (
                <div className="py-4 text-center text-slate-400 italic text-xs">No special cases available.</div>
              )}
            </div>

            {/* Custom Input Option Footer */}
            <div className="p-1.5 border-t border-slate-100 dark:border-white/10 bg-slate-50 dark:bg-slate-800/40 flex justify-between items-center">
              <button
                type="button"
                onClick={handleCustomPrompt}
                className="w-full text-center py-1 text-[11px] font-bold text-cyan-600 dark:text-cyan-400 hover:text-cyan-700 dark:hover:text-cyan-300 transition-colors flex items-center justify-center gap-1"
              >
                <Plus className="w-3 h-3" />
                <span>Enter Custom Case Name...</span>
              </button>
            </div>
          </div>,
          document.body
        )}
    </div>
  );
}
