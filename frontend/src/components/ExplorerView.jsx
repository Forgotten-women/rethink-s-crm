import React, { useEffect, useState, useRef, useMemo } from 'react';
import { Table, Search, Download, ChevronLeft, ChevronRight, ChevronDown, Edit3, UserCheck, Eye, Columns, CheckSquare, Square, Save, ArrowUpDown, ArrowUp, ArrowDown, X, Check, AlertCircle, Layers, Filter, SlidersHorizontal } from 'lucide-react';
import { API_BASE_URL } from '../config';

const DEFAULT_EXPLORER_COLUMNS = [
  'First Name',
  'Last Name',
  'Total Online Donations Net Amount in Settled Currency',
  'Transaction Donor Classification',
  'Lifetime Donor Classification',
  'Total LTV',
  'Payment Frequency',
  'Programme Fund',
  'Department',
  'Office',
  'Portfolio',
  'Heading',
  'Sub-Heading',
  'Country',
  'Code',
  'Old Code',
  'Zakat Eligibility'
];

const COLUMN_ALIASES = {
  'Display Name': 'Donor Name',
  'Total Online Donations Net Amount in Settled Currency': 'Settled Net Amount',
  'Lifetime Donor Classification': 'Lifetime Classification',
  'Transaction Donor Classification': 'Transaction Classification',
  'Campaign Name': 'Campaign',
  'Community Name': 'Community',
  'Created Date (UTC)': 'Date',
  'Donation Amount in Project Currency (May be approx.)': 'Project Amount',
  'Donation Currency (DC)': 'Currency',
  'Payment Frequency': 'Frequency',
  'fundraiser_name': 'Fundraiser',
  'Fundraiser Name': 'Fundraiser',
  'fundraiser_url': 'Fundraiser URL',
  'Fundraiser URL': 'Fundraiser URL',
  'Campaign URL': 'Campaign URL',
  'campaign_url': 'Campaign URL',
  'Heading': 'Department',
  'Sub-Heading': 'Office',
  'heading': 'Department',
  'sub_heading': 'Office',
  'Department': 'Department',
  'Office': 'Office',
  'Portfolio': 'Portfolio',
  'department': 'Department',
  'office': 'Office',
  'portfolio': 'Portfolio',
  'Programme Fund': 'Programme Fund',
  'programme_fund': 'Programme Fund',
  'Fund Code': 'Fund Code',
  'fund_code': 'Fund Code',
  'Old Code': 'Old Code',
  'old_code': 'Old Code',
  'Code': 'Code',
  'code': 'Code',
  'Country': 'Project Country',
  'Zakat Eligibility': 'Zakat'
};

const SEARCH_TARGET_OPTIONS = [
  { id: 'all', label: 'All Fields', title: 'Search across all fields' },
  { id: 'campaigns', label: 'Campaigns', title: 'Search Campaign Name' },
  { id: 'community', label: 'Community', title: 'Search Community Name' },
  { id: 'name', label: 'Donor Name', title: 'Search First, Last, and Display Name' },
  { id: 'email', label: 'Email', title: 'Search Email Address' },
  { id: 'donation_id', label: 'Donation ID', title: 'Search Donation ID, Donor ID, Transfer ID' },
  { id: 'fundraiser', label: 'Fundraiser', title: 'Search Fundraiser Name' },
  { id: 'code', label: 'Code', title: 'Search Project/Allocation Code' }
];

const ALL_SEARCH_FIELD_IDS = ['campaigns', 'community', 'name', 'email', 'donation_id', 'fundraiser', 'code'];

const getStoredSearchTargets = () => {
  try {
    const saved = localStorage.getItem('explorer_search_targets');
    if (saved) {
      const parsed = JSON.parse(saved);
      if (Array.isArray(parsed) && parsed.length > 0) {
        return parsed;
      }
    }
  } catch (e) {}
  return ['all'];
};

const getFundraiserColumn = (cols = []) => {
  return cols.find(c => ['fundraiser_name', 'Fundraiser Name', 'fundraiser'].includes(c)) || 'fundraiser_name';
};
const getCampaignColumn = (cols = []) => {
  return cols.find(c => ['Campaign Name', 'campaign_name', 'Campaign'].includes(c)) || 'Campaign Name';
};

const getStoredColumns = () => {
  try {
    const saved = localStorage.getItem('explorer_selected_columns');
    if (saved) {
      const parsed = JSON.parse(saved);
      if (Array.isArray(parsed) && parsed.length > 0) {
        return parsed;
      }
    }
  } catch (e) {
    console.error('Error reading explorer_selected_columns from localStorage:', e);
  }
  return null;
};

const getStoredPreset = () => {
  try {
    return localStorage.getItem('explorer_column_preset') || 'default';
  } catch (e) {
    return 'default';
  }
};

export default function ExplorerView({ user, filters, onSelectDonor }) {
  const [data, setData] = useState({ total_records: 0, page: 1, page_size: 100, total_pages: 1, available_columns: [], records: [] });
  const [loading, setLoading] = useState(true);
  
  // Controls state
  const [search, setSearch] = useState('');
  const [preset, setPreset] = useState(() => getStoredPreset());
  const [pageSize, setPageSize] = useState(100);
  const [currentPage, setCurrentPage] = useState(1);
  const [showColumnChooser, setShowColumnChooser] = useState(false);
  const [showExportMenu, setShowExportMenu] = useState(false);
  const [columnFilterText, setColumnFilterText] = useState('');
  const [selectedColumns, setSelectedColumns] = useState(() => {
    return getStoredColumns() || DEFAULT_EXPLORER_COLUMNS;
  });
  const [sortBy, setSortBy] = useState(null);
  const [sortOrder, setSortOrder] = useState('asc');

  // Scoped Search Targets State
  const [searchTargets, setSearchTargets] = useState(() => getStoredSearchTargets());

  const isAllActive = useMemo(() => {
    return searchTargets.includes('all') || ALL_SEARCH_FIELD_IDS.every(id => searchTargets.includes(id));
  }, [searchTargets]);

  const searchPlaceholder = useMemo(() => {
    if (isAllActive) {
      return '🔍 Search all fields (Name, Campaign, Community, Email, ID...)';
    }
    const activeLabels = SEARCH_TARGET_OPTIONS
      .filter(opt => opt.id !== 'all' && searchTargets.includes(opt.id))
      .map(opt => opt.label);
    if (activeLabels.length === 1) {
      return `🔍 Searching only in ${activeLabels[0]}...`;
    }
    return `🔍 Searching in ${activeLabels.join(', ')}...`;
  }, [isAllActive, searchTargets]);

  const handleToggleAll = () => {
    setSearchTargets(['all']);
    try { localStorage.setItem('explorer_search_targets', JSON.stringify(['all'])); } catch(e) {}
    setCurrentPage(1);
  };

  const handleToggleTarget = (fieldId) => {
    let newTargets;
    if (isAllActive) {
      // If all were active, clicking a specific field isolates to ONLY this field (user said "for example i want to search only in campaigns")
      newTargets = [fieldId];
    } else if (searchTargets.includes(fieldId)) {
      // If it's active, toggle it off
      const remaining = searchTargets.filter(id => id !== fieldId && id !== 'all');
      newTargets = remaining.length > 0 ? remaining : ['all'];
    } else {
      // If it's inactive, add it
      const updated = [...searchTargets.filter(id => id !== 'all'), fieldId];
      if (ALL_SEARCH_FIELD_IDS.every(id => updated.includes(id))) {
        newTargets = ['all'];
      } else {
        newTargets = updated;
      }
    }
    setSearchTargets(newTargets);
    try { localStorage.setItem('explorer_search_targets', JSON.stringify(newTargets)); } catch(e) {}
    setCurrentPage(1);
  };

  const handleTargetContextMenu = (e, fieldId) => {
    e.preventDefault();
    setSearchTargets([fieldId]);
    try { localStorage.setItem('explorer_search_targets', JSON.stringify([fieldId])); } catch(e) {}
    setCurrentPage(1);
  };

  // Inline Cell Editing State
  const [editingCell, setEditingCell] = useState(null); // { rowIdx, colName, value }
  const [cellMessage, setCellMessage] = useState('');

  // Classification lookups for smart quick-pick and auto-enrichment
  const [campaignCodesLookup, setCampaignCodesLookup] = useState({});
  const [codeMap, setCodeMap] = useState({});

  // Single Donor Record Modal Edit State
  const [editingDonorModal, setEditingDonorModal] = useState(null); // { row, fields }
  const [editModalSaving, setEditModalSaving] = useState(false);
  const [editModalMsg, setEditModalMsg] = useState('');

  // Bulk edit form state
  const [showBulkEdit, setShowBulkEdit] = useState(false);
  const [bulkCol1, setBulkCol1] = useState('First Name');
  const [bulkVal1, setBulkVal1] = useState('');
  const [bulkCol2, setBulkCol2] = useState('');
  const [bulkVal2, setBulkVal2] = useState('');
  const [bulkCol3, setBulkCol3] = useState('');
  const [bulkVal3, setBulkVal3] = useState('');
  const [bulkCol4, setBulkCol4] = useState('');
  const [bulkVal4, setBulkVal4] = useState('');
  const [bulkSaving, setBulkSaving] = useState(false);
  const [bulkMessage, setBulkMessage] = useState('');

  const canEdit = user?.role === 'super_admin' || user?.can_edit_donors === 1;

  // Load Campaign Codes lookup, Code Map on mount
  useEffect(() => {
    fetch(`${API_BASE_URL}/api/classifications/campaign-codes`)
      .then(r => r.json())
      .then(data => { if (data && typeof data === 'object') setCampaignCodesLookup(data); })
      .catch(err => console.error('Error fetching campaign-codes lookup:', err));

    fetch(`${API_BASE_URL}/api/classifications/code-map`)
      .then(r => r.json())
      .then(data => { if (data && typeof data === 'object') setCodeMap(data); })
      .catch(err => console.error('Error fetching code-map:', err));
  }, []);

  const loadDonors = () => {
    setLoading(true);
    const searchFieldsParam = isAllActive ? 'all' : searchTargets.join(',');
    const params = new URLSearchParams({
      page: currentPage,
      page_size: pageSize,
      search: search,
      search_fields: searchFieldsParam
    });

    if (sortBy) {
      params.append('sort_by', sortBy);
      params.append('sort_order', sortOrder);
    }

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
      if (filters.campaign && filters.campaign !== 'All Campaigns') {
        params.append('campaign', filters.campaign);
      }
    }

    fetch(`${API_BASE_URL}/api/donors?${params.toString()}`)
      .then(res => res.json())
      .then(resData => {
        setData(resData);
        if (resData.available_columns?.length > 0) {
          setSelectedColumns(prev => {
            let candidate = (prev && prev.length > 0) ? prev : (getStoredColumns() || DEFAULT_EXPLORER_COLUMNS);
            const valid = candidate.filter(c => resData.available_columns.includes(c));
            if (valid.length > 0) {
              const currentPreset = getStoredPreset();
              if (currentPreset === 'fundraisers') {
                const fundCol = getFundraiserColumn(resData.available_columns);
                if (fundCol && resData.available_columns.includes(fundCol) && !valid.includes(fundCol)) {
                  const campIdx = valid.indexOf('Campaign Name');
                  if (campIdx !== -1) {
                    valid.splice(campIdx, 0, fundCol);
                  } else {
                    valid.push(fundCol);
                  }
                }
              }
              try {
                localStorage.setItem('explorer_selected_columns', JSON.stringify(valid));
              } catch (e) {}
              return valid;
            }
            const defaultCols = DEFAULT_EXPLORER_COLUMNS.filter(c => resData.available_columns.includes(c));
            const fallback = defaultCols.length > 0 ? defaultCols : resData.available_columns.slice(0, 12);
            try {
              localStorage.setItem('explorer_selected_columns', JSON.stringify(fallback));
            } catch (e) {}
            return fallback;
          });
        }
        setLoading(false);
      })
      .catch(err => {
        console.error('Error fetching donors explorer:', err);
        setLoading(false);
      });
  };

  useEffect(() => {
    loadDonors();
  }, [currentPage, pageSize, search, searchTargets, filters, sortBy, sortOrder]);

  const handleToggleColumn = (col) => {
    setSelectedColumns(prev => {
      const updated = prev.includes(col)
        ? prev.filter(c => c !== col)
        : [...prev, col];
      try {
        localStorage.setItem('explorer_selected_columns', JSON.stringify(updated));
      } catch (e) {}
      return updated;
    });
    setPreset('custom');
    try {
      localStorage.setItem('explorer_column_preset', 'custom');
    } catch (e) {}
  };

  const handleSelectAllColumns = () => {
    if (!data.available_columns || data.available_columns.length === 0) return;
    const allCols = [...data.available_columns];
    setSelectedColumns(allCols);
    setPreset('all');
    try {
      localStorage.setItem('explorer_selected_columns', JSON.stringify(allCols));
      localStorage.setItem('explorer_column_preset', 'all');
    } catch (e) {}
  };

  const handleDeselectAllColumns = () => {
    setSelectedColumns([]);
    setPreset('custom');
    try {
      localStorage.setItem('explorer_selected_columns', JSON.stringify([]));
      localStorage.setItem('explorer_column_preset', 'custom');
    } catch (e) {}
  };

  const handleResetDefaultColumns = () => {
    const available = data.available_columns || [];
    const defaultCols = DEFAULT_EXPLORER_COLUMNS.filter(c => available.includes(c));
    const fallback = defaultCols.length > 0 ? defaultCols : available.slice(0, 12);
    setSelectedColumns(fallback);
    setPreset('default');
    try {
      localStorage.setItem('explorer_selected_columns', JSON.stringify(fallback));
      localStorage.setItem('explorer_column_preset', 'default');
    } catch (e) {}
  };

  const handlePresetChange = (val) => {
    setPreset(val);
    try {
      localStorage.setItem('explorer_column_preset', val);
    } catch (e) {}

    let newCols = [];
    const available = data.available_columns || [];
    if (val === 'default') {
      newCols = DEFAULT_EXPLORER_COLUMNS.filter(c => available.includes(c));
    } else if (val === 'all') {
      newCols = [...available];
    } else if (val === 'minimal') {
      newCols = [
        'First Name',
        'Last Name',
        'Total Online Donations Net Amount in Settled Currency',
        'Payment Frequency'
      ].filter(c => available.includes(c));
    } else if (val === 'fundraisers') {
      const fundCol = getFundraiserColumn(available);
      const campCol = getCampaignColumn(available);
      newCols = [
        'First Name',
        'Last Name',
        fundCol,
        campCol,
        'Total Online Donations Net Amount in Settled Currency',
        'Payment Frequency',
        'Created Date (UTC)'
      ].filter(c => available.includes(c));
    }

    if (newCols.length > 0) {
      setSelectedColumns(newCols);
      try {
        localStorage.setItem('explorer_selected_columns', JSON.stringify(newCols));
      } catch (e) {}
    }
  };

  const handleInlineSave = (row, colName, newVal) => {
    if (!canEdit) return;

    fetch(`${API_BASE_URL}/api/donors/update-record`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_role: user?.role || 'admin',
        can_edit_donors: canEdit,
        row_id: row._row_id !== undefined && row._row_id !== null ? Number(row._row_id) : null,
        donation_id: row['Donation ID'] || null,
        column_name: colName,
        new_value: String(newVal)
      })
    })
      .then(async r => {
        const text = await r.text();
        try {
          return JSON.parse(text);
        } catch {
          return { status: 'error', detail: text || `HTTP ${r.status}` };
        }
      })
      .then(res => {
        if (res?.status === 'success') {
          setCellMessage(`✅ Saved ${colName}!`);
          setEditingCell(null);
          loadDonors();
          setTimeout(() => setCellMessage(''), 2500);
        } else {
          setCellMessage(`❌ ${res?.detail || 'Save failed'}`);
          setTimeout(() => setCellMessage(''), 3000);
        }
      })
      .catch(err => {
        setCellMessage(`❌ Error: ${err.message}`);
        setTimeout(() => setCellMessage(''), 3000);
      });
  };

  const handleSaveDonorModal = (e) => {
    e.preventDefault();
    if (!editingDonorModal || !canEdit) return;
    setEditModalSaving(true);
    setEditModalMsg('');

    fetch(`${API_BASE_URL}/api/donors/update-record`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_role: user?.role || 'admin',
        can_edit_donors: canEdit,
        row_id: editingDonorModal.row._row_id !== undefined && editingDonorModal.row._row_id !== null ? Number(editingDonorModal.row._row_id) : null,
        donation_id: editingDonorModal.row['Donation ID'] || null,
        updated_fields: editingDonorModal.fields
      })
    })
      .then(async r => {
        const text = await r.text();
        try {
          return JSON.parse(text);
        } catch {
          return { status: 'error', detail: text || `HTTP ${r.status}` };
        }
      })
      .then(res => {
        setEditModalSaving(false);
        if (res?.status === 'success') {
          setEditModalMsg(`✅ Successfully updated donor record!`);
          loadDonors();
          setTimeout(() => {
            setEditingDonorModal(null);
            setEditModalMsg('');
          }, 1000);
        } else {
          setEditModalMsg(`❌ ${res?.detail || 'Failed to update record.'}`);
        }
      })
      .catch(err => {
        setEditModalSaving(false);
        setEditModalMsg(`❌ Error: ${err.message}`);
      });
  };

  const handleBulkEditSubmit = (e) => {
    e.preventDefault();
    setBulkSaving(true);
    setBulkMessage('');

    const target_columns = [];
    const new_values = [];

    if (bulkCol1) {
      target_columns.push(bulkCol1);
      new_values.push(bulkVal1);
    }
    if (bulkCol2) {
      target_columns.push(bulkCol2);
      new_values.push(bulkVal2);
    }
    if (bulkCol3) {
      target_columns.push(bulkCol3);
      new_values.push(bulkVal3);
    }
    if (bulkCol4) {
      target_columns.push(bulkCol4);
      new_values.push(bulkVal4);
    }

    if (target_columns.length === 0) {
      setBulkMessage('❌ Please select at least one target field.');
      setBulkSaving(false);
      return;
    }

    const searchFieldsParam = isAllActive ? 'all' : searchTargets.join(',');

    fetch(`${API_BASE_URL}/api/donors/bulk-edit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_role: user?.role || 'admin',
        target_columns,
        new_values,
        filter_search: search,
        filter_search_fields: searchFieldsParam,
        filter_payment_type: filters?.payment_type,
        filter_tier: filters?.tier,
        filter_source: filters?.source,
        filter_programme_fund: filters?.programme_fund,
        filter_heading: filters?.heading,
        filter_subheading: filters?.subheading,
        filter_country: filters?.country,
        filter_code: filters?.code,
        filter_zakat: filters?.zakat,
        filter_donor_country: filters?.donor_country,
        filter_campaign_search: filters?.campaign_search,
        filter_campaign: (filters?.campaign && filters.campaign !== 'All Campaigns') ? filters.campaign : null,
        filter_gift_aid: filters?.gift_aid,
        filter_start_date: filters?.start_date,
        filter_end_date: filters?.end_date
      })
    })
      .then(r => r.json())
      .then(res => {
        setBulkSaving(false);
        if (res?.status === 'success') {
          setBulkMessage(`✅ ${res.message}`);
          loadDonors();
          setTimeout(() => setShowBulkEdit(false), 1500);
        } else {
          setBulkMessage(`❌ ${res?.detail || 'Failed to apply bulk edit.'}`);
        }
      })
      .catch(err => {
        setBulkSaving(false);
        setBulkMessage(`❌ Error: ${err.message}`);
      });
  };


  const getTierBadgeClass = (tier) => {
    switch (tier) {
      case 'Super High': return 'badge-pink';
      case 'High': return 'badge-amber';
      case 'Medium': return 'badge-emerald';
      case 'Medium Low': return 'badge-cyan';
      default: return 'badge-slate';
    }
  };

  const formatDate = (val) => {
    if (!val) return 'N/A';
    const str = String(val);
    return str.split('T')[0].split(' ')[0];
  };

  const handleExportDonors = (format, exportAll = false) => {
    const searchFieldsParam = isAllActive ? 'all' : searchTargets.join(',');
    const params = new URLSearchParams({
      format: format,
      search: search,
      search_fields: searchFieldsParam
    });

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
      if (filters.campaign && filters.campaign !== 'All Campaigns') {
        params.append('campaign', filters.campaign);
      }
      if (filters.gift_aid) params.append('gift_aid', filters.gift_aid);
      if (filters.start_date) params.append('start_date', filters.start_date);
      if (filters.end_date) params.append('end_date', filters.end_date);
    }

    if (!exportAll && selectedColumns && selectedColumns.length > 0) {
      params.append('columns', selectedColumns.join(','));
    }

    window.open(`${API_BASE_URL}/api/donors/export?${params.toString()}`, '_blank');
  };

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-extrabold text-white flex items-center gap-2">
            <Table className="w-5 h-5 text-cyan-400" /> Data Explorer & 360° Profile Center
          </h2>
          <p className="text-xs text-slate-400">Search, filter, inspect donor 360° profiles, customize visible columns, and edit records.</p>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          {/* Export Dropdown Group */}
          <div className="relative inline-block text-left">
            <div className="flex items-center bg-slate-900/90 border border-emerald-500/30 p-1 rounded-xl shadow-lg">
              <button 
                onClick={() => handleExportDonors('xlsx', false)}
                className="text-xs font-bold text-emerald-400 hover:bg-emerald-500/20 px-2.5 py-1.5 rounded-lg flex items-center gap-1.5 transition-all"
                title={`Export visible columns (${selectedColumns.length}) as Excel (.xlsx) - Fast`}
              >
                <Download className="w-3.5 h-3.5" /> Excel (.xlsx)
              </button>
              <span className="text-white/20 text-xs">|</span>
              <button 
                onClick={() => handleExportDonors('csv', false)}
                className="text-xs font-bold text-emerald-400 hover:bg-emerald-500/20 px-2 py-1.5 rounded-lg flex items-center gap-1 transition-all"
                title={`Export visible columns (${selectedColumns.length}) as CSV`}
              >
                CSV
              </button>
              <span className="text-white/20 text-xs">|</span>
              <button
                type="button"
                onClick={() => setShowExportMenu(!showExportMenu)}
                className="text-xs text-emerald-400 hover:bg-emerald-500/20 px-1.5 py-1.5 rounded-lg transition-all flex items-center"
                title="More export options (All Columns, Full Data)"
              >
                <ChevronDown className={`w-3.5 h-3.5 transition-transform ${showExportMenu ? 'rotate-180' : ''}`} />
              </button>
            </div>

            {showExportMenu && (
              <div 
                className="absolute right-0 mt-1.5 w-64 bg-slate-900/95 border border-emerald-500/30 rounded-xl shadow-2xl py-2 z-50 backdrop-blur-md"
                onMouseLeave={() => setShowExportMenu(false)}
              >
                <div className="px-3 py-1.5 text-[10px] font-bold uppercase tracking-wider text-slate-400 border-b border-white/5">
                  Export Options
                </div>
                <button
                  type="button"
                  onClick={() => { setShowExportMenu(false); handleExportDonors('xlsx', false); }}
                  className="w-full text-left px-3 py-2 text-xs text-white hover:bg-emerald-500/20 flex items-center justify-between transition-colors"
                >
                  <span className="flex items-center gap-2">
                    <Download className="w-3.5 h-3.5 text-emerald-400" /> Excel (Visible {selectedColumns.length} Cols)
                  </span>
                  <span className="text-[10px] font-bold text-emerald-400 bg-emerald-500/10 px-1.5 py-0.5 rounded">Fast (~5s)</span>
                </button>
                <button
                  type="button"
                  onClick={() => { setShowExportMenu(false); handleExportDonors('xlsx', true); }}
                  className="w-full text-left px-3 py-2 text-xs text-white hover:bg-emerald-500/20 flex items-center justify-between transition-colors"
                >
                  <span className="flex items-center gap-2">
                    <Download className="w-3.5 h-3.5 text-emerald-400" /> Excel (All 140+ Columns)
                  </span>
                  <span className="text-[10px] font-bold text-slate-400 bg-white/5 px-1.5 py-0.5 rounded">Full Data</span>
                </button>
                <div className="border-t border-white/5 my-1" />
                <button
                  type="button"
                  onClick={() => { setShowExportMenu(false); handleExportDonors('csv', false); }}
                  className="w-full text-left px-3 py-2 text-xs text-white hover:bg-emerald-500/20 flex items-center justify-between transition-colors"
                >
                  <span className="flex items-center gap-2">
                    <Download className="w-3.5 h-3.5 text-emerald-400" /> CSV (Visible {selectedColumns.length} Cols)
                  </span>
                  <span className="text-[10px] font-bold text-emerald-400 bg-emerald-500/10 px-1.5 py-0.5 rounded">Instant</span>
                </button>
                <button
                  type="button"
                  onClick={() => { setShowExportMenu(false); handleExportDonors('csv', true); }}
                  className="w-full text-left px-3 py-2 text-xs text-white hover:bg-emerald-500/20 flex items-center justify-between transition-colors"
                >
                  <span className="flex items-center gap-2">
                    <Download className="w-3.5 h-3.5 text-emerald-400" /> CSV (All 140+ Columns)
                  </span>
                  <span className="text-[10px] font-bold text-slate-400 bg-white/5 px-1.5 py-0.5 rounded">Full Data</span>
                </button>
              </div>
            )}
          </div>

          <select
            value={preset}
            onChange={e => handlePresetChange(e.target.value)}
            className="bg-slate-900 border border-white/10 rounded-xl px-3 py-2 text-xs text-white focus:outline-none focus:border-cyan-500 cursor-pointer"
          >
            <option value="default">📋 Default Preset</option>
            <option value="minimal">🔍 Minimal View</option>
            <option value="fundraisers">🤝 Fundraisers & Campaigns</option>
            <option value="all">🌐 All Columns</option>
            {preset === 'custom' && <option value="custom">⚙️ Custom Selection ({selectedColumns.length})</option>}
          </select>

          <button 
            onClick={() => setShowColumnChooser(!showColumnChooser)}
            className="btn-secondary text-xs flex items-center gap-1.5 text-cyan-400 border-cyan-500/30 hover:bg-cyan-500/10"
          >
            <Columns className="w-3.5 h-3.5" /> 📐 Choose Visible Columns ({selectedColumns.length})
          </button>

          {(user?.role === 'super_admin' || user?.can_edit_donors === 1) && (
            <button 
              onClick={() => setShowBulkEdit(!showBulkEdit)}
              className="btn-secondary text-xs flex items-center gap-1.5 text-purple-400 border-purple-500/30 hover:bg-purple-500/10"
            >
              <Edit3 className="w-3.5 h-3.5" /> ⚡ Bulk Edit Records
            </button>
          )}
        </div>
      </div>

      {cellMessage && <div className="text-xs font-bold text-emerald-400 animate-pulse">{cellMessage}</div>}

      {/* Column Chooser Modal UI */}
      {showColumnChooser && (
        <div className="glass-panel p-5 border-l-4 border-cyan-400 flex flex-col gap-4 animate-fadeIn">
          <div className="flex items-center justify-between border-b border-white/10 pb-3 flex-wrap gap-2">
            <div className="flex items-center gap-2">
              <h3 className="text-xs font-extrabold text-white uppercase tracking-wider flex items-center gap-2">
                <Columns className="w-4 h-4 text-cyan-400" /> Select & Customize Visible Columns
              </h3>
              <span className="text-[11px] font-mono px-2 py-0.5 rounded-full bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
                {selectedColumns.length} of {data.available_columns?.length || 0} active
              </span>
            </div>
            <div className="flex items-center gap-2">
              <button 
                type="button"
                onClick={handleSelectAllColumns} 
                className="text-xs px-2.5 py-1 rounded-lg bg-white/5 hover:bg-white/10 text-slate-300 hover:text-white border border-white/10 transition-colors"
              >
                Select All
              </button>
              <button 
                type="button"
                onClick={handleResetDefaultColumns} 
                className="text-xs px-2.5 py-1 rounded-lg bg-white/5 hover:bg-white/10 text-cyan-400 hover:text-cyan-300 border border-cyan-500/20 transition-colors"
              >
                Reset Defaults
              </button>
              <button 
                type="button"
                onClick={handleDeselectAllColumns} 
                className="text-xs px-2.5 py-1 rounded-lg bg-white/5 hover:bg-white/10 text-rose-400/80 hover:text-rose-300 border border-rose-500/20 transition-colors"
              >
                Clear
              </button>
              <button 
                type="button"
                onClick={() => setShowColumnChooser(false)} 
                className="text-xs px-2.5 py-1 rounded-lg bg-white/10 hover:bg-white/20 text-white transition-colors ml-1"
              >
                Done
              </button>
            </div>
          </div>

          <div className="relative">
            <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              type="text"
              placeholder="Search / filter columns..."
              value={columnFilterText}
              onChange={e => setColumnFilterText(e.target.value)}
              className="w-full bg-slate-900/80 border border-white/10 rounded-lg pl-8 pr-3 py-1.5 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-cyan-400"
            />
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-2.5 max-h-[240px] overflow-y-auto pr-1 custom-scrollbar">
            {data.available_columns
              ?.filter(col => {
                if (!columnFilterText.trim()) return true;
                const query = columnFilterText.toLowerCase();
                const alias = (COLUMN_ALIASES[col] || '').toLowerCase();
                return col.toLowerCase().includes(query) || alias.includes(query);
              })
              .map(col => {
                const isChecked = selectedColumns.includes(col);
                return (
                  <div 
                    key={col} 
                    onClick={() => handleToggleColumn(col)}
                    className={`p-2 rounded-lg border text-xs cursor-pointer flex items-center gap-2 transition-all ${
                      isChecked ? 'border-cyan-400/50 bg-cyan-500/10 text-cyan-300 font-bold' : 'border-white/5 bg-slate-900/60 text-slate-400 hover:text-white'
                    }`}
                  >
                    {isChecked ? <CheckSquare className="w-4 h-4 text-cyan-400 shrink-0" /> : <Square className="w-4 h-4 text-slate-500 shrink-0" />}
                    <span className="truncate" title={col}>{COLUMN_ALIASES[col] || col}</span>
                  </div>
                );
              })}
          </div>
        </div>
      )}

      {/* Bulk Edit Form */}
      {showBulkEdit && (
        <div className="glass-panel p-5 border-l-4 border-purple-400 flex flex-col gap-4 animate-fadeIn">
          <h3 className="text-sm font-bold text-white flex items-center gap-2">
            <Edit3 className="w-4 h-4 text-purple-400" /> Bulk Edit All {data.total_records?.toLocaleString()} Filtered Donor Records
          </h3>
          {bulkMessage && <div className="text-xs font-bold text-emerald-400">{bulkMessage}</div>}

          <form onSubmit={handleBulkEditSubmit} className="flex flex-col gap-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              {/* Field 1 (Required) */}
              <div className="flex flex-col gap-1.5 p-3 rounded-xl border border-white/5 bg-slate-900/40">
                <label className="text-[11px] text-purple-300 font-bold uppercase tracking-wider">Target Field #1 *</label>
                <select 
                  value={bulkCol1} 
                  onChange={e => setBulkCol1(e.target.value)} 
                  className="w-full bg-slate-900 border border-white/10 rounded-lg p-2 text-xs text-white focus:outline-none focus:border-purple-400"
                >
                  <option value="">-- Choose Field --</option>
                  {data.available_columns.map(col => (
                    <option key={col} value={col}>{COLUMN_ALIASES[col] || col}</option>
                  ))}
                </select>
                <input 
                  type="text" 
                  placeholder="New Value #1..." 
                  value={bulkVal1} 
                  onChange={e => setBulkVal1(e.target.value)} 
                  disabled={!bulkCol1}
                  className="w-full bg-slate-900 border border-white/10 rounded-lg p-2 text-xs text-white disabled:opacity-40 disabled:cursor-not-allowed"
                />
              </div>

              {/* Field 2 (Optional) */}
              <div className="flex flex-col gap-1.5 p-3 rounded-xl border border-white/5 bg-slate-900/40">
                <label className="text-[11px] text-slate-400 font-bold uppercase tracking-wider">Target Field #2 (Optional)</label>
                <select 
                  value={bulkCol2} 
                  onChange={e => setBulkCol2(e.target.value)} 
                  className="w-full bg-slate-900 border border-white/10 rounded-lg p-2 text-xs text-white focus:outline-none focus:border-purple-400"
                >
                  <option value="">-- None --</option>
                  {data.available_columns.map(col => (
                    <option key={col} value={col}>{COLUMN_ALIASES[col] || col}</option>
                  ))}
                </select>
                <input 
                  type="text" 
                  placeholder="New Value #2..." 
                  value={bulkVal2} 
                  onChange={e => setBulkVal2(e.target.value)} 
                  disabled={!bulkCol2}
                  className="w-full bg-slate-900 border border-white/10 rounded-lg p-2 text-xs text-white disabled:opacity-40 disabled:cursor-not-allowed"
                />
              </div>

              {/* Field 3 (Optional) */}
              <div className="flex flex-col gap-1.5 p-3 rounded-xl border border-white/5 bg-slate-900/40">
                <label className="text-[11px] text-slate-400 font-bold uppercase tracking-wider">Target Field #3 (Optional)</label>
                <select 
                  value={bulkCol3} 
                  onChange={e => setBulkCol3(e.target.value)} 
                  className="w-full bg-slate-900 border border-white/10 rounded-lg p-2 text-xs text-white focus:outline-none focus:border-purple-400"
                >
                  <option value="">-- None --</option>
                  {data.available_columns.map(col => (
                    <option key={col} value={col}>{COLUMN_ALIASES[col] || col}</option>
                  ))}
                </select>
                <input 
                  type="text" 
                  placeholder="New Value #3..." 
                  value={bulkVal3} 
                  onChange={e => setBulkVal3(e.target.value)} 
                  disabled={!bulkCol3}
                  className="w-full bg-slate-900 border border-white/10 rounded-lg p-2 text-xs text-white disabled:opacity-40 disabled:cursor-not-allowed"
                />
              </div>

              {/* Field 4 (Optional) */}
              <div className="flex flex-col gap-1.5 p-3 rounded-xl border border-white/5 bg-slate-900/40">
                <label className="text-[11px] text-slate-400 font-bold uppercase tracking-wider">Target Field #4 (Optional)</label>
                <select 
                  value={bulkCol4} 
                  onChange={e => setBulkCol4(e.target.value)} 
                  className="w-full bg-slate-900 border border-white/10 rounded-lg p-2 text-xs text-white focus:outline-none focus:border-purple-400"
                >
                  <option value="">-- None --</option>
                  {data.available_columns.map(col => (
                    <option key={col} value={col}>{COLUMN_ALIASES[col] || col}</option>
                  ))}
                </select>
                <input 
                  type="text" 
                  placeholder="New Value #4..." 
                  value={bulkVal4} 
                  onChange={e => setBulkVal4(e.target.value)} 
                  disabled={!bulkCol4}
                  className="w-full bg-slate-900 border border-white/10 rounded-lg p-2 text-xs text-white disabled:opacity-40 disabled:cursor-not-allowed"
                />
              </div>
            </div>

            <div className="flex justify-end gap-2 mt-2">
              <button type="button" onClick={() => setShowBulkEdit(false)} className="btn-secondary text-xs">Cancel</button>
              <button type="submit" disabled={bulkSaving} className="btn-primary text-xs">
                {bulkSaving ? 'Saving...' : '⚡ Apply Bulk Changes Now'}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Control Toolbar */}
      <div className="glass-panel p-4 flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          {/* Quick Search */}
          <div className="relative min-w-[280px] max-w-lg flex-1">
            <Search className="w-4 h-4 text-cyan-400 absolute left-3.5 top-3" />
            <input 
              type="text"
              placeholder={searchPlaceholder}
              value={search}
              onChange={e => { setSearch(e.target.value); setCurrentPage(1); }}
              className="w-full bg-slate-900/90 border border-white/10 rounded-xl pl-10 pr-9 py-2.5 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500 transition-all shadow-inner"
            />
            {search && (
              <button
                type="button"
                onClick={() => { setSearch(''); setCurrentPage(1); }}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-white p-1 rounded-md transition-colors"
                title="Clear search text"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>

          {/* Page Size & Record Count */}
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-400 font-bold">Page Size:</span>
              <select 
                value={pageSize} 
                onChange={e => { setPageSize(Number(e.target.value)); setCurrentPage(1); }}
                className="bg-slate-900 border border-white/10 rounded-xl px-3 py-2 text-xs text-white focus:outline-none focus:border-cyan-500 cursor-pointer"
              >
                <option value={50}>50 rows</option>
                <option value={100}>100 rows</option>
                <option value={250}>250 rows</option>
                <option value={500}>500 rows</option>
              </select>
            </div>

            <span className="text-xs text-slate-400 hidden sm:inline">
              Total: <span className="font-bold text-white">{data.total_records?.toLocaleString()}</span> records
            </span>
          </div>
        </div>

        {/* Search Field Scope Toggles */}
        <div className="flex items-center gap-1.5 flex-wrap pt-2 border-t border-white/5">
          <span className="text-[11px] font-bold text-slate-400 mr-1 flex items-center gap-1.5">
            <Filter className="w-3.5 h-3.5 text-cyan-400" /> Search in:
          </span>

          {/* All Fields Button */}
          <button
            type="button"
            onClick={handleToggleAll}
            className={`px-2.5 py-1 rounded-lg text-xs font-semibold transition-all flex items-center gap-1.5 cursor-pointer ${
              isAllActive
                ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/50 shadow-sm font-bold'
                : 'bg-slate-900/80 text-slate-400 border border-white/5 hover:text-slate-200 hover:border-white/10'
            }`}
            title="Search across all fields"
          >
            <span className={`w-1.5 h-1.5 rounded-full ${isAllActive ? 'bg-cyan-400 shadow-glow' : 'bg-slate-500'}`} />
            All Fields
          </button>

          {/* Individual Field Toggle Pills */}
          {SEARCH_TARGET_OPTIONS.filter(opt => opt.id !== 'all').map(target => {
            const isTargetActive = !isAllActive && searchTargets.includes(target.id);
            return (
              <button
                key={target.id}
                type="button"
                onClick={() => handleToggleTarget(target.id)}
                onContextMenu={(e) => handleTargetContextMenu(e, target.id)}
                className={`px-2.5 py-1 rounded-lg text-xs font-semibold transition-all flex items-center gap-1.5 cursor-pointer select-none ${
                  isTargetActive
                    ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/50 shadow-sm font-bold'
                    : isAllActive
                    ? 'bg-slate-900/60 text-slate-400 border border-white/5 hover:text-slate-200 hover:border-white/10'
                    : 'bg-slate-900/40 text-slate-500 border border-white/5 hover:text-slate-300 hover:border-white/10 opacity-70 hover:opacity-100'
                }`}
                title={`${target.title} (Click to toggle on/off, Right-click to isolate)`}
              >
                {isTargetActive && <Check className="w-3 h-3 text-cyan-400" />}
                <span>{target.label}</span>
              </button>
            );
          })}

          {!isAllActive && (
            <button
              type="button"
              onClick={handleToggleAll}
              className="text-[11px] text-slate-400 hover:text-cyan-400 underline ml-2 transition-colors cursor-pointer"
            >
              Reset to All
            </button>
          )}
        </div>

        {/* Cell Message Banner */}
        {cellMessage && (
          <div className="p-2.5 rounded-xl bg-cyan-500/10 border border-cyan-500/30 text-cyan-300 text-xs font-bold flex items-center gap-2 animate-fade-in w-full">
            <Check className="w-4 h-4 text-cyan-400" />
            <span>{cellMessage}</span>
          </div>
        )}
      </div>

      {/* Single Donor Record Edit Modal */}
      {editingDonorModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-md animate-fade-in">
          <div className="bg-slate-900 border border-white/15 rounded-3xl p-6 max-w-xl w-full shadow-2xl flex flex-col gap-5 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between border-b border-white/10 pb-4">
              <div className="flex items-center gap-2.5">
                <div className="p-2.5 rounded-xl bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                  <Edit3 className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-base font-black text-white">
                    Edit Donor Record
                  </h3>
                  <p className="text-xs text-slate-400">
                    {editingDonorModal.row['Display Name'] || editingDonorModal.row['First Name'] || 'Donor Record'} {editingDonorModal.row['Donation ID'] ? `(#${editingDonorModal.row['Donation ID']})` : ''}
                  </p>
                </div>
              </div>
              <button
                onClick={() => setEditingDonorModal(null)}
                className="p-2 rounded-xl text-slate-400 hover:text-white hover:bg-white/10 transition-all cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {editModalMsg && (
              <div className={`p-3 rounded-xl text-xs font-bold flex items-center gap-2 ${editModalMsg.startsWith('✅') ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30' : 'bg-rose-500/15 text-rose-300 border border-rose-500/30'}`}>
                {editModalMsg.startsWith('✅') ? <Check className="w-4 h-4 text-emerald-400" /> : <AlertCircle className="w-4 h-4 text-rose-400" />}
                <span>{editModalMsg}</span>
              </div>
            )}

            <form onSubmit={handleSaveDonorModal} className="flex flex-col gap-4">
              {/* 🎯 Smart Campaign Code Quick-Pick (If Campaign has known code variants) */}
              {(() => {
                const activeCName = (editingDonorModal.fields['Campaign Name'] || editingDonorModal.row['Campaign Name'] || '').trim().toLowerCase();
                const variants = (activeCName && campaignCodesLookup[activeCName]) || [];
                if (variants.length === 0) return null;

                return (
                  <div className="p-3.5 rounded-2xl bg-amber-500/10 border border-amber-500/30 flex flex-col gap-2 shadow-inner">
                    <div className="flex items-center justify-between">
                      <span className="text-[11px] font-bold text-amber-300 uppercase tracking-wider flex items-center gap-1.5">
                        🎯 Campaign Quick-Pick ({variants.length} Code {variants.length > 1 ? 'Variants' : 'Variant'})
                      </span>
                      <span className="text-[10px] text-amber-200/70">Click variant to auto-fill all classification fields</span>
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {variants.map(v => {
                        const isSelected = editingDonorModal.fields['Code']?.trim().toUpperCase() === v.code.toUpperCase();
                        return (
                          <button
                            key={v.code}
                            type="button"
                            onClick={() => {
                              setEditingDonorModal(prev => ({
                                ...prev,
                                fields: {
                                  ...prev.fields,
                                  'Code': v.code,
                                  'Programme Fund': v.programme_fund || '',
                                  'Fund Code': v.fund_code || '',
                                  'Department': v.department || v.heading || 'Unassigned',
                                  'Office': v.office || v.sub_heading || 'Unassigned',
                                  'Portfolio': v.portfolio || '',
                                  'Heading': v.heading || v.department || 'Unassigned',
                                  'Sub-Heading': v.sub_heading || v.office || 'Unassigned',
                                  'Country': v.country || 'Unassigned',
                                  'Zakat Eligibility': v.zakat_eligibility || 'Unassigned'
                                }
                              }));
                            }}
                            className={`px-3 py-1.5 rounded-xl text-xs font-mono font-bold transition-all cursor-pointer flex items-center gap-1.5 ${
                              isSelected
                                ? 'bg-amber-400 text-slate-950 shadow-md shadow-amber-500/30 ring-2 ring-amber-300'
                                : 'bg-slate-800/90 text-amber-300 hover:bg-amber-500/20 border border-amber-500/30'
                            }`}
                          >
                            <span>{v.code}</span>
                            {v.is_primary && <span className="text-[10px] text-emerald-400 font-sans">⭐ Primary</span>}
                            <span className="text-[10px] opacity-70 font-sans font-normal">({v.department || v.heading} • {v.country})</span>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                );
              })()}

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5 text-xs">
                {Object.keys(editingDonorModal.fields).map(field => {
                  const isCodeField = field === 'Code';
                  return (
                    <div key={field} className="flex flex-col gap-1.5">
                      <label className="text-slate-400 font-bold uppercase tracking-wider text-[10px]">
                        {COLUMN_ALIASES[field] || field}
                      </label>
                      <input
                        type="text"
                        list={isCodeField ? "explorer-modal-codes-list" : undefined}
                        value={editingDonorModal.fields[field] || ''}
                        onChange={e => {
                          const val = e.target.value;
                          let updatedFields = {
                            ...editingDonorModal.fields,
                            [field]: val
                          };
                          // If user typed/selected a Code, auto-fill recognized fields
                          if (isCodeField) {
                            const codeKey = (val || '').trim().toLowerCase();
                            if (codeMap[codeKey]) {
                              const cInfo = codeMap[codeKey];
                              const dept = cInfo.Department || cInfo.Heading;
                              const off = cInfo.Office || cInfo['Sub-Heading'];
                              if (dept && dept !== 'Unassigned') {
                                updatedFields['Department'] = dept;
                                updatedFields['Heading'] = dept;
                              }
                              if (off && off !== 'Unassigned') {
                                updatedFields['Office'] = off;
                                updatedFields['Sub-Heading'] = off;
                              }
                              if (cInfo.Portfolio !== undefined) {
                                updatedFields['Portfolio'] = cInfo.Portfolio;
                              }
                              if (cInfo['Programme Fund'] !== undefined) updatedFields['Programme Fund'] = cInfo['Programme Fund'];
                              if (cInfo['Fund Code'] !== undefined) updatedFields['Fund Code'] = cInfo['Fund Code'];
                              if (cInfo['Old Code'] !== undefined) updatedFields['Old Code'] = cInfo['Old Code'];
                              if (cInfo.Country && cInfo.Country !== 'Unassigned') updatedFields['Country'] = cInfo.Country;
                              if (cInfo['Zakat Eligibility'] && cInfo['Zakat Eligibility'] !== 'Unassigned') updatedFields['Zakat Eligibility'] = cInfo['Zakat Eligibility'];
                            }
                          }
                          setEditingDonorModal({
                            ...editingDonorModal,
                            fields: updatedFields
                          });
                        }}
                        className={`bg-slate-950 border border-white/10 rounded-xl px-3 py-2 text-white text-xs focus:outline-none focus:border-cyan-400 transition-all ${
                          isCodeField ? 'font-mono uppercase font-bold text-cyan-400 border-cyan-500/40' : ''
                        }`}
                      />
                    </div>
                  );
                })}
              </div>

              <datalist id="explorer-modal-codes-list">
                {Object.keys(codeMap).map(k => (
                  <option key={k} value={k.toUpperCase()} />
                ))}
              </datalist>

              <div className="flex items-center justify-end gap-3 pt-4 border-t border-white/10">
                <button
                  type="button"
                  onClick={() => setEditingDonorModal(null)}
                  className="px-4 py-2 rounded-xl text-xs font-bold text-slate-400 hover:text-white bg-slate-800 hover:bg-slate-700 transition-all cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={editModalSaving}
                  className="px-5 py-2 rounded-xl text-xs font-bold text-slate-950 bg-gradient-to-r from-emerald-400 to-teal-400 hover:from-emerald-300 hover:to-teal-300 shadow-md shadow-emerald-500/20 transition-all flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
                >
                  {editModalSaving ? (
                    <span>Saving...</span>
                  ) : (
                    <>
                      <Save className="w-3.5 h-3.5" />
                      <span>Save Changes</span>
                    </>
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Sleek Pagination Bar */}
      <div className="glass-panel px-4 py-3 flex flex-wrap items-center justify-between gap-4 text-xs">
        <div className="flex items-center gap-2">
          <button 
            disabled={currentPage <= 1}
            onClick={() => setCurrentPage(prev => Math.max(1, prev - 1))}
            className="btn-secondary text-xs px-3 py-1.5 disabled:opacity-40"
          >
            <ChevronLeft className="w-3.5 h-3.5 inline mr-1" /> Prev
          </button>
          <button 
            disabled={currentPage >= data.total_pages}
            onClick={() => setCurrentPage(prev => Math.min(data.total_pages, prev + 1))}
            className="btn-secondary text-xs px-3 py-1.5 disabled:opacity-40"
          >
            Next <ChevronRight className="w-3.5 h-3.5 inline ml-1" />
          </button>

          <span className="badge badge-cyan ml-2">Page {currentPage} of {data.total_pages}</span>
        </div>

        <div className="text-slate-400 font-medium">
          Showing <b className="text-cyan-400">{((currentPage - 1) * pageSize) + 1} - {Math.min(currentPage * pageSize, data.total_records)}</b> of <b className="text-white">{data.total_records?.toLocaleString()}</b> total records
        </div>
      </div>

      {/* Main Data Table */}
      {loading ? (
        <div className="py-24 text-center text-slate-400 font-semibold animate-pulse">
          ⚡ Loading Explorer Records...
        </div>
      ) : (
        <div className="glass-panel overflow-hidden border border-white/10 rounded-2xl shadow-2xl">
          <div className="overflow-x-auto max-h-[640px]">
            <table className="crm-table">
              <thead className="sticky top-0 z-20 backdrop-blur-md bg-slate-900/90 border-b border-white/10">
                <tr>
                  <th className="whitespace-nowrap font-extrabold tracking-wider text-center pl-4 w-20">
                    Actions
                  </th>
                  {selectedColumns.map(c => {
                    const isSorted = sortBy === c;
                    return (
                      <th 
                        key={c} 
                        onClick={() => {
                          if (sortBy === c) {
                            if (sortOrder === 'asc') {
                              setSortOrder('desc');
                            } else {
                              setSortBy(null);
                              setSortOrder('asc');
                            }
                          } else {
                            setSortBy(c);
                            setSortOrder('asc');
                          }
                          setCurrentPage(1);
                        }}
                        className="whitespace-nowrap font-extrabold tracking-wider cursor-pointer hover:bg-white/5 select-none transition-colors group"
                      >
                        <div className="flex items-center gap-1.5 justify-between">
                          <span>{COLUMN_ALIASES[c] || c}</span>
                          <span className="text-slate-400 group-hover:text-white transition-colors">
                            {isSorted ? (
                              sortOrder === 'asc' ? <ArrowUp className="w-3.5 h-3.5 text-cyan-400" /> : <ArrowDown className="w-3.5 h-3.5 text-cyan-400" />
                            ) : (
                              <ArrowUpDown className="w-3 h-3 opacity-30 group-hover:opacity-100" />
                            )}
                          </span>
                        </div>
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {data.records?.map((row, rowIdx) => {
                  const hasValidEmail = row['Email'] && !['nan', 'none', '', 'unassigned', 'null'].includes(String(row['Email']).trim().toLowerCase());
                  const donorIdVal = (row['Donor ID'] && !['nan', 'none', '', 'unassigned', 'null', 'donation boost', 'anonymous', 'anonymous kind soul'].includes(String(row['Donor ID']).trim().toLowerCase())) ? row['Donor ID'] : null;
                  const donorKey = hasValidEmail 
                    ? row['Email'] 
                    : (donorIdVal || (row['Donation ID'] ? `ID:${row['Donation ID']}` : (row['Display Name'] || row['First Name'] || 'Anonymous Donor')));
                  return (
                    <tr 
                      key={rowIdx} 
                      className="hover:bg-cyan-500/5 transition-colors group"
                    >
                      {/* Actions Column on Extreme Left */}
                      <td className="whitespace-nowrap text-center pl-4 w-20">
                        <div className="flex items-center justify-center gap-1.5" onClick={e => e.stopPropagation()}>
                          <button
                            type="button"
                            onClick={() => onSelectDonor(donorKey)}
                            className="p-1.5 rounded-lg text-cyan-400 hover:bg-cyan-500/15 transition-all cursor-pointer"
                            title="View Donor Profile Drawer"
                          >
                            <Eye className="w-3.5 h-3.5" />
                          </button>
                          {canEdit && (
                            <button
                              type="button"
                              onClick={() => setEditingDonorModal({
                                row,
                                fields: {
                                  'First Name': row['First Name'] || '',
                                  'Last Name': row['Last Name'] || '',
                                  'Email': row['Email'] || '',
                                  'fundraiser_name': row['fundraiser_name'] || row['Fundraiser Name'] || '',
                                  'Campaign Name': row['Campaign Name'] || '',
                                  'Programme Fund': row['Programme Fund'] || '',
                                  'Fund Code': row['Fund Code'] || '',
                                  'Department': row['Department'] || row['Heading'] || '',
                                  'Office': row['Office'] || row['Sub-Heading'] || '',
                                  'Portfolio': row['Portfolio'] || '',
                                  'Country': row['Country'] || '',
                                  'Code': row['Code'] || '',
                                  'Old Code': row['Old Code'] || '',
                                  'Zakat Eligibility': row['Zakat Eligibility'] || ''
                                }
                              })}
                              className="p-1.5 rounded-lg text-emerald-400 hover:bg-emerald-500/15 transition-all cursor-pointer"
                              title="Edit Donor Record Details"
                            >
                              <Edit3 className="w-3.5 h-3.5" />
                            </button>
                          )}
                        </div>
                      </td>

                      {selectedColumns.map(c => {
                        const val = row[c];

                        if (c === 'First Name' || c === 'Display Name') {
                          const isSettled = String(row['Payout Settled'] || row['payout_settled'] || '').toLowerCase() === 'yes';
                          return (
                            <td 
                              key={c} 
                              className="whitespace-nowrap font-medium"
                            >
                              <div className="flex items-center gap-2">
                                <button
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    onSelectDonor(donorKey);
                                  }}
                                  className="text-cyan-400 hover:text-cyan-300 font-bold hover:underline flex items-center gap-1.5 cursor-pointer text-left"
                                  title="Click to view donor detail side view"
                                >
                                  <Eye className="w-3 h-3 opacity-60 group-hover:opacity-100" />
                                  <span>{val || 'Unnamed Donor'}</span>
                                </button>
                                {isSettled && (
                                  <span className="text-[10px] px-2 py-0.5 rounded-full font-extrabold uppercase bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30 shadow-sm" title="Donor transaction settled in payout bank transfer">
                                    Settled
                                  </span>
                                )}
                              </div>
                            </td>
                          );
                        }
                        if (c === 'Total Online Donations Net Amount in Settled Currency' || typeof val === 'number') {
                          return (
                            <td 
                              key={c} 
                              className="font-mono text-cyan-400 font-extrabold whitespace-nowrap"
                            >
                              £{typeof val === 'number' ? val.toFixed(2) : parseFloat(val || 0).toFixed(2)}
                            </td>
                          );
                        }
                        if (c === 'Lifetime Donor Classification' || c === 'Transaction Donor Classification') {
                          return (
                            <td 
                              key={c} 
                              className="whitespace-nowrap"
                            >
                              <span className={`badge ${getTierBadgeClass(val)}`}>{val || 'Unassigned'}</span>
                            </td>
                          );
                        }
                        if (c === 'fundraiser_name' || c === 'Fundraiser Name') {
                          return (
                            <td key={c} className="whitespace-nowrap">
                              {val ? (
                                <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-bold bg-amber-500/10 text-amber-400 border border-amber-500/20 shadow-sm">
                                  🤝 {val}
                                </span>
                              ) : (
                                <span className="text-slate-500 italic text-xs">Unassigned</span>
                              )}
                            </td>
                          );
                        }
                        if (c === 'Created Date (UTC)') {
                          return (
                            <td 
                              key={c} 
                              className="text-slate-400 text-xs font-mono whitespace-nowrap"
                            >
                              {formatDate(val)}
                            </td>
                          );
                        }
                        if (c === 'Programme Fund') {
                          return (
                            <td key={c} className="whitespace-nowrap">
                              {val && String(val).trim() && !['nan', 'none', 'unassigned', ''].includes(String(val).trim().toLowerCase()) ? (
                                <span className="inline-flex items-center px-2.5 py-1 rounded-lg text-xs font-bold bg-purple-500/15 text-purple-300 border border-purple-500/30">
                                  {val}
                                </span>
                              ) : (
                                <span className="text-slate-500 italic text-xs">Unassigned</span>
                              )}
                            </td>
                          );
                        }
                        if (c === 'Code') {
                          return (
                            <td key={c} className="whitespace-nowrap">
                              {val && String(val).trim() && !['nan', 'none', 'unassigned', ''].includes(String(val).trim().toLowerCase()) ? (
                                <span className="font-mono text-cyan-400 font-bold text-xs bg-cyan-500/10 border border-cyan-500/20 px-2 py-0.5 rounded">
                                  {val}
                                </span>
                              ) : (
                                <span className="text-slate-500 italic text-xs">Unassigned</span>
                              )}
                            </td>
                          );
                        }
                        if (c === 'Old Code') {
                          return (
                            <td key={c} className="whitespace-nowrap">
                              {val && String(val).trim() && !['nan', 'none', 'unassigned', ''].includes(String(val).trim().toLowerCase()) ? (
                                <span className="font-mono text-slate-400 text-xs bg-slate-800/60 border border-slate-700/40 px-2 py-0.5 rounded" title="Legacy Allocation Code">
                                  {val}
                                </span>
                              ) : (
                                <span className="text-slate-600 text-xs">—</span>
                              )}
                            </td>
                          );
                        }
                        return (
                          <td 
                            key={c} 
                            className="max-w-[240px] truncate text-slate-200"
                          >
                            {val !== undefined && val !== null ? String(val) : ''}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
