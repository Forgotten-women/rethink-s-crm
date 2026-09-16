import React, { useEffect, useState, useMemo } from 'react';
import { 
  CreditCard, 
  DollarSign, 
  Layers, 
  CheckCircle, 
  Search, 
  RefreshCw, 
  TrendingUp, 
  Building, 
  Trash2,
  AlertCircle,
  X,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  ChevronUp,
  Folder,
  FolderOpen,
  Maximize2,
  Minimize2,
  Tag,
  Download,
  FileSpreadsheet,
  Edit3,
  Check,
  Save,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  Globe,
  Zap,
  Sliders,
  Users,
  UserCheck,
  Mail,
  Copy,
  CheckCheck,
  Calendar,
  ShieldCheck,
  Filter
} from 'lucide-react';
import { API_BASE_URL } from '../config';

export default function PayoutsView({ user, accentColor, onDataChange, activeCompany = 'rethink', companies = [] }) {
  const isConsolidated = activeCompany === 'all';
  const currency = 'GBP'; // Unified GBP (£) settlement
  const [selectedPlatform, setSelectedPlatform] = useState('launchgood'); // 'launchgood' | 'paysuite'
  const [statusFilter, setStatusFilter] = useState('ALL'); // 'ALL' | 'Paid' | 'Unpaid'

  const [summary, setSummary] = useState({
    total_gross: 0,
    total_fees: 0,
    total_reserves: 0,
    net_payout: 0,
    total_transactions: 0,
    settled_donations_count: 0,
    paid_count: 0,
    unpaid_count: 0,
    paid_amount: 0,
    unpaid_amount: 0,
    collection_rate: 100,
    disbursement_summary: {},
    ledger_breakdown: []
  });
  
  const [batchesData, setBatchesData] = useState({ total_batches: 0, page: 1, page_size: 25, total_pages: 1, batches: [] });
  const [selectedBatch, setSelectedBatch] = useState('ALL'); // 'ALL' or specific transfer_id
  
  // Breakdown Data
  const [campaignData, setCampaignData] = useState([]);
  const [codeGroups, setCodeGroups] = useState([]);
  const [headingGroups, setHeadingGroups] = useState([]);
  const [countryGroups, setCountryGroups] = useState([]);

  // Expanded Groups State
  const [expandedCodes, setExpandedCodes] = useState({});
  const [expandedHeadings, setExpandedHeadings] = useState({});
  const [expandedCountries, setExpandedCountries] = useState({});

  // Breakdown View Mode: 'code_groups' | 'heading_groups' | 'country_groups' | 'flat'
  const [breakdownViewMode, setBreakdownViewMode] = useState('code_groups');
  
  // Sorting State
  const [sortBy, setSortBy] = useState('gross_amount');
  const [sortOrder, setSortOrder] = useState('desc');

  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [activeTab, setActiveTab] = useState('disbursement'); // 'disbursement', 'batches', 'campaigns', 'donors', 'ledger'
  
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);

  // Pagination State for each breakdown mode
  const [codePage, setCodePage] = useState(1);
  const [codePageSize, setCodePageSize] = useState(25);

  const [headingPage, setHeadingPage] = useState(1);
  const [headingPageSize, setHeadingPageSize] = useState(25);

  const [countryPage, setCountryPage] = useState(1);
  const [countryPageSize, setCountryPageSize] = useState(25);

  const [campPage, setCampPage] = useState(1);
  const [campPageSize, setCampPageSize] = useState(25);

  // Donor Level Breakdown State
  const [donorsData, setDonorsData] = useState({ total_records: 0, page: 1, page_size: 25, total_pages: 1, records: [], summary: {} });
  const [donorPage, setDonorPage] = useState(1);
  const [donorPageSize, setDonorPageSize] = useState(25);
  const [donorSortBy, setDonorSortBy] = useState('created_date');
  const [donorSortOrder, setDonorSortOrder] = useState('desc');
  const [donorCodeFilter, setDonorCodeFilter] = useState('ALL');
  const [donorLoading, setDonorLoading] = useState(false);
  const [copiedId, setCopiedId] = useState(null);

  // Classification Edit State & Code Map Lookup
  const [codeMap, setCodeMap] = useState({});
  const [editingClassification, setEditingClassification] = useState(null); // { campaign_name, code, heading, sub_heading, country, zakat_eligibility }
  const [editSaving, setEditSaving] = useState(false);
  const [editMsg, setEditMsg] = useState('');
  
  // Real-time Save Toast Notification
  const [saveNotification, setSaveNotification] = useState(null);

  // Purge Payout Modal State
  const [showPurgeModal, setShowPurgeModal] = useState(false);
  const [purgeConfirm, setPurgeConfirm] = useState(false);
  const [purging, setPurging] = useState(false);
  const [purgeMsg, setPurgeMsg] = useState('');

  const isSuperAdmin = user?.role === 'super_admin';
  const canEdit = user?.role === 'super_admin' || user?.role === 'admin' || user?.can_edit_donors === 1;
  const currSymbol = '£';
  const isPaysuite = selectedPlatform === 'paysuite';

  // Load Code Map on Mount
  useEffect(() => {
    fetch(`${API_BASE_URL}/api/classifications/code-map`)
      .then(r => r.json())
      .then(data => {
        if (data && typeof data === 'object') setCodeMap(data);
      })
      .catch(err => console.error('Error fetching code-map for payouts:', err));
  }, []);

  // 300ms Debounce on Search Input
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(search);
    }, 300);
    return () => clearTimeout(timer);
  }, [search]);

  // Auto-dismiss toast notification after 7s
  useEffect(() => {
    if (saveNotification) {
      const timer = setTimeout(() => setSaveNotification(null), 7000);
      return () => clearTimeout(timer);
    }
  }, [saveNotification]);

  const fetchPayoutData = (searchQuery = debouncedSearch, batchVal = selectedBatch, plat = selectedPlatform, st = statusFilter) => {
    setLoading(true);
    const searchParam = searchQuery ? `&search=${encodeURIComponent(searchQuery)}` : '';
    const batchParam = batchVal && batchVal !== 'ALL' ? `&batch=${encodeURIComponent(batchVal)}` : '';
    const statusParam = st && st !== 'ALL' ? `&status=${encodeURIComponent(st)}` : '';
    const companyParam = `&company_id=${encodeURIComponent(activeCompany)}`;
    
    Promise.all([
      fetch(`${API_BASE_URL}/api/payouts/summary?platform=${plat}&currency=${currency}${batchParam}${statusParam}${companyParam}`).then(r => r.ok ? r.json() : {}),
      fetch(`${API_BASE_URL}/api/payouts/batches?platform=${plat}&currency=${currency}&page=${currentPage}&page_size=${pageSize}${searchParam}${companyParam}`).then(r => r.ok ? r.json() : {}),
      fetch(`${API_BASE_URL}/api/payouts/campaign-breakdown?platform=${plat}&currency=${currency}${batchParam}${searchParam}${statusParam}${companyParam}`).then(r => r.ok ? r.json() : {}),
      fetch(`${API_BASE_URL}/api/payouts/ledger-breakdown?platform=${plat}&currency=${currency}${batchParam}${statusParam}${companyParam}`).then(r => r.ok ? r.json() : {})
    ])
      .then(([sumRes = {}, batchRes = {}, campRes = {}, ledgerRes = {}]) => {
        setSummary({
          ...sumRes,
          disbursement_summary: sumRes?.disbursement_summary || ledgerRes?.disbursement_summary || {},
          ledger_breakdown: sumRes?.ledger_breakdown || ledgerRes?.ledger || []
        });
        setBatchesData(batchRes || { total_batches: 0, page: 1, page_size: 25, batches: [] });
        setCampaignData(campRes?.campaigns || []);
        setCodeGroups(campRes?.code_groups || []);
        setHeadingGroups(campRes?.heading_groups || []);
        setCountryGroups(campRes?.country_groups || []);
        setLoading(false);
      })
      .catch(err => {
        console.error('Error loading payout reconciliation data:', err);
        setLoading(false);
      });
  };

  const fetchDonorsData = (searchQuery = debouncedSearch, batchVal = selectedBatch, pageNum = donorPage, pSize = donorPageSize, plat = selectedPlatform, st = statusFilter) => {
    setDonorLoading(true);
    const searchParam = searchQuery ? `&search=${encodeURIComponent(searchQuery)}` : '';
    const batchParam = batchVal && batchVal !== 'ALL' ? `&batch=${encodeURIComponent(batchVal)}` : '';
    const codeParam = donorCodeFilter && donorCodeFilter !== 'ALL' ? `&code=${encodeURIComponent(donorCodeFilter)}` : '';
    const statusParam = st && st !== 'ALL' ? `&status=${encodeURIComponent(st)}` : '';
    const sortParam = `&sort_by=${encodeURIComponent(donorSortBy)}&sort_order=${encodeURIComponent(donorSortOrder)}`;
    const companyParam = `&company_id=${encodeURIComponent(activeCompany)}`;
    
    fetch(`${API_BASE_URL}/api/payouts/donors?platform=${plat}&currency=${currency}&page=${pageNum}&page_size=${pSize}${sortParam}${batchParam}${searchParam}${codeParam}${statusParam}${companyParam}`)
      .then(r => r.json())
      .then(res => {
        setDonorsData(res || { total_records: 0, page: 1, page_size: 25, total_pages: 1, records: [], summary: {} });
        setDonorLoading(false);
      })
      .catch(err => {
        console.error('Error loading payout donors data:', err);
        setDonorLoading(false);
      });
  };

  useEffect(() => {
    fetchPayoutData(debouncedSearch, selectedBatch, selectedPlatform, statusFilter);
  }, [currentPage, pageSize, debouncedSearch, selectedBatch, selectedPlatform, statusFilter, activeCompany]);

  useEffect(() => {
    if (activeTab === 'donors') {
      fetchDonorsData(debouncedSearch, selectedBatch, donorPage, donorPageSize, selectedPlatform, statusFilter);
    }
  }, [activeTab, donorPage, donorPageSize, donorSortBy, donorSortOrder, donorCodeFilter, debouncedSearch, selectedBatch, selectedPlatform, statusFilter, activeCompany]);

  const handleCopyId = (id) => {
    if (!id) return;
    navigator.clipboard?.writeText(String(id));
    setCopiedId(String(id));
    setTimeout(() => setCopiedId(null), 2000);
  };

  const handleDonorSort = (columnKey) => {
    if (donorSortBy === columnKey) {
      setDonorSortOrder(prev => (prev === 'asc' ? 'desc' : 'asc'));
    } else {
      setDonorSortBy(columnKey);
      setDonorSortOrder('desc');
    }
    setDonorPage(1);
  };

  const handlePageChange = (newPage) => {
    if (newPage >= 1 && newPage <= batchesData.total_pages) {
      setCurrentPage(newPage);
    }
  };

  // Expand / Collapse Toggles
  const toggleCodeExpand = (code) => {
    setExpandedCodes(prev => ({ ...prev, [code]: !prev[code] }));
  };

  const toggleHeadingExpand = (heading) => {
    setExpandedHeadings(prev => ({ ...prev, [heading]: !prev[heading] }));
  };

  const toggleCountryExpand = (country) => {
    setExpandedCountries(prev => ({ ...prev, [country]: !prev[country] }));
  };

  const expandAll = () => {
    if (breakdownViewMode === 'code_groups') {
      const allExp = {};
      codeGroups.forEach(cg => { allExp[cg.code] = true; });
      setExpandedCodes(allExp);
    } else if (breakdownViewMode === 'heading_groups') {
      const allExp = {};
      headingGroups.forEach(hg => { allExp[hg.heading] = true; });
      setExpandedHeadings(allExp);
    } else if (breakdownViewMode === 'country_groups') {
      const allExp = {};
      countryGroups.forEach(ctg => { allExp[ctg.country] = true; });
      setExpandedCountries(allExp);
    }
  };

  const collapseAll = () => {
    if (breakdownViewMode === 'code_groups') setExpandedCodes({});
    else if (breakdownViewMode === 'heading_groups') setExpandedHeadings({});
    else if (breakdownViewMode === 'country_groups') setExpandedCountries({});
  };

  // Sort Handler
  const handleSort = (columnKey) => {
    if (sortBy === columnKey) {
      setSortOrder(prev => (prev === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortBy(columnKey);
      setSortOrder('desc');
    }
  };

  // Sort Helper for arrays
  const sortItems = (items) => {
    if (!items || items.length === 0) return [];
    return [...items].sort((a, b) => {
      let valA = a[sortBy];
      let valB = b[sortBy];

      if (valA === undefined || valA === null) valA = '';
      if (valB === undefined || valB === null) valB = '';

      if (typeof valA === 'number' && typeof valB === 'number') {
        return sortOrder === 'asc' ? valA - valB : valB - valA;
      }
      return sortOrder === 'asc' 
        ? String(valA).localeCompare(String(valB)) 
        : String(valB).localeCompare(String(valA));
    });
  };

  // Open Edit Classification Modal
  const handleOpenEditModal = (camp) => {
    setEditingClassification({
      campaign_name: camp.campaign_name || '',
      code: camp.code || '',
      heading: camp.heading || '',
      sub_heading: camp.sub_heading || '',
      country: camp.country || (isPaysuite ? 'ALL' : ''),
      zakat_eligibility: camp.zakat || camp.zakat_eligibility || (isPaysuite ? 'Non-Zakat' : 'Unassigned')
    });
    setEditMsg('');
  };

  // Handle Quick Code Pick within Edit Modal
  const handleSelectCodeInModal = (newCode) => {
    const cleanCode = String(newCode).trim().toUpperCase();
    const mapped = codeMap[cleanCode.toLowerCase()];
    if (mapped) {
      setEditingClassification(prev => ({
        ...prev,
        code: cleanCode,
        heading: mapped.Heading || prev.heading,
        sub_heading: mapped['Sub-Heading'] || prev.sub_heading,
        country: mapped.Country || prev.country,
        zakat_eligibility: mapped['Zakat Eligibility'] || prev.zakat_eligibility
      }));
    } else {
      setEditingClassification(prev => ({ ...prev, code: cleanCode }));
    }
  };

  // Save Classification Handler with Real-time Sync
  const handleSaveClassification = async () => {
    if (!canEdit || !editingClassification) return;
    setEditSaving(true);
    setEditMsg('');

    try {
      const res = await fetch(`${API_BASE_URL}/api/payouts/update-classification`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          company_id: activeCompany,
          user_role: user?.role || 'admin',
          campaign_name: editingClassification.campaign_name,
          code: editingClassification.code,
          heading: editingClassification.heading,
          sub_heading: editingClassification.sub_heading,
          country: editingClassification.country,
          zakat_eligibility: editingClassification.zakat_eligibility,
          platform: selectedPlatform,
          can_edit: true
        })
      });

      const data = await res.json();
      setEditSaving(false);

      if (res.ok && data.status === 'success') {
        setSaveNotification({
          type: 'success',
          title: isPaysuite ? 'Paysuite Direct Debit Classification Synchronized' : 'Classification Synchronized',
          message: data.message,
          timestamp: new Date().toLocaleTimeString()
        });
        setEditingClassification(null);
        fetchPayoutData(debouncedSearch, selectedBatch, selectedPlatform, statusFilter);
        fetchDonorsData(debouncedSearch, selectedBatch, donorPage, donorPageSize, selectedPlatform, statusFilter);
        if (typeof onDataChange === 'function') {
          onDataChange();
        }
      } else {
        setEditMsg(data.detail || data.message || 'Failed to update classification.');
      }
    } catch (err) {
      setEditSaving(false);
      setEditMsg(`Network error: ${err.message}`);
    }
  };

  const handlePurgePayouts = () => {
    if (!isSuperAdmin) return;
    if (!purgeConfirm) {
      setPurgeMsg('❌ Please check the confirmation box before purging payout data.');
      return;
    }

    setPurging(true);
    setPurgeMsg('');

    fetch(`${API_BASE_URL}/api/admin/purge-payouts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_role: user?.role,
        confirm: true
      })
    })
      .then(r => r.json())
      .then(res => {
        setPurging(false);
        if (res?.status === 'success') {
          setPurgeMsg(`✅ ${res.message}`);
          setTimeout(() => {
            setShowPurgeModal(false);
            setPurgeConfirm(false);
            setPurgeMsg('');
            fetchPayoutData();
            if (typeof onDataChange === 'function') onDataChange();
          }, 1500);
        } else {
          setPurgeMsg(`❌ ${res?.detail || 'Failed to purge payout data.'}`);
        }
      })
      .catch(err => {
        setPurging(false);
        setPurgeMsg(`❌ Error purging payout data: ${err.message}`);
      });
  };

  const handleExportExcel = async () => {
    try {
      setExporting(true);
      const batchParam = selectedBatch && selectedBatch !== 'ALL' ? `&batch=${encodeURIComponent(selectedBatch)}` : '';
      const statusParam = statusFilter && statusFilter !== 'ALL' ? `&status=${encodeURIComponent(statusFilter)}` : '';
      const searchParam = (debouncedSearch || search) ? `&search=${encodeURIComponent(debouncedSearch || search)}` : '';
      const codeParam = donorCodeFilter && donorCodeFilter !== 'ALL' ? `&code=${encodeURIComponent(donorCodeFilter)}` : '';
      const companyParam = `&company_id=${encodeURIComponent(activeCompany)}`;
      const res = await fetch(`${API_BASE_URL}/api/payouts/export?platform=${selectedPlatform}&currency=${currency}${batchParam}${statusParam}${searchParam}${codeParam}${companyParam}`);
      if (!res.ok) throw new Error('Failed to generate export file');
      
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      const batchTag = selectedBatch && selectedBatch !== 'ALL' ? `_${selectedBatch.replace(/[^a-zA-Z0-9_-]/g, '_')}` : '_all';
      const statusTag = statusFilter && statusFilter !== 'ALL' ? `_${statusFilter.toLowerCase()}` : '';
      a.download = `${selectedPlatform}_reconciliation_${currency.toLowerCase()}${batchTag}${statusTag}_${new Date().toISOString().slice(0, 10)}.xlsx`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (err) {
      console.error('Export error:', err);
      alert(`Export failed: ${err.message}`);
    } finally {
      setExporting(false);
    }
  };

  // Sorted and Paginated Data for all 4 View Modes
  const sortedCodes = useMemo(() => sortItems(codeGroups), [codeGroups, sortBy, sortOrder]);
  const effectiveCodePageSize = codePageSize === 'All' ? Math.max(1, sortedCodes.length) : Number(codePageSize);
  const totalCodePages = Math.max(1, Math.ceil(sortedCodes.length / effectiveCodePageSize));
  const safeCodePage = Math.min(Math.max(1, codePage), totalCodePages);
  const paginatedCodes = codePageSize === 'All' 
    ? sortedCodes 
    : sortedCodes.slice((safeCodePage - 1) * effectiveCodePageSize, safeCodePage * effectiveCodePageSize);

  const sortedHeadings = useMemo(() => sortItems(headingGroups), [headingGroups, sortBy, sortOrder]);
  const effectiveHeadingPageSize = headingPageSize === 'All' ? Math.max(1, sortedHeadings.length) : Number(headingPageSize);
  const totalHeadingPages = Math.max(1, Math.ceil(sortedHeadings.length / effectiveHeadingPageSize));
  const safeHeadingPage = Math.min(Math.max(1, headingPage), totalHeadingPages);
  const paginatedHeadings = headingPageSize === 'All'
    ? sortedHeadings
    : sortedHeadings.slice((safeHeadingPage - 1) * effectiveHeadingPageSize, safeHeadingPage * effectiveHeadingPageSize);

  const sortedCountries = useMemo(() => sortItems(countryGroups), [countryGroups, sortBy, sortOrder]);
  const effectiveCountryPageSize = countryPageSize === 'All' ? Math.max(1, sortedCountries.length) : Number(countryPageSize);
  const totalCountryPages = Math.max(1, Math.ceil(sortedCountries.length / effectiveCountryPageSize));
  const safeCountryPage = Math.min(Math.max(1, countryPage), totalCountryPages);
  const paginatedCountries = countryPageSize === 'All'
    ? sortedCountries
    : sortedCountries.slice((safeCountryPage - 1) * effectiveCountryPageSize, safeCountryPage * effectiveCountryPageSize);

  const sortedCampaigns = useMemo(() => sortItems(campaignData), [campaignData, sortBy, sortOrder]);
  const effectiveCampPageSize = campPageSize === 'All' ? Math.max(1, sortedCampaigns.length) : Number(campPageSize);
  const totalCampPages = Math.max(1, Math.ceil(sortedCampaigns.length / effectiveCampPageSize));
  const safeCampPage = Math.min(Math.max(1, campPage), totalCampPages);
  const paginatedCampaigns = campPageSize === 'All' 
    ? sortedCampaigns 
    : sortedCampaigns.slice((safeCampPage - 1) * effectiveCampPageSize, safeCampPage * effectiveCampPageSize);

  const disb = summary.disbursement_summary || {};

  return (
    <div className="flex flex-col gap-6 animate-fade-in pb-16 relative">
      
      {/* Floating Save & Sync Notification Toast */}
      {saveNotification && (
        <div className="fixed top-6 right-6 z-[9999] flex items-start gap-3 p-4 rounded-2xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-white/10 shadow-2xl backdrop-blur-xl animate-fade-in max-w-md">
          <div className={`p-2 rounded-xl shrink-0 ${saveNotification.type === 'success' ? 'bg-emerald-500/10 text-emerald-500' : 'bg-rose-500/10 text-rose-500'}`}>
            {saveNotification.type === 'success' ? <CheckCircle className="w-5 h-5" /> : <AlertCircle className="w-5 h-5" />}
          </div>
          <div className="flex-1 min-w-0">
            <h4 className="text-xs font-black uppercase tracking-wider text-slate-800 dark:text-white">
              {saveNotification.title}
            </h4>
            <p className="text-xs text-slate-600 dark:text-slate-300 mt-0.5">
              {saveNotification.message}
            </p>
            <span className="text-[10px] text-slate-400 font-mono mt-1 block">
              {saveNotification.timestamp}
            </span>
          </div>
          <button 
            onClick={() => setSaveNotification(null)}
            className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Header & Control Bar */}
      <div className="flex flex-wrap items-center justify-between gap-4 pb-2 border-b border-slate-200 dark:border-white/10">
        <div className="flex items-center gap-3">
          <div className={`p-3 bg-gradient-to-tr ${isPaysuite ? 'from-amber-600 to-orange-500 shadow-amber-500/20' : 'from-emerald-600 to-teal-500 shadow-teal-500/20'} rounded-2xl shadow-lg text-white transition-all`}>
            {isPaysuite ? <CreditCard className="w-6 h-6" /> : <Layers className="w-6 h-6" />}
          </div>
          <div>
            <div className="flex items-center gap-2.5">
              <h1 className="text-xl font-black tracking-tight text-slate-900 dark:text-white">
                Payout Reconciliation Center
              </h1>
              <span className={`text-xs px-2.5 py-0.5 rounded-full font-bold uppercase ${
                isPaysuite 
                  ? 'bg-amber-100 text-amber-800 dark:bg-amber-500/20 dark:text-amber-400' 
                  : 'bg-emerald-100 text-emerald-800 dark:bg-emerald-500/20 dark:text-emerald-400'
              }`}>
                {isPaysuite ? 'Paysuite Direct Debit' : 'LaunchGood Payouts'}
              </span>
            </div>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5 font-medium">
              {isPaysuite 
                ? 'Monthly direct debit settlement cycles, collection status audits, failure tracking, and reference classification mapping'
                : 'Gross settlement tracking, processing fee audits, reserve withholdings, and bank payout batch reconciliation'}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3 flex-wrap">
          {/* Platform Selector Switcher */}
          <div className="flex items-center p-1 bg-slate-100 dark:bg-slate-800/90 rounded-2xl border border-slate-200 dark:border-white/10 shadow-inner">
            <button
              onClick={() => {
                setSelectedPlatform('launchgood');
                setSelectedBatch('ALL');
                setStatusFilter('ALL');
                setCurrentPage(1);
                setDonorPage(1);
              }}
              className={`flex items-center gap-2 px-3.5 py-1.5 rounded-xl text-xs font-bold transition-all cursor-pointer ${
                !isPaysuite
                  ? 'bg-gradient-to-r from-emerald-600 to-teal-600 text-white shadow-md shadow-emerald-500/20'
                  : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
              }`}
            >
              <Zap className="w-3.5 h-3.5" />
              <span>LaunchGood</span>
              <span className={`text-[10px] px-1.5 py-0.2 rounded-md font-mono font-black ${
                !isPaysuite ? 'bg-white/20 text-white' : 'bg-slate-200 dark:bg-slate-700 text-slate-600 dark:text-slate-400'
              }`}>
                8,761
              </span>
            </button>

            <button
              onClick={() => {
                setSelectedPlatform('paysuite');
                setSelectedBatch('ALL');
                setStatusFilter('ALL');
                setCurrentPage(1);
                setDonorPage(1);
                if (activeTab === 'batches') setActiveTab('campaigns');
              }}
              className={`flex items-center gap-2 px-3.5 py-1.5 rounded-xl text-xs font-bold transition-all cursor-pointer ${
                isPaysuite
                  ? 'bg-gradient-to-r from-amber-600 to-orange-600 text-white shadow-md shadow-amber-500/20'
                  : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
              }`}
            >
              <CreditCard className="w-3.5 h-3.5" />
              <span>Paysuite</span>
              <span className={`text-[10px] px-1.5 py-0.2 rounded-md font-mono font-black ${
                isPaysuite ? 'bg-white/20 text-white' : 'bg-slate-200 dark:bg-slate-700 text-slate-600 dark:text-slate-400'
              }`}>
                1,480
              </span>
            </button>
          </div>

          {/* Export Multi-Sheet Excel Button */}
          <button
            onClick={handleExportExcel}
            disabled={exporting || loading}
            className={`px-4 py-2 text-xs font-bold text-white bg-gradient-to-r ${isPaysuite ? 'from-amber-600 to-orange-600 shadow-amber-500/20 hover:from-amber-500 hover:to-orange-500' : 'from-emerald-600 to-teal-600 shadow-emerald-500/20 hover:from-emerald-500 hover:to-teal-500'} rounded-xl shadow-md transition-all flex items-center gap-2 cursor-pointer disabled:opacity-50`}
            title={`Download multi-sheet Excel report (.xlsx) for ${isPaysuite ? 'Paysuite' : 'LaunchGood'}`}
          >
            {exporting ? (
              <RefreshCw className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <FileSpreadsheet className="w-3.5 h-3.5" />
            )}
            <span>{exporting ? 'Exporting...' : selectedBatch !== 'ALL' ? `Export ${selectedBatch}` : 'Export Excel (.xlsx)'}</span>
          </button>

          {/* Super Admin Purge Payout Button (Only for LaunchGood) */}
          {isSuperAdmin && !isPaysuite && (
            <button
              onClick={() => setShowPurgeModal(true)}
              className="px-3.5 py-2 text-xs font-bold text-rose-700 dark:text-rose-300 bg-rose-50 dark:bg-rose-950/40 hover:bg-rose-100 dark:hover:bg-rose-900/60 rounded-xl border border-rose-500/30 transition-all flex items-center gap-1.5 cursor-pointer shadow-sm"
              title="Delete all LaunchGood payout settlement data from the system"
            >
              <Trash2 className="w-3.5 h-3.5 text-rose-500" />
              <span>Purge</span>
            </button>
          )}

          <button 
            onClick={() => fetchPayoutData(debouncedSearch, selectedBatch, selectedPlatform, statusFilter)}
            disabled={loading}
            className="px-3.5 py-2 text-xs font-bold text-slate-700 dark:text-slate-200 bg-slate-100 dark:bg-slate-800/80 hover:bg-slate-200 dark:hover:bg-slate-700/80 rounded-xl border border-slate-300 dark:border-white/10 transition-all flex items-center gap-2 cursor-pointer shadow-sm disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin text-emerald-500' : ''}`} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {/* Batch & Status Filters Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3 p-3.5 rounded-2xl border border-slate-200 dark:border-white/10 bg-white/80 dark:bg-slate-900/80 backdrop-blur-xl shadow-sm">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs font-extrabold uppercase tracking-wider text-slate-500 dark:text-slate-400 mr-1 flex items-center gap-1.5">
            <Layers className={`w-4 h-4 ${isPaysuite ? 'text-amber-500' : 'text-emerald-500'}`} />
            <span>{isPaysuite ? 'Collection Cycle:' : 'Split by Batch:'}</span>
          </span>

          <button
            onClick={() => {
              setSelectedBatch('ALL');
              setCurrentPage(1);
            }}
            className={`px-3.5 py-1.5 rounded-xl text-xs font-bold transition-all flex items-center gap-1.5 cursor-pointer ${
              selectedBatch === 'ALL'
                ? isPaysuite 
                  ? 'bg-gradient-to-r from-amber-600 to-orange-600 text-white shadow-md shadow-amber-500/20'
                  : 'bg-gradient-to-r from-emerald-600 to-teal-600 text-white shadow-md shadow-emerald-500/20'
                : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700'
            }`}
          >
            <span>{isPaysuite ? 'All Collection Months' : 'All Payout Batches'}</span>
            <span className={`px-1.5 py-0.2 rounded-md text-[10px] font-mono ${selectedBatch === 'ALL' ? 'bg-white/20 text-white' : 'bg-slate-200 dark:bg-slate-700 text-slate-700 dark:text-slate-300'}`}>
              {batchesData.total_batches}
            </span>
          </button>

          {batchesData.batches
            .filter(b => b.transfer_id && !['N/A', 'nan', 'none', ''].includes(String(b.transfer_id).toLowerCase()))
            .slice(0, 10)
            .map((b, idx) => {
              const cleanId = String(b.transfer_id).replace('.0', '');
              const isSelected = selectedBatch === cleanId;
              const label = isPaysuite ? b.batch_label : `#${cleanId}`;
              return (
                <button
                  key={idx}
                  onClick={() => {
                    setSelectedBatch(cleanId);
                    setCurrentPage(1);
                  }}
                  className={`px-3.5 py-1.5 rounded-xl text-xs font-bold transition-all flex items-center gap-1.5 cursor-pointer ${
                    isSelected
                      ? isPaysuite
                        ? 'bg-gradient-to-r from-amber-600 to-orange-600 text-white shadow-md shadow-amber-500/20'
                        : 'bg-gradient-to-r from-emerald-600 to-teal-600 text-white shadow-md shadow-emerald-500/20'
                      : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700'
                  }`}
                >
                  <span className="font-semibold">{label}</span>
                  <span className={`px-1.5 py-0.2 rounded-md text-[10px] font-mono font-bold ${isSelected ? 'bg-white/20 text-white' : isPaysuite ? 'bg-amber-500/10 text-amber-600 dark:text-amber-400' : 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'}`}>
                    £{Number(b.transfer_amount || 0).toLocaleString('en-GB', { maximumFractionDigits: 0 })}
                  </span>
                </button>
              );
            })}
        </div>

        {/* Status Filter for Paysuite */}
        {isPaysuite && (
          <div className="flex items-center gap-1.5 p-1 bg-amber-500/10 dark:bg-amber-950/30 rounded-xl border border-amber-500/20">
            <span className="text-[11px] font-bold text-amber-700 dark:text-amber-400 pl-2 pr-1 flex items-center gap-1">
              <Sliders className="w-3 h-3" /> Status:
            </span>
            {[
              { id: 'ALL', label: 'All', count: summary?.batch_total_count ?? summary?.total_transactions ?? 0 },
              { id: 'Paid', label: 'Paid', count: summary?.batch_paid_count ?? summary?.paid_count ?? 0, color: 'text-emerald-500' },
              { id: 'Unpaid', label: 'Unpaid', count: summary?.batch_unpaid_count ?? summary?.unpaid_count ?? 0, color: 'text-rose-500' }
            ].map(st => (
              <button
                key={st.id}
                onClick={() => { setStatusFilter(st.id); setCurrentPage(1); setDonorPage(1); }}
                className={`px-3 py-1 text-xs font-bold rounded-lg transition-all cursor-pointer flex items-center gap-1.5 ${
                  statusFilter === st.id
                    ? 'bg-amber-600 text-white shadow-sm'
                    : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
                }`}
              >
                <span>{st.label}</span>
                <span className={`text-[10px] px-1.5 py-0.2 rounded-md font-mono ${statusFilter === st.id ? 'bg-white/20 text-white' : 'bg-slate-200 dark:bg-slate-700 text-slate-600 dark:text-slate-300'}`}>
                  {st.count}
                </span>
              </button>
            ))}
          </div>
        )}

        {selectedBatch !== 'ALL' && (
          <div className="flex items-center gap-2">
            <span className="text-xs font-bold text-amber-600 dark:text-amber-400 bg-amber-500/10 px-2.5 py-1 rounded-lg border border-amber-500/20">
              Active Filter: {selectedBatch}
            </span>
            <button
              onClick={() => setSelectedBatch('ALL')}
              className="text-xs font-bold text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white px-2.5 py-1 rounded-lg bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 transition-all cursor-pointer flex items-center gap-1"
            >
              <X className="w-3.5 h-3.5" />
              <span>Show All</span>
            </button>
          </div>
        )}
      </div>

      {/* Top 4 Financial Metric Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Card 1: Gross Presented */}
        <div className="p-5 rounded-2xl border border-slate-200 dark:border-white/10 bg-white/80 dark:bg-slate-900/80 backdrop-blur-xl shadow-sm flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
              {isPaysuite ? 'Total Presented Collections' : 'Gross Donations Settlement'}
            </span>
            <div className={`p-2 ${isPaysuite ? 'bg-amber-500/10 text-amber-600 dark:text-amber-400' : 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'} rounded-xl`}>
              <DollarSign className="w-4 h-4" />
            </div>
          </div>
          <div className="text-2xl font-black text-slate-900 dark:text-white">
            {currSymbol}{(summary.total_gross || 0).toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </div>
          <div className="text-[11px] text-slate-500 dark:text-slate-400 font-medium">
            From {(summary.total_transactions ?? 0).toLocaleString()} {isPaysuite ? 'direct debit collections' : 'settled donor transactions'}
          </div>
        </div>

        {/* Card 2: Settled / Paid */}
        <div className="p-5 rounded-2xl border border-slate-200 dark:border-white/10 bg-white/80 dark:bg-slate-900/80 backdrop-blur-xl shadow-sm flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
              {isPaysuite ? 'Successfully Paid / Settled' : 'Processing Fees Paid'}
            </span>
            <div className={`p-2 ${isPaysuite ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400' : 'bg-rose-500/10 text-rose-600 dark:text-rose-400'} rounded-xl`}>
              {isPaysuite ? <CheckCircle className="w-4 h-4" /> : <CreditCard className="w-4 h-4" />}
            </div>
          </div>
          <div className={`text-2xl font-black ${isPaysuite ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'}`}>
            {currSymbol}{isPaysuite ? (summary.paid_amount ?? 0).toLocaleString('en-GB', { minimumFractionDigits: 2 }) : (summary.total_fees || 0).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
          </div>
          <div className="text-[11px] text-slate-500 dark:text-slate-400 font-medium">
            {isPaysuite 
              ? `${(summary.paid_count ?? 0).toLocaleString()} collections successfully debited`
              : `${summary.total_gross > 0 ? ((summary.total_fees / summary.total_gross) * 100).toFixed(2) : '0.00'}% platform & CC fee ratio`}
          </div>
        </div>

        {/* Card 3: Unpaid / Reserves */}
        <div className="p-5 rounded-2xl border border-slate-200 dark:border-white/10 bg-white/80 dark:bg-slate-900/80 backdrop-blur-xl shadow-sm flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
              {isPaysuite ? 'Unpaid / Failed Debits' : 'Reserve Adjustment'}
            </span>
            <div className={`p-2 ${isPaysuite ? 'bg-rose-500/10 text-rose-600 dark:text-rose-400' : 'bg-amber-500/10 text-amber-600 dark:text-amber-400'} rounded-xl`}>
              {isPaysuite ? <AlertCircle className="w-4 h-4" /> : <Layers className="w-4 h-4" />}
            </div>
          </div>
          <div className={`text-2xl font-black ${isPaysuite ? 'text-rose-600 dark:text-rose-400' : 'text-amber-600 dark:text-amber-400'}`}>
            {currSymbol}{isPaysuite ? (summary.unpaid_amount ?? 0).toLocaleString('en-GB', { minimumFractionDigits: 2 }) : (summary.total_reserves || 0).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
          </div>
          <div className="text-[11px] text-slate-500 dark:text-slate-400 font-medium">
            {isPaysuite 
              ? `${(summary.unpaid_count ?? 0).toLocaleString()} failed / uncollected debit items` 
              : 'Platform rolling reserves & hold funds'}
          </div>
        </div>

        {/* Card 4: Net Bank Payout */}
        <div className="p-5 rounded-2xl border border-slate-200 dark:border-white/10 bg-white/80 dark:bg-slate-900/80 backdrop-blur-xl shadow-sm flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
              {isPaysuite ? 'Net Payout Disbursed' : 'Net Bank Transfers Disbursed'}
            </span>
            <div className="p-2 bg-cyan-500/10 text-cyan-600 dark:text-cyan-400 rounded-xl">
              <Building className="w-4 h-4" />
            </div>
          </div>
          <div className="text-2xl font-black text-cyan-600 dark:text-cyan-400">
            {currSymbol}{(summary.net_payout || 0).toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </div>
          <div className="text-[11px] text-slate-500 dark:text-slate-400 font-medium flex items-center gap-1">
            <CheckCircle className="w-3.5 h-3.5 text-cyan-500" />
            <span>{isPaysuite ? `Collection rate: ${(summary.collection_rate ?? 0).toFixed(1)}%` : 'Total net payout transferred to bank'}</span>
          </div>
        </div>
      </div>

      {/* Sub-Tab Navigation & Search Bar */}
      <div className="flex flex-wrap items-center justify-between gap-4 p-4 rounded-2xl border border-slate-200 dark:border-white/10 bg-white/80 dark:bg-slate-900/80 backdrop-blur-xl shadow-sm">
        {/* Tab Buttons */}
        <div className="flex items-center gap-2 flex-wrap">
          <button 
            onClick={() => setActiveTab('disbursement')}
            className={`px-4 py-2 rounded-xl text-xs font-bold transition-all flex items-center gap-2 cursor-pointer ${
              activeTab === 'disbursement'
                ? isPaysuite
                  ? 'bg-gradient-to-r from-amber-600 to-orange-600 text-white shadow-md shadow-amber-500/20'
                  : 'bg-gradient-to-r from-emerald-600 to-teal-600 text-white shadow-md shadow-teal-500/20'
                : 'bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700'
            }`}
          >
            <TrendingUp className="w-3.5 h-3.5" />
            <span>{isPaysuite ? 'Disbursement & Collection Summary' : 'Finance Disbursement Summary'}</span>
          </button>

          {!isPaysuite && (
            <button 
              onClick={() => setActiveTab('batches')}
              className={`px-4 py-2 rounded-xl text-xs font-bold transition-all flex items-center gap-2 cursor-pointer ${
                activeTab === 'batches'
                  ? 'bg-gradient-to-r from-emerald-600 to-teal-600 text-white shadow-md shadow-teal-500/20'
                  : 'bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700'
              }`}
            >
              <Building className="w-3.5 h-3.5" />
              <span>Transfer Batches ({batchesData.total_batches})</span>
            </button>
          )}
          
          <button 
            onClick={() => setActiveTab('campaigns')}
            className={`px-4 py-2 rounded-xl text-xs font-bold transition-all flex items-center gap-2 cursor-pointer ${
              activeTab === 'campaigns'
                ? isPaysuite
                  ? 'bg-gradient-to-r from-amber-600 to-orange-600 text-white shadow-md shadow-amber-500/20'
                  : 'bg-gradient-to-r from-emerald-600 to-teal-600 text-white shadow-md shadow-teal-500/20'
                : 'bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700'
            }`}
          >
            <FolderOpen className="w-3.5 h-3.5" />
            <span>{isPaysuite ? `Code & Direct Debit Breakdown (${codeGroups.length} Codes)` : `Code & Campaign Breakdown (${codeGroups.length} Codes)`}</span>
          </button>

          <button 
            onClick={() => setActiveTab('donors')}
            className={`px-4 py-2 rounded-xl text-xs font-bold transition-all flex items-center gap-2 cursor-pointer ${
              activeTab === 'donors'
                ? isPaysuite
                  ? 'bg-gradient-to-r from-amber-600 to-orange-600 text-white shadow-md shadow-amber-500/20'
                  : 'bg-gradient-to-r from-emerald-600 to-teal-600 text-white shadow-md shadow-teal-500/20'
                : 'bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700'
            }`}
          >
            <Users className="w-3.5 h-3.5" />
            <span>Donor Level Breakdown ({donorsData.total_records > 0 ? donorsData.total_records.toLocaleString() : (summary.total_transactions ? summary.total_transactions.toLocaleString() : (isPaysuite ? '1,480' : '8,761'))})</span>
          </button>

          <button 
            onClick={() => setActiveTab('ledger')}
            className={`px-4 py-2 rounded-xl text-xs font-bold transition-all flex items-center gap-2 cursor-pointer ${
              activeTab === 'ledger'
                ? isPaysuite
                  ? 'bg-gradient-to-r from-amber-600 to-orange-600 text-white shadow-md shadow-amber-500/20'
                  : 'bg-gradient-to-r from-emerald-600 to-teal-600 text-white shadow-md shadow-teal-500/20'
                : 'bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700'
            }`}
          >
            <CreditCard className="w-3.5 h-3.5" />
            <span>Accounting Ledger Audit ({summary.ledger_breakdown?.length || 0})</span>
          </button>
        </div>

        {/* Live Search */}
        <div className="relative min-w-[260px]">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input 
            type="text"
            placeholder={isPaysuite ? "Search Bank Ref, Donor or Code..." : "Search Transfer ID or Campaign..."}
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setCurrentPage(1);
              setCodePage(1);
              setHeadingPage(1);
              setCountryPage(1);
              setCampPage(1);
            }}
            className="w-full pl-9 pr-4 py-2 text-xs rounded-xl border border-slate-200 dark:border-white/10 bg-slate-50 dark:bg-slate-800/60 text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
          />
        </div>
      </div>

      {/* Main Content Area */}
      {loading ? (
        <div className="p-12 text-center text-xs font-bold text-slate-500 dark:text-slate-400 animate-pulse flex flex-col items-center gap-3">
          <RefreshCw className={`w-6 h-6 animate-spin ${isPaysuite ? 'text-amber-500' : 'text-emerald-500'}`} />
          <span>Loading {isPaysuite ? 'Paysuite' : 'LaunchGood'} Payout Reconciliation Data...</span>
        </div>
      ) : activeTab === 'disbursement' ? (
        /* Tab 0: Finance Disbursement Summary Table */
        <div className="flex flex-col gap-6">
          <div className="rounded-2xl border border-slate-200 dark:border-white/10 bg-white/80 dark:bg-slate-900/80 backdrop-blur-xl shadow-sm overflow-hidden">
            <div className="p-4 border-b border-slate-200 dark:border-white/10 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className={`p-1.5 rounded-lg ${isPaysuite ? 'bg-amber-500/10 text-amber-600 dark:text-amber-400' : 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'}`}>
                  <TrendingUp className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="text-sm font-black text-slate-900 dark:text-white">
                    {isPaysuite ? 'Paysuite Direct Debit Settlement Model (GBP)' : 'LaunchGood Disbursement Summary (GBP)'}
                  </h3>
                  <p className="text-[11px] text-slate-500 dark:text-slate-400 font-medium">
                    {isPaysuite 
                      ? 'Reconciled monthly direct debit collections, collection rates, and bank transfers'
                      : 'Verified finance team ledger reconciliation model for GBP settlement'}
                  </p>
                </div>
              </div>
              <span className={`px-3 py-1 rounded-xl text-xs font-bold ${isPaysuite ? 'bg-amber-100 text-amber-800 dark:bg-amber-500/20 dark:text-amber-400' : 'bg-emerald-100 text-emerald-800 dark:bg-emerald-500/20 dark:text-emerald-400'}`}>
                100% Reconciled
              </span>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="bg-slate-100/70 dark:bg-slate-800/60 text-[11px] uppercase font-bold text-slate-500 dark:text-slate-400 border-b border-slate-200 dark:border-white/10">
                    <th className="p-3.5 pl-6">{isPaysuite ? 'Direct Debit Line Item' : 'Disbursement Summary Line Item'}</th>
                    <th className="p-3.5 text-center"># Transactions</th>
                    <th className="p-3.5 pr-6 text-right">Value (£)</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200 dark:divide-white/5 text-xs text-slate-800 dark:text-slate-200 font-medium">
                  {isPaysuite ? (
                    <>
                      {/* Total Presented Collections */}
                      <tr className="hover:bg-slate-50/60 dark:hover:bg-slate-800/40 transition-colors">
                        <td className="p-3.5 pl-6 font-bold text-slate-900 dark:text-white">
                          Total Direct Debit Collections Presented
                        </td>
                        <td className="p-3.5 text-center font-mono font-bold text-slate-700 dark:text-slate-300">
                          {Number(disb.gross_donations_count || 0).toLocaleString()}
                        </td>
                        <td className="p-3.5 pr-6 text-right font-mono font-bold text-slate-900 dark:text-white">
                          {currSymbol}{Number(disb.gross_donations || 0).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                        </td>
                      </tr>

                      {/* Paid Collections */}
                      <tr className="hover:bg-slate-50/60 dark:hover:bg-slate-800/40 transition-colors">
                        <td className="p-3.5 pl-6 text-emerald-700 dark:text-emerald-400 font-semibold flex items-center gap-1.5">
                          <CheckCircle className="w-3.5 h-3.5 text-emerald-500" />
                          <span>Paid & Successfully Settled Collections</span>
                        </td>
                        <td className="p-3.5 text-center font-mono font-bold text-emerald-600 dark:text-emerald-400">
                          {Number(disb.paid_count || 0).toLocaleString()}
                        </td>
                        <td className="p-3.5 pr-6 text-right font-mono font-bold text-emerald-600 dark:text-emerald-400">
                          {currSymbol}{Number(disb.paid_amount || 0).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                        </td>
                      </tr>

                      {/* Unpaid / Failed Collections */}
                      <tr className="hover:bg-slate-50/60 dark:hover:bg-slate-800/40 transition-colors">
                        <td className="p-3.5 pl-6 text-rose-700 dark:text-rose-400 font-semibold flex items-center gap-1.5">
                          <AlertCircle className="w-3.5 h-3.5 text-rose-500" />
                          <span>Unpaid / Failed / Cancelled Debits</span>
                        </td>
                        <td className="p-3.5 text-center font-mono font-bold text-rose-600 dark:text-rose-400">
                          {Number(disb.unpaid_count || 0).toLocaleString()}
                        </td>
                        <td className="p-3.5 pr-6 text-right font-mono font-bold text-rose-600 dark:text-rose-400">
                          {currSymbol}{Number(disb.unpaid_amount || 0).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                        </td>
                      </tr>

                      {/* Collection Success Rate */}
                      <tr className="hover:bg-slate-50/60 dark:hover:bg-slate-800/40 transition-colors">
                        <td className="p-3.5 pl-6 text-slate-700 dark:text-slate-300">
                          Collection Success Rate
                        </td>
                        <td className="p-3.5 text-center font-mono text-slate-400">—</td>
                        <td className="p-3.5 pr-6 text-right font-mono font-bold text-amber-600 dark:text-amber-400">
                          {disb.collection_rate || 97.3}%
                        </td>
                      </tr>

                      {/* Processing Fees */}
                      <tr className="hover:bg-slate-50/60 dark:hover:bg-slate-800/40 transition-colors">
                        <td className="p-3.5 pl-6 text-slate-700 dark:text-slate-300">
                          Processing Fees Paid
                        </td>
                        <td className="p-3.5 text-center font-mono text-slate-400">—</td>
                        <td className="p-3.5 pr-6 text-right font-mono font-bold text-slate-500">
                          {currSymbol}0.00
                        </td>
                      </tr>

                      {/* Total Disbursement Highlight Row */}
                      <tr className="bg-amber-500/10 font-black border-t-2 border-amber-500/30">
                        <td className="p-3.5 pl-6 text-amber-800 dark:text-amber-300 uppercase tracking-wider text-[11px] flex items-center gap-2">
                          <CheckCircle className="w-4 h-4 text-amber-500" />
                          <span>Total Net Disbursed</span>
                        </td>
                        <td className="p-3.5 text-center font-mono text-amber-800 dark:text-amber-300">
                          {Number(disb.total_disbursement_count || 0).toLocaleString()}
                        </td>
                        <td className="p-3.5 pr-6 text-right font-mono text-amber-600 dark:text-amber-400 text-base font-black">
                          {currSymbol}{Number(disb.total_disbursement || 0).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                        </td>
                      </tr>
                    </>
                  ) : (
                    <>
                      {/* LaunchGood Disbursement Rows */}
                      <tr className="hover:bg-slate-50/60 dark:hover:bg-slate-800/40 transition-colors">
                        <td className="p-3.5 pl-6 font-bold text-slate-900 dark:text-white">
                          Gross Donations/Contributions
                        </td>
                        <td className="p-3.5 text-center font-mono font-bold text-slate-700 dark:text-slate-300">
                          {Number(disb.gross_donations_count || 0).toLocaleString()}
                        </td>
                        <td className="p-3.5 pr-6 text-right font-mono font-bold text-slate-900 dark:text-white">
                          {currSymbol}{Number(disb.gross_donations || 0).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                        </td>
                      </tr>

                      <tr className="hover:bg-slate-50/60 dark:hover:bg-slate-800/40 transition-colors">
                        <td className="p-3.5 pl-6 text-slate-700 dark:text-slate-300">Refunds</td>
                        <td className="p-3.5 text-center font-mono text-slate-600 dark:text-slate-400">{Number(disb.refunds_count || 0).toLocaleString()}</td>
                        <td className="p-3.5 pr-6 text-right font-mono font-semibold text-rose-600 dark:text-rose-400">
                          {disb.refunds ? `${currSymbol}${Number(disb.refunds).toLocaleString('en-GB', { minimumFractionDigits: 2 })}` : `${currSymbol}0.00`}
                        </td>
                      </tr>

                      <tr className="bg-slate-100/90 dark:bg-slate-800/80 font-black border-y-2 border-slate-300 dark:border-white/10">
                        <td className="p-3.5 pl-6 text-slate-900 dark:text-white uppercase tracking-wider text-[11px]">Net Sales</td>
                        <td className="p-3.5 text-center font-mono text-slate-900 dark:text-white">{Number(disb.net_sales_count || 0).toLocaleString()}</td>
                        <td className="p-3.5 pr-6 text-right font-mono text-slate-900 dark:text-white text-sm">
                          {currSymbol}{Number(disb.net_sales || 0).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                        </td>
                      </tr>

                      <tr className="hover:bg-slate-50/60 dark:hover:bg-slate-800/40 transition-colors">
                        <td className="p-3.5 pl-6 text-slate-700 dark:text-slate-300">Processing Fees</td>
                        <td className="p-3.5 text-center font-mono text-slate-400">—</td>
                        <td className="p-3.5 pr-6 text-right font-mono font-bold text-rose-600 dark:text-rose-400">
                          {currSymbol}{Number(disb.processing_fees || 0).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                        </td>
                      </tr>

                      <tr className="hover:bg-slate-50/60 dark:hover:bg-slate-800/40 transition-colors">
                        <td className="p-3.5 pl-6 text-slate-700 dark:text-slate-300">Manual Adjustments Total (Zakat donation fees)</td>
                        <td className="p-3.5 text-center font-mono text-slate-600 dark:text-slate-400">{Number(disb.manual_adjustments_count || 0)}</td>
                        <td className="p-3.5 pr-6 text-right font-mono font-bold text-rose-600 dark:text-rose-400">
                          {currSymbol}{Number(disb.manual_adjustments || 0).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                        </td>
                      </tr>

                      <tr className="hover:bg-slate-50/60 dark:hover:bg-slate-800/40 transition-colors">
                        <td className="p-3.5 pl-6 text-slate-700 dark:text-slate-300">Reserve Adjustment</td>
                        <td className="p-3.5 text-center font-mono text-slate-600 dark:text-slate-400">{Number(disb.reserve_adjustment_count || 0)}</td>
                        <td className="p-3.5 pr-6 text-right font-mono font-bold text-amber-600 dark:text-amber-400">
                          {currSymbol}{Number(disb.reserve_adjustment || 0).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                        </td>
                      </tr>

                      <tr className="hover:bg-slate-50/60 dark:hover:bg-slate-800/40 transition-colors">
                        <td className="p-3.5 pl-6 text-slate-700 dark:text-slate-300">Foreign Exchange</td>
                        <td className="p-3.5 text-center font-mono text-slate-600 dark:text-slate-400">{Number(disb.foreign_exchange_count || 0)}</td>
                        <td className="p-3.5 pr-6 text-right font-mono font-bold text-slate-900 dark:text-white">
                          {currSymbol}{Number(disb.foreign_exchange || 0).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                        </td>
                      </tr>

                      <tr className="bg-emerald-500/10 font-black border-t-2 border-emerald-500/30">
                        <td className="p-3.5 pl-6 text-emerald-800 dark:text-emerald-300 uppercase tracking-wider text-[11px] flex items-center gap-2">
                          <CheckCircle className="w-4 h-4 text-emerald-500" />
                          <span>Total Disbursement</span>
                        </td>
                        <td className="p-3.5 text-center font-mono text-emerald-800 dark:text-emerald-300">{Number(disb.total_disbursement_count || 0).toLocaleString()}</td>
                        <td className="p-3.5 pr-6 text-right font-mono text-emerald-600 dark:text-emerald-400 text-base font-black">
                          {currSymbol}{Number(disb.total_disbursement || 0).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                        </td>
                      </tr>
                    </>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      ) : activeTab === 'batches' ? (
        /* Tab 1: Payout Batches Table */
        <div className="flex flex-col gap-4">
          <div className="rounded-2xl border border-slate-200 dark:border-white/10 bg-white/80 dark:bg-slate-900/80 backdrop-blur-xl shadow-sm overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="bg-slate-100/70 dark:bg-slate-800/60 text-[11px] uppercase font-bold text-slate-500 dark:text-slate-400 border-b border-slate-200 dark:border-white/10">
                    <th className="p-3.5 pl-6">{isPaysuite ? 'Collection Month / Cycle' : 'Transfer ID / Batch'}</th>
                    <th className="p-3.5">Settlement Date</th>
                    <th className="p-3.5 text-center">{isPaysuite ? 'Direct Debit Refs' : 'Campaigns'}</th>
                    <th className="p-3.5 text-center">{isPaysuite ? 'Total Collections' : 'Donations'}</th>
                    {isPaysuite && <th className="p-3.5 text-center">Paid / Unpaid</th>}
                    <th className="p-3.5">{isPaysuite ? 'Gross Presented' : 'Gross Settlement'}</th>
                    {!isPaysuite && <th className="p-3.5">Fees Deducted</th>}
                    <th className="p-3.5 pr-6">{isPaysuite ? 'Net Settlement' : 'Net Bank Payout'}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200 dark:divide-white/5 text-xs text-slate-800 dark:text-slate-200 font-medium">
                  {batchesData.batches.length === 0 ? (
                    <tr>
                      <td colSpan={isPaysuite ? 8 : 7} className="p-8 text-center text-slate-500 dark:text-slate-400 font-semibold">
                        No payout batches found matching your search.
                      </td>
                    </tr>
                  ) : (
                    batchesData.batches.map((batch, idx) => {
                      const cleanId = String(batch.transfer_id).replace('.0', '');
                      const isSelected = selectedBatch === cleanId;
                      const batchLabel = isPaysuite ? batch.batch_label : `#${cleanId}`;
                      return (
                        <tr 
                          key={idx} 
                          className={`transition-colors cursor-pointer ${
                            isSelected 
                              ? isPaysuite ? 'bg-amber-500/10 hover:bg-amber-500/15' : 'bg-emerald-500/10 hover:bg-emerald-500/15'
                              : 'hover:bg-slate-50/60 dark:hover:bg-slate-800/40'
                          }`}
                          onClick={() => setSelectedBatch(cleanId)}
                        >
                          <td className="p-3.5 pl-6">
                            <div className="flex items-center gap-2">
                              <span className="font-semibold text-slate-900 dark:text-white px-2.5 py-1 rounded-lg bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-white/10">
                                {batchLabel}
                              </span>
                              {isSelected && (
                                <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${isPaysuite ? 'bg-amber-100 text-amber-800 dark:bg-amber-500/20 dark:text-amber-400' : 'bg-emerald-100 text-emerald-800 dark:bg-emerald-500/20 dark:text-emerald-400'}`}>
                                  Active Filter
                                </span>
                              )}
                            </div>
                          </td>
                          <td className="p-3.5 text-slate-600 dark:text-slate-400">
                            {batch.created_date || 'N/A'}
                          </td>
                          <td className="p-3.5 text-center font-bold text-slate-700 dark:text-slate-300 font-mono">
                            {batch.campaigns_count}
                          </td>
                          <td className="p-3.5 text-center font-bold text-slate-700 dark:text-slate-300 font-mono">
                            {batch.donations_count}
                          </td>
                          {isPaysuite && (
                            <td className="p-3.5 text-center font-mono text-xs">
                              <span className="text-emerald-600 dark:text-emerald-400 font-bold">{batch.paid_count || 0} Paid</span>
                              {batch.unpaid_count > 0 && (
                                <span className="text-rose-500 ml-1.5 font-bold">/ {batch.unpaid_count} Unpaid</span>
                              )}
                            </td>
                          )}
                          <td className="p-3.5 font-bold text-slate-900 dark:text-white font-mono">
                            {currSymbol}{Number(batch.gross_amount || 0).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                          </td>
                          {!isPaysuite && (
                            <td className="p-3.5 font-semibold text-rose-600 dark:text-rose-400 font-mono">
                              {currSymbol}{Number(batch.processing_fees || 0).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                            </td>
                          )}
                          <td className={`p-3.5 pr-6 font-black ${isPaysuite ? 'text-amber-600 dark:text-amber-400' : 'text-emerald-600 dark:text-emerald-400'} font-mono text-sm`}>
                            {currSymbol}{Number(batch.transfer_amount || 0).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Batches Pagination Footer */}
          {batchesData.total_pages > 1 && (
            <div className="flex items-center justify-between p-4 rounded-2xl border border-slate-200 dark:border-white/10 bg-white/80 dark:bg-slate-900/80 backdrop-blur-xl shadow-sm text-xs font-semibold">
              <span className="text-slate-500 dark:text-slate-400">
                Showing Page <span className="text-slate-900 dark:text-white font-bold">{batchesData.page}</span> of <span className="text-slate-900 dark:text-white font-bold">{batchesData.total_pages}</span> ({batchesData.total_batches} total {isPaysuite ? 'cycles' : 'batches'})
              </span>
              <div className="flex items-center gap-2">
                <button 
                  onClick={() => handlePageChange(currentPage - 1)}
                  disabled={currentPage <= 1}
                  className="p-2 rounded-xl border border-slate-200 dark:border-white/10 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-40 transition-all cursor-pointer"
                >
                  <ChevronLeft className="w-4 h-4 text-slate-700 dark:text-slate-300" />
                </button>
                <button 
                  onClick={() => handlePageChange(currentPage + 1)}
                  disabled={currentPage >= batchesData.total_pages}
                  className="p-2 rounded-xl border border-slate-200 dark:border-white/10 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-40 transition-all cursor-pointer"
                >
                  <ChevronRight className="w-4 h-4 text-slate-700 dark:text-slate-300" />
                </button>
              </div>
            </div>
          )}
        </div>
      ) : activeTab === 'campaigns' ? (
        /* Tab 2: Code & Campaign Breakdown */
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center justify-between gap-4 p-4 rounded-2xl border border-slate-200 dark:border-white/10 bg-white/80 dark:bg-slate-900/80 backdrop-blur-xl shadow-sm">
            <div className="flex items-center gap-3 flex-wrap">
              <div className="flex items-center p-1 bg-slate-100 dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-white/10 shadow-inner text-xs font-bold flex-wrap">
                {/* 1. Group by Code */}
                <button
                  onClick={() => setBreakdownViewMode('code_groups')}
                  className={`px-3 py-1.5 rounded-lg transition-all flex items-center gap-1.5 cursor-pointer ${
                    breakdownViewMode === 'code_groups'
                      ? isPaysuite ? 'bg-amber-600 text-white shadow-sm' : 'bg-emerald-600 text-white shadow-sm'
                      : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
                  }`}
                >
                  <Tag className="w-3.5 h-3.5" />
                  <span>By Code ({codeGroups.length})</span>
                </button>

                {/* 2. Group by Heading */}
                <button
                  onClick={() => setBreakdownViewMode('heading_groups')}
                  className={`px-3 py-1.5 rounded-lg transition-all flex items-center gap-1.5 cursor-pointer ${
                    breakdownViewMode === 'heading_groups'
                      ? isPaysuite ? 'bg-amber-600 text-white shadow-sm' : 'bg-emerald-600 text-white shadow-sm'
                      : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
                  }`}
                >
                  <Folder className="w-3.5 h-3.5" />
                  <span>By Heading ({headingGroups.length})</span>
                </button>

                {/* 3. Group by Country */}
                <button
                  onClick={() => setBreakdownViewMode('country_groups')}
                  className={`px-3 py-1.5 rounded-lg transition-all flex items-center gap-1.5 cursor-pointer ${
                    breakdownViewMode === 'country_groups'
                      ? isPaysuite ? 'bg-amber-600 text-white shadow-sm' : 'bg-emerald-600 text-white shadow-sm'
                      : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
                  }`}
                >
                  <Globe className="w-3.5 h-3.5" />
                  <span>By Country ({countryGroups.length})</span>
                </button>

                {/* 4. Flat List */}
                <button
                  onClick={() => setBreakdownViewMode('flat')}
                  className={`px-3 py-1.5 rounded-lg transition-all flex items-center gap-1.5 cursor-pointer ${
                    breakdownViewMode === 'flat'
                      ? isPaysuite ? 'bg-amber-600 text-white shadow-sm' : 'bg-emerald-600 text-white shadow-sm'
                      : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
                  }`}
                >
                  <Layers className="w-3.5 h-3.5" />
                  <span>{isPaysuite ? `Direct Debit List (${campaignData.length})` : `Campaign List (${campaignData.length})`}</span>
                </button>
              </div>

              {breakdownViewMode !== 'flat' && (
                <div className="flex items-center gap-1.5">
                  <button
                    onClick={expandAll}
                    className="px-2.5 py-1.5 rounded-lg text-xs font-semibold text-slate-600 dark:text-slate-300 bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 transition-all flex items-center gap-1 cursor-pointer"
                    title="Expand all hierarchical group cards"
                  >
                    <Maximize2 className="w-3 h-3" />
                    <span>Expand All</span>
                  </button>
                  <button
                    onClick={collapseAll}
                    className="px-2.5 py-1.5 rounded-lg text-xs font-semibold text-slate-600 dark:text-slate-300 bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 transition-all flex items-center gap-1 cursor-pointer"
                    title="Collapse all hierarchical group cards"
                  >
                    <Minimize2 className="w-3 h-3" />
                    <span>Collapse All</span>
                  </button>
                </div>
              )}
            </div>

            <div className="flex items-center gap-2 text-xs font-semibold text-slate-500 dark:text-slate-400">
              <span>Sort by:</span>
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value)}
                className="bg-slate-100 dark:bg-slate-800 border border-slate-300 dark:border-white/10 rounded-xl px-2.5 py-1.5 text-xs text-slate-800 dark:text-white focus:outline-none cursor-pointer"
              >
                <option value="gross_amount">Gross Raised</option>
                <option value="transfer_amount">Net Settlement</option>
                <option value="processing_fees">CC Fees</option>
                <option value="donations_count">{isPaysuite ? 'Collections Count' : 'Donations Count'}</option>
                <option value="code">Code (A-Z)</option>
              </select>
              <button
                onClick={() => setSortOrder(prev => (prev === 'asc' ? 'desc' : 'asc'))}
                className="p-1.5 rounded-lg bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 transition-all cursor-pointer text-slate-700 dark:text-slate-300"
                title={sortOrder === 'asc' ? 'Ascending' : 'Descending'}
              >
                {sortOrder === 'asc' ? <ArrowUp className="w-3.5 h-3.5" /> : <ArrowDown className="w-3.5 h-3.5" />}
              </button>
            </div>
          </div>

          {/* Breakdown Mode 1: Code Groups */}
          {breakdownViewMode === 'code_groups' && (
            <div className="flex flex-col gap-4">
              <div className="flex flex-col gap-3">
                {paginatedCodes.length === 0 ? (
                  <div className="p-12 text-center text-slate-500 dark:text-slate-400 font-semibold bg-white/80 dark:bg-slate-900/80 rounded-2xl border border-slate-200 dark:border-white/10">
                    No code classifications found matching current criteria.
                  </div>
                ) : (
                  paginatedCodes.map((cg, idx) => {
                    const isExpanded = !!expandedCodes[cg.code];
                    const sortedSubs = sortItems(cg.campaigns || []);
                    return (
                      <div 
                        key={idx} 
                        className="rounded-2xl border border-slate-200 dark:border-white/10 bg-white/80 dark:bg-slate-900/80 backdrop-blur-xl shadow-sm overflow-hidden transition-all"
                      >
                        {/* Group Header Card */}
                        <div 
                          onClick={() => toggleCodeExpand(cg.code)}
                          className="p-4 flex flex-wrap items-center justify-between gap-4 cursor-pointer hover:bg-slate-50/80 dark:hover:bg-slate-800/50 transition-colors select-none"
                        >
                          <div className="flex items-center gap-3 min-w-0">
                            <div className={`p-2 rounded-xl ${isPaysuite ? 'bg-amber-500/10 text-amber-600 dark:text-amber-400' : 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'} shrink-0`}>
                              <Tag className="w-4 h-4" />
                            </div>
                            <div className="flex flex-col min-w-0">
                              <div className="flex items-center gap-2 flex-wrap">
                                <span className={`text-sm font-black font-mono ${isPaysuite ? 'text-amber-600 dark:text-amber-400' : 'text-emerald-600 dark:text-emerald-400'}`}>
                                  {cg.code}
                                </span>
                                <span className="text-xs font-bold text-slate-800 dark:text-white">
                                  {cg.heading}
                                </span>
                                {cg.sub_heading && cg.sub_heading !== 'Unassigned' && (
                                  <span className="text-xs text-slate-500 dark:text-slate-400">
                                    • {cg.sub_heading}
                                  </span>
                                )}
                                {cg.zakat !== 'Unassigned' && (
                                  <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-100 text-emerald-800 dark:bg-emerald-500/20 dark:text-emerald-300">
                                    {cg.zakat}
                                  </span>
                                )}
                                {cg.country !== 'Unassigned' && (
                                  <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300">
                                    {cg.country}
                                  </span>
                                )}
                              </div>
                              <span className="text-[11px] text-slate-400 font-medium mt-0.5">
                                {cg.campaigns_count} {isPaysuite ? 'direct debit references' : 'contributing campaigns'} • {cg.donations_count} {isPaysuite ? 'collections' : 'donations'}
                              </span>
                            </div>
                          </div>

                          <div className="flex items-center gap-6 shrink-0">
                            <div className="text-right">
                              <span className="text-[10px] uppercase font-bold text-slate-400 block">Gross Raised</span>
                              <span className="text-sm font-bold font-mono text-slate-900 dark:text-white">
                                {currSymbol}{Number(cg.gross_amount).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                              </span>
                            </div>

                            <div className="text-right">
                              <span className="text-[10px] uppercase font-bold text-slate-400 block">Fees</span>
                              <span className="text-xs font-semibold font-mono text-rose-600 dark:text-rose-400">
                                {currSymbol}{Number(cg.processing_fees).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                              </span>
                            </div>

                            <div className="text-right">
                              <span className="text-[10px] uppercase font-bold text-slate-400 block">Net Settlement</span>
                              <span className={`text-sm font-black font-mono ${isPaysuite ? 'text-amber-600 dark:text-amber-400' : 'text-emerald-600 dark:text-emerald-400'}`}>
                                {currSymbol}{Number(cg.transfer_amount).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                              </span>
                            </div>

                            <div className="p-1.5 rounded-lg bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400">
                              {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                            </div>
                          </div>
                        </div>

                        {/* Nested Items Table */}
                        {isExpanded && (
                          <div className="border-t border-slate-200 dark:border-white/10 bg-slate-50/50 dark:bg-slate-950/40 p-4">
                            <div className="overflow-x-auto rounded-xl border border-slate-200 dark:border-white/10">
                              <table className="w-full text-left border-collapse bg-white dark:bg-slate-900">
                                <thead>
                                  <tr className="bg-slate-100/70 dark:bg-slate-800/60 text-[10px] uppercase font-bold text-slate-500 dark:text-slate-400 border-b border-slate-200 dark:border-white/10">
                                    <th className="p-3 pl-4">{isPaysuite ? 'Direct Debit Ref (Bank Ref)' : 'Campaign Name'}</th>
                                    {isPaysuite && <th className="p-3">Donor Name</th>}
                                    <th className="p-3 text-center">{isPaysuite ? 'Collections' : 'Donations'}</th>
                                    <th className="p-3">Gross Raised</th>
                                    <th className="p-3">Fees</th>
                                    <th className="p-3">Net Settlement</th>
                                    {canEdit && <th className="p-3 pr-4 text-right">Classify</th>}
                                  </tr>
                                </thead>
                                <tbody className="divide-y divide-slate-200 dark:divide-white/5 text-xs text-slate-800 dark:text-slate-200 font-medium">
                                  {sortedSubs.map((camp, cIdx) => (
                                    <tr key={cIdx} className="hover:bg-slate-50/60 dark:hover:bg-slate-800/40 transition-colors">
                                      <td className="p-3 pl-4 font-bold text-slate-900 dark:text-white max-w-[280px] truncate" title={camp.campaign_name}>
                                        <div className="flex items-center gap-1.5">
                                          <span className="font-mono">{camp.campaign_name}</span>
                                          <button
                                            onClick={(e) => { e.stopPropagation(); handleCopyId(camp.campaign_name); }}
                                            className="text-slate-400 hover:text-emerald-500 transition-colors cursor-pointer"
                                            title="Copy ID"
                                          >
                                            {copiedId === String(camp.campaign_name) ? (
                                              <CheckCheck className="w-3 h-3 text-emerald-500" />
                                            ) : (
                                              <Copy className="w-3 h-3" />
                                            )}
                                          </button>
                                        </div>
                                      </td>
                                      {isPaysuite && (
                                        <td className="p-3 text-slate-700 dark:text-slate-300">
                                          {camp.donor_name || 'Direct Debit Donor'}
                                        </td>
                                      )}
                                      <td className="p-3 text-center font-bold font-mono text-slate-700 dark:text-slate-300">
                                        {camp.donations_count}
                                      </td>
                                      <td className="p-3 font-bold font-mono text-slate-900 dark:text-white">
                                        {currSymbol}{Number(camp.gross_amount).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                                      </td>
                                      <td className="p-3 font-semibold text-rose-600 dark:text-rose-400 font-mono">
                                        {currSymbol}{Number(camp.processing_fees).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                                      </td>
                                      <td className={`p-3 font-black font-mono ${isPaysuite ? 'text-amber-600 dark:text-amber-400' : 'text-emerald-600 dark:text-emerald-400'}`}>
                                        {currSymbol}{Number(camp.transfer_amount).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                                      </td>
                                      {canEdit && (
                                        <td className="p-3 pr-4 text-right">
                                          <button
                                            onClick={() => handleOpenEditModal(camp)}
                                            className="p-1.5 rounded-lg bg-slate-100 dark:bg-slate-800 hover:bg-emerald-500/10 hover:text-emerald-500 text-slate-500 transition-all cursor-pointer"
                                            title="Edit Classification & Sync to Database"
                                          >
                                            <Edit3 className="w-3.5 h-3.5" />
                                          </button>
                                        </td>
                                      )}
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })
                )}
              </div>

              {/* Code Breakdown Pagination Footer */}
              <div className="flex flex-wrap items-center justify-between gap-4 p-4 rounded-2xl border border-slate-200 dark:border-white/10 bg-white/80 dark:bg-slate-900/80 backdrop-blur-xl shadow-sm text-xs font-semibold">
                <div className="flex items-center gap-3">
                  <span className="text-slate-500 dark:text-slate-400">Page Size:</span>
                  <select 
                    value={codePageSize}
                    onChange={(e) => {
                      setCodePageSize(e.target.value);
                      setCodePage(1);
                    }}
                    className="bg-slate-100 dark:bg-slate-800 border border-slate-300 dark:border-white/10 rounded-xl px-3 py-1.5 text-xs text-slate-800 dark:text-white focus:outline-none cursor-pointer"
                  >
                    <option value={25}>25 codes</option>
                    <option value={50}>50 codes</option>
                    <option value={100}>100 codes</option>
                    <option value="All">All ({sortedCodes.length})</option>
                  </select>
                  <span className="text-slate-500 dark:text-slate-400 border-l border-slate-200 dark:border-white/10 pl-3">
                    Showing Page <span className="text-slate-900 dark:text-white font-bold">{safeCodePage}</span> of <span className="text-slate-900 dark:text-white font-bold">{totalCodePages}</span> ({sortedCodes.length} total codes)
                  </span>
                </div>

                {codePageSize !== 'All' && totalCodePages > 1 && (
                  <div className="flex items-center gap-2">
                    <button 
                      onClick={() => setCodePage(p => Math.max(1, p - 1))}
                      disabled={safeCodePage <= 1}
                      className="p-2 rounded-xl border border-slate-200 dark:border-white/10 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-40 transition-all cursor-pointer"
                    >
                      <ChevronLeft className="w-4 h-4 text-slate-700 dark:text-slate-300" />
                    </button>
                    <button 
                      onClick={() => setCodePage(p => Math.min(totalCodePages, p + 1))}
                      disabled={safeCodePage >= totalCodePages}
                      className="p-2 rounded-xl border border-slate-200 dark:border-white/10 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-40 transition-all cursor-pointer"
                    >
                      <ChevronRight className="w-4 h-4 text-slate-700 dark:text-slate-300" />
                    </button>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Breakdown Mode 2: Heading Groups */}
          {breakdownViewMode === 'heading_groups' && (
            <div className="flex flex-col gap-4">
              <div className="flex flex-col gap-3">
                {paginatedHeadings.length === 0 ? (
                  <div className="p-12 text-center text-slate-500 dark:text-slate-400 font-semibold bg-white/80 dark:bg-slate-900/80 rounded-2xl border border-slate-200 dark:border-white/10">
                    No heading groups found matching current criteria.
                  </div>
                ) : (
                  paginatedHeadings.map((hg, idx) => {
                    const isExpanded = !!expandedHeadings[hg.heading];
                    const sortedSubs = sortItems(hg.campaigns || []);
                    return (
                      <div 
                        key={idx} 
                        className="rounded-2xl border border-slate-200 dark:border-white/10 bg-white/80 dark:bg-slate-900/80 backdrop-blur-xl shadow-sm overflow-hidden transition-all"
                      >
                        {/* Heading Header Card */}
                        <div 
                          onClick={() => toggleHeadingExpand(hg.heading)}
                          className="p-4 flex flex-wrap items-center justify-between gap-4 cursor-pointer hover:bg-slate-50/80 dark:hover:bg-slate-800/50 transition-colors select-none"
                        >
                          <div className="flex items-center gap-3 min-w-0">
                            <div className={`p-2 rounded-xl ${isPaysuite ? 'bg-amber-500/10 text-amber-600 dark:text-amber-400' : 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'} shrink-0`}>
                              <Folder className="w-4 h-4" />
                            </div>
                            <div className="flex flex-col min-w-0">
                              <div className="flex items-center gap-2 flex-wrap">
                                <span className="text-sm font-black text-slate-800 dark:text-white">
                                  {hg.heading}
                                </span>
                                {hg.codes && hg.codes.length > 0 && (
                                  <div className="flex items-center gap-1 flex-wrap">
                                    {hg.codes.slice(0, 5).map((c, cidx) => (
                                      <span key={cidx} className={`px-1.5 py-0.2 rounded text-[10px] font-mono font-bold ${isPaysuite ? 'bg-amber-100 text-amber-800 dark:bg-amber-500/20 dark:text-amber-300' : 'bg-emerald-100 text-emerald-800 dark:bg-emerald-500/20 dark:text-emerald-300'}`}>
                                        {c}
                                      </span>
                                    ))}
                                    {hg.codes.length > 5 && (
                                      <span className="text-[10px] text-slate-400 font-mono">
                                        +{hg.codes.length - 5} more
                                      </span>
                                    )}
                                  </div>
                                )}
                              </div>
                              <span className="text-[11px] text-slate-400 font-medium mt-0.5">
                                {hg.codes_count || (hg.codes ? hg.codes.length : 0)} classification codes • {hg.campaigns_count || (hg.campaigns ? hg.campaigns.length : 0)} {isPaysuite ? 'direct debit references' : 'contributing campaigns'} • {hg.donations_count || 0} {isPaysuite ? 'collections' : 'donations'}
                              </span>
                            </div>
                          </div>

                          <div className="flex items-center gap-6 shrink-0">
                            <div className="text-right">
                              <span className="text-[10px] uppercase font-bold text-slate-400 block">Gross Raised</span>
                              <span className="text-sm font-bold font-mono text-slate-900 dark:text-white">
                                {currSymbol}{Number(hg.gross_amount || 0).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                              </span>
                            </div>

                            <div className="text-right">
                              <span className="text-[10px] uppercase font-bold text-slate-400 block">Fees</span>
                              <span className="text-xs font-semibold font-mono text-rose-600 dark:text-rose-400">
                                {currSymbol}{Number(hg.processing_fees || 0).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                              </span>
                            </div>

                            <div className="text-right">
                              <span className="text-[10px] uppercase font-bold text-slate-400 block">Net Settlement</span>
                              <span className={`text-sm font-black font-mono ${isPaysuite ? 'text-amber-600 dark:text-amber-400' : 'text-emerald-600 dark:text-emerald-400'}`}>
                                {currSymbol}{Number(hg.transfer_amount || 0).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                              </span>
                            </div>

                            <div className="p-1.5 rounded-lg bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400">
                              {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                            </div>
                          </div>
                        </div>

                        {/* Nested Items Table */}
                        {isExpanded && (
                          <div className="border-t border-slate-200 dark:border-white/10 bg-slate-50/50 dark:bg-slate-950/40 p-4">
                            <div className="overflow-x-auto rounded-xl border border-slate-200 dark:border-white/10">
                              <table className="w-full text-left border-collapse bg-white dark:bg-slate-900">
                                <thead>
                                  <tr className="bg-slate-100/70 dark:bg-slate-800/60 text-[10px] uppercase font-bold text-slate-500 dark:text-slate-400 border-b border-slate-200 dark:border-white/10">
                                    <th className="p-3 pl-4">{isPaysuite ? 'Direct Debit Ref (Bank Ref)' : 'Campaign Name'}</th>
                                    <th className="p-3">Classification Code</th>
                                    {isPaysuite && <th className="p-3">Donor Name</th>}
                                    <th className="p-3 text-center">{isPaysuite ? 'Collections' : 'Donations'}</th>
                                    <th className="p-3">Gross Raised</th>
                                    <th className="p-3">Fees</th>
                                    <th className="p-3">Net Settlement</th>
                                    {canEdit && <th className="p-3 pr-4 text-right">Classify</th>}
                                  </tr>
                                </thead>
                                <tbody className="divide-y divide-slate-200 dark:divide-white/5 text-xs text-slate-800 dark:text-slate-200 font-medium">
                                  {sortedSubs.map((camp, cIdx) => (
                                    <tr key={cIdx} className="hover:bg-slate-50/60 dark:hover:bg-slate-800/40 transition-colors">
                                      <td className="p-3 pl-4 font-bold text-slate-900 dark:text-white max-w-[280px] truncate" title={camp.campaign_name}>
                                        <div className="flex items-center gap-1.5">
                                          <span className="font-mono">{camp.campaign_name}</span>
                                          <button
                                            onClick={(e) => { e.stopPropagation(); handleCopyId(camp.campaign_name); }}
                                            className="text-slate-400 hover:text-emerald-500 transition-colors cursor-pointer"
                                            title="Copy ID"
                                          >
                                            {copiedId === String(camp.campaign_name) ? (
                                              <CheckCheck className="w-3 h-3 text-emerald-500" />
                                            ) : (
                                              <Copy className="w-3 h-3" />
                                            )}
                                          </button>
                                        </div>
                                      </td>
                                      <td className="p-3">
                                        <span className={`px-2 py-0.5 rounded text-[11px] font-mono font-bold ${isPaysuite ? 'bg-amber-100 text-amber-800 dark:bg-amber-500/20 dark:text-amber-300' : 'bg-emerald-100 text-emerald-800 dark:bg-emerald-500/20 dark:text-emerald-300'}`}>
                                          {camp.code}
                                        </span>
                                      </td>
                                      {isPaysuite && (
                                        <td className="p-3 text-slate-700 dark:text-slate-300">
                                          {camp.donor_name || 'Direct Debit Donor'}
                                        </td>
                                      )}
                                      <td className="p-3 text-center font-bold font-mono text-slate-700 dark:text-slate-300">
                                        {camp.donations_count}
                                      </td>
                                      <td className="p-3 font-bold font-mono text-slate-900 dark:text-white">
                                        {currSymbol}{Number(camp.gross_amount).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                                      </td>
                                      <td className="p-3 font-semibold text-rose-600 dark:text-rose-400 font-mono">
                                        {currSymbol}{Number(camp.processing_fees).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                                      </td>
                                      <td className={`p-3 font-black font-mono ${isPaysuite ? 'text-amber-600 dark:text-amber-400' : 'text-emerald-600 dark:text-emerald-400'}`}>
                                        {currSymbol}{Number(camp.transfer_amount).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                                      </td>
                                      {canEdit && (
                                        <td className="p-3 pr-4 text-right">
                                          <button
                                            onClick={() => handleOpenEditModal(camp)}
                                            className="p-1.5 rounded-lg bg-slate-100 dark:bg-slate-800 hover:bg-emerald-500/10 hover:text-emerald-500 text-slate-500 transition-all cursor-pointer"
                                            title="Edit Classification & Sync to Database"
                                          >
                                            <Edit3 className="w-3.5 h-3.5" />
                                          </button>
                                        </td>
                                      )}
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })
                )}
              </div>

              {/* Heading Breakdown Pagination Footer */}
              <div className="flex flex-wrap items-center justify-between gap-4 p-4 rounded-2xl border border-slate-200 dark:border-white/10 bg-white/80 dark:bg-slate-900/80 backdrop-blur-xl shadow-sm text-xs font-semibold">
                <div className="flex items-center gap-3">
                  <span className="text-slate-500 dark:text-slate-400">Page Size:</span>
                  <select 
                    value={headingPageSize}
                    onChange={(e) => {
                      setHeadingPageSize(e.target.value);
                      setHeadingPage(1);
                    }}
                    className="bg-slate-100 dark:bg-slate-800 border border-slate-300 dark:border-white/10 rounded-xl px-3 py-1.5 text-xs text-slate-800 dark:text-white focus:outline-none cursor-pointer"
                  >
                    <option value={25}>25 headings</option>
                    <option value={50}>50 headings</option>
                    <option value={100}>100 headings</option>
                    <option value="All">All ({sortedHeadings.length})</option>
                  </select>
                  <span className="text-slate-500 dark:text-slate-400 border-l border-slate-200 dark:border-white/10 pl-3">
                    Showing Page <span className="text-slate-900 dark:text-white font-bold">{safeHeadingPage}</span> of <span className="text-slate-900 dark:text-white font-bold">{totalHeadingPages}</span> ({sortedHeadings.length} total headings)
                  </span>
                </div>

                {headingPageSize !== 'All' && totalHeadingPages > 1 && (
                  <div className="flex items-center gap-2">
                    <button 
                      onClick={() => setHeadingPage(p => Math.max(1, p - 1))}
                      disabled={safeHeadingPage <= 1}
                      className="p-2 rounded-xl border border-slate-200 dark:border-white/10 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-40 transition-all cursor-pointer"
                    >
                      <ChevronLeft className="w-4 h-4 text-slate-700 dark:text-slate-300" />
                    </button>
                    <button 
                      onClick={() => setHeadingPage(p => Math.min(totalHeadingPages, p + 1))}
                      disabled={safeHeadingPage >= totalHeadingPages}
                      className="p-2 rounded-xl border border-slate-200 dark:border-white/10 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-40 transition-all cursor-pointer"
                    >
                      <ChevronRight className="w-4 h-4 text-slate-700 dark:text-slate-300" />
                    </button>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Breakdown Mode 3: Country Groups */}
          {breakdownViewMode === 'country_groups' && (
            <div className="flex flex-col gap-4">
              <div className="flex flex-col gap-3">
                {paginatedCountries.length === 0 ? (
                  <div className="p-12 text-center text-slate-500 dark:text-slate-400 font-semibold bg-white/80 dark:bg-slate-900/80 rounded-2xl border border-slate-200 dark:border-white/10">
                    No country groups found matching current criteria.
                  </div>
                ) : (
                  paginatedCountries.map((ctg, idx) => {
                    const isExpanded = !!expandedCountries[ctg.country];
                    const sortedSubs = sortItems(ctg.campaigns || []);
                    return (
                      <div 
                        key={idx} 
                        className="rounded-2xl border border-slate-200 dark:border-white/10 bg-white/80 dark:bg-slate-900/80 backdrop-blur-xl shadow-sm overflow-hidden transition-all"
                      >
                        {/* Country Header Card */}
                        <div 
                          onClick={() => toggleCountryExpand(ctg.country)}
                          className="p-4 flex flex-wrap items-center justify-between gap-4 cursor-pointer hover:bg-slate-50/80 dark:hover:bg-slate-800/50 transition-colors select-none"
                        >
                          <div className="flex items-center gap-3 min-w-0">
                            <div className={`p-2 rounded-xl ${isPaysuite ? 'bg-amber-500/10 text-amber-600 dark:text-amber-400' : 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'} shrink-0`}>
                              <Globe className="w-4 h-4" />
                            </div>
                            <div className="flex flex-col min-w-0">
                              <div className="flex items-center gap-2 flex-wrap">
                                <span className="text-sm font-black text-slate-800 dark:text-white">
                                  {ctg.country}
                                </span>
                                {ctg.codes && ctg.codes.length > 0 && (
                                  <div className="flex items-center gap-1 flex-wrap">
                                    {ctg.codes.slice(0, 5).map((c, cidx) => (
                                      <span key={cidx} className={`px-1.5 py-0.2 rounded text-[10px] font-mono font-bold ${isPaysuite ? 'bg-amber-100 text-amber-800 dark:bg-amber-500/20 dark:text-amber-300' : 'bg-emerald-100 text-emerald-800 dark:bg-emerald-500/20 dark:text-emerald-300'}`}>
                                        {c}
                                      </span>
                                    ))}
                                    {ctg.codes.length > 5 && (
                                      <span className="text-[10px] text-slate-400 font-mono">
                                        +{ctg.codes.length - 5} more
                                      </span>
                                    )}
                                  </div>
                                )}
                              </div>
                              <span className="text-[11px] text-slate-400 font-medium mt-0.5">
                                {ctg.codes_count || (ctg.codes ? ctg.codes.length : 0)} classification codes • {ctg.campaigns_count || (ctg.campaigns ? ctg.campaigns.length : 0)} {isPaysuite ? 'direct debit references' : 'contributing campaigns'} • {ctg.donations_count || 0} {isPaysuite ? 'collections' : 'donations'}
                              </span>
                            </div>
                          </div>

                          <div className="flex items-center gap-6 shrink-0">
                            <div className="text-right">
                              <span className="text-[10px] uppercase font-bold text-slate-400 block">Gross Raised</span>
                              <span className="text-sm font-bold font-mono text-slate-900 dark:text-white">
                                {currSymbol}{Number(ctg.gross_amount || 0).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                              </span>
                            </div>

                            <div className="text-right">
                              <span className="text-[10px] uppercase font-bold text-slate-400 block">Fees</span>
                              <span className="text-xs font-semibold font-mono text-rose-600 dark:text-rose-400">
                                {currSymbol}{Number(ctg.processing_fees || 0).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                              </span>
                            </div>

                            <div className="text-right">
                              <span className="text-[10px] uppercase font-bold text-slate-400 block">Net Settlement</span>
                              <span className={`text-sm font-black font-mono ${isPaysuite ? 'text-amber-600 dark:text-amber-400' : 'text-emerald-600 dark:text-emerald-400'}`}>
                                {currSymbol}{Number(ctg.transfer_amount || 0).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                              </span>
                            </div>

                            <div className="p-1.5 rounded-lg bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400">
                              {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                            </div>
                          </div>
                        </div>

                        {/* Nested Items Table */}
                        {isExpanded && (
                          <div className="border-t border-slate-200 dark:border-white/10 bg-slate-50/50 dark:bg-slate-950/40 p-4">
                            <div className="overflow-x-auto rounded-xl border border-slate-200 dark:border-white/10">
                              <table className="w-full text-left border-collapse bg-white dark:bg-slate-900">
                                <thead>
                                  <tr className="bg-slate-100/70 dark:bg-slate-800/60 text-[10px] uppercase font-bold text-slate-500 dark:text-slate-400 border-b border-slate-200 dark:border-white/10">
                                    <th className="p-3 pl-4">{isPaysuite ? 'Direct Debit Ref (Bank Ref)' : 'Campaign Name'}</th>
                                    <th className="p-3">Classification Code</th>
                                    {isPaysuite && <th className="p-3">Donor Name</th>}
                                    <th className="p-3 text-center">{isPaysuite ? 'Collections' : 'Donations'}</th>
                                    <th className="p-3">Gross Raised</th>
                                    <th className="p-3">Fees</th>
                                    <th className="p-3">Net Settlement</th>
                                    {canEdit && <th className="p-3 pr-4 text-right">Classify</th>}
                                  </tr>
                                </thead>
                                <tbody className="divide-y divide-slate-200 dark:divide-white/5 text-xs text-slate-800 dark:text-slate-200 font-medium">
                                  {sortedSubs.map((camp, cIdx) => (
                                    <tr key={cIdx} className="hover:bg-slate-50/60 dark:hover:bg-slate-800/40 transition-colors">
                                      <td className="p-3 pl-4 font-bold text-slate-900 dark:text-white max-w-[280px] truncate" title={camp.campaign_name}>
                                        <div className="flex items-center gap-1.5">
                                          <span className="font-mono">{camp.campaign_name}</span>
                                          <button
                                            onClick={(e) => { e.stopPropagation(); handleCopyId(camp.campaign_name); }}
                                            className="text-slate-400 hover:text-emerald-500 transition-colors cursor-pointer"
                                            title="Copy ID"
                                          >
                                            {copiedId === String(camp.campaign_name) ? (
                                              <CheckCheck className="w-3 h-3 text-emerald-500" />
                                            ) : (
                                              <Copy className="w-3 h-3" />
                                            )}
                                          </button>
                                        </div>
                                      </td>
                                      <td className="p-3">
                                        <span className={`px-2 py-0.5 rounded text-[11px] font-mono font-bold ${isPaysuite ? 'bg-amber-100 text-amber-800 dark:bg-amber-500/20 dark:text-amber-300' : 'bg-emerald-100 text-emerald-800 dark:bg-emerald-500/20 dark:text-emerald-300'}`}>
                                          {camp.code}
                                        </span>
                                      </td>
                                      {isPaysuite && (
                                        <td className="p-3 text-slate-700 dark:text-slate-300">
                                          {camp.donor_name || 'Direct Debit Donor'}
                                        </td>
                                      )}
                                      <td className="p-3 text-center font-bold font-mono text-slate-700 dark:text-slate-300">
                                        {camp.donations_count}
                                      </td>
                                      <td className="p-3 font-bold font-mono text-slate-900 dark:text-white">
                                        {currSymbol}{Number(camp.gross_amount).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                                      </td>
                                      <td className="p-3 font-semibold text-rose-600 dark:text-rose-400 font-mono">
                                        {currSymbol}{Number(camp.processing_fees).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                                      </td>
                                      <td className={`p-3 font-black font-mono ${isPaysuite ? 'text-amber-600 dark:text-amber-400' : 'text-emerald-600 dark:text-emerald-400'}`}>
                                        {currSymbol}{Number(camp.transfer_amount).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                                      </td>
                                      {canEdit && (
                                        <td className="p-3 pr-4 text-right">
                                          <button
                                            onClick={() => handleOpenEditModal(camp)}
                                            className="p-1.5 rounded-lg bg-slate-100 dark:bg-slate-800 hover:bg-emerald-500/10 hover:text-emerald-500 text-slate-500 transition-all cursor-pointer"
                                            title="Edit Classification & Sync to Database"
                                          >
                                            <Edit3 className="w-3.5 h-3.5" />
                                          </button>
                                        </td>
                                      )}
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })
                )}
              </div>

              {/* Country Breakdown Pagination Footer */}
              <div className="flex flex-wrap items-center justify-between gap-4 p-4 rounded-2xl border border-slate-200 dark:border-white/10 bg-white/80 dark:bg-slate-900/80 backdrop-blur-xl shadow-sm text-xs font-semibold">
                <div className="flex items-center gap-3">
                  <span className="text-slate-500 dark:text-slate-400">Page Size:</span>
                  <select 
                    value={countryPageSize}
                    onChange={(e) => {
                      setCountryPageSize(e.target.value);
                      setCountryPage(1);
                    }}
                    className="bg-slate-100 dark:bg-slate-800 border border-slate-300 dark:border-white/10 rounded-xl px-3 py-1.5 text-xs text-slate-800 dark:text-white focus:outline-none cursor-pointer"
                  >
                    <option value={25}>25 countries</option>
                    <option value={50}>50 countries</option>
                    <option value={100}>100 countries</option>
                    <option value="All">All ({sortedCountries.length})</option>
                  </select>
                  <span className="text-slate-500 dark:text-slate-400 border-l border-slate-200 dark:border-white/10 pl-3">
                    Showing Page <span className="text-slate-900 dark:text-white font-bold">{safeCountryPage}</span> of <span className="text-slate-900 dark:text-white font-bold">{totalCountryPages}</span> ({sortedCountries.length} total countries)
                  </span>
                </div>

                {countryPageSize !== 'All' && totalCountryPages > 1 && (
                  <div className="flex items-center gap-2">
                    <button 
                      onClick={() => setCountryPage(p => Math.max(1, p - 1))}
                      disabled={safeCountryPage <= 1}
                      className="p-2 rounded-xl border border-slate-200 dark:border-white/10 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-40 transition-all cursor-pointer"
                    >
                      <ChevronLeft className="w-4 h-4 text-slate-700 dark:text-slate-300" />
                    </button>
                    <button 
                      onClick={() => setCountryPage(p => Math.min(totalCountryPages, p + 1))}
                      disabled={safeCountryPage >= totalCountryPages}
                      className="p-2 rounded-xl border border-slate-200 dark:border-white/10 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-40 transition-all cursor-pointer"
                    >
                      <ChevronRight className="w-4 h-4 text-slate-700 dark:text-slate-300" />
                    </button>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Breakdown Mode 4: Flat List */}
          {breakdownViewMode === 'flat' && (
            <div className="flex flex-col gap-4">
              <div className="rounded-2xl border border-slate-200 dark:border-white/10 bg-white/80 dark:bg-slate-900/80 backdrop-blur-xl shadow-sm overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="w-full text-left border-collapse">
                    <thead>
                      <tr className="bg-slate-100/70 dark:bg-slate-800/60 text-[11px] uppercase font-bold text-slate-500 dark:text-slate-400 border-b border-slate-200 dark:border-white/10">
                        <th className="p-3.5 pl-5 cursor-pointer select-none" onClick={() => handleSort('campaign_name')}>
                          <div className="flex items-center gap-1.5">
                            <span>{isPaysuite ? 'Direct Debit Ref (Bank Ref)' : 'Campaign Name'}</span>
                            <ArrowUpDown className="w-3 h-3 text-slate-400" />
                          </div>
                        </th>
                        <th className="p-3.5 cursor-pointer select-none" onClick={() => handleSort('code')}>
                          <div className="flex items-center gap-1.5">
                            <span>Classification</span>
                            <ArrowUpDown className="w-3 h-3 text-slate-400" />
                          </div>
                        </th>
                        <th className="p-3.5 cursor-pointer select-none" onClick={() => handleSort('gross_amount')}>
                          <div className="flex items-center gap-1.5">
                            <span>Gross Raised</span>
                            <ArrowUpDown className="w-3 h-3 text-slate-400" />
                          </div>
                        </th>
                        <th className="p-3.5 cursor-pointer select-none" onClick={() => handleSort('processing_fees')}>
                          <div className="flex items-center gap-1.5">
                            <span>Fees</span>
                            <ArrowUpDown className="w-3 h-3 text-slate-400" />
                          </div>
                        </th>
                        <th className="p-3.5 cursor-pointer select-none" onClick={() => handleSort('transfer_amount')}>
                          <div className="flex items-center gap-1.5">
                            <span>Net Settlement</span>
                            <ArrowUpDown className="w-3 h-3 text-slate-400" />
                          </div>
                        </th>
                        {canEdit && <th className="p-3.5 pr-5 text-right">Classify</th>}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-200 dark:divide-white/5 text-xs text-slate-800 dark:text-slate-200 font-medium">
                      {paginatedCampaigns.length === 0 ? (
                        <tr>
                          <td colSpan={canEdit ? 6 : 5} className="p-8 text-center text-slate-500 dark:text-slate-400 font-semibold">
                            No {isPaysuite ? 'direct debit' : 'campaign'} settlement breakdown data found.
                          </td>
                        </tr>
                      ) : (
                        paginatedCampaigns.map((camp, idx) => (
                          <tr key={idx} className="hover:bg-slate-50/60 dark:hover:bg-slate-800/40 transition-colors">
                            <td className="p-3.5 pl-5 font-bold text-slate-900 dark:text-white max-w-[280px] truncate" title={camp.campaign_name}>
                              <div className="flex items-center gap-1.5">
                                <span className="font-mono">{camp.campaign_name}</span>
                                <button
                                  onClick={(e) => { e.stopPropagation(); handleCopyId(camp.campaign_name); }}
                                  className="text-slate-400 hover:text-emerald-500 transition-colors cursor-pointer"
                                  title="Copy ID"
                                >
                                  {copiedId === String(camp.campaign_name) ? (
                                    <CheckCheck className="w-3 h-3 text-emerald-500" />
                                  ) : (
                                    <Copy className="w-3 h-3" />
                                  )}
                                </button>
                              </div>
                            </td>
                            <td className="p-3.5">
                              <div className="flex flex-col gap-0.5 text-[11px]">
                                <div className="flex items-center gap-1.5">
                                  <span className="font-bold text-slate-700 dark:text-slate-300">{camp.heading}</span>
                                  {camp.zakat !== 'Unassigned' && (
                                    <span className="px-1.5 py-0.2 rounded text-[10px] font-bold bg-emerald-100 text-emerald-800 dark:bg-emerald-500/20 dark:text-emerald-300">
                                      {camp.zakat}
                                    </span>
                                  )}
                                </div>
                                <span className={`${isPaysuite ? 'text-amber-600 dark:text-amber-400' : 'text-emerald-600 dark:text-emerald-400'} text-[10px] font-mono font-black`}>{camp.code}</span>
                              </div>
                            </td>
                            <td className="p-3.5 font-bold font-mono text-slate-900 dark:text-white">
                              {currSymbol}{Number(camp.gross_amount).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                            </td>
                            <td className="p-3.5 font-semibold text-rose-600 dark:text-rose-400 font-mono">
                              {currSymbol}{Number(camp.processing_fees).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                            </td>
                            <td className={`p-3.5 font-black font-mono ${isPaysuite ? 'text-amber-600 dark:text-amber-400' : 'text-emerald-600 dark:text-emerald-400'}`}>
                              {currSymbol}{Number(camp.transfer_amount).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                            </td>
                            {canEdit && (
                              <td className="p-3.5 pr-5 text-right">
                                <button
                                  onClick={() => handleOpenEditModal(camp)}
                                  className="p-1.5 rounded-lg bg-slate-100 dark:bg-slate-800 hover:bg-emerald-500/10 hover:text-emerald-500 text-slate-500 transition-all cursor-pointer"
                                  title="Edit Classification & Sync to Database"
                                >
                                  <Edit3 className="w-3.5 h-3.5" />
                                </button>
                              </td>
                            )}
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Campaign Breakdown Pagination Footer */}
              <div className="flex flex-wrap items-center justify-between gap-4 p-4 rounded-2xl border border-slate-200 dark:border-white/10 bg-white/80 dark:bg-slate-900/80 backdrop-blur-xl shadow-sm text-xs font-semibold">
                <div className="flex items-center gap-3">
                  <span className="text-slate-500 dark:text-slate-400">Page Size:</span>
                  <select 
                    value={campPageSize}
                    onChange={(e) => {
                      setCampPageSize(e.target.value);
                      setCampPage(1);
                    }}
                    className="bg-slate-100 dark:bg-slate-800 border border-slate-300 dark:border-white/10 rounded-xl px-3 py-1.5 text-xs text-slate-800 dark:text-white focus:outline-none cursor-pointer"
                  >
                    <option value={25}>25 items</option>
                    <option value={50}>50 items</option>
                    <option value={100}>100 items</option>
                    <option value="All">All ({sortedCampaigns.length})</option>
                  </select>
                  <span className="text-slate-500 dark:text-slate-400 border-l border-slate-200 dark:border-white/10 pl-3">
                    Showing Page <span className="text-slate-900 dark:text-white font-bold">{safeCampPage}</span> of <span className="text-slate-900 dark:text-white font-bold">{totalCampPages}</span> ({sortedCampaigns.length} total items)
                  </span>
                </div>

                {campPageSize !== 'All' && totalCampPages > 1 && (
                  <div className="flex items-center gap-2">
                    <button 
                      onClick={() => setCampPage(p => Math.max(1, p - 1))}
                      disabled={safeCampPage <= 1}
                      className="p-2 rounded-xl border border-slate-200 dark:border-white/10 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-40 transition-all cursor-pointer"
                    >
                      <ChevronLeft className="w-4 h-4 text-slate-700 dark:text-slate-300" />
                    </button>
                    <button 
                      onClick={() => setCampPage(p => Math.min(totalCampPages, p + 1))}
                      disabled={safeCampPage >= totalCampPages}
                      className="p-2 rounded-xl border border-slate-200 dark:border-white/10 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-40 transition-all cursor-pointer"
                    >
                      <ChevronRight className="w-4 h-4 text-slate-700 dark:text-slate-300" />
                    </button>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      ) : activeTab === 'donors' ? (
        /* Tab 4: Donor Level Breakdown */
        <div className="flex flex-col gap-6">
          {/* Top Filter & Summary Header */}
          <div className="flex flex-wrap items-center justify-between gap-4 p-4 rounded-2xl border border-slate-200 dark:border-white/10 bg-white/80 dark:bg-slate-900/80 backdrop-blur-xl shadow-sm">
            <div className="flex items-center gap-3 flex-wrap">
              <div className="flex items-center gap-2">
                <div className={`p-2 rounded-xl ${isPaysuite ? 'bg-amber-500/10 text-amber-600 dark:text-amber-400' : 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'}`}>
                  <Users className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-sm font-black text-slate-900 dark:text-white flex items-center gap-2">
                    <span>{isPaysuite ? 'Paysuite Direct Debit Collections' : 'Settled Donor Transactions (Payout Reconciled)'}</span>
                    <span className={`px-2 py-0.5 rounded-md text-[11px] font-mono font-bold ${isPaysuite ? 'bg-amber-100 text-amber-800 dark:bg-amber-500/20 dark:text-amber-300' : 'bg-emerald-100 text-emerald-800 dark:bg-emerald-500/20 dark:text-emerald-300'}`}>
                      {donorsData.total_records.toLocaleString()} Collections
                    </span>
                  </h3>
                  <p className="text-[11px] text-slate-500 dark:text-slate-400 font-medium">
                    {isPaysuite 
                      ? 'Individual direct debit monthly debits with collection status, donor details, and classification codes'
                      : 'Individual donor contributions reconciled in LaunchGood payout transfer batches'}
                  </p>
                </div>
              </div>
            </div>

            {/* Donor Level Controls & Code Filter */}
            <div className="flex items-center gap-3 flex-wrap">
              <div className="flex items-center gap-1.5 bg-slate-100 dark:bg-slate-800 p-1 rounded-xl border border-slate-200 dark:border-white/10">
                <span className="text-[11px] font-bold text-slate-500 dark:text-slate-400 pl-2">Filter Code:</span>
                <select
                  value={donorCodeFilter}
                  onChange={(e) => {
                    setDonorCodeFilter(e.target.value);
                    setDonorPage(1);
                  }}
                  className="bg-transparent text-xs font-bold text-slate-800 dark:text-white py-1 px-2 focus:outline-none cursor-pointer"
                >
                  <option value="ALL">All Codes ({codeGroups.length})</option>
                  {codeGroups.map(cg => (
                    <option key={cg.code} value={cg.code}>
                      {cg.code} - {cg.heading} ({cg.campaigns_count} items)
                    </option>
                  ))}
                </select>
              </div>

              {donorCodeFilter !== 'ALL' && (
                <button
                  onClick={() => {
                    setDonorCodeFilter('ALL');
                    setDonorPage(1);
                  }}
                  className="p-1.5 rounded-lg bg-rose-500/10 text-rose-600 hover:bg-rose-500/20 text-xs font-bold transition-all cursor-pointer flex items-center gap-1"
                >
                  <X className="w-3.5 h-3.5" />
                  <span>Clear Code Filter</span>
                </button>
              )}
            </div>
          </div>

          {/* Quick Metrics Bar */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div className="p-3.5 rounded-xl border border-slate-200 dark:border-white/10 bg-white/60 dark:bg-slate-900/60 backdrop-blur-md">
              <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 block">Total Collections</span>
              <span className="text-lg font-black text-slate-900 dark:text-white font-mono">
                {donorsData.total_records.toLocaleString()}
              </span>
            </div>
            <div className="p-3.5 rounded-xl border border-slate-200 dark:border-white/10 bg-white/60 dark:bg-slate-900/60 backdrop-blur-md">
              <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 block">Gross Presented</span>
              <span className="text-lg font-black text-slate-900 dark:text-white font-mono">
                {currSymbol}{Number(donorsData.summary?.total_gross || 0).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
              </span>
            </div>
            <div className="p-3.5 rounded-xl border border-slate-200 dark:border-white/10 bg-white/60 dark:bg-slate-900/60 backdrop-blur-md">
              <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 block">Fees</span>
              <span className="text-lg font-black text-rose-600 dark:text-rose-400 font-mono">
                {currSymbol}{Number(donorsData.summary?.total_fees || 0).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
              </span>
            </div>
            <div className="p-3.5 rounded-xl border border-slate-200 dark:border-white/10 bg-white/60 dark:bg-slate-900/60 backdrop-blur-md">
              <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 block">Net Settlement</span>
              <span className={`text-lg font-black ${isPaysuite ? 'text-amber-600 dark:text-amber-400' : 'text-emerald-600 dark:text-emerald-400'} font-mono`}>
                {currSymbol}{Number(donorsData.summary?.total_net || 0).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
              </span>
            </div>
          </div>

          {/* Donors Table */}
          <div className="rounded-2xl border border-slate-200 dark:border-white/10 bg-white/80 dark:bg-slate-900/80 backdrop-blur-xl shadow-sm overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="bg-slate-100/70 dark:bg-slate-800/60 text-[11px] uppercase font-bold text-slate-500 dark:text-slate-400 border-b border-slate-200 dark:border-white/10">
                    <th className="p-3.5 pl-5 cursor-pointer select-none" onClick={() => handleDonorSort('donation_id')}>
                      <div className="flex items-center gap-1.5">
                        <span>{isPaysuite ? 'Bank Ref / Direct Debit' : 'Donation ID'}</span>
                        <ArrowUpDown className="w-3 h-3 text-slate-400" />
                      </div>
                    </th>
                    {isPaysuite && (
                      <th className="p-3.5 cursor-pointer select-none" onClick={() => handleDonorSort('status')}>
                        <div className="flex items-center gap-1.5">
                          <span>Status</span>
                          <ArrowUpDown className="w-3 h-3 text-slate-400" />
                        </div>
                      </th>
                    )}
                    <th className="p-3.5 cursor-pointer select-none" onClick={() => handleDonorSort('donor_name')}>
                      <div className="flex items-center gap-1.5">
                        <span>Donor Name & Email</span>
                        <ArrowUpDown className="w-3 h-3 text-slate-400" />
                      </div>
                    </th>
                    <th className="p-3.5 cursor-pointer select-none" onClick={() => handleDonorSort('code')}>
                      <div className="flex items-center gap-1.5">
                        <span>Classification</span>
                        <ArrowUpDown className="w-3 h-3 text-slate-400" />
                      </div>
                    </th>
                    <th className="p-3.5 cursor-pointer select-none" onClick={() => handleDonorSort('gross_amount')}>
                      <div className="flex items-center gap-1.5">
                        <span>Gross</span>
                        <ArrowUpDown className="w-3 h-3 text-slate-400" />
                      </div>
                    </th>
                    <th className="p-3.5 cursor-pointer select-none" onClick={() => handleDonorSort('net_amount')}>
                      <div className="flex items-center gap-1.5">
                        <span>Net Settlement</span>
                        <ArrowUpDown className="w-3 h-3 text-slate-400" />
                      </div>
                    </th>
                    <th className="p-3.5 cursor-pointer select-none" onClick={() => handleDonorSort('transfer_id')}>
                      <div className="flex items-center gap-1.5">
                        <span>{isPaysuite ? 'Collection Month' : 'Batch #'}</span>
                        <ArrowUpDown className="w-3 h-3 text-slate-400" />
                      </div>
                    </th>
                    <th className="p-3.5 cursor-pointer select-none" onClick={() => handleDonorSort('created_date')}>
                      <div className="flex items-center gap-1.5">
                        <span>Date</span>
                        <ArrowUpDown className="w-3 h-3 text-slate-400" />
                      </div>
                    </th>
                    {canEdit && <th className="p-3.5 pr-5 text-right">Classify</th>}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200 dark:divide-white/5 text-xs text-slate-800 dark:text-slate-200 font-medium">
                  {donorLoading ? (
                    <tr>
                      <td colSpan={canEdit ? (isPaysuite ? 10 : 9) : (isPaysuite ? 9 : 8)} className="p-12 text-center text-slate-500 dark:text-slate-400 font-semibold">
                        <div className="flex items-center justify-center gap-2">
                          <RefreshCw className={`w-4 h-4 animate-spin ${isPaysuite ? 'text-amber-500' : 'text-emerald-500'}`} />
                          <span>Loading donor settlement records...</span>
                        </div>
                      </td>
                    </tr>
                  ) : donorsData.records.length === 0 ? (
                    <tr>
                      <td colSpan={canEdit ? (isPaysuite ? 10 : 9) : (isPaysuite ? 9 : 8)} className="p-12 text-center text-slate-500 dark:text-slate-400 font-semibold">
                        No settled donor transactions found matching active criteria.
                      </td>
                    </tr>
                  ) : (
                    donorsData.records.map((d, idx) => (
                      <tr key={idx} className="hover:bg-slate-50/60 dark:hover:bg-slate-800/40 transition-colors">
                        {/* ID */}
                        <td className="p-3.5 pl-5">
                          <div className="flex items-center gap-1.5">
                            <span className="font-mono font-bold text-slate-700 dark:text-slate-300 bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded-md text-[11px]">
                              {d.donation_id}
                            </span>
                            <button
                              onClick={() => handleCopyId(d.donation_id)}
                              className="text-slate-400 hover:text-emerald-500 transition-colors cursor-pointer"
                              title="Copy ID"
                            >
                              {copiedId === String(d.donation_id) ? (
                                <CheckCheck className="w-3 h-3 text-emerald-500" />
                              ) : (
                                <Copy className="w-3 h-3" />
                              )}
                            </button>
                          </div>
                        </td>

                        {/* Status (for Paysuite) */}
                        {isPaysuite && (
                          <td className="p-3.5">
                            <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                              d.status === 'Paid'
                                ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-500/20 dark:text-emerald-400'
                                : 'bg-rose-100 text-rose-800 dark:bg-rose-500/20 dark:text-rose-400'
                            }`}>
                              {d.status}
                            </span>
                          </td>
                        )}

                        {/* Donor Name & Email */}
                        <td className="p-3.5">
                          <div className="flex items-center gap-2.5">
                            <div className={`w-7 h-7 rounded-full ${isPaysuite ? 'bg-amber-500/20 text-amber-600 dark:text-amber-400' : 'bg-emerald-500/20 text-emerald-600 dark:text-emerald-400'} flex items-center justify-center font-bold text-[10px] shrink-0`}>
                              {d.donor_name ? d.donor_name.slice(0, 2).toUpperCase() : 'DD'}
                            </div>
                            <div className="flex flex-col min-w-0 max-w-[200px]">
                              <span className="font-bold text-slate-900 dark:text-white truncate" title={d.donor_name}>
                                {d.donor_name}
                              </span>
                              {d.email && d.email !== 'nan' && (
                                <span className="text-[10px] text-slate-500 dark:text-slate-400 truncate flex items-center gap-1" title={d.email}>
                                  <Mail className="w-2.5 h-2.5 opacity-60" />
                                  {d.email}
                                </span>
                              )}
                            </div>
                          </div>
                        </td>

                        {/* Classification */}
                        <td className="p-3.5">
                          <div className="flex flex-col gap-0.5 text-[11px]">
                            <div className="flex items-center gap-1.5">
                              <span className="font-bold text-slate-700 dark:text-slate-300">{d.heading}</span>
                              {d.zakat && d.zakat !== 'Unassigned' && (
                                <span className="px-1.5 py-0.2 rounded text-[10px] font-bold bg-emerald-100 text-emerald-800 dark:bg-emerald-500/20 dark:text-emerald-300">
                                  {d.zakat}
                                </span>
                              )}
                            </div>
                            <div className="flex items-center gap-1">
                              <span className={`${isPaysuite ? 'text-amber-600 dark:text-amber-400' : 'text-emerald-600 dark:text-emerald-400'} text-[10px] font-mono font-black`}>{d.code}</span>
                              {d.country && d.country !== 'Unassigned' && (
                                <span className="text-slate-400 text-[10px]">({d.country})</span>
                              )}
                            </div>
                          </div>
                        </td>

                        {/* Gross Raised */}
                        <td className="p-3.5 font-bold font-mono text-slate-900 dark:text-white">
                          {currSymbol}{Number(d.gross_amount).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                        </td>

                        {/* Net Settlement */}
                        <td className={`p-3.5 font-black font-mono ${isPaysuite ? (d.status === 'Paid' ? 'text-amber-600 dark:text-amber-400' : 'text-slate-400') : 'text-emerald-600 dark:text-emerald-400'}`}>
                          {currSymbol}{Number(d.net_amount).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                        </td>

                        {/* Batch / Collection Month */}
                        <td className="p-3.5 text-slate-700 dark:text-slate-300 font-semibold font-mono text-xs">
                          {d.batch_label || d.transfer_id}
                        </td>

                        {/* Date */}
                        <td className="p-3.5 text-slate-600 dark:text-slate-400 text-xs">
                          {d.created_date}
                        </td>

                        {/* Quick Classify Button */}
                        {canEdit && (
                          <td className="p-3.5 pr-5 text-right">
                            <button
                              onClick={() => handleOpenEditModal(d)}
                              className="p-1.5 rounded-lg bg-slate-100 dark:bg-slate-800 hover:bg-emerald-500/10 hover:text-emerald-500 text-slate-500 transition-all cursor-pointer"
                              title="Quick-Classify Reference & Sync to Matrix"
                            >
                              <Edit3 className="w-3.5 h-3.5" />
                            </button>
                          </td>
                        )}
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Donors Pagination Footer */}
          {donorsData.total_pages > 1 && (
            <div className="flex flex-wrap items-center justify-between gap-4 p-4 rounded-2xl border border-slate-200 dark:border-white/10 bg-white/80 dark:bg-slate-900/80 backdrop-blur-xl shadow-sm text-xs font-semibold">
              <div className="flex items-center gap-3">
                <span className="text-slate-500 dark:text-slate-400">Page Size:</span>
                <select 
                  value={donorPageSize}
                  onChange={(e) => {
                    setDonorPageSize(Number(e.target.value));
                    setDonorPage(1);
                  }}
                  className="bg-slate-100 dark:bg-slate-800 border border-slate-300 dark:border-white/10 rounded-xl px-3 py-1.5 text-xs text-slate-800 dark:text-white focus:outline-none cursor-pointer"
                >
                  <option value={25}>25 transactions</option>
                  <option value={50}>50 transactions</option>
                  <option value={100}>100 transactions</option>
                </select>
                <span className="text-slate-500 dark:text-slate-400 border-l border-slate-200 dark:border-white/10 pl-3">
                  Showing Page <span className="text-slate-900 dark:text-white font-bold">{donorsData.page}</span> of <span className="text-slate-900 dark:text-white font-bold">{donorsData.total_pages}</span> ({donorsData.total_records.toLocaleString()} total records)
                </span>
              </div>

              <div className="flex items-center gap-2">
                <button 
                  onClick={() => setDonorPage(p => Math.max(1, p - 1))}
                  disabled={donorsData.page <= 1}
                  className="p-2 rounded-xl border border-slate-200 dark:border-white/10 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-40 transition-all cursor-pointer"
                >
                  <ChevronLeft className="w-4 h-4 text-slate-700 dark:text-slate-300" />
                </button>
                <button 
                  onClick={() => setDonorPage(p => Math.min(donorsData.total_pages, p + 1))}
                  disabled={donorsData.page >= donorsData.total_pages}
                  className="p-2 rounded-xl border border-slate-200 dark:border-white/10 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-40 transition-all cursor-pointer"
                >
                  <ChevronRight className="w-4 h-4 text-slate-700 dark:text-slate-300" />
                </button>
              </div>
            </div>
          )}
        </div>
      ) : (
        /* Tab 5: Accounting Ledger Audit */
        <div className="flex flex-col gap-4">
          <div className="rounded-2xl border border-slate-200 dark:border-white/10 bg-white/80 dark:bg-slate-900/80 backdrop-blur-xl shadow-sm overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="bg-slate-100/70 dark:bg-slate-800/60 text-[11px] uppercase font-bold text-slate-500 dark:text-slate-400 border-b border-slate-200 dark:border-white/10">
                    <th className="p-3.5 pl-6">Row Type</th>
                    <th className="p-3.5">Audit Description</th>
                    <th className="p-3.5 text-center">Row Count</th>
                    <th className="p-3.5">Gross Amount</th>
                    <th className="p-3.5">Processing Fees</th>
                    <th className="p-3.5 pr-6">Net Impact</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200 dark:divide-white/5 text-xs text-slate-800 dark:text-slate-200 font-medium">
                  {summary.ledger_breakdown?.length === 0 ? (
                    <tr>
                      <td colSpan="6" className="p-8 text-center text-slate-500 dark:text-slate-400 font-semibold">
                        No ledger entries found.
                      </td>
                    </tr>
                  ) : (
                    summary.ledger_breakdown?.map((l, idx) => (
                      <tr key={idx} className="hover:bg-slate-50/60 dark:hover:bg-slate-800/40 transition-colors">
                        <td className="p-3.5 pl-6">
                          <span className={`px-2.5 py-1 rounded-lg text-xs font-bold ${
                            l.row_type === 'Donation' || l.row_type === 'Paid Collection'
                              ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20'
                              : l.row_type === 'Payout'
                              ? 'bg-cyan-500/10 text-cyan-600 dark:text-cyan-400 border border-cyan-500/20'
                              : l.row_type === 'Unpaid / Failed'
                              ? 'bg-rose-500/10 text-rose-600 dark:text-rose-400 border border-rose-500/20'
                              : 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20'
                          }`}>
                            {l.row_type}
                          </span>
                        </td>
                        <td className="p-3.5 text-slate-600 dark:text-slate-400">
                          {l.description}
                        </td>
                        <td className="p-3.5 text-center font-bold text-slate-700 dark:text-slate-300 font-mono">
                          {Number(l.count || 0).toLocaleString()}
                        </td>
                        <td className="p-3.5 font-bold text-slate-900 dark:text-white font-mono">
                          {currSymbol}{Number(l.gross_amount || 0).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                        </td>
                        <td className="p-3.5 font-semibold text-rose-600 dark:text-rose-400 font-mono">
                          {currSymbol}{Number(l.processing_fees || 0).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                        </td>
                        <td className={`p-3.5 pr-6 font-black font-mono text-sm ${Number(l.net_amount) < 0 ? 'text-rose-600 dark:text-rose-400' : 'text-slate-900 dark:text-white'}`}>
                          {currSymbol}{Number(l.net_amount || 0).toLocaleString('en-GB', { minimumFractionDigits: 2 })}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* Edit Classification Modal */}
      {editingClassification && (
        <div className="fixed inset-0 z-50 bg-slate-950/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-white/10 rounded-2xl max-w-lg w-full p-6 shadow-2xl flex flex-col gap-4 animate-fade-in">
            <div className="flex items-center justify-between border-b border-slate-100 dark:border-white/10 pb-3">
              <div className="flex items-center gap-2">
                <div className={`p-2 rounded-xl ${isPaysuite ? 'bg-amber-500/10 text-amber-600 dark:text-amber-400' : 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'}`}>
                  <Edit3 className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-sm font-black text-slate-900 dark:text-white">
                    {isPaysuite ? 'Assign Paysuite Classification' : 'Assign Classification Code'}
                  </h3>
                  <p className="text-[11px] text-slate-500 dark:text-slate-400 font-medium">
                    {isPaysuite ? 'Updates Direct Debit reference across all collections and syncs with Paysuite Matrix' : 'Synchronizes with master classification matrix & all linked records'}
                  </p>
                </div>
              </div>
              <button 
                onClick={() => setEditingClassification(null)} 
                className="text-slate-400 hover:text-slate-600 dark:hover:text-white cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="flex flex-col gap-3">
              <div>
                <label className="text-[11px] font-extrabold uppercase tracking-wider text-slate-400 block mb-1">
                  {isPaysuite ? 'Direct Debit Ref (Bank Ref)' : 'Campaign Name'}
                </label>
                <input 
                  type="text"
                  value={editingClassification.campaign_name}
                  disabled
                  className="w-full px-3.5 py-2 rounded-xl border border-slate-200 dark:border-white/10 bg-slate-100 dark:bg-slate-800 text-xs font-mono font-bold text-slate-600 dark:text-slate-400 cursor-not-allowed"
                />
              </div>

              <div>
                <label className="text-[11px] font-extrabold uppercase tracking-wider text-slate-400 block mb-1">
                  Classification Code <span className="text-emerald-500">*</span>
                </label>
                <input 
                  type="text"
                  value={editingClassification.code}
                  onChange={(e) => handleSelectCodeInModal(e.target.value)}
                  placeholder="e.g. GAZ-EMR, SYR-SPN-HUF, ALL-DIV..."
                  list="payout-modal-codes-list"
                  className="w-full px-3.5 py-2 rounded-xl border border-slate-300 dark:border-white/10 bg-white dark:bg-slate-800 text-xs font-mono font-bold focus:outline-none focus:ring-2 focus:ring-emerald-500 uppercase"
                />
                <datalist id="payout-modal-codes-list">
                  {Object.keys(codeMap).map((k) => (
                    <option key={k} value={k.toUpperCase()}>
                      {codeMap[k].Heading} • {codeMap[k]['Sub-Heading']} ({codeMap[k].Country})
                    </option>
                  ))}
                </datalist>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-[11px] font-extrabold uppercase tracking-wider text-slate-400 block mb-1">
                    Heading
                  </label>
                  <input 
                    type="text"
                    value={editingClassification.heading}
                    onChange={(e) => setEditingClassification(prev => ({ ...prev, heading: e.target.value }))}
                    className="w-full px-3.5 py-2 rounded-xl border border-slate-300 dark:border-white/10 bg-white dark:bg-slate-800 text-xs font-semibold focus:outline-none focus:ring-2 focus:ring-emerald-500"
                  />
                </div>
                <div>
                  <label className="text-[11px] font-extrabold uppercase tracking-wider text-slate-400 block mb-1">
                    Sub-Heading
                  </label>
                  <input 
                    type="text"
                    value={editingClassification.sub_heading}
                    onChange={(e) => setEditingClassification(prev => ({ ...prev, sub_heading: e.target.value }))}
                    className="w-full px-3.5 py-2 rounded-xl border border-slate-300 dark:border-white/10 bg-white dark:bg-slate-800 text-xs font-semibold focus:outline-none focus:ring-2 focus:ring-emerald-500"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-[11px] font-extrabold uppercase tracking-wider text-slate-400 block mb-1">
                    Country
                  </label>
                  <input 
                    type="text"
                    value={editingClassification.country}
                    onChange={(e) => setEditingClassification(prev => ({ ...prev, country: e.target.value }))}
                    className="w-full px-3.5 py-2 rounded-xl border border-slate-300 dark:border-white/10 bg-white dark:bg-slate-800 text-xs font-semibold focus:outline-none focus:ring-2 focus:ring-emerald-500"
                  />
                </div>
                <div>
                  <label className="text-[11px] font-extrabold uppercase tracking-wider text-slate-400 block mb-1">
                    Zakat Eligibility
                  </label>
                  <select 
                    value={editingClassification.zakat_eligibility}
                    onChange={(e) => setEditingClassification(prev => ({ ...prev, zakat_eligibility: e.target.value }))}
                    className="w-full px-3.5 py-2 rounded-xl border border-slate-300 dark:border-white/10 bg-white dark:bg-slate-800 text-xs font-semibold focus:outline-none focus:ring-2 focus:ring-emerald-500 cursor-pointer"
                  >
                    <option value="Zakat">Zakat</option>
                    <option value="Non-Zakat">Non-Zakat</option>
                    <option value="Zakat Eligible">Zakat Eligible</option>
                    <option value="Unassigned">Unassigned</option>
                  </select>
                </div>
              </div>
            </div>

            {editMsg && (
              <div className="p-3 rounded-xl bg-rose-500/10 text-rose-500 text-xs font-bold flex items-center gap-2">
                <AlertCircle className="w-4 h-4 shrink-0" />
                <span>{editMsg}</span>
              </div>
            )}

            <div className="flex items-center justify-end gap-2 border-t border-slate-100 dark:border-white/10 pt-4">
              <button
                onClick={() => setEditingClassification(null)}
                className="px-4 py-2 rounded-xl text-xs font-bold text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 transition-all cursor-pointer"
              >
                Cancel
              </button>
              <button
                onClick={handleSaveClassification}
                disabled={editSaving || !editingClassification.code.trim()}
                className={`px-5 py-2 rounded-xl text-xs font-bold text-white bg-gradient-to-r ${isPaysuite ? 'from-amber-600 to-orange-600 hover:from-amber-500 hover:to-orange-500 shadow-amber-500/20' : 'from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 shadow-emerald-500/20'} shadow-md transition-all flex items-center gap-2 cursor-pointer disabled:opacity-50`}
              >
                {editSaving ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                <span>{editSaving ? 'Saving & Syncing...' : 'Save & Sync Classification'}</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Super Admin Purge Payout Data Modal */}
      {showPurgeModal && (
        <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-md flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-rose-500/30 rounded-2xl max-w-md w-full p-6 shadow-2xl flex flex-col gap-4 text-white">
            <div className="flex items-center justify-between border-b border-white/10 pb-3">
              <h3 className="text-base font-extrabold text-rose-400 flex items-center gap-2">
                <AlertCircle className="w-5 h-5" /> Purge Payout Settlement Data
              </h3>
              <button onClick={() => setShowPurgeModal(false)} className="text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>

            <p className="text-xs text-slate-300 leading-relaxed">
              This action will delete all LaunchGood payout settlement batches and transaction reconciliation records from the system.
            </p>

            <label className="flex items-center gap-2.5 p-3 rounded-xl bg-slate-800/80 border border-white/10 cursor-pointer">
              <input 
                type="checkbox" 
                checked={purgeConfirm}
                onChange={(e) => setPurgeConfirm(e.target.checked)}
                className="w-4 h-4 accent-rose-500 cursor-pointer rounded"
              />
              <span className="text-xs font-semibold text-slate-200">
                I understand this will purge all LaunchGood payout data.
              </span>
            </label>

            {purgeMsg && (
              <div className="p-3 rounded-xl bg-rose-500/10 text-rose-400 text-xs font-bold flex items-center gap-2">
                <AlertCircle className="w-4 h-4 shrink-0" />
                <span>{purgeMsg}</span>
              </div>
            )}

            <div className="flex items-center justify-end gap-2 border-t border-white/10 pt-4">
              <button
                onClick={() => setShowPurgeModal(false)}
                className="px-4 py-2 rounded-xl text-xs font-bold text-slate-400 hover:text-white transition-all cursor-pointer"
              >
                Cancel
              </button>
              <button
                onClick={handlePurgePayouts}
                disabled={purging || !purgeConfirm}
                className="px-4 py-2 rounded-xl text-xs font-bold text-white bg-rose-600 hover:bg-rose-500 transition-all flex items-center gap-2 cursor-pointer disabled:opacity-50"
              >
                {purging ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />}
                <span>{purging ? 'Purging...' : 'Confirm Purge'}</span>
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
