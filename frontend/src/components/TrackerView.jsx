import React, { useEffect, useState, useMemo, useRef } from 'react';
import { 
  Target, ShieldAlert, CheckCircle2, AlertCircle, Edit3, Save, 
  UserCheck, Flame, HeartHandshake, Plus, Search, Filter, 
  ExternalLink, FileText, Video, Folder, Mail, Phone, RefreshCw, 
  Trash2, X, Send, Eye, MessageSquare, Layers, Settings,
  Check, ArrowRight, UserPlus, Users, Link2, Copy, Sparkles,
  Calendar, Award, Inbox, Clock, ChevronRight, ChevronLeft,
  ChevronsLeft, ChevronsRight, ChevronDown, ChevronUp, Code, RotateCcw,
  FileCode, Tag, HelpCircle, LayoutTemplate, Zap, AlertTriangle, Bell, Download, Sliders, SendHorizontal, EyeOff, Ban
} from 'lucide-react';
import { API_BASE_URL } from '../config';

export default function TrackerView({ user, filters, onSelectDonor, activeCompany = 'rethink', companies = [] }) {
  const isConsolidated = activeCompany === 'all';
  
  // Navigation Tabs: 'beneficiaries' | 'allocations' | 'alerts' | 'analytics' | 'outlook' | 'templates'
  const [activeTab, setActiveTab] = useState('beneficiaries');

  // --- OVERDUE ALERTS TRACKER STATE ---
  const [overdueSummary, setOverdueSummary] = useState(null);
  const [overdueDonors, setOverdueDonors] = useState([]);
  const [overdueCampaigns, setOverdueCampaigns] = useState([]);
  const [overdueTotalDonors, setOverdueTotalDonors] = useState(0);
  const [overdueTotalCampaigns, setOverdueTotalCampaigns] = useState(0);
  const [overdueActiveSubTab, setOverdueActiveSubTab] = useState('donors'); // 'donors' | 'campaigns'
  const [overdueThreshold, setOverdueThreshold] = useState(30); // 15 | 30 | 60 | 90 | custom
  const [overdueTypeFilter, setOverdueTypeFilter] = useState('All'); // 'All' | 'Orphan' | 'Hafiz' | 'Widow' | 'Ex-Prisoner'
  const [overdueSeverityFilter, setOverdueSeverityFilter] = useState('all'); // 'all' | 'critical' | 'urgent' | 'warning'
  const [overdueTargetStatusFilter, setOverdueTargetStatusFilter] = useState('all'); // 'all' | 'target_reached' | 'threshold_reached' | 'below_threshold'
  const [overdueSearchQuery, setOverdueSearchQuery] = useState('');
  const [overdueDonorPage, setOverdueDonorPage] = useState(1);
  const [overdueDonorPageSize, setOverdueDonorPageSize] = useState(15);
  const [overdueCampaignPage, setOverdueCampaignPage] = useState(1);
  const [overdueCampaignPageSize, setOverdueCampaignPageSize] = useState(15);
  const [loadingOverdue, setLoadingOverdue] = useState(false);

  // Overdue Settings & Staff Digest State
  const [showAlertSettingsModal, setShowAlertSettingsModal] = useState(false);
  const [savingAlertSettings, setSavingAlertSettings] = useState(false);
  const [sendingDigest, setSendingDigest] = useState(false);
  const [digestFeedback, setDigestFeedback] = useState(null);
  const [alertSettings, setAlertSettings] = useState({
    threshold_days: 30,
    staff_emails: '',
    digest_frequency: 'weekly',
    last_digest_sent_at: null
  });
  const [overdueDismissals, setOverdueDismissals] = useState([]);
  const [overdueDismissalsCount, setOverdueDismissalsCount] = useState(0);
  const [dismissModalData, setDismissModalData] = useState({
    isOpen: false,
    item: null,
    type: 'donor',
    reason: 'False positive / Not for 1-to-1 sponsorship',
    customReason: ''
  });
  const [dismissing, setDismissing] = useState(false);
  const [showExportMenu, setShowExportMenu] = useState(false);
  const [exportingCsv, setExportingCsv] = useState(false);

  // --- TAB 1 & 2 STATE: BENEFICIARIES & ALLOCATIONS ---
  const [beneficiaries, setBeneficiaries] = useState([]);
  const [allocations, setAllocations] = useState([]);
  const [qualifyingDonors, setQualifyingDonors] = useState([]);
  const [qualifyingCampaigns, setQualifyingCampaigns] = useState([]);
  const [allocationLeftTab, setAllocationLeftTab] = useState('donors'); // 'donors' | 'campaigns'
  const [allocationTypeFilter, setAllocationTypeFilter] = useState('all'); // 'all' | 'individual' | 'campaign'
  const [loadingData, setLoadingData] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedTypeFilter, setSelectedTypeFilter] = useState('All');
  const [selectedStatusFilter, setSelectedStatusFilter] = useState('All');
  const [selectedDonorType, setSelectedDonorType] = useState('Orphan');

  // --- DONORS LEFT PANEL SEARCH & PAGINATION STATE ---
  const [donorSearchQuery, setDonorSearchQuery] = useState('');
  const [donorSlotFilter, setDonorSlotFilter] = useState('all'); // 'all' | 'available' | 'full'
  const [donorPage, setDonorPage] = useState(1);
  const [donorPageSize, setDonorPageSize] = useState(10);

  // --- CAMPAIGNS LEFT PANEL SEARCH & PAGINATION STATE ---
  const [campaignListSearchQuery, setCampaignListSearchQuery] = useState('');
  const [campaignSlotFilter, setCampaignSlotFilter] = useState('all'); // 'all' | 'available' | 'full'
  const [campaignPage, setCampaignPage] = useState(1);
  const [campaignPageSize, setCampaignPageSize] = useState(10);

  // --- BENEFICIARIES DIRECTORY PAGINATION STATE ---
  const [beneficiaryPage, setBeneficiaryPage] = useState(1);
  const [beneficiaryPageSize, setBeneficiaryPageSize] = useState(10);

  // --- ACTIVE ALLOCATIONS PAGINATION STATE ---
  const [allocationPage, setAllocationPage] = useState(1);
  const [allocationPageSize, setAllocationPageSize] = useState(10);

  // Modals State
  const [showAddBeneficiaryModal, setShowAddBeneficiaryModal] = useState(false);
  const [editingBeneficiary, setEditingBeneficiary] = useState(null);
  const [beneficiaryForm, setBeneficiaryForm] = useState({
    sponsorship_type: 'Orphan',
    name: '',
    location: '',
    project_code: '',
    donor_folder_link: '',
    profile_link: '',
    video_link: '',
    status: 'Unallocated'
  });

  // Manual Donor Modal State
  const [showManualDonorModal, setShowManualDonorModal] = useState(false);
  const [editingManualDonor, setEditingManualDonor] = useState(null);
  const [manualDonorForm, setManualDonorForm] = useState({
    donor_name: '',
    donor_email: '',
    donor_phone: '',
    sponsorship_type: 'Orphan',
    total_donated: 480,
    custom_slots: 1,
    notes: ''
  });
  const [savingManualDonor, setSavingManualDonor] = useState(false);

  // Allocation Modal State
  const [isAllocateModalOpen, setIsAllocateModalOpen] = useState(false);
  const [allocateModalBeneficiary, setAllocateModalBeneficiary] = useState(null);
  const [modalDonorSearchQuery, setModalDonorSearchQuery] = useState('');
  const [allocationMode, setAllocationMode] = useState('donor'); // 'donor' | 'campaign'
  const [selectedDonorForAllocation, setSelectedDonorForAllocation] = useState(null);
  const [donorContactEmail, setDonorContactEmail] = useState('');
  const [donorContactPhone, setDonorContactPhone] = useState('');
  const [donorContactName, setDonorContactName] = useState('');
  const [selectedCampaignForAllocation, setSelectedCampaignForAllocation] = useState(null);
  const [campaignSearchQuery, setCampaignSearchQuery] = useState('');
  const [isCustomCampaign, setIsCustomCampaign] = useState(false);
  const [customCampaignName, setCustomCampaignName] = useState('');
  const [campaignCommunityName, setCampaignCommunityName] = useState('');
  const [campaignContactEmail, setCampaignContactEmail] = useState('');
  const [campaignContactPhone, setCampaignContactPhone] = useState('');
  const [campaignContactName, setCampaignContactName] = useState('');
  const [allocationNotes, setAllocationNotes] = useState('');
  const [modalDonorSourceTab, setModalDonorSourceTab] = useState('sponsorship'); // 'sponsorship' | 'all_crm' | 'custom'
  const [allCrmSearchQuery, setAllCrmSearchQuery] = useState('');
  const [allCrmDonors, setAllCrmDonors] = useState([]);
  const [isSearchingAllCrm, setIsSearchingAllCrm] = useState(false);

  // Left Panel All CRM Donors Tab State
  const [leftAllCrmSearchQuery, setLeftAllCrmSearchQuery] = useState('');
  const [leftAllCrmDonors, setLeftAllCrmDonors] = useState([]);
  const [isSearchingLeftAllCrm, setIsSearchingLeftAllCrm] = useState(false);

  // Searchable Beneficiary Dropdown inside Allocation Modal
  const [beneficiarySearchQuery, setBeneficiarySearchQuery] = useState('');
  const [beneficiaryTypeFilter, setBeneficiaryTypeFilter] = useState('All');
  const [isBeneficiaryDropdownOpen, setIsBeneficiaryDropdownOpen] = useState(false);
  const beneficiaryDropdownRef = useRef(null);

  useEffect(() => {
    function handleClickOutside(event) {
      if (beneficiaryDropdownRef.current && !beneficiaryDropdownRef.current.contains(event.target)) {
        setIsBeneficiaryDropdownOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);

  // Real-time Search across ALL CRM Donors (for allocation modal)
  useEffect(() => {
    if (modalDonorSourceTab !== 'all_crm' || !allCrmSearchQuery.trim()) {
      setAllCrmDonors([]);
      return;
    }
    const timer = setTimeout(() => {
      setIsSearchingAllCrm(true);
      fetch(`${API_BASE_URL}/api/tracker/search-any-donor?query=${encodeURIComponent(allCrmSearchQuery.trim())}&sponsorship_type=${encodeURIComponent(selectedDonorType)}&company_id=${activeCompany}`)
        .then(r => r.json())
        .then(data => {
          setAllCrmDonors(data.donors || []);
          setIsSearchingAllCrm(false);
        })
        .catch(err => {
          console.error('Failed to search CRM donors:', err);
          setIsSearchingAllCrm(false);
        });
    }, 300);
    return () => clearTimeout(timer);
  }, [allCrmSearchQuery, modalDonorSourceTab, selectedDonorType, activeCompany]);

  // Real-time Search across ALL CRM Donors (for left panel tab)
  useEffect(() => {
    if (allocationLeftTab !== 'all_crm' || !leftAllCrmSearchQuery.trim()) {
      setLeftAllCrmDonors([]);
      return;
    }
    const timer = setTimeout(() => {
      setIsSearchingLeftAllCrm(true);
      fetch(`${API_BASE_URL}/api/tracker/search-any-donor?query=${encodeURIComponent(leftAllCrmSearchQuery.trim())}&sponsorship_type=${encodeURIComponent(selectedDonorType)}&company_id=${activeCompany}`)
        .then(r => r.json())
        .then(data => {
          setLeftAllCrmDonors(data.donors || []);
          setIsSearchingLeftAllCrm(false);
        })
        .catch(err => {
          console.error('Failed to search left CRM donors:', err);
          setIsSearchingLeftAllCrm(false);
        });
    }, 300);
    return () => clearTimeout(timer);
  }, [leftAllCrmSearchQuery, allocationLeftTab, selectedDonorType, activeCompany]);

  // Media & Document PDF Modal
  const [previewMedia, setPreviewMedia] = useState(null); // { type: 'pdf'|'video', url: '', rawUrl: '', title: '' }

  // Multi-Year Feedbacks Timeline Modal
  const [timelineBeneficiary, setTimelineBeneficiary] = useState(null);
  const [feedbacksList, setFeedbacksList] = useState([]);
  const [loadingFeedbacks, setLoadingFeedbacks] = useState(false);
  const [showAddFeedbackForm, setShowAddFeedbackForm] = useState(false);
  const [feedbackForm, setFeedbackForm] = useState({
    feedback_title: '',
    feedback_date: new Date().toISOString().split('T')[0],
    year_label: 'Year 1 - 2026',
    report_link: '',
    video_link: '',
    donor_folder_link: '',
    progress_summary: '',
    notes: ''
  });

  // Sponsorship Renewal Lifecycle & Dates State
  const [allocationRenewalFilter, setAllocationRenewalFilter] = useState('all'); // 'all' | 'active' | 'due' | 'grace' | 'lapsed'
  const [editingDatesAllocation, setEditingDatesAllocation] = useState(null);
  const [datesForm, setDatesForm] = useState({
    start_date: '',
    end_date: '',
    renewal_status: 'active'
  });
  const [renewingAllocationId, setRenewingAllocationId] = useState(null);

  // Contact info editing state
  const [editingContactAllocation, setEditingContactAllocation] = useState(null);
  const [contactForm, setContactForm] = useState({
    donor_name: '',
    donor_email: '',
    donor_phone: ''
  });
  const [savingContact, setSavingContact] = useState(false);

  // Interactive Email Modal (Microsoft 365 / Outlook)
  const [emailModalAllocation, setEmailModalAllocation] = useState(null);
  const [emailTemplates, setEmailTemplates] = useState([]);
  const [selectedTemplateType, setSelectedTemplateType] = useState('profile_intro');
  const [emailDraft, setEmailDraft] = useState({ subject: '', body_html: '', recipient_email: '', recipient_name: '' });
  const [sendingEmail, setSendingEmail] = useState(false);

  // Two-Way Conversation Drawer
  const [conversationAllocation, setConversationAllocation] = useState(null);
  const [conversationMessages, setConversationMessages] = useState([]);
  const [loadingMessages, setLoadingMessages] = useState(false);

  // --- TAB 3 STATE: TARGETS & ANALYTICS ---
  const [stats, setStats] = useState(null);
  const [showEditTargets, setShowEditTargets] = useState(false);
  const [analyticsSubTabs, setAnalyticsSubTabs] = useState({
    Orphan: 'met',
    Widow: 'met',
    'Ex-Prisoner': 'met',
    Hafiz: 'met'
  });
  const [targetInputs, setTargetInputs] = useState({
    Hafiz: 240,
    Orphan: 480,
    Widow: 1080,
    'Ex-Prisoner': 1080
  });
  const [savingTargets, setSavingTargets] = useState(false);
  const [statusMessage, setStatusMessage] = useState('');

  // --- TAB 4 STATE: OUTLOOK / MICROSOFT 365 SETTINGS ---
  const [outlookStatus, setOutlookStatus] = useState(null);
  const [outlookCreds, setOutlookCreds] = useState({ client_id: '', client_secret: '', tenant_id: 'common' });
  const [savingOutlookCreds, setSavingOutlookCreds] = useState(false);
  const [testEmailRecipient, setTestEmailRecipient] = useState('office@rethinkcharity.org.uk');
  const [sendingTestEmail, setSendingTestEmail] = useState(false);
  const [activatingOutlookSub, setActivatingOutlookSub] = useState(false);

  const getAuthHeaders = (extra = {}) => {
    const token = localStorage.getItem('analytics_token');
    const userStr = localStorage.getItem('analytics_user');
    const headers = { ...extra };
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
    if (userStr) {
      try {
        const u = JSON.parse(userStr);
        if (u?.email) {
          headers['X-User-Email'] = u.email;
        }
      } catch (e) {}
    }
    return headers;
  };

  const getAuthUrl = (url) => {
    const userStr = localStorage.getItem('analytics_user');
    let email = user?.email || '';
    if (!email && userStr) {
      try {
        email = JSON.parse(userStr)?.email || '';
      } catch (e) {}
    }
    if (!email || url.includes('user_identity=')) return url;
    const sep = url.includes('?') ? '&' : '?';
    return `${url}${sep}user_identity=${encodeURIComponent(email)}`;
  };

  // --- TAB 5 STATE: EMAIL TEMPLATES CONFIGURATION & CHARITY THEMES ---
  const CHARITY_THEMES_PRESETS = {
    rethink: {
      id: 'rethink',
      name: 'Rethink Charity',
      short_name: 'Rethink',
      tagline: 'Transparent Impact &bull; Sustainable Change',
      accent: '#A051CF',
      badgeClass: 'bg-purple-50 text-purple-700 border-purple-200 dark:bg-purple-950/60 dark:text-purple-300 dark:border-purple-800',
      logo: '/logos/rethink_logo.jpg',
      contact_email: 'info@rethinkcharity.org',
      website_url: 'https://rethinkcharity.org',
      website_display: 'www.rethinkcharity.org'
    },
    iqra: {
      id: 'iqra',
      name: 'IQRA',
      short_name: 'IQRA',
      tagline: 'Empowering Through Knowledge &amp; Compassion',
      accent: '#00B6F0',
      badgeClass: 'bg-cyan-50 text-cyan-700 border-cyan-200 dark:bg-cyan-950/60 dark:text-cyan-300 dark:border-cyan-800',
      logo: '/logos/iqra_logo.png',
      contact_email: 'info@iqra.org',
      website_url: 'https://iqra.org',
      website_display: 'www.iqra.org'
    },
    sp: {
      id: 'sp',
      name: "Sisters' Project",
      short_name: 'SP',
      tagline: 'Supporting Sisters, Strengthening Communities',
      accent: '#BE123C',
      badgeClass: 'bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-950/60 dark:text-rose-300 dark:border-rose-800',
      logo: '/logos/sp_logo.png',
      contact_email: 'info@sistersproject.co.uk',
      website_url: 'https://www.sistersproject.co.uk',
      website_display: 'www.sistersproject.co.uk'
    }
  };

  // Selected charity theme for Tab 5 configuration
  const [selectedCharityTheme, setSelectedCharityTheme] = useState(() => {
    return activeCompany === 'iqra' ? 'iqra' : 'rethink';
  });

  // Selected charity theme for Modal 5 email dispatch
  const [selectedModalTheme, setSelectedModalTheme] = useState(() => {
    return activeCompany === 'iqra' ? 'iqra' : 'rethink';
  });

  // Allowed charity themes in current workspace (Rethink has Rethink & SP; Iqra has Iqra & SP; SP is universal)
  const availableCharityThemes = useMemo(() => {
    if (activeCompany === 'iqra') {
      return [CHARITY_THEMES_PRESETS.iqra, CHARITY_THEMES_PRESETS.sp];
    }
    if (activeCompany === 'all') {
      return [CHARITY_THEMES_PRESETS.rethink, CHARITY_THEMES_PRESETS.iqra, CHARITY_THEMES_PRESETS.sp];
    }
    return [CHARITY_THEMES_PRESETS.rethink, CHARITY_THEMES_PRESETS.sp];
  }, [activeCompany]);

  // Keep themes in sync with active workspace
  useEffect(() => {
    if (activeCompany === 'iqra' && selectedCharityTheme === 'rethink') {
      setSelectedCharityTheme('iqra');
    } else if (activeCompany === 'rethink' && selectedCharityTheme === 'iqra') {
      setSelectedCharityTheme('rethink');
    }
    if (activeCompany === 'iqra' && selectedModalTheme === 'rethink') {
      setSelectedModalTheme('iqra');
    } else if (activeCompany === 'rethink' && selectedModalTheme === 'iqra') {
      setSelectedModalTheme('rethink');
    }
  }, [activeCompany]);

  const [selectedTemplateForConfig, setSelectedTemplateForConfig] = useState('profile_intro');
  const [templateDraft, setTemplateDraft] = useState({
    id: null,
    template_type: 'profile_intro',
    subject: '',
    body_html: ''
  });
  const [templateEditorMode, setTemplateEditorMode] = useState('editor'); // 'editor' | 'preview'
  const [savingTemplate, setSavingTemplate] = useState(false);
  const [templateStatusMsg, setTemplateStatusMsg] = useState('');
  const [showAddTemplateModal, setShowAddTemplateModal] = useState(false);
  const [newTemplateForm, setNewTemplateForm] = useState({
    template_type: '',
    subject: '',
    body_html: ''
  });

  const AVAILABLE_VARIABLES = [
    { tag: '{First_Name}', label: 'Recipient / Donor First Name', example: 'Sarah' },
    { tag: '{donor_name}', label: 'Recipient / Donor Full Name', example: 'Sarah Ahmed' },
    { tag: '{Email}', label: 'Recipient Email Address', example: 'sarah.ahmed@example.com' },
    { tag: '{beneficiary_name}', label: 'Beneficiary Name', example: 'Zayd Al-Mansoor' },
    { tag: '{sponsorship_type}', label: 'Sponsorship Type', example: 'Orphan Sponsorship' },
    { tag: '{sponsorship_year}', label: 'Current Sponsorship Cycle / Year', example: 'Year 1' },
    { tag: '{renewal_deadline}', label: 'Renewal Deadline / End Date', example: '2027-09-21' },
    { tag: '{days_remaining}', label: 'Days Remaining in Cycle', example: '30 days' },
    { tag: '{project_code}', label: 'Project Code', example: 'ORPH-2026-089' },
    { tag: '{location}', label: 'Location', example: 'Gaza, Palestine' },
    { tag: '{donor_folder_link}', label: 'Donor Folder / Media Link', example: 'https://drive.google.com/folders/sample-orphan-123' },
    { tag: '{folder_link}', label: 'Folder Link (Alias)', example: 'https://drive.google.com/folders/sample-orphan-123' },
    { tag: '{profile_link}', label: 'Profile Document Link', example: 'https://drive.google.com/file/d/ORPH-2026-089/view' },
    { tag: '{video_link}', label: 'Video Update Link', example: 'https://youtube.com/watch?v=sample_video' },
    { tag: '{report_link}', label: 'Annual Report Link', example: 'https://drive.google.com/file/d/annual-feedback.pdf' },
    { tag: '{campaign_name}', label: 'Campaign / Community', example: "Jamila's Sponsor an Orphan" },
    { tag: '{community_name}', label: 'Community Name', example: 'Midlands Community' }
  ];

  // Helper function to check if string is a valid web URL
  const isWebUrl = (url) => {
    if (!url || typeof url !== 'string') return false;
    const trimmed = url.trim();
    return trimmed.startsWith('http://') || trimmed.startsWith('https://') || trimmed.startsWith('/uploads/');
  };

  // Helper function to extract embeddable document / PDF Preview URL (OneDrive, SharePoint, Google Drive, Direct PDF)
  const getEmbeddableDocUrl = (url) => {
    if (!url) return '';
    try {
      const trimmed = url.trim();
      if (!isWebUrl(trimmed)) {
        return ''; // Filename only, not a live web URL
      }
      // OneDrive / SharePoint embed support
      if (trimmed.includes('onedrive.live.com') || trimmed.includes('sharepoint.com')) {
        if (trimmed.includes('download.aspx') || trimmed.includes('embed')) return trimmed;
        return `${trimmed}${trimmed.includes('?') ? '&' : '?'}action=embedview`;
      }
      // Google Drive file link support
      const driveMatch = trimmed.match(/\/d\/([a-zA-Z0-9_-]+)/) || trimmed.match(/[?&]id=([a-zA-Z0-9_-]+)/);
      if (driveMatch && driveMatch[1]) {
        return `https://drive.google.com/file/d/${driveMatch[1]}/preview`;
      }
      return trimmed;
    } catch {
      return url;
    }
  };

  // -------------------------------------------------------------
  // DATA FETCHING
  // -------------------------------------------------------------
  const loadBeneficiariesAndAllocations = () => {
    setLoadingData(true);
    const params = new URLSearchParams();
    params.append('company_id', activeCompany);

    Promise.all([
      fetch(`${API_BASE_URL}/api/tracker/beneficiaries?${params.toString()}`).then(r => r.json()),
      fetch(`${API_BASE_URL}/api/tracker/allocations?${params.toString()}`).then(r => r.json()),
      fetch(`${API_BASE_URL}/api/tracker/qualifying-donors?company_id=${activeCompany}&sponsorship_type=${selectedDonorType}`).then(r => r.json()),
      fetch(`${API_BASE_URL}/api/tracker/qualifying-campaigns?company_id=${activeCompany}&sponsorship_type=${selectedDonorType}`).then(r => r.json()),
      fetch(`${API_BASE_URL}/api/tracker/outlook/status?company_id=${activeCompany}`).then(r => r.json()),
      fetch(`${API_BASE_URL}/api/tracker/email-templates?company_id=${activeCompany}`).then(r => r.json())
    ])
      .then(([bData, aData, qData, cData, oData, tData]) => {
        setBeneficiaries(bData?.beneficiaries || []);
        setAllocations(aData?.allocations || []);
        setQualifyingDonors(qData?.donors || []);
        setQualifyingCampaigns(cData?.campaigns || []);
        setOutlookStatus(oData || null);
        if (oData?.tenant_id) {
          setOutlookCreds(prev => ({
            ...prev,
            tenant_id: oData.tenant_id || '76312bf2-382f-4ef6-8466-97c26aa8c92f',
            client_id: prev.client_id || (oData.client_id_set ? 'a068a95b-b576-42b1-8f8c-530d76fc40b7' : '')
          }));
        }
        setEmailTemplates(tData?.templates || []);
        setLoadingData(false);
      })
      .catch(err => {
        console.error('Error fetching tracker data:', err);
        setLoadingData(false);
      });
  };

  const loadTrackerStats = () => {
    const params = new URLSearchParams();
    params.append('company_id', activeCompany);
    if (filters) {
      Object.keys(filters).forEach(k => {
        if (filters[k]) params.append(k, filters[k]);
      });
    }

    fetch(`${API_BASE_URL}/api/tracker/stats?${params.toString()}`)
      .then(res => res.json())
      .then(data => {
        setStats(data);
        if (data) {
          setTargetInputs({
            Hafiz: data.Hafiz?.target || 240,
            Orphan: data.Orphan?.target || 480,
            Widow: data.Widow?.target || 1080,
            'Ex-Prisoner': data['Ex-Prisoner']?.target || 1080
          });
        }
      })
      .catch(console.error);
  };

  const loadOverdueSummary = (forceRefresh = false) => {
    fetch(`${API_BASE_URL}/api/tracker/overdue-summary?company_id=${activeCompany}&threshold_days=${overdueThreshold}${forceRefresh ? '&force_refresh=true' : ''}`)
      .then(r => r.json())
      .then(data => {
        setOverdueSummary(data);
        if (data?.dismissals_count !== undefined) {
          setOverdueDismissalsCount(data.dismissals_count);
        }
      })
      .catch(console.error);
  };

  const loadOverdueSettings = () => {
    fetch(`${API_BASE_URL}/api/tracker/overdue-settings?company_id=${activeCompany}`)
      .then(r => r.json())
      .then(data => {
        if (data) {
          setAlertSettings(data);
          if (data.threshold_days) setOverdueThreshold(data.threshold_days);
        }
      })
      .catch(console.error);
  };

  const loadOverdueDonors = (forceRefresh = false) => {
    setLoadingOverdue(true);
    const params = new URLSearchParams({
      company_id: activeCompany,
      sponsorship_type: overdueTypeFilter,
      target_status: overdueTargetStatusFilter,
      min_days: overdueThreshold,
      severity: overdueSeverityFilter,
      page: overdueDonorPage,
      page_size: overdueDonorPageSize
    });
    if (overdueSearchQuery) params.append('search', overdueSearchQuery);
    if (forceRefresh) params.append('force_refresh', 'true');

    fetch(`${API_BASE_URL}/api/tracker/overdue-donors?${params.toString()}`)
      .then(r => r.json())
      .then(data => {
        setOverdueDonors(data?.records || []);
        setOverdueTotalDonors(data?.total_records || 0);
        setLoadingOverdue(false);
      })
      .catch(err => {
        console.error('Error fetching overdue donors:', err);
        setLoadingOverdue(false);
      });
  };

  const loadOverdueCampaigns = (forceRefresh = false) => {
    setLoadingOverdue(true);
    const params = new URLSearchParams({
      company_id: activeCompany,
      sponsorship_type: overdueTypeFilter,
      target_status: overdueTargetStatusFilter,
      min_days: overdueThreshold,
      severity: overdueSeverityFilter,
      page: overdueCampaignPage,
      page_size: overdueCampaignPageSize
    });
    if (overdueSearchQuery) params.append('search', overdueSearchQuery);
    if (forceRefresh) params.append('force_refresh', 'true');

    fetch(`${API_BASE_URL}/api/tracker/overdue-campaigns?${params.toString()}`)
      .then(r => r.json())
      .then(data => {
        setOverdueCampaigns(data?.records || []);
        setOverdueTotalCampaigns(data?.total_records || 0);
        setLoadingOverdue(false);
      })
      .catch(err => {
        console.error('Error fetching overdue campaigns:', err);
        setLoadingOverdue(false);
      });
  };

  const loadOverdueDismissals = () => {
    fetch(`${API_BASE_URL}/api/tracker/overdue-dismissals?company_id=${activeCompany}`)
      .then(r => r.json())
      .then(data => {
        setOverdueDismissals(data?.dismissals || []);
        setOverdueDismissalsCount(data?.count || 0);
      })
      .catch(console.error);
  };

  const handleAllocateOverdueDonor = (d) => {
    setSelectedDonorForAllocation(d);
    setSelectedCampaignForAllocation(null);
    setAllocationMode('donor');
    setDonorContactName(d.donor_name || '');
    setDonorContactEmail(d.donor_email || '');
    setDonorContactPhone(d.donor_phone || '');
    setSelectedDonorType(d.sponsorship_type);
    
    // Look for matching unallocated beneficiary
    const matching = beneficiaries.find(b => (!b.allocation_id || b.status === 'Unallocated') && b.sponsorship_type === d.sponsorship_type);
    const anyAvailable = beneficiaries.find(b => !b.allocation_id || b.status === 'Unallocated');
    const targetBeneficiary = matching || anyAvailable;

    if (targetBeneficiary) {
      setAllocateModalBeneficiary(targetBeneficiary);
      setIsAllocateModalOpen(true);
    } else {
      alert(`No unallocated beneficiaries found in the database. Switching to Allocations workbench.`);
      setAllocationLeftTab('donors');
      setActiveTab('allocations');
    }
  };

  const handleAllocateOverdueCampaign = (c) => {
    setSelectedCampaignForAllocation(c);
    setSelectedDonorForAllocation(null);
    setAllocationMode('campaign');
    setIsCustomCampaign(false);
    setCampaignContactName(c.organizer_name || c.campaign_name);
    setCampaignContactEmail(c.organizer_email || '');
    setSelectedDonorType(c.sponsorship_type);

    const matching = beneficiaries.find(b => (!b.allocation_id || b.status === 'Unallocated') && b.sponsorship_type === c.sponsorship_type);
    const anyAvailable = beneficiaries.find(b => !b.allocation_id || b.status === 'Unallocated');
    const targetBeneficiary = matching || anyAvailable;

    if (targetBeneficiary) {
      setAllocateModalBeneficiary(targetBeneficiary);
      setIsAllocateModalOpen(true);
    } else {
      alert(`No unallocated beneficiaries found in the database. Switching to Allocations workbench.`);
      setAllocationLeftTab('campaigns');
      setActiveTab('allocations');
    }
  };

  const handleConfirmDismissal = () => {
    if (!dismissModalData.item) return;
    setDismissing(true);
    const finalReason = dismissModalData.reason === 'Other' 
      ? (dismissModalData.customReason || 'Other / False positive')
      : dismissModalData.reason;

    fetch(`${API_BASE_URL}/api/tracker/overdue-dismiss`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        company_id: activeCompany,
        entity_type: dismissModalData.type,
        entity_id: dismissModalData.type === 'donor' ? dismissModalData.item.donor_id : dismissModalData.item.campaign_name,
        entity_name: dismissModalData.type === 'donor' ? dismissModalData.item.donor_name : dismissModalData.item.campaign_name,
        sponsorship_type: dismissModalData.item.sponsorship_type,
        reason: finalReason
      })
    })
      .then(r => r.json())
      .then(res => {
        setDismissing(false);
        setDismissModalData({ isOpen: false, item: null, type: 'donor', reason: 'False positive / Not for 1-to-1 sponsorship', customReason: '' });
        loadOverdueSummary(true);
        loadOverdueDonors(true);
        loadOverdueCampaigns(true);
        loadOverdueDismissals();
      })
      .catch(err => {
        setDismissing(false);
        alert('Failed to dismiss alert: ' + err);
      });
  };

  const handleRestoreDismissal = (item) => {
    if (!window.confirm(`Restore "${item.entity_name || item.entity_id}" back to active overdue alerts?`)) return;
    fetch(`${API_BASE_URL}/api/tracker/overdue-undismiss`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        company_id: activeCompany,
        entity_type: item.entity_type,
        entity_id: item.entity_id,
        sponsorship_type: item.sponsorship_type
      })
    })
      .then(r => r.json())
      .then(res => {
        loadOverdueSummary(true);
        loadOverdueDonors(true);
        loadOverdueCampaigns(true);
        loadOverdueDismissals();
      })
      .catch(err => alert('Failed to restore alert: ' + err));
  };

  const handleSendOverdueDigest = (dryRun = false) => {
    setSendingDigest(true);
    setDigestFeedback(null);
    fetch(`${API_BASE_URL}/api/tracker/send-overdue-digest`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        company_id: activeCompany,
        threshold_days: overdueThreshold,
        recipient_emails: alertSettings.staff_emails,
        dry_run: dryRun
      })
    })
      .then(r => r.json())
      .then(res => {
        setSendingDigest(false);
        setDigestFeedback(res);
        if (res.status === 'success') {
          loadOverdueSettings();
        }
      })
      .catch(err => {
        setSendingDigest(false);
        setDigestFeedback({ status: 'error', message: String(err) });
      });
  };

  const handleSaveAlertSettings = (e) => {
    if (e) e.preventDefault();
    setSavingAlertSettings(true);
    fetch(`${API_BASE_URL}/api/tracker/overdue-settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        company_id: activeCompany,
        threshold_days: alertSettings.threshold_days,
        staff_emails: alertSettings.staff_emails,
        digest_frequency: alertSettings.digest_frequency
      })
    })
      .then(r => r.json())
      .then(res => {
        setSavingAlertSettings(false);
        setShowAlertSettingsModal(false);
        setOverdueThreshold(alertSettings.threshold_days);
        loadOverdueSummary();
      })
      .catch(err => {
        setSavingAlertSettings(false);
        alert('Failed to save settings: ' + err);
      });
  };

  const exportOverdueCsv = async (scope = 'current') => {
    setExportingCsv(true);
    try {
      const isDonors = overdueActiveSubTab === 'donors';
      const isDismissed = overdueActiveSubTab === 'dismissed';

      let dataList = [];

      if (isDismissed) {
        dataList = overdueDismissals || [];
        if (dataList.length === 0) {
          alert('No dismissed records available to export.');
          setExportingCsv(false);
          return;
        }
        const headers = ['Entity Name', 'Entity ID', 'Entity Type', 'Program', 'Reason', 'Dismissed By', 'Dismissed Date'];
        const rows = dataList.map(item => [
          `"${(item.entity_name || '').replace(/"/g, '""')}"`,
          `"${(item.entity_id || '').replace(/"/g, '""')}"`,
          `"${(item.entity_type || '').replace(/"/g, '""')}"`,
          `"${(item.sponsorship_type || '').replace(/"/g, '""')}"`,
          `"${(item.reason || '').replace(/"/g, '""')}"`,
          `"${(item.dismissed_by || '').replace(/"/g, '""')}"`,
          `"${(item.dismissed_at || '').replace(/"/g, '""')}"`
        ]);
        const csvContent = 'data:text/csv;charset=utf-8,\uFEFF' + [headers.join(','), ...rows.map(r => r.join(','))].join('\n');
        const encodedUri = encodeURI(csvContent);
        const link = document.createElement('a');
        link.setAttribute('href', encodedUri);
        link.setAttribute('download', `overdue_dismissed_${activeCompany}_${new Date().toISOString().slice(0, 10)}.csv`);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        setExportingCsv(false);
        return;
      }

      if (scope === 'current') {
        dataList = isDonors ? overdueDonors : overdueCampaigns;
      } else {
        // Fetch ALL matching records from API directly
        const endpoint = isDonors ? 'overdue-donors' : 'overdue-campaigns';
        const params = new URLSearchParams({
          company_id: activeCompany,
          sponsorship_type: overdueTypeFilter,
          target_status: overdueTargetStatusFilter,
          min_days: overdueThreshold,
          severity: overdueSeverityFilter,
          all_records: 'true'
        });
        if (overdueSearchQuery) params.append('search', overdueSearchQuery);

        const res = await fetch(`${API_BASE_URL}/api/tracker/${endpoint}?${params.toString()}`);
        const data = await res.json();
        dataList = data?.records || [];
      }

      if (!dataList || dataList.length === 0) {
        alert('No overdue records available to export.');
        setExportingCsv(false);
        return;
      }

      const headers = isDonors
        ? ['Donor ID', 'Donor Name', 'Email', 'Phone', 'Sponsorship Type', 'Total Donated', 'Target Amount', '% Raised', 'Target Status', 'Max Slots', 'Allocated Count', 'Remaining Slots', 'Oldest Donation Date', 'Waiting Days', 'Severity', 'Involved Campaigns']
        : ['Campaign Name', 'Community', 'Organizer Name', 'Organizer Email', 'Sponsorship Type', 'Total Raised', 'Target Amount', '% Raised', 'Target Status', 'Max Slots', 'Allocated Count', 'Remaining Slots', 'Oldest Donation Date', 'Waiting Days', 'Severity'];

      const rows = dataList.map(item => isDonors ? [
        `"${(item.donor_id || '').replace(/"/g, '""')}"`,
        `"${(item.donor_name || '').replace(/"/g, '""')}"`,
        `"${(item.donor_email || '').replace(/"/g, '""')}"`,
        `"${(item.donor_phone || '').replace(/"/g, '""')}"`,
        `"${(item.sponsorship_type || '').replace(/"/g, '""')}"`,
        item.total_donated || 0,
        item.target_amount || 0,
        item.pct_raised || 0,
        `"${item.target_status || ''}"`,
        item.max_slots || 0,
        item.allocated_count || 0,
        item.remaining_slots || 0,
        `"${item.oldest_donation_date || ''}"`,
        item.waiting_days || 0,
        `"${item.severity || ''}"`,
        `"${((item.campaigns_involved || []).join('; ') || item.campaign_names || '').replace(/"/g, '""')}"`
      ] : [
        `"${(item.campaign_name || '').replace(/"/g, '""')}"`,
        `"${(item.community_name || '').replace(/"/g, '""')}"`,
        `"${(item.organizer_name || '').replace(/"/g, '""')}"`,
        `"${(item.organizer_email || '').replace(/"/g, '""')}"`,
        `"${(item.sponsorship_type || '').replace(/"/g, '""')}"`,
        item.total_raised || 0,
        item.target_amount || 0,
        item.pct_raised || 0,
        `"${item.target_status || ''}"`,
        item.max_slots || 0,
        item.allocated_count || 0,
        item.remaining_slots || 0,
        `"${item.oldest_donation_date || ''}"`,
        item.waiting_days || 0,
        `"${item.severity || ''}"`
      ]);

      const csvContent = 'data:text/csv;charset=utf-8,\uFEFF' + [headers.join(','), ...rows.map(r => r.join(','))].join('\n');
      const encodedUri = encodeURI(csvContent);
      const link = document.createElement('a');
      link.setAttribute('href', encodedUri);
      link.setAttribute('download', `overdue_${overdueActiveSubTab}_${scope}_${activeCompany}_${new Date().toISOString().slice(0, 10)}.csv`);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    } catch (err) {
      console.error('Export failed:', err);
      alert('Failed to export CSV: ' + err.message);
    } finally {
      setExportingCsv(false);
    }
  };

  useEffect(() => {
    loadBeneficiariesAndAllocations();
    loadTrackerStats();
    loadOverdueSummary();
    loadOverdueSettings();
  }, [activeCompany, selectedDonorType, filters]);

  useEffect(() => {
    if (activeTab === 'alerts') {
      if (overdueActiveSubTab === 'donors') {
        loadOverdueDonors();
      } else if (overdueActiveSubTab === 'campaigns') {
        loadOverdueCampaigns();
      } else if (overdueActiveSubTab === 'dismissed') {
        loadOverdueDismissals();
      }
    }
  }, [activeTab, activeCompany, overdueActiveSubTab, overdueThreshold, overdueTypeFilter, overdueSeverityFilter, overdueTargetStatusFilter, overdueSearchQuery, overdueDonorPage, overdueDonorPageSize, overdueCampaignPage, overdueCampaignPageSize]);

  useEffect(() => {
    if (activeTab === 'alerts') {
      loadOverdueSummary();
      loadOverdueDismissals();
    }
  }, [activeTab, activeCompany, overdueThreshold, overdueTypeFilter, overdueSeverityFilter, overdueTargetStatusFilter, overdueSearchQuery]);

  // Sync template configuration draft when template list, charity theme, or selection changes
  useEffect(() => {
    if (emailTemplates && emailTemplates.length > 0) {
      const themeTemplates = emailTemplates.filter(t => (t.charity_theme || t.company_id || 'rethink') === selectedCharityTheme);
      const match = themeTemplates.find(t => t.template_type === selectedTemplateForConfig) || themeTemplates[0] || emailTemplates[0];
      if (match) {
        setSelectedTemplateForConfig(match.template_type);
        setTemplateDraft({
          id: match.id,
          template_type: match.template_type,
          subject: match.subject || '',
          body_html: match.body_html || ''
        });
      }
    }
  }, [selectedTemplateForConfig, selectedCharityTheme, emailTemplates]);

  // Handle Microsoft 365 OAuth Callback code from URL query param if present
  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search);
    const code = urlParams.get('code');
    if (code) {
      const redirectUri = `${window.location.origin}/sponsorship-tracker`;
      fetch(getAuthUrl(`${API_BASE_URL}/api/tracker/outlook/exchange-token`), {
        method: 'POST',
        headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({
          code,
          redirect_uri: redirectUri,
          company_id: activeCompany
        })
      })
        .then(r => r.json())
        .then(res => {
          if (res?.status === 'success') {
            setStatusMessage(`✅ Microsoft 365 connected as ${res.connected_email}`);
            window.history.replaceState({}, document.title, window.location.pathname);
            loadBeneficiariesAndAllocations();
          }
        })
        .catch(console.error);
    }
  }, []);

  // -------------------------------------------------------------
  // BENEFICIARY ACTIONS (CREATE, EDIT, DELETE)
  // -------------------------------------------------------------
  const handleSaveBeneficiary = (e) => {
    e.preventDefault();
    if (!beneficiaryForm.name || !beneficiaryForm.project_code) {
      alert('Name and Project Code are required.');
      return;
    }

    const isEditing = Boolean(editingBeneficiary);
    const endpoint = isEditing 
      ? `${API_BASE_URL}/api/tracker/beneficiaries/${editingBeneficiary.id}`
      : `${API_BASE_URL}/api/tracker/beneficiaries`;
    const method = isEditing ? 'PUT' : 'POST';

    fetch(endpoint, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...beneficiaryForm,
        company_id: activeCompany
      })
    })
      .then(r => r.json())
      .then(res => {
        if (res.status === 'success') {
          setShowAddBeneficiaryModal(false);
          setEditingBeneficiary(null);
          setBeneficiaryForm({
            sponsorship_type: 'Orphan',
            name: '',
            location: '',
            project_code: '',
            donor_folder_link: '',
            profile_link: '',
            video_link: '',
            status: 'Unallocated'
          });
          loadBeneficiariesAndAllocations();
        } else {
          alert(`Error: ${res.detail || 'Failed to save beneficiary'}`);
        }
      })
      .catch(err => alert(`Error: ${err.message}`));
  };

  const handleDeleteBeneficiary = (id, name) => {
    if (!window.confirm(`Are you sure you want to delete beneficiary "${name}"? This will also remove associated allocations.`)) return;

    fetch(getAuthUrl(`${API_BASE_URL}/api/tracker/beneficiaries/${id}`), { 
      method: 'DELETE',
      headers: getAuthHeaders()
    })
      .then(r => r.json())
      .then(res => {
        if (res.status === 'success') {
          loadBeneficiariesAndAllocations();
        }
      })
      .catch(err => alert(err.message));
  };

  // -------------------------------------------------------------
  // MANUAL DONOR ACTIONS
  // -------------------------------------------------------------
  const handleSaveManualDonor = async (e) => {
    e.preventDefault();
    if (!manualDonorForm.donor_name.trim()) {
      alert('Donor Full Name is required.');
      return;
    }
    if (!manualDonorForm.donor_email.trim() && !manualDonorForm.donor_phone.trim()) {
      alert('Please provide at least an Email address or Phone number.');
      return;
    }

    setSavingManualDonor(true);
    try {
      const isEdit = Boolean(editingManualDonor);
      const rawId = editingManualDonor?.raw_id || (editingManualDonor?.donor_id ? String(editingManualDonor.donor_id).replace('manual_', '') : null);
      const url = isEdit
        ? `${API_BASE_URL}/api/tracker/manual-donors/${rawId}`
        : `${API_BASE_URL}/api/tracker/manual-donors`;
      const method = isEdit ? 'PUT' : 'POST';

      const payload = {
        donor_name: manualDonorForm.donor_name.trim(),
        donor_email: manualDonorForm.donor_email.trim(),
        donor_phone: manualDonorForm.donor_phone.trim(),
        sponsorship_type: manualDonorForm.sponsorship_type,
        total_donated: parseFloat(manualDonorForm.total_donated) || 0.0,
        custom_slots: manualDonorForm.custom_slots ? parseInt(manualDonorForm.custom_slots) : null,
        notes: manualDonorForm.notes.trim(),
        company_id: activeCompany
      };

      const res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to save manual donor');
      }

      setShowManualDonorModal(false);
      setEditingManualDonor(null);
      setManualDonorForm({
        donor_name: '',
        donor_email: '',
        donor_phone: '',
        sponsorship_type: selectedDonorType || 'Orphan',
        total_donated: targetInputs[selectedDonorType] || 480,
        custom_slots: 1,
        notes: ''
      });
      loadBeneficiariesAndAllocations();
    } catch (err) {
      alert(err.message || 'Error saving manual donor');
    } finally {
      setSavingManualDonor(false);
    }
  };

  const handleDeleteManualDonor = async (donor) => {
    if (!window.confirm(`Are you sure you want to delete manual donor "${donor.donor_name}"?`)) {
      return;
    }
    try {
      const rawId = donor.raw_id || String(donor.donor_id).replace('manual_', '');
      const res = await fetch(`${API_BASE_URL}/api/tracker/manual-donors/${rawId}`, {
        method: 'DELETE'
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to delete manual donor');
      }
      loadBeneficiariesAndAllocations();
    } catch (err) {
      alert(err.message || 'Error deleting manual donor');
    }
  };

  // -------------------------------------------------------------
  // ALLOCATION ACTIONS
  // -------------------------------------------------------------
  const handleSelectDonorForAllocation = (d) => {
    setSelectedDonorForAllocation(d);
    if (d) {
      setDonorContactEmail((d.donor_email && d.donor_email.toLowerCase() !== 'n/a') ? d.donor_email : '');
      setDonorContactPhone((d.donor_phone && d.donor_phone.toLowerCase() !== 'n/a') ? d.donor_phone : '');
      setDonorContactName(d.donor_name || '');
    } else {
      setDonorContactEmail('');
      setDonorContactPhone('');
      setDonorContactName('');
    }
  };

  const handleConfirmAllocation = () => {
    if (!allocateModalBeneficiary) return;

    if (allocationMode === 'donor') {
      if (!selectedDonorForAllocation) {
        alert('Please select a donor or enter custom donor details.');
        return;
      }
      if (!donorContactEmail.trim() && !donorContactPhone.trim()) {
        alert('Please provide at least one contact method (Email or Phone number) for the donor.');
        return;
      }

      const isExceptional = Boolean(
        selectedDonorForAllocation.remaining_slots <= 0 ||
        selectedDonorForAllocation.status === 'ineligible' ||
        selectedDonorForAllocation.status === 'over_capacity' ||
        selectedDonorForAllocation.status === 'at_capacity' ||
        selectedDonorForAllocation.is_exceptional
      );

      fetch(`${API_BASE_URL}/api/tracker/allocations`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          beneficiary_id: allocateModalBeneficiary.id,
          allocation_type: 'individual',
          donor_email: donorContactEmail.trim(),
          donor_phone: donorContactPhone.trim(),
          donor_name: donorContactName.trim() || selectedDonorForAllocation.donor_name,
          donor_id: selectedDonorForAllocation.donor_id || donorContactEmail.trim(),
          allocated_amount: selectedDonorForAllocation.target_amount || allocateModalBeneficiary.target_amount || 480,
          admin_notes: allocationNotes,
          company_id: activeCompany,
          is_exceptional: isExceptional
        })
      })
        .then(r => r.json())
        .then(res => {
          if (res.status === 'success') {
            setIsAllocateModalOpen(false);
            setAllocateModalBeneficiary(null);
            handleSelectDonorForAllocation(null);
            setAllocationNotes('');
            loadBeneficiariesAndAllocations();
          } else {
            alert(`Allocation Error: ${res.detail || 'Could not allocate.'}`);
          }
        })
        .catch(err => alert(err.message));
    } else {
      // Campaign / Community Mode
      if (!isCustomCampaign && !selectedCampaignForAllocation) {
        alert('Please select a campaign from the list or switch to custom campaign.');
        return;
      }
      if (isCustomCampaign && !customCampaignName.trim()) {
        alert('Please enter a campaign name.');
        return;
      }
      if (!campaignContactEmail.trim() && !campaignContactPhone.trim()) {
        alert('Please enter at least one contact method (Email or Phone Number) for the recipient.');
        return;
      }

      const campName = isCustomCampaign ? customCampaignName.trim() : selectedCampaignForAllocation.campaign_name;
      const commName = isCustomCampaign ? campaignCommunityName.trim() : (selectedCampaignForAllocation?.community_name || '');
      const contactName = campaignContactName.trim() || (isCustomCampaign ? customCampaignName.trim() : (selectedCampaignForAllocation?.organizer_name || campName));
      const targetAmt = selectedCampaignForAllocation?.target_amount || 480;

      fetch(`${API_BASE_URL}/api/tracker/allocations`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          beneficiary_id: allocateModalBeneficiary.id,
          allocation_type: 'campaign',
          campaign_name: campName,
          community_name: commName,
          donor_email: campaignContactEmail.trim(),
          donor_phone: campaignContactPhone.trim(),
          donor_name: contactName,
          allocated_amount: targetAmt,
          admin_notes: allocationNotes,
          company_id: activeCompany
        })
      })
        .then(r => r.json())
        .then(res => {
          if (res.status === 'success') {
            setIsAllocateModalOpen(false);
            setAllocateModalBeneficiary(null);
            setSelectedCampaignForAllocation(null);
            setIsCustomCampaign(false);
            setCustomCampaignName('');
            setCampaignCommunityName('');
            setCampaignContactEmail('');
            setCampaignContactPhone('');
            setCampaignContactName('');
            setAllocationNotes('');
            loadBeneficiariesAndAllocations();
          } else {
            alert(`Allocation Error: ${res.detail || 'Could not allocate.'}`);
          }
        })
        .catch(err => alert(err.message));
    }
  };

  const handleDeallocate = (allocId, bName) => {
    if (!window.confirm(`Release beneficiary "${bName}" from this donor allocation?`)) return;

    fetch(getAuthUrl(`${API_BASE_URL}/api/tracker/allocations/${allocId}`), { 
      method: 'DELETE',
      headers: getAuthHeaders()
    })
      .then(r => r.json())
      .then(res => {
        if (res.status === 'success') {
          loadBeneficiariesAndAllocations();
        }
      })
      .catch(err => alert(err.message));
  };

  // -------------------------------------------------------------
  // FEEDBACKS & TIMELINE ACTIONS
  // -------------------------------------------------------------
  const openFeedbackTimeline = (b) => {
    setTimelineBeneficiary(b);
    setLoadingFeedbacks(true);
    fetch(`${API_BASE_URL}/api/tracker/beneficiaries/${b.id}/feedbacks`)
      .then(r => r.json())
      .then(data => {
        setFeedbacksList(data?.feedbacks || []);
        setLoadingFeedbacks(false);
      })
      .catch(() => setLoadingFeedbacks(false));
  };

  const handleAddFeedback = (e) => {
    e.preventDefault();
    if (!feedbackForm.feedback_title || !timelineBeneficiary) return;

    fetch(`${API_BASE_URL}/api/tracker/beneficiaries/${timelineBeneficiary.id}/feedbacks`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...feedbackForm,
        company_id: activeCompany
      })
    })
      .then(r => r.json())
      .then(res => {
        if (res.status === 'success') {
          setShowAddFeedbackForm(false);
          setFeedbackForm({
            feedback_title: '',
            feedback_date: new Date().toISOString().split('T')[0],
            year_label: 'Year 1 - 2026',
            report_link: '',
            video_link: '',
            donor_folder_link: '',
            progress_summary: '',
            notes: ''
          });
          openFeedbackTimeline(timelineBeneficiary);
          loadBeneficiariesAndAllocations();
        }
      })
      .catch(err => alert(err.message));
  };

  const handleDeleteFeedback = (fbId) => {
    if (!window.confirm('Delete this feedback report?')) return;
    fetch(getAuthUrl(`${API_BASE_URL}/api/tracker/feedbacks/${fbId}`), { 
      method: 'DELETE',
      headers: getAuthHeaders()
    })
      .then(r => r.json())
      .then(res => {
        if (res.status === 'success' && timelineBeneficiary) {
          openFeedbackTimeline(timelineBeneficiary);
          loadBeneficiariesAndAllocations();
        }
      });
  };

  // -------------------------------------------------------------
  // SPONSORSHIP RENEWAL & DATES ACTIONS
  // -------------------------------------------------------------
  const handleRenewAllocation = (allocId) => {
    if (!window.confirm('Renew this sponsorship allocation for +1 Year (+365 days)?')) return;
    setRenewingAllocationId(allocId);

    fetch(`${API_BASE_URL}/api/tracker/allocations/${allocId}/renew`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ company_id: activeCompany })
    })
      .then(r => r.json())
      .then(res => {
        setRenewingAllocationId(null);
        if (res.status === 'success') {
          alert(`✅ Sponsorship renewed successfully!\nNew Cycle End Date: ${res.end_date}\nTotal Renewal Count: ${res.renewal_count}`);
          loadBeneficiariesAndAllocations();
        } else {
          alert(`Error renewing sponsorship: ${res.detail || 'Failed to renew'}`);
        }
      })
      .catch(err => {
        setRenewingAllocationId(null);
        alert(`Error: ${err.message}`);
      });
  };

  const handleSaveDates = (e) => {
    e.preventDefault();
    if (!editingDatesAllocation) return;

    fetch(`${API_BASE_URL}/api/tracker/allocations/${editingDatesAllocation.id}/dates`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        start_date: datesForm.start_date,
        end_date: datesForm.end_date,
        renewal_status: datesForm.renewal_status,
        company_id: activeCompany
      })
    })
      .then(r => r.json())
      .then(res => {
        if (res.status === 'success') {
          setEditingDatesAllocation(null);
          loadBeneficiariesAndAllocations();
        } else {
          alert(`Error updating dates: ${res.detail || 'Failed to update dates'}`);
        }
      })
      .catch(err => alert(`Error: ${err.message}`));
  };

  const openEditContactModal = (alloc) => {
    setEditingContactAllocation(alloc);
    setContactForm({
      donor_name: alloc.donor_name || '',
      donor_email: (alloc.donor_email && alloc.donor_email.toLowerCase() !== 'n/a') ? alloc.donor_email : '',
      donor_phone: (alloc.donor_phone && alloc.donor_phone.toLowerCase() !== 'n/a') ? alloc.donor_phone : ''
    });
  };

  const handleSaveContact = async (e) => {
    e.preventDefault();
    if (!editingContactAllocation) return;
    if (!contactForm.donor_email.trim() && !contactForm.donor_phone.trim()) {
      alert('At least one contact method (Email or Phone number) is mandatory.');
      return;
    }
    setSavingContact(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/tracker/allocations/${editingContactAllocation.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          donor_name: contactForm.donor_name.trim() || undefined,
          donor_email: contactForm.donor_email.trim(),
          donor_phone: contactForm.donor_phone.trim()
        })
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || 'Failed to update contact info');
      }
      setEditingContactAllocation(null);
      loadBeneficiariesAndAllocations();
    } catch (err) {
      alert(`Error updating contact: ${err.message}`);
    } finally {
      setSavingContact(false);
    }
  };

  // -------------------------------------------------------------
  // OUTLOOK EMAIL DISPATCH & CONVERSATIONS
  // -------------------------------------------------------------
  const [emailModalTab, setEmailModalTab] = useState('edit'); // 'edit' | 'preview'
  const openEmailDispatcher = (alloc, defaultType = 'profile_intro', defaultTheme = null) => {
    setEmailModalAllocation(alloc);
    const themeToUse = defaultTheme || selectedModalTheme || (activeCompany === 'iqra' ? 'iqra' : 'rethink');
    setSelectedModalTheme(themeToUse);
    setSelectedTemplateType(defaultType);
    setEmailModalTab('edit');

    const themeTemplates = emailTemplates.filter(t => (t.charity_theme || t.company_id || 'rethink') === themeToUse);
    const tpl = themeTemplates.find(t => t.template_type === defaultType) || emailTemplates.find(t => t.template_type === defaultType) || {
      subject: `Sponsorship Update: {beneficiary_name}`,
      body_html: `<p>Dear {donor_name},</p><p>Here is your sponsorship update for {beneficiary_name}.</p>`
    };

    const recipientEmail = alloc.is_campaign_allocation
      ? (alloc.campaign_contact_email || alloc.donor_email || '')
      : (alloc.donor_email || '');

    const recipientName = alloc.is_campaign_allocation
      ? (alloc.campaign_contact_name || alloc.campaign_name || alloc.donor_name || 'Campaign Lead')
      : (alloc.donor_name || 'Generous Donor');

    const firstName = recipientName.split(' ')[0] || recipientName;

    const replacePlaceholders = (text) => {
      if (!text) return '';
      const folderLink = alloc.donor_folder_link || alloc.profile_link || '#';
      const yearStr = alloc.sponsorship_year ? `Year ${alloc.sponsorship_year}` : 'Year 1';
      const daysLeftStr = alloc.days_remaining != null ? `${alloc.days_remaining} days` : '30 days';
      const deadlineStr = alloc.end_date || 'N/A';

      return text
        .replace(/{{First_Name}}|{First_Name}/gi, firstName)
        .replace(/{{donor_name}}|{donor_name}/gi, recipientName)
        .replace(/{{Email}}|{Email}|{{recipient_email}}|{recipient_email}/gi, recipientEmail)
        .replace(/{{beneficiary_name}}|{beneficiary_name}/gi, alloc.beneficiary_name || 'Beneficiary')
        .replace(/{{sponsorship_type}}|{sponsorship_type}/gi, alloc.sponsorship_type || 'Sponsorship')
        .replace(/{{sponsorship_year}}|{sponsorship_year}/gi, yearStr)
        .replace(/{{renewal_deadline}}|{renewal_deadline}/gi, deadlineStr)
        .replace(/{{days_remaining}}|{days_remaining}/gi, daysLeftStr)
        .replace(/{{location}}|{location}/gi, alloc.location || '')
        .replace(/{{project_code}}|{project_code}/gi, alloc.project_code || '')
        .replace(/{{donor_folder_link}}|{donor_folder_link}/gi, folderLink)
        .replace(/{{folder_link}}|{folder_link}/gi, folderLink)
        .replace(/{{profile_link}}|{profile_link}/gi, alloc.profile_link || '#')
        .replace(/{{video_link}}|{video_link}/gi, alloc.video_link || '#')
        .replace(/{{report_link}}|{report_link}/gi, alloc.report_link || alloc.profile_link || '#')
        .replace(/{{campaign_name}}|{campaign_name}/gi, alloc.campaign_name || 'Campaign')
        .replace(/{{community_name}}|{community_name}/gi, alloc.community_name || 'Community')
        .replace(/{{Subject}}|{Subject}/gi, tpl.subject || 'Sponsorship Update')
        .replace(/{{Message_Body}}|{Message_Body}/gi, 'Thank you for your generous sponsorship and support.');
    };

    setEmailDraft({
      subject: replacePlaceholders(tpl.subject),
      body_html: replacePlaceholders(tpl.body_html),
      recipient_email: recipientEmail,
      recipient_name: recipientName
    });
  };

  const handleSwitchModalTheme = (newTheme) => {
    setSelectedModalTheme(newTheme);
    if (!emailModalAllocation) return;
    const themeTemplates = emailTemplates.filter(t => (t.charity_theme || t.company_id || 'rethink') === newTheme);
    const tpl = themeTemplates.find(t => t.template_type === selectedTemplateType) || themeTemplates[0];
    if (tpl) {
      setSelectedTemplateType(tpl.template_type);

      const recipientEmail = emailModalAllocation.is_campaign_allocation
        ? (emailModalAllocation.campaign_contact_email || emailModalAllocation.donor_email || '')
        : (emailModalAllocation.donor_email || '');
      const recipientName = emailModalAllocation.is_campaign_allocation
        ? (emailModalAllocation.campaign_contact_name || emailModalAllocation.campaign_name || emailModalAllocation.donor_name || 'Campaign Lead')
        : (emailModalAllocation.donor_name || 'Generous Donor');
      const firstName = recipientName.split(' ')[0] || recipientName;

      const folderLink = emailModalAllocation.donor_folder_link || emailModalAllocation.profile_link || '#';
      const yearStr = emailModalAllocation.sponsorship_year ? `Year ${emailModalAllocation.sponsorship_year}` : 'Year 1';
      const daysLeftStr = emailModalAllocation.days_remaining != null ? `${emailModalAllocation.days_remaining} days` : '30 days';
      const deadlineStr = emailModalAllocation.end_date || 'N/A';

      const rep = (text) => (text || '')
        .replace(/{{First_Name}}|{First_Name}/gi, firstName)
        .replace(/{{donor_name}}|{donor_name}/gi, recipientName)
        .replace(/{{Email}}|{Email}|{{recipient_email}}|{recipient_email}/gi, recipientEmail)
        .replace(/{{beneficiary_name}}|{beneficiary_name}/gi, emailModalAllocation.beneficiary_name || 'Beneficiary')
        .replace(/{{sponsorship_type}}|{sponsorship_type}/gi, emailModalAllocation.sponsorship_type || 'Sponsorship')
        .replace(/{{sponsorship_year}}|{sponsorship_year}/gi, yearStr)
        .replace(/{{renewal_deadline}}|{renewal_deadline}/gi, deadlineStr)
        .replace(/{{days_remaining}}|{days_remaining}/gi, daysLeftStr)
        .replace(/{{location}}|{location}/gi, emailModalAllocation.location || '')
        .replace(/{{project_code}}|{project_code}/gi, emailModalAllocation.project_code || '')
        .replace(/{{donor_folder_link}}|{donor_folder_link}/gi, folderLink)
        .replace(/{{folder_link}}|{folder_link}/gi, folderLink)
        .replace(/{{profile_link}}|{profile_link}/gi, emailModalAllocation.profile_link || '#')
        .replace(/{{video_link}}|{video_link}/gi, emailModalAllocation.video_link || '#')
        .replace(/{{report_link}}|{report_link}/gi, emailModalAllocation.report_link || emailModalAllocation.profile_link || '#')
        .replace(/{{campaign_name}}|{campaign_name}/gi, emailModalAllocation.campaign_name || 'Campaign')
        .replace(/{{community_name}}|{community_name}/gi, emailModalAllocation.community_name || 'Community')
        .replace(/{{Subject}}|{Subject}/gi, tpl.subject || 'Sponsorship Update')
        .replace(/{{Message_Body}}|{Message_Body}/gi, 'Thank you for your generous sponsorship and support.');

      setEmailDraft(prev => ({
        ...prev,
        subject: rep(tpl.subject),
        body_html: rep(tpl.body_html)
      }));
    }
  };

  const handleSendOutlookEmail = () => {
    if (!emailModalAllocation) return;
    setSendingEmail(true);

    fetch(getAuthUrl(`${API_BASE_URL}/api/tracker/outlook/send`), {
      method: 'POST',
      headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({
        allocation_id: emailModalAllocation.id,
        template_type: selectedTemplateType,
        recipient_email: emailDraft.recipient_email,
        recipient_name: emailDraft.recipient_name,
        subject: emailDraft.subject,
        body_html: emailDraft.body_html,
        company_id: selectedModalTheme || activeCompany
      })
    })
      .then(r => r.json())
      .then(res => {
        setSendingEmail(false);
        if (res.status === 'success') {
          setEmailModalAllocation(null);
          alert('✅ Email successfully dispatched via Microsoft 365 / Outlook!');
          loadBeneficiariesAndAllocations();
        } else {
          alert(`Failed to send email: ${res.detail || 'Unknown error'}`);
        }
      })
      .catch(err => {
        setSendingEmail(false);
        alert(`Error: ${err.message}`);
      });
  };

  const openConversationDrawer = (alloc) => {
    setConversationAllocation(alloc);
    setLoadingMessages(true);
    fetch(`${API_BASE_URL}/api/tracker/allocations/${alloc.id}/communications`)
      .then(r => r.json())
      .then(data => {
        setConversationMessages(data?.messages || []);
        setLoadingMessages(false);
      })
      .catch(() => setLoadingMessages(false));
  };

  // -------------------------------------------------------------
  // EMAIL TEMPLATE MANAGEMENT ACTIONS
  // -------------------------------------------------------------
  const handleSaveTemplate = (e) => {
    if (e) e.preventDefault();
    if (!templateDraft.template_type) return;
    setSavingTemplate(true);
    setTemplateStatusMsg('');

    const effectiveCompanyId = (selectedCharityTheme === 'sp' && activeCompany === 'rethink') ? 'sp_rethink' : selectedCharityTheme;
    fetch(`${API_BASE_URL}/api/tracker/email-templates`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        company_id: effectiveCompanyId,
        template_type: templateDraft.template_type,
        subject: templateDraft.subject,
        body_html: templateDraft.body_html
      })
    })
      .then(r => r.json())
      .then(res => {
        setSavingTemplate(false);
        if (res.status === 'success') {
          setTemplateStatusMsg(`✅ Template saved for ${CHARITY_THEMES_PRESETS[selectedCharityTheme]?.name || selectedCharityTheme}!`);
          loadBeneficiariesAndAllocations();
          setTimeout(() => setTemplateStatusMsg(''), 3000);
        } else {
          setTemplateStatusMsg(`❌ ${res.detail || 'Failed to save template.'}`);
        }
      })
      .catch(err => {
        setSavingTemplate(false);
        setTemplateStatusMsg(`❌ Error: ${err.message}`);
      });
  };

  const handleResetDefaultTemplates = () => {
    const themeName = CHARITY_THEMES_PRESETS[selectedCharityTheme]?.name || selectedCharityTheme;
    if (!window.confirm(`Reset all templates to factory defaults for "${themeName}"? Any custom modifications will be overwritten.`)) return;
    setSavingTemplate(true);
    fetch(`${API_BASE_URL}/api/tracker/email-templates/reset-defaults?company_id=${activeCompany}&charity_theme=${selectedCharityTheme}`, {
      method: 'POST'
    })
      .then(r => r.json())
      .then(res => {
        setSavingTemplate(false);
        if (res.status === 'success') {
          alert(`✅ Email templates restored to default settings for ${themeName}!`);
          loadBeneficiariesAndAllocations();
        } else {
          alert(res.detail || 'Failed to reset templates');
        }
      })
      .catch(err => {
        setSavingTemplate(false);
        alert(err.message);
      });
  };

  const handleDeleteTemplate = (templateId) => {
    if (!window.confirm('Are you sure you want to delete this custom email template?')) return;
    fetch(`${API_BASE_URL}/api/tracker/email-templates/${templateId}`, {
      method: 'DELETE'
    })
      .then(r => r.json())
      .then(res => {
        if (res.status === 'success') {
          loadBeneficiariesAndAllocations();
          setSelectedTemplateForConfig('profile_intro');
        } else {
          alert(res.detail || 'Failed to delete template');
        }
      })
      .catch(err => alert(err.message));
  };

  const handleCreateCustomTemplate = (e) => {
    e.preventDefault();
    if (!newTemplateForm.template_type.trim()) {
      alert('Please enter a unique template key identifier (e.g. quarterly_checkin)');
      return;
    }
    const cleanKey = newTemplateForm.template_type.trim().toLowerCase().replace(/[^a-z0-9_]/g, '_');
    const effectiveCompanyId = (selectedCharityTheme === 'sp' && activeCompany === 'rethink') ? 'sp_rethink' : selectedCharityTheme;
    fetch(`${API_BASE_URL}/api/tracker/email-templates`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        company_id: effectiveCompanyId,
        template_type: cleanKey,
        subject: newTemplateForm.subject || `Sponsorship Update: {beneficiary_name}`,
        body_html: newTemplateForm.body_html || `<p>Dear {donor_name},</p><p>Update on {beneficiary_name}:</p>`
      })
    })
      .then(r => r.json())
      .then(res => {
        if (res.status === 'success') {
          setShowAddTemplateModal(false);
          setNewTemplateForm({ template_type: '', subject: '', body_html: '' });
          setSelectedTemplateForConfig(cleanKey);
          loadBeneficiariesAndAllocations();
        } else {
          alert(res.detail || 'Failed to create template');
        }
      })
      .catch(err => alert(err.message));
  };

  const handleSaveModalDraftAsDefault = () => {
    if (!selectedTemplateType) return;
    const themeName = CHARITY_THEMES_PRESETS[selectedModalTheme]?.name || selectedModalTheme;
    if (!window.confirm(`Save your current edits as the global default for template "${selectedTemplateType}" under ${themeName}? Future emails will use this updated text.`)) return;

    const effectiveModalCompanyId = (selectedModalTheme === 'sp' && activeCompany === 'rethink') ? 'sp_rethink' : selectedModalTheme;
    fetch(`${API_BASE_URL}/api/tracker/email-templates`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        company_id: effectiveModalCompanyId,
        template_type: selectedTemplateType,
        subject: emailDraft.subject,
        body_html: emailDraft.body_html
      })
    })
      .then(r => r.json())
      .then(res => {
        if (res.status === 'success') {
          alert(`✅ Template saved as global default for ${themeName}!`);
          loadBeneficiariesAndAllocations();
        } else {
          alert(res.detail || 'Failed to save template default');
        }
      })
      .catch(err => alert(err.message));
  };

  // -------------------------------------------------------------
  // TARGETS UPDATE
  // -------------------------------------------------------------
  const handleSaveTargets = (e) => {
    e.preventDefault();
    if (user?.role !== 'super_admin') return;
    setSavingTargets(true);
    setStatusMessage('');

    fetch(`${API_BASE_URL}/api/tracker/targets`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        company_id: activeCompany,
        user_role: user?.role,
        targets: {
          Hafiz: parseFloat(targetInputs.Hafiz) || 240,
          Orphan: parseFloat(targetInputs.Orphan) || 480,
          Widow: parseFloat(targetInputs.Widow) || 1080,
          'Ex-Prisoner': parseFloat(targetInputs['Ex-Prisoner']) || 1080
        }
      })
    })
      .then(res => res.json())
      .then(data => {
        setSavingTargets(false);
        if (data?.status === 'success') {
          setStatusMessage('✅ Targets updated successfully!');
          loadTrackerStats();
          setTimeout(() => setShowEditTargets(false), 1200);
        } else {
          setStatusMessage(`❌ ${data?.detail || 'Failed to update targets.'}`);
        }
      })
      .catch(err => {
        setSavingTargets(false);
        setStatusMessage(`❌ Error: ${err.message}`);
      });
  };

  // -------------------------------------------------------------
  // MICROSOFT 365 / OUTLOOK SETTINGS ACTIONS
  // -------------------------------------------------------------
  const handleConnectOutlookOAuth = () => {
    const redirectUri = `${window.location.origin}/sponsorship-tracker`;
    fetch(`${API_BASE_URL}/api/tracker/outlook/auth-url?company_id=${activeCompany}&redirect_uri=${encodeURIComponent(redirectUri)}`)
      .then(r => r.json())
      .then(data => {
        if (data?.auth_url) {
          window.location.href = data.auth_url;
        } else {
          alert('Please enter and save your Microsoft Azure Client ID & Secret first.');
        }
      })
      .catch(err => alert(err.message));
  };

  const handleSaveOutlookCredentials = (e) => {
    e.preventDefault();
    setSavingOutlookCreds(true);
    fetch(getAuthUrl(`${API_BASE_URL}/api/tracker/outlook/save-credentials`), {
      method: 'POST',
      headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({
        ...outlookCreds,
        company_id: activeCompany
      })
    })
      .then(r => r.json())
      .then(res => {
        setSavingOutlookCreds(false);
        if (res.status === 'success') {
          alert('Microsoft Azure credentials saved successfully!');
          loadBeneficiariesAndAllocations();
        } else {
          alert(`Failed to save credentials: ${res.detail || 'Unknown error'}`);
        }
      })
      .catch(err => {
        setSavingOutlookCreds(false);
        alert(err.message);
      });
  };

  const handleActivateOutlookSubscription = () => {
    if (!outlookStatus?.connected) {
      alert("Please click the blue 'Connect with Microsoft 365' button first to sign in to your Microsoft account. Once connected, the webhook subscription will automatically activate and self-renew!");
      return;
    }

    setActivatingOutlookSub(true);
    const notifUrl = (API_BASE_URL.startsWith('http') ? API_BASE_URL : window.location.origin + API_BASE_URL) + '/api/tracker/outlook/webhook';
    fetch(getAuthUrl(`${API_BASE_URL}/api/tracker/outlook/setup-subscription?company_id=${activeCompany}&notification_url=${encodeURIComponent(notifUrl)}`), { 
      method: 'POST',
      headers: getAuthHeaders()
    })
      .then(r => r.json())
      .then(res => {
        setActivatingOutlookSub(false);
        if (res.status === 'success') {
          alert(`✅ Microsoft Graph Webhook Subscription active! Expiration: ${res.expiration}`);
          loadBeneficiariesAndAllocations();
        } else {
          alert(`Failed to activate subscription: ${res.detail || 'Unknown error'}`);
        }
      })
      .catch(err => {
        setActivatingOutlookSub(false);
        alert(err.message);
      });
  };

  const handleSendTestOutlookEmail = () => {
    if (!outlookStatus?.connected) {
      alert("Please connect your Microsoft 365 account first.");
      return;
    }
    const targetEmail = (testEmailRecipient || 'office@rethinkcharity.org.uk').trim();
    if (!targetEmail || !targetEmail.includes('@')) {
      alert("Please enter a valid recipient email address.");
      return;
    }
    setSendingTestEmail(true);

    fetch(getAuthUrl(`${API_BASE_URL}/api/tracker/outlook/test-send`), {
      method: 'POST',
      headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({
        company_id: activeCompany,
        recipient_email: targetEmail
      })
    })
      .then(r => r.json())
      .then(res => {
        setSendingTestEmail(false);
        if (res.status === 'success') {
          alert(`✅ ${res.message}`);
        } else {
          alert(`❌ Failed to send test email: ${res.detail || res.message || 'Unknown error'}`);
        }
      })
      .catch(err => {
        setSendingTestEmail(false);
        alert(`❌ Error sending test email: ${err.message}`);
      });
  };

  // -------------------------------------------------------------
  // FILTERED & PAGINATED BENEFICIARIES
  // -------------------------------------------------------------
  useEffect(() => {
    setBeneficiaryPage(1);
  }, [searchQuery, selectedTypeFilter, selectedStatusFilter, beneficiaries.length]);

  const filteredBeneficiaries = useMemo(() => {
    return beneficiaries.filter(b => {
      if (selectedTypeFilter !== 'All' && b.sponsorship_type !== selectedTypeFilter) return false;
      if (selectedStatusFilter === 'Allocated' && !b.allocation_id) return false;
      if (selectedStatusFilter === 'Unallocated' && b.allocation_id) return false;
      if (searchQuery) {
        const q = searchQuery.toLowerCase();
        const matchesName = (b.name || '').toLowerCase().includes(q);
        const matchesCode = (b.project_code || '').toLowerCase().includes(q);
        const matchesLoc = (b.location || '').toLowerCase().includes(q);
        const matchesDonor = (b.donor_name || '').toLowerCase().includes(q);
        const matchesEmail = (b.donor_email || '').toLowerCase().includes(q);
        if (!matchesName && !matchesCode && !matchesLoc && !matchesDonor && !matchesEmail) return false;
      }
      return true;
    });
  }, [beneficiaries, selectedTypeFilter, selectedStatusFilter, searchQuery]);

  const totalBeneficiaryPages = Math.max(1, Math.ceil(filteredBeneficiaries.length / beneficiaryPageSize));
  const paginatedBeneficiaries = useMemo(() => {
    const start = (beneficiaryPage - 1) * beneficiaryPageSize;
    return filteredBeneficiaries.slice(start, start + beneficiaryPageSize);
  }, [filteredBeneficiaries, beneficiaryPage, beneficiaryPageSize]);

  // -------------------------------------------------------------
  // FILTERED & PAGINATED QUALIFYING DONORS
  // -------------------------------------------------------------
  useEffect(() => {
    setDonorPage(1);
  }, [donorSearchQuery, donorSlotFilter, selectedDonorType, activeCompany]);

  const filteredQualifyingDonors = useMemo(() => {
    return qualifyingDonors.filter(d => {
      if (donorSlotFilter === 'available' && d.remaining_slots <= 0) return false;
      if (donorSlotFilter === 'full' && d.remaining_slots > 0) return false;
      if (donorSearchQuery) {
        const q = donorSearchQuery.toLowerCase().trim();
        const cleanQ = q.replace(/[\s\-\(\)\+]/g, '');
        const cleanPhone = (d.donor_phone || '').replace(/[\s\-\(\)\+]/g, '');

        const matchesName = (d.donor_name || '').toLowerCase().includes(q);
        const matchesEmail = (d.donor_email || '').toLowerCase().includes(q);
        const matchesPhone = (d.donor_phone || '').toLowerCase().includes(q) || (Boolean(cleanQ) && cleanPhone.includes(cleanQ));
        const matchesId = (String(d.donor_id || '')).toLowerCase().includes(q);
        if (!matchesName && !matchesEmail && !matchesPhone && !matchesId) return false;
      }
      return true;
    });
  }, [qualifyingDonors, donorSearchQuery, donorSlotFilter]);

  const totalDonorPages = Math.max(1, Math.ceil(filteredQualifyingDonors.length / donorPageSize));
  const paginatedQualifyingDonors = useMemo(() => {
    const start = (donorPage - 1) * donorPageSize;
    return filteredQualifyingDonors.slice(start, start + donorPageSize);
  }, [filteredQualifyingDonors, donorPage, donorPageSize]);

  // -------------------------------------------------------------
  // FILTERED & PAGINATED QUALIFYING CAMPAIGNS
  // -------------------------------------------------------------
  useEffect(() => {
    setCampaignPage(1);
  }, [campaignListSearchQuery, campaignSlotFilter, selectedDonorType, activeCompany]);

  const filteredQualifyingCampaigns = useMemo(() => {
    return qualifyingCampaigns.filter(c => {
      if (campaignSlotFilter === 'available' && c.remaining_slots <= 0) return false;
      if (campaignSlotFilter === 'full' && c.remaining_slots > 0) return false;
      if (campaignListSearchQuery) {
        const q = campaignListSearchQuery.toLowerCase().trim();
        const matchesName = (c.campaign_name || '').toLowerCase().includes(q);
        const matchesComm = (c.community_name || '').toLowerCase().includes(q);
        const matchesEmail = (c.organizer_email || '').toLowerCase().includes(q);
        const matchesOrgName = (c.organizer_name || '').toLowerCase().includes(q);
        if (!matchesName && !matchesComm && !matchesEmail && !matchesOrgName) return false;
      }
      return true;
    });
  }, [qualifyingCampaigns, campaignListSearchQuery, campaignSlotFilter]);

  const totalCampaignPages = Math.max(1, Math.ceil(filteredQualifyingCampaigns.length / campaignPageSize));
  const paginatedQualifyingCampaigns = useMemo(() => {
    const start = (campaignPage - 1) * campaignPageSize;
    return filteredQualifyingCampaigns.slice(start, start + campaignPageSize);
  }, [filteredQualifyingCampaigns, campaignPage, campaignPageSize]);

  // -------------------------------------------------------------
  // FILTERED & PAGINATED ACTIVE ALLOCATIONS
  // -------------------------------------------------------------
  useEffect(() => {
    setAllocationPage(1);
  }, [allocationTypeFilter, allocationRenewalFilter, allocations.length]);

  const filteredAllocations = useMemo(() => {
    return allocations.filter(a => {
      if (allocationTypeFilter === 'individual' && a.allocation_type === 'campaign') return false;
      if (allocationTypeFilter === 'campaign' && a.allocation_type !== 'campaign') return false;
      if (allocationRenewalFilter !== 'all' && a.cycle_status !== allocationRenewalFilter) return false;
      return true;
    });
  }, [allocations, allocationTypeFilter, allocationRenewalFilter]);

  const totalAllocationPages = Math.max(1, Math.ceil(filteredAllocations.length / allocationPageSize));
  const paginatedAllocations = useMemo(() => {
    const start = (allocationPage - 1) * allocationPageSize;
    return filteredAllocations.slice(start, start + allocationPageSize);
  }, [filteredAllocations, allocationPage, allocationPageSize]);

  // Filtered Donors inside Modal (all eligible and override candidates)
  const modalFilteredDonors = useMemo(() => {
    return qualifyingDonors.filter(d => {
      if (modalDonorSearchQuery) {
        const q = modalDonorSearchQuery.toLowerCase().trim();
        const cleanQ = q.replace(/[\s\-\(\)\+]/g, '');
        const cleanPhone = (d.donor_phone || '').replace(/[\s\-\(\)\+]/g, '');

        const matchesName = (d.donor_name || '').toLowerCase().includes(q);
        const matchesEmail = (d.donor_email || '').toLowerCase().includes(q);
        const matchesPhone = (d.donor_phone || '').toLowerCase().includes(q) || (Boolean(cleanQ) && cleanPhone.includes(cleanQ));
        const matchesId = (String(d.donor_id || '')).toLowerCase().includes(q);
        if (!matchesName && !matchesEmail && !matchesPhone && !matchesId) return false;
      }
      return true;
    });
  }, [qualifyingDonors, modalDonorSearchQuery]);

  // All Unallocated Beneficiaries available for manual allocation
  const unallocatedBeneficiaries = useMemo(() => {
    return beneficiaries.filter(b => !b.allocation_id || b.status === 'Unallocated');
  }, [beneficiaries]);

  // Filtered Beneficiaries for Modal Searchable Dropdown
  const modalFilteredBeneficiaries = useMemo(() => {
    return unallocatedBeneficiaries.filter(b => {
      if (beneficiaryTypeFilter !== 'All' && b.sponsorship_type !== beneficiaryTypeFilter) {
        return false;
      }
      if (beneficiarySearchQuery.trim()) {
        const q = beneficiarySearchQuery.toLowerCase().trim();
        const matchesName = (b.name || '').toLowerCase().includes(q);
        const matchesCode = (b.project_code || '').toLowerCase().includes(q);
        const matchesLocation = (b.location || '').toLowerCase().includes(q);
        const matchesType = (b.sponsorship_type || '').toLowerCase().includes(q);
        return matchesName || matchesCode || matchesLocation || matchesType;
      }
      return true;
    });
  }, [unallocatedBeneficiaries, beneficiaryTypeFilter, beneficiarySearchQuery]);

  const beneficiaryTypeCounts = useMemo(() => {
    const counts = { All: unallocatedBeneficiaries.length, Orphan: 0, Hafiz: 0, Widow: 0, 'Ex-Prisoner': 0 };
    unallocatedBeneficiaries.forEach(b => {
      if (counts[b.sponsorship_type] !== undefined) {
        counts[b.sponsorship_type]++;
      }
    });
    return counts;
  }, [unallocatedBeneficiaries]);

  const SPONSORSHIP_METADATA = {
    Hafiz: { color: 'cyan', bg: 'bg-cyan-500/10 text-cyan-600 border-cyan-500/20 dark:text-cyan-400', icon: HeartHandshake },
    Orphan: { color: 'emerald', bg: 'bg-emerald-500/10 text-emerald-600 border-emerald-500/20 dark:text-emerald-400', icon: Flame },
    Widow: { color: 'purple', bg: 'bg-purple-500/10 text-purple-600 border-purple-500/20 dark:text-purple-400', icon: HeartHandshake },
    'Ex-Prisoner': { color: 'rose', bg: 'bg-rose-500/10 text-rose-600 border-rose-500/20 dark:text-rose-400', icon: UserCheck }
  };

  return (
    <div className="flex flex-col gap-6 p-1 md:p-2">
      {/* Top Header & 4 Tabs Bar */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 bg-white/80 dark:bg-slate-900/80 backdrop-blur-md p-5 rounded-2xl border border-slate-200/80 dark:border-slate-800 shadow-sm">
        <div>
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-gradient-to-br from-blue-600 to-indigo-600 text-white shadow-md">
              <Target className="w-6 h-6" />
            </div>
            <div>
              <h1 className="text-xl md:text-2xl font-black text-slate-800 dark:text-white tracking-tight flex items-center gap-2">
                Sponsorship Tracker & Allocations
                <span className="text-xs uppercase px-2.5 py-0.5 rounded-full font-bold bg-blue-50 dark:bg-blue-950/60 text-blue-600 dark:text-blue-400 border border-blue-200/60 dark:border-blue-800/60">
                  {activeCompany.toUpperCase()}
                </span>
              </h1>
              <p className="text-xs md:text-sm text-slate-500 dark:text-slate-400">
                Beneficiary allocations, multi-donor capacities, zero-disk document profiles, and Microsoft 365 / Outlook integration.
              </p>
            </div>
          </div>
        </div>

        {/* Tab Switcher Pills */}
        <div className="flex flex-wrap items-center bg-slate-100 dark:bg-slate-800/80 p-1.5 rounded-xl border border-slate-200/80 dark:border-slate-700/60 gap-1">
          <button
            onClick={() => setActiveTab('beneficiaries')}
            className={`px-3.5 py-2 rounded-lg text-xs md:text-sm font-bold transition-all flex items-center gap-2 ${
              activeTab === 'beneficiaries'
                ? 'bg-white dark:bg-slate-900 text-blue-600 dark:text-blue-400 shadow-sm border border-slate-200/60 dark:border-slate-700'
                : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
            }`}
          >
            <Users className="w-4 h-4" />
            Beneficiaries {loadingData ? <span className="inline-block w-4 h-2.5 bg-slate-300/80 dark:bg-slate-700 rounded-xs animate-pulse align-middle ml-0.5" /> : `(${beneficiaries.length})`}
          </button>

          <button
            onClick={() => setActiveTab('allocations')}
            className={`px-3.5 py-2 rounded-lg text-xs md:text-sm font-bold transition-all flex items-center gap-2 ${
              activeTab === 'allocations'
                ? 'bg-white dark:bg-slate-900 text-blue-600 dark:text-blue-400 shadow-sm border border-slate-200/60 dark:border-slate-700'
                : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
            }`}
          >
            <Layers className="w-4 h-4" />
            Allocations Matrix {loadingData ? <span className="inline-block w-4 h-2.5 bg-slate-300/80 dark:bg-slate-700 rounded-xs animate-pulse align-middle ml-0.5" /> : `(${allocations.length})`}
          </button>

          <button
            onClick={() => setActiveTab('alerts')}
            className={`px-3.5 py-2 rounded-lg text-xs md:text-sm font-bold transition-all flex items-center gap-2 ${
              activeTab === 'alerts'
                ? 'bg-gradient-to-r from-amber-500 to-rose-500 text-white shadow-sm'
                : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
            }`}
          >
            <AlertTriangle className={`w-4 h-4 ${activeTab === 'alerts' ? 'text-white' : 'text-amber-500'}`} />
            <span>Overdue Alerts</span>
            {overdueSummary && (overdueSummary.total_overdue_donors + overdueSummary.total_overdue_campaigns) > 0 && (
              <span className={`px-2 py-0.5 text-[10px] font-black rounded-full shadow-xs ${
                activeTab === 'alerts' ? 'bg-white text-rose-600' : 'bg-rose-500 text-white animate-pulse'
              }`}>
                {overdueSummary.total_overdue_donors + overdueSummary.total_overdue_campaigns}
              </span>
            )}
          </button>


          <button
            onClick={() => setActiveTab('outlook')}
            className={`px-3.5 py-2 rounded-lg text-xs md:text-sm font-bold transition-all flex items-center gap-2 ${
              activeTab === 'outlook'
                ? 'bg-white dark:bg-slate-900 text-blue-600 dark:text-blue-400 shadow-sm border border-slate-200/60 dark:border-slate-700'
                : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
            }`}
          >
            <Mail className="w-4 h-4" />
            Outlook & MS 365
            {outlookStatus?.connected && (
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
            )}
          </button>

          <button
            onClick={() => setActiveTab('templates')}
            className={`px-3.5 py-2 rounded-lg text-xs md:text-sm font-bold transition-all flex items-center gap-2 ${
              activeTab === 'templates'
                ? 'bg-white dark:bg-slate-900 text-blue-600 dark:text-blue-400 shadow-sm border border-slate-200/60 dark:border-slate-700'
                : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
            }`}
          >
            <LayoutTemplate className="w-4 h-4" />
            Email Templates {loadingData ? <span className="inline-block w-4 h-2.5 bg-slate-300/80 dark:bg-slate-700 rounded-xs animate-pulse align-middle ml-0.5" /> : `(${emailTemplates.length})`}
          </button>
        </div>
      </div>

      {/* ========================================================= */}
      {/* TAB 1: BENEFICIARIES DIRECTORY */}
      {/* ========================================================= */}
      {activeTab === 'beneficiaries' && (
        <div className="flex flex-col gap-5">
          {/* Toolbar & Filter Bar */}
          <div className="flex flex-col md:flex-row items-stretch md:items-center justify-between gap-3 bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-200/80 dark:border-slate-800 shadow-sm">
            {/* Search Input */}
            <div className="relative flex-1 max-w-md">
              <Search className="w-4 h-4 absolute left-3.5 top-3 text-slate-400" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search beneficiary, project code, donor..."
                className="w-full pl-9 pr-4 py-2 text-xs md:text-sm bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700 rounded-lg text-slate-800 dark:text-slate-100 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
              />
            </div>

            {/* Type & Status Filters */}
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex items-center bg-slate-100 dark:bg-slate-800 p-1 rounded-lg border border-slate-200 dark:border-slate-700 text-xs">
                {['All', 'Orphan', 'Widow', 'Ex-Prisoner', 'Hafiz'].map((t) => {
                  const statusSubset = selectedStatusFilter === 'All'
                    ? beneficiaries
                    : selectedStatusFilter === 'Allocated'
                    ? beneficiaries.filter(b => Boolean(b.allocation_id))
                    : beneficiaries.filter(b => !b.allocation_id);
                  const count = t === 'All' 
                    ? statusSubset.length 
                    : statusSubset.filter(b => b.sponsorship_type === t).length;
                  return (
                    <button
                      key={t}
                      onClick={() => setSelectedTypeFilter(t)}
                      className={`px-2.5 py-1 rounded-md font-semibold transition-all flex items-center gap-1.5 ${
                        selectedTypeFilter === t
                          ? 'bg-white dark:bg-slate-900 text-blue-600 dark:text-blue-400 shadow-xs font-bold'
                          : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
                      }`}
                    >
                      <span>{t}</span>
                      <span className={`text-[10px] px-1.5 py-0.2 rounded-full font-bold min-w-[18px] text-center ${
                        selectedTypeFilter === t
                          ? 'bg-blue-100 dark:bg-blue-950/80 text-blue-700 dark:text-blue-300'
                          : 'bg-slate-200/70 dark:bg-slate-700/70 text-slate-600 dark:text-slate-400'
                      }`}>
                        {loadingData ? (
                          <span className="inline-block w-2 h-2 rounded-full bg-slate-400 dark:bg-slate-500 animate-pulse align-middle" />
                        ) : (
                          count
                        )}
                      </span>
                    </button>
                  );
                })}
              </div>

              <div className="flex items-center bg-slate-100 dark:bg-slate-800 p-1 rounded-lg border border-slate-200 dark:border-slate-700 text-xs">
                {['All', 'Allocated', 'Unallocated'].map((s) => {
                  const typeSubset = selectedTypeFilter === 'All'
                    ? beneficiaries
                    : beneficiaries.filter(b => b.sponsorship_type === selectedTypeFilter);
                  const count = s === 'All'
                    ? typeSubset.length
                    : s === 'Allocated'
                    ? typeSubset.filter(b => Boolean(b.allocation_id)).length
                    : typeSubset.filter(b => !b.allocation_id).length;
                  return (
                    <button
                      key={s}
                      onClick={() => setSelectedStatusFilter(s)}
                      className={`px-2.5 py-1 rounded-md font-semibold transition-all flex items-center gap-1.5 ${
                        selectedStatusFilter === s
                          ? 'bg-white dark:bg-slate-900 text-blue-600 dark:text-blue-400 shadow-xs font-bold'
                          : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
                      }`}
                    >
                      <span>{s}</span>
                      <span className={`text-[10px] px-1.5 py-0.2 rounded-full font-bold min-w-[18px] text-center ${
                        selectedStatusFilter === s
                          ? 'bg-blue-100 dark:bg-blue-950/80 text-blue-700 dark:text-blue-300'
                          : 'bg-slate-200/70 dark:bg-slate-700/70 text-slate-600 dark:text-slate-400'
                      }`}>
                        {loadingData ? (
                          <span className="inline-block w-2 h-2 rounded-full bg-slate-400 dark:bg-slate-500 animate-pulse align-middle" />
                        ) : (
                          count
                        )}
                      </span>
                    </button>
                  );
                })}
              </div>

              {/* Action Buttons */}
              <button
                onClick={() => {
                  setEditingManualDonor(null);
                  const activeType = selectedTypeFilter !== 'All' ? selectedTypeFilter : selectedDonorType || 'Orphan';
                  setManualDonorForm({
                    donor_name: '',
                    donor_email: '',
                    donor_phone: '',
                    sponsorship_type: activeType,
                    total_donated: targetInputs[activeType] || 480,
                    custom_slots: 1,
                    notes: ''
                  });
                  setShowManualDonorModal(true);
                }}
                className="px-3 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white font-bold text-xs md:text-sm flex items-center gap-1.5 shadow-sm transition-all"
                title="Create a sponsorship donor record manually without needing to assign a beneficiary immediately"
              >
                <UserPlus className="w-4 h-4" />
                Add Manual Donor
              </button>

              <button
                onClick={() => {
                  setEditingBeneficiary(null);
                  setBeneficiaryForm({
                    sponsorship_type: 'Orphan',
                    name: '',
                    location: '',
                    project_code: '',
                    donor_folder_link: '',
                    profile_link: '',
                    video_link: '',
                    status: 'Unallocated'
                  });
                  setShowAddBeneficiaryModal(true);
                }}
                className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-bold text-xs md:text-sm flex items-center gap-2 shadow-sm transition-all"
              >
                <Plus className="w-4 h-4" />
                Add Beneficiary
              </button>
            </div>
          </div>

          {/* Beneficiaries Table */}
          <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200/80 dark:border-slate-800 shadow-sm overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b border-slate-200 dark:border-slate-800 bg-slate-50/75 dark:bg-slate-800/40 text-[11px] uppercase tracking-wider text-slate-500 dark:text-slate-400 font-bold">
                    <th className="py-3.5 px-4">Beneficiary & Type</th>
                    <th className="py-3.5 px-4">Project Code</th>
                    <th className="py-3.5 px-4">Location</th>
                    <th className="py-3.5 px-4">Profile & Media Assets</th>
                    <th className="py-3.5 px-4">Allocation Status</th>
                    <th className="py-3.5 px-4">Annual Feedbacks</th>
                    <th className="py-3.5 px-4 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60 text-xs md:text-sm">
                  {loadingData ? (
                    Array.from({ length: 8 }).map((_, idx) => (
                      <tr key={idx} className="animate-pulse border-b border-slate-100 dark:border-slate-800/60">
                        <td className="py-3.5 px-4">
                          <div className="flex items-center gap-2.5">
                            <div className="w-8 h-8 rounded-lg bg-slate-200 dark:bg-slate-800 shrink-0" />
                            <div className="space-y-1.5">
                              <div className="h-3.5 bg-slate-200 dark:bg-slate-800 rounded w-36" />
                              <div className="h-2.5 bg-slate-100 dark:bg-slate-800/70 rounded w-16" />
                            </div>
                          </div>
                        </td>
                        <td className="py-3.5 px-4">
                          <div className="h-5 bg-slate-200 dark:bg-slate-800 rounded w-28" />
                        </td>
                        <td className="py-3.5 px-4">
                          <div className="h-3.5 bg-slate-200 dark:bg-slate-800 rounded w-20" />
                        </td>
                        <td className="py-3.5 px-4">
                          <div className="flex items-center gap-2">
                            <div className="h-6 bg-slate-200 dark:bg-slate-800 rounded w-20" />
                            <div className="w-6 h-6 bg-slate-200 dark:bg-slate-800 rounded" />
                          </div>
                        </td>
                        <td className="py-3.5 px-4">
                          <div className="h-6 bg-slate-200 dark:bg-slate-800 rounded w-24" />
                        </td>
                        <td className="py-3.5 px-4">
                          <div className="h-6 bg-slate-200 dark:bg-slate-800 rounded w-20" />
                        </td>
                        <td className="py-3.5 px-4 text-right">
                          <div className="flex items-center justify-end gap-1.5">
                            <div className="w-6 h-6 bg-slate-200 dark:bg-slate-800 rounded" />
                            <div className="w-6 h-6 bg-slate-200 dark:bg-slate-800 rounded" />
                          </div>
                        </td>
                      </tr>
                    ))
                  ) : filteredBeneficiaries.length === 0 ? (
                    <tr>
                      <td colSpan={7} className="py-12 text-center text-slate-400 font-medium">
                        No beneficiaries found matching your filter criteria.
                      </td>
                    </tr>
                  ) : (
                    paginatedBeneficiaries.map((b) => {
                      const typeMeta = SPONSORSHIP_METADATA[b.sponsorship_type] || SPONSORSHIP_METADATA.Orphan;
                      const IconComp = typeMeta.icon;

                      return (
                        <tr key={b.id} className="hover:bg-slate-50/60 dark:hover:bg-slate-800/40 transition-colors">
                          {/* Beneficiary Name & Type */}
                          <td className="py-3.5 px-4">
                            <div className="flex items-center gap-2.5">
                              <div className={`p-2 rounded-lg ${typeMeta.bg} border`}>
                                <IconComp className="w-4 h-4" />
                              </div>
                              <div>
                                <div className="font-bold text-slate-800 dark:text-slate-100">{b.name}</div>
                                <span className="text-[10px] uppercase font-bold text-slate-400 tracking-wider">
                                  {b.sponsorship_type}
                                </span>
                              </div>
                            </div>
                          </td>

                          {/* Project Code */}
                          <td className="py-3.5 px-4">
                            <span className="font-mono text-xs font-bold px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700">
                              {b.project_code}
                            </span>
                          </td>

                          {/* Location */}
                          <td className="py-3.5 px-4 text-slate-600 dark:text-slate-300">
                            {b.location || '—'}
                          </td>

                          {/* Media Assets (Zero-Disk Previews) */}
                          <td className="py-3.5 px-4">
                            <div className="flex items-center gap-1.5 flex-wrap">
                              {b.profile_link ? (
                                <button
                                  onClick={() => setPreviewMedia({ type: 'pdf', url: getEmbeddableDocUrl(b.profile_link), rawUrl: b.profile_link, title: `Profile: ${b.name} (${b.project_code})` })}
                                  className="px-2.5 py-1 rounded-md bg-blue-50 dark:bg-blue-950/60 text-blue-600 dark:text-blue-400 border border-blue-200/60 dark:border-blue-800/60 font-semibold text-xs flex items-center gap-1 hover:bg-blue-100 transition-all"
                                  title="View In-App PDF Stream"
                                >
                                  <Eye className="w-3.5 h-3.5" />
                                  Profile PDF
                                </button>
                              ) : (
                                <span className="text-slate-400 text-xs italic">No PDF</span>
                              )}

                              {b.video_link && (
                                <button
                                  onClick={() => setPreviewMedia({ type: 'video', url: b.video_link, title: `Video: ${b.name}` })}
                                  className="p-1 rounded-md bg-rose-50 dark:bg-rose-950/60 text-rose-600 dark:text-rose-400 border border-rose-200/60 dark:border-rose-800/60 hover:bg-rose-100 transition-all"
                                  title="Watch Video Update"
                                >
                                  <Video className="w-3.5 h-3.5" />
                                </button>
                              )}

                              {b.donor_folder_link && (
                                <a
                                  href={b.donor_folder_link}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="p-1 rounded-md bg-amber-50 dark:bg-amber-950/60 text-amber-600 dark:text-amber-400 border border-amber-200/60 dark:border-amber-800/60 hover:bg-amber-100 transition-all"
                                  title="Open Donor Folder"
                                >
                                  <Folder className="w-3.5 h-3.5" />
                                </a>
                              )}
                            </div>
                          </td>

                          {/* Allocation Status */}
                          <td className="py-3.5 px-4">
                            {b.allocation_id ? (
                              <div className="flex flex-col gap-1">
                                <div className="flex items-center gap-1.5">
                                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-bold bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800">
                                    <Check className="w-3 h-3" />
                                    {b.donor_name || 'Allocated'}
                                  </span>
                                </div>
                                <span className="text-[10px] text-slate-400 font-mono truncate max-w-[140px]">
                                  {b.donor_email}
                                </span>
                                {b.communication_status && (
                                  <span className={`text-[10px] font-bold ${
                                    b.communication_status === 'Donor Replied' 
                                      ? 'text-cyan-600 dark:text-cyan-400 font-extrabold flex items-center gap-0.5' 
                                      : 'text-slate-500'
                                  }`}>
                                    {b.communication_status === 'Donor Replied' ? '💬 Donor Replied' : b.communication_status}
                                  </span>
                                )}
                              </div>
                            ) : (
                                <button
                                  onClick={() => {
                                    setIsAllocateModalOpen(true);
                                    setAllocateModalBeneficiary(b);
                                    handleSelectDonorForAllocation(null);
                                    setSelectedCampaignForAllocation(null);
                                    setAllocationMode('donor');
                                    setSelectedDonorType(b.sponsorship_type);
                                    setBeneficiarySearchQuery('');
                                    setBeneficiaryTypeFilter('All');
                                    setIsBeneficiaryDropdownOpen(false);
                                  }}
                                  className="px-2.5 py-1 rounded-lg bg-amber-50 dark:bg-amber-950/60 text-amber-600 dark:text-amber-400 border border-amber-200 dark:border-amber-800 text-xs font-bold hover:bg-amber-100 transition-all flex items-center gap-1"
                                >
                                  <UserPlus className="w-3.5 h-3.5" />
                                  Quick Allocate
                                </button>
                            )}
                          </td>

                          {/* Annual Feedbacks Timeline */}
                          <td className="py-3.5 px-4">
                            <button
                              onClick={() => openFeedbackTimeline(b)}
                              className="px-2.5 py-1 rounded-md bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700 font-semibold text-xs flex items-center gap-1.5 transition-all"
                            >
                              <Calendar className="w-3.5 h-3.5 text-blue-500" />
                              <span>{b.feedbacks_count || 0} Reports</span>
                            </button>
                          </td>

                          {/* Actions */}
                          <td className="py-3.5 px-4 text-right">
                            <div className="flex items-center justify-end gap-1.5">
                              {b.allocation_id && (
                                <button
                                  onClick={() => openEmailDispatcher({
                                    id: b.allocation_id,
                                    donor_name: b.donor_name,
                                    donor_email: b.donor_email,
                                    beneficiary_name: b.name,
                                    location: b.location,
                                    project_code: b.project_code,
                                    profile_link: b.profile_link,
                                    video_link: b.video_link
                                  })}
                                  className="p-1.5 rounded-lg bg-blue-50 dark:bg-blue-950/60 text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-800 hover:bg-blue-100 transition-all"
                                  title="Send Email via Outlook"
                                >
                                  <Send className="w-3.5 h-3.5" />
                                </button>
                              )}

                              <button
                                onClick={() => {
                                  setEditingBeneficiary(b);
                                  setBeneficiaryForm({
                                    sponsorship_type: b.sponsorship_type,
                                    name: b.name,
                                    location: b.location || '',
                                    project_code: b.project_code,
                                    donor_folder_link: b.donor_folder_link || '',
                                    profile_link: b.profile_link || '',
                                    video_link: b.video_link || '',
                                    status: b.status || 'Unallocated'
                                  });
                                  setShowAddBeneficiaryModal(true);
                                }}
                                className="p-1.5 rounded-lg text-slate-500 hover:text-slate-800 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-all"
                                title="Edit Beneficiary Info"
                              >
                                <Edit3 className="w-3.5 h-3.5" />
                              </button>

                              <button
                                onClick={() => handleDeleteBeneficiary(b.id, b.name)}
                                className="p-1.5 rounded-lg text-rose-500 hover:text-rose-700 hover:bg-rose-50 dark:hover:bg-rose-950/40 transition-all"
                                title="Delete Beneficiary"
                              >
                                <Trash2 className="w-3.5 h-3.5" />
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>

            {/* Beneficiaries Pagination Footer */}
            {!loadingData && filteredBeneficiaries.length > 0 && (
              <div className="p-3 bg-slate-50/70 dark:bg-slate-800/50 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between text-xs text-slate-500 flex-wrap gap-2">
                <div className="flex items-center gap-2">
                  <span className="text-[11px]">
                    Showing <strong className="text-slate-700 dark:text-slate-300">{(beneficiaryPage - 1) * beneficiaryPageSize + 1}</strong> to <strong className="text-slate-700 dark:text-slate-300">{Math.min(beneficiaryPage * beneficiaryPageSize, filteredBeneficiaries.length)}</strong> of <strong className="text-slate-700 dark:text-slate-300">{filteredBeneficiaries.length}</strong>
                  </span>
                  <select
                    value={beneficiaryPageSize}
                    onChange={(e) => {
                      setBeneficiaryPageSize(Number(e.target.value));
                      setBeneficiaryPage(1);
                    }}
                    className="px-1.5 py-0.5 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded text-[11px] font-semibold text-slate-700 dark:text-slate-300"
                  >
                    <option value={10}>10 / page</option>
                    <option value={25}>25 / page</option>
                    <option value={50}>50 / page</option>
                    <option value={100}>100 / page</option>
                  </select>
                </div>

                <div className="flex items-center gap-1">
                  <button
                    disabled={beneficiaryPage <= 1}
                    onClick={() => setBeneficiaryPage(1)}
                    className="p-1 rounded hover:bg-slate-200 dark:hover:bg-slate-700 disabled:opacity-30"
                    title="First page"
                  >
                    <ChevronsLeft className="w-3.5 h-3.5" />
                  </button>
                  <button
                    disabled={beneficiaryPage <= 1}
                    onClick={() => setBeneficiaryPage(prev => Math.max(1, prev - 1))}
                    className="p-1 rounded hover:bg-slate-200 dark:hover:bg-slate-700 disabled:opacity-30"
                    title="Previous page"
                  >
                    <ChevronLeft className="w-3.5 h-3.5" />
                  </button>

                  <span className="px-2 py-0.5 font-bold text-[11px] bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded text-slate-800 dark:text-slate-200">
                    {beneficiaryPage} / {totalBeneficiaryPages}
                  </span>

                  <button
                    disabled={beneficiaryPage >= totalBeneficiaryPages}
                    onClick={() => setBeneficiaryPage(prev => Math.min(totalBeneficiaryPages, prev + 1))}
                    className="p-1 rounded hover:bg-slate-200 dark:hover:bg-slate-700 disabled:opacity-30"
                    title="Next page"
                  >
                    <ChevronRight className="w-3.5 h-3.5" />
                  </button>
                  <button
                    disabled={beneficiaryPage >= totalBeneficiaryPages}
                    onClick={() => setBeneficiaryPage(totalBeneficiaryPages)}
                    className="p-1 rounded hover:bg-slate-200 dark:hover:bg-slate-700 disabled:opacity-30"
                    title="Last page"
                  >
                    <ChevronsRight className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ========================================================= */}
      {/* TAB 2: DONOR ALLOCATIONS MATRIX & CAPACITY ENGINE */}
      {/* ========================================================= */}
      {activeTab === 'allocations' && (
        <div className="flex flex-col gap-6">
          {/* Sponsorship Sub-Tabs Selector */}
          <div className="flex flex-wrap items-center justify-between gap-3 bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-200/80 dark:border-slate-800 shadow-sm">
            <div className="flex items-center gap-2">
              <span className="text-xs font-bold text-slate-400 uppercase tracking-wider mr-2">Sponsorship Type:</span>
              {['Orphan', 'Widow', 'Ex-Prisoner', 'Hafiz'].map((t) => (
                <button
                  key={t}
                  onClick={() => setSelectedDonorType(t)}
                  className={`px-3 py-1.5 rounded-lg text-xs md:text-sm font-bold transition-all ${
                    selectedDonorType === t
                      ? 'bg-blue-600 text-white shadow-sm'
                      : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200'
                  }`}
                >
                  {t}
                </button>
              ))}
            </div>

            <div className="flex flex-wrap items-center gap-4 text-xs font-semibold text-slate-600 dark:text-slate-400">
              <div className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full bg-emerald-500" />
                <span>Available Donors ({qualifyingDonors.filter(d => d.remaining_slots > 0).length})</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full bg-purple-500" />
                <span>Available Campaigns ({qualifyingCampaigns.filter(c => c.remaining_slots > 0).length})</span>
              </div>
              <button
                onClick={() => {
                  setEditingManualDonor(null);
                  setManualDonorForm({
                    donor_name: '',
                    donor_email: '',
                    donor_phone: '',
                    sponsorship_type: selectedDonorType,
                    total_donated: targetInputs[selectedDonorType] || 480,
                    custom_slots: 1,
                    notes: ''
                  });
                  setShowManualDonorModal(true);
                }}
                className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white font-bold text-xs flex items-center gap-1.5 shadow-sm transition-all ml-2"
                title="Create a manual sponsorship donor record"
              >
                <UserPlus className="w-3.5 h-3.5" />
                Add Manual Donor
              </button>
            </div>
          </div>

          {/* 2-Column Split: Donors & Campaigns Capacity on Left, Active Allocations on Right */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            {/* Left Column: Qualifying Donors & Campaigns Capacity Engine */}
            <div className="lg:col-span-5 flex flex-col gap-4">
              <div className="bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-200/80 dark:border-slate-800 shadow-sm flex flex-col gap-3">
                {/* Switcher Tab Header */}
                <div className="flex items-center justify-between pb-3 border-b border-slate-100 dark:border-slate-800 flex-wrap gap-2">
                  <div className="flex items-center gap-1 p-1 bg-slate-100 dark:bg-slate-800 rounded-lg">
                    <button
                      onClick={() => setAllocationLeftTab('donors')}
                      className={`px-2.5 py-1 rounded-md text-xs font-bold transition-all flex items-center gap-1.5 ${
                        allocationLeftTab === 'donors'
                          ? 'bg-white dark:bg-slate-900 text-blue-600 dark:text-blue-400 shadow-xs'
                          : 'text-slate-500 dark:text-slate-400 hover:text-slate-700'
                      }`}
                    >
                      <Users className="w-3.5 h-3.5" />
                      Donors ({qualifyingDonors.length})
                    </button>
                    <button
                      onClick={() => setAllocationLeftTab('campaigns')}
                      className={`px-2.5 py-1 rounded-md text-xs font-bold transition-all flex items-center gap-1.5 ${
                        allocationLeftTab === 'campaigns'
                          ? 'bg-white dark:bg-slate-900 text-purple-600 dark:text-purple-400 shadow-xs'
                          : 'text-slate-500 dark:text-slate-400 hover:text-slate-700'
                      }`}
                    >
                      <Layers className="w-3.5 h-3.5" />
                      Campaigns ({qualifyingCampaigns.length})
                    </button>
                    <button
                      onClick={() => setAllocationLeftTab('all_crm')}
                      className={`px-2.5 py-1 rounded-md text-xs font-bold transition-all flex items-center gap-1.5 ${
                        allocationLeftTab === 'all_crm'
                          ? 'bg-white dark:bg-slate-900 text-amber-600 dark:text-amber-400 shadow-xs'
                          : 'text-slate-500 dark:text-slate-400 hover:text-slate-700'
                      }`}
                    >
                      <Zap className="w-3.5 h-3.5 text-amber-500 fill-amber-500" />
                      All CRM Donors (Other Causes)
                    </button>
                  </div>

                  <span className="text-[11px] font-mono text-slate-500">
                    Target: £{qualifyingDonors[0]?.target_amount || 480} / slot
                  </span>
                </div>

                {/* Left Tab 1: Donors List with Search & Pagination */}
                {allocationLeftTab === 'donors' && (
                  <div className="flex flex-col gap-3">
                    {/* Search & Slot Filter Bar */}
                    <div className="flex flex-col gap-2">
                      <div className="relative">
                        <Search className="w-3.5 h-3.5 absolute left-3 top-2.5 text-slate-400" />
                        <input
                          type="text"
                          placeholder="Search donors by name, email, or phone..."
                          value={donorSearchQuery}
                          onChange={(e) => setDonorSearchQuery(e.target.value)}
                          className="w-full pl-8 pr-8 py-1.5 bg-slate-50 dark:bg-slate-800/80 border border-slate-200 dark:border-slate-700 rounded-lg text-xs"
                        />
                        {donorSearchQuery && (
                          <button
                            onClick={() => setDonorSearchQuery('')}
                            className="absolute right-2.5 top-2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
                          >
                            <X className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </div>

                      {/* Filter Chips */}
                      <div className="flex items-center justify-between text-[11px] gap-1 flex-wrap">
                        <div className="flex items-center gap-1">
                          <button
                            onClick={() => setDonorSlotFilter('all')}
                            className={`px-2 py-0.5 rounded-md font-semibold transition-all ${
                              donorSlotFilter === 'all'
                                ? 'bg-blue-600 text-white shadow-2xs'
                                : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400'
                            }`}
                          >
                            All {loadingData ? <span className="inline-block w-3 h-2 bg-slate-300 dark:bg-slate-700 rounded-xs animate-pulse align-middle" /> : `(${qualifyingDonors.length})`}
                          </button>
                          <button
                            onClick={() => setDonorSlotFilter('available')}
                            className={`px-2 py-0.5 rounded-md font-semibold transition-all ${
                              donorSlotFilter === 'available'
                                ? 'bg-emerald-600 text-white shadow-2xs'
                                : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400'
                            }`}
                          >
                            Available {loadingData ? <span className="inline-block w-3 h-2 bg-slate-300 dark:bg-slate-700 rounded-xs animate-pulse align-middle" /> : `(${qualifyingDonors.filter(d => d.remaining_slots > 0).length})`}
                          </button>
                          <button
                            onClick={() => setDonorSlotFilter('full')}
                            className={`px-2 py-0.5 rounded-md font-semibold transition-all ${
                              donorSlotFilter === 'full'
                                ? 'bg-slate-700 text-white shadow-2xs'
                                : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400'
                            }`}
                          >
                            Full {loadingData ? <span className="inline-block w-3 h-2 bg-slate-300 dark:bg-slate-700 rounded-xs animate-pulse align-middle" /> : `(${qualifyingDonors.filter(d => d.remaining_slots <= 0).length})`}
                          </button>
                        </div>

                        <span className="text-slate-400 text-[10px]">
                          {loadingData ? '···' : `${filteredQualifyingDonors.length} matching`}
                        </span>
                      </div>
                    </div>

                    {/* Donors Paginated Cards Stream */}
                    <div className="flex flex-col gap-2.5 min-h-[300px] max-h-[520px] overflow-y-auto pr-1">
                      {loadingData ? (
                        Array.from({ length: 4 }).map((_, idx) => (
                          <div
                            key={idx}
                            className="p-3.5 rounded-xl border border-slate-200/80 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/30 animate-pulse flex flex-col gap-2.5"
                          >
                            <div className="flex items-start justify-between">
                              <div className="space-y-1.5 flex-1">
                                <div className="h-4 bg-slate-200 dark:bg-slate-700 rounded w-36" />
                                <div className="h-3 bg-slate-100 dark:bg-slate-800 rounded w-48" />
                              </div>
                              <div className="h-4 bg-slate-200 dark:bg-slate-700 rounded w-16" />
                            </div>
                            <div className="pt-2 border-t border-slate-200/60 dark:border-slate-800/80 flex items-center justify-between">
                              <div className="h-4 bg-slate-200 dark:bg-slate-700 rounded w-24" />
                              <div className="h-4 bg-slate-100 dark:bg-slate-800 rounded w-20" />
                            </div>
                          </div>
                        ))
                      ) : paginatedQualifyingDonors.length === 0 ? (
                        <div className="py-12 text-center text-slate-400 text-xs">
                          {donorSearchQuery || donorSlotFilter !== 'all'
                            ? 'No donors match your search or filter criteria.'
                            : `No qualifying donors found for ${selectedDonorType}.`}
                        </div>
                      ) : (
                        paginatedQualifyingDonors.map((d) => (
                          <div
                            key={d.donor_id}
                            className="p-3.5 rounded-xl border border-slate-200/80 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/30 hover:border-blue-400/50 transition-all flex flex-col gap-2.5"
                          >
                            <div className="flex items-start justify-between">
                              <div>
                                <div className="font-bold text-slate-800 dark:text-slate-100 text-xs md:text-sm flex items-center gap-1.5 flex-wrap">
                                  <span>{d.donor_name}</span>
                                  {d.is_manual && (
                                    <span className="px-1.5 py-0.2 rounded text-[9px] font-bold bg-amber-500/15 text-amber-700 dark:text-amber-300 border border-amber-500/30 flex items-center gap-0.5">
                                      <Tag className="w-2.5 h-2.5" /> Manual Entry
                                    </span>
                                  )}
                                </div>
                                <div className="text-[11px] text-slate-400 font-mono truncate max-w-[180px]">
                                  {d.donor_email}
                                </div>
                                {d.donor_phone && (
                                  <div className="text-[11px] text-slate-500 dark:text-slate-400 flex items-center gap-1 mt-0.5 font-mono">
                                    <Phone className="w-3 h-3 text-slate-400 shrink-0" />
                                    <span>{d.donor_phone}</span>
                                  </div>
                                )}
                                {d.notes && (
                                  <div className="text-[10px] text-slate-500 dark:text-slate-400 italic mt-1 line-clamp-1" title={d.notes}>
                                    📝 {d.notes}
                                  </div>
                                )}
                              </div>

                              <div className="text-right">
                                <div className="font-black text-slate-800 dark:text-white text-xs md:text-sm">
                                  £{d.total_donated.toLocaleString()}
                                </div>
                                <span className="text-[10px] text-slate-400 uppercase font-semibold">
                                  {d.is_manual ? 'Manual Total' : 'Total Donated'}
                                </span>
                              </div>
                            </div>

                            {/* Capacity Stats & Allocation Badges */}
                            <div className="flex items-center justify-between pt-2 border-t border-slate-200/60 dark:border-slate-800/80 text-xs">
                              <div className="flex items-center gap-1.5 flex-wrap">
                                {d.allocated_count > d.max_slots ? (
                                  <span className="px-2 py-0.5 rounded-md font-bold bg-amber-50 dark:bg-amber-950/60 text-amber-600 dark:text-amber-400 border border-amber-300 dark:border-amber-800/60 text-[10px] flex items-center gap-1">
                                    <Zap className="w-2.5 h-2.5 text-amber-500 fill-amber-500" />
                                    Exceptional ({d.allocated_count}/{d.max_slots})
                                  </span>
                                ) : (
                                  <span className="px-2 py-0.5 rounded-md font-bold bg-blue-50 dark:bg-blue-950/60 text-blue-600 dark:text-blue-400 border border-blue-200/60 dark:border-blue-800/60 text-[10px]">
                                    {d.allocated_count} / {d.max_slots} Assigned
                                  </span>
                                )}

                                {d.remaining_slots > 0 ? (
                                  <span className="px-2 py-0.5 rounded-md font-bold bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 border border-emerald-200/60 dark:border-emerald-800/60 text-[10px]">
                                    {d.remaining_slots} Available Slots
                                  </span>
                                ) : (
                                  <span className="px-2 py-0.5 rounded-md font-bold bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400 text-[10px]">
                                    {d.allocated_count > d.max_slots ? 'Over Capacity' : 'Max Capacity'}
                                  </span>
                                )}
                              </div>

                              <div className="flex items-center gap-1.5">
                                {d.is_manual && (
                                  <div className="flex items-center gap-1 mr-1">
                                    <button
                                      type="button"
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        setEditingManualDonor(d);
                                        setManualDonorForm({
                                          donor_name: d.donor_name,
                                          donor_email: d.donor_email !== 'N/A' ? d.donor_email : '',
                                          donor_phone: d.donor_phone || '',
                                          sponsorship_type: d.sponsorship_type || selectedDonorType,
                                          total_donated: d.total_donated,
                                          custom_slots: d.max_slots,
                                          notes: d.notes || ''
                                        });
                                        setShowManualDonorModal(true);
                                      }}
                                      className="p-1 rounded text-slate-400 hover:text-blue-600 hover:bg-blue-50 dark:hover:bg-slate-800 transition-all"
                                      title="Edit Manual Donor"
                                    >
                                      <Edit3 className="w-3.5 h-3.5" />
                                    </button>
                                    <button
                                      type="button"
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        handleDeleteManualDonor(d);
                                      }}
                                      className="p-1 rounded text-slate-400 hover:text-red-600 hover:bg-red-50 dark:hover:bg-slate-800 transition-all"
                                      title="Delete Manual Donor"
                                    >
                                      <Trash2 className="w-3.5 h-3.5" />
                                    </button>
                                  </div>
                                )}

                                <button
                                  onClick={() => {
                                    handleSelectDonorForAllocation(d);
                                    setSelectedCampaignForAllocation(null);
                                    setAllocationMode('donor');
                                    setModalDonorSearchQuery('');
                                    setBeneficiarySearchQuery('');
                                    setBeneficiaryTypeFilter('All');
                                    setIsBeneficiaryDropdownOpen(false);
                                    const available = beneficiaries.filter(b => !b.allocation_id || b.status === 'Unallocated');
                                    if (available.length === 0) {
                                      alert(`No unallocated beneficiaries available. Please add a beneficiary in the Beneficiaries tab first.`);
                                      return;
                                    }
                                    const matching = available.find(b => b.sponsorship_type === selectedDonorType) || available[0];
                                    setIsAllocateModalOpen(true);
                                    setAllocateModalBeneficiary(null);
                                  }}
                                  title={d.remaining_slots > 0 ? 'Assign Beneficiary' : 'Exceptional Assignment: Allocate additional beneficiary beyond slot limit'}
                                  className={`px-2 py-1 rounded text-white font-bold text-[11px] transition-all flex items-center gap-1 shadow-xs shrink-0 ${
                                    d.remaining_slots > 0
                                      ? 'bg-blue-600 hover:bg-blue-700'
                                      : 'bg-amber-600 hover:bg-amber-700'
                                  }`}
                                >
                                  <Plus className="w-3 h-3" />
                                  {d.remaining_slots > 0 ? 'Assign' : 'Assign (Override)'}
                                </button>
                              </div>
                            </div>

                            {d.allocated_beneficiaries?.length > 0 && (
                              <div className="flex flex-wrap gap-1 mt-1">
                                {d.allocated_beneficiaries.map((ab, idx) => (
                                  <span
                                    key={idx}
                                    className="px-2 py-0.5 rounded text-[10px] bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 font-semibold text-slate-600 dark:text-slate-300"
                                  >
                                    👤 {ab.beneficiary_name} ({ab.project_code})
                                  </span>
                                ))}
                              </div>
                            )}
                          </div>
                        ))
                      )}
                    </div>

                    {/* Donors Pagination Footer */}
                    {!loadingData && filteredQualifyingDonors.length > 0 && (
                      <div className="pt-3 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between text-xs text-slate-500 flex-wrap gap-2">
                        <div className="flex items-center gap-2">
                          <span className="text-[11px]">
                            Showing <strong className="text-slate-700 dark:text-slate-300">{(donorPage - 1) * donorPageSize + 1}</strong> to <strong className="text-slate-700 dark:text-slate-300">{Math.min(donorPage * donorPageSize, filteredQualifyingDonors.length)}</strong> of <strong className="text-slate-700 dark:text-slate-300">{filteredQualifyingDonors.length}</strong>
                          </span>
                          <select
                            value={donorPageSize}
                            onChange={(e) => {
                              setDonorPageSize(Number(e.target.value));
                              setDonorPage(1);
                            }}
                            className="px-1.5 py-0.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded text-[11px] font-semibold"
                          >
                            <option value={10}>10 / page</option>
                            <option value={25}>25 / page</option>
                            <option value={50}>50 / page</option>
                          </select>
                        </div>

                        <div className="flex items-center gap-1">
                          <button
                            disabled={donorPage <= 1}
                            onClick={() => setDonorPage(1)}
                            className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-30"
                            title="First page"
                          >
                            <ChevronsLeft className="w-3.5 h-3.5" />
                          </button>
                          <button
                            disabled={donorPage <= 1}
                            onClick={() => setDonorPage(prev => Math.max(1, prev - 1))}
                            className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-30"
                            title="Previous page"
                          >
                            <ChevronLeft className="w-3.5 h-3.5" />
                          </button>

                          <span className="px-2 py-0.5 font-bold text-[11px] bg-slate-100 dark:bg-slate-800 rounded">
                            {donorPage} / {totalDonorPages}
                          </span>

                          <button
                            disabled={donorPage >= totalDonorPages}
                            onClick={() => setDonorPage(prev => Math.min(totalDonorPages, prev + 1))}
                            className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-30"
                            title="Next page"
                          >
                            <ChevronRight className="w-3.5 h-3.5" />
                          </button>
                          <button
                            disabled={donorPage >= totalDonorPages}
                            onClick={() => setDonorPage(totalDonorPages)}
                            className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-30"
                            title="Last page"
                          >
                            <ChevronsRight className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* Left Tab 2: Campaigns List with Search & Pagination */}
                {allocationLeftTab === 'campaigns' && (
                  <div className="flex flex-col gap-3">
                    {/* Search & Slot Filter Bar */}
                    <div className="flex flex-col gap-2">
                      <div className="relative">
                        <Search className="w-3.5 h-3.5 absolute left-3 top-2.5 text-slate-400" />
                        <input
                          type="text"
                          placeholder="Search campaigns, community, or email..."
                          value={campaignListSearchQuery}
                          onChange={(e) => setCampaignListSearchQuery(e.target.value)}
                          className="w-full pl-8 pr-8 py-1.5 bg-slate-50 dark:bg-slate-800/80 border border-slate-200 dark:border-slate-700 rounded-lg text-xs"
                        />
                        {campaignListSearchQuery && (
                          <button
                            onClick={() => setCampaignListSearchQuery('')}
                            className="absolute right-2.5 top-2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
                          >
                            <X className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </div>

                      {/* Filter Chips */}
                      <div className="flex items-center justify-between text-[11px] gap-1 flex-wrap">
                        <div className="flex items-center gap-1">
                          <button
                            onClick={() => setCampaignSlotFilter('all')}
                            className={`px-2 py-0.5 rounded-md font-semibold transition-all ${
                              campaignSlotFilter === 'all'
                                ? 'bg-purple-600 text-white shadow-2xs'
                                : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400'
                            }`}
                          >
                            All {loadingData ? <span className="inline-block w-3 h-2 bg-slate-300 dark:bg-slate-700 rounded-xs animate-pulse align-middle" /> : `(${qualifyingCampaigns.length})`}
                          </button>
                          <button
                            onClick={() => setCampaignSlotFilter('available')}
                            className={`px-2 py-0.5 rounded-md font-semibold transition-all ${
                              campaignSlotFilter === 'available'
                                ? 'bg-emerald-600 text-white shadow-2xs'
                                : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400'
                            }`}
                          >
                            Available {loadingData ? <span className="inline-block w-3 h-2 bg-slate-300 dark:bg-slate-700 rounded-xs animate-pulse align-middle" /> : `(${qualifyingCampaigns.filter(c => c.remaining_slots > 0).length})`}
                          </button>
                          <button
                            onClick={() => setCampaignSlotFilter('full')}
                            className={`px-2 py-0.5 rounded-md font-semibold transition-all ${
                              campaignSlotFilter === 'full'
                                ? 'bg-slate-700 text-white shadow-2xs'
                                : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400'
                            }`}
                          >
                            Full {loadingData ? <span className="inline-block w-3 h-2 bg-slate-300 dark:bg-slate-700 rounded-xs animate-pulse align-middle" /> : `(${qualifyingCampaigns.filter(c => c.remaining_slots <= 0).length})`}
                          </button>
                        </div>

                        <span className="text-slate-400 text-[10px]">
                          {loadingData ? '···' : `${filteredQualifyingCampaigns.length} matching`}
                        </span>
                      </div>
                    </div>

                    {/* Campaigns Paginated Cards Stream */}
                    <div className="flex flex-col gap-2.5 min-h-[300px] max-h-[520px] overflow-y-auto pr-1">
                      {loadingData ? (
                        Array.from({ length: 4 }).map((_, idx) => (
                          <div
                            key={idx}
                            className="p-3.5 rounded-xl border border-slate-200/80 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/30 animate-pulse flex flex-col gap-2.5"
                          >
                            <div className="flex items-start justify-between">
                              <div className="space-y-1.5 flex-1">
                                <div className="h-4 bg-slate-200 dark:bg-slate-700 rounded w-40" />
                                <div className="h-3 bg-slate-100 dark:bg-slate-800 rounded w-28" />
                              </div>
                              <div className="h-4 bg-slate-200 dark:bg-slate-700 rounded w-16" />
                            </div>
                            <div className="pt-2 border-t border-slate-200/60 dark:border-slate-800/80 flex items-center justify-between">
                              <div className="h-4 bg-slate-200 dark:bg-slate-700 rounded w-24" />
                              <div className="h-4 bg-slate-100 dark:bg-slate-800 rounded w-20" />
                            </div>
                          </div>
                        ))
                      ) : paginatedQualifyingCampaigns.length === 0 ? (
                        <div className="py-12 text-center text-slate-400 text-xs">
                          {campaignListSearchQuery || campaignSlotFilter !== 'all'
                            ? 'No campaigns match your search or filter criteria.'
                            : `No qualifying campaigns found for ${selectedDonorType}.`}
                        </div>
                      ) : (
                        paginatedQualifyingCampaigns.map((c, idx) => (
                          <div
                            key={idx}
                            className="p-3.5 rounded-xl border border-slate-200/80 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/30 hover:border-purple-400/50 transition-all flex flex-col gap-2.5"
                          >
                            <div className="flex items-start justify-between gap-2">
                              <div>
                                <div className="font-bold text-slate-800 dark:text-slate-100 text-xs md:text-sm flex items-center gap-1.5 flex-wrap">
                                  🏷️ {c.campaign_name}
                                </div>
                                {c.community_name && (
                                  <span className="inline-block mt-1 px-1.5 py-0.5 rounded bg-purple-50 dark:bg-purple-950/60 text-purple-600 dark:text-purple-400 text-[10px] font-semibold border border-purple-200/60 dark:border-purple-800/60">
                                    🏛️ {c.community_name}
                                  </span>
                                )}
                                {c.organizer_email && (
                                  <div className="text-[11px] text-slate-400 font-mono truncate max-w-[200px] mt-0.5">
                                    ✉️ {c.organizer_email}
                                  </div>
                                )}
                              </div>

                              <div className="text-right shrink-0">
                                <div className="font-black text-slate-800 dark:text-white text-xs md:text-sm">
                                  £{c.total_raised.toLocaleString()}
                                </div>
                                <span className="text-[10px] text-slate-400 uppercase font-semibold">Total Raised</span>
                              </div>
                            </div>

                            {/* Capacity Stats & Allocation Badges */}
                            <div className="flex items-center justify-between pt-2 border-t border-slate-200/60 dark:border-slate-800/80 text-xs">
                              <div className="flex items-center gap-1.5 flex-wrap">
                                <span className="px-2 py-0.5 rounded-md font-bold bg-purple-50 dark:bg-purple-950/60 text-purple-600 dark:text-purple-400 border border-purple-200/60 dark:border-purple-800/60 text-[10px]">
                                  {c.allocated_count} / {c.max_slots} Assigned
                                </span>

                                {c.remaining_slots > 0 ? (
                                  <span className="px-2 py-0.5 rounded-md font-bold bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 border border-emerald-200/60 dark:border-emerald-800/60 text-[10px]">
                                    {c.remaining_slots} Slots Available
                                  </span>
                                ) : c.max_slots > 0 ? (
                                  <span className="px-2 py-0.5 rounded-md font-bold bg-slate-100 dark:bg-slate-800 text-slate-400 text-[10px]">
                                    Max Capacity
                                  </span>
                                ) : (
                                  <span className="px-2 py-0.5 rounded-md font-bold bg-slate-100 dark:bg-slate-800 text-slate-400 text-[10px]">
                                    Custom Direct
                                  </span>
                                )}
                              </div>

                              <button
                                onClick={() => {
                                  setSelectedCampaignForAllocation(c);
                                  setAllocationMode('campaign');
                                  setIsCustomCampaign(false);
                                  setCampaignContactEmail(c.organizer_email || '');
                                  setCampaignContactName(c.organizer_name || '');
                                  const available = beneficiaries.filter(b => !b.allocation_id || b.status === 'Unallocated');
                                  if (available.length === 0) {
                                    alert(`No unallocated beneficiaries available. Please add a beneficiary in the Beneficiaries tab first.`);
                                    return;
                                  }
                                  const matching = available.find(b => b.sponsorship_type === selectedDonorType) || available[0];
                                  setIsAllocateModalOpen(true);
                                  setAllocateModalBeneficiary(null);
                                }}
                                className="px-2 py-1 rounded bg-purple-600 hover:bg-purple-700 text-white font-bold text-[11px] transition-all flex items-center gap-1"
                              >
                                <Plus className="w-3 h-3" />
                                Assign
                              </button>
                            </div>

                            {c.allocated_beneficiaries?.length > 0 && (
                              <div className="flex flex-wrap gap-1 mt-1">
                                {c.allocated_beneficiaries.map((ab, idx) => (
                                  <span
                                    key={idx}
                                    className="px-2 py-0.5 rounded text-[10px] bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 font-semibold text-slate-600 dark:text-slate-300"
                                  >
                                    👤 {ab.beneficiary_name} ({ab.project_code})
                                  </span>
                                ))}
                              </div>
                            )}
                          </div>
                        ))
                      )}
                    </div>

                    {/* Campaigns Pagination Footer */}
                    {!loadingData && filteredQualifyingCampaigns.length > 0 && (
                      <div className="pt-3 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between text-xs text-slate-500 flex-wrap gap-2">
                        <div className="flex items-center gap-2">
                          <span className="text-[11px]">
                            Showing <strong className="text-slate-700 dark:text-slate-300">{(campaignPage - 1) * campaignPageSize + 1}</strong> to <strong className="text-slate-700 dark:text-slate-300">{Math.min(campaignPage * campaignPageSize, filteredQualifyingCampaigns.length)}</strong> of <strong className="text-slate-700 dark:text-slate-300">{filteredQualifyingCampaigns.length}</strong>
                          </span>
                          <select
                            value={campaignPageSize}
                            onChange={(e) => {
                              setCampaignPageSize(Number(e.target.value));
                              setCampaignPage(1);
                            }}
                            className="px-1.5 py-0.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded text-[11px] font-semibold"
                          >
                            <option value={10}>10 / page</option>
                            <option value={25}>25 / page</option>
                            <option value={50}>50 / page</option>
                            <option value={100}>100 / page</option>
                          </select>
                        </div>

                        <div className="flex items-center gap-1">
                          <button
                            disabled={campaignPage <= 1}
                            onClick={() => setCampaignPage(1)}
                            className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-30"
                            title="First page"
                          >
                            <ChevronsLeft className="w-3.5 h-3.5" />
                          </button>
                          <button
                            disabled={campaignPage <= 1}
                            onClick={() => setCampaignPage(prev => Math.max(1, prev - 1))}
                            className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-30"
                            title="Previous page"
                          >
                            <ChevronLeft className="w-3.5 h-3.5" />
                          </button>

                          <span className="px-2 py-0.5 font-bold text-[11px] bg-slate-100 dark:bg-slate-800 rounded">
                            {campaignPage} / {totalCampaignPages}
                          </span>

                          <button
                            disabled={campaignPage >= totalCampaignPages}
                            onClick={() => setCampaignPage(prev => Math.min(totalCampaignPages, prev + 1))}
                            className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-30"
                            title="Next page"
                          >
                            <ChevronRight className="w-3.5 h-3.5" />
                          </button>
                          <button
                            disabled={campaignPage >= totalCampaignPages}
                            onClick={() => setCampaignPage(totalCampaignPages)}
                            className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-30"
                            title="Last page"
                          >
                            <ChevronsRight className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* Left Tab 3: ALL CRM DONORS (OTHER CAUSES) */}
                {allocationLeftTab === 'all_crm' && (
                  <div className="flex flex-col gap-3">
                    {/* Search Bar */}
                    <div className="flex flex-col gap-2">
                      <div className="relative">
                        <Search className="w-3.5 h-3.5 absolute left-3 top-2.5 text-amber-500" />
                        <input
                          type="text"
                          placeholder="Search across entire CRM (name, email, phone, ID)..."
                          value={leftAllCrmSearchQuery}
                          onChange={(e) => setLeftAllCrmSearchQuery(e.target.value)}
                          className="w-full pl-8 pr-8 py-1.5 bg-slate-50 dark:bg-slate-800/80 border border-amber-200 dark:border-amber-800/80 rounded-lg text-xs focus:ring-1 focus:ring-amber-500 focus:outline-none"
                        />
                        {leftAllCrmSearchQuery && (
                          <button
                            onClick={() => setLeftAllCrmSearchQuery('')}
                            className="absolute right-2.5 top-2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
                          >
                            <X className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </div>

                      <div className="flex items-center justify-between text-[11px] text-slate-500 px-1">
                        <span className="flex items-center gap-1 font-semibold text-amber-600 dark:text-amber-400">
                          <Zap className="w-3 h-3 text-amber-500 fill-amber-500" />
                          Universal CRM Override Directory
                        </span>
                        <span>
                          {leftAllCrmDonors.length > 0 ? `${leftAllCrmDonors.length} found` : '105k+ records'}
                        </span>
                      </div>
                    </div>

                    {/* Donors Cards List */}
                    <div className="flex flex-col gap-2.5 max-h-[650px] overflow-y-auto pr-1">
                      {isSearchingLeftAllCrm ? (
                        <div className="p-8 text-center flex flex-col items-center justify-center gap-2 text-slate-500 text-xs">
                          <RefreshCw className="w-5 h-5 animate-spin text-amber-500" />
                          <span>Searching all CRM records across causes...</span>
                        </div>
                      ) : leftAllCrmDonors.length === 0 ? (
                        <div className="p-6 text-center flex flex-col items-center justify-center gap-2 border border-dashed border-slate-200 dark:border-slate-800 rounded-xl bg-slate-50/50 dark:bg-slate-900/30 text-xs text-slate-500">
                          <div className="p-3 rounded-full bg-amber-50 dark:bg-amber-950/60 text-amber-600 dark:text-amber-400">
                            <Zap className="w-5 h-5 fill-amber-500/20" />
                          </div>
                          {leftAllCrmSearchQuery ? (
                            <span>No CRM donors found matching "{leftAllCrmSearchQuery}".</span>
                          ) : (
                            <div className="flex flex-col gap-1 max-w-xs">
                              <span className="font-bold text-slate-700 dark:text-slate-200">
                                Exceptional Override Search
                              </span>
                              <span className="text-[11px] text-slate-400">
                                Search by name, email, phone, or ID to find any donor in the CRM — including those who donated to Masjids, Emergency Relief, Education, or General — and assign them a beneficiary.
                              </span>
                            </div>
                          )}
                        </div>
                      ) : (
                        leftAllCrmDonors.map((d) => {
                          const isOverride = d.remaining_slots <= 0;
                          return (
                            <div
                              key={d.donor_id}
                              className="p-3 rounded-xl border border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 hover:border-amber-300 dark:hover:border-amber-700/60 transition-all flex flex-col gap-2 shadow-xs"
                            >
                              {/* Top Row: Name + LTV Amount */}
                              <div className="flex items-start justify-between gap-2">
                                <div>
                                  <div className="font-bold text-slate-800 dark:text-slate-100 text-xs flex items-center gap-1.5 flex-wrap">
                                    {d.donor_name}
                                    {isOverride && (
                                      <span className="px-1.5 py-0.2 rounded text-[9px] font-bold bg-amber-50 dark:bg-amber-950/60 text-amber-600 dark:text-amber-400 border border-amber-300 dark:border-amber-800 flex items-center gap-1">
                                        <Zap className="w-2.5 h-2.5 fill-amber-500 text-amber-500" /> Override
                                      </span>
                                    )}
                                  </div>
                                  <span className="text-[11px] font-mono text-slate-400 block truncate max-w-[220px]">
                                    {d.donor_email || 'No email in data'}
                                  </span>
                                  {d.donor_phone && (
                                    <span className="text-[10px] font-mono text-slate-500 dark:text-slate-400 flex items-center gap-1 mt-0.5">
                                      <Phone className="w-3 h-3 text-slate-400 shrink-0" />
                                      {d.donor_phone}
                                    </span>
                                  )}
                                </div>

                                <div className="text-right shrink-0">
                                  <div className="font-black text-slate-800 dark:text-white text-xs">
                                    £{Number(d.total_lifetime_donated || 0).toLocaleString()}
                                  </div>
                                  <span className="text-[9px] text-purple-600 dark:text-purple-400 uppercase font-bold tracking-wider">
                                    CRM LTV
                                  </span>
                                </div>
                              </div>

                              {/* Causes badges */}
                              {d.causes && d.causes.length > 0 && (
                                <div className="flex flex-wrap gap-1">
                                  {d.causes.map((c, idx) => (
                                    <span
                                      key={idx}
                                      className="px-1.5 py-0.2 bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 rounded text-[9px] font-medium border border-slate-200 dark:border-slate-700"
                                    >
                                      {c}
                                    </span>
                                  ))}
                                </div>
                              )}

                              {/* Capacity Stats & Allocation Badges */}
                              <div className="flex items-center justify-between pt-2 border-t border-slate-200/60 dark:border-slate-800/80 text-xs">
                                <div className="flex items-center gap-1.5 flex-wrap">
                                  <span className="px-2 py-0.5 rounded-md font-bold bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 text-[10px]">
                                    {selectedDonorType}: £{Number(d.total_donated || 0).toLocaleString()}
                                  </span>
                                  {d.remaining_slots > 0 ? (
                                    <span className="px-2 py-0.5 rounded-md font-bold bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 text-[10px]">
                                      {d.remaining_slots} Slots Available
                                    </span>
                                  ) : (
                                    <span className="px-2 py-0.5 rounded-md font-bold bg-amber-50 dark:bg-amber-950/60 text-amber-600 dark:text-amber-400 border border-amber-300 dark:border-amber-800 text-[10px]">
                                      {d.allocated_count > d.max_slots ? `Exceptional (${d.allocated_count}/${d.max_slots})` : `Override Candidate (${d.allocated_count}/${d.max_slots})`}
                                    </span>
                                  )}
                                </div>

                                <button
                                  onClick={() => {
                                    handleSelectDonorForAllocation(d);
                                    setSelectedCampaignForAllocation(null);
                                    setAllocationMode('donor');
                                    setModalDonorSearchQuery('');
                                    setBeneficiarySearchQuery('');
                                    setBeneficiaryTypeFilter('All');
                                    setIsBeneficiaryDropdownOpen(false);
                                    const available = beneficiaries.filter(b => !b.allocation_id || b.status === 'Unallocated');
                                    if (available.length === 0) {
                                      alert(`No unallocated beneficiaries available. Please add a beneficiary in the Beneficiaries tab first.`);
                                      return;
                                    }
                                    const matching = available.find(b => b.sponsorship_type === selectedDonorType) || available[0];
                                    setIsAllocateModalOpen(true);
                                    setAllocateModalBeneficiary(null);
                                  }}
                                  title="Assign beneficiary to this donor via exceptional override"
                                  className={`px-2 py-1 rounded text-white font-bold text-[11px] transition-all flex items-center gap-1 shadow-xs shrink-0 ${
                                    d.remaining_slots > 0
                                      ? 'bg-blue-600 hover:bg-blue-700'
                                      : 'bg-amber-600 hover:bg-amber-700'
                                  }`}
                                >
                                  <Plus className="w-3 h-3" />
                                  {d.remaining_slots > 0 ? 'Assign' : 'Assign (Override)'}
                                </button>
                              </div>

                              {d.allocated_beneficiaries?.length > 0 && (
                                <div className="flex flex-wrap gap-1 mt-1">
                                  {d.allocated_beneficiaries.map((ab, idx) => (
                                    <span
                                      key={idx}
                                      className="px-2 py-0.5 rounded text-[10px] bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 font-semibold text-slate-600 dark:text-slate-300"
                                    >
                                      👤 {ab.beneficiary_name} ({ab.project_code})
                                    </span>
                                  ))}
                                </div>
                              )}
                            </div>
                          );
                        })
                      )}
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Right Column: Active Allocations */}
            <div className="lg:col-span-7 flex flex-col gap-4">
              <div className="bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-200/80 dark:border-slate-800 shadow-sm">
                <div className="flex flex-col gap-3 pb-3 border-b border-slate-100 dark:border-slate-800">
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                    <div className="flex items-center gap-2">
                      <h3 className="font-bold text-slate-800 dark:text-slate-100 text-sm flex items-center gap-2">
                        <Layers className="w-4 h-4 text-blue-500" />
                        Active Allocations {loadingData ? <span className="inline-block w-4 h-2.5 bg-slate-300/80 dark:bg-slate-700 rounded-xs animate-pulse align-middle ml-0.5" /> : `(${allocations.length})`}
                      </h3>
                    </div>

                    {/* Type Filter Pills */}
                    <div className="flex items-center gap-1 p-1 bg-slate-100 dark:bg-slate-800 rounded-lg text-xs">
                      <button
                        onClick={() => setAllocationTypeFilter('all')}
                        className={`px-2.5 py-1 rounded-md font-semibold transition-all ${
                          allocationTypeFilter === 'all'
                            ? 'bg-white dark:bg-slate-900 text-slate-900 dark:text-white shadow-xs font-bold'
                            : 'text-slate-500 hover:text-slate-800'
                        }`}
                      >
                        All {loadingData ? <span className="inline-block w-3 h-2 bg-slate-300 dark:bg-slate-700 rounded-xs animate-pulse align-middle" /> : `(${allocations.length})`}
                      </button>
                      <button
                        onClick={() => setAllocationTypeFilter('individual')}
                        className={`px-2.5 py-1 rounded-md font-semibold transition-all ${
                          allocationTypeFilter === 'individual'
                            ? 'bg-white dark:bg-slate-900 text-blue-600 dark:text-blue-400 shadow-xs font-bold'
                            : 'text-slate-500 hover:text-slate-800'
                        }`}
                      >
                        👤 Donors {loadingData ? <span className="inline-block w-3 h-2 bg-slate-300 dark:bg-slate-700 rounded-xs animate-pulse align-middle" /> : `(${allocations.filter(a => a.allocation_type !== 'campaign').length})`}
                      </button>
                      <button
                        onClick={() => setAllocationTypeFilter('campaign')}
                        className={`px-2.5 py-1 rounded-md font-semibold transition-all ${
                          allocationTypeFilter === 'campaign'
                            ? 'bg-white dark:bg-slate-900 text-purple-600 dark:text-purple-400 shadow-xs font-bold'
                            : 'text-slate-500 hover:text-slate-800'
                        }`}
                      >
                        🏷️ Campaigns {loadingData ? <span className="inline-block w-3 h-2 bg-slate-300 dark:bg-slate-700 rounded-xs animate-pulse align-middle" /> : `(${allocations.filter(a => a.allocation_type === 'campaign').length})`}
                      </button>
                    </div>
                  </div>

                  {/* Renewal Lifecycle Filter Pills */}
                  <div className="flex items-center gap-1 flex-wrap text-xs pt-1">
                    <span className="text-[11px] font-bold text-slate-400 uppercase mr-1">Lifecycle:</span>
                    <button
                      onClick={() => setAllocationRenewalFilter('all')}
                      className={`px-2 py-0.5 rounded-md font-bold text-[11px] transition-all ${
                        allocationRenewalFilter === 'all'
                          ? 'bg-slate-800 text-white dark:bg-slate-200 dark:text-slate-900 shadow-xs'
                          : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200'
                      }`}
                    >
                      All Cycles
                    </button>
                    <button
                      onClick={() => setAllocationRenewalFilter('active')}
                      className={`px-2 py-0.5 rounded-md font-bold text-[11px] transition-all flex items-center gap-1 ${
                        allocationRenewalFilter === 'active'
                          ? 'bg-emerald-600 text-white shadow-xs'
                          : 'bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 border border-emerald-200/60 dark:border-emerald-800/60'
                      }`}
                    >
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                      Active {loadingData ? <span className="inline-block w-3 h-2 bg-slate-300 dark:bg-slate-700 rounded-xs animate-pulse align-middle" /> : `(${allocations.filter(a => a.cycle_status === 'active').length})`}
                    </button>
                    <button
                      onClick={() => setAllocationRenewalFilter('due')}
                      className={`px-2 py-0.5 rounded-md font-bold text-[11px] transition-all flex items-center gap-1 ${
                        allocationRenewalFilter === 'due'
                          ? 'bg-amber-600 text-white shadow-xs'
                          : 'bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-300 border border-amber-200/60 dark:border-amber-800/60'
                      }`}
                    >
                      <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                      Due (30d) {loadingData ? <span className="inline-block w-3 h-2 bg-slate-300 dark:bg-slate-700 rounded-xs animate-pulse align-middle" /> : `(${allocations.filter(a => a.cycle_status === 'due').length})`}
                    </button>
                    <button
                      onClick={() => setAllocationRenewalFilter('grace')}
                      className={`px-2 py-0.5 rounded-md font-bold text-[11px] transition-all flex items-center gap-1 ${
                        allocationRenewalFilter === 'grace'
                          ? 'bg-orange-600 text-white shadow-xs'
                          : 'bg-orange-50 dark:bg-orange-950/40 text-orange-700 dark:text-orange-300 border border-orange-200/60 dark:border-orange-800/60'
                      }`}
                    >
                      <span className="w-1.5 h-1.5 rounded-full bg-orange-400" />
                      Grace (30d) {loadingData ? <span className="inline-block w-3 h-2 bg-slate-300 dark:bg-slate-700 rounded-xs animate-pulse align-middle" /> : `(${allocations.filter(a => a.cycle_status === 'grace').length})`}
                    </button>
                    <button
                      onClick={() => setAllocationRenewalFilter('lapsed')}
                      className={`px-2 py-0.5 rounded-md font-bold text-[11px] transition-all flex items-center gap-1 ${
                        allocationRenewalFilter === 'lapsed'
                          ? 'bg-rose-600 text-white shadow-xs'
                          : 'bg-rose-50 dark:bg-rose-950/40 text-rose-700 dark:text-rose-300 border border-rose-200/60 dark:border-rose-800/60'
                      }`}
                    >
                      <span className="w-1.5 h-1.5 rounded-full bg-rose-400" />
                      Lapsed {loadingData ? <span className="inline-block w-3 h-2 bg-slate-300 dark:bg-slate-700 rounded-xs animate-pulse align-middle" /> : `(${allocations.filter(a => a.cycle_status === 'lapsed').length})`}
                    </button>
                  </div>
                </div>

                <div className="flex flex-col gap-3 mt-3 max-h-[620px] overflow-y-auto pr-1">
                  {loadingData ? (
                    Array.from({ length: 4 }).map((_, idx) => (
                      <div
                        key={idx}
                        className="p-4 rounded-xl border border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 animate-pulse flex flex-col gap-3 shadow-xs"
                      >
                        <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-2">
                          <div className="space-y-2 flex-1">
                            <div className="h-4 bg-slate-200 dark:bg-slate-800 rounded w-48" />
                            <div className="h-3 bg-slate-100 dark:bg-slate-800/70 rounded w-56" />
                            <div className="h-3 bg-slate-100 dark:bg-slate-800/70 rounded w-36" />
                          </div>
                          <div className="h-6 bg-slate-200 dark:bg-slate-800 rounded-full w-28" />
                        </div>
                        <div className="pt-2 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between">
                          <div className="h-6 bg-slate-200 dark:bg-slate-800 rounded w-36" />
                          <div className="h-6 bg-slate-100 dark:bg-slate-800 rounded w-16" />
                        </div>
                      </div>
                    ))
                  ) : filteredAllocations.length === 0 ? (
                    <div className="py-12 text-center text-slate-400 text-xs">
                      No matching allocations found for selected filters.
                    </div>
                  ) : (
                    paginatedAllocations.map((a) => (
                      <div
                        key={a.id}
                        className={`p-4 rounded-xl border transition-all flex flex-col gap-3 shadow-xs ${
                          a.cycle_status === 'due'
                            ? 'border-amber-300 dark:border-amber-700 bg-amber-50/20 dark:bg-amber-950/10'
                            : a.cycle_status === 'grace'
                            ? 'border-orange-300 dark:border-orange-700 bg-orange-50/20 dark:bg-orange-950/10'
                            : a.cycle_status === 'lapsed'
                            ? 'border-rose-300 dark:border-rose-700 bg-rose-50/20 dark:bg-rose-950/10'
                            : 'border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 hover:border-blue-400/50'
                        }`}
                      >
                        <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-2">
                          <div className="flex-1">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="font-bold text-slate-800 dark:text-slate-100 text-sm">
                                {a.beneficiary_name}
                              </span>
                              <span className="font-mono text-[11px] px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 font-bold">
                                {a.project_code}
                              </span>
                              <span className="text-xs px-2 py-0.5 rounded-full font-bold bg-blue-50 dark:bg-blue-950/60 text-blue-600 dark:text-blue-400">
                                {a.sponsorship_type}
                              </span>
                              {a.allocation_type === 'campaign' ? (
                                <span className="text-xs px-2 py-0.5 rounded-full font-bold bg-purple-50 dark:bg-purple-950/60 text-purple-600 dark:text-purple-400 border border-purple-200/60 dark:border-purple-800/60">
                                  🏷️ Campaign Allocation
                                </span>
                              ) : (
                                <span className="text-xs px-2 py-0.5 rounded-full font-bold bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300">
                                  👤 Individual Donor
                                </span>
                              )}
                            </div>

                            <div className="text-xs text-slate-600 dark:text-slate-300 mt-1.5 flex flex-col gap-0.5">
                              {(() => {
                                const hasEmail = Boolean(a.donor_email && a.donor_email.trim() && a.donor_email.toLowerCase() !== 'n/a');
                                const hasPhone = Boolean(a.donor_phone && a.donor_phone.trim() && a.donor_phone.toLowerCase() !== 'n/a');

                                return a.allocation_type === 'campaign' ? (
                                  <>
                                    <div className="font-bold text-purple-700 dark:text-purple-300">
                                      🏷️ Campaign: {a.campaign_name || a.donor_name}
                                    </div>
                                    {a.community_name && (
                                      <div className="text-slate-500 dark:text-slate-400">
                                        🏛️ Community: <strong>{a.community_name}</strong>
                                      </div>
                                    )}
                                    <div className="text-slate-500 dark:text-slate-400 flex items-center gap-1.5 flex-wrap">
                                      <span>✉️ Contacts:</span>
                                      {hasEmail ? (
                                        <span className="font-mono text-slate-700 dark:text-slate-200 font-semibold">{a.donor_email}</span>
                                      ) : (
                                        <span className="text-amber-600 dark:text-amber-400 italic text-[11px]">No email provided</span>
                                      )}
                                      {hasPhone && (
                                        <span className="font-mono text-slate-600 dark:text-slate-300 ml-1">📞 {a.donor_phone}</span>
                                      )}
                                      <button
                                        onClick={() => openEditContactModal(a)}
                                        className="text-blue-600 hover:text-blue-700 dark:text-blue-400 font-bold text-[11px] underline ml-1 cursor-pointer"
                                      >
                                        {hasEmail ? 'Edit' : '+ Add Email'}
                                      </button>
                                    </div>
                                  </>
                                ) : (
                                  <div className="flex items-center gap-1.5 flex-wrap">
                                    <span>
                                      Assigned Donor: <strong className="text-slate-800 dark:text-slate-200">{a.donor_name}</strong>
                                      {hasEmail ? (
                                        <span className="font-mono ml-1">({a.donor_email})</span>
                                      ) : (
                                        <span className="text-amber-600 dark:text-amber-400 italic text-[11px] ml-1">(No email)</span>
                                      )}
                                      {hasPhone && (
                                        <span className="font-mono text-slate-600 dark:text-slate-300 ml-1">📞 {a.donor_phone}</span>
                                      )}
                                    </span>
                                    <button
                                      onClick={() => openEditContactModal(a)}
                                      className="text-blue-600 hover:text-blue-700 dark:text-blue-400 font-bold text-[11px] underline ml-1 cursor-pointer"
                                    >
                                      {hasEmail ? 'Edit' : '+ Add Email'}
                                    </button>
                                  </div>
                                );
                              })()}

                              {/* Sponsorship Cycle Dates & Renewal Indicator */}
                              <div className="flex items-center gap-2 mt-1 text-[11px] text-slate-500 dark:text-slate-400 flex-wrap">
                                <span>📅 Cycle: <strong>{a.start_date || 'N/A'}</strong> → <strong>{a.end_date || 'N/A'}</strong></span>
                                {a.renewal_count > 0 && (
                                  <span className="px-1.5 py-0.2 rounded bg-indigo-50 dark:bg-indigo-950/60 text-indigo-600 dark:text-indigo-400 font-bold border border-indigo-200 dark:border-indigo-800">
                                    Renewed {a.renewal_count}x
                                  </span>
                                )}
                              </div>
                            </div>
                          </div>

                          <div className="flex flex-col sm:flex-row items-start sm:items-center gap-2 shrink-0">
                            {/* Renewal Status Badge */}
                            <div 
                              className={`px-2.5 py-1 rounded-full text-xs font-bold border flex items-center gap-1.5 shadow-2xs ${
                                a.cycle_status === 'due'
                                  ? 'bg-amber-100 dark:bg-amber-950/80 text-amber-800 dark:text-amber-200 border-amber-300 dark:border-amber-700 animate-pulse'
                                  : a.cycle_status === 'grace'
                                  ? 'bg-orange-100 dark:bg-orange-950/80 text-orange-800 dark:text-orange-200 border-orange-300 dark:border-orange-700'
                                  : a.cycle_status === 'lapsed'
                                  ? 'bg-rose-100 dark:bg-rose-950/80 text-rose-800 dark:text-rose-200 border-rose-300 dark:border-rose-700'
                                  : a.cycle_status === 'renewed'
                                  ? 'bg-purple-50 dark:bg-purple-950/80 text-purple-700 dark:text-purple-300 border-purple-300 dark:border-purple-700'
                                  : 'bg-emerald-50 dark:bg-emerald-950/80 text-emerald-700 dark:text-emerald-300 border-emerald-300 dark:border-emerald-700'
                              }`}
                            >
                              {a.cycle_status === 'due' ? (
                                <>
                                  <AlertCircle className="w-3.5 h-3.5 text-amber-600 dark:text-amber-400" />
                                  <span>Due for Renewal ({a.days_remaining}d left)</span>
                                </>
                              ) : a.cycle_status === 'grace' ? (
                                <>
                                  <Clock className="w-3.5 h-3.5 text-orange-600 dark:text-orange-400" />
                                  <span>Grace Period ({Math.abs(a.days_remaining)}d past)</span>
                                </>
                              ) : a.cycle_status === 'lapsed' ? (
                                <>
                                  <ShieldAlert className="w-3.5 h-3.5 text-rose-600 dark:text-rose-400" />
                                  <span>Lapsed ({Math.abs(a.days_remaining)}d overdue)</span>
                                </>
                              ) : (
                                <>
                                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" />
                                  <span>Active · Year {a.sponsorship_year || 1} ({a.days_remaining || 0}d left)</span>
                                </>
                              )}
                            </div>

                            {/* Email Delivery & Open Tracking Pill */}
                            {a.latest_email_status && (
                              <div 
                                title={
                                  a.latest_email_status === 'opened'
                                    ? `Email was opened ${a.latest_email_open_count || 1} time(s). First opened on ${new Date(a.latest_email_opened_at).toLocaleString()}`
                                    : a.latest_email_status === 'replied'
                                    ? `Donor replied to this email thread.`
                                    : `Email successfully delivered to inbox via Microsoft 365.`
                                }
                                className={`px-2.5 py-1 rounded-full text-xs font-bold border flex items-center gap-1.5 transition-all shadow-xs ${
                                  a.latest_email_status === 'opened'
                                    ? 'bg-emerald-50 dark:bg-emerald-950/70 text-emerald-700 dark:text-emerald-300 border-emerald-300 dark:border-emerald-700'
                                    : a.latest_email_status === 'replied'
                                    ? 'bg-cyan-50 dark:bg-cyan-950/70 text-cyan-700 dark:text-cyan-300 border-cyan-300 dark:border-cyan-700'
                                    : 'bg-blue-50 dark:bg-blue-950/70 text-blue-700 dark:text-blue-300 border-blue-200 dark:border-blue-800'
                                }`}
                              >
                                {a.latest_email_status === 'opened' ? (
                                  <>
                                    <Eye className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" />
                                    <span>
                                      Opened {a.latest_email_open_count > 1 ? `(${a.latest_email_open_count}x)` : ''}
                                    </span>
                                  </>
                                ) : a.latest_email_status === 'replied' ? (
                                  <>
                                    <MessageSquare className="w-3.5 h-3.5 text-cyan-600 dark:text-cyan-400" />
                                    <span>Donor Replied</span>
                                  </>
                                ) : (
                                  <>
                                    <Check className="w-3.5 h-3.5 text-blue-600 dark:text-blue-400" />
                                    <span>Delivered</span>
                                  </>
                                )}
                              </div>
                            )}
                          </div>
                        </div>

                        {/* Actions Toolbar */}
                        <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-slate-100 dark:border-slate-800 text-xs">
                          <div className="flex items-center gap-1.5 flex-wrap">
                            {/* 1-Click Renew Action */}
                            <button
                              disabled={renewingAllocationId === a.id}
                              onClick={() => handleRenewAllocation(a.id)}
                              className="px-2.5 py-1 rounded-md bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 text-white font-bold text-xs flex items-center gap-1 shadow-xs transition-all"
                              title="Extend sponsorship for +1 Year (+365 days) and advance cycle"
                            >
                              <RefreshCw className={`w-3 h-3 ${renewingAllocationId === a.id ? 'animate-spin' : ''}`} />
                              Renew +1 Year
                            </button>

                            {/* Manual Dates Adjustment */}
                            <button
                              onClick={() => {
                                setEditingDatesAllocation(a);
                                setDatesForm({
                                  start_date: a.start_date || '',
                                  end_date: a.end_date || '',
                                  renewal_status: a.renewal_status || 'active'
                                });
                              }}
                              className="px-2.5 py-1 rounded-md bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700 font-semibold text-xs flex items-center gap-1 transition-all"
                              title="Edit start date, end date, and renewal status"
                            >
                              <Calendar className="w-3 h-3 text-slate-500" />
                              Dates
                            </button>

                            {/* Annual Feedbacks Drawer */}
                            <button
                              onClick={() => {
                                const ben = beneficiaries.find(b => b.id === a.beneficiary_id) || {
                                  id: a.beneficiary_id,
                                  name: a.beneficiary_name,
                                  project_code: a.project_code,
                                  allocation_id: a.id,
                                  donor_name: a.donor_name,
                                  donor_email: a.donor_email,
                                  sponsorship_type: a.sponsorship_type
                                };
                                openFeedbackTimeline(ben);
                              }}
                              className="px-2.5 py-1 rounded-md bg-indigo-50 dark:bg-indigo-950/60 text-indigo-600 dark:text-indigo-400 border border-indigo-200 dark:border-indigo-800 hover:bg-indigo-100 font-bold text-xs flex items-center gap-1 transition-all"
                              title="View & log annual progress reports"
                            >
                              <FileText className="w-3 h-3" />
                              Feedback ({a.feedbacks_count || 0})
                            </button>

                            {/* Renewal Notice Email Action */}
                            {Boolean(a.donor_email && a.donor_email.trim() && a.donor_email.toLowerCase() !== 'n/a') && (a.cycle_status === 'due' || a.cycle_status === 'grace') && (
                              <button
                                onClick={() => openEmailDispatcher(a, 'renewal_notice')}
                                className="px-2.5 py-1 rounded-md bg-amber-600 hover:bg-amber-700 text-white font-bold text-xs flex items-center gap-1 shadow-xs transition-all animate-bounce"
                                title="Send Renewal Notice Outreach Email"
                              >
                                <Mail className="w-3 h-3" />
                                Send Renewal Notice
                              </button>
                            )}

                            {/* Standard Email Dispatch - Hidden if no email, with + Add Email option */}
                            {Boolean(a.donor_email && a.donor_email.trim() && a.donor_email.toLowerCase() !== 'n/a') ? (
                              <button
                                onClick={() => openEmailDispatcher(a, 'profile_intro')}
                                className="px-2.5 py-1 rounded-md bg-blue-600 hover:bg-blue-700 text-white font-bold text-xs flex items-center gap-1 shadow-xs transition-all"
                                title="Send Profile & Updates via Outlook"
                              >
                                <Send className="w-3 h-3" />
                                Outlook Email
                              </button>
                            ) : (
                              <button
                                onClick={() => openEditContactModal(a)}
                                className="px-2.5 py-1 rounded-md bg-amber-50 dark:bg-amber-950/60 text-amber-700 dark:text-amber-300 border border-amber-300 dark:border-amber-800 hover:bg-amber-100 dark:hover:bg-amber-900/60 font-bold text-xs flex items-center gap-1 transition-all cursor-pointer"
                                title="Add email address to enable Outlook email sending"
                              >
                                <Mail className="w-3 h-3 text-amber-600" />
                                + Add Email
                              </button>
                            )}

                            <button
                              onClick={() => openConversationDrawer(a)}
                              className="px-2.5 py-1 rounded-md bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700 font-semibold text-xs flex items-center gap-1 transition-all"
                            >
                              <MessageSquare className="w-3 h-3 text-blue-500" />
                              Messages ({a.messages_count || 0})
                              {a.inbound_replies_count > 0 && (
                                <span className="w-2 h-2 rounded-full bg-cyan-500" />
                              )}
                            </button>
                          </div>

                          <div className="flex items-center gap-1.5">
                            <button
                              onClick={() => handleDeallocate(a.id, a.beneficiary_name)}
                              className="px-2.5 py-1 rounded-md text-rose-500 hover:text-rose-700 hover:bg-rose-50 dark:hover:bg-rose-950/40 text-xs font-semibold transition-all"
                            >
                              Release
                            </button>
                          </div>
                        </div>
                      </div>
                    ))
                  )}
                </div>

                {/* Active Allocations Pagination Footer */}
                {!loadingData && filteredAllocations.length > 0 && (
                  <div className="pt-3 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between text-xs text-slate-500 flex-wrap gap-2">
                    <div className="flex items-center gap-2">
                      <span className="text-[11px]">
                        Showing <strong className="text-slate-700 dark:text-slate-300">{(allocationPage - 1) * allocationPageSize + 1}</strong> to <strong className="text-slate-700 dark:text-slate-300">{Math.min(allocationPage * allocationPageSize, filteredAllocations.length)}</strong> of <strong className="text-slate-700 dark:text-slate-300">{filteredAllocations.length}</strong>
                      </span>
                      <select
                        value={allocationPageSize}
                        onChange={(e) => {
                          setAllocationPageSize(Number(e.target.value));
                          setAllocationPage(1);
                        }}
                        className="px-1.5 py-0.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded text-[11px] font-semibold text-slate-700 dark:text-slate-300"
                      >
                        <option value={10}>10 / page</option>
                        <option value={25}>25 / page</option>
                        <option value={50}>50 / page</option>
                        <option value={100}>100 / page</option>
                      </select>
                    </div>

                    <div className="flex items-center gap-1">
                      <button
                        disabled={allocationPage <= 1}
                        onClick={() => setAllocationPage(1)}
                        className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-30"
                        title="First page"
                      >
                        <ChevronsLeft className="w-3.5 h-3.5" />
                      </button>
                      <button
                        disabled={allocationPage <= 1}
                        onClick={() => setAllocationPage(prev => Math.max(1, prev - 1))}
                        className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-30"
                        title="Previous page"
                      >
                        <ChevronLeft className="w-3.5 h-3.5" />
                      </button>

                      <span className="px-2 py-0.5 font-bold text-[11px] bg-slate-100 dark:bg-slate-800 rounded text-slate-700 dark:text-slate-300">
                        {allocationPage} / {totalAllocationPages}
                      </span>

                      <button
                        disabled={allocationPage >= totalAllocationPages}
                        onClick={() => setAllocationPage(prev => Math.min(totalAllocationPages, prev + 1))}
                        className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-30"
                        title="Next page"
                      >
                        <ChevronRight className="w-3.5 h-3.5" />
                      </button>
                      <button
                        disabled={allocationPage >= totalAllocationPages}
                        onClick={() => setAllocationPage(totalAllocationPages)}
                        className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-30"
                        title="Last page"
                      >
                        <ChevronsRight className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================= */}
      {/* TAB OVERDUE ALERTS: SPONSORSHIP SLA & UNALLOCATED ENGINE  */}
      {/* ========================================================= */}
      {activeTab === 'alerts' && (
        <div className="flex flex-col gap-6">
          {/* Top Alert Center Header Bar */}
          <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 bg-white dark:bg-slate-900 p-5 rounded-2xl border border-slate-200/80 dark:border-slate-800 shadow-sm">
            <div className="flex items-center gap-3">
              <div className="p-3 rounded-xl bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20">
                <AlertTriangle className="w-6 h-6 text-amber-500" />
              </div>
              <div>
                <h2 className="text-lg md:text-xl font-black text-slate-800 dark:text-white tracking-tight flex items-center gap-2">
                  Sponsorship Overdue & SLA Alert Center
                  <span className="text-xs uppercase px-2.5 py-0.5 rounded-full font-bold bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20">
                    Threshold: &ge; {overdueThreshold} Days
                  </span>
                </h2>
                <p className="text-xs md:text-sm text-slate-500 dark:text-slate-400">
                  Real-time monitoring of donors and campaigns who contributed towards sponsorships but have pending beneficiary allocations beyond the SLA window.
                </p>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2.5">
              <button
                onClick={() => {
                  loadOverdueSummary(true);
                  loadOverdueDonors(true);
                  loadOverdueCampaigns(true);
                  loadOverdueDismissals();
                }}
                className="px-3.5 py-2 rounded-xl bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 text-xs font-bold transition-all flex items-center gap-1.5 shadow-xs"
                title="Force refresh overdue alerts cache"
              >
                <RefreshCw className={`w-4 h-4 text-slate-500 ${loadingOverdue ? 'animate-spin' : ''}`} />
                Refresh
              </button>

              {/* EXPORT CSV DROPDOWN MENU */}
              <div className="relative">
                <button
                  type="button"
                  onClick={() => setShowExportMenu(prev => !prev)}
                  disabled={exportingCsv}
                  className="px-3.5 py-2 rounded-xl bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 text-xs font-bold transition-all flex items-center gap-1.5 shadow-xs disabled:opacity-50"
                  title="Export overdue alerts to CSV"
                >
                  <Download className={`w-4 h-4 text-slate-500 ${exportingCsv ? 'animate-bounce' : ''}`} />
                  <span>{exportingCsv ? 'Exporting...' : 'Export CSV'}</span>
                  <ChevronDown className={`w-3.5 h-3.5 text-slate-400 transition-transform ${showExportMenu ? 'rotate-180' : ''}`} />
                </button>

                {showExportMenu && (
                  <div
                    className="absolute right-0 mt-2 w-64 bg-white dark:bg-slate-900 rounded-xl shadow-2xl border border-slate-200 dark:border-slate-800 py-1.5 z-50 animate-in fade-in zoom-in-95 duration-150"
                    onMouseLeave={() => setShowExportMenu(false)}
                  >
                    <div className="px-3.5 py-2 text-[10px] uppercase font-bold tracking-wider text-slate-400 border-b border-slate-100 dark:border-slate-800">
                      Choose Export Scope
                    </div>

                    <button
                      type="button"
                      onClick={() => {
                        setShowExportMenu(false);
                        exportOverdueCsv('current');
                      }}
                      className="w-full text-left px-3.5 py-2.5 hover:bg-slate-50 dark:hover:bg-slate-800 flex items-start gap-2.5 transition-colors group"
                    >
                      <FileText className="w-4 h-4 text-blue-500 shrink-0 mt-0.5 group-hover:scale-110 transition-transform" />
                      <div>
                        <div className="text-xs font-bold text-slate-700 dark:text-slate-200">
                          Export Current Page
                        </div>
                        <div className="text-[11px] text-slate-400">
                          {overdueActiveSubTab === 'donors'
                            ? `${overdueDonors.length} donors on current page`
                            : overdueActiveSubTab === 'campaigns'
                              ? `${overdueCampaigns.length} campaigns on current page`
                              : `${overdueDismissals.length} dismissed records`}
                        </div>
                      </div>
                    </button>

                    <button
                      type="button"
                      onClick={() => {
                        setShowExportMenu(false);
                        exportOverdueCsv('all');
                      }}
                      className="w-full text-left px-3.5 py-2.5 hover:bg-slate-50 dark:hover:bg-slate-800 flex items-start gap-2.5 transition-colors border-t border-slate-100 dark:border-slate-800/60 group"
                    >
                      <Download className="w-4 h-4 text-emerald-500 shrink-0 mt-0.5 group-hover:scale-110 transition-transform" />
                      <div>
                        <div className="text-xs font-bold text-slate-700 dark:text-slate-200">
                          Export All Matching Records
                        </div>
                        <div className="text-[11px] text-slate-400">
                          {overdueActiveSubTab === 'donors'
                            ? `All ${overdueTotalDonors} overdue donors`
                            : overdueActiveSubTab === 'campaigns'
                              ? `All ${overdueTotalCampaigns} overdue campaigns`
                              : `All ${overdueDismissals.length} dismissed records`}
                        </div>
                      </div>
                    </button>
                  </div>
                )}
              </div>

              <button
                onClick={() => setShowAlertSettingsModal(true)}
                className="px-3.5 py-2 rounded-xl bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 text-xs font-bold transition-all flex items-center gap-1.5 shadow-xs"
                title="Configure alert thresholds & staff recipients"
              >
                <Sliders className="w-4 h-4 text-slate-500" />
                Alert Settings
              </button>

              <button
                disabled={sendingDigest}
                onClick={() => handleSendOverdueDigest(false)}
                className="px-4 py-2 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700 text-white text-xs font-bold transition-all flex items-center gap-2 shadow-sm disabled:opacity-50"
                title="Immediately send the SLA digest email to configured staff recipients"
              >
                <SendHorizontal className="w-4 h-4" />
                {sendingDigest ? 'Sending Digest...' : 'Send Digest to Staff'}
              </button>
            </div>
          </div>

          {/* Digest Feedback Banner if any */}
          {digestFeedback && (
            <div className={`p-4 rounded-xl border flex items-center justify-between gap-3 text-xs font-semibold ${
              digestFeedback.status === 'success'
                ? 'bg-emerald-50 dark:bg-emerald-950/40 border-emerald-200 dark:border-emerald-800 text-emerald-800 dark:text-emerald-300'
                : (digestFeedback.status === 'warning'
                    ? 'bg-amber-50 dark:bg-amber-950/40 border-amber-200 dark:border-amber-800 text-amber-800 dark:text-amber-300'
                    : 'bg-rose-50 dark:bg-rose-950/40 border-rose-200 dark:border-rose-800 text-rose-800 dark:text-rose-300')
            }`}>
              <div className="flex items-center gap-2">
                <AlertCircle className="w-4 h-4 shrink-0" />
                <span>{digestFeedback.message}</span>
              </div>
              <button onClick={() => setDigestFeedback(null)} className="text-slate-400 hover:text-slate-600">
                <X className="w-4 h-4" />
              </button>
            </div>
          )}

          {/* 4 KPI Summary Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-200/80 dark:border-slate-800 shadow-sm flex items-center gap-3">
              <div className="p-3 rounded-xl bg-rose-500/10 text-rose-600 dark:text-rose-400 border border-rose-500/20">
                <Users className="w-6 h-6" />
              </div>
              <div>
                <div className="text-2xl font-black text-slate-800 dark:text-white">
                  {overdueSummary ? overdueSummary.total_overdue_donors.toLocaleString() : '...'}
                </div>
                <div className="text-xs font-semibold text-slate-500 dark:text-slate-400">
                  Overdue Donors (&ge;{overdueThreshold}d)
                </div>
              </div>
            </div>

            <div className="bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-200/80 dark:border-slate-800 shadow-sm flex items-center gap-3">
              <div className="p-3 rounded-xl bg-purple-500/10 text-purple-600 dark:text-purple-400 border border-purple-500/20">
                <Layers className="w-6 h-6" />
              </div>
              <div>
                <div className="text-2xl font-black text-slate-800 dark:text-white">
                  {overdueSummary ? overdueSummary.total_overdue_campaigns.toLocaleString() : '...'}
                </div>
                <div className="text-xs font-semibold text-slate-500 dark:text-slate-400">
                  Overdue Campaigns (&ge;{overdueThreshold}d)
                </div>
              </div>
            </div>

            <div className="bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-200/80 dark:border-slate-800 shadow-sm flex items-center gap-3">
              <div className="p-3 rounded-xl bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20">
                <HeartHandshake className="w-6 h-6" />
              </div>
              <div>
                <div className="text-2xl font-black text-slate-800 dark:text-white">
                  {overdueSummary ? overdueSummary.total_unallocated_slots.toLocaleString() : '...'}
                </div>
                <div className="text-xs font-semibold text-slate-500 dark:text-slate-400">
                  Unallocated Slots Waiting
                </div>
              </div>
            </div>

            <div className="bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-200/80 dark:border-slate-800 shadow-sm flex items-center gap-3">
              <div className="p-3 rounded-xl bg-blue-500/10 text-blue-600 dark:text-blue-400 border border-blue-500/20">
                <Clock className="w-6 h-6" />
              </div>
              <div>
                <div className="text-2xl font-black text-rose-600 dark:text-rose-400">
                  {overdueSummary ? `${overdueSummary.longest_waiting_days} Days` : '...'}
                </div>
                <div className="text-xs font-semibold text-slate-500 dark:text-slate-400">
                  Longest Unallocated Age
                </div>
              </div>
            </div>
          </div>

          {/* Controls: Program Filter, Target Status Filter, Days Threshold, Severity Filter, Search */}
          <div className="flex flex-col gap-4 bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-200/80 dark:border-slate-800 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-3">
              {/* Sponsorship Types */}
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className="text-xs font-bold text-slate-400 uppercase tracking-wider mr-1">Program:</span>
                {['All', 'Orphan', 'Hafiz', 'Widow', 'Ex-Prisoner'].map((t) => (
                  <button
                    key={t}
                    onClick={() => {
                      setOverdueTypeFilter(t);
                      setOverdueDonorPage(1);
                      setOverdueCampaignPage(1);
                    }}
                    className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${
                      overdueTypeFilter === t
                        ? 'bg-blue-600 text-white shadow-xs'
                        : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200'
                    }`}
                  >
                    {t}
                  </button>
                ))}
              </div>

              {/* Threshold Preset Pills */}
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className="text-xs font-bold text-slate-400 uppercase tracking-wider mr-1">Threshold:</span>
                {[15, 30, 60, 90].map((days) => (
                  <button
                    key={days}
                    onClick={() => {
                      setOverdueThreshold(days);
                      setOverdueDonorPage(1);
                      setOverdueCampaignPage(1);
                    }}
                    className={`px-2.5 py-1 rounded-lg text-xs font-bold transition-all ${
                      overdueThreshold === days
                        ? 'bg-amber-500 text-white shadow-xs'
                        : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200'
                    }`}
                  >
                    &ge; {days} Days {days === 30 ? '(Default)' : ''}
                  </button>
                ))}
              </div>
            </div>

            {/* Target Status Filter */}
            <div className="flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-slate-100 dark:border-slate-800">
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className="text-xs font-bold text-slate-400 uppercase tracking-wider mr-1">Target Status:</span>
                {[
                  { id: 'all', label: 'All Statuses' },
                  { id: 'target_reached', label: '🎯 Target Reached (≥100%)' },
                  { id: 'threshold_reached', label: '✅ Threshold Reached (≥80%)' },
                  { id: 'below_threshold', label: '⏳ Below Target (<80%)' }
                ].map((ts) => (
                  <button
                    key={ts.id}
                    onClick={() => {
                      setOverdueTargetStatusFilter(ts.id);
                      setOverdueDonorPage(1);
                      setOverdueCampaignPage(1);
                    }}
                    className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${
                      overdueTargetStatusFilter === ts.id
                        ? 'bg-blue-600 text-white shadow-xs'
                        : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200'
                    }`}
                  >
                    {ts.label}
                  </button>
                ))}
              </div>

              {/* Quick Target Stat Summary Badges */}
              {overdueSummary?.by_target_status && (
                <div className="flex items-center gap-2 text-[11px] font-bold">
                  <span className="px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700 dark:bg-emerald-950/80 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800">
                    🎯 {overdueSummary.by_target_status.target_reached || 0} Met
                  </span>
                  <span className="px-2 py-0.5 rounded-full bg-blue-100 text-blue-700 dark:bg-blue-950/80 dark:text-blue-300 border border-blue-200 dark:border-blue-800">
                    ✅ {overdueSummary.by_target_status.threshold_reached || 0} Approaching
                  </span>
                  <span className="px-2 py-0.5 rounded-full bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400 border border-slate-200 dark:border-slate-700">
                    ⏳ {overdueSummary.by_target_status.below_threshold || 0} In Progress
                  </span>
                </div>
              )}
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-slate-100 dark:border-slate-800">
              {/* Severity Filter */}
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className="text-xs font-bold text-slate-400 uppercase tracking-wider mr-1">Severity:</span>
                {[
                  { id: 'all', label: 'All Severities' },
                  { id: 'critical', label: '🔴 Critical (90d+)' },
                  { id: 'urgent', label: '🟠 Urgent (60-89d)' },
                  { id: 'warning', label: '🟡 Warning (30-59d)' }
                ].map((s) => (
                  <button
                    key={s.id}
                    onClick={() => {
                      setOverdueSeverityFilter(s.id);
                      setOverdueDonorPage(1);
                      setOverdueCampaignPage(1);
                    }}
                    className={`px-2.5 py-1 rounded-md text-xs font-semibold transition-all ${
                      overdueSeverityFilter === s.id
                        ? 'bg-slate-800 text-white dark:bg-slate-200 dark:text-slate-900 shadow-xs'
                        : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200'
                    }`}
                  >
                    {s.label}
                  </button>
                ))}
              </div>

              {/* Search Bar */}
              <div className="relative w-full sm:w-72">
                <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                <input
                  type="text"
                  placeholder="Search donor, email, campaign..."
                  value={overdueSearchQuery}
                  onChange={(e) => {
                    setOverdueSearchQuery(e.target.value);
                    setOverdueDonorPage(1);
                    setOverdueCampaignPage(1);
                  }}
                  className="w-full pl-9 pr-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-xs text-slate-900 dark:text-white placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>
            </div>
          </div>

          {/* Sub-View Switcher: Donors vs Campaigns vs Dismissed */}
          <div className="flex items-center gap-2 border-b border-slate-200 dark:border-slate-800 pb-2 flex-wrap">
            <button
              onClick={() => setOverdueActiveSubTab('donors')}
              className={`px-4 py-2 rounded-xl text-xs md:text-sm font-bold transition-all flex items-center gap-2 ${
                overdueActiveSubTab === 'donors'
                  ? 'bg-blue-600 text-white shadow-sm'
                  : 'bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 border border-slate-200/80 dark:border-slate-800'
              }`}
            >
              <Users className="w-4 h-4" />
              Overdue Donors ({overdueTotalDonors.toLocaleString()})
            </button>

            <button
              onClick={() => setOverdueActiveSubTab('campaigns')}
              className={`px-4 py-2 rounded-xl text-xs md:text-sm font-bold transition-all flex items-center gap-2 ${
                overdueActiveSubTab === 'campaigns'
                  ? 'bg-purple-600 text-white shadow-sm'
                  : 'bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 border border-slate-200/80 dark:border-slate-800'
              }`}
            >
              <Layers className="w-4 h-4" />
              Overdue Campaigns ({overdueTotalCampaigns.toLocaleString()})
            </button>

            <button
              onClick={() => {
                setOverdueActiveSubTab('dismissed');
                loadOverdueDismissals();
              }}
              className={`px-4 py-2 rounded-xl text-xs md:text-sm font-bold transition-all flex items-center gap-2 ${
                overdueActiveSubTab === 'dismissed'
                  ? 'bg-rose-600 text-white shadow-sm'
                  : 'bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 border border-slate-200/80 dark:border-slate-800'
              }`}
            >
              <EyeOff className="w-4 h-4" />
              Dismissed False Positives ({overdueDismissalsCount || 0})
            </button>
          </div>

          {/* OVERDUE DONORS TABLE */}
          {overdueActiveSubTab === 'donors' && (
            <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200/80 dark:border-slate-800 shadow-sm overflow-hidden flex flex-col">
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse text-xs">
                  <thead>
                    <tr className="bg-slate-50 dark:bg-slate-800/80 text-slate-500 uppercase font-bold text-[11px] tracking-wider border-b border-slate-200 dark:border-slate-800">
                      <th className="py-3 px-4">Donor Name & Contact</th>
                      <th className="py-3 px-4">Program</th>
                      <th className="py-3 px-4 text-center">Unallocated Slots</th>
                      <th className="py-3 px-4 text-right min-w-[170px]">Total Donated / Target</th>
                      <th className="py-3 px-4">Oldest Donation</th>
                      <th className="py-3 px-4 text-center">Waiting Age</th>
                      <th className="py-3 px-4">Involved Campaigns</th>
                      <th className="py-3 px-4 text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                    {loadingOverdue ? (
                      <tr>
                        <td colSpan="8" className="py-12 text-center text-slate-400">
                          <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2 text-blue-500" />
                          Loading overdue donors...
                        </td>
                      </tr>
                    ) : overdueDonors.length === 0 ? (
                      <tr>
                        <td colSpan="8" className="py-12 text-center text-slate-400">
                          <CheckCircle2 className="w-8 h-8 mx-auto mb-2 text-emerald-500 opacity-60" />
                          <div className="font-bold text-sm text-slate-700 dark:text-slate-300">No overdue donors found!</div>
                          <div className="text-xs mt-1">All donors within the {overdueThreshold}-day window have been allocated.</div>
                        </td>
                      </tr>
                    ) : (
                      overdueDonors.map((d, idx) => {
                        const sevBadge = d.severity === 'critical'
                          ? 'bg-rose-500/10 text-rose-600 border-rose-500/20 dark:text-rose-400'
                          : (d.severity === 'urgent'
                              ? 'bg-orange-500/10 text-orange-600 border-orange-500/20 dark:text-orange-400'
                              : 'bg-amber-500/10 text-amber-600 border-amber-500/20 dark:text-amber-400');
                        return (
                          <tr key={`${d.donor_id}_${d.sponsorship_type}_${idx}`} className="hover:bg-slate-50/60 dark:hover:bg-slate-800/40 transition-colors">
                            <td className="py-3 px-4">
                              <div className="font-bold text-slate-800 dark:text-slate-100 flex items-center gap-1.5">
                                {d.donor_name}
                                {d.is_manual && (
                                  <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-slate-200 dark:bg-slate-700 text-slate-600 dark:text-slate-300">Manual</span>
                                )}
                              </div>
                              <div className="text-[11px] text-slate-500 dark:text-slate-400 flex items-center gap-2 mt-0.5">
                                {d.donor_email && d.donor_email !== 'N/A' && (
                                  <span className="flex items-center gap-1 hover:text-blue-500">
                                    <Mail className="w-3 h-3 text-slate-400" />
                                    {d.donor_email}
                                  </span>
                                )}
                                {d.donor_phone && (
                                  <span className="flex items-center gap-1 hover:text-blue-500">
                                    <Phone className="w-3 h-3 text-slate-400" />
                                    {d.donor_phone}
                                  </span>
                                )}
                              </div>
                            </td>

                            <td className="py-3 px-4">
                              <span className="px-2.5 py-1 rounded-full text-xs font-bold bg-blue-50 dark:bg-blue-950/60 text-blue-600 dark:text-blue-400 border border-blue-200/60 dark:border-blue-800/60">
                                {d.sponsorship_type}
                              </span>
                            </td>

                            <td className="py-3 px-4 text-center">
                              {d.max_slots > 0 ? (
                                <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-black bg-rose-500/10 text-rose-600 dark:text-rose-400 border border-rose-500/20">
                                  {d.remaining_slots} / {d.max_slots} slots
                                </span>
                              ) : (
                                <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-bold bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20">
                                  Partial ({d.pct_raised || 0}%)
                                </span>
                              )}
                            </td>

                            <td className="py-3 px-4 text-right">
                              <div className="font-mono font-bold text-slate-800 dark:text-slate-200">
                                £{d.total_donated.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                                {d.target_amount && (
                                  <span className="text-[11px] font-normal text-slate-400 dark:text-slate-500 ml-1">
                                    / £{d.target_amount.toLocaleString()}
                                  </span>
                                )}
                              </div>
                              <div className="flex items-center justify-end gap-1.5 mt-1">
                                {d.is_target_reached ? (
                                  <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-bold bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border border-emerald-500/20">
                                    🎯 Target Reached ({d.pct_raised}%)
                                  </span>
                                ) : d.is_threshold_reached ? (
                                  <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-bold bg-blue-500/10 text-blue-700 dark:text-blue-400 border border-blue-500/20">
                                    ✅ Threshold Reached ({d.pct_raised}%)
                                  </span>
                                ) : (
                                  <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-bold bg-amber-500/10 text-amber-700 dark:text-amber-400 border border-amber-500/20">
                                    ⏳ Below Target ({d.pct_raised}%)
                                  </span>
                                )}
                              </div>
                              <div className="w-full bg-slate-100 dark:bg-slate-700/60 h-1.5 rounded-full overflow-hidden mt-1.5">
                                <div
                                  className={`h-full rounded-full transition-all ${
                                    d.is_target_reached
                                      ? 'bg-emerald-500'
                                      : d.is_threshold_reached
                                      ? 'bg-blue-500'
                                      : 'bg-amber-500'
                                  }`}
                                  style={{ width: `${Math.min(d.pct_raised || 0, 100)}%` }}
                                />
                              </div>
                            </td>

                            <td className="py-3 px-4 font-mono text-slate-600 dark:text-slate-300">
                              {d.oldest_donation_date || 'N/A'}
                            </td>

                            <td className="py-3 px-4 text-center">
                              <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-black border ${sevBadge}`}>
                                <Clock className="w-3 h-3" />
                                {d.waiting_days} days
                              </span>
                            </td>

                            <td className="py-3 px-4 max-w-xs text-slate-600 dark:text-slate-400">
                              {(d.campaigns_involved && d.campaigns_involved.length > 0) ? (
                                <div className="flex flex-wrap items-center gap-1">
                                  {d.campaigns_involved.slice(0, 2).map((camp, cIdx) => (
                                    <a
                                      key={cIdx}
                                      href={`https://www.launchgood.com/campaign/search?q=${encodeURIComponent(camp)}`}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-slate-100 hover:bg-blue-50 hover:text-blue-600 dark:bg-slate-800 dark:hover:bg-blue-950/40 text-slate-700 dark:text-slate-300 text-[10px] font-medium transition-colors border border-transparent hover:border-blue-200 dark:hover:border-blue-800/50"
                                      title={`Verify "${camp}" on LaunchGood`}
                                    >
                                      <span className="truncate max-w-[120px]">{camp}</span>
                                      <ExternalLink className="w-2.5 h-2.5 text-slate-400" />
                                    </a>
                                  ))}
                                  {d.campaigns_involved.length > 2 && (
                                    <span className="text-[10px] text-slate-400 font-bold" title={d.campaigns_involved.slice(2).join(', ')}>
                                      +{d.campaigns_involved.length - 2} more
                                    </span>
                                  )}
                                </div>
                              ) : (
                                <span className="text-slate-400 italic">General / Online</span>
                              )}
                            </td>

                            <td className="py-3 px-4 text-right">
                              <div className="flex items-center justify-end gap-1.5">
                                <button
                                  onClick={() => handleAllocateOverdueDonor(d)}
                                  className="px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-bold text-xs flex items-center gap-1.5 shadow-xs transition-all"
                                  title="Allocate beneficiary to this donor now"
                                >
                                  <Zap className="w-3.5 h-3.5" />
                                  Allocate Now
                                </button>
                                <button
                                  onClick={() => setDismissModalData({
                                    isOpen: true,
                                    item: d,
                                    type: 'donor',
                                    reason: 'False positive / Not for 1-to-1 sponsorship',
                                    customReason: ''
                                  })}
                                  className="p-1.5 rounded-lg text-slate-400 hover:text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950/40 border border-slate-200 dark:border-slate-700 transition-all flex items-center gap-1 text-[11px] font-semibold"
                                  title="Dismiss / Mark as False Positive"
                                >
                                  <EyeOff className="w-3.5 h-3.5" />
                                  <span className="hidden sm:inline">Dismiss</span>
                                </button>
                              </div>
                            </td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>

              {/* Pagination Toolbar */}
              {overdueTotalDonors > overdueDonorPageSize && (
                <div className="flex items-center justify-between p-3.5 border-t border-slate-100 dark:border-slate-800 text-xs text-slate-500">
                  <div>
                    Showing {Math.min(overdueTotalDonors, (overdueDonorPage - 1) * overdueDonorPageSize + 1)} - {Math.min(overdueTotalDonors, overdueDonorPage * overdueDonorPageSize)} of {overdueTotalDonors} overdue donors
                  </div>
                  <div className="flex items-center gap-1">
                    <button
                      disabled={overdueDonorPage <= 1}
                      onClick={() => setOverdueDonorPage(prev => Math.max(1, prev - 1))}
                      className="px-2.5 py-1 rounded bg-slate-100 dark:bg-slate-800 disabled:opacity-40"
                    >
                      &larr; Prev
                    </button>
                    <span className="px-2 font-bold text-slate-700 dark:text-slate-300">
                      Page {overdueDonorPage} / {Math.ceil(overdueTotalDonors / overdueDonorPageSize)}
                    </span>
                    <button
                      disabled={overdueDonorPage >= Math.ceil(overdueTotalDonors / overdueDonorPageSize)}
                      onClick={() => setOverdueDonorPage(prev => prev + 1)}
                      className="px-2.5 py-1 rounded bg-slate-100 dark:bg-slate-800 disabled:opacity-40"
                    >
                      Next &rarr;
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* OVERDUE CAMPAIGNS TABLE */}
          {overdueActiveSubTab === 'campaigns' && (
            <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200/80 dark:border-slate-800 shadow-sm overflow-hidden flex flex-col">
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse text-xs">
                  <thead>
                    <tr className="bg-slate-50 dark:bg-slate-800/80 text-slate-500 uppercase font-bold text-[11px] tracking-wider border-b border-slate-200 dark:border-slate-800">
                      <th className="py-3 px-4">Campaign Name & Community</th>
                      <th className="py-3 px-4">Organizer Contact</th>
                      <th className="py-3 px-4">Program</th>
                      <th className="py-3 px-4 text-center">Unallocated Slots</th>
                      <th className="py-3 px-4 text-right min-w-[170px]">Total Raised / Target</th>
                      <th className="py-3 px-4">Oldest Donation</th>
                      <th className="py-3 px-4 text-center">Waiting Age</th>
                      <th className="py-3 px-4 text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                    {loadingOverdue ? (
                      <tr>
                        <td colSpan="8" className="py-12 text-center text-slate-400">
                          <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2 text-purple-500" />
                          Loading overdue campaigns...
                        </td>
                      </tr>
                    ) : overdueCampaigns.length === 0 ? (
                      <tr>
                        <td colSpan="8" className="py-12 text-center text-slate-400">
                          <CheckCircle2 className="w-8 h-8 mx-auto mb-2 text-emerald-500 opacity-60" />
                          <div className="font-bold text-sm text-slate-700 dark:text-slate-300">No overdue campaigns found!</div>
                          <div className="text-xs mt-1">All campaigns within the {overdueThreshold}-day window have been allocated.</div>
                        </td>
                      </tr>
                    ) : (
                      overdueCampaigns.map((c, idx) => {
                        const sevBadge = c.severity === 'critical'
                          ? 'bg-rose-500/10 text-rose-600 border-rose-500/20 dark:text-rose-400'
                          : (c.severity === 'urgent'
                              ? 'bg-orange-500/10 text-orange-600 border-orange-500/20 dark:text-orange-400'
                              : 'bg-amber-500/10 text-amber-600 border-amber-500/20 dark:text-amber-400');
                        return (
                          <tr key={`${c.campaign_name}_${c.sponsorship_type}_${idx}`} className="hover:bg-slate-50/60 dark:hover:bg-slate-800/40 transition-colors">
                            <td className="py-3 px-4">
                              <div className="font-bold text-slate-800 dark:text-slate-100 flex items-center gap-2 flex-wrap">
                                <span>{c.campaign_name}</span>
                                {c.campaign_url && (
                                  <a
                                    href={c.campaign_url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className={`inline-flex items-center gap-1 text-[11px] font-bold px-2 py-0.5 rounded-md border transition-all ${
                                      c.has_direct_url
                                        ? 'bg-blue-50 dark:bg-blue-950/60 text-blue-600 dark:text-blue-400 border-blue-200 dark:border-blue-800/60 hover:bg-blue-100 dark:hover:bg-blue-900/60'
                                        : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 border-slate-200 dark:border-slate-700 hover:bg-slate-200 dark:hover:bg-slate-700'
                                    }`}
                                    title={c.has_direct_url ? `Open verified campaign: ${c.campaign_url}` : `Search and verify "${c.campaign_name}" on LaunchGood`}
                                  >
                                    <span>{c.has_direct_url ? 'View Campaign' : 'Verify'}</span>
                                    <ExternalLink className="w-3 h-3" />
                                  </a>
                                )}
                              </div>
                              {c.community_name && (
                                <div className="text-[11px] text-purple-600 dark:text-purple-400 font-semibold mt-0.5">
                                  {c.community_name}
                                </div>
                              )}
                            </td>

                            <td className="py-3 px-4">
                              <div className="text-slate-700 dark:text-slate-300 font-medium">{c.organizer_name || 'Anonymous Organizer'}</div>
                              {c.organizer_email && (
                                <div className="text-[11px] text-slate-400 flex items-center gap-1">
                                  <Mail className="w-3 h-3 text-slate-400" />
                                  {c.organizer_email}
                                </div>
                              )}
                            </td>

                            <td className="py-3 px-4">
                              <span className="px-2.5 py-1 rounded-full text-xs font-bold bg-purple-50 dark:bg-purple-950/60 text-purple-600 dark:text-purple-400 border border-purple-200/60 dark:border-purple-800/60">
                                {c.sponsorship_type}
                              </span>
                            </td>

                            <td className="py-3 px-4 text-center">
                              {c.max_slots > 0 ? (
                                <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-black bg-rose-500/10 text-rose-600 dark:text-rose-400 border border-rose-500/20">
                                  {c.remaining_slots} / {c.max_slots} slots
                                </span>
                              ) : (
                                <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-bold bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20">
                                  Partial ({c.pct_raised || 0}%)
                                </span>
                              )}
                            </td>

                            <td className="py-3 px-4 text-right">
                              <div className="font-mono font-bold text-slate-800 dark:text-slate-200">
                                £{c.total_raised.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                                {c.target_amount && (
                                  <span className="text-[11px] font-normal text-slate-400 dark:text-slate-500 ml-1">
                                    / £{c.target_amount.toLocaleString()}
                                  </span>
                                )}
                              </div>
                              <div className="flex items-center justify-end gap-1.5 mt-1">
                                {c.is_target_reached ? (
                                  <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-bold bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border border-emerald-500/20">
                                    🎯 Target Reached ({c.pct_raised}%)
                                  </span>
                                ) : c.is_threshold_reached ? (
                                  <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-bold bg-blue-500/10 text-blue-700 dark:text-blue-400 border border-blue-500/20">
                                    ✅ Threshold Reached ({c.pct_raised}%)
                                  </span>
                                ) : (
                                  <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-bold bg-amber-500/10 text-amber-700 dark:text-amber-400 border border-amber-500/20">
                                    ⏳ Below Target ({c.pct_raised}%)
                                  </span>
                                )}
                              </div>
                              <div className="w-full bg-slate-100 dark:bg-slate-700/60 h-1.5 rounded-full overflow-hidden mt-1.5">
                                <div
                                  className={`h-full rounded-full transition-all ${
                                    c.is_target_reached
                                      ? 'bg-emerald-500'
                                      : c.is_threshold_reached
                                      ? 'bg-blue-500'
                                      : 'bg-amber-500'
                                  }`}
                                  style={{ width: `${Math.min(c.pct_raised || 0, 100)}%` }}
                                />
                              </div>
                            </td>

                            <td className="py-3 px-4 font-mono text-slate-600 dark:text-slate-300">
                              {c.oldest_donation_date || 'N/A'}
                            </td>

                            <td className="py-3 px-4 text-center">
                              <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-black border ${sevBadge}`}>
                                <Clock className="w-3 h-3" />
                                {c.waiting_days} days
                              </span>
                            </td>

                            <td className="py-3 px-4 text-right">
                              <div className="flex items-center justify-end gap-1.5">
                                <button
                                  onClick={() => handleAllocateOverdueCampaign(c)}
                                  className="px-3 py-1.5 rounded-lg bg-purple-600 hover:bg-purple-700 text-white font-bold text-xs flex items-center gap-1.5 shadow-xs transition-all"
                                  title="Allocate beneficiary to this campaign now"
                                >
                                  <Zap className="w-3.5 h-3.5" />
                                  Allocate Now
                                </button>
                                <button
                                  onClick={() => setDismissModalData({
                                    isOpen: true,
                                    item: c,
                                    type: 'campaign',
                                    reason: 'False positive / Not for 1-to-1 sponsorship',
                                    customReason: ''
                                  })}
                                  className="p-1.5 rounded-lg text-slate-400 hover:text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950/40 border border-slate-200 dark:border-slate-700 transition-all flex items-center gap-1 text-[11px] font-semibold"
                                  title="Dismiss / Mark as False Positive"
                                >
                                  <EyeOff className="w-3.5 h-3.5" />
                                  <span className="hidden sm:inline">Dismiss</span>
                                </button>
                              </div>
                            </td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>

              {/* Pagination Toolbar */}
              {overdueTotalCampaigns > overdueCampaignPageSize && (
                <div className="flex items-center justify-between p-3.5 border-t border-slate-100 dark:border-slate-800 text-xs text-slate-500">
                  <div>
                    Showing {Math.min(overdueTotalCampaigns, (overdueCampaignPage - 1) * overdueCampaignPageSize + 1)} - {Math.min(overdueTotalCampaigns, overdueCampaignPage * overdueCampaignPageSize)} of {overdueTotalCampaigns} overdue campaigns
                  </div>
                  <div className="flex items-center gap-1">
                    <button
                      disabled={overdueCampaignPage <= 1}
                      onClick={() => setOverdueCampaignPage(prev => Math.max(1, prev - 1))}
                      className="px-2.5 py-1 rounded bg-slate-100 dark:bg-slate-800 disabled:opacity-40"
                    >
                      &larr; Prev
                    </button>
                    <span className="px-2 font-bold text-slate-700 dark:text-slate-300">
                      Page {overdueCampaignPage} / {Math.ceil(overdueTotalCampaigns / overdueCampaignPageSize)}
                    </span>
                    <button
                      disabled={overdueCampaignPage >= Math.ceil(overdueTotalCampaigns / overdueCampaignPageSize)}
                      onClick={() => setOverdueCampaignPage(prev => prev + 1)}
                      className="px-2.5 py-1 rounded bg-slate-100 dark:bg-slate-800 disabled:opacity-40"
                    >
                      Next &rarr;
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* DISMISSED FALSE POSITIVES TABLE */}
          {overdueActiveSubTab === 'dismissed' && (
            <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200/80 dark:border-slate-800 shadow-sm overflow-hidden flex flex-col">
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse text-xs">
                  <thead>
                    <tr className="bg-slate-50 dark:bg-slate-800/80 text-slate-500 uppercase font-bold text-[11px] tracking-wider border-b border-slate-200 dark:border-slate-800">
                      <th className="py-3 px-4">Dismissed Entity</th>
                      <th className="py-3 px-4">Entity Type</th>
                      <th className="py-3 px-4">Program</th>
                      <th className="py-3 px-4">Reason / Note</th>
                      <th className="py-3 px-4">Dismissed On</th>
                      <th className="py-3 px-4 text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 dark:divide-slate-800 font-medium">
                    {overdueDismissals.length === 0 ? (
                      <tr>
                        <td colSpan={6} className="py-12 text-center text-slate-400">
                          <CheckCircle2 className="w-8 h-8 text-emerald-500 mx-auto mb-2 opacity-60" />
                          No dismissed alerts. Any donor or campaign marked as a false positive will appear here and can be restored anytime.
                        </td>
                      </tr>
                    ) : (
                      overdueDismissals.map((item) => (
                        <tr key={item.id} className="hover:bg-slate-50/60 dark:hover:bg-slate-800/40 transition-colors">
                          <td className="py-3 px-4 font-bold text-slate-800 dark:text-slate-100">
                            <div>{item.entity_name || item.entity_id}</div>
                            <div className="text-[10px] text-slate-400 font-mono">ID: {item.entity_id}</div>
                          </td>
                          <td className="py-3 px-4">
                            <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                              item.entity_type === 'donor'
                                ? 'bg-blue-50 dark:bg-blue-950/60 text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-800/50'
                                : 'bg-purple-50 dark:bg-purple-950/60 text-purple-600 dark:text-purple-400 border border-purple-200 dark:border-purple-800/50'
                            }`}>
                              {item.entity_type}
                            </span>
                          </td>
                          <td className="py-3 px-4">
                            <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300">
                              {item.sponsorship_type}
                            </span>
                          </td>
                          <td className="py-3 px-4 text-slate-600 dark:text-slate-300 max-w-sm">
                            <span className="italic">"{item.reason || 'False positive'}"</span>
                          </td>
                          <td className="py-3 px-4 text-slate-400 font-mono text-[11px]">
                            {item.dismissed_at ? new Date(item.dismissed_at).toLocaleDateString() : 'N/A'}
                          </td>
                          <td className="py-3 px-4 text-right">
                            <button
                              onClick={() => handleRestoreDismissal(item)}
                              className="px-3 py-1.5 rounded-lg bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 font-bold text-xs flex items-center gap-1.5 shadow-xs ml-auto transition-all"
                              title="Restore back to active overdue alerts"
                            >
                              <RotateCcw className="w-3.5 h-3.5 text-blue-600" />
                              Restore Alert
                            </button>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}


      {/* ========================================================= */}
      {/* TAB 4: MICROSOFT 365 / OUTLOOK INTEGRATION SETTINGS */}
      {/* ========================================================= */}
      {activeTab === 'outlook' && (
        <div className="flex flex-col gap-6">
          {/* Connection Status Card */}
          <div className="bg-white dark:bg-slate-900 p-6 rounded-2xl border border-slate-200/80 dark:border-slate-800 shadow-sm flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
            <div className="flex items-center gap-4">
              <div className={`p-4 rounded-2xl ${
                outlookStatus?.connected 
                  ? 'bg-blue-600 text-white shadow-lg shadow-blue-500/20' 
                  : 'bg-slate-100 dark:bg-slate-800 text-slate-400'
              }`}>
                <Mail className="w-8 h-8" />
              </div>

              <div>
                <div className="flex items-center gap-2">
                  <h3 className="text-lg font-black text-slate-800 dark:text-white">
                    Microsoft 365 / Outlook Integration (Graph API)
                  </h3>
                  <span className={`px-2.5 py-0.5 rounded-full text-xs font-bold ${
                    outlookStatus?.connected
                      ? 'bg-emerald-50 text-emerald-600 dark:bg-emerald-950/60 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800'
                      : 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400'
                  }`}>
                    {outlookStatus?.connected ? 'Connected' : 'Not Connected'}
                  </span>
                </div>

                <p className="text-xs md:text-sm text-slate-500 dark:text-slate-400 mt-1">
                  {outlookStatus?.connected
                    ? `Authenticated as ${outlookStatus.connected_email}. Real-time Microsoft Graph two-way sync enabled.`
                    : 'Connect your Microsoft 365 / Outlook organization account to dispatch updates and listen to donor replies.'}
                </p>
              </div>
            </div>

            <div className="flex items-center gap-3">
              {outlookStatus?.connected ? (
                <button
                  onClick={() => {
                    if (window.confirm('Disconnect Microsoft 365 / Outlook account?')) {
                      fetch(getAuthUrl(`${API_BASE_URL}/api/tracker/outlook/disconnect?company_id=${activeCompany}`), { 
                        method: 'POST',
                        headers: getAuthHeaders()
                      })
                        .then(() => loadBeneficiariesAndAllocations());
                    }
                  }}
                  className="px-4 py-2 rounded-xl bg-rose-50 dark:bg-rose-950/60 text-rose-600 dark:text-rose-400 border border-rose-200 dark:border-rose-800 text-xs font-bold hover:bg-rose-100 transition-all"
                >
                  Disconnect Account
                </button>
              ) : (
                <button
                  onClick={handleConnectOutlookOAuth}
                  className="px-5 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-700 text-white font-bold text-xs md:text-sm shadow-md transition-all flex items-center gap-2"
                >
                  <Mail className="w-4 h-4" />
                  Connect with Microsoft 365
                </button>
              )}
            </div>
          </div>

          {/* Credentials & Webhook Subscription Grid */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Microsoft Azure App Credentials */}
            <form onSubmit={handleSaveOutlookCredentials} className="bg-white dark:bg-slate-900 p-5 rounded-xl border border-slate-200/80 dark:border-slate-800 shadow-sm flex flex-col gap-4">
              <h4 className="font-bold text-slate-800 dark:text-slate-100 text-sm flex items-center gap-2">
                <Settings className="w-4 h-4 text-blue-500" />
                Microsoft Azure AD App Credentials
              </h4>

              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-semibold text-slate-600 dark:text-slate-400">Application (Client) ID</label>
                <input
                  type="text"
                  placeholder="e.g. 11111111-2222-3333-4444-555555555555"
                  value={outlookCreds.client_id}
                  onChange={(e) => setOutlookCreds({ ...outlookCreds, client_id: e.target.value })}
                  className="px-3 py-2 text-xs bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg font-mono"
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-semibold text-slate-600 dark:text-slate-400">Client Secret</label>
                <input
                  type="password"
                  placeholder="Azure App Client Secret Value"
                  value={outlookCreds.client_secret}
                  onChange={(e) => setOutlookCreds({ ...outlookCreds, client_secret: e.target.value })}
                  className="px-3 py-2 text-xs bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg"
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-semibold text-slate-600 dark:text-slate-400">Directory (Tenant) ID</label>
                <input
                  type="text"
                  placeholder="common (or your Azure Tenant GUID)"
                  value={outlookCreds.tenant_id}
                  onChange={(e) => setOutlookCreds({ ...outlookCreds, tenant_id: e.target.value })}
                  className="px-3 py-2 text-xs bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg font-mono"
                />
              </div>

              <button
                type="submit"
                disabled={savingOutlookCreds}
                className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-bold text-xs flex items-center justify-center gap-2 shadow-xs transition-all mt-2"
              >
                <Save className="w-4 h-4" />
                {savingOutlookCreds ? 'Saving...' : 'Save Microsoft 365 Credentials'}
              </button>
            </form>

            {/* Microsoft Graph Webhook Subscription */}
            <div className="bg-white dark:bg-slate-900 p-5 rounded-xl border border-slate-200/80 dark:border-slate-800 shadow-sm flex flex-col gap-4 justify-between">
              <div>
                <h4 className="font-bold text-slate-800 dark:text-slate-100 text-sm flex items-center gap-2">
                  <Inbox className="w-4 h-4 text-cyan-500" />
                  Microsoft Graph Webhook & Reply Listener
                </h4>
                <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                  Microsoft Graph delivers change notifications to this webhook when a donor replies.
                </p>

                <div className="mt-4 p-3 rounded-lg bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700 flex flex-col gap-1.5">
                  <span className="text-[11px] font-bold text-slate-500 uppercase">Notification Endpoint:</span>
                  <div className="flex items-center justify-between font-mono text-xs text-blue-600 dark:text-blue-400">
                    <span className="truncate">
                      {(API_BASE_URL.startsWith('http') ? API_BASE_URL : window.location.origin + API_BASE_URL)}/api/tracker/outlook/webhook
                    </span>
                    <button
                      onClick={() => {
                        const fullUrl = (API_BASE_URL.startsWith('http') ? API_BASE_URL : window.location.origin + API_BASE_URL) + '/api/tracker/outlook/webhook';
                        navigator.clipboard.writeText(fullUrl);
                        alert('Copied webhook URL to clipboard!');
                      }}
                      className="p-1 rounded hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-500"
                    >
                      <Copy className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>

                <div className="mt-3 flex items-center gap-2 text-xs">
                  <span className="font-semibold text-slate-600 dark:text-slate-400">Subscription Status:</span>
                  <span className={`px-2 py-0.5 rounded font-bold ${
                    outlookStatus?.subscription_active
                      ? 'bg-cyan-50 dark:bg-cyan-950/60 text-cyan-600 dark:text-cyan-400 border border-cyan-200 dark:border-cyan-800'
                      : 'bg-slate-100 text-slate-400'
                  }`}>
                    {outlookStatus?.subscription_active ? `Active (Exp: ${new Date(outlookStatus.subscription_expiration).toLocaleDateString()})` : 'Inactive (Connect Account First)'}
                  </span>
                </div>
              </div>

              <div className="flex flex-col gap-3">
                <button
                  onClick={handleActivateOutlookSubscription}
                  disabled={activatingOutlookSub}
                  className="px-4 py-2.5 rounded-lg bg-cyan-600 hover:bg-cyan-700 text-white font-bold text-xs flex items-center justify-center gap-2 shadow-xs transition-all disabled:opacity-50"
                >
                  <RefreshCw className={`w-4 h-4 ${activatingOutlookSub ? 'animate-spin' : ''}`} />
                  {activatingOutlookSub ? 'Activating / Renewing...' : 'Activate / Renew Graph Webhook Subscription'}
                </button>

                {outlookStatus?.connected && (
                  <div className="pt-3 border-t border-slate-200 dark:border-slate-800 flex flex-col gap-2">
                    <span className="text-[11px] font-bold text-slate-500 uppercase flex items-center gap-1.5">
                      <Mail className="w-3.5 h-3.5 text-blue-500" />
                      Send Verification Email:
                    </span>
                    <div className="flex items-center gap-2">
                      <input
                        type="email"
                        value={testEmailRecipient}
                        onChange={(e) => setTestEmailRecipient(e.target.value)}
                        placeholder="office@rethinkcharity.org.uk"
                        className="flex-1 px-3 py-1.5 text-xs bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-slate-800 dark:text-slate-100"
                      />
                      <button
                        onClick={handleSendTestOutlookEmail}
                        disabled={sendingTestEmail}
                        className="px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-bold text-xs flex items-center gap-1.5 shadow-xs transition-all disabled:opacity-50 whitespace-nowrap"
                      >
                        <Send className="w-3.5 h-3.5" />
                        {sendingTestEmail ? 'Sending...' : 'Send Test Email'}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================= */}
      {/* TAB 5: EMAIL TEMPLATES CONFIGURATION & DESIGNER */}
      {/* ========================================================= */}
      {activeTab === 'templates' && (
        <div className="flex flex-col gap-6">
          {/* Header Card */}
          <div className="bg-white dark:bg-slate-900 p-6 rounded-2xl border border-slate-200/80 dark:border-slate-800 shadow-sm flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
            <div className="flex items-center gap-4">
              <div className="p-4 rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 text-white shadow-lg shadow-indigo-500/20">
                <LayoutTemplate className="w-8 h-8" />
              </div>
              <div>
                <div className="flex items-center gap-2 flex-wrap">
                  <h3 className="text-lg font-black text-slate-800 dark:text-white">
                    Email Templates & Automated Dispatch Designer
                  </h3>
                  <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-purple-50 text-purple-600 dark:bg-purple-950/60 dark:text-purple-400 border border-purple-200 dark:border-purple-800">
                    {activeCompany.toUpperCase()} Workspace
                  </span>
                </div>
                <p className="text-xs md:text-sm text-slate-500 dark:text-slate-400 mt-1">
                  Customize the subject lines, HTML message layout, and placeholder variables for donor emails dispatched via Microsoft 365.
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2.5 w-full md:w-auto">
              <button
                onClick={handleResetDefaultTemplates}
                disabled={savingTemplate}
                className="px-3.5 py-2 rounded-xl border border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-300 font-bold text-xs flex items-center gap-1.5 transition-all"
                title="Restore all factory default templates for this organization"
              >
                <RotateCcw className="w-3.5 h-3.5 text-slate-400" />
                Reset Defaults
              </button>

              <button
                onClick={() => setShowAddTemplateModal(true)}
                className="px-4 py-2 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700 text-white font-bold text-xs flex items-center gap-1.5 shadow-sm transition-all"
              >
                <Plus className="w-4 h-4" />
                + Create Custom Template
              </button>
            </div>
          </div>

          {/* Main 2-Panel Layout: Templates List & Template Editor / Preview */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
            {/* Left Column (4 cols): Template Selector List */}
            <div className="lg:col-span-4 flex flex-col gap-3">
              {/* Charity Theme Switcher */}
              <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200/80 dark:border-slate-800 shadow-sm p-3.5 flex flex-col gap-2.5">
                <div className="flex items-center justify-between px-1">
                  <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">
                    Charity Brand Theme
                  </span>
                  <span className="text-[10px] font-medium text-slate-400">
                    {availableCharityThemes.length} Brand{availableCharityThemes.length > 1 ? 's' : ''} Configured
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  {availableCharityThemes.map((theme) => {
                    const isSelected = selectedCharityTheme === theme.id;
                    return (
                      <button
                        key={theme.id}
                        type="button"
                        onClick={() => {
                          setSelectedCharityTheme(theme.id);
                          const themeTemplates = emailTemplates.filter(t => (t.charity_theme || t.company_id || 'rethink') === theme.id);
                          const matched = themeTemplates.find(t => t.template_type === selectedTemplateForConfig) || themeTemplates[0];
                          if (matched) {
                            setSelectedTemplateForConfig(matched.template_type);
                            setTemplateDraft({
                              id: matched.id,
                              template_type: matched.template_type,
                              subject: matched.subject || '',
                              body_html: matched.body_html || ''
                            });
                          }
                        }}
                        className={`p-2.5 rounded-xl border text-left transition-all flex items-center gap-2.5 ${
                          isSelected
                            ? 'border-indigo-500 bg-indigo-50/80 dark:bg-indigo-950/60 shadow-xs ring-1 ring-indigo-500'
                            : 'border-slate-200/80 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/30 hover:border-slate-300 dark:hover:border-slate-700'
                        }`}
                      >
                        <img
                          src={theme.logo?.startsWith('http') || theme.logo?.startsWith('data:') ? theme.logo : `${(API_BASE_URL || '').replace(/\/+$/, '')}${theme.logo?.startsWith('/') ? '' : '/'}${theme.logo}`}
                          alt={theme.name}
                          className="w-7 h-7 rounded-lg object-contain bg-white p-0.5 border border-slate-200 dark:border-slate-700 shrink-0"
                          onError={(e) => { e.currentTarget.style.display = 'none'; }}
                        />
                        <div className="min-w-0 flex-1">
                          <div className={`text-xs font-bold truncate ${isSelected ? 'text-indigo-950 dark:text-indigo-200' : 'text-slate-800 dark:text-slate-200'}`}>
                            {theme.name}
                          </div>
                          <div className="text-[10px] text-slate-400 truncate">
                            {theme.short_name}
                          </div>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Templates List */}
              <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200/80 dark:border-slate-800 shadow-sm p-4 flex flex-col gap-2">
                {(() => {
                  const filteredTemplates = emailTemplates.filter(
                    (tpl) => (tpl.charity_theme || tpl.company_id || 'rethink') === selectedCharityTheme
                  );
                  return (
                    <>
                      <div className="flex items-center justify-between px-2">
                        <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">
                          {CHARITY_THEMES_PRESETS[selectedCharityTheme]?.name || 'Charity'} Templates ({filteredTemplates.length})
                        </span>
                        <span className="text-[10px] font-mono text-indigo-600 dark:text-indigo-400">
                          {selectedCharityTheme.toUpperCase()}
                        </span>
                      </div>

                      <div className="flex flex-col gap-1.5">
                        {filteredTemplates.length === 0 ? (
                          <div className="p-4 text-center text-xs text-slate-400">
                            No templates found for this charity theme.
                            <button
                              type="button"
                              onClick={handleResetDefaultTemplates}
                              className="mt-2 text-indigo-600 hover:underline block mx-auto text-xs font-semibold"
                            >
                              Seed Default Templates
                            </button>
                          </div>
                        ) : (
                          filteredTemplates.map((tpl) => {
                            const isSelected = selectedTemplateForConfig === tpl.template_type;
                            const isSystemDefault = ['profile_intro', 'video_update', 'end_year_feedback', 'campaign_update', 'allocation_complete', 'cycle_renewal'].includes(tpl.template_type);

                            return (
                              <div
                                key={tpl.id || `${tpl.template_type}-${tpl.company_id}`}
                                onClick={() => {
                                  setSelectedTemplateForConfig(tpl.template_type);
                                  setTemplateDraft({
                                    id: tpl.id,
                                    template_type: tpl.template_type,
                                    subject: tpl.subject || '',
                                    body_html: tpl.body_html || ''
                                  });
                                }}
                                className={`p-3.5 rounded-xl border cursor-pointer transition-all flex flex-col gap-1.5 relative group ${
                                  isSelected
                                    ? 'border-indigo-500 bg-indigo-50/70 dark:bg-indigo-950/50 shadow-sm'
                                    : 'border-slate-200/80 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/30 hover:border-slate-300 dark:hover:border-slate-700'
                                }`}
                              >
                                <div className="flex items-center justify-between">
                                  <span className={`font-mono text-xs font-bold px-2 py-0.5 rounded ${
                                    isSelected
                                      ? 'bg-indigo-600 text-white'
                                      : 'bg-slate-200/70 dark:bg-slate-700 text-slate-700 dark:text-slate-300'
                                  }`}>
                                    {tpl.template_type}
                                  </span>

                                  <div className="flex items-center gap-1.5">
                                    {isSystemDefault ? (
                                      <span className="text-[10px] font-semibold text-slate-400 dark:text-slate-500 bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded-full">
                                        Standard
                                      </span>
                                    ) : (
                                      <span className="text-[10px] font-semibold text-purple-600 dark:text-purple-400 bg-purple-50 dark:bg-purple-950/60 px-2 py-0.5 rounded-full border border-purple-200 dark:border-purple-800">
                                        Custom
                                      </span>
                                    )}

                                    {!isSystemDefault && (
                                      <button
                                        type="button"
                                        onClick={(e) => {
                                          e.stopPropagation();
                                          handleDeleteTemplate(tpl.id);
                                        }}
                                        className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-rose-100 dark:hover:bg-rose-950 text-rose-500 transition-all"
                                        title="Delete this custom template"
                                      >
                                        <Trash2 className="w-3.5 h-3.5" />
                                      </button>
                                    )}
                                  </div>
                                </div>

                                <div className="text-xs font-bold text-slate-800 dark:text-slate-200 truncate mt-0.5">
                                  {tpl.subject || '(No Subject Defined)'}
                                </div>

                                <div className="text-[11px] text-slate-500 dark:text-slate-400 line-clamp-2 leading-relaxed">
                                  {(tpl.body_html || '').replace(/<[^>]*>?/gm, '').trim() || 'No preview text available'}
                                </div>
                              </div>
                            );
                          })
                        )}
                      </div>
                    </>
                  );
                })()}
              </div>

              {/* Dynamic Variables Guide Card */}
              <div className="bg-indigo-50/50 dark:bg-indigo-950/30 rounded-2xl border border-indigo-100 dark:border-indigo-900/50 p-4 flex flex-col gap-2.5 text-xs">
                <div className="flex items-center gap-1.5 text-indigo-900 dark:text-indigo-300 font-bold">
                  <Tag className="w-4 h-4 text-indigo-500" />
                  <span>Dynamic Placeholders</span>
                </div>
                <p className="text-[11px] text-indigo-800/80 dark:text-indigo-300/80 leading-relaxed">
                  Click any variable pill below to copy or insert it directly into your template. Variables will dynamically resolve during donor email dispatch.
                </p>
                <div className="flex flex-wrap gap-1.5 mt-1">
                  {AVAILABLE_VARIABLES.map((v) => (
                    <button
                      key={v.tag}
                      type="button"
                      onClick={() => {
                        setTemplateDraft(prev => ({
                          ...prev,
                          body_html: (prev.body_html || '') + ` ${v.tag} `
                        }));
                      }}
                      className="px-2 py-1 rounded-lg bg-white dark:bg-slate-800 border border-indigo-200 dark:border-indigo-800 font-mono text-[11px] text-indigo-700 dark:text-indigo-300 hover:bg-indigo-600 hover:text-white transition-all shadow-2xs flex items-center gap-1"
                      title={`Example value: ${v.example}`}
                    >
                      <span>{v.tag}</span>
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Right Column (8 cols): Interactive Template Editor & Live Preview */}
            <div className="lg:col-span-8 flex flex-col gap-4">
              <form onSubmit={handleSaveTemplate} className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200/80 dark:border-slate-800 shadow-sm p-5 md:p-6 flex flex-col gap-5">
                {/* Editor Header */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-4 border-b border-slate-100 dark:border-slate-800">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-sm font-black text-indigo-600 dark:text-indigo-400">
                        {templateDraft.template_type}
                      </span>
                      <span className="text-[10px] uppercase font-bold px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-500">
                        Editable Template
                      </span>
                    </div>
                    <span className="text-xs text-slate-400">
                      Changes saved here apply immediately to all future email dispatches.
                    </span>
                  </div>

                  {/* Mode Switcher: Code / Live Preview */}
                  <div className="flex items-center bg-slate-100 dark:bg-slate-800 p-1 rounded-xl border border-slate-200/80 dark:border-slate-700">
                    <button
                      type="button"
                      onClick={() => setTemplateEditorMode('editor')}
                      className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all flex items-center gap-1.5 ${
                        templateEditorMode === 'editor'
                          ? 'bg-white dark:bg-slate-900 text-indigo-600 dark:text-indigo-400 shadow-xs'
                          : 'text-slate-500 hover:text-slate-900 dark:hover:text-white'
                      }`}
                    >
                      <Code className="w-3.5 h-3.5" />
                      HTML / Text Editor
                    </button>
                    <button
                      type="button"
                      onClick={() => setTemplateEditorMode('preview')}
                      className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all flex items-center gap-1.5 ${
                        templateEditorMode === 'preview'
                          ? 'bg-white dark:bg-slate-900 text-indigo-600 dark:text-indigo-400 shadow-xs'
                          : 'text-slate-500 hover:text-slate-900 dark:hover:text-white'
                      }`}
                    >
                      <Eye className="w-3.5 h-3.5" />
                      Live Preview
                    </button>
                  </div>
                </div>

                {/* Email Subject Field */}
                <div className="flex flex-col gap-1.5">
                  <div className="flex items-center justify-between">
                    <label className="font-bold text-xs text-slate-700 dark:text-slate-300 flex items-center gap-1.5">
                      <span>Email Subject Line *</span>
                    </label>
                    <span className="text-[10px] text-slate-400">Supports variable tags like &#123;beneficiary_name&#125;</span>
                  </div>
                  <input
                    type="text"
                    required
                    value={templateDraft.subject}
                    onChange={(e) => setTemplateDraft({ ...templateDraft, subject: e.target.value })}
                    placeholder="e.g. Sponsorship Update: {beneficiary_name}"
                    className="w-full px-3.5 py-2.5 bg-slate-50 dark:bg-slate-800/80 border border-slate-200 dark:border-slate-700 rounded-xl font-bold text-xs md:text-sm text-slate-800 dark:text-white focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 transition-all"
                  />
                </div>

                {/* Dynamic Variable Chips Bar */}
                <div className="flex flex-col gap-1.5 p-3 rounded-xl bg-slate-50 dark:bg-slate-800/50 border border-slate-200/80 dark:border-slate-700">
                  <div className="flex items-center justify-between text-[11px] font-bold text-slate-500">
                    <span>Quick Insert Variable:</span>
                    <span className="font-normal text-[10px] text-slate-400">Click a chip to append into body</span>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {AVAILABLE_VARIABLES.map((v) => (
                      <button
                        key={v.tag}
                        type="button"
                        onClick={() => {
                          setTemplateDraft(prev => ({
                            ...prev,
                            body_html: (prev.body_html || '') + ` ${v.tag} `
                          }));
                        }}
                        className="px-2.5 py-1 rounded-md bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 text-[11px] font-mono font-medium text-slate-700 dark:text-slate-300 hover:border-indigo-500 hover:text-indigo-600 dark:hover:text-indigo-400 transition-all shadow-2xs"
                      >
                        {v.tag}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Editor vs Live Preview Container */}
                {templateEditorMode === 'editor' ? (
                  <div className="flex flex-col gap-1.5">
                    <div className="flex items-center justify-between">
                      <label className="font-bold text-xs text-slate-700 dark:text-slate-300">
                        Email Body (HTML / Structured Content) *
                      </label>
                      <span className="text-[10px] text-slate-400">Standard HTML formatting supported (&lt;p&gt;, &lt;strong&gt;, &lt;a&gt;, &lt;br&gt;)</span>
                    </div>
                    <textarea
                      rows={14}
                      required
                      value={templateDraft.body_html}
                      onChange={(e) => setTemplateDraft({ ...templateDraft, body_html: e.target.value })}
                      placeholder="<p>Dear {donor_name},</p><p>We are pleased to share an update...</p>"
                      className="w-full px-3.5 py-3 bg-slate-950 text-emerald-400 dark:text-emerald-300 font-mono text-xs leading-relaxed border border-slate-800 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 transition-all"
                    />
                  </div>
                ) : (
                  <div className="flex flex-col gap-2">
                    <div className="flex items-center justify-between text-xs text-slate-500">
                      <span className="font-bold">Live Rendered Outlook Inbox Preview</span>
                      <span className="text-[11px] text-emerald-600 dark:text-emerald-400 font-semibold flex items-center gap-1">
                        <Check className="w-3 h-3" /> Variables Evaluated
                      </span>
                    </div>

                    {/* Styled Realistic Email Preview Frame */}
                    <div className="border border-slate-200 dark:border-slate-700 rounded-2xl bg-white dark:bg-slate-950 overflow-hidden shadow-sm flex flex-col">
                      {/* Fake Email Client Header */}
                      <div className="bg-slate-100 dark:bg-slate-900 p-4 border-b border-slate-200 dark:border-slate-800 flex flex-col gap-2 text-xs">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <span className="font-bold text-slate-700 dark:text-slate-300">Subject:</span>
                            <span className="font-bold text-slate-900 dark:text-white">
                              {templateDraft.subject
                                .replace(/{{First_Name}}|{First_Name}/gi, 'Sarah')
                                .replace(/{{donor_name}}|{donor_name}/gi, 'Sarah Ahmed')
                                .replace(/{{beneficiary_name}}|{beneficiary_name}/gi, 'Zayd Al-Mansoor')
                                .replace(/{{sponsorship_type}}|{sponsorship_type}/gi, 'Orphan Sponsorship')
                                .replace(/{{sponsorship_year}}|{sponsorship_year}/gi, 'Year 1')
                                .replace(/{{project_code}}|{project_code}/gi, 'ORPH-2026-089')
                                .replace(/{{location}}|{location}/gi, 'Gaza, Palestine')
                                .replace(/{{campaign_name}}|{campaign_name}/gi, "Jamila's Sponsor an Orphan")
                                .replace(/{{community_name}}|{community_name}/gi, 'Midlands Community')
                              }
                            </span>
                          </div>
                          <span className="text-[10px] text-slate-400">Just now</span>
                        </div>

                        <div className="flex items-center gap-2 text-[11px] text-slate-500">
                          <span>From:</span>
                          <span className="font-mono text-slate-700 dark:text-slate-300">
                            {CHARITY_THEMES_PRESETS[selectedCharityTheme]?.contact_email || 'info@rethinkcharity.org'}
                          </span>
                          <span className="text-slate-300">|</span>
                          <span>To:</span>
                          <span className="font-mono text-slate-700 dark:text-slate-300">sarah.ahmed@example.com</span>
                        </div>
                      </div>

                      {/* Rendered HTML Content */}
                      <iframe
                        title="Email Live Preview"
                        className="w-full h-[550px] border-0 bg-white"
                        srcDoc={
                          (templateDraft.body_html || '')
                            .replace(/{{First_Name}}|{First_Name}/gi, 'Sarah')
                            .replace(/{{donor_name}}|{donor_name}/gi, 'Sarah Ahmed')
                            .replace(/{{Email}}|{Email}|{{recipient_email}}|{recipient_email}/gi, 'sarah.ahmed@example.com')
                            .replace(/{{beneficiary_name}}|{beneficiary_name}/gi, 'Zayd Al-Mansoor')
                            .replace(/{{sponsorship_type}}|{sponsorship_type}/gi, 'Orphan Sponsorship')
                            .replace(/{{sponsorship_year}}|{sponsorship_year}/gi, 'Year 1')
                            .replace(/{{renewal_deadline}}|{renewal_deadline}/gi, '2027-09-21')
                            .replace(/{{days_remaining}}|{days_remaining}/gi, '30 days')
                            .replace(/{{project_code}}|{project_code}/gi, 'ORPH-2026-089')
                            .replace(/{{location}}|{location}/gi, 'Gaza, Palestine')
                            .replace(/{{donor_folder_link}}|{donor_folder_link}/gi, (CHARITY_THEMES_PRESETS[selectedCharityTheme]?.website_url || 'https://rethinkcharity.org') + '/folders/sample-orphan-123')
                            .replace(/{{folder_link}}|{folder_link}/gi, (CHARITY_THEMES_PRESETS[selectedCharityTheme]?.website_url || 'https://rethinkcharity.org') + '/folders/sample-orphan-123')
                            .replace(/{{profile_link}}|{profile_link}/gi, (CHARITY_THEMES_PRESETS[selectedCharityTheme]?.website_url || 'https://rethinkcharity.org') + '/profiles/ORPH-2026-089')
                            .replace(/{{video_link}}|{video_link}/gi, 'https://youtube.com/watch?v=sample_video')
                            .replace(/{{report_link}}|{report_link}/gi, (CHARITY_THEMES_PRESETS[selectedCharityTheme]?.website_url || 'https://rethinkcharity.org') + '/reports/annual-feedback.pdf')
                            .replace(/{{campaign_name}}|{campaign_name}/gi, "Jamila's Sponsor an Orphan")
                            .replace(/{{community_name}}|{community_name}/gi, 'Midlands Community')
                            .replace(/{{Subject}}|{Subject}/gi, templateDraft.subject || 'Sponsorship Update')
                            .replace(/https:\/\/rethink-s-crm\.vercel\.app\/logos\/rethink_logo\.jpg/gi, '/logos/rethink_email_logo.png')
                            .replace(/\/logos\/rethink_logo\.jpg/gi, '/logos/rethink_email_logo.png')
                            .replace(/https:\/\/rethink-s-crm\.vercel\.app\/logos\/iqra_logo\.png/gi, '/logos/iqra_logo.png')
                        }
                      />
                    </div>
                  </div>
                )}

                {/* Footer Controls & Save Button */}
                <div className="flex flex-col sm:flex-row items-center justify-between gap-3 pt-4 border-t border-slate-100 dark:border-slate-800">
                  <div>
                    {templateStatusMsg && (
                      <span className="text-xs font-bold text-emerald-600 dark:text-emerald-400 animate-in fade-in">
                        {templateStatusMsg}
                      </span>
                    )}
                  </div>

                  <div className="flex items-center gap-2.5 w-full sm:w-auto justify-end">
                    <button
                      type="submit"
                      disabled={savingTemplate}
                      className="px-6 py-2.5 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700 disabled:opacity-50 text-white font-bold text-xs flex items-center justify-center gap-2 shadow-sm transition-all"
                    >
                      <Save className="w-4 h-4" />
                      {savingTemplate ? 'Saving Changes...' : 'Save Template Changes'}
                    </button>
                  </div>
                </div>
              </form>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================= */}
      {/* MODAL 1: ADD / EDIT BENEFICIARY */}
      {/* ========================================================= */}
      {showAddBeneficiaryModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs">
          <div className="bg-white dark:bg-slate-900 w-full max-w-lg rounded-2xl border border-slate-200 dark:border-slate-800 shadow-2xl p-6 flex flex-col gap-4 animate-in fade-in zoom-in duration-150">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100 dark:border-slate-800">
              <h3 className="font-bold text-slate-800 dark:text-slate-100 text-base flex items-center gap-2">
                <UserPlus className="w-5 h-5 text-blue-500" />
                {editingBeneficiary ? 'Edit Beneficiary' : 'Add New Beneficiary'}
              </h3>
              <button
                onClick={() => setShowAddBeneficiaryModal(false)}
                className="p-1 rounded-lg text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleSaveBeneficiary} className="flex flex-col gap-3.5 text-xs">
              <div className="grid grid-cols-2 gap-3">
                <div className="flex flex-col gap-1">
                  <label className="font-semibold text-slate-600 dark:text-slate-400">Sponsorship Type *</label>
                  <select
                    value={beneficiaryForm.sponsorship_type}
                    onChange={(e) => setBeneficiaryForm({ ...beneficiaryForm, sponsorship_type: e.target.value })}
                    className="px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg font-bold"
                  >
                    <option value="Orphan">Orphan</option>
                    <option value="Widow">Widow</option>
                    <option value="Ex-Prisoner">Ex-Prisoner</option>
                    <option value="Hafiz">Hafiz</option>
                  </select>
                </div>

                <div className="flex flex-col gap-1">
                  <label className="font-semibold text-slate-600 dark:text-slate-400">Project Code *</label>
                  <input
                    type="text"
                    placeholder="e.g. ORP-GAZ-1042"
                    required
                    value={beneficiaryForm.project_code}
                    onChange={(e) => setBeneficiaryForm({ ...beneficiaryForm, project_code: e.target.value })}
                    className="px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg font-mono font-bold"
                  />
                </div>
              </div>

              <div className="flex flex-col gap-1">
                <label className="font-semibold text-slate-600 dark:text-slate-400">Beneficiary Full Name *</label>
                <input
                  type="text"
                  placeholder="e.g. Amina Khan"
                  required
                  value={beneficiaryForm.name}
                  onChange={(e) => setBeneficiaryForm({ ...beneficiaryForm, name: e.target.value })}
                  className="px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-sm font-bold"
                />
              </div>

              <div className="flex flex-col gap-1">
                <label className="font-semibold text-slate-600 dark:text-slate-400">Location / Country</label>
                <input
                  type="text"
                  placeholder="e.g. Gaza / Rafah, Palestine"
                  value={beneficiaryForm.location}
                  onChange={(e) => setBeneficiaryForm({ ...beneficiaryForm, location: e.target.value })}
                  className="px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg"
                />
              </div>

              <div className="flex flex-col gap-1">
                <label className="font-semibold text-slate-600 dark:text-slate-400">Profile Document / PDF Link (OneDrive / Cloud Link)</label>
                <input
                  type="url"
                  placeholder="https://..."
                  value={beneficiaryForm.profile_link}
                  onChange={(e) => setBeneficiaryForm({ ...beneficiaryForm, profile_link: e.target.value })}
                  className="px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg font-mono text-[11px]"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="flex flex-col gap-1">
                  <label className="font-semibold text-slate-600 dark:text-slate-400">Video Update Link</label>
                  <input
                    type="url"
                    placeholder="https://..."
                    value={beneficiaryForm.video_link}
                    onChange={(e) => setBeneficiaryForm({ ...beneficiaryForm, video_link: e.target.value })}
                    className="px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-[11px]"
                  />
                </div>

                <div className="flex flex-col gap-1">
                  <label className="font-semibold text-slate-600 dark:text-slate-400">Donor Cloud Folder</label>
                  <input
                    type="url"
                    placeholder="https://..."
                    value={beneficiaryForm.donor_folder_link}
                    onChange={(e) => setBeneficiaryForm({ ...beneficiaryForm, donor_folder_link: e.target.value })}
                    className="px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-[11px]"
                  />
                </div>
              </div>

              <div className="flex items-center justify-end gap-2 pt-3 border-t border-slate-100 dark:border-slate-800">
                <button
                  type="button"
                  onClick={() => setShowAddBeneficiaryModal(false)}
                  className="px-4 py-2 rounded-lg text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 font-semibold"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-5 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-bold flex items-center gap-2 shadow-sm"
                >
                  <Save className="w-4 h-4" />
                  {editingBeneficiary ? 'Update Beneficiary' : 'Create Beneficiary'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ========================================================= */}
      {/* MODAL 1B: ADD / EDIT MANUAL SPONSORSHIP DONOR */}
      {/* ========================================================= */}
      {showManualDonorModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs">
          <div className="bg-white dark:bg-slate-900 w-full max-w-lg rounded-2xl border border-slate-200 dark:border-slate-800 shadow-2xl p-6 flex flex-col gap-4 animate-in fade-in zoom-in duration-150">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100 dark:border-slate-800">
              <div className="flex items-center gap-2">
                <div className="p-2 rounded-xl bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400">
                  <UserPlus className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="font-bold text-slate-800 dark:text-slate-100 text-base">
                    {editingManualDonor ? 'Edit Manual Sponsorship Donor' : 'Add Manual Sponsorship Donor'}
                  </h3>
                  <p className="text-[11px] text-slate-500 dark:text-slate-400">
                    Create a donor record for offline / direct sponsorship tracking without allocating upfront.
                  </p>
                </div>
              </div>
              <button
                onClick={() => {
                  setShowManualDonorModal(false);
                  setEditingManualDonor(null);
                }}
                className="p-1 rounded-lg text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleSaveManualDonor} className="flex flex-col gap-3.5 text-xs">
              <div className="grid grid-cols-2 gap-3">
                <div className="flex flex-col gap-1">
                  <label className="font-semibold text-slate-600 dark:text-slate-400">Sponsorship Type *</label>
                  <select
                    value={manualDonorForm.sponsorship_type}
                    onChange={(e) => {
                      const newType = e.target.value;
                      const targetCost = targetInputs[newType] || 480;
                      setManualDonorForm(prev => ({
                        ...prev,
                        sponsorship_type: newType,
                        total_donated: prev.total_donated || targetCost
                      }));
                    }}
                    className="px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg font-bold"
                  >
                    <option value="Orphan">Orphan (£{targetInputs.Orphan || 480})</option>
                    <option value="Hafiz">Hafiz (£{targetInputs.Hafiz || 240})</option>
                    <option value="Widow">Widow (£{targetInputs.Widow || 1080})</option>
                    <option value="Ex-Prisoner">Ex-Prisoner (£{targetInputs['Ex-Prisoner'] || 1080})</option>
                  </select>
                </div>

                <div className="flex flex-col gap-1">
                  <label className="font-semibold text-slate-600 dark:text-slate-400">Donor Full Name *</label>
                  <input
                    type="text"
                    placeholder="e.g. John Doe"
                    required
                    value={manualDonorForm.donor_name}
                    onChange={(e) => setManualDonorForm({ ...manualDonorForm, donor_name: e.target.value })}
                    className="px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg font-bold text-xs"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="flex flex-col gap-1">
                  <label className="font-semibold text-slate-600 dark:text-slate-400">Donor Email Address</label>
                  <input
                    type="email"
                    placeholder="e.g. donor@domain.com"
                    value={manualDonorForm.donor_email}
                    onChange={(e) => setManualDonorForm({ ...manualDonorForm, donor_email: e.target.value })}
                    className="px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg font-mono text-xs"
                  />
                </div>

                <div className="flex flex-col gap-1">
                  <label className="font-semibold text-slate-600 dark:text-slate-400">Donor Phone Number</label>
                  <input
                    type="tel"
                    placeholder="e.g. +44 7123 456789"
                    value={manualDonorForm.donor_phone}
                    onChange={(e) => setManualDonorForm({ ...manualDonorForm, donor_phone: e.target.value })}
                    className="px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg font-mono text-xs"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="flex flex-col gap-1">
                  <label className="font-semibold text-slate-600 dark:text-slate-400">Total Donated / Pledged (£)</label>
                  <input
                    type="number"
                    step="any"
                    placeholder="e.g. 480"
                    value={manualDonorForm.total_donated}
                    onChange={(e) => {
                      const val = parseFloat(e.target.value) || 0;
                      const targetCost = targetInputs[manualDonorForm.sponsorship_type] || 480;
                      const autoSlots = Math.max(1, Math.floor(val / (0.8 * targetCost)));
                      setManualDonorForm(prev => ({
                        ...prev,
                        total_donated: e.target.value,
                        custom_slots: autoSlots
                      }));
                    }}
                    className="px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg font-mono font-bold text-xs"
                  />
                </div>

                <div className="flex flex-col gap-1">
                  <label className="font-semibold text-slate-600 dark:text-slate-400">Allocable Capacity (Slots)</label>
                  <input
                    type="number"
                    min="1"
                    placeholder="e.g. 1"
                    value={manualDonorForm.custom_slots || 1}
                    onChange={(e) => setManualDonorForm({ ...manualDonorForm, custom_slots: parseInt(e.target.value) || 1 })}
                    className="px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg font-mono font-bold text-xs"
                  />
                </div>
              </div>

              <div className="flex flex-col gap-1">
                <label className="font-semibold text-slate-600 dark:text-slate-400">Notes / Payment Reference</label>
                <textarea
                  rows="2"
                  placeholder="e.g. Offline bank transfer ref #59201, 1-year pledge, cash donation..."
                  value={manualDonorForm.notes}
                  onChange={(e) => setManualDonorForm({ ...manualDonorForm, notes: e.target.value })}
                  className="px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-xs"
                />
              </div>

              <div className="flex items-center justify-end gap-2 pt-3 border-t border-slate-100 dark:border-slate-800">
                <button
                  type="button"
                  onClick={() => {
                    setShowManualDonorModal(false);
                    setEditingManualDonor(null);
                  }}
                  className="px-4 py-2 rounded-lg text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 font-semibold"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={savingManualDonor}
                  className="px-5 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white font-bold flex items-center gap-2 shadow-sm disabled:opacity-50"
                >
                  <Save className="w-4 h-4" />
                  {savingManualDonor ? 'Saving...' : editingManualDonor ? 'Update Manual Donor' : 'Create Sponsorship Donor'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ========================================================= */}
      {/* MODAL 2: ZERO-DISK DOCUMENT / PDF / VIDEO MODAL VIEWER */}
      {/* ========================================================= */}
      {previewMedia && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-3 md:p-6 bg-black/75 backdrop-blur-xs">
          <div className="bg-white dark:bg-slate-900 w-full max-w-5xl h-[88vh] rounded-2xl border border-slate-200 dark:border-slate-800 shadow-2xl flex flex-col overflow-hidden animate-in fade-in zoom-in duration-150">
            <div className="flex items-center justify-between px-5 py-3.5 border-b border-slate-200 dark:border-slate-800 bg-slate-50/80 dark:bg-slate-800/50">
              <div className="flex items-center gap-2.5">
                <div className="p-1.5 rounded-lg bg-blue-50 dark:bg-blue-950/60 text-blue-600 dark:text-blue-400">
                  {previewMedia.type === 'pdf' ? <FileText className="w-4 h-4" /> : <Video className="w-4 h-4" />}
                </div>
                <h3 className="font-bold text-slate-800 dark:text-slate-100 text-sm md:text-base truncate max-w-md">
                  {previewMedia.title}
                </h3>
              </div>

              <div className="flex items-center gap-2">
                {previewMedia.rawUrl && (
                  <a
                    href={previewMedia.rawUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="p-1.5 rounded-lg text-slate-500 hover:text-slate-800 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800"
                    title="Open original link"
                  >
                    <ExternalLink className="w-4 h-4" />
                  </a>
                )}
                <button
                  onClick={() => setPreviewMedia(null)}
                  className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
            </div>

            <div className="flex-1 bg-slate-100 dark:bg-slate-950 relative flex flex-col">
              {previewMedia.url && isWebUrl(previewMedia.url) ? (
                <iframe
                  src={previewMedia.url}
                  title={previewMedia.title}
                  className="w-full h-full border-0"
                  allow="autoplay; encrypted-media"
                  allowFullScreen
                />
              ) : (
                <div className="flex-1 flex flex-col items-center justify-center p-8 text-center max-w-md mx-auto gap-4">
                  <div className="w-16 h-16 rounded-2xl bg-amber-50 dark:bg-amber-950/60 border border-amber-200 dark:border-amber-800 flex items-center justify-center text-amber-500 shadow-sm">
                    <FileText className="w-8 h-8" />
                  </div>
                  <div>
                    <h4 className="font-bold text-slate-800 dark:text-slate-100 text-base">
                      Document Filename Reference
                    </h4>
                    <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                      This beneficiary currently lists a local file name rather than an online cloud URL:
                    </p>
                    <div className="mt-2.5 p-3 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl font-mono text-xs font-bold text-slate-800 dark:text-slate-200 break-all select-all shadow-xs">
                      📄 {previewMedia.rawUrl || 'No file reference specified'}
                    </div>
                  </div>
                  <div className="p-3.5 bg-blue-50/80 dark:bg-blue-950/40 border border-blue-200/60 dark:border-blue-800/60 rounded-xl text-xs text-blue-700 dark:text-blue-300 text-left flex items-start gap-2.5">
                    <AlertCircle className="w-4 h-4 shrink-0 mt-0.5 text-blue-600 dark:text-blue-400" />
                    <span>
                      To view and preview this PDF directly inside the browser, edit this beneficiary and paste the live online link (from <strong>SharePoint</strong>, <strong>OneDrive</strong>, or <strong>Google Drive</strong>).
                    </span>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ========================================================= */}
      {/* MODAL 3: MULTI-YEAR ANNUAL FEEDBACK TIMELINE */}
      {/* ========================================================= */}
      {timelineBeneficiary && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs">
          <div className="bg-white dark:bg-slate-900 w-full max-w-2xl max-h-[85vh] rounded-2xl border border-slate-200 dark:border-slate-800 shadow-2xl p-6 flex flex-col gap-4 overflow-hidden animate-in fade-in zoom-in duration-150">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100 dark:border-slate-800">
              <div>
                <h3 className="font-bold text-slate-800 dark:text-slate-100 text-base flex items-center gap-2">
                  <Calendar className="w-5 h-5 text-blue-500" />
                  Multi-Year Progress & Annual Feedback Timeline
                </h3>
                <span className="text-xs text-slate-500">
                  Beneficiary: <strong>{timelineBeneficiary.name}</strong> ({timelineBeneficiary.project_code}) · {timelineBeneficiary.sponsorship_type}
                </span>
              </div>
              <button
                onClick={() => setTimelineBeneficiary(null)}
                className="p-1 rounded-lg text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto pr-1 flex flex-col gap-3.5">
              {loadingFeedbacks ? (
                <div className="py-8 text-center text-slate-400 text-xs">Loading feedbacks...</div>
              ) : feedbacksList.length === 0 ? (
                <div className="py-8 text-center text-slate-400 text-xs">
                  No annual feedback reports logged yet for this beneficiary.
                </div>
              ) : (
                feedbacksList.map((fb) => (
                  <div
                    key={fb.id}
                    className="p-4 rounded-xl border border-slate-200/80 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/30 flex flex-col gap-2.5 shadow-2xs"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-blue-100 dark:bg-blue-950/80 text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-800">
                            🏷️ {fb.year_label || 'Annual Report'}
                          </span>
                          <span className="font-bold text-slate-800 dark:text-slate-100 text-sm">
                            {fb.feedback_title}
                          </span>
                        </div>
                        <span className="text-xs font-mono text-slate-400 mt-1 block">
                          Logged: {fb.feedback_date}
                        </span>
                      </div>

                      <button
                        onClick={() => handleDeleteFeedback(fb.id)}
                        className="text-rose-500 hover:text-rose-700 p-1"
                        title="Delete feedback entry"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>

                    {fb.progress_summary && (
                      <div className="text-xs text-slate-700 dark:text-slate-200 bg-white dark:bg-slate-900 p-3 rounded-lg border border-slate-200/80 dark:border-slate-800">
                        <div className="text-[10px] uppercase font-bold text-slate-400 mb-1">Executive Summary:</div>
                        <p className="whitespace-pre-line">{fb.progress_summary}</p>
                      </div>
                    )}

                    {fb.notes && (
                      <p className="text-xs text-slate-600 dark:text-slate-300 bg-white/60 dark:bg-slate-900/60 p-2.5 rounded-lg border border-slate-200/60 dark:border-slate-800/60">
                        <strong className="text-slate-500 text-[10px] uppercase block mb-0.5">Admin Notes:</strong>
                        {fb.notes}
                      </p>
                    )}

                    <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-slate-200/60 dark:border-slate-800/80">
                      <div className="flex items-center gap-2 flex-wrap">
                        {fb.report_link && (
                          <button
                            onClick={() => setPreviewMedia({ type: 'pdf', url: getEmbeddableDocUrl(fb.report_link), rawUrl: fb.report_link, title: fb.feedback_title })}
                            className="px-2.5 py-1 rounded bg-blue-50 dark:bg-blue-950/60 text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-800 text-[11px] font-bold flex items-center gap-1 hover:bg-blue-100"
                          >
                            <FileText className="w-3 h-3" />
                            View PDF Report
                          </button>
                        )}

                        {fb.video_link && (
                          <button
                            onClick={() => setPreviewMedia({ type: 'video', url: fb.video_link, title: fb.feedback_title })}
                            className="px-2.5 py-1 rounded bg-rose-50 dark:bg-rose-950/60 text-rose-600 dark:text-rose-400 border border-rose-200 dark:border-rose-800 text-[11px] font-bold flex items-center gap-1 hover:bg-rose-100"
                          >
                            <Video className="w-3 h-3" />
                            Watch Video
                          </button>
                        )}

                        {fb.donor_folder_link && (
                          <a
                            href={fb.donor_folder_link}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="px-2.5 py-1 rounded bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800 text-[11px] font-bold flex items-center gap-1 hover:bg-emerald-100"
                          >
                            <Folder className="w-3 h-3" />
                            Media Folder
                          </a>
                        )}
                      </div>

                      {/* Dispatch Action to Donor */}
                      <button
                        onClick={() => {
                          const alloc = allocations.find(a => a.beneficiary_id === timelineBeneficiary.id) || {
                            id: timelineBeneficiary.allocation_id,
                            donor_name: timelineBeneficiary.donor_name,
                            donor_email: timelineBeneficiary.donor_email,
                            beneficiary_name: timelineBeneficiary.name,
                            sponsorship_type: timelineBeneficiary.sponsorship_type,
                            project_code: timelineBeneficiary.project_code,
                            location: timelineBeneficiary.location,
                            donor_folder_link: fb.donor_folder_link || timelineBeneficiary.donor_folder_link,
                            report_link: fb.report_link,
                            video_link: fb.video_link
                          };
                          setTimelineBeneficiary(null);
                          openEmailDispatcher(alloc, 'end_year_feedback');
                        }}
                        className="px-3 py-1 rounded-md bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700 text-white font-bold text-[11px] flex items-center gap-1 shadow-xs transition-all"
                        title="Send this annual feedback directly to the assigned donor via Outlook"
                      >
                        <Send className="w-3 h-3" />
                        Dispatch to Donor
                      </button>
                    </div>
                  </div>
                ))
              )}

              {showAddFeedbackForm ? (
                <form onSubmit={handleAddFeedback} className="p-4 rounded-xl border border-blue-200 dark:border-blue-800/60 bg-blue-50/20 dark:bg-blue-950/20 flex flex-col gap-3 text-xs">
                  <div className="font-bold text-slate-800 dark:text-slate-100 flex items-center gap-1.5">
                    <Sparkles className="w-4 h-4 text-blue-500" />
                    Log New Annual Progress / End-of-Year Report
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                    <input
                      type="text"
                      placeholder="Year Label (e.g. Year 1 - 2026)"
                      required
                      value={feedbackForm.year_label}
                      onChange={(e) => setFeedbackForm({ ...feedbackForm, year_label: e.target.value })}
                      className="px-3 py-2 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg font-bold"
                    />
                    <input
                      type="text"
                      placeholder="Title (e.g. Academic & Wellbeing Report)"
                      required
                      value={feedbackForm.feedback_title}
                      onChange={(e) => setFeedbackForm({ ...feedbackForm, feedback_title: e.target.value })}
                      className="px-3 py-2 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg font-semibold"
                    />
                    <input
                      type="date"
                      required
                      value={feedbackForm.feedback_date}
                      onChange={(e) => setFeedbackForm({ ...feedbackForm, feedback_date: e.target.value })}
                      className="px-3 py-2 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg font-semibold"
                    />
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                    <input
                      type="url"
                      placeholder="Report PDF Document Link"
                      value={feedbackForm.report_link}
                      onChange={(e) => setFeedbackForm({ ...feedbackForm, report_link: e.target.value })}
                      className="px-3 py-2 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg text-[11px]"
                    />
                    <input
                      type="url"
                      placeholder="Video Update Link"
                      value={feedbackForm.video_link}
                      onChange={(e) => setFeedbackForm({ ...feedbackForm, video_link: e.target.value })}
                      className="px-3 py-2 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg text-[11px]"
                    />
                    <input
                      type="url"
                      placeholder="Donor Media Folder Link"
                      value={feedbackForm.donor_folder_link}
                      onChange={(e) => setFeedbackForm({ ...feedbackForm, donor_folder_link: e.target.value })}
                      className="px-3 py-2 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg text-[11px]"
                    />
                  </div>

                  <textarea
                    placeholder="Progress Summary (highlight achievements, health, education, milestones)..."
                    rows={2}
                    value={feedbackForm.progress_summary}
                    onChange={(e) => setFeedbackForm({ ...feedbackForm, progress_summary: e.target.value })}
                    className="px-3 py-2 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg text-xs"
                  />

                  <textarea
                    placeholder="Internal Admin notes (optional)..."
                    rows={2}
                    value={feedbackForm.notes}
                    onChange={(e) => setFeedbackForm({ ...feedbackForm, notes: e.target.value })}
                    className="px-3 py-2 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg text-xs"
                  />

                  <div className="flex items-center justify-end gap-2 pt-1">
                    <button
                      type="button"
                      onClick={() => setShowAddFeedbackForm(false)}
                      className="px-3 py-1.5 rounded-lg text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      className="px-4 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-bold"
                    >
                      Save Report
                    </button>
                  </div>
                </form>
              ) : (
                <button
                  onClick={() => setShowAddFeedbackForm(true)}
                  className="px-4 py-2.5 rounded-xl border-2 border-dashed border-slate-200 dark:border-slate-700 hover:border-blue-400 text-slate-600 dark:text-slate-300 font-bold text-xs flex items-center justify-center gap-2 transition-all"
                >
                  <Plus className="w-4 h-4" />
                  Add Annual Progress / Feedback Report
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ========================================================= */}
      {/* MODAL: EDIT SPONSORSHIP DATES & LIFECYCLE */}
      {/* ========================================================= */}
      {editingDatesAllocation && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs">
          <div className="bg-white dark:bg-slate-900 w-full max-w-md rounded-2xl border border-slate-200 dark:border-slate-800 shadow-2xl p-6 flex flex-col gap-4 animate-in fade-in zoom-in duration-150">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100 dark:border-slate-800">
              <div>
                <h3 className="font-bold text-slate-800 dark:text-slate-100 text-base flex items-center gap-2">
                  <Calendar className="w-5 h-5 text-blue-500" />
                  Edit Sponsorship Dates
                </h3>
                <span className="text-xs text-slate-500">
                  Beneficiary: <strong>{editingDatesAllocation.beneficiary_name}</strong>
                </span>
              </div>
              <button
                onClick={() => setEditingDatesAllocation(null)}
                className="p-1 rounded-lg text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleSaveDates} className="flex flex-col gap-3.5 text-xs">
              <div className="flex flex-col gap-1">
                <label className="font-semibold text-slate-600 dark:text-slate-400">Start Date</label>
                <input
                  type="date"
                  required
                  value={datesForm.start_date}
                  onChange={(e) => setDatesForm({ ...datesForm, start_date: e.target.value })}
                  className="px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg font-bold"
                />
              </div>

              <div className="flex flex-col gap-1">
                <label className="font-semibold text-slate-600 dark:text-slate-400">End Date / Renewal Deadline</label>
                <input
                  type="date"
                  required
                  value={datesForm.end_date}
                  onChange={(e) => setDatesForm({ ...datesForm, end_date: e.target.value })}
                  className="px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg font-bold"
                />
              </div>

              <div className="flex flex-col gap-1">
                <label className="font-semibold text-slate-600 dark:text-slate-400">Renewal Status Override</label>
                <select
                  value={datesForm.renewal_status}
                  onChange={(e) => setDatesForm({ ...datesForm, renewal_status: e.target.value })}
                  className="px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg font-bold"
                >
                  <option value="active">Active (Normal Cycle)</option>
                  <option value="due">Due for Renewal (30-day window)</option>
                  <option value="grace">Grace Period (Past deadline)</option>
                  <option value="lapsed">Lapsed</option>
                  <option value="renewed">Renewed</option>
                </select>
              </div>

              <div className="flex items-center justify-end gap-2 pt-3 border-t border-slate-100 dark:border-slate-800">
                <button
                  type="button"
                  onClick={() => setEditingDatesAllocation(null)}
                  className="px-4 py-2 rounded-lg text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 font-semibold"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-5 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-bold flex items-center gap-2 shadow-sm"
                >
                  <Save className="w-4 h-4" />
                  Save Changes
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ========================================================= */}
      {/* MODAL: EDIT DONOR / CAMPAIGN CONTACT INFO */}
      {/* ========================================================= */}
      {editingContactAllocation && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs">
          <div className="bg-white dark:bg-slate-900 w-full max-w-md rounded-2xl border border-slate-200 dark:border-slate-800 shadow-2xl p-6 flex flex-col gap-4 animate-in fade-in zoom-in duration-150">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100 dark:border-slate-800">
              <div>
                <h3 className="font-bold text-slate-800 dark:text-slate-100 text-base flex items-center gap-2">
                  <Mail className="w-5 h-5 text-blue-500" />
                  Edit Contact Information
                </h3>
                <span className="text-xs text-slate-500">
                  Beneficiary: <strong>{editingContactAllocation.beneficiary_name}</strong>
                </span>
              </div>
              <button
                onClick={() => setEditingContactAllocation(null)}
                className="p-1 rounded-lg text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleSaveContact} className="flex flex-col gap-3.5 text-xs">
              <div className="flex flex-col gap-1">
                <label className="font-semibold text-slate-600 dark:text-slate-400">
                  {editingContactAllocation.allocation_type === 'campaign' ? 'Campaign / Contact Name' : 'Donor Name'}
                </label>
                <input
                  type="text"
                  value={contactForm.donor_name}
                  onChange={(e) => setContactForm({ ...contactForm, donor_name: e.target.value })}
                  placeholder="e.g. John Doe / Campaign Lead"
                  className="px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg font-medium text-slate-800 dark:text-slate-100"
                />
              </div>

              <div className="flex flex-col gap-1">
                <label className="font-semibold text-slate-600 dark:text-slate-400">
                  Email Address <span className="text-blue-500 font-normal">(Unlocks Outlook Email)</span>
                </label>
                <input
                  type="email"
                  value={contactForm.donor_email}
                  onChange={(e) => setContactForm({ ...contactForm, donor_email: e.target.value })}
                  placeholder="e.g. donor@example.com"
                  className="px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg font-mono font-medium text-slate-800 dark:text-slate-100"
                />
              </div>

              <div className="flex flex-col gap-1">
                <label className="font-semibold text-slate-600 dark:text-slate-400">
                  Phone Number
                </label>
                <input
                  type="tel"
                  value={contactForm.donor_phone}
                  onChange={(e) => setContactForm({ ...contactForm, donor_phone: e.target.value })}
                  placeholder="e.g. +44 7123 456789"
                  className="px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg font-mono font-medium text-slate-800 dark:text-slate-100"
                />
              </div>

              <p className="text-[11px] text-slate-500 dark:text-slate-400 bg-blue-50 dark:bg-blue-950/40 border border-blue-100 dark:border-blue-900/40 p-2.5 rounded-lg">
                💡 Adding an email address will instantly unlock the <strong>Outlook Email</strong> dispatch button on this allocation.
              </p>

              <div className="flex items-center justify-end gap-2 pt-3 border-t border-slate-100 dark:border-slate-800">
                <button
                  type="button"
                  onClick={() => setEditingContactAllocation(null)}
                  className="px-4 py-2 rounded-lg text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 font-semibold"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={savingContact}
                  className="px-5 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-bold flex items-center gap-2 shadow-sm cursor-pointer"
                >
                  <Save className="w-4 h-4" />
                  {savingContact ? 'Saving...' : 'Save Contact'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ========================================================= */}
      {/* MODAL 4: ALLOCATION SELECTOR (DONOR OR CAMPAIGN / COMMUNITY) */}
      {/* ========================================================= */}
      {isAllocateModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs">
          <div className="bg-white dark:bg-slate-900 w-full max-w-xl max-h-[92vh] rounded-2xl border border-slate-200 dark:border-slate-800 shadow-2xl p-6 flex flex-col gap-4 overflow-y-auto animate-in fade-in zoom-in duration-150">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100 dark:border-slate-800">
              <div>
                <h3 className="font-bold text-slate-800 dark:text-slate-100 text-base flex items-center gap-2">
                  <UserCheck className="w-5 h-5 text-blue-500" />
                  Allocate Beneficiary
                </h3>
                <span className="text-xs text-slate-500">
                  Assign beneficiary to an individual qualifying donor or a campaign / community.
                </span>
              </div>
              <button
                onClick={() => {
                  setAllocateModalBeneficiary(null);
                  setIsAllocateModalOpen(false);
                }}
                className="p-1 rounded-lg text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* STEP 1: SEARCHABLE BENEFICIARY SELECTOR */}
            <div className="flex flex-col gap-1.5 p-3 rounded-xl bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700 relative" ref={beneficiaryDropdownRef}>
              <div className="flex items-center justify-between">
                <label className="text-xs font-bold text-slate-700 dark:text-slate-300 flex items-center gap-1.5">
                  <UserCheck className="w-4 h-4 text-blue-600 dark:text-blue-400" />
                  Select Beneficiary to Assign:
                </label>
                <span className="text-[11px] font-semibold text-slate-400">
                  {unallocatedBeneficiaries.length} Available
                </span>
              </div>

              {/* Interactive Combobox Trigger Button */}
              <button
                type="button"
                onClick={() => setIsBeneficiaryDropdownOpen(!isBeneficiaryDropdownOpen)}
                className={`w-full px-3 py-2.5 bg-white dark:bg-slate-900 border rounded-xl text-left flex items-center justify-between gap-2 transition-all shadow-xs ${
                  isBeneficiaryDropdownOpen
                    ? 'border-blue-500 ring-2 ring-blue-500/20'
                    : 'border-slate-300 dark:border-slate-600 hover:border-slate-400'
                }`}
              >
                {allocateModalBeneficiary ? (
                  <div className="flex items-center justify-between w-full min-w-0 pr-2">
                    <div className="flex items-center gap-2 truncate">
                      <span className="font-bold text-slate-800 dark:text-slate-100 text-xs truncate">
                        {allocateModalBeneficiary.name}
                      </span>
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-blue-50 dark:bg-blue-950/60 text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-800 shrink-0">
                        {allocateModalBeneficiary.sponsorship_type}
                      </span>
                    </div>
                    <div className="text-[11px] font-mono text-slate-500 dark:text-slate-400 shrink-0">
                      {allocateModalBeneficiary.project_code || 'No Code'} • {allocateModalBeneficiary.location || 'N/A'}
                    </div>
                  </div>
                ) : (
                  <span className="text-slate-400 text-xs font-medium">Click to search & select a beneficiary...</span>
                )}
                <div className="text-slate-400 shrink-0">
                  {isBeneficiaryDropdownOpen ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                </div>
              </button>

              {/* Floating Searchable Beneficiaries Dropdown Menu */}
              {isBeneficiaryDropdownOpen && (
                <div className="absolute top-full left-0 right-0 mt-1.5 z-50 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl shadow-2xl p-2.5 flex flex-col gap-2 animate-in fade-in zoom-in-95 duration-150">
                  {/* Search Input */}
                  <div className="relative">
                    <Search className="w-3.5 h-3.5 absolute left-3 top-2.5 text-slate-400" />
                    <input
                      type="text"
                      autoFocus
                      placeholder="Search beneficiary by name, code (e.g. RT-ORP-ABS...), or location..."
                      value={beneficiarySearchQuery}
                      onChange={(e) => setBeneficiarySearchQuery(e.target.value)}
                      className="w-full pl-8 pr-8 py-1.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-xs text-slate-800 dark:text-slate-100 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-blue-500"
                    />
                    {beneficiarySearchQuery && (
                      <button
                        type="button"
                        onClick={() => setBeneficiarySearchQuery('')}
                        className="absolute right-2.5 top-2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>

                  {/* Type Filter Tabs */}
                  <div className="flex items-center gap-1 overflow-x-auto pb-1 border-b border-slate-100 dark:border-slate-800">
                    {['All', 'Orphan', 'Hafiz', 'Widow', 'Ex-Prisoner'].map((type) => {
                      const count = beneficiaryTypeCounts[type] || 0;
                      return (
                        <button
                          key={type}
                          type="button"
                          onClick={() => setBeneficiaryTypeFilter(type)}
                          className={`px-2 py-0.5 rounded-full text-[10px] font-bold transition-all shrink-0 ${
                            beneficiaryTypeFilter === type
                              ? 'bg-blue-600 text-white shadow-xs'
                              : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200'
                          }`}
                        >
                          {type} ({count})
                        </button>
                      );
                    })}
                  </div>

                  {/* List of Beneficiaries */}
                  <div className="max-h-56 overflow-y-auto flex flex-col gap-1 pr-1">
                    {modalFilteredBeneficiaries.length === 0 ? (
                      <div className="py-6 text-center text-xs text-slate-400">
                        {beneficiarySearchQuery
                          ? `No unallocated beneficiaries match "${beneficiarySearchQuery}"`
                          : 'No unallocated beneficiaries found.'}
                      </div>
                    ) : (
                      modalFilteredBeneficiaries.map((b) => {
                        const isSelected = allocateModalBeneficiary?.id === b.id;
                        return (
                          <div
                            key={b.id}
                            onClick={() => {
                              setAllocateModalBeneficiary(b);
                              setSelectedDonorType(b.sponsorship_type);
                              setIsBeneficiaryDropdownOpen(false);
                            }}
                            className={`p-2 rounded-lg cursor-pointer transition-all flex items-center justify-between gap-2 ${
                              isSelected
                                ? 'bg-blue-50 dark:bg-blue-950/70 border border-blue-200 dark:border-blue-800'
                                : 'hover:bg-slate-50 dark:hover:bg-slate-800/80 border border-transparent'
                            }`}
                          >
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-2">
                                <span className={`font-bold text-xs truncate ${isSelected ? 'text-blue-700 dark:text-blue-300' : 'text-slate-800 dark:text-slate-100'}`}>
                                  {b.name}
                                </span>
                                <span className="px-1.5 py-0.2 rounded text-[9px] font-bold bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300">
                                  {b.sponsorship_type}
                                </span>
                              </div>
                              <div className="text-[10px] text-slate-400 font-mono flex items-center gap-2 mt-0.5">
                                <span>{b.project_code || 'No Code'}</span>
                                <span>•</span>
                                <span>📍 {b.location || 'Unknown'}</span>
                              </div>
                            </div>

                            {isSelected ? (
                              <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-blue-600 text-white flex items-center gap-1 shrink-0">
                                <Check className="w-3 h-3" /> Selected
                              </span>
                            ) : (
                              <span className="text-[10px] text-emerald-600 dark:text-emerald-400 font-semibold shrink-0">
                                Available
                              </span>
                            )}
                          </div>
                        );
                      })
                    )}
                  </div>
                </div>
              )}

              {allocateModalBeneficiary && (
                <div className="flex items-center justify-between text-[11px] text-slate-500 pt-0.5">
                  <span>
                    Type: <strong className="text-slate-700 dark:text-slate-300">{allocateModalBeneficiary.sponsorship_type}</strong>
                  </span>
                  <span>
                    Location: <strong className="text-slate-700 dark:text-slate-300">{allocateModalBeneficiary.location || 'N/A'}</strong>
                  </span>
                  <span>
                    Code: <strong className="font-mono text-slate-700 dark:text-slate-300">{allocateModalBeneficiary.project_code || 'N/A'}</strong>
                  </span>
                </div>
              )}
            </div>

            {/* Mode Switcher: Individual Donor vs Campaign / Community */}
            <div className="flex items-center gap-2 p-1 bg-slate-100 dark:bg-slate-800 rounded-xl">
              <button
                type="button"
                onClick={() => setAllocationMode('donor')}
                className={`flex-1 py-2 rounded-lg font-bold text-xs transition-all flex items-center justify-center gap-1.5 ${
                  allocationMode === 'donor'
                    ? 'bg-white dark:bg-slate-900 text-blue-600 dark:text-blue-400 shadow-xs'
                    : 'text-slate-500 hover:text-slate-800'
                }`}
              >
                <Users className="w-4 h-4" />
                Assign to Individual Donor
              </button>
              <button
                type="button"
                onClick={() => setAllocationMode('campaign')}
                className={`flex-1 py-2 rounded-lg font-bold text-xs transition-all flex items-center justify-center gap-1.5 ${
                  allocationMode === 'campaign'
                    ? 'bg-white dark:bg-slate-900 text-purple-600 dark:text-purple-400 shadow-xs'
                    : 'text-slate-500 hover:text-slate-800'
                }`}
              >
                <Layers className="w-4 h-4" />
                Assign to Campaign / Community
              </button>
            </div>

            {/* MODE 1: INDIVIDUAL DONOR */}
            {allocationMode === 'donor' && (
              <div className="flex flex-col gap-2.5 text-xs">
                {/* Active Selected Donor Banner & Editable Contact Information */}
                {selectedDonorForAllocation && (() => {
                  const isSelectedExceptional = Boolean(
                    selectedDonorForAllocation.remaining_slots <= 0 ||
                    selectedDonorForAllocation.is_exceptional ||
                    selectedDonorForAllocation.status === 'ineligible' ||
                    selectedDonorForAllocation.status === 'over_capacity' ||
                    selectedDonorForAllocation.status === 'at_capacity'
                  );

                  return (
                    <div className="flex flex-col gap-2.5">
                      <div className={`p-3 rounded-xl border-2 flex items-start justify-between gap-3 shadow-xs animate-in fade-in duration-150 ${
                        isSelectedExceptional
                          ? 'bg-amber-50/80 dark:bg-amber-950/40 border-amber-500/70 dark:border-amber-600/70'
                          : 'bg-blue-50 dark:bg-blue-950/40 border-blue-500/60 dark:border-blue-600/60'
                      }`}>
                        <div className="flex items-start gap-2.5 min-w-0">
                          <div className={`p-2 rounded-lg text-white shrink-0 mt-0.5 ${
                            isSelectedExceptional ? 'bg-amber-600' : 'bg-blue-600'
                          }`}>
                            {isSelectedExceptional ? <Zap className="w-4 h-4 fill-white" /> : <UserCheck className="w-4 h-4" />}
                          </div>
                          <div className="min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="font-bold text-slate-800 dark:text-slate-100 text-sm">
                                {selectedDonorForAllocation.donor_name}
                              </span>
                              {isSelectedExceptional ? (
                                <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-600 text-white flex items-center gap-1">
                                  <Zap className="w-2.5 h-2.5 fill-white" /> Exceptional Override
                                </span>
                              ) : (
                                <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-blue-600 text-white flex items-center gap-1">
                                  <Check className="w-3 h-3" /> Selected Donor
                                </span>
                              )}
                            </div>
                            <div className="flex items-center gap-3 text-[11px] text-slate-500 mt-1 flex-wrap">
                              <span className="font-mono">✉️ {selectedDonorForAllocation.donor_email || 'No email in data'}</span>
                              {selectedDonorForAllocation.donor_phone && (
                                <span>📞 {selectedDonorForAllocation.donor_phone}</span>
                              )}
                              <span>💰 For {selectedDonorType}: <strong>£{Number(selectedDonorForAllocation.total_donated || 0).toLocaleString()}</strong></span>
                              {selectedDonorForAllocation.total_lifetime_donated !== undefined && (
                                <span className="text-purple-600 dark:text-purple-400 font-semibold">
                                  🌐 LTV: <strong>£{Number(selectedDonorForAllocation.total_lifetime_donated || 0).toLocaleString()}</strong>
                                </span>
                              )}
                              {selectedDonorForAllocation.remaining_slots > 0 ? (
                                <span className="text-emerald-600 dark:text-emerald-400 font-bold">
                                  {selectedDonorForAllocation.remaining_slots} Slots Available
                                </span>
                              ) : (
                                <span className="text-amber-600 dark:text-amber-400 font-bold">
                                  ⚡ Capacity Reached ({selectedDonorForAllocation.allocated_count || 0}/{selectedDonorForAllocation.max_slots || 0}) • Override Slot
                                </span>
                              )}
                            </div>

                            {isSelectedExceptional && (
                              <div className="mt-2 p-1.5 rounded-md bg-amber-100/70 dark:bg-amber-950/60 border border-amber-300 dark:border-amber-800 text-[11px] text-amber-800 dark:text-amber-300 flex items-start gap-1.5">
                                <AlertCircle className="w-3.5 h-3.5 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
                                <span>
                                  <strong>Admin Override Notice:</strong> This donor has insufficient/at-capacity slots for {selectedDonorType}. Proceeding will assign this beneficiary as an <em>exceptional allocation</em> and record an audit tag.
                                </span>
                              </div>
                            )}
                          </div>
                        </div>
                        <button
                          type="button"
                          onClick={() => handleSelectDonorForAllocation(null)}
                          className="text-[11px] font-bold text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-200 shrink-0 underline cursor-pointer"
                        >
                          Change
                        </button>
                      </div>

                      {/* Editable Contact Information for this Allocation */}
                      <div className="p-3 bg-white dark:bg-slate-900 rounded-xl border border-blue-200 dark:border-blue-900/60 flex flex-col gap-2 shadow-xs">
                        <div className="flex items-center justify-between">
                          <label className="font-bold text-slate-800 dark:text-slate-200 text-xs flex items-center gap-1.5">
                            <Mail className="w-3.5 h-3.5 text-blue-600 dark:text-blue-400" />
                            Donor Contact Details for Allocation
                          </label>
                          <span className="text-[10px] text-slate-400">
                            Default loaded from data • Edit anytime
                          </span>
                        </div>

                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                          <div className="flex flex-col gap-1">
                            <label className="text-[11px] font-semibold text-slate-600 dark:text-slate-400">
                              Contact Email <span className="text-blue-500 font-normal">(Enables Outlook Email)</span>
                            </label>
                            <input
                              type="email"
                              placeholder="e.g. donor@example.com"
                              value={donorContactEmail}
                              onChange={(e) => setDonorContactEmail(e.target.value)}
                              className="px-2.5 py-1.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-xs font-mono text-slate-800 dark:text-slate-100 placeholder-slate-400 focus:ring-1 focus:ring-blue-500 focus:outline-none"
                            />
                          </div>

                          <div className="flex flex-col gap-1">
                            <label className="text-[11px] font-semibold text-slate-600 dark:text-slate-400">
                              Contact Phone
                            </label>
                            <input
                              type="tel"
                              placeholder="e.g. +44 7123 456789"
                              value={donorContactPhone}
                              onChange={(e) => setDonorContactPhone(e.target.value)}
                              className="px-2.5 py-1.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-xs font-mono text-slate-800 dark:text-slate-100 placeholder-slate-400 focus:ring-1 focus:ring-blue-500 focus:outline-none"
                            />
                          </div>
                        </div>

                        <div className="flex flex-col gap-1">
                          <label className="text-[11px] font-semibold text-slate-600 dark:text-slate-400">
                            Donor Display Name
                          </label>
                          <input
                            type="text"
                            placeholder="Donor name"
                            value={donorContactName}
                            onChange={(e) => setDonorContactName(e.target.value)}
                            className="px-2.5 py-1.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-xs font-medium text-slate-800 dark:text-slate-100 placeholder-slate-400 focus:ring-1 focus:ring-blue-500 focus:outline-none"
                          />
                        </div>
                      </div>
                    </div>
                  );
                })()}

                {/* Donor Selection Controls */}
                <div className="flex flex-col gap-2 mt-1">
                  <div className="flex items-center justify-between">
                    <label className="font-bold text-slate-700 dark:text-slate-300 text-xs">
                      {selectedDonorForAllocation ? 'Or Choose Another Donor to Assign:' : 'Select Donor to Assign:'}
                    </label>
                  </div>

                  {/* Donor Source Selection Tabs */}
                  <div className="flex items-center gap-1 p-1 bg-slate-100 dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 text-xs">
                    <button
                      type="button"
                      onClick={() => setModalDonorSourceTab('sponsorship')}
                      className={`flex-1 py-1.5 px-2 rounded-md font-semibold text-[11px] transition-all flex items-center justify-center gap-1.5 ${
                        modalDonorSourceTab === 'sponsorship'
                          ? 'bg-white dark:bg-slate-900 text-blue-600 dark:text-blue-400 shadow-xs font-bold'
                          : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
                      }`}
                    >
                      <Target className="w-3.5 h-3.5" />
                      {selectedDonorType} Donors ({modalFilteredDonors.length})
                    </button>
                    <button
                      type="button"
                      onClick={() => setModalDonorSourceTab('all_crm')}
                      className={`flex-1 py-1.5 px-2 rounded-md font-semibold text-[11px] transition-all flex items-center justify-center gap-1.5 ${
                        modalDonorSourceTab === 'all_crm'
                          ? 'bg-white dark:bg-slate-900 text-purple-600 dark:text-purple-400 shadow-xs font-bold'
                          : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
                      }`}
                    >
                      <Search className="w-3.5 h-3.5" />
                      All CRM Donors (Other Causes)
                    </button>
                    <button
                      type="button"
                      onClick={() => setModalDonorSourceTab('custom')}
                      className={`flex-1 py-1.5 px-2 rounded-md font-semibold text-[11px] transition-all flex items-center justify-center gap-1.5 ${
                        modalDonorSourceTab === 'custom'
                          ? 'bg-white dark:bg-slate-900 text-emerald-600 dark:text-emerald-400 shadow-xs font-bold'
                          : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
                      }`}
                    >
                      <UserPlus className="w-3.5 h-3.5" />
                      Manual Entry
                    </button>
                  </div>

                  {/* TAB 1: SPONSORSHIP DONORS */}
                  {modalDonorSourceTab === 'sponsorship' && (
                    <div className="flex flex-col gap-2">
                      <div className="relative">
                        <Search className="w-3.5 h-3.5 absolute left-3 top-2.5 text-slate-400" />
                        <input
                          type="text"
                          placeholder={`Search ${selectedDonorType} donors by name, email, or phone...`}
                          value={modalDonorSearchQuery}
                          onChange={(e) => setModalDonorSearchQuery(e.target.value)}
                          className="w-full pl-8 pr-8 py-1.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-xs"
                        />
                        {modalDonorSearchQuery && (
                          <button
                            onClick={() => setModalDonorSearchQuery('')}
                            className="absolute right-2.5 top-2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
                          >
                            <X className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </div>

                      <div className="max-h-52 overflow-y-auto flex flex-col gap-2 border border-slate-200 dark:border-slate-700 rounded-xl p-2 bg-slate-50 dark:bg-slate-800/40">
                        {modalFilteredDonors.length === 0 ? (
                          <div className="py-6 text-center text-slate-400">
                            {modalDonorSearchQuery
                              ? 'No donors match your filter.'
                              : `No qualifying donors found for ${selectedDonorType}. Switch to "All CRM Donors" to assign someone from another cause.`}
                          </div>
                        ) : (
                          modalFilteredDonors.map((d) => {
                            const isSelected = selectedDonorForAllocation?.donor_id === d.donor_id;
                            const isOverCapacity = d.allocated_count > d.max_slots;
                            return (
                              <div
                                key={d.donor_id}
                                onClick={() => handleSelectDonorForAllocation(d)}
                                className={`p-2.5 rounded-xl border cursor-pointer transition-all flex items-center justify-between ${
                                  isSelected
                                    ? 'border-blue-600 bg-blue-50/90 dark:bg-blue-950/80 shadow-xs ring-2 ring-blue-500/40'
                                    : 'border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 hover:border-slate-300'
                                }`}
                              >
                                <div>
                                  <div className="font-bold text-slate-800 dark:text-slate-100 flex items-center gap-2">
                                    {d.donor_name}
                                    {isSelected && (
                                      <span className="px-1.5 py-0.2 rounded text-[10px] font-bold bg-blue-600 text-white flex items-center gap-1">
                                        <Check className="w-3 h-3" /> Selected
                                      </span>
                                    )}
                                  </div>
                                  <span className="text-slate-400 font-mono text-[11px] block">{d.donor_email}</span>
                                  {d.donor_phone && (
                                    <span className="text-slate-500 dark:text-slate-400 font-mono text-[11px] flex items-center gap-1 mt-0.5">
                                      <Phone className="w-3 h-3 text-slate-400 shrink-0" />
                                      {d.donor_phone}
                                    </span>
                                  )}
                                </div>

                                <div className="text-right flex flex-col items-end gap-1">
                                  {d.remaining_slots > 0 ? (
                                    <span className="px-2 py-0.5 rounded font-bold bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 text-[10px]">
                                      {d.remaining_slots} Slots Available
                                    </span>
                                  ) : isOverCapacity ? (
                                    <span className="px-2 py-0.5 rounded font-bold bg-amber-50 dark:bg-amber-950/60 text-amber-600 dark:text-amber-400 border border-amber-300 dark:border-amber-800 text-[10px] flex items-center gap-1">
                                      <Zap className="w-2.5 h-2.5" /> Exceptional ({d.allocated_count}/{d.max_slots})
                                    </span>
                                  ) : (
                                    <span className="px-2 py-0.5 rounded font-bold bg-slate-100 dark:bg-slate-800 text-slate-500 text-[10px]">
                                      At Capacity ({d.allocated_count}/{d.max_slots}) • Override
                                    </span>
                                  )}
                                  <div className="text-[11px] font-bold text-slate-700 dark:text-slate-300">
                                    Donated £{Number(d.total_donated || 0).toLocaleString()}
                                  </div>
                                </div>
                              </div>
                            );
                          })
                        )}
                      </div>
                    </div>
                  )}

                  {/* TAB 2: ALL CRM DONORS (OTHER CAUSES) */}
                  {modalDonorSourceTab === 'all_crm' && (
                    <div className="flex flex-col gap-2">
                      <div className="relative">
                        <Search className="w-3.5 h-3.5 absolute left-3 top-2.5 text-purple-500" />
                        <input
                          type="text"
                          placeholder="Search any CRM donor across all causes (e.g. name, email, phone, or ID)..."
                          value={allCrmSearchQuery}
                          onChange={(e) => setAllCrmSearchQuery(e.target.value)}
                          className="w-full pl-8 pr-8 py-1.5 bg-slate-50 dark:bg-slate-800 border border-purple-200 dark:border-purple-800/80 rounded-lg text-xs focus:ring-1 focus:ring-purple-500 focus:outline-none"
                        />
                        {allCrmSearchQuery && (
                          <button
                            onClick={() => setAllCrmSearchQuery('')}
                            className="absolute right-2.5 top-2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
                          >
                            <X className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </div>

                      <div className="max-h-56 overflow-y-auto flex flex-col gap-2 border border-slate-200 dark:border-slate-700 rounded-xl p-2 bg-slate-50 dark:bg-slate-800/40">
                        {isSearchingAllCrm ? (
                          <div className="py-6 text-center text-purple-600 dark:text-purple-400 flex items-center justify-center gap-2">
                            <RefreshCw className="w-4 h-4 animate-spin" />
                            <span>Searching all CRM records...</span>
                          </div>
                        ) : allCrmDonors.length === 0 ? (
                          <div className="py-6 px-4 text-center text-slate-400 text-xs">
                            {allCrmSearchQuery
                              ? 'No donors found across the CRM matching your query.'
                              : 'Type a name, email, or phone to search any donor in the CRM — including donors who contributed towards Masjids, Emergency Relief, or other campaigns.'}
                          </div>
                        ) : (
                          allCrmDonors.map((d) => {
                            const isSelected = selectedDonorForAllocation?.donor_id === d.donor_id;
                            const isOverride = d.remaining_slots <= 0;
                            return (
                              <div
                                key={d.donor_id}
                                onClick={() => handleSelectDonorForAllocation(d)}
                                className={`p-2.5 rounded-xl border cursor-pointer transition-all flex items-start justify-between gap-3 ${
                                  isSelected
                                    ? 'border-purple-600 bg-purple-50/90 dark:bg-purple-950/80 shadow-xs ring-2 ring-purple-500/40'
                                    : 'border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 hover:border-purple-300'
                                }`}
                              >
                                <div className="min-w-0">
                                  <div className="font-bold text-slate-800 dark:text-slate-100 flex items-center gap-2 flex-wrap">
                                    {d.donor_name}
                                    {isSelected && (
                                      <span className="px-1.5 py-0.2 rounded text-[10px] font-bold bg-purple-600 text-white flex items-center gap-1">
                                        <Check className="w-3 h-3" /> Selected
                                      </span>
                                    )}
                                  </div>
                                  <span className="text-slate-400 font-mono text-[11px] block truncate">{d.donor_email}</span>
                                  {d.donor_phone && (
                                    <span className="text-slate-500 dark:text-slate-400 font-mono text-[11px] flex items-center gap-1 mt-0.5">
                                      <Phone className="w-3 h-3 text-slate-400 shrink-0" />
                                      {d.donor_phone}
                                    </span>
                                  )}
                                  {d.causes && d.causes.length > 0 && (
                                    <div className="flex flex-wrap gap-1 mt-1.5">
                                      {d.causes.map((c, idx) => (
                                        <span key={idx} className="px-1.5 py-0.2 bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 rounded text-[9px] font-medium border border-slate-200 dark:border-slate-700">
                                          {c}
                                        </span>
                                      ))}
                                    </div>
                                  )}
                                </div>

                                <div className="text-right flex flex-col items-end gap-1 shrink-0">
                                  <span className="px-2 py-0.5 rounded font-bold bg-purple-50 dark:bg-purple-950/60 text-purple-700 dark:text-purple-300 border border-purple-200/60 dark:border-purple-800/60 text-[10px]">
                                    LTV: £{Number(d.total_lifetime_donated || 0).toLocaleString()}
                                  </span>
                                  {isOverride ? (
                                    <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-amber-50 dark:bg-amber-950/60 text-amber-600 dark:text-amber-400 border border-amber-300 dark:border-amber-800 flex items-center gap-1">
                                      <Zap className="w-2.5 h-2.5" /> Exceptional Override
                                    </span>
                                  ) : (
                                    <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400">
                                      {d.remaining_slots} {selectedDonorType} Slots
                                    </span>
                                  )}
                                  <div className="text-[10px] text-slate-400">
                                    {selectedDonorType}: £{Number(d.total_donated || 0).toLocaleString()}
                                  </div>
                                </div>
                              </div>
                            );
                          })
                        )}
                      </div>
                    </div>
                  )}

                  {/* TAB 3: MANUAL / CUSTOM ENTRY */}
                  {modalDonorSourceTab === 'custom' && (
                    <div className="p-3 bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-700 flex flex-col gap-2.5 shadow-xs">
                      <div className="text-xs text-slate-600 dark:text-slate-300 font-medium">
                        Assign this beneficiary directly by entering the recipient donor details below. This will be recorded as an exceptional allocation.
                      </div>

                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                        <div className="flex flex-col gap-1">
                          <label className="text-[11px] font-semibold text-slate-600 dark:text-slate-400">
                            Donor Email Address
                          </label>
                          <input
                            type="email"
                            placeholder="e.g. donor@domain.com"
                            value={donorContactEmail}
                            onChange={(e) => setDonorContactEmail(e.target.value)}
                            className="px-2.5 py-1.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-xs font-mono"
                          />
                        </div>

                        <div className="flex flex-col gap-1">
                          <label className="text-[11px] font-semibold text-slate-600 dark:text-slate-400">
                            Donor Phone Number
                          </label>
                          <input
                            type="tel"
                            placeholder="e.g. +44 7123 456789"
                            value={donorContactPhone}
                            onChange={(e) => setDonorContactPhone(e.target.value)}
                            className="px-2.5 py-1.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-xs font-mono"
                          />
                        </div>
                      </div>

                      <div className="flex flex-col gap-1">
                        <label className="text-[11px] font-semibold text-slate-600 dark:text-slate-400">
                          Donor Full Name
                        </label>
                        <input
                          type="text"
                          placeholder="e.g. John Doe"
                          value={donorContactName}
                          onChange={(e) => setDonorContactName(e.target.value)}
                          className="px-2.5 py-1.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-xs font-medium"
                        />
                      </div>

                      <button
                        type="button"
                        onClick={() => {
                          if (!donorContactEmail.trim() && !donorContactPhone.trim()) {
                            alert('Please provide at least an email or phone number for the custom donor.');
                            return;
                          }
                          handleSelectDonorForAllocation({
                            donor_id: donorContactEmail.trim() || donorContactPhone.trim(),
                            donor_name: donorContactName.trim() || 'Custom Donor',
                            donor_email: donorContactEmail.trim(),
                            donor_phone: donorContactPhone.trim(),
                            total_donated: 0,
                            total_lifetime_donated: 0,
                            target_amount: allocateModalBeneficiary?.target_amount || 480,
                            max_slots: 0,
                            allocated_count: 0,
                            remaining_slots: 0,
                            is_exceptional: true,
                            status: 'exceptional'
                          });
                        }}
                        className="mt-1 py-2 px-3 bg-emerald-600 hover:bg-emerald-700 text-white font-bold rounded-lg text-xs transition-all flex items-center justify-center gap-1.5 shadow-xs"
                      >
                        <Check className="w-3.5 h-3.5" />
                        Apply Custom Donor Details
                      </button>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* MODE 2: CAMPAIGN / COMMUNITY */}
            {allocationMode === 'campaign' && (
              <div className="flex flex-col gap-3 text-xs">
                {/* Active Selected Campaign Banner (when one is already selected) */}
                {selectedCampaignForAllocation && !isCustomCampaign && (
                  <div className="p-3 bg-purple-50 dark:bg-purple-950/40 rounded-xl border-2 border-purple-500/60 dark:border-purple-600/60 flex items-start justify-between gap-3 shadow-xs animate-in fade-in duration-150">
                    <div className="flex items-start gap-2.5 min-w-0">
                      <div className="p-2 rounded-lg bg-purple-600 text-white shrink-0 mt-0.5">
                        <Layers className="w-4 h-4" />
                      </div>
                      <div className="min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-bold text-slate-800 dark:text-slate-100 text-sm">
                            {selectedCampaignForAllocation.campaign_name}
                          </span>
                          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-purple-600 text-white flex items-center gap-1">
                            <Check className="w-3 h-3" /> Pre-Selected Campaign
                          </span>
                        </div>
                        {selectedCampaignForAllocation.community_name && (
                          <div className="text-[11px] font-medium text-purple-700 dark:text-purple-300 mt-0.5">
                            🏛️ Community: {selectedCampaignForAllocation.community_name}
                          </div>
                        )}
                        <div className="flex items-center gap-3 text-[11px] text-slate-500 mt-1 flex-wrap">
                          {selectedCampaignForAllocation.organizer_email && (
                            <span className="font-mono">✉️ {selectedCampaignForAllocation.organizer_email}</span>
                          )}
                          <span>💰 Raised: <strong>£{Number(selectedCampaignForAllocation.total_raised || 0).toLocaleString()}</strong></span>
                          <span className="text-emerald-600 dark:text-emerald-400 font-bold">
                            {selectedCampaignForAllocation.remaining_slots > 0 ? `${selectedCampaignForAllocation.remaining_slots} Slots Available` : 'Direct Allocation'}
                          </span>
                        </div>
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => setSelectedCampaignForAllocation(null)}
                      className="text-[11px] font-bold text-purple-600 dark:text-purple-400 hover:text-purple-800 dark:hover:text-purple-200 shrink-0 underline"
                    >
                      Change
                    </button>
                  </div>
                )}

                {/* Existing vs Custom Campaign Sub-Toggle */}
                <div className="flex items-center justify-between">
                  <label className="font-bold text-slate-700 dark:text-slate-300">
                    {isCustomCampaign
                      ? 'Enter Custom Campaign Details:'
                      : selectedCampaignForAllocation
                        ? 'Or Choose Another Campaign from Database:'
                        : 'Select Campaign from Database:'}
                  </label>
                  <button
                    type="button"
                    onClick={() => {
                      setIsCustomCampaign(!isCustomCampaign);
                      setSelectedCampaignForAllocation(null);
                    }}
                    className="text-purple-600 dark:text-purple-400 font-bold hover:underline text-[11px]"
                  >
                    {isCustomCampaign ? '← Choose Existing Campaign' : '+ Or Enter Custom Campaign'}
                  </button>
                </div>

                {!isCustomCampaign ? (
                  <div className="flex flex-col gap-2">
                    <div className="relative">
                      <Search className="w-3.5 h-3.5 absolute left-3 top-2.5 text-slate-400" />
                      <input
                        type="text"
                        placeholder="Search campaigns (e.g. Jamila, Project 100 Smiles)..."
                        value={campaignSearchQuery}
                        onChange={(e) => setCampaignSearchQuery(e.target.value)}
                        className="w-full pl-8 pr-3 py-1.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-xs"
                      />
                    </div>

                    <div className="max-h-52 overflow-y-auto flex flex-col gap-2 border border-slate-200 dark:border-slate-700 rounded-xl p-2 bg-slate-50 dark:bg-slate-800/40">
                      {qualifyingCampaigns
                        .filter(c => !campaignSearchQuery || c.campaign_name.toLowerCase().includes(campaignSearchQuery.toLowerCase()) || (c.community_name && c.community_name.toLowerCase().includes(campaignSearchQuery.toLowerCase())))
                        .length === 0 ? (
                        <div className="py-6 text-center text-slate-400">
                          No matching campaigns found. Try typing a custom campaign name above.
                        </div>
                      ) : (
                        qualifyingCampaigns
                          .filter(c => !campaignSearchQuery || c.campaign_name.toLowerCase().includes(campaignSearchQuery.toLowerCase()) || (c.community_name && c.community_name.toLowerCase().includes(campaignSearchQuery.toLowerCase())))
                          .map((c, idx) => {
                            const isSelected = selectedCampaignForAllocation?.campaign_name === c.campaign_name;
                            return (
                              <div
                                key={idx}
                                onClick={() => {
                                  setSelectedCampaignForAllocation(c);
                                  if (c.organizer_email) setCampaignContactEmail(c.organizer_email);
                                  if (c.organizer_name) setCampaignContactName(c.organizer_name);
                                }}
                                className={`p-3 rounded-xl border cursor-pointer transition-all flex items-center justify-between ${
                                  isSelected
                                    ? 'border-purple-600 bg-purple-50/90 dark:bg-purple-950/80 shadow-xs ring-2 ring-purple-500/40'
                                    : 'border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 hover:border-slate-300'
                                }`}
                              >
                                <div>
                                  <div className="font-bold text-slate-800 dark:text-slate-100 flex items-center gap-1.5 flex-wrap">
                                    🏷️ {c.campaign_name}
                                    {isSelected && (
                                      <span className="px-1.5 py-0.2 rounded text-[10px] font-bold bg-purple-600 text-white flex items-center gap-1">
                                        <Check className="w-3 h-3" /> Selected
                                      </span>
                                    )}
                                  </div>
                                  {c.community_name && (
                                    <span className="text-[10px] text-purple-600 dark:text-purple-400 font-semibold">
                                      🏛️ {c.community_name}
                                    </span>
                                  )}
                                  {c.organizer_email && (
                                    <div className="text-[10px] text-slate-400 font-mono">
                                      ✉️ {c.organizer_email}
                                    </div>
                                  )}
                                </div>

                                <div className="text-right shrink-0">
                                  <span className={`px-2 py-0.5 rounded font-bold text-[10px] ${
                                    c.remaining_slots > 0
                                      ? 'bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400'
                                      : 'bg-slate-100 dark:bg-slate-800 text-slate-400'
                                  }`}>
                                    {c.remaining_slots > 0 ? `${c.remaining_slots} Slots Available` : 'Direct Allocation'}
                                  </span>
                                  <div className="text-[11px] font-bold text-slate-700 dark:text-slate-300 mt-1">
                                    Raised £{c.total_raised.toLocaleString()}
                                  </div>
                                </div>
                              </div>
                            );
                          })
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="flex flex-col gap-2">
                    <div>
                      <label className="font-semibold text-slate-600 dark:text-slate-400">Campaign Name *</label>
                      <input
                        type="text"
                        placeholder="e.g. Jamila's Sponsor an Orphan"
                        value={customCampaignName}
                        onChange={(e) => setCustomCampaignName(e.target.value)}
                        className="w-full px-3 py-2 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-xs mt-1"
                      />
                    </div>
                    <div>
                      <label className="font-semibold text-slate-600 dark:text-slate-400">Community Name (Optional)</label>
                      <input
                        type="text"
                        placeholder="e.g. Greater London Community"
                        value={campaignCommunityName}
                        onChange={(e) => setCampaignCommunityName(e.target.value)}
                        className="w-full px-3 py-2 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-xs mt-1"
                      />
                    </div>
                  </div>
                )}

                {/* Contact Emails, Phone & Organizer Name */}
                <div className="p-3.5 bg-purple-50/60 dark:bg-purple-950/30 rounded-xl border border-purple-200/80 dark:border-purple-900/60 flex flex-col gap-3 mt-1">
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-purple-950 dark:text-purple-200 text-xs flex items-center gap-1.5">
                      <Users className="w-3.5 h-3.5 text-purple-600 dark:text-purple-400" />
                      Recipient Contact Information
                    </span>
                    {(campaignContactEmail || campaignContactPhone || campaignContactName) && (
                      <button
                        type="button"
                        onClick={() => {
                          setCampaignContactEmail('');
                          setCampaignContactPhone('');
                          setCampaignContactName('');
                        }}
                        className="text-[10px] text-purple-600 dark:text-purple-400 hover:underline font-semibold"
                      >
                        Clear Contacts
                      </button>
                    )}
                  </div>

                  {/* Validation status badge */}
                  <div className="flex items-center gap-1.5 text-[11px]">
                    {campaignContactEmail.trim() || campaignContactPhone.trim() ? (
                      <span className="text-emerald-600 dark:text-emerald-400 font-bold flex items-center gap-1">
                        <Check className="w-3 h-3" /> Contact method provided (Email / Phone)
                      </span>
                    ) : (
                      <span className="text-amber-600 dark:text-amber-400 font-bold flex items-center gap-1">
                        <AlertCircle className="w-3.5 h-3.5" /> At least one required (Email or Phone Number) *
                      </span>
                    )}
                  </div>

                  {/* Email Input */}
                  <div>
                    <label className="font-semibold text-purple-900 dark:text-purple-300 flex items-center justify-between text-xs">
                      <span>Recipient Contact Email(s) {!campaignContactPhone.trim() && <strong className="text-rose-500">*</strong>}</span>
                      <span className="text-[10px] font-normal text-purple-600 dark:text-purple-400">Comma-separated for multiple</span>
                    </label>
                    <input
                      type="text"
                      placeholder="e.g. jamila@org.com, team@org.com"
                      value={campaignContactEmail}
                      onChange={(e) => setCampaignContactEmail(e.target.value)}
                      className="w-full px-3 py-2 bg-white dark:bg-slate-900 border border-purple-200 dark:border-purple-800 rounded-lg text-xs font-mono mt-1 focus:ring-1 focus:ring-purple-500 focus:outline-none"
                    />
                  </div>

                  {/* Phone Input */}
                  <div>
                    <label className="font-semibold text-purple-900 dark:text-purple-300 flex items-center justify-between text-xs">
                      <span>Recipient Contact Phone Number(s) {!campaignContactEmail.trim() && <strong className="text-rose-500">*</strong>}</span>
                      <span className="text-[10px] font-normal text-purple-600 dark:text-purple-400">Comma-separated for multiple</span>
                    </label>
                    <input
                      type="text"
                      placeholder="e.g. +44 7123 456789, +44 7987 654321"
                      value={campaignContactPhone}
                      onChange={(e) => setCampaignContactPhone(e.target.value)}
                      className="w-full px-3 py-2 bg-white dark:bg-slate-900 border border-purple-200 dark:border-purple-800 rounded-lg text-xs font-mono mt-1 focus:ring-1 focus:ring-purple-500 focus:outline-none"
                    />
                  </div>

                  {/* Organizer Name */}
                  <div>
                    <label className="font-semibold text-purple-900 dark:text-purple-300 text-xs">
                      Contact / Organizer Name (Optional)
                    </label>
                    <input
                      type="text"
                      placeholder="e.g. Jamila (Campaign Lead)"
                      value={campaignContactName}
                      onChange={(e) => setCampaignContactName(e.target.value)}
                      className="w-full px-3 py-2 bg-white dark:bg-slate-900 border border-purple-200 dark:border-purple-800 rounded-lg text-xs mt-1 focus:ring-1 focus:ring-purple-500 focus:outline-none"
                    />
                  </div>

                  <span className="text-[10px] text-slate-500 dark:text-slate-400 block pt-0.5">
                    Introduction profiles and feedback reports will be delivered to the specified email / phone contacts.
                  </span>
                </div>
              </div>
            )}

            {/* Notes & Actions */}
            <div className="flex flex-col gap-1 mt-1 text-xs">
              <label className="font-semibold text-slate-600 dark:text-slate-400">Internal Admin Notes (Optional)</label>
              <input
                type="text"
                placeholder="e.g. Allocated via campaign funds raised in Ramadan"
                value={allocationNotes}
                onChange={(e) => setAllocationNotes(e.target.value)}
                className="px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-xs"
              />
            </div>

            <div className="flex items-center justify-end gap-2 pt-3 border-t border-slate-100 dark:border-slate-800">
              <button
                type="button"
                onClick={() => {
                  setAllocateModalBeneficiary(null);
                  setIsAllocateModalOpen(false);
                }}
                className="px-4 py-2 rounded-lg text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 font-semibold text-xs"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={
                  !allocateModalBeneficiary ||
                  (allocationMode === 'donor'
                    ? !selectedDonorForAllocation
                    : (!campaignContactEmail.trim() && !campaignContactPhone.trim()) || (!isCustomCampaign && !selectedCampaignForAllocation) || (isCustomCampaign && !customCampaignName.trim()))
                }
                onClick={handleConfirmAllocation}
                className="px-5 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-bold text-xs flex items-center gap-2 shadow-sm"
              >
                <Check className="w-4 h-4" />
                Confirm Allocation
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================= */}
      {/* MODAL 5: MICROSOFT 365 / OUTLOOK EMAIL DISPATCHER */}
      {/* ========================================================= */}
      {emailModalAllocation && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs">
          <div className="bg-white dark:bg-slate-900 w-full max-w-2xl max-h-[90vh] rounded-2xl border border-slate-200 dark:border-slate-800 shadow-2xl p-6 flex flex-col gap-4 overflow-hidden animate-in fade-in zoom-in duration-150">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100 dark:border-slate-800">
              <div className="flex items-center gap-2.5">
                <div className="p-2 rounded-lg bg-blue-50 dark:bg-blue-950/60 text-blue-600 dark:text-blue-400">
                  <Mail className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="font-bold text-slate-800 dark:text-slate-100 text-base">
                    Compose & Dispatch via Microsoft 365 / Outlook
                  </h3>
                  <span className="text-xs text-slate-400">
                    Recipient: <strong>{emailDraft.recipient_name}</strong> ({emailDraft.recipient_email})
                  </span>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <div className="flex items-center gap-1 bg-slate-100 dark:bg-slate-800 p-0.5 rounded-lg border border-slate-200 dark:border-slate-700">
                  <button
                    type="button"
                    onClick={() => setEmailModalTab('edit')}
                    className={`px-2.5 py-1 rounded-md text-[11px] font-bold flex items-center gap-1 transition-all ${
                      emailModalTab === 'edit'
                        ? 'bg-white dark:bg-slate-900 text-blue-600 dark:text-blue-400 shadow-2xs'
                        : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
                    }`}
                  >
                    <Code className="w-3.5 h-3.5" />
                    HTML Editor
                  </button>
                  <button
                    type="button"
                    onClick={() => setEmailModalTab('preview')}
                    className={`px-2.5 py-1 rounded-md text-[11px] font-bold flex items-center gap-1 transition-all ${
                      emailModalTab === 'preview'
                        ? 'bg-white dark:bg-slate-900 text-blue-600 dark:text-blue-400 shadow-2xs'
                        : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
                    }`}
                  >
                    <Eye className="w-3.5 h-3.5" />
                    Live Branded Preview
                  </button>
                </div>

                <button
                  onClick={() => setEmailModalAllocation(null)}
                  className="p-1 rounded-lg text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
            </div>

            <div className="flex flex-col gap-3.5 text-xs overflow-y-auto pr-1">
              {/* Charity Theme Switcher in Modal */}
              <div className="flex items-center gap-2 p-2 bg-slate-50 dark:bg-slate-800/50 rounded-xl border border-slate-200/80 dark:border-slate-700">
                <span className="font-bold text-slate-500 uppercase text-[10px] shrink-0">Charity Theme:</span>
                <div className="flex items-center gap-1.5 flex-wrap">
                  {availableCharityThemes.map((theme) => {
                    const isSelected = selectedModalTheme === theme.id;
                    return (
                      <button
                        key={theme.id}
                        type="button"
                        onClick={() => handleSwitchModalTheme(theme.id)}
                        className={`px-2.5 py-1 rounded-lg text-xs font-bold flex items-center gap-1.5 transition-all ${
                          isSelected
                            ? 'bg-blue-600 text-white shadow-xs'
                            : 'bg-white dark:bg-slate-900 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700 hover:border-slate-300'
                        }`}
                      >
                        <img
                          src={theme.logo}
                          alt={theme.name}
                          className="w-3.5 h-3.5 rounded object-contain bg-white shrink-0"
                          onError={(e) => { e.target.style.display = 'none'; }}
                        />
                        <span>{theme.name}</span>
                      </button>
                    );
                  })}
                </div>
              </div>

              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-bold text-slate-500 uppercase text-[10px]">Template:</span>
                {emailTemplates
                  .filter((tpl) => (tpl.charity_theme || tpl.company_id || 'rethink') === selectedModalTheme)
                  .map((tpl) => (
                    <button
                      key={tpl.id || tpl.template_type}
                      type="button"
                      onClick={() => openEmailDispatcher(emailModalAllocation, tpl.template_type)}
                      className={`px-3 py-1 rounded-md font-bold text-xs transition-all ${
                        selectedTemplateType === tpl.template_type
                          ? 'bg-blue-600 text-white shadow-xs'
                          : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200'
                      }`}
                    >
                      {tpl.template_type}
                    </button>
                  ))}
              </div>

              <div className="flex flex-col gap-1">
                <label className="font-semibold text-slate-600 dark:text-slate-400">Subject</label>
                <input
                  type="text"
                  value={emailDraft.subject}
                  onChange={(e) => setEmailDraft({ ...emailDraft, subject: e.target.value })}
                  className="px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg font-bold text-sm"
                />
              </div>

              {emailModalTab === 'preview' ? (
                <div className="flex flex-col gap-1.5">
                  <label className="font-semibold text-slate-600 dark:text-slate-400 flex items-center justify-between">
                    <span>Live Branded Email Preview (Recipient View):</span>
                    <span className="text-[10px] text-emerald-600 font-bold">
                      {CHARITY_THEMES_PRESETS[selectedModalTheme]?.name || 'Charity'} Responsive Layout
                    </span>
                  </label>
                  <div className="border border-slate-200 dark:border-slate-700 rounded-xl overflow-hidden bg-white shadow-sm">
                    <iframe
                      title="Recipient Email Preview"
                      className="w-full h-[420px] border-0 bg-white"
                      srcDoc={
                        (emailDraft.body_html || '<p style="padding:20px;text-align:center;color:#666;">No content</p>')
                          .replace(/https:\/\/rethink-s-crm\.vercel\.app\/logos\/rethink_logo\.jpg/gi, '/logos/rethink_email_logo.png')
                          .replace(/\/logos\/rethink_logo\.jpg/gi, '/logos/rethink_email_logo.png')
                          .replace(/https:\/\/rethink-s-crm\.vercel\.app\/logos\/iqra_logo\.png/gi, '/logos/iqra_logo.png')
                          .replace(/data:image\/[^;]+;base64,[^"'\s>]+/gi, '/logos/rethink_email_logo.png')
                      }
                    />
                  </div>
                </div>
              ) : (
                <>
                  {/* Variable Chips in Modal */}
                  <div className="flex flex-col gap-1 p-2.5 rounded-lg bg-slate-50 dark:bg-slate-800/40 border border-slate-200/80 dark:border-slate-700">
                    <span className="text-[10px] font-bold text-slate-400">Quick Insert Variable Tag:</span>
                    <div className="flex flex-wrap gap-1">
                      {AVAILABLE_VARIABLES.map((v) => (
                        <button
                          key={v.tag}
                          type="button"
                          onClick={() => {
                            setEmailDraft(prev => ({
                              ...prev,
                              body_html: (prev.body_html || '') + ` ${v.tag} `
                            }));
                          }}
                          className="px-2 py-0.5 rounded bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 text-[10px] font-mono text-slate-600 dark:text-slate-300 hover:border-blue-500 hover:text-blue-600"
                          title={`Example value: ${v.example}`}
                        >
                          {v.tag}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="flex flex-col gap-1">
                    <label className="font-semibold text-slate-600 dark:text-slate-400">Email Body (HTML / Formatted)</label>
                    <textarea
                      rows={9}
                      value={emailDraft.body_html}
                      onChange={(e) => setEmailDraft({ ...emailDraft, body_html: e.target.value })}
                      className="px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg font-mono text-xs leading-relaxed"
                    />
                  </div>
                </>
              )}

              {/* Exact Email Delivery & Open Tracking Notification */}
              <div className="flex items-center gap-2 p-2.5 rounded-lg bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800/60 text-emerald-800 dark:text-emerald-300 text-xs">
                <Eye className="w-4 h-4 text-emerald-600 dark:text-emerald-400 shrink-0" />
                <span>
                  <strong>Exact Tracking Active:</strong> A secure 1x1 read receipt pixel will be embedded automatically. Delivery, open timestamps, and read counts will be tracked in real-time.
                </span>
              </div>

              <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3 pt-3 border-t border-slate-100 dark:border-slate-800">
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={handleSaveModalDraftAsDefault}
                    className="text-[11px] text-indigo-600 dark:text-indigo-400 hover:underline font-semibold flex items-center gap-1"
                    title="Save your current text as default for this template type"
                  >
                    <Save className="w-3.5 h-3.5" />
                    Save Edits as Template Default
                  </button>
                </div>

                <div className="flex items-center gap-2 justify-end">
                  <button
                    type="button"
                    onClick={() => setEmailModalAllocation(null)}
                    className="px-4 py-2 rounded-lg text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 font-semibold"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    disabled={sendingEmail}
                    onClick={handleSendOutlookEmail}
                    className="px-5 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-bold flex items-center gap-2 shadow-sm"
                  >
                    <Send className="w-4 h-4" />
                    {sendingEmail ? 'Sending via Outlook...' : 'Send Email Now'}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================= */}
      {/* MODAL 7: CREATE NEW CUSTOM TEMPLATE */}
      {/* ========================================================= */}
      {showAddTemplateModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs">
          <div className="bg-white dark:bg-slate-900 w-full max-w-lg rounded-2xl border border-slate-200 dark:border-slate-800 shadow-2xl p-6 flex flex-col gap-4 animate-in fade-in zoom-in duration-150">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100 dark:border-slate-800">
              <h3 className="font-bold text-slate-800 dark:text-slate-100 text-base flex items-center gap-2">
                <Plus className="w-5 h-5 text-indigo-500" />
                Create New Email Template
              </h3>
              <button
                onClick={() => setShowAddTemplateModal(false)}
                className="p-1 rounded-lg text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleCreateCustomTemplate} className="flex flex-col gap-3.5 text-xs">
              <div className="flex flex-col gap-1">
                <label className="font-semibold text-slate-600 dark:text-slate-400">Template Key / Identifier *</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. quarterly_update or eid_greetings"
                  value={newTemplateForm.template_type}
                  onChange={(e) => setNewTemplateForm({ ...newTemplateForm, template_type: e.target.value })}
                  className="px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg font-mono font-bold"
                />
                <span className="text-[10px] text-slate-400">Lowercase letters, numbers, and underscores only.</span>
              </div>

              <div className="flex flex-col gap-1">
                <label className="font-semibold text-slate-600 dark:text-slate-400">Default Subject Line *</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Quarterly Update: {beneficiary_name}"
                  value={newTemplateForm.subject}
                  onChange={(e) => setNewTemplateForm({ ...newTemplateForm, subject: e.target.value })}
                  className="px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg font-bold"
                />
              </div>

              <div className="flex flex-col gap-1">
                <label className="font-semibold text-slate-600 dark:text-slate-400">Default HTML Body Content</label>
                <textarea
                  rows={5}
                  placeholder="<p>Dear {donor_name},</p><p>We are delighted to share an update...</p>"
                  value={newTemplateForm.body_html}
                  onChange={(e) => setNewTemplateForm({ ...newTemplateForm, body_html: e.target.value })}
                  className="px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg font-mono text-xs"
                />
              </div>

              <div className="flex items-center justify-end gap-2 pt-3 border-t border-slate-100 dark:border-slate-800">
                <button
                  type="button"
                  onClick={() => setShowAddTemplateModal(false)}
                  className="px-4 py-2 rounded-lg text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 font-semibold"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-5 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white font-bold flex items-center gap-2 shadow-sm"
                >
                  <Save className="w-4 h-4" />
                  Create Template
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ========================================================= */}
      {/* DRAWER 6: TWO-WAY CONVERSATION HISTORY */}
      {/* ========================================================= */}
      {conversationAllocation && (
        <div className="fixed inset-0 z-50 flex items-center justify-end bg-black/50 backdrop-blur-xs">
          <div className="bg-white dark:bg-slate-900 w-full max-w-lg h-full border-l border-slate-200 dark:border-slate-800 shadow-2xl p-6 flex flex-col gap-4 animate-in slide-in-from-right duration-200">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100 dark:border-slate-800">
              <div className="flex items-center gap-2.5">
                <div className="p-2 rounded-lg bg-blue-50 dark:bg-blue-950/60 text-blue-600 dark:text-blue-400">
                  <MessageSquare className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="font-bold text-slate-800 dark:text-slate-100 text-base">
                    Communication History
                  </h3>
                  <span className="text-xs text-slate-400">
                    {conversationAllocation.donor_name} ↔ {conversationAllocation.beneficiary_name}
                  </span>
                </div>
              </div>

              <button
                onClick={() => setConversationAllocation(null)}
                className="p-1 rounded-lg text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Messages Stream */}
            <div className="flex-1 overflow-y-auto flex flex-col gap-3 pr-1">
              {loadingMessages ? (
                <div className="py-12 text-center text-slate-400 text-xs">Loading communications...</div>
              ) : conversationMessages.length === 0 ? (
                <div className="py-12 text-center text-slate-400 text-xs">
                  No communications logged yet. Send an email to start the conversation timeline.
                </div>
              ) : (
                conversationMessages.map((m) => {
                  const isInbound = m.direction === 'inbound';
                  return (
                    <div
                      key={m.id}
                      className={`p-3.5 rounded-2xl flex flex-col gap-1.5 max-w-[88%] ${
                        isInbound
                          ? 'self-start bg-slate-100 dark:bg-slate-800 text-slate-800 dark:text-slate-100 rounded-tl-xs border border-slate-200/80 dark:border-slate-700'
                          : 'self-end bg-blue-600 text-white rounded-tr-xs shadow-xs'
                      }`}
                    >
                      <div className="flex items-center justify-between text-[10px] font-bold opacity-80 gap-3">
                        <span>{isInbound ? `💬 Inbound from ${m.sender_email}` : `📤 Outbound via Microsoft 365`}</span>
                        <span>{new Date(m.sent_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                      </div>

                      {m.subject && (
                        <div className="font-bold text-xs underline decoration-white/30">{m.subject}</div>
                      )}

                      <div
                        className="text-xs leading-relaxed break-words"
                        dangerouslySetInnerHTML={{ __html: m.body }}
                      />

                      {/* Delivery & Read Tracking Audit Footer */}
                      {!isInbound && (
                        <div className="pt-2 mt-1 border-t border-white/20 flex flex-wrap items-center justify-between gap-1 text-[10px] text-white/90">
                          <div className="flex items-center gap-1 font-medium">
                            {m.delivery_status === 'opened' ? (
                              <span className="flex items-center gap-1 font-bold text-emerald-200">
                                <Eye className="w-3 h-3" />
                                Opened {m.open_count > 1 ? `(${m.open_count}x)` : 'by recipient'}
                              </span>
                            ) : m.delivery_status === 'replied' ? (
                              <span className="flex items-center gap-1 font-bold text-cyan-200">
                                <MessageSquare className="w-3 h-3" />
                                Donor Replied
                              </span>
                            ) : (
                              <span className="flex items-center gap-1 opacity-90">
                                <Check className="w-3 h-3" />
                                Delivered to Inbox
                              </span>
                            )}
                          </div>

                          {m.opened_at && m.delivery_status === 'opened' && (
                            <span className="text-[9px] opacity-80 font-mono">
                              First opened: {new Date(m.opened_at).toLocaleDateString([], { month: 'short', day: 'numeric' })}{' '}
                              {new Date(m.opened_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                            </span>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })
              )}
            </div>

            <div className="pt-3 border-t border-slate-100 dark:border-slate-800">
              <button
                onClick={() => {
                  const alloc = conversationAllocation;
                  setConversationAllocation(null);
                  openEmailDispatcher(alloc, 'profile_intro');
                }}
                className="w-full py-2.5 rounded-xl bg-blue-600 hover:bg-blue-700 text-white font-bold text-xs flex items-center justify-center gap-2 shadow-xs"
              >
                <Send className="w-4 h-4" />
                Reply or Send New Update via Outlook
              </button>
            </div>
          </div>
        </div>
      )}

      {/* OVERDUE ALERTS CONFIGURATION & STAFF DIGEST MODAL */}
      {showAlertSettingsModal && (
        <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white dark:bg-slate-900 rounded-2xl shadow-2xl border border-slate-200 dark:border-slate-800 max-w-lg w-full overflow-hidden animate-in fade-in zoom-in-95 duration-200">
            {/* Modal Header */}
            <div className="px-6 py-4 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between bg-amber-50/50 dark:bg-amber-950/20">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-amber-500 text-white flex items-center justify-center shadow-md">
                  <Sliders className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-base font-bold text-slate-800 dark:text-slate-100">
                    Alert & Staff Digest Settings
                  </h3>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    Configure SLA thresholds and automated email digests to staff
                  </p>
                </div>
              </div>
              <button
                onClick={() => {
                  setShowAlertSettingsModal(false);
                  setDigestFeedback(null);
                }}
                className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Modal Body */}
            <form onSubmit={handleSaveAlertSettings} className="p-6 space-y-5">
              {/* Threshold Days */}
              <div>
                <label className="block text-xs font-bold text-slate-700 dark:text-slate-300 mb-1.5">
                  Overdue SLA Threshold (Days)
                </label>
                <p className="text-[11px] text-slate-500 dark:text-slate-400 mb-2">
                  Donations older than this threshold with unallocated beneficiary slots will trigger an overdue alert.
                </p>
                <div className="flex items-center gap-2">
                  <input
                    type="number"
                    min="1"
                    max="365"
                    value={alertSettings.threshold_days}
                    onChange={(e) => setAlertSettings(prev => ({ ...prev, threshold_days: parseInt(e.target.value) || 1 }))}
                    className="w-28 px-3 py-2 text-sm font-bold bg-slate-50 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-xl focus:ring-2 focus:ring-amber-500 focus:outline-none"
                    required
                  />
                  <div className="flex items-center gap-1.5">
                    {[15, 30, 60, 90].map(days => (
                      <button
                        key={days}
                        type="button"
                        onClick={() => setAlertSettings(prev => ({ ...prev, threshold_days: days }))}
                        className={`px-2.5 py-1 text-xs rounded-lg font-medium transition-all ${
                          alertSettings.threshold_days === days
                            ? 'bg-amber-500 text-white font-bold shadow-xs'
                            : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700'
                        }`}
                      >
                        {days}d
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              {/* Staff Recipient Emails */}
              <div>
                <label className="block text-xs font-bold text-slate-700 dark:text-slate-300 mb-1.5">
                  Staff Recipient Emails (Comma-separated)
                </label>
                <p className="text-[11px] text-slate-500 dark:text-slate-400 mb-2">
                  Operations or fundraising team members who should receive overdue digest notifications.
                </p>
                <textarea
                  rows={2}
                  value={alertSettings.staff_emails}
                  onChange={(e) => setAlertSettings(prev => ({ ...prev, staff_emails: e.target.value }))}
                  placeholder="e.g. operations@charity.org, director@charity.org"
                  className="w-full px-3 py-2 text-xs bg-slate-50 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-xl focus:ring-2 focus:ring-amber-500 focus:outline-none"
                />
              </div>

              {/* Digest Frequency */}
              <div>
                <label className="block text-xs font-bold text-slate-700 dark:text-slate-300 mb-1.5">
                  Digest Frequency
                </label>
                <select
                  value={alertSettings.digest_frequency}
                  onChange={(e) => setAlertSettings(prev => ({ ...prev, digest_frequency: e.target.value }))}
                  className="w-full px-3 py-2 text-xs bg-slate-50 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-xl focus:ring-2 focus:ring-amber-500 focus:outline-none"
                >
                  <option value="daily">Daily Summary (Every morning at 08:00 UTC)</option>
                  <option value="weekly">Weekly Digest (Every Monday morning)</option>
                  <option value="monthly">Monthly Audit (1st of each month)</option>
                </select>
                {alertSettings.last_digest_sent_at && (
                  <p className="text-[10px] text-slate-400 mt-1">
                    Last digest dispatched: {new Date(alertSettings.last_digest_sent_at).toLocaleString()}
                  </p>
                )}
              </div>

              {/* Feedback Alert if Send Digest was clicked */}
              {digestFeedback && (
                <div className={`p-3 rounded-xl text-xs flex items-start gap-2 ${
                  digestFeedback.status === 'success'
                    ? 'bg-emerald-50 dark:bg-emerald-950/40 text-emerald-800 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800'
                    : 'bg-rose-50 dark:bg-rose-950/40 text-rose-800 dark:text-rose-300 border border-rose-200 dark:border-rose-800'
                }`}>
                  {digestFeedback.status === 'success' ? (
                    <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0 mt-0.5" />
                  ) : (
                    <AlertCircle className="w-4 h-4 text-rose-600 shrink-0 mt-0.5" />
                  )}
                  <div>
                    <div className="font-bold">{digestFeedback.message}</div>
                    {digestFeedback.stats && (
                      <div className="text-[11px] opacity-80 mt-0.5">
                        {digestFeedback.stats.total_overdue_donors} overdue donors ({digestFeedback.stats.total_unallocated_slots} slots), longest wait {digestFeedback.stats.longest_waiting_days}d.
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Action Buttons */}
              <div className="pt-3 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between">
                <button
                  type="button"
                  onClick={() => handleSendOverdueDigest(false)}
                  disabled={sendingDigest || !alertSettings.staff_emails.trim()}
                  className="px-3 py-2 rounded-xl text-xs font-bold bg-amber-100 dark:bg-amber-950/60 text-amber-800 dark:text-amber-300 hover:bg-amber-200 dark:hover:bg-amber-900/60 disabled:opacity-50 transition-colors flex items-center gap-1.5"
                  title={!alertSettings.staff_emails.trim() ? 'Add at least one staff email above' : 'Dispatch digest immediately'}
                >
                  <SendHorizontal className="w-3.5 h-3.5" />
                  {sendingDigest ? 'Dispatching...' : 'Send Digest Now'}
                </button>

                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      setShowAlertSettingsModal(false);
                      setDigestFeedback(null);
                    }}
                    className="px-4 py-2 rounded-xl text-xs font-bold text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={savingAlertSettings}
                    className="px-4 py-2 rounded-xl text-xs font-bold bg-emerald-600 hover:bg-emerald-700 text-white shadow-xs transition-colors flex items-center gap-1.5"
                  >
                    <Save className="w-3.5 h-3.5" />
                    {savingAlertSettings ? 'Saving...' : 'Save Settings'}
                  </button>
                </div>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* OVERDUE ALERT DISMISSAL / FALSE POSITIVE CONFIRMATION MODAL */}
      {dismissModalData.isOpen && (
        <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white dark:bg-slate-900 rounded-2xl shadow-2xl border border-slate-200 dark:border-slate-800 max-w-md w-full overflow-hidden animate-in fade-in zoom-in-95 duration-200">
            <div className="px-6 py-4 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between bg-rose-50/50 dark:bg-rose-950/20">
              <div className="flex items-center gap-2.5">
                <div className="w-9 h-9 rounded-xl bg-rose-600 text-white flex items-center justify-center shadow-xs">
                  <EyeOff className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-slate-800 dark:text-slate-100">
                    Dismiss Alert / False Positive
                  </h3>
                  <p className="text-[11px] text-slate-500 dark:text-slate-400">
                    Remove from overdue queue & email digests
                  </p>
                </div>
              </div>
              <button
                onClick={() => setDismissModalData({ isOpen: false, item: null, type: 'donor', reason: 'False positive / Not for 1-to-1 sponsorship', customReason: '' })}
                className="p-1 rounded-lg text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-6 space-y-4 text-xs">
              <div className="p-3.5 bg-slate-50 dark:bg-slate-800 rounded-xl border border-slate-200/80 dark:border-slate-700">
                <div className="font-bold text-slate-800 dark:text-slate-100 text-sm">
                  {dismissModalData.type === 'donor' ? dismissModalData.item?.donor_name : dismissModalData.item?.campaign_name}
                </div>
                <div className="text-slate-500 text-[11px] mt-0.5 font-mono">
                  {dismissModalData.type === 'donor'
                    ? `Donor ID: ${dismissModalData.item?.donor_id || 'N/A'}`
                    : `Community: ${dismissModalData.item?.community_name || 'General'}`}
                </div>
                <div className="flex items-center gap-2 mt-2">
                  <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-blue-100 dark:bg-blue-950 text-blue-700 dark:text-blue-300">
                    {dismissModalData.item?.sponsorship_type}
                  </span>
                  <span className="text-[11px] text-rose-600 font-semibold">
                    Waiting {dismissModalData.item?.waiting_days} days
                  </span>
                </div>
              </div>

              <div>
                <label className="block font-bold text-slate-700 dark:text-slate-300 mb-1.5">
                  Select Dismissal Reason
                </label>
                <select
                  value={dismissModalData.reason}
                  onChange={(e) => setDismissModalData(prev => ({ ...prev, reason: e.target.value }))}
                  className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-xl text-xs focus:ring-2 focus:ring-rose-500 focus:outline-none"
                >
                  <option value="False positive / Not for 1-to-1 sponsorship">False positive / Not for 1-to-1 sponsorship</option>
                  <option value="Donor requested no beneficiary allocation">Donor requested no beneficiary allocation</option>
                  <option value="Corporate or institutional grant donation">Corporate or institutional grant donation</option>
                  <option value="Duplicate donation / Handled outside CRM">Duplicate donation / Handled outside CRM</option>
                  <option value="Direct project funding (non-allocable)">Direct project funding (non-allocable)</option>
                  <option value="Other">Other / Custom reason</option>
                </select>
              </div>

              {dismissModalData.reason === 'Other' && (
                <div>
                  <label className="block font-bold text-slate-700 dark:text-slate-300 mb-1">
                    Custom Reason Note
                  </label>
                  <input
                    type="text"
                    placeholder="Explain why this alert is being dismissed..."
                    value={dismissModalData.customReason || ''}
                    onChange={(e) => setDismissModalData(prev => ({ ...prev, customReason: e.target.value }))}
                    className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-xl text-xs"
                  />
                </div>
              )}

              <div className="p-3 bg-amber-50 dark:bg-amber-950/40 rounded-xl border border-amber-200 dark:border-amber-800/60 text-[11px] text-amber-800 dark:text-amber-300">
                💡 You can restore this {dismissModalData.type} at any time from the <strong>Dismissed False Positives</strong> tab.
              </div>

              <div className="pt-3 border-t border-slate-100 dark:border-slate-800 flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setDismissModalData({ isOpen: false, item: null, type: 'donor', reason: 'False positive / Not for 1-to-1 sponsorship', customReason: '' })}
                  className="px-4 py-2 rounded-xl text-xs font-bold text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleConfirmDismissal}
                  disabled={dismissing}
                  className="px-4 py-2 rounded-xl text-xs font-bold bg-rose-600 hover:bg-rose-700 text-white shadow-xs disabled:opacity-50 flex items-center gap-1.5 transition-colors"
                >
                  {dismissing ? 'Dismissing...' : 'Confirm Dismissal'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
