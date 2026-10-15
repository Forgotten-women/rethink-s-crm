import React, { useEffect, useState, useMemo, useRef } from 'react';
import { createPortal } from 'react-dom';
import { 
  HeartHandshake, PlusCircle, Search, Filter, Calendar, Target, 
  TrendingUp, Users, DollarSign, Edit3, Trash2, Eye, X, Check, 
  RefreshCw, ChevronRight, BarChart3, Clock, AlertCircle, ShieldAlert,
  Layers, CheckCircle2, Award, ArrowUpRight, LayoutGrid, List, Sparkles,
  ArrowRight, ExternalLink, Activity, ChevronLeft, ChevronsLeft,
  ChevronsRight, ArrowUpDown, ArrowDown, ArrowUp, SlidersHorizontal,
  ChevronDown, ChevronUp, Plus
} from 'lucide-react';
import { API_BASE_URL } from '../config';
import FundraiserFormModal from './FundraiserFormModal';
import AddDonationModal, { canEditRecords } from './AddDonationModal';

export default function FundraiserView({ user, accentColor = 'cyan', activeCompany = 'rethink', companies = [] }) {
  const isConsolidated = activeCompany === 'all';
  // Strictly enforce that only Super Admin accounts can manage fundraisers
  const isSuperAdmin = user?.role?.toLowerCase() === 'super_admin';
  const canEditPages = canEditRecords(user) && activeCompany !== 'all';
  const [linkFormFor, setLinkFormFor] = useState(null);
  const [linkType, setLinkType] = useState('fundraiser_url');
  const [linkValue, setLinkValue] = useState('');
  const [linkBusy, setLinkBusy] = useState(false);
  const [linkError, setLinkError] = useState('');
  const [addingDonationFor, setAddingDonationFor] = useState(null);
  const addPageLink = async (fid) => {
    setLinkBusy(true); setLinkError('');
    try {
      const res = await fetch(`${API_BASE_URL}/api/fundraisers/${encodeURIComponent(fid)}/links`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ company_id: activeCompany, match_type: linkType, value: linkValue.trim() }) });
      const d = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(d.detail || `Error ${res.status}`);
      setLinkFormFor(null); setLinkValue(''); loadFundraisers(true);
    } catch (e) { setLinkError(e.message); } finally { setLinkBusy(false); }
  };
  const removePageLink = async (fid, linkId) => {
    if (!window.confirm('Stop tracking this page for this fundraiser?')) return;
    const res = await fetch(`${API_BASE_URL}/api/fundraisers/${encodeURIComponent(fid)}/links/${encodeURIComponent(linkId)}?company_id=${encodeURIComponent(activeCompany)}`, { method: 'DELETE' });
    if (res.ok) loadFundraisers(true);
  };

  // Data State
  const [fundraisersData, setFundraisersData] = useState({ summary: {}, fundraisers: [] });
  const [availableCampaigns, setAvailableCampaigns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncToast, setSyncToast] = useState(null);

  // Sync & Discover new fundraisers from live transaction data
  const handleSyncDiscovered = () => {
    if (isConsolidated) {
      alert('Syncing fundraisers is disabled in Consolidated (All Companies) mode. Please select a specific company.');
      return;
    }
    setSyncing(true);
    fetch(`${API_BASE_URL}/api/fundraisers/sync-discovered?company_id=${encodeURIComponent(activeCompany)}`, { method: 'POST' })
      .then(r => r.json())
      .then(res => {
        setSyncing(false);
        setSyncToast(res.message || 'Fundraisers synced from data successfully.');
        loadFundraisers(true);
        loadCampaignsList();
        setTimeout(() => setSyncToast(null), 4500);
      })
      .catch(err => {
        setSyncing(false);
        setSyncToast('Sync error: ' + err.message);
        setTimeout(() => setSyncToast(null), 4500);
      });
  };

  // Filters & View State
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('ALL');
  const [statusOptions, setStatusOptions] = useState(['ACTIVE', 'PAUSED', 'COMPLETED', 'RAMADAN']);
  const [ramadanPeriods, setRamadanPeriods] = useState([]);
  const [ramadanChoice, setRamadanChoice] = useState('');
  const [txFilter, setTxFilter] = useState('');
  const [ramadanOpen, setRamadanOpen] = useState(false);
  const [ramadanYear, setRamadanYear] = useState(null);
  const ramadanRef = useRef(null);
  const ramadanPanelRef = useRef(null);
  const [ramadanPos, setRamadanPos] = useState(null);
  useEffect(() => {
    if (!ramadanOpen) return undefined;
    // The panel is rendered at the top level of the page (portal) so cards below can never cover it
    const place = () => {
      const r = ramadanRef.current?.getBoundingClientRect();
      if (r) setRamadanPos({ top: r.bottom + 6, right: Math.max(8, window.innerWidth - r.right) });
    };
    place();
    const close = (e) => {
      if (ramadanRef.current?.contains(e.target) || ramadanPanelRef.current?.contains(e.target)) return;
      setRamadanOpen(false);
    };
    const esc = (e) => { if (e.key === 'Escape') setRamadanOpen(false); };
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', esc);
    window.addEventListener('resize', place);
    window.addEventListener('scroll', place, true);
    return () => {
      document.removeEventListener('mousedown', close); document.removeEventListener('keydown', esc);
      window.removeEventListener('resize', place); window.removeEventListener('scroll', place, true);
    };
  }, [ramadanOpen]);
  // Page separator: the charity's own pages (Rethink / Iqra) vs SP pages
  const [pageGroupFilter, setPageGroupFilter] = useState('ALL');
  const mainGroupLabel = activeCompany === 'iqra' ? 'Iqra' : 'Rethink';

  // Status list (incl. RAMADAN and any custom status in use) and the Ramadan date presets
  useEffect(() => {
    fetch(`${API_BASE_URL}/api/fundraisers/statuses?company_id=${encodeURIComponent(activeCompany)}`)
      .then(r => (r.ok ? r.json() : null)).then(d => { if (d?.statuses) setStatusOptions(d.statuses); }).catch(() => {});
    fetch(`${API_BASE_URL}/api/fundraisers/ramadan-periods?company_id=${encodeURIComponent(activeCompany)}`)
      .then(r => (r.ok ? r.json() : null)).then(d => { if (d?.periods) setRamadanPeriods(d.periods); }).catch(() => {});
  }, [activeCompany]);
  const [dateFilterMode, setDateFilterMode] = useState('all'); // 'all', 'this_year', 'last_year', 'last_30', 'last_90', 'custom'
  const [customStartDate, setCustomStartDate] = useState('');
  const [customEndDate, setCustomEndDate] = useState('');
  const [appliedStartDate, setAppliedStartDate] = useState('');
  const [appliedEndDate, setAppliedEndDate] = useState('');
  const [viewMode, setViewMode] = useState('grid'); // 'grid' or 'table'

  // Pagination & Sorting State
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(() => {
    try {
      const saved = localStorage.getItem('fundraiser_page_size');
      if (saved) return saved === 'ALL' ? 'ALL' : Number(saved);
    } catch (e) {}
    return 'ALL';
  });
  const [sortBy, setSortBy] = useState('period_raised'); // 'period_raised', 'all_time_raised', 'target_goal', 'progress', 'donors', 'txns', 'date', 'name'
  const [sortOrder, setSortOrder] = useState('desc'); // 'desc' or 'asc'
  const [jumpPageInput, setJumpPageInput] = useState('');

  // Modal State (Create / Edit)
  const [showModal, setShowModal] = useState(false);
  const [editingFundraiser, setEditingFundraiser] = useState(null);

  // Delete State
  const [deleteConfirm, setDeleteConfirm] = useState(null);
  const [deleting, setDeleting] = useState(false);

  // Drilldown Drawer State
  const [selectedFundraiserId, setSelectedFundraiserId] = useState(null);
  const [drilldownData, setDrilldownData] = useState(null);
  const [loadingDrilldown, setLoadingDrilldown] = useState(false);
  const [drilldownStartDate, setDrilldownStartDate] = useState('');
  const [drilldownEndDate, setDrilldownEndDate] = useState('');
  const [showAllCampaigns, setShowAllCampaigns] = useState(false);
  const [campaignBreakdownSearch, setCampaignBreakdownSearch] = useState('');
  const drawerBodyRef = useRef(null);

  const selectedFundraiserIdRef = useRef(selectedFundraiserId);
  const drilldownStartDateRef = useRef(drilldownStartDate);
  const drilldownEndDateRef = useRef(drilldownEndDate);
  useEffect(() => {
    selectedFundraiserIdRef.current = selectedFundraiserId;
    drilldownStartDateRef.current = drilldownStartDate;
    drilldownEndDateRef.current = drilldownEndDate;
  }, [selectedFundraiserId, drilldownStartDate, drilldownEndDate]);

  // Synchronize applied date filters based on preset buttons
  const handleDatePresetChange = (mode) => {
    setDateFilterMode(mode);
    setRamadanChoice('');
    setCurrentPage(1);
    const today = new Date();
    if (mode === 'all') {
      setAppliedStartDate('');
      setAppliedEndDate('');
      setCustomStartDate('');
      setCustomEndDate('');
    } else if (mode === 'this_year') {
      const start = `${today.getFullYear()}-01-01`;
      setAppliedStartDate(start);
      setAppliedEndDate('');
      setCustomStartDate(start);
      setCustomEndDate('');
    } else if (mode === 'last_year') {
      const start = `${today.getFullYear() - 1}-01-01`;
      const end = `${today.getFullYear() - 1}-12-31`;
      setAppliedStartDate(start);
      setAppliedEndDate(end);
      setCustomStartDate(start);
      setCustomEndDate(end);
    } else if (mode === 'last_30') {
      const d = new Date();
      d.setDate(today.getDate() - 30);
      const start = d.toISOString().split('T')[0];
      setAppliedStartDate(start);
      setAppliedEndDate('');
      setCustomStartDate(start);
      setCustomEndDate('');
    } else if (mode === 'last_90') {
      const d = new Date();
      d.setDate(today.getDate() - 90);
      const start = d.toISOString().split('T')[0];
      setAppliedStartDate(start);
      setAppliedEndDate('');
      setCustomStartDate(start);
      setCustomEndDate('');
    } else if (mode === 'custom') {
      // Keep custom inputs
    }
  };

  // Ramadan presets: 'YYYY|weeks|mode' - mode 'incl' = Ramadan + N weeks after, 'after' = only the N weeks after
  const shiftDays = (iso, days) => { const d = new Date(`${iso}T00:00:00Z`); d.setUTCDate(d.getUTCDate() + days); return d.toISOString().slice(0, 10); };
  const fmtDay = (iso) => new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' });
  const ramadanRange = (year, weeks, mode) => {
    const r = ramadanPeriods.find(p => String(p.year) === String(year));
    if (!r) return null;
    const n = Number(weeks);
    return { start: mode === 'after' ? shiftDays(r.end, 1) : r.start, end: n > 0 ? shiftDays(r.end, 7 * n) : r.end };
  };
  const ramadanLabel = (choice) => {
    if (!choice) return '';
    const [year, weeks, mode] = choice.split('|');
    const rg = ramadanRange(year, weeks, mode);
    const what = mode === 'after' ? `${weeks} wks after Ramadan ${year}` : `Ramadan ${year}${Number(weeks) ? ` + ${weeks} wks` : ''}`;
    return rg ? `${what} · ${fmtDay(rg.start)} – ${fmtDay(rg.end)}` : what;
  };

  const handleRamadanPreset = (choice) => {
    setRamadanChoice(choice);
    if (!choice) return;
    const [year, weeks, mode] = choice.split('|');
    const r = ramadanPeriods.find(p => String(p.year) === year);
    if (!r) return;
    const n = Number(weeks);
    const start = mode === 'after' ? shiftDays(r.end, 1) : r.start;
    const end = n > 0 ? shiftDays(r.end, 7 * n) : r.end;
    setDateFilterMode('ramadan');
    setAppliedStartDate(start);
    setAppliedEndDate(end);
    setCustomStartDate(start);
    setCustomEndDate(end);
    setCurrentPage(1);
  };

  const handleApplyCustomDateRange = (e) => {
    if (e) e.preventDefault();
    setAppliedStartDate(customStartDate);
    setAppliedEndDate(customEndDate);
    setCurrentPage(1);
  };

  const handleClearDateFilter = () => {
    setDateFilterMode('all');
    setRamadanChoice('');
    setAppliedStartDate('');
    setAppliedEndDate('');
    setCustomStartDate('');
    setCustomEndDate('');
    setCurrentPage(1);
  };

  // Load fundraisers list
  const loadFundraisers = (silent = false) => {
    if (!silent) setLoading(true);
    setRefreshing(true);

    const params = new URLSearchParams();
    params.append('company_id', activeCompany);
    if (appliedStartDate) params.append('start_date', appliedStartDate);
    if (appliedEndDate) params.append('end_date', appliedEndDate);
    if (statusFilter !== 'ALL') params.append('status_filter', statusFilter);

    fetch(`${API_BASE_URL}/api/fundraisers?${params.toString()}`)
      .then(res => res.json())
      .then(data => {
        setFundraisersData(data);
        setLoading(false);
        setRefreshing(false);
      })
      .catch(err => {
        console.error('Error fetching fundraisers:', err);
        setLoading(false);
        setRefreshing(false);
      });
  };

  // Load available campaigns for assignment
  const loadCampaignsList = () => {
    fetch(`${API_BASE_URL}/api/fundraisers/campaigns-list?company_id=${encodeURIComponent(activeCompany)}`)
      .then(res => res.json())
      .then(data => setAvailableCampaigns(data || []))
      .catch(err => console.error('Error fetching campaigns list:', err));
  };

  // Load Drilldown for selected fundraiser
  const loadDrilldown = (fid, sDate = drilldownStartDate, eDate = drilldownEndDate) => {
    if (!fid) return;
    setLoadingDrilldown(true);
    if (sDate !== undefined) setDrilldownStartDate(sDate || '');
    if (eDate !== undefined) setDrilldownEndDate(eDate || '');
    const params = new URLSearchParams();
    params.append('company_id', activeCompany);
    if (sDate) params.append('start_date', sDate);
    if (eDate) params.append('end_date', eDate);

    fetch(`${API_BASE_URL}/api/fundraisers/${fid}?${params.toString()}`)
      .then(res => res.json())
      .then(data => {
        setDrilldownData(data);
        setShowAllCampaigns(false);
        setLoadingDrilldown(false);
        setTimeout(() => {
          if (drawerBodyRef.current) {
            drawerBodyRef.current.scrollTop = 0;
          }
        }, 0);
      })
      .catch(err => {
        console.error('Error loading drilldown:', err);
        setLoadingDrilldown(false);
      });
  };

  useEffect(() => {
    loadFundraisers();
    loadCampaignsList();

    // Build WS URL: use API_BASE_URL if set, otherwise use window.location.host
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsHost = API_BASE_URL
      ? API_BASE_URL.replace(/^https?:\/\//, '')
      : window.location.host;
    const wsUrl = `${wsProtocol}//${wsHost}/ws/events?token=${encodeURIComponent(localStorage.getItem('analytics_token') || '')}`;

    let socket = null;
    let fallbackInterval = null;

    const startPollingFallback = () => {
      if (!fallbackInterval) {
        fallbackInterval = setInterval(() => {
          loadFundraisers(true);
          if (selectedFundraiserIdRef.current) {
            loadDrilldown(selectedFundraiserIdRef.current, drilldownStartDateRef.current, drilldownEndDateRef.current);
          }
        }, 30000);
      }
    };

    try {
      socket = new WebSocket(wsUrl);
      socket.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          if (['FUNDRAISER_UPDATED', 'DONORS_UPDATED', 'MATRIX_UPDATED', 'PAYOUTS_UPDATED'].includes(payload?.event)) {
            loadFundraisers(true);
            loadCampaignsList();
            if (selectedFundraiserIdRef.current) {
              loadDrilldown(selectedFundraiserIdRef.current, drilldownStartDateRef.current, drilldownEndDateRef.current);
            }
          }
        } catch (e) {}
      };
      socket.onerror = () => {
        startPollingFallback();
      };
      socket.onclose = () => {
        startPollingFallback();
      };
    } catch (e) {
      startPollingFallback();
    }

    const handleFocus = () => {
      loadFundraisers(true);
      if (selectedFundraiserIdRef.current) {
        loadDrilldown(selectedFundraiserIdRef.current, drilldownStartDateRef.current, drilldownEndDateRef.current);
      }
    };
    window.addEventListener('focus', handleFocus);
    // New donations from ANY source (platform sync, webhooks, other users) arrive via the live stream within ~1 s
    window.addEventListener('crm:data-changed', handleFocus);

    return () => {
      if (socket) {
        socket.onclose = null;
        socket.onerror = null;
        try { socket.close(); } catch (e) {}
      }
      if (fallbackInterval) clearInterval(fallbackInterval);
      window.removeEventListener('focus', handleFocus);
      window.removeEventListener('crm:data-changed', handleFocus);
    };
  }, [appliedStartDate, appliedEndDate, statusFilter, activeCompany]);

  // Open Create Modal
  const handleOpenCreateModal = () => {
    if (!isSuperAdmin) return;
    setEditingFundraiser(null);
    setShowModal(true);
    loadCampaignsList();
  };

  // Open Edit Modal
  const handleOpenEditModal = (f) => {
    if (!isSuperAdmin) return;
    setEditingFundraiser(f);
    setShowModal(true);
    loadCampaignsList();
  };

  // Delete Fundraiser
  const handleDeleteFundraiser = (fid) => {
    if (!isSuperAdmin) return;
    setDeleting(true);

    fetch(`${API_BASE_URL}/api/fundraisers/${fid}?user_role=${user?.role}&company_id=${encodeURIComponent(activeCompany)}`, {
      method: 'DELETE'
    })
      .then(r => r.json())
      .then(res => {
        setDeleting(false);
        setDeleteConfirm(null);
        if (res.status === 'success') {
          loadFundraisers(true);
          loadCampaignsList();
          if (selectedFundraiserId === fid) {
            setSelectedFundraiserId(null);
            setDrilldownData(null);
          }
        }
      })
      .catch(err => {
        setDeleting(false);
        console.error('Error deleting fundraiser:', err);
      });
  };

  // Filter fundraisers list for display (strictly exclude stale/unassigned fundraisers with 0 campaigns)
  const filteredFundraisers = useMemo(() => {
    const list = fundraisersData.fundraisers || [];
    return list.filter(f => {
      // Make sure no stale/unassigned fundraiser without campaigns is displayed
      if (!f.assigned_campaigns || f.assigned_campaigns.length === 0) {
        return false;
      }

      const matchSearch = !searchQuery || 
        f.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (f.email && f.email.toLowerCase().includes(searchQuery.toLowerCase())) ||
        (f.assigned_campaigns || []).some(c => 
          c.campaign_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
          (c.code && c.code.toLowerCase().includes(searchQuery.toLowerCase()))
        );
      
      const matchPage = !searchQuery || (f.tracked_pages || []).some(tp => (tp.value || '').toLowerCase().includes(searchQuery.toLowerCase()));
      const matchStatus = statusFilter === 'ALL' || f.status === statusFilter;
      const matchGroup = pageGroupFilter === 'ALL' || (f.page_group || 'MAIN') === pageGroupFilter;
      return (matchSearch || matchPage) && matchStatus && matchGroup;
    });
  }, [fundraisersData.fundraisers, searchQuery, statusFilter, pageGroupFilter]);
  const pageGroupCounts = useMemo(() => {
    const list = (fundraisersData.fundraisers || []).filter(f => f.assigned_campaigns && f.assigned_campaigns.length);
    return { ALL: list.length, MAIN: list.filter(f => (f.page_group || 'MAIN') === 'MAIN').length, SP: list.filter(f => f.page_group === 'SP').length };
  }, [fundraisersData.fundraisers]);

  // Sort filtered fundraisers
  const sortedFundraisers = useMemo(() => {
    return [...filteredFundraisers].sort((a, b) => {
      let valA, valB;
      if (sortBy === 'period_raised') {
        valA = a.total_raised != null ? a.total_raised : (a.total_raised_period || 0);
        valB = b.total_raised != null ? b.total_raised : (b.total_raised_period || 0);
      } else if (sortBy === 'all_time_raised') {
        valA = a.all_time_raised != null ? a.all_time_raised : (a.total_raised_all_time || a.total_raised || 0);
        valB = b.all_time_raised != null ? b.all_time_raised : (b.total_raised_all_time || b.total_raised || 0);
      } else if (sortBy === 'target_goal') {
        valA = a.target_goal || 0;
        valB = b.target_goal || 0;
      } else if (sortBy === 'progress') {
        valA = a.progress_percentage || 0;
        valB = b.progress_percentage || 0;
      } else if (sortBy === 'donors') {
        valA = a.donor_count != null ? a.donor_count : (a.period_donors || a.total_donors || 0);
        valB = b.donor_count != null ? b.donor_count : (b.period_donors || b.total_donors || 0);
      } else if (sortBy === 'txns') {
        valA = a.donation_count != null ? a.donation_count : (a.period_transactions || a.total_transactions || 0);
        valB = b.donation_count != null ? b.donation_count : (b.period_transactions || b.total_transactions || 0);
      } else if (sortBy === 'name') {
        return sortOrder === 'asc' 
          ? a.name.localeCompare(b.name) 
          : b.name.localeCompare(a.name);
      } else if (sortBy === 'date') {
        valA = a.first_donation_date && a.first_donation_date !== 'N/A' ? a.first_donation_date : (a.start_date || '');
        valB = b.first_donation_date && b.first_donation_date !== 'N/A' ? b.first_donation_date : (b.start_date || '');
        return sortOrder === 'asc' 
          ? valA.localeCompare(valB) 
          : valB.localeCompare(valA);
      } else {
        valA = a.total_raised || 0;
        valB = b.total_raised || 0;
      }

      if (sortOrder === 'asc') {
        return valA > valB ? 1 : valA < valB ? -1 : 0;
      } else {
        return valA < valB ? 1 : valA > valB ? -1 : 0;
      }
    });
  }, [filteredFundraisers, sortBy, sortOrder]);

  // Pagination calculation
  const totalItems = sortedFundraisers.length;
  const isAllPages = pageSize === 'ALL';
  const effectivePageSize = isAllPages ? Math.max(1, totalItems) : Number(pageSize);
  const totalPages = isAllPages ? 1 : Math.max(1, Math.ceil(totalItems / effectivePageSize));

  // Auto-adjust page if current page exceeds total pages
  useEffect(() => {
    if (currentPage > totalPages && totalPages > 0) {
      setCurrentPage(totalPages);
    }
  }, [totalPages, currentPage]);

  const paginatedFundraisers = useMemo(() => {
    if (isAllPages) return sortedFundraisers;
    const startIndex = (currentPage - 1) * effectivePageSize;
    return sortedFundraisers.slice(startIndex, startIndex + effectivePageSize);
  }, [sortedFundraisers, currentPage, effectivePageSize, isAllPages]);

  const startItemIndex = totalItems === 0 ? 0 : isAllPages ? 1 : (currentPage - 1) * effectivePageSize + 1;
  const endItemIndex = isAllPages ? totalItems : Math.min(currentPage * effectivePageSize, totalItems);

  // Persist page size preference
  useEffect(() => {
    try {
      localStorage.setItem('fundraiser_page_size', String(pageSize));
    } catch (e) {}
  }, [pageSize]);

  // Dynamically compute available page sizes so sizes >= totalItems (e.g. 48 or 96 when total is 36) are never shown
  const availablePageSizes = useMemo(() => {
    const baseSizes = [12, 24, 48, 96];
    const filtered = baseSizes.filter(size => size < totalItems);
    return [...filtered, 'ALL'];
  }, [totalItems]);

  // If currently selected pageSize is numeric and >= totalItems, reset to 'ALL'
  useEffect(() => {
    if (pageSize !== 'ALL' && typeof pageSize === 'number' && totalItems > 0 && pageSize >= totalItems) {
      setPageSize('ALL');
    }
  }, [totalItems, pageSize]);

  // Smart pagination range builder (e.g. 1, 2, 3 ... 10)
  const paginationRange = useMemo(() => {
    if (totalPages <= 7) {
      return Array.from({ length: totalPages }, (_, i) => i + 1);
    }
    const delta = 1;
    const range = [];
    const rangeWithDots = [];
    let l;

    for (let i = 1; i <= totalPages; i++) {
      if (i === 1 || i === totalPages || (i >= currentPage - delta && i <= currentPage + delta)) {
        range.push(i);
      }
    }

    for (let i of range) {
      if (l) {
        if (i - l === 2) {
          rangeWithDots.push(l + 1);
        } else if (i - l !== 1) {
          rangeWithDots.push('...');
        }
      }
      rangeWithDots.push(i);
      l = i;
    }
    return rangeWithDots;
  }, [totalPages, currentPage]);

  // Drilldown campaign breakdown filtering & summary
  const filteredCampaignBreakdown = useMemo(() => {
    const list = drilldownData?.campaign_breakdown || [];
    if (!campaignBreakdownSearch.trim()) return list;
    const q = campaignBreakdownSearch.toLowerCase().trim();
    return list.filter(cb => 
      (cb.campaign_name && cb.campaign_name.toLowerCase().includes(q)) ||
      (cb.code && cb.code.toLowerCase().includes(q)) ||
      (cb.heading && cb.heading.toLowerCase().includes(q))
    );
  }, [drilldownData?.campaign_breakdown, campaignBreakdownSearch]);

  const displayedCampaigns = useMemo(() => {
    if (campaignBreakdownSearch.trim() || showAllCampaigns) {
      return filteredCampaignBreakdown;
    }
    return filteredCampaignBreakdown.slice(0, 5);
  }, [filteredCampaignBreakdown, campaignBreakdownSearch, showAllCampaigns]);

  const totalCampaignsGross = useMemo(() => {
    return (drilldownData?.campaign_breakdown || []).reduce((acc, c) => acc + (c.gross_raised || 0), 0);
  }, [drilldownData?.campaign_breakdown]);

  // Pagination Controls UI Bar
  const renderPaginationControls = (isTop = false) => {
    if (totalItems === 0) return null;

    return (
      <div 
        className={`flex flex-col sm:flex-row items-center justify-between gap-3 px-4 py-2.5 rounded-xl border ${
          isTop ? 'mb-1' : 'mt-2'
        }`}
        style={{
          backgroundColor: 'var(--bg-glass)',
          borderColor: 'var(--border-glass)',
          backdropFilter: 'blur(8px)'
        }}
      >
        {/* Left Side: Count & Page Size Selector */}
        <div className="flex items-center gap-3 flex-wrap justify-center sm:justify-start">
          <span className="text-xs font-bold" style={{ color: 'var(--text-muted)' }}>
            Showing <span className="font-extrabold text-cyan-600 dark:text-cyan-400">{startItemIndex}</span> - <span className="font-extrabold text-cyan-600 dark:text-cyan-400">{endItemIndex}</span> of <span className="font-extrabold" style={{ color: 'var(--text-main)' }}>{totalItems}</span> fundraisers
          </span>

          {availablePageSizes.length > 1 && (
            <div className="flex items-center gap-1.5 pl-3 border-l" style={{ borderColor: 'var(--border-glass)' }}>
              <span className="text-[11px] font-semibold" style={{ color: 'var(--text-sub)' }}>Show:</span>
              {availablePageSizes.map(size => {
                const isActive = pageSize === size || (size === 'ALL' && pageSize === 'ALL');
                return (
                  <button
                    key={size}
                    onClick={() => {
                      setPageSize(size);
                      setCurrentPage(1);
                    }}
                    className={`px-2 py-0.5 rounded text-[11px] font-bold transition-all ${
                      isActive
                        ? 'bg-cyan-500 text-white shadow-sm'
                        : 'hover:bg-slate-200 dark:hover:bg-slate-800'
                    }`}
                    style={{
                      color: isActive ? '#ffffff' : 'var(--text-muted)'
                    }}
                  >
                    {size === 'ALL' ? 'All' : size}
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {/* Right Side: Page Navigation Buttons & Jump */}
        {!isAllPages && totalPages > 1 && (
          <div className="flex items-center gap-1.5 flex-wrap justify-center sm:justify-end">
            {/* First Page */}
            <button
              onClick={() => setCurrentPage(1)}
              disabled={currentPage === 1}
              className="p-1.5 rounded-lg border text-xs disabled:opacity-30 disabled:cursor-not-allowed hover:border-cyan-500/50 transition-colors"
              style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', borderColor: 'var(--input-border)' }}
              title="First Page"
            >
              <ChevronsLeft className="w-3.5 h-3.5" />
            </button>

            {/* Previous Page */}
            <button
              onClick={() => setCurrentPage(prev => Math.max(prev - 1, 1))}
              disabled={currentPage === 1}
              className="p-1.5 rounded-lg border text-xs disabled:opacity-30 disabled:cursor-not-allowed hover:border-cyan-500/50 transition-colors"
              style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', borderColor: 'var(--input-border)' }}
              title="Previous Page"
            >
              <ChevronLeft className="w-3.5 h-3.5" />
            </button>

            {/* Numbered Page Buttons */}
            <div className="flex items-center gap-1">
              {paginationRange.map((page, idx) => {
                if (page === '...') {
                  return (
                    <span key={`dots-${idx}`} className="px-1.5 py-1 text-xs font-bold text-slate-400">
                      •••
                    </span>
                  );
                }
                const isActive = currentPage === page;
                return (
                  <button
                    key={page}
                    onClick={() => setCurrentPage(page)}
                    className={`min-w-[28px] h-7 px-2 rounded-lg text-xs font-extrabold transition-all ${
                      isActive
                        ? 'bg-gradient-to-r from-cyan-500 to-blue-600 text-white shadow-sm shadow-cyan-500/30'
                        : 'border hover:border-cyan-500/50'
                    }`}
                    style={{
                      backgroundColor: isActive ? undefined : 'var(--input-bg)',
                      color: isActive ? '#ffffff' : 'var(--text-main)',
                      borderColor: isActive ? 'transparent' : 'var(--input-border)'
                    }}
                  >
                    {page}
                  </button>
                );
              })}
            </div>

            {/* Next Page */}
            <button
              onClick={() => setCurrentPage(prev => Math.min(prev + 1, totalPages))}
              disabled={currentPage === totalPages}
              className="p-1.5 rounded-lg border text-xs disabled:opacity-30 disabled:cursor-not-allowed hover:border-cyan-500/50 transition-colors"
              style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', borderColor: 'var(--input-border)' }}
              title="Next Page"
            >
              <ChevronRight className="w-3.5 h-3.5" />
            </button>

            {/* Last Page */}
            <button
              onClick={() => setCurrentPage(totalPages)}
              disabled={currentPage === totalPages}
              className="p-1.5 rounded-lg border text-xs disabled:opacity-30 disabled:cursor-not-allowed hover:border-cyan-500/50 transition-colors"
              style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', borderColor: 'var(--input-border)' }}
              title="Last Page"
            >
              <ChevronsRight className="w-3.5 h-3.5" />
            </button>

            {/* Page Jump */}
            {totalPages > 3 && (
              <div className="flex items-center gap-1 pl-2 border-l" style={{ borderColor: 'var(--border-glass)' }}>
                <span className="text-[11px] font-semibold" style={{ color: 'var(--text-sub)' }}>Go to:</span>
                <input
                  type="number"
                  min="1"
                  max={totalPages}
                  placeholder={currentPage}
                  onKeyDown={e => {
                    if (e.key === 'Enter') {
                      const val = parseInt(e.target.value, 10);
                      if (!isNaN(val) && val >= 1 && val <= totalPages) {
                        setCurrentPage(val);
                        e.target.value = '';
                      }
                    }
                  }}
                  className="w-12 px-1.5 py-1 text-center text-xs rounded-lg border focus:outline-none focus:border-cyan-500"
                  style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', borderColor: 'var(--input-border)' }}
                />
              </div>
            )}
          </div>
        )}
      </div>
    );
  };

  const summary = fundraisersData.summary || {};
  const isDateFiltered = !!(appliedStartDate || appliedEndDate);

  return (
    <div className="flex flex-col gap-4">
      
      {/* ── Top Header & Actions ─────────────────────────────────── */}
      <div className="flex items-center justify-between flex-wrap gap-3 pb-1">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-cyan-500/20 to-blue-500/20 border border-cyan-500/30 flex items-center justify-center text-cyan-500 shadow-sm shrink-0">
            <HeartHandshake className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-black tracking-tight" style={{ color: 'var(--text-main)' }}>
                Fundraiser Tracking &amp; Campaign Attribution
              </h2>
              <span className="inline-flex items-center gap-1 text-[10px] font-extrabold px-2 py-0.5 rounded-full bg-cyan-500/10 text-cyan-600 dark:text-cyan-400 border border-cyan-500/20">
                <span className="w-1.5 h-1.5 rounded-full bg-cyan-500 animate-pulse" /> Live Inception
              </span>
            </div>
            <p className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>
              Real-time campaign attribution based on actual donor data timestamps with custom Date X to Date Y window filtering.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {isSuperAdmin && (
            <button
              onClick={handleSyncDiscovered}
              disabled={syncing}
              className="btn-secondary text-xs flex items-center gap-1.5 px-3 py-1.5 border-cyan-500/30 text-cyan-600 dark:text-cyan-400 hover:bg-cyan-500/10"
              title="Scan donor records to auto-discover and link new fundraisers"
            >
              <Sparkles className={`w-3.5 h-3.5 ${syncing ? 'animate-spin' : 'text-cyan-500'}`} />
              {syncing ? 'Syncing Data...' : 'Sync from Data'}
            </button>
          )}

          <button
            onClick={() => loadFundraisers(false)}
            disabled={refreshing}
            className="btn-secondary text-xs flex items-center gap-1.5 px-3 py-1.5"
            title="Refresh live metrics from database"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? 'animate-spin' : ''}`} /> Refresh Live
          </button>

          {isSuperAdmin && (
            <button
              onClick={() => {
                if (isConsolidated) {
                  alert('Adding fundraisers is disabled in Consolidated (All Companies) mode. Please select a specific company.');
                  return;
                }
                handleOpenCreateModal();
              }}
              disabled={isConsolidated}
              className={`btn-primary text-xs flex items-center gap-1.5 px-3.5 py-1.5 ${
                isConsolidated ? 'opacity-60 cursor-not-allowed bg-slate-600' : 'shadow-md shadow-cyan-500/20'
              }`}
              title={isConsolidated ? "Disabled in consolidated mode" : "Add Fundraiser"}
            >
              <PlusCircle className="w-3.5 h-3.5" /> Add Fundraiser
            </button>
          )}
        </div>
      </div>

      {/* Consolidated Mode Alert */}
      {isConsolidated && (
        <div className="flex items-center gap-3 p-3.5 rounded-2xl bg-amber-500/10 border border-amber-500/30 text-amber-900 dark:text-amber-200 animate-fadeIn">
          <AlertCircle className="w-5 h-5 text-amber-500 shrink-0" />
          <div className="text-xs">
            <span className="font-bold">Consolidated Mode (All Companies):</span> Showing aggregated fundraisers and performance metrics across all organizations. Creating, editing, syncing, and deleting fundraisers is disabled in consolidated view. Switch to a specific company to make changes.
          </div>
        </div>
      )}

      {/* ── Sync Notification Toast ───────────────────────────────── */}
      {syncToast && (
        <div className="glass-panel p-2.5 px-3.5 bg-gradient-to-r from-cyan-500/10 via-blue-500/10 to-transparent border border-cyan-500/30 flex items-center justify-between text-xs font-semibold text-cyan-700 dark:text-cyan-300">
          <div className="flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-cyan-500 shrink-0" />
            <span>{syncToast}</span>
          </div>
          <button onClick={() => setSyncToast(null)} className="text-slate-400 hover:text-slate-200">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* ── KPI Summary Cards ────────────────────────────────────── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3.5">
        {/* Card 1: Total Active Fundraisers */}
        <div className="glass-panel p-3.5 flex items-center gap-3.5 relative overflow-hidden border-l-4 border-l-cyan-500">
          <div className="p-2.5 rounded-xl bg-cyan-500/10 text-cyan-500 border border-cyan-500/20 shrink-0">
            <Users className="w-4 h-4" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-[10px] font-extrabold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
              Active Fundraisers
            </div>
            <div className="text-xl font-black mt-0.5 tracking-tight" style={{ color: 'var(--text-main)' }}>
              {summary.total_fundraisers || 0}
            </div>
            <div className="text-[10px] text-cyan-600 dark:text-cyan-400 font-semibold truncate">
              {filteredFundraisers.filter(f => f.status === 'ACTIVE').length} currently active
            </div>
          </div>
        </div>

        {/* Card 2: Raised in Selected Date Window */}
        <div className="glass-panel p-3.5 flex items-center gap-3.5 relative overflow-hidden border-l-4 border-l-emerald-500">
          <div className="p-2.5 rounded-xl bg-emerald-500/10 text-emerald-500 border border-emerald-500/20 shrink-0">
            <DollarSign className="w-4 h-4" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-[10px] font-extrabold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
              {isDateFiltered ? 'Raised (Filtered Window)' : 'Raised (All-Time)'}
            </div>
            <div className="text-xl font-black text-emerald-600 dark:text-emerald-400 mt-0.5 tracking-tight">
              £{(summary.total_raised_period || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </div>
            <div className="text-[10px] font-semibold truncate" style={{ color: 'var(--text-muted)' }}>
              {isDateFiltered ? `${appliedStartDate || 'Start'} → ${appliedEndDate || 'Present'}` : 'Since first donor gift'}
            </div>
          </div>
        </div>

        {/* Card 3: Total Lifetime Raised */}
        <div className="glass-panel p-3.5 flex items-center gap-3.5 relative overflow-hidden border-l-4 border-l-purple-500">
          <div className="p-2.5 rounded-xl bg-purple-500/10 text-purple-500 border border-purple-500/20 shrink-0">
            <TrendingUp className="w-4 h-4" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-[10px] font-extrabold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
              All-Time Lifetime Raised
            </div>
            <div className="text-xl font-black text-purple-600 dark:text-purple-400 mt-0.5 tracking-tight">
              £{(summary.total_raised_all_time || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </div>
            <div className="text-[10px] font-semibold truncate" style={{ color: 'var(--text-muted)' }}>
              Across {summary.total_transactions || 0} total donations
            </div>
          </div>
        </div>

        {/* Card 4: Goal Achievement */}
        <div className="glass-panel p-3.5 flex items-center gap-3.5 relative overflow-hidden border-l-4 border-l-amber-500">
          <div className="p-2.5 rounded-xl bg-amber-500/10 text-amber-500 border border-amber-500/20 shrink-0">
            <Target className="w-4 h-4" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center justify-between">
              <div className="text-[10px] font-extrabold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
                Goal Progress
              </div>
              <span className="text-xs font-black text-amber-600 dark:text-amber-400">
                {summary.overall_progress_pct || 0}%
              </span>
            </div>
            <div className="text-lg font-black text-amber-600 dark:text-amber-400 mt-0.5">
              £{(summary.total_target_goal || 0).toLocaleString()} <span className="text-[10px] font-normal" style={{ color: 'var(--text-sub)' }}>target</span>
            </div>
            <div className="w-full rounded-full h-1.5 mt-1 overflow-hidden" style={{ backgroundColor: 'var(--bg-card-inner)' }}>
              <div 
                className="bg-gradient-to-r from-amber-500 to-emerald-500 h-full rounded-full transition-all duration-500"
                style={{ width: `${Math.min(summary.overall_progress_pct || 0, 100)}%` }}
              />
            </div>
          </div>
        </div>
      </div>

      {/* ── Interactive Date Range Filter Toolbar ───────────────── */}
      <div className="glass-panel p-3.5 flex flex-col gap-2.5">
        
        {/* Row 1: Search, Status, Presets and View Mode */}
        <div className="flex flex-col lg:flex-row items-stretch lg:items-center justify-between gap-2.5">
          <div className="flex items-center gap-2 flex-1 flex-wrap">
            {/* Search Box */}
            <div className="relative flex-1 min-w-[200px]">
              <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                placeholder="Search by fundraiser or campaign..."
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                className="w-full pl-8 pr-3 py-1.5 text-xs rounded-lg focus:outline-none"
                style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' }}
              />
            </div>

            {/* Page separator: Rethink / Iqra pages vs SP pages */}
            <div className="flex items-center gap-0.5 p-0.5 rounded-lg" role="group" aria-label="Page group" style={{ border: '1px solid var(--input-border)' }}>
              {[['ALL', 'All pages'], ['MAIN', `${mainGroupLabel} pages`], ['SP', 'SP pages']].map(([g, label]) => (
                <button key={g} type="button" onClick={() => { setPageGroupFilter(g); setCurrentPage(1); }}
                  className={`px-2 py-1 rounded-md text-[11px] font-bold transition-all ${pageGroupFilter === g
                    ? (g === 'SP' ? 'bg-pink-500/20 text-pink-600 dark:text-pink-300' : 'bg-cyan-500/20 text-cyan-600 dark:text-cyan-300')
                    : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-200'}`}>
                  {label} ({pageGroupCounts[g]})
                </button>
              ))}
            </div>

            {/* Status Filter */}
            <select
              value={statusFilter}
              onChange={e => {
                setStatusFilter(e.target.value);
                setCurrentPage(1);
              }}
              className="px-2.5 py-1.5 text-xs rounded-lg focus:outline-none"
              style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' }}
            >
              <option value="ALL">All Statuses</option>
              {statusOptions.map(st => (
                <option key={st} value={st}>{st === 'ACTIVE' ? 'Active Only' : st.charAt(0) + st.slice(1).toLowerCase()}</option>
              ))}
            </select>

            {/* Sort Filter */}
            <div className="flex items-center gap-1">
              <select
                value={sortBy}
                onChange={e => setSortBy(e.target.value)}
                className="px-2.5 py-1.5 text-xs rounded-lg focus:outline-none font-medium"
                style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' }}
              >
                <option value="period_raised">{isDateFiltered ? 'Sort: Period Raised' : 'Sort: Total Raised'}</option>
                <option value="all_time_raised">Sort: Lifetime Raised</option>
                <option value="progress">Sort: Goal Progress %</option>
                <option value="target_goal">Sort: Target Goal</option>
                <option value="donors">Sort: Donor Count</option>
                <option value="txns">Sort: Transactions</option>
                <option value="name">Sort: Name (A-Z)</option>
                <option value="date">Sort: First Gift Date</option>
              </select>

              <button
                type="button"
                onClick={() => setSortOrder(prev => prev === 'desc' ? 'asc' : 'desc')}
                className="p-1.5 rounded-lg border hover:border-cyan-500/50 transition-colors"
                style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', borderColor: 'var(--input-border)' }}
                title={sortOrder === 'desc' ? 'Sort Descending (High to Low)' : 'Sort Ascending (Low to High)'}
              >
                {sortOrder === 'desc' ? <ArrowDown className="w-3.5 h-3.5 text-cyan-500" /> : <ArrowUp className="w-3.5 h-3.5 text-cyan-500" />}
              </button>
            </div>
          </div>

          {/* Preset Buttons */}
          <div className="flex items-center gap-1 flex-wrap">
            <span className="text-[11px] font-bold flex items-center gap-1 mr-1" style={{ color: 'var(--text-muted)' }}>
              <Calendar className="w-3 h-3 text-cyan-500" /> Period:
            </span>

            {[
              { id: 'all', label: 'All-Time (First Gift)' },
              { id: 'this_year', label: 'This Year' },
              { id: 'last_year', label: 'Last Year' },
              { id: 'last_30', label: 'Last 30 Days' },
              { id: 'last_90', label: 'Last 90 Days' }
            ].map(p => (
              <button
                key={p.id}
                onClick={() => handleDatePresetChange(p.id)}
                className={`px-2 py-1 rounded-md text-[11px] font-bold transition-all ${
                  dateFilterMode === p.id 
                    ? 'bg-cyan-500/20 text-cyan-600 dark:text-cyan-300 border border-cyan-500/30' 
                    : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-200'
                }`}
              >
                {p.label}
              </button>
            ))}

            {ramadanPeriods.length > 0 && (() => {
              const years = [...ramadanPeriods].sort((a, b) => b.year - a.year);
              const todayIso = new Date().toISOString().slice(0, 10);
              const defaultYear = (years.find(p => p.start <= todayIso) || years[years.length - 1]).year;
              const year = ramadanYear ?? (ramadanChoice ? Number(ramadanChoice.split('|')[0]) : defaultYear);
              const period = years.find(p => p.year === year);
              const active = dateFilterMode === 'ramadan' && ramadanChoice;
              const option = (weeks, mode, label) => {
                const value = `${year}|${weeks}|${mode}`;
                const rg = ramadanRange(year, weeks, mode);
                const selected = ramadanChoice === value && dateFilterMode === 'ramadan';
                return (
                  <button key={value} type="button" onClick={() => { handleRamadanPreset(value); setRamadanOpen(false); }}
                    className={`flex flex-col items-start px-2 py-1.5 rounded-lg border text-left transition-all ${selected
                      ? 'border-violet-500 bg-violet-500/15 text-violet-700 dark:text-violet-200'
                      : 'border-transparent hover:border-violet-400/50 hover:bg-violet-500/5'}`}
                    style={selected ? undefined : { color: 'var(--text-main)' }}>
                    <span className="text-[11px] font-bold">{label}</span>
                    {rg && <span className="text-[10px] whitespace-nowrap" style={{ color: 'var(--text-muted)' }}>{fmtDay(rg.start)} – {fmtDay(rg.end)}</span>}
                  </button>
                );
              };
              return (
                <div className="relative" ref={ramadanRef}>
                  <button type="button" onClick={() => setRamadanOpen(o => !o)} aria-expanded={ramadanOpen} aria-haspopup="dialog"
                    className={`px-2.5 py-1 rounded-md text-[11px] font-bold flex items-center gap-1.5 border transition-all ${active
                      ? 'bg-violet-500/20 text-violet-700 dark:text-violet-200 border-violet-500/40'
                      : 'border-transparent text-slate-500 hover:text-slate-700 dark:hover:text-slate-200'}`}>
                    <span aria-hidden="true">🌙</span>
                    {active ? ramadanLabel(ramadanChoice) : 'Ramadan'}
                    <ChevronDown className={`w-3 h-3 transition-transform ${ramadanOpen ? 'rotate-180' : ''}`} />
                  </button>
                  {active && (
                    <button type="button" aria-label="Clear Ramadan filter" onClick={() => handleDatePresetChange('all')}
                      className="absolute -right-1.5 -top-1.5 w-4 h-4 rounded-full bg-violet-600 text-white flex items-center justify-center shadow">
                      <X className="w-2.5 h-2.5" />
                    </button>
                  )}
                  {ramadanOpen && ramadanPos && createPortal(
                    <div role="dialog" aria-label="Ramadan periods" ref={ramadanPanelRef}
                      className="fixed z-[90] w-[21rem] max-w-[calc(100vw-1rem)] rounded-xl border shadow-2xl p-3 flex flex-col gap-2.5"
                      style={{ top: ramadanPos.top, right: ramadanPos.right, backgroundColor: 'var(--bg-canvas)', borderColor: 'var(--border-glass)' }}>
                      <div className="flex gap-1 flex-wrap">
                        {years.map(p => (
                          <button key={p.year} type="button" onClick={() => setRamadanYear(p.year)}
                            className={`px-2.5 py-1 rounded-full text-[11px] font-bold border ${p.year === year
                              ? 'bg-violet-600 text-white border-violet-600' : 'border-slate-300/60 dark:border-slate-600'}`}
                            style={p.year === year ? undefined : { color: 'var(--text-muted)' }}>
                            {p.year}{p.estimated ? '*' : ''}
                          </button>
                        ))}
                      </div>
                      {period && (
                        <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
                          Ramadan {period.year}: <b style={{ color: 'var(--text-main)' }}>{fmtDay(period.start)} – {fmtDay(period.end)} {period.year}</b>
                          {period.estimated && <span> · estimated dates</span>}
                        </div>
                      )}
                      <div>
                        <div className="text-[10px] uppercase font-bold mb-1" style={{ color: 'var(--text-sub)' }}>Ramadan plus the weeks after</div>
                        <div className="grid grid-cols-2 gap-1">
                          {option(0, 'incl', 'Ramadan only')}
                          {option(2, 'incl', '+ 2 weeks')}
                          {option(3, 'incl', '+ 3 weeks')}
                          {option(4, 'incl', '+ 4 weeks')}
                        </div>
                      </div>
                      <div>
                        <div className="text-[10px] uppercase font-bold mb-1" style={{ color: 'var(--text-sub)' }}>Only after Ramadan</div>
                        <div className="grid grid-cols-3 gap-1">
                          {option(2, 'after', '2 weeks')}
                          {option(3, 'after', '3 weeks')}
                          {option(4, 'after', '4 weeks')}
                        </div>
                      </div>
                    </div>,
                    document.body
                  )}
                </div>
              );
            })()}

            {/* View Mode Toggle */}
            <div className="flex items-center gap-1 ml-2 pl-2 border-l" style={{ borderColor: 'var(--border-glass)' }}>
              <button
                onClick={() => setViewMode('grid')}
                className={`p-1.5 rounded-lg transition-all ${viewMode === 'grid' ? 'bg-cyan-500/20 text-cyan-500 border border-cyan-500/30' : 'text-slate-400 hover:text-slate-200'}`}
                title="Grid Cards View"
              >
                <LayoutGrid className="w-3.5 h-3.5" />
              </button>
              <button
                onClick={() => setViewMode('table')}
                className={`p-1.5 rounded-lg transition-all ${viewMode === 'table' ? 'bg-cyan-500/20 text-cyan-500 border border-cyan-500/30' : 'text-slate-400 hover:text-slate-200'}`}
                title="Leaderboard Table View"
              >
                <List className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        </div>

        {/* Row 2: Manual Date Range Inputs (From Date X to Date Y) */}
        <div className="flex items-center justify-between flex-wrap gap-2 pt-2 border-t" style={{ borderColor: 'var(--border-glass)' }}>
          <form onSubmit={handleApplyCustomDateRange} className="flex items-center gap-2 flex-wrap text-xs">
            <span className="text-[11px] font-bold" style={{ color: 'var(--text-muted)' }}>Custom Range:</span>
            
            <div className="flex items-center gap-1">
              <span className="text-[11px]" style={{ color: 'var(--text-sub)' }}>From (X):</span>
              <input
                type="date"
                value={customStartDate}
                onChange={e => {
                  setCustomStartDate(e.target.value);
                  setDateFilterMode('custom');
                }}
                className="px-2 py-1 text-xs rounded-md focus:outline-none"
                style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' }}
              />
            </div>

            <div className="flex items-center gap-1">
              <span className="text-[11px]" style={{ color: 'var(--text-sub)' }}>To (Y):</span>
              <input
                type="date"
                value={customEndDate}
                onChange={e => {
                  setCustomEndDate(e.target.value);
                  setDateFilterMode('custom');
                }}
                className="px-2 py-1 text-xs rounded-md focus:outline-none"
                style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' }}
              />
            </div>

            <button
              type="submit"
              className="btn-primary text-xs px-2.5 py-1 shadow-sm font-bold"
            >
              Apply Filter
            </button>

            {isDateFiltered && (
              <button
                type="button"
                onClick={handleClearDateFilter}
                className="px-2 py-1 rounded-md hover:bg-rose-500/10 text-rose-500 text-xs font-bold flex items-center gap-1 transition-colors"
                title="Clear date filter and view all-time"
              >
                <X className="w-3 h-3" /> Reset
              </button>
            )}
          </form>

          {/* Active Filter Indicator Badge */}
          {isDateFiltered && (
            <div className="flex items-center gap-1.5 text-[11px] font-bold px-2.5 py-1 rounded-lg bg-cyan-500/10 border border-cyan-500/20 text-cyan-700 dark:text-cyan-300">
              <Clock className="w-3 h-3" />
              <span>Window:</span>
              <span className="font-extrabold text-cyan-600 dark:text-cyan-400">
                {appliedStartDate || 'Beginning'} &rarr; {appliedEndDate || 'Latest'}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Top Pagination Controls */}
      {!loading && filteredFundraisers.length > 0 && renderPaginationControls(true)}

      {/* ── Main Content: Grid / Table Views ─────────────────────── */}
      {loading ? (
        <div className="glass-panel p-10 text-center flex flex-col items-center justify-center gap-2.5">
          <RefreshCw className="w-7 h-7 text-cyan-500 animate-spin" />
          <p className="text-xs font-semibold" style={{ color: 'var(--text-main)' }}>Loading live fundraiser analytics...</p>
        </div>
      ) : filteredFundraisers.length === 0 ? (
        <div className="glass-panel p-10 text-center flex flex-col items-center justify-center gap-3">
          <div className="p-3 rounded-2xl bg-cyan-500/10 text-cyan-500 border border-cyan-500/20">
            <HeartHandshake className="w-8 h-8" />
          </div>
          <div>
            <h3 className="text-sm font-bold" style={{ color: 'var(--text-main)' }}>No Fundraisers Found</h3>
            <p className="text-xs mt-0.5 max-w-md mx-auto" style={{ color: 'var(--text-muted)' }}>
              {searchQuery ? `No fundraisers match search "${searchQuery}".` : 'Create your first fundraiser and assign campaigns to start tracking live progress.'}
            </p>
          </div>
          {isSuperAdmin && (
            <button
              onClick={handleOpenCreateModal}
              className="btn-primary text-xs flex items-center gap-1.5 px-3.5 py-1.5"
            >
              <PlusCircle className="w-3.5 h-3.5" /> Create First Fundraiser
            </button>
          )}
        </div>
      ) : viewMode === 'grid' ? (
        /* ── Grid Cards View (Responsive 3/4 Column Layout) ───────── */
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-3 2xl:grid-cols-4 gap-4">
          {paginatedFundraisers.map(f => {
            const hasGoal = f.target_goal > 0;
            const progress = f.progress_percentage || 0;
            const isCompleted = progress >= 100;
            const firstDate = f.first_donation_date && f.first_donation_date !== 'N/A' ? f.first_donation_date : (f.start_date !== 'N/A' ? f.start_date : 'No donations yet');

            return (
              <div 
                key={f.id}
                className="glass-panel p-4 flex flex-col justify-between gap-3 transition-all duration-300 hover:border-cyan-500/30 hover:shadow-lg group relative overflow-hidden"
              >
                {/* Status Indicator Bar */}
                <div className={`absolute top-0 left-0 right-0 h-1 ${
                  f.status === 'ACTIVE' ? 'bg-cyan-500' : f.status === 'COMPLETED' ? 'bg-emerald-500' : f.status === 'RAMADAN' ? 'bg-violet-500' : 'bg-slate-500'
                }`} />

                {/* Card Top: Profile & Status */}
                <div>
                  <div className="flex items-start justify-between gap-2.5">
                    <div className="flex items-center gap-2.5 min-w-0">
                      <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-500/20 to-blue-500/20 text-cyan-500 font-black flex items-center justify-center border border-cyan-500/30 text-xs shrink-0">
                        {f.name.substring(0, 2).toUpperCase()}
                      </div>
                      <div className="min-w-0">
                        <h4 className="text-xs font-black group-hover:text-cyan-500 transition-colors truncate" style={{ color: 'var(--text-main)' }}>
                          {f.name}
                        </h4>
                        <div className="text-[10px] flex items-center gap-1.5 truncate" style={{ color: 'var(--text-muted)' }}>
                          {f.email ? <span className="truncate">{f.email}</span> : null}
                          {f.phone ? <span>• {f.phone}</span> : null}
                        </div>
                      </div>
                    </div>

                    {/* Status Badge */}
                    <span className={`px-2 py-0.5 rounded text-[9px] font-black uppercase tracking-wider shrink-0 border ${
                      f.status === 'ACTIVE' 
                        ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30' 
                        : f.status === 'COMPLETED'
                        ? 'bg-blue-500/15 text-blue-600 dark:text-blue-400 border-blue-500/30'
                        : f.status === 'RAMADAN'
                        ? 'bg-violet-500/15 text-violet-600 dark:text-violet-300 border-violet-500/30'
                        : 'bg-slate-500/15 text-slate-600 dark:text-slate-400 border-slate-500/30'
                    }`}>
                      {f.status}
                    </span>
                    <span className={`px-2 py-0.5 rounded text-[9px] font-black uppercase tracking-wider shrink-0 border ${f.page_group === 'SP'
                      ? 'bg-pink-500/15 text-pink-600 dark:text-pink-300 border-pink-500/30'
                      : 'bg-cyan-500/10 text-cyan-700 dark:text-cyan-300 border-cyan-500/20'}`}>
                      {f.page_group_label || mainGroupLabel}
                    </span>
                  </div>

                  {/* ── Date Factor Hero Box ─────────────────────────── */}
                  <div 
                    className="mt-3 p-2 rounded-lg border flex items-center justify-between text-xs"
                    style={{ backgroundColor: 'var(--bg-card-inner)', borderColor: 'var(--border-glass)' }}
                  >
                    <div className="flex items-center gap-1.5 min-w-0 text-[11px]" style={{ color: 'var(--text-muted)' }}>
                      <Clock className="w-3 h-3 text-cyan-500 shrink-0" />
                      {isDateFiltered ? (
                        <span className="truncate">Period window:</span>
                      ) : (
                        <span className="truncate">First gift date:</span>
                      )}
                    </div>
                    <span className="font-extrabold text-[11px] text-cyan-600 dark:text-cyan-400 shrink-0 ml-1">
                      {isDateFiltered ? `${appliedStartDate || 'Start'} → ${appliedEndDate || 'Now'}` : firstDate}
                    </span>
                  </div>

                  {/* ── Raised Amounts ───────────────────────────────── */}
                  <div className="mt-3 flex items-baseline justify-between">
                    <div>
                      <div className="text-[10px] uppercase font-bold" style={{ color: 'var(--text-sub)' }}>
                        {isDateFiltered ? 'Raised (In Period)' : 'Total Raised (All-Time)'}
                      </div>
                      <div className="text-xl font-black text-emerald-600 dark:text-emerald-400 tracking-tight">
                        £{f.total_raised_period.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </div>
                    </div>
                    {isDateFiltered && (
                      <div className="text-right">
                        <div className="text-[10px] uppercase font-bold" style={{ color: 'var(--text-sub)' }}>Lifetime</div>
                        <div className="text-xs font-bold" style={{ color: 'var(--text-main)' }}>
                          £{f.total_raised_all_time.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                        </div>
                      </div>
                    )}
                  </div>

                  {/* ── Target & Progress Bar ────────────────────────── */}
                  {hasGoal ? (
                    <div className="mt-2.5">
                      <div className="flex items-center justify-between text-[11px] mb-1">
                        <span className="font-semibold" style={{ color: 'var(--text-muted)' }}>
                          Goal: £{f.target_goal.toLocaleString()}
                        </span>
                        <span className="font-black text-cyan-600 dark:text-cyan-400">
                          {progress}% {isCompleted ? '🎉' : ''}
                        </span>
                      </div>
                      <div className="w-full rounded-full h-2 overflow-hidden" style={{ backgroundColor: 'var(--bg-card-inner)' }}>
                        <div 
                          className={`h-full rounded-full transition-all duration-500 ${
                            isCompleted 
                              ? 'bg-gradient-to-r from-emerald-500 to-cyan-400' 
                              : 'bg-gradient-to-r from-cyan-500 to-blue-500'
                          }`}
                          style={{ width: `${Math.min(progress, 100)}%` }}
                        />
                      </div>
                    </div>
                  ) : (
                    <div className="mt-2 text-[11px] italic" style={{ color: 'var(--text-sub)' }}>
                      No fundraising target set
                    </div>
                  )}

                  {/* ── Donors & Avg Donation Metrics ────────────────── */}
                  <div className="mt-3 grid grid-cols-2 gap-2 pt-2 border-t" style={{ borderColor: 'var(--border-glass)' }}>
                    <div className="p-1.5 rounded-md" style={{ backgroundColor: 'var(--bg-card-inner)' }}>
                      <div className="text-[10px]" style={{ color: 'var(--text-sub)' }}>Donors</div>
                      <div className="text-xs font-extrabold" style={{ color: 'var(--text-main)' }}>
                        {isDateFiltered ? `${f.period_donors} (in period)` : f.total_donors}
                      </div>
                    </div>
                    <div className="p-1.5 rounded-md" style={{ backgroundColor: 'var(--bg-card-inner)' }}>
                      <div className="text-[10px]" style={{ color: 'var(--text-sub)' }}>Avg Donation</div>
                      <div className="text-xs font-extrabold" style={{ color: 'var(--text-main)' }}>
                        £{(f.avg_donation !== undefined ? f.avg_donation : (f.average_donation || 0)).toFixed(2)}
                      </div>
                    </div>
                  </div>

                  {/* ── Assigned Campaigns Pills ─────────────────────── */}
                  <div className="mt-3">
                    <div className="text-[10px] uppercase font-bold mb-1.5 flex items-center justify-between" style={{ color: 'var(--text-sub)' }}>
                      <span>Campaigns ({f.assigned_campaigns ? f.assigned_campaigns.length : 0})</span>
                    </div>
                    <div className="flex flex-wrap gap-1 max-h-16 overflow-y-auto pr-1">
                      {(f.assigned_campaigns || []).map((c, i) => (
                        <span 
                          key={i} 
                          className="px-2 py-0.5 rounded text-[10px] font-bold bg-cyan-500/10 text-cyan-700 dark:text-cyan-300 border border-cyan-500/20 truncate max-w-full"
                          title={`${c.campaign_name} (${c.code || 'No Code'})`}
                        >
                          {c.campaign_name}
                        </span>
                      ))}
                      {(!f.assigned_campaigns || f.assigned_campaigns.length === 0) && (
                        <span className="text-[10px] italic" style={{ color: 'var(--text-sub)' }}>
                          No campaigns assigned yet
                        </span>
                      )}
                    </div>
                  </div>

                  {/* ── Tracked page links (live) ─────────────────────── */}
                  {(f.tracked_pages || []).some(tp => tp.match_type !== 'campaign_name') && (
                    <div className="mt-2">
                      <div className="text-[10px] uppercase font-bold mb-1" style={{ color: 'var(--text-sub)' }}>
                        Tracked pages ({f.tracked_pages.filter(tp => tp.match_type !== 'campaign_name').length})
                      </div>
                      <div className="flex flex-col gap-0.5 max-h-20 overflow-y-auto pr-1">
                        {f.tracked_pages.filter(tp => tp.match_type !== 'campaign_name').map(tp => (
                          <div key={tp.assignment_id} className="flex items-center justify-between gap-2 text-[10px]" title={tp.value}>
                            <span className="truncate" style={{ color: 'var(--text-main)' }}>
                              <span className="font-bold text-violet-600 dark:text-violet-300">{tp.match_label}</span> · {tp.value.replace(/^https?:\/\/(www\.)?/, '')}
                            </span>
                            <span className="shrink-0 font-bold flex items-center gap-1" style={{ color: 'var(--text-muted)' }}>
                              £{(isDateFiltered ? tp.raised_period : tp.raised_all_time).toLocaleString()} · {isDateFiltered ? tp.donations_period : tp.donations_all_time}
                              {canEditPages && tp.assignment_id && <button type="button" onClick={(e) => { e.stopPropagation(); removePageLink(f.id, tp.assignment_id); }} title="Stop tracking this page" className="text-rose-400 hover:text-rose-600"><X className="w-3 h-3" /></button>}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  {canEditPages && (
                    <div className="mt-2" onClick={e => e.stopPropagation()}>
                      {linkFormFor === f.id ? (
                        <div className="flex flex-col gap-1.5 p-2 rounded-lg border border-violet-500/30 bg-violet-500/5">
                          <div className="flex gap-1.5">
                            <select value={linkType} onChange={e => setLinkType(e.target.value)} className="px-1.5 py-1 text-[11px] rounded-md" style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' }}>
                              <option value="fundraiser_url">Fundraiser page</option><option value="campaign_url">Campaign page</option>
                              <option value="community_url">Community / team page</option><option value="campaign_name">Campaign name</option>
                            </select>
                            <input autoFocus value={linkValue} onChange={e => setLinkValue(e.target.value)} placeholder={linkType === 'campaign_name' ? 'Exact campaign name' : 'Paste the page link'}
                              className="flex-1 min-w-0 px-2 py-1 text-[11px] rounded-md" style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' }} />
                          </div>
                          <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>A new page with no donations yet is fine: its donations count for {f.name} as soon as they arrive.</div>
                          {linkError && <div className="text-[10px] text-rose-500">{linkError}</div>}
                          <div className="flex justify-end gap-2">
                            <button type="button" onClick={() => { setLinkFormFor(null); setLinkError(''); }} className="text-[11px]" style={{ color: 'var(--text-sub)' }}>Cancel</button>
                            <button type="button" disabled={linkBusy || !linkValue.trim()} onClick={() => addPageLink(f.id)} className="px-2 py-0.5 text-[11px] rounded-md bg-violet-600 text-white font-bold disabled:opacity-40">{linkBusy ? 'Adding…' : 'Track page'}</button>
                          </div>
                        </div>
                      ) : (
                        <button type="button" onClick={() => { setLinkFormFor(f.id); setLinkValue(''); setLinkError(''); }} className="text-[11px] font-semibold text-violet-600 dark:text-violet-300 flex items-center gap-1">
                          <Plus className="w-3 h-3" /> Add page link
                        </button>
                      )}
                    </div>
                  )}
                </div>

                {/* Card Bottom: Drilldown & Admin Actions */}
                <div className="pt-2 border-t flex items-center justify-between gap-2 mt-1" style={{ borderColor: 'var(--border-glass)' }}>
                  <button
                    onClick={() => {
                      setSelectedFundraiserId(f.id);
                      setShowAllCampaigns(false);
                      setCampaignBreakdownSearch('');
                      setDrilldownStartDate(appliedStartDate);
                      setDrilldownEndDate(appliedEndDate);
                      loadDrilldown(f.id, appliedStartDate, appliedEndDate);
                    }}
                    className="flex-1 py-1.5 px-2.5 rounded-lg bg-cyan-500/10 hover:bg-cyan-500/20 text-cyan-600 dark:text-cyan-400 text-xs font-bold flex items-center justify-center gap-1.5 transition-colors"
                  >
                    <Eye className="w-3.5 h-3.5" /> View Drilldown
                  </button>

                  {isSuperAdmin && (
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => handleOpenEditModal(f)}
                        className="p-1.5 rounded-lg hover:bg-slate-200 dark:hover:bg-slate-700/60 text-slate-400 hover:text-cyan-500 transition-colors"
                        title="Edit Fundraiser"
                      >
                        <Edit3 className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={() => setDeleteConfirm(f)}
                        className="p-1.5 rounded-lg bg-rose-500/10 hover:bg-rose-500/20 text-rose-500 transition-colors"
                        title="Delete Fundraiser"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        /* ── Table View ─────────────────────────────────────────── */
        <div className="glass-panel overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="border-b" style={{ borderColor: 'var(--border-glass)', backgroundColor: 'var(--table-header-bg)' }}>
                  <th 
                    onClick={() => {
                      if (sortBy === 'name') setSortOrder(prev => prev === 'asc' ? 'desc' : 'asc');
                      else { setSortBy('name'); setSortOrder('asc'); }
                    }}
                    className="py-2.5 px-3.5 font-bold uppercase tracking-wider cursor-pointer hover:text-cyan-500 select-none transition-colors" 
                    style={{ color: sortBy === 'name' ? 'var(--color-primary, #06b6d4)' : 'var(--text-muted)' }}
                  >
                    <div className="flex items-center gap-1">
                      <span>Fundraiser</span>
                      {sortBy === 'name' && (sortOrder === 'asc' ? <ArrowUp className="w-3 h-3" /> : <ArrowDown className="w-3 h-3" />)}
                    </div>
                  </th>
                  <th 
                    onClick={() => {
                      if (sortBy === 'date') setSortOrder(prev => prev === 'asc' ? 'desc' : 'asc');
                      else { setSortBy('date'); setSortOrder('desc'); }
                    }}
                    className="py-2.5 px-3.5 font-bold uppercase tracking-wider cursor-pointer hover:text-cyan-500 select-none transition-colors" 
                    style={{ color: sortBy === 'date' ? 'var(--color-primary, #06b6d4)' : 'var(--text-muted)' }}
                  >
                    <div className="flex items-center gap-1">
                      <span>First Gift Date</span>
                      {sortBy === 'date' && (sortOrder === 'asc' ? <ArrowUp className="w-3 h-3" /> : <ArrowDown className="w-3 h-3" />)}
                    </div>
                  </th>
                  <th 
                    onClick={() => {
                      if (sortBy === 'period_raised') setSortOrder(prev => prev === 'asc' ? 'desc' : 'asc');
                      else { setSortBy('period_raised'); setSortOrder('desc'); }
                    }}
                    className="py-2.5 px-3.5 font-bold uppercase tracking-wider cursor-pointer hover:text-cyan-500 select-none transition-colors" 
                    style={{ color: sortBy === 'period_raised' ? 'var(--color-primary, #06b6d4)' : 'var(--text-muted)' }}
                  >
                    <div className="flex items-center gap-1">
                      <span>{isDateFiltered ? 'Period Raised' : 'Total Raised'}</span>
                      {sortBy === 'period_raised' && (sortOrder === 'asc' ? <ArrowUp className="w-3 h-3" /> : <ArrowDown className="w-3 h-3" />)}
                    </div>
                  </th>
                  <th 
                    onClick={() => {
                      if (sortBy === 'all_time_raised') setSortOrder(prev => prev === 'asc' ? 'desc' : 'asc');
                      else { setSortBy('all_time_raised'); setSortOrder('desc'); }
                    }}
                    className="py-2.5 px-3.5 font-bold uppercase tracking-wider cursor-pointer hover:text-cyan-500 select-none transition-colors" 
                    style={{ color: sortBy === 'all_time_raised' ? 'var(--color-primary, #06b6d4)' : 'var(--text-muted)' }}
                  >
                    <div className="flex items-center gap-1">
                      <span>Lifetime Raised</span>
                      {sortBy === 'all_time_raised' && (sortOrder === 'asc' ? <ArrowUp className="w-3 h-3" /> : <ArrowDown className="w-3 h-3" />)}
                    </div>
                  </th>
                  <th 
                    onClick={() => {
                      if (sortBy === 'target_goal') setSortOrder(prev => prev === 'asc' ? 'desc' : 'asc');
                      else { setSortBy('target_goal'); setSortOrder('desc'); }
                    }}
                    className="py-2.5 px-3.5 font-bold uppercase tracking-wider cursor-pointer hover:text-cyan-500 select-none transition-colors" 
                    style={{ color: sortBy === 'target_goal' ? 'var(--color-primary, #06b6d4)' : 'var(--text-muted)' }}
                  >
                    <div className="flex items-center gap-1">
                      <span>Target Goal</span>
                      {sortBy === 'target_goal' && (sortOrder === 'asc' ? <ArrowUp className="w-3 h-3" /> : <ArrowDown className="w-3 h-3" />)}
                    </div>
                  </th>
                  <th 
                    onClick={() => {
                      if (sortBy === 'progress') setSortOrder(prev => prev === 'asc' ? 'desc' : 'asc');
                      else { setSortBy('progress'); setSortOrder('desc'); }
                    }}
                    className="py-2.5 px-3.5 font-bold uppercase tracking-wider cursor-pointer hover:text-cyan-500 select-none transition-colors" 
                    style={{ color: sortBy === 'progress' ? 'var(--color-primary, #06b6d4)' : 'var(--text-muted)' }}
                  >
                    <div className="flex items-center gap-1">
                      <span>Progress</span>
                      {sortBy === 'progress' && (sortOrder === 'asc' ? <ArrowUp className="w-3 h-3" /> : <ArrowDown className="w-3 h-3" />)}
                    </div>
                  </th>
                  <th 
                    onClick={() => {
                      if (sortBy === 'donors') setSortOrder(prev => prev === 'asc' ? 'desc' : 'asc');
                      else { setSortBy('donors'); setSortOrder('desc'); }
                    }}
                    className="py-2.5 px-3.5 font-bold uppercase tracking-wider cursor-pointer hover:text-cyan-500 select-none transition-colors" 
                    style={{ color: sortBy === 'donors' ? 'var(--color-primary, #06b6d4)' : 'var(--text-muted)' }}
                  >
                    <div className="flex items-center gap-1">
                      <span>Donors</span>
                      {sortBy === 'donors' && (sortOrder === 'asc' ? <ArrowUp className="w-3 h-3" /> : <ArrowDown className="w-3 h-3" />)}
                    </div>
                  </th>
                  <th className="py-2.5 px-3.5 font-bold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>Assigned Campaigns</th>
                  <th className="py-2.5 px-3.5 font-bold uppercase tracking-wider text-right" style={{ color: 'var(--text-muted)' }}>Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y" style={{ borderColor: 'var(--border-glass)' }}>
                {paginatedFundraisers.map(f => (
                  <tr key={f.id} className="hover:bg-slate-200/40 dark:hover:bg-slate-800/40 transition-colors">
                    <td className="py-2.5 px-3.5 font-bold" style={{ color: 'var(--text-main)' }}>
                      <div className="flex items-center gap-2">
                        <div className="w-6 h-6 rounded-md bg-cyan-500/20 text-cyan-500 font-bold flex items-center justify-center text-[10px]">
                          {f.name.substring(0, 2).toUpperCase()}
                        </div>
                        <div>
                          <div>{f.name}</div>
                          <div className="text-[10px] font-normal" style={{ color: 'var(--text-sub)' }}>{f.email || 'No email'}</div>
                        </div>
                      </div>
                    </td>
                    <td className="py-2.5 px-3.5 font-semibold text-[11px]" style={{ color: 'var(--text-muted)' }}>
                      {f.first_donation_date && f.first_donation_date !== 'N/A' ? f.first_donation_date : (f.start_date || 'N/A')}
                    </td>
                    <td className="py-2.5 px-3.5 font-black text-emerald-600 dark:text-emerald-400">
                      £{f.total_raised_period.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </td>
                    <td className="py-2.5 px-3.5 font-bold text-purple-600 dark:text-purple-400">
                      £{f.total_raised_all_time.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </td>
                    <td className="py-2.5 px-3.5 font-semibold" style={{ color: 'var(--text-main)' }}>
                      {f.target_goal > 0 ? `£${f.target_goal.toLocaleString()}` : '—'}
                    </td>
                    <td className="py-2.5 px-3.5">
                      {f.target_goal > 0 ? (
                        <div className="flex items-center gap-1.5">
                          <div className="w-14 rounded-full h-1.5 overflow-hidden" style={{ backgroundColor: 'var(--bg-card-inner)' }}>
                            <div 
                              className="bg-cyan-500 h-full rounded-full"
                              style={{ width: `${Math.min(f.progress_percentage, 100)}%` }}
                            />
                          </div>
                          <span className="font-bold text-[10px] text-cyan-600 dark:text-cyan-400">{f.progress_percentage}%</span>
                        </div>
                      ) : (
                        <span className="text-[10px]" style={{ color: 'var(--text-sub)' }}>—</span>
                      )}
                    </td>
                    <td className="py-2.5 px-3.5 font-semibold" style={{ color: 'var(--text-main)' }}>
                      {isDateFiltered ? `${f.period_donors} (period)` : f.total_donors}
                    </td>
                    <td className="py-2.5 px-3.5">
                      <div className="flex flex-wrap gap-1 max-w-[200px]">
                        {(f.assigned_campaigns || []).slice(0, 2).map((c, i) => (
                          <span key={i} className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-cyan-500/10 text-cyan-700 dark:text-cyan-300 border border-cyan-500/20 truncate max-w-[110px]">
                            {c.campaign_name}
                          </span>
                        ))}
                        {(f.assigned_campaigns || []).length > 2 && (
                          <span className="text-[9px] font-bold self-center" style={{ color: 'var(--text-sub)' }}>
                            +{f.assigned_campaigns.length - 2}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="py-2.5 px-3.5 text-right">
                      <div className="flex items-center justify-end gap-1">
                        <button
                          onClick={() => {
                            setSelectedFundraiserId(f.id);
                            setShowAllCampaigns(false);
                            setCampaignBreakdownSearch('');
                            setDrilldownStartDate(appliedStartDate);
                            setDrilldownEndDate(appliedEndDate);
                            loadDrilldown(f.id, appliedStartDate, appliedEndDate);
                          }}
                          className="p-1 rounded bg-cyan-500/10 hover:bg-cyan-500/20 text-cyan-500 transition-colors"
                          title="View Drilldown"
                        >
                          <Eye className="w-3 h-3" />
                        </button>
                        {isSuperAdmin && (
                          <>
                            <button
                              onClick={() => handleOpenEditModal(f)}
                              className="p-1 rounded hover:bg-slate-200 dark:hover:bg-slate-700/60 text-slate-400 hover:text-cyan-500 transition-colors"
                              title="Edit Fundraiser"
                            >
                              <Edit3 className="w-3 h-3" />
                            </button>
                            <button
                              onClick={() => setDeleteConfirm(f)}
                              className="p-1 rounded bg-rose-500/10 hover:bg-rose-500/20 text-rose-500 transition-colors"
                              title="Delete Fundraiser"
                            >
                              <Trash2 className="w-3 h-3" />
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Bottom Pagination Controls */}
      {!loading && filteredFundraisers.length > 0 && renderPaginationControls(false)}

      {/* ── Super Admin: Create / Edit Modal ─────────────────────── */}
      <FundraiserFormModal
        isOpen={showModal}
        onClose={() => setShowModal(false)}
        editingFundraiser={editingFundraiser}
        availableCampaigns={availableCampaigns}
        onSuccess={() => {
          loadFundraisers(true);
          loadCampaignsList();
        }}
        isSuperAdmin={isSuperAdmin}
        user={user}
        activeCompany={activeCompany}
      />

      {/* ── Super Admin: Delete Confirmation Modal ──────────────── */}
      {deleteConfirm && isSuperAdmin && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
          <div 
            className="glass-panel max-w-md w-full p-5 rounded-2xl border shadow-2xl animate-in zoom-in-95"
            style={{ backgroundColor: 'var(--bg-card)', borderColor: 'rgba(244,63,94,0.3)', color: 'var(--text-main)' }}
          >
            <div className="flex items-center gap-2.5 text-rose-500 mb-2.5">
              <ShieldAlert className="w-5 h-5" />
              <h3 className="text-sm font-extrabold">Confirm Delete Fundraiser</h3>
            </div>
            <p className="text-xs" style={{ color: 'var(--text-main)' }}>
              Are you sure you want to delete fundraiser <strong style={{ color: 'var(--text-main)' }}>"{deleteConfirm.name}"</strong>?
            </p>
            <p className="text-[11px] mt-1" style={{ color: 'var(--text-sub)' }}>
              This will remove the fundraiser profile and all campaign assignments. Underlying donor transactions will not be deleted.
            </p>
            <div className="flex items-center justify-end gap-2.5 mt-5">
              <button
                onClick={() => setDeleteConfirm(null)}
                className="btn-secondary text-xs px-3.5 py-1.5"
              >
                Cancel
              </button>
              <button
                onClick={() => handleDeleteFundraiser(deleteConfirm.id)}
                disabled={deleting}
                className="px-3.5 py-1.5 rounded-lg text-xs font-bold bg-rose-500 hover:bg-rose-600 text-white transition-colors flex items-center gap-1.5 shadow-md shadow-rose-500/20"
              >
                {deleting ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Trash2 className="w-3 h-3" />}
                Delete Permanently
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Drilldown Drawer: Campaign Breakdown & Donor Log ─────── */}
      {selectedFundraiserId && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/60 backdrop-blur-sm animate-in fade-in">
          <div 
            className="w-[min(1400px,96vw)] max-w-[96vw] h-full glass-panel border-l shadow-2xl flex flex-col overflow-hidden animate-in slide-in-from-right duration-300 rounded-none" 
            style={{ backgroundColor: 'var(--drawer-bg)', borderColor: 'var(--border-glass)', color: 'var(--text-main)' }}
          >
            
            {/* Drawer Header */}
            <div className="p-4 border-b flex items-center justify-between gap-3" style={{ borderColor: 'var(--border-glass)' }}>
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-lg bg-cyan-500/20 text-cyan-500 font-black flex items-center justify-center text-xs border border-cyan-500/30">
                  {drilldownData?.fundraiser?.name?.substring(0, 2).toUpperCase() || 'FR'}
                </div>
                <div>
                  <h3 className="text-sm font-black" style={{ color: 'var(--text-main)' }}>
                    {drilldownData?.fundraiser?.name || 'Fundraiser Performance'}
                  </h3>
                  <div className="text-[11px] flex items-center gap-2 flex-wrap" style={{ color: 'var(--text-muted)' }}>
                    {(drilldownStartDate || drilldownEndDate || drilldownData?.fundraiser?.is_custom_filtered) ? (
                      <>
                        <span className="px-1.5 py-0.2 rounded text-[10px] font-bold bg-cyan-500/10 text-cyan-600 dark:text-cyan-400 border border-cyan-500/20">
                          Period
                        </span>
                        <span>First Gift: <strong>{drilldownData?.fundraiser?.first_donation_date || 'N/A'}</strong></span>
                        {drilldownData?.fundraiser?.latest_donation_date && drilldownData?.fundraiser?.latest_donation_date !== 'N/A' && (
                          <span>• Latest: <strong>{drilldownData?.fundraiser?.latest_donation_date}</strong></span>
                        )}
                        {drilldownData?.fundraiser?.first_donation_date_all_time && (
                          <span className="opacity-70 text-[10px] hidden sm:inline">(All-Time: {drilldownData?.fundraiser?.first_donation_date_all_time} → {drilldownData?.fundraiser?.latest_donation_date_all_time})</span>
                        )}
                      </>
                    ) : (
                      <>
                        <span>First Gift: <strong>{drilldownData?.fundraiser?.first_donation_date || drilldownData?.fundraiser?.start_date || 'N/A'}</strong></span>
                        {drilldownData?.fundraiser?.latest_donation_date && drilldownData?.fundraiser?.latest_donation_date !== 'N/A' && (
                          <span>• Latest: <strong>{drilldownData?.fundraiser?.latest_donation_date}</strong></span>
                        )}
                      </>
                    )}
                    <span>• Goal: £{drilldownData?.fundraiser?.target_goal?.toLocaleString() || '0'}</span>
                    {drilldownData?.fundraiser?.net_received_all_time !== undefined && (
                      <span title="Totals here are what the platforms show (gross). This is what reached the charity after platform fees.">
                        • Net received after fees: £{Number(drilldownData.fundraiser.net_received_all_time).toLocaleString()}
                      </span>
                    )}
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-1.5">
                {canEditPages && drilldownData?.fundraiser && (
                  <button type="button" onClick={() => setAddingDonationFor(drilldownData.fundraiser)}
                    className="px-2.5 py-1.5 rounded-lg text-xs font-bold bg-emerald-600 hover:bg-emerald-500 text-white flex items-center gap-1" title="Record an offline donation for this fundraiser">
                    <Plus className="w-3.5 h-3.5" /> Add donation
                  </button>
                )}
                <button
                  onClick={() => loadDrilldown(selectedFundraiserId, drilldownStartDate, drilldownEndDate)}
                  disabled={loadingDrilldown}
                  title="Refresh fundraiser data"
                  className="p-1.5 rounded-lg text-slate-400 hover:text-cyan-500 hover:bg-slate-200 dark:hover:bg-slate-800 transition-colors disabled:opacity-50"
                >
                  <RefreshCw className={`w-4 h-4 ${loadingDrilldown ? 'animate-spin text-cyan-500' : ''}`} />
                </button>
                <button
                  onClick={() => {
                    setSelectedFundraiserId(null);
                    setDrilldownData(null);
                    setShowAllCampaigns(false);
                    setCampaignBreakdownSearch('');
                  }}
                  className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 dark:hover:text-white hover:bg-slate-200 dark:hover:bg-slate-800 transition-colors"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            </div>

            {/* Drawer Filter Sub-bar */}
            <div className="p-2.5 border-b flex items-center justify-between gap-2 flex-wrap text-xs" style={{ backgroundColor: 'var(--bg-card-inner)', borderColor: 'var(--border-glass)' }}>
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className="font-bold flex items-center gap-1 text-[11px]" style={{ color: 'var(--text-muted)' }}>
                  <Calendar className="w-3 h-3 text-cyan-500" /> Filter:
                </span>
                <input
                  type="date"
                  value={drilldownStartDate}
                  onChange={e => setDrilldownStartDate(e.target.value)}
                  className="px-2 py-0.5 text-xs rounded-md focus:outline-none"
                  style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' }}
                />
                <span style={{ color: 'var(--text-sub)' }}>&rarr;</span>
                <input
                  type="date"
                  value={drilldownEndDate}
                  onChange={e => setDrilldownEndDate(e.target.value)}
                  className="px-2 py-0.5 text-xs rounded-md focus:outline-none"
                  style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' }}
                />
                <button
                  onClick={() => loadDrilldown(selectedFundraiserId, drilldownStartDate, drilldownEndDate)}
                  className="btn-primary text-[11px] px-2 py-0.5 font-bold"
                >
                  Apply
                </button>
                {(drilldownStartDate || drilldownEndDate) && (
                  <button
                    onClick={() => {
                      setDrilldownStartDate('');
                      setDrilldownEndDate('');
                      loadDrilldown(selectedFundraiserId, '', '');
                    }}
                    className="text-rose-500 font-bold hover:underline text-[11px] ml-1"
                  >
                    Reset
                  </button>
                )}
              </div>

              <div className="font-black text-emerald-600 dark:text-emerald-400 text-xs">
                {(drilldownStartDate || drilldownEndDate) ? (
                  <span>Period: £{drilldownData?.fundraiser?.total_raised_period?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                ) : (
                  <span>All-Time: £{drilldownData?.fundraiser?.total_raised_all_time?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                )}
              </div>
            </div>

            {/* Drawer Body */}
            <div ref={drawerBodyRef} className="flex-1 overflow-y-auto p-4 custom-scrollbar flex flex-col gap-4">
              {loadingDrilldown ? (
                <div className="text-center py-10 flex flex-col items-center justify-center gap-2">
                  <RefreshCw className="w-7 h-7 text-cyan-500 animate-spin" />
                  <p className="text-xs" style={{ color: 'var(--text-muted)' }}>Loading campaign breakdown...</p>
                </div>
              ) : (
                <>
                  {/* Assigned Campaign Performance Section */}
                  <div className="flex flex-col gap-2.5">
                    <div className="flex items-center justify-between gap-2 flex-wrap">
                      <div className="flex items-center gap-2">
                        <div className="p-1 rounded-lg bg-cyan-500/10 text-cyan-600 dark:text-cyan-400">
                          <BarChart3 className="w-4 h-4" />
                        </div>
                        <h4 className="text-xs font-extrabold uppercase tracking-wider flex items-center gap-2" style={{ color: 'var(--text-main)' }}>
                          Assigned Campaign Performance
                          <span className="text-[10px] font-extrabold px-2 py-0.5 rounded-full bg-cyan-500/10 text-cyan-600 dark:text-cyan-400 border border-cyan-500/20">
                            {(drilldownData?.campaign_breakdown || []).length} campaigns
                          </span>
                        </h4>
                      </div>

                      <div className="text-xs font-black text-emerald-600 dark:text-emerald-400">
                        Total: £{totalCampaignsGross.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </div>
                    </div>

                    {/* Quick search if multiple campaigns (> 5) */}
                    {(drilldownData?.campaign_breakdown || []).length > 5 && (
                      <div className="relative">
                        <Search className="w-3.5 h-3.5 absolute left-3 top-2.5 text-slate-400" />
                        <input
                          type="text"
                          placeholder="Search campaigns by name, code, or category..."
                          value={campaignBreakdownSearch}
                          onChange={e => setCampaignBreakdownSearch(e.target.value)}
                          className="w-full pl-8 pr-7 py-1.5 text-xs rounded-lg border focus:outline-none focus:border-cyan-500 transition-colors"
                          style={{
                            backgroundColor: 'var(--input-bg)',
                            color: 'var(--input-text)',
                            borderColor: 'var(--input-border)'
                          }}
                        />
                        {campaignBreakdownSearch && (
                          <button
                            onClick={() => setCampaignBreakdownSearch('')}
                            className="absolute right-2.5 top-2 text-slate-400 hover:text-slate-600 dark:hover:text-white text-xs"
                          >
                            &times;
                          </button>
                        )}
                      </div>
                    )}

                    {/* Permanent Breakdown Table */}
                    <div className="border rounded-xl overflow-hidden max-h-72 overflow-y-auto custom-scrollbar shadow-sm" style={{ borderColor: 'var(--border-glass)', backgroundColor: 'var(--bg-card-inner)' }}>
                      <table className="w-full text-left text-xs border-collapse">
                        <thead className="sticky top-0 z-10" style={{ backgroundColor: 'var(--table-header-bg)', boxShadow: '0 1px 2px rgba(0,0,0,0.05)' }}>
                          <tr className="border-b" style={{ borderColor: 'var(--border-glass)' }}>
                            <th className="py-2.5 px-3 font-bold" style={{ color: 'var(--text-muted)' }}>Campaign</th>
                            <th className="py-2.5 px-3 font-bold" style={{ color: 'var(--text-muted)' }}>Code</th>
                            <th className="py-2.5 px-3 font-bold" style={{ color: 'var(--text-muted)' }}>Category</th>
                            <th className="py-2.5 px-3 font-bold text-right" style={{ color: 'var(--text-muted)' }}>
                              {(drilldownStartDate || drilldownEndDate) ? 'Period Raised' : 'Gross Raised'}
                            </th>
                            <th className="py-2.5 px-3 font-bold text-right" style={{ color: 'var(--text-muted)' }}>Donors</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y" style={{ borderColor: 'var(--border-glass)' }}>
                          {displayedCampaigns.length === 0 ? (
                            <tr>
                              <td colSpan={5} className="py-4 text-center" style={{ color: 'var(--text-sub)' }}>
                                {campaignBreakdownSearch
                                  ? `No campaigns match "${campaignBreakdownSearch}"`
                                  : 'No donation activity recorded for assigned campaigns yet.'}
                              </td>
                            </tr>
                          ) : (
                            displayedCampaigns.map((cb, i) => (
                              <tr key={i} className="hover:bg-slate-200/40 dark:hover:bg-slate-800/40 transition-colors">
                                <td className="py-2.5 px-3 font-bold max-w-[200px] truncate" style={{ color: 'var(--text-main)' }} title={cb.campaign_name}>
                                  {cb.campaign_name}
                                </td>
                                <td className="py-2.5 px-3 font-mono text-cyan-600 dark:text-cyan-400 font-bold text-[10px]">
                                  {cb.code}
                                </td>
                                <td className="py-2.5 px-3 text-[10px]" style={{ color: 'var(--text-muted)' }}>
                                  {cb.heading}
                                </td>
                                <td className="py-2.5 px-3 font-black text-emerald-600 dark:text-emerald-400 text-right">
                                  £{cb.gross_raised.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                                </td>
                                <td className="py-2.5 px-3 text-right font-semibold" style={{ color: 'var(--text-main)' }}>
                                  {cb.total_donors}
                                </td>
                              </tr>
                            ))
                          )}
                        </tbody>
                      </table>
                    </div>

                    {/* Expand/Collapse toggle button when > 5 campaigns and not searching */}
                    {!campaignBreakdownSearch && (drilldownData?.campaign_breakdown || []).length > 5 && (
                      <button
                        type="button"
                        onClick={() => setShowAllCampaigns(prev => !prev)}
                        className="w-full py-2 px-3 rounded-lg border text-center text-xs font-bold transition-all flex items-center justify-center gap-1.5 hover:bg-slate-200/40 dark:hover:bg-slate-800/40 cursor-pointer"
                        style={{ borderColor: 'var(--border-glass)', color: 'var(--accent-cyan)' }}
                      >
                        {showAllCampaigns ? (
                          <>Show Less (Top 5 Only) <ChevronUp className="w-3.5 h-3.5" /></>
                        ) : (
                          <>Show All {(drilldownData?.campaign_breakdown || []).length} Campaigns ({(drilldownData?.campaign_breakdown || []).length - 5} more) <ChevronDown className="w-3.5 h-3.5" /></>
                        )}
                      </button>
                    )}
                  </div>

                  {/* Tracked pages & campaigns: what each assignment brought in (live) */}
                  {(drilldownData?.tracked_pages || []).length > 0 && (
                    <div className="glass-panel p-3">
                      <h4 className="text-xs font-bold mb-2 flex items-center gap-1.5" style={{ color: 'var(--text-main)' }}>
                        <Layers className="w-3.5 h-3.5 text-violet-500" /> Tracked pages &amp; campaigns ({drilldownData.tracked_pages.length})
                      </h4>
                      <div className="overflow-x-auto">
                        <table className="w-full text-[11px]">
                          <thead><tr style={{ color: 'var(--text-sub)' }} className="text-left">
                            <th className="py-1 pr-2">Type</th><th className="py-1 pr-2">Page / campaign</th>
                            <th className="py-1 pr-2 text-right">{drilldownData?.fundraiser?.is_custom_filtered ? 'Period' : 'Raised'}</th>
                            <th className="py-1 pr-2 text-right">Gifts</th><th className="py-1 pr-2 text-right">Donors</th><th className="py-1 text-right">Latest gift</th>
                          </tr></thead>
                          <tbody>
                            {drilldownData.tracked_pages.map(tp => (
                              <tr key={tp.assignment_id} className="border-t" style={{ borderColor: 'var(--border-glass)', color: 'var(--text-main)' }}>
                                <td className="py-1 pr-2 whitespace-nowrap font-bold text-violet-600 dark:text-violet-300">{tp.match_label}</td>
                                <td className="py-1 pr-2 max-w-[260px] truncate" title={tp.value}>{tp.value}</td>
                                <td className="py-1 pr-2 text-right font-bold">£{(drilldownData?.fundraiser?.is_custom_filtered ? tp.raised_period : tp.raised_all_time).toLocaleString()}</td>
                                <td className="py-1 pr-2 text-right">{drilldownData?.fundraiser?.is_custom_filtered ? tp.donations_period : tp.donations_all_time}</td>
                                <td className="py-1 pr-2 text-right">{tp.donors}</td>
                                <td className="py-1 text-right">{tp.latest_donation_date || '—'}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}

                  {/* Monthly Timeline */}
                  {(drilldownData?.monthly_timeline || []).length > 0 && (
                    <div>
                      <h4 className="text-xs font-extrabold uppercase tracking-wider mb-2 flex items-center gap-1.5" style={{ color: 'var(--text-muted)' }}>
                        <TrendingUp className="w-3.5 h-3.5 text-purple-500" /> Monthly Growth Breakdown
                      </h4>
                      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                        {drilldownData.monthly_timeline.map((m, i) => (
                          <div 
                            key={i} 
                            className="p-2 rounded-lg border text-center transition-all"
                            style={{ backgroundColor: 'var(--bg-card-inner)', borderColor: 'var(--border-glass)' }}
                          >
                            <div className="text-[9px] font-bold uppercase" style={{ color: 'var(--text-sub)' }}>{m.month}</div>
                            <div className="text-[11px] font-black text-purple-600 dark:text-purple-400 mt-0.5">
                              £{m.amount.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Every donation in the period, with full detail */}
                  <div>
                    <div className="flex items-center justify-between gap-2 flex-wrap mb-2">
                      <h4 className="text-xs font-extrabold uppercase tracking-wider flex items-center gap-1.5" style={{ color: 'var(--text-muted)' }}>
                        <Clock className="w-3.5 h-3.5 text-cyan-500" /> Donations ({(drilldownData?.transactions_total ?? drilldownData?.recent_transactions?.length ?? 0).toLocaleString()}{drilldownData?.transactions_total > (drilldownData?.recent_transactions?.length || 0) ? `, newest ${drilldownData.recent_transactions.length.toLocaleString()} shown` : ''})
                      </h4>
                      <span className="relative">
                        <Search className="w-3.5 h-3.5 absolute left-2 top-1/2 -translate-y-1/2 text-slate-400" />
                        <input id="fundraiser-tx-filter" value={txFilter} onChange={e => setTxFilter(e.target.value)} placeholder="Filter donor, campaign, code…"
                          className="pl-7 pr-2 py-1 text-xs rounded-lg w-64" style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' }} />
                      </span>
                    </div>
                    <div className="border rounded-lg overflow-auto max-h-[50vh] custom-scrollbar" style={{ borderColor: 'var(--border-glass)' }}>
                      <table className="w-full text-left text-xs border-collapse">
                        <thead className="sticky top-0 z-10">
                          <tr className="border-b" style={{ backgroundColor: 'var(--table-header-bg)', borderColor: 'var(--border-glass)' }}>
                            {['Date', 'Donor', 'Email', 'Campaign', 'Giving level', 'Code', 'Heading', 'Sub-heading', 'Tracked page', 'Gift Aid', 'Status', 'Platform', 'Donation ID', 'Raised', 'Net received'].map(h => (
                              <th key={h} className={`py-1.5 px-2.5 font-bold whitespace-nowrap ${h === 'Raised' || h === 'Net received' ? 'text-right' : ''}`} style={{ color: 'var(--text-muted)' }}>{h}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody className="divide-y" style={{ borderColor: 'var(--border-glass)' }}>
                          {(drilldownData?.recent_transactions || []).filter(tx => {
                            const q = txFilter.trim().toLowerCase();
                            return !q || [tx.donor_name, tx.email, tx.campaign_name, tx.code, tx.heading, tx.sub_heading, tx.giving_level, tx.donation_id, tx.tracked_page]
                              .some(v => String(v || '').toLowerCase().includes(q));
                          }).map((tx, i) => (
                            <tr key={`${tx.donation_id}-${i}`} className="hover:bg-slate-200/40 dark:hover:bg-slate-800/40 transition-colors">
                              <td className="py-1.5 px-2.5 whitespace-nowrap font-mono text-[11px]" style={{ color: 'var(--text-sub)' }}>{tx.date}</td>
                              <td className="py-1.5 px-2.5 font-bold whitespace-nowrap" style={{ color: 'var(--text-main)' }}>{tx.donor_name}</td>
                              <td className="py-1.5 px-2.5 whitespace-nowrap" style={{ color: 'var(--text-muted)' }}>{tx.email}</td>
                              <td className="py-1.5 px-2.5 min-w-[12rem]" style={{ color: 'var(--text-main)' }} title={tx.campaign_name}>{tx.campaign_name}</td>
                              <td className="py-1.5 px-2.5 whitespace-nowrap" style={{ color: 'var(--text-muted)' }}>{tx.giving_level || '—'}</td>
                              <td className="py-1.5 px-2.5 whitespace-nowrap font-mono" style={{ color: 'var(--text-main)' }}>{tx.code}</td>
                              <td className="py-1.5 px-2.5 whitespace-nowrap" style={{ color: 'var(--text-main)' }}>{tx.heading || '—'}</td>
                              <td className="py-1.5 px-2.5 whitespace-nowrap" style={{ color: 'var(--text-main)' }}>{tx.sub_heading || '—'}</td>
                              <td className="py-1.5 px-2.5 max-w-[16rem] truncate" style={{ color: 'var(--text-muted)' }} title={tx.tracked_page}>{(tx.tracked_page || '—').replace(/^https?:\/\/(www\.)?/, '')}</td>
                              <td className="py-1.5 px-2.5 whitespace-nowrap" style={{ color: 'var(--text-muted)' }}>{tx.gift_aid || '—'}</td>
                              <td className="py-1.5 px-2.5 whitespace-nowrap" style={{ color: 'var(--text-muted)' }}>{tx.status || '—'}</td>
                              <td className="py-1.5 px-2.5 whitespace-nowrap" style={{ color: 'var(--text-muted)' }}>{tx.platform}</td>
                              <td className="py-1.5 px-2.5 whitespace-nowrap font-mono text-[10px]" style={{ color: 'var(--text-muted)' }}>{tx.donation_id}</td>
                              <td className="py-1.5 px-2.5 font-bold text-emerald-600 dark:text-emerald-400 text-right whitespace-nowrap tabular-nums">£{Number(tx.amount || 0).toFixed(2)}</td>
                              <td className="py-1.5 px-2.5 text-right whitespace-nowrap tabular-nums" style={{ color: 'var(--text-muted)' }}>{tx.net_received == null ? '—' : `£${Number(tx.net_received).toFixed(2)}`}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {addingDonationFor && (
        <AddDonationModal company={activeCompany} defaults={{ fundraiser_name: addingDonationFor.name || '' }}
          onClose={() => setAddingDonationFor(null)}
          onCreated={() => { loadFundraisers(true); if (selectedFundraiserId) loadDrilldown(selectedFundraiserId, drilldownStartDate, drilldownEndDate); }} />
      )}
    </div>
  );
}
