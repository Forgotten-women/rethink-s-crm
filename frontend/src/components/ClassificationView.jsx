import React, { useEffect, useState, useRef, useMemo } from 'react';
import { 
  Shield, 
  Save, 
  CheckCircle, 
  AlertCircle, 
  RefreshCw, 
  Download, 
  Upload, 
  Trash2, 
  X, 
  FileSpreadsheet, 
  Lock,
  ExternalLink,
  Zap,
  Gift,
  CreditCard,
  Globe,
  Search,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  Filter,
  Plus,
  Edit3,
  Sparkles
} from 'lucide-react';
import { API_BASE_URL } from '../config';

// Robust frontend text cleaner to repair mojibake / corrupted UTF-8 and strip zero-width characters
function cleanText(val) {
  if (!val || typeof val !== 'string') return val || '';
  let s = val.trim();
  s = s.replace(/\u00AD/g, '').replace(/[\u200B-\u200D\uFEFF]/g, '');
  s = s.replace(/AshbÄ\xad/gi, 'Ashbā')
       .replace(/AshbÄ/gi, 'Ashbā')
       .replace(/â€“/g, '–')
       .replace(/â€”/g, '—')
       .replace(/â€™/g, "’")
       .replace(/â€œ/g, '“')
       .replace(/â€/g, '”')
       .replace(/Ã©/g, 'é')
       .replace(/Ã¨/g, 'è')
       .replace(/Ã®/g, 'î')
       .replace(/Ã´/g, 'ô')
       .replace(/Ã¹/g, 'ù')
       .replace(/Ã¡/g, 'á')
       .replace(/Ã­/g, 'í')
       .replace(/Ã³/g, 'ó')
       .replace(/Ãº/g, 'ú')
       .replace(/Ã±/g, 'ñ')
       .replace(/Ã\s/g, 'à');
  return s;
}

export default function ClassificationView({ user, activeCompany = 'rethink', companies = [] }) {
  const isConsolidated = activeCompany === 'all';
  // Enforce company platform partitioning
  // Iqra: GiveBrite, Madinah, Master
  // Rethink: LaunchGood, GiveBright, Paysuite, Website, Master
  const isIqra = activeCompany === 'iqra';

  // Persist selected platform in localStorage with company compatibility
  const [platform, setPlatform] = useState(() => {
    const saved = localStorage.getItem('selected_classification_platform');
    if (activeCompany === 'iqra') {
      return ['master', 'givebright', 'madinah'].includes(saved) ? saved : 'givebright';
    }
    return ['master', 'launchgood', 'givebright', 'paysuite', 'website'].includes(saved) ? saved : 'launchgood';
  });

  const [matrixData, setMatrixData] = useState({ total_campaigns: 0, classified_campaigns: 0, unassigned_campaigns: 0, rules: [] });
  const [codeMap, setCodeMap] = useState({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveNotification, setSaveNotification] = useState(null); // { type: 'success' | 'error' | 'info', title: string, message: string, timestamp: string }

  // Auto-dismiss success notification after 7 seconds
  useEffect(() => {
    if (saveNotification?.type === 'success') {
      const timer = setTimeout(() => {
        setSaveNotification(null);
      }, 7000);
      return () => clearTimeout(timer);
    }
  }, [saveNotification]);

  // Ensure active platform matches active company
  useEffect(() => {
    if (activeCompany === 'iqra') {
      if (!['master', 'givebright', 'madinah'].includes(platform)) {
        handleSelectPlatform('givebright');
      }
    } else if (activeCompany === 'rethink') {
      if (!['master', 'launchgood', 'givebright', 'paysuite', 'website'].includes(platform)) {
        handleSelectPlatform('launchgood');
      }
    }
  }, [activeCompany]);

  // 🚀 Fast Client-Side Search & Pagination State
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('ALL'); // 'ALL', 'CLASSIFIED', 'UNASSIGNED'
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(50); // 25, 50, 100, 250, 'All'
  const [jumpPage, setJumpPage] = useState('');
  
  // Importer Modal State
  const [showImportModal, setShowImportModal] = useState(false);
  const [importFile, setImportFile] = useState(null);
  const [importMode, setImportMode] = useState('merge'); // 'merge' or 'replace'
  const [importing, setImporting] = useState(false);
  const [importMsg, setImportMsg] = useState('');
  const fileInputRef = useRef(null);

  const isSuperAdmin = user?.role === 'super_admin';

  // Update platform handler with localStorage persistence
  const handleSelectPlatform = (newPlat) => {
    if (newPlat === platform) return;
    setPlatform(newPlat);
    localStorage.setItem('selected_classification_platform', newPlat);
    setCurrentPage(1);
  };

  // Reset page to 1 whenever search, status filter, or page size changes
  useEffect(() => {
    setCurrentPage(1);
  }, [platform, statusFilter, searchQuery, pageSize]);

  // Fetch Code Map for dynamic Code -> Heading, Sub-Heading, Country, Zakat auto-fill
  useEffect(() => {
    fetch(`${API_BASE_URL}/api/classifications/code-map?company_id=${encodeURIComponent(activeCompany)}`)
      .then(res => res.json())
      .then(data => {
        if (data && typeof data === 'object') {
          setCodeMap(data);
        }
      })
      .catch(err => console.error('Error fetching code map:', err));
  }, [activeCompany]);

  // Master Code Modal State
  const [masterCodeModal, setMasterCodeModal] = useState(null); // { isEdit: bool, data: { code, department, office, portfolio, country, zakat_eligibility, description, is_active } }
  const [savingMasterCode, setSavingMasterCode] = useState(false);
  const [masterCodeModalMsg, setMasterCodeModalMsg] = useState('');

  const handleOpenAddMasterCode = () => {
    setMasterCodeModal({
      isEdit: false,
      data: {
        code: '',
        programme_fund: '',
        fund_code: '',
        department: '',
        office: '',
        portfolio: '',
        country: '',
        zakat_eligibility: 'Zakat',
        legacy_non_zakat_code: '',
        legacy_zakat_code: '',
        old_codes: '',
        description: '',
        is_active: 1
      }
    });
    setMasterCodeModalMsg('');
  };

  const handleOpenEditMasterCode = (rule) => {
    setMasterCodeModal({
      isEdit: true,
      data: {
        code: rule.code || rule['Code'],
        programme_fund: rule.programme_fund || rule['Programme Fund'] || '',
        fund_code: rule.fund_code || rule['Fund Code'] || '',
        department: rule.department || rule['Department'] || rule['Heading'] || '',
        office: rule.office || rule['Office'] || rule['Sub-Heading'] || '',
        portfolio: rule.portfolio || rule['Portfolio'] || '',
        country: rule.country || rule['Country'] || '',
        zakat_eligibility: rule.zakat_eligibility || rule['Zakat Eligibility'] || 'Zakat',
        legacy_non_zakat_code: rule.legacy_non_zakat_code || rule['Legacy Non-Zakat GL Code'] || '',
        legacy_zakat_code: rule.legacy_zakat_code || rule['Legacy Zakat GL Code'] || '',
        old_codes: rule.old_codes || rule['Old Code(s)'] || '',
        description: rule.description || rule['Description'] || '',
        is_active: rule.is_active !== undefined ? rule.is_active : 1
      }
    });
    setMasterCodeModalMsg('');
  };

  const handleSaveMasterCodeSubmit = async (e) => {
    e.preventDefault();
    if (!isSuperAdmin || !masterCodeModal) return;
    setSavingMasterCode(true);
    setMasterCodeModalMsg('');

    try {
      const res = await fetch(`${API_BASE_URL}/api/classifications/master-codes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_role: user?.role,
          company_id: activeCompany,
          code: masterCodeModal.data.code,
          programme_fund: masterCodeModal.data.programme_fund || '',
          fund_code: masterCodeModal.data.fund_code || '',
          department: masterCodeModal.data.department,
          office: masterCodeModal.data.office,
          portfolio: masterCodeModal.data.portfolio || '',
          country: masterCodeModal.data.country,
          zakat_eligibility: masterCodeModal.data.zakat_eligibility || 'Zakat',
          legacy_non_zakat_code: masterCodeModal.data.legacy_non_zakat_code || '',
          legacy_zakat_code: masterCodeModal.data.legacy_zakat_code || '',
          old_codes: masterCodeModal.data.old_codes || '',
          description: masterCodeModal.data.description || '',
          is_active: masterCodeModal.data.is_active || 1
        })
      });

      const data = await res.json();
      setSavingMasterCode(false);

      if (res.ok && data?.status === 'success') {
        setMasterCodeModalMsg(`✅ ${data.message || 'Saved successfully!'}`);
        setSaveNotification({
          type: 'success',
          title: 'Master Code Saved & Synced',
          message: data.message || `Master project code '${masterCodeModal.data.code}' saved & cascaded to matching donations.`,
          timestamp: new Date().toLocaleTimeString()
        });
        fetch(`${API_BASE_URL}/api/classifications/code-map?company_id=${encodeURIComponent(activeCompany)}`)
          .then(r => r.json())
          .then(cm => { if (cm) setCodeMap(cm); });
        setTimeout(() => {
          setMasterCodeModal(null);
          loadMatrixData();
        }, 800);
      } else {
        setMasterCodeModalMsg(`❌ ${data?.detail || 'Failed to save master code.'}`);
      }
    } catch (err) {
      setSavingMasterCode(false);
      setMasterCodeModalMsg(`❌ Error: ${err.message}`);
    }
  };

  const handleDeleteMasterCode = async (rule) => {
    if (!isSuperAdmin) return;
    const cCode = rule.code || rule['Code'];
    if (!window.confirm(`Are you sure you want to delete Master Project Code "${cCode}"?\n\nThis will remove it from the canonical codes registry.`)) {
      return;
    }

    try {
      const res = await fetch(`${API_BASE_URL}/api/classifications/master-codes/${encodeURIComponent(cCode)}?user_role=${encodeURIComponent(user?.role)}&company_id=${encodeURIComponent(activeCompany)}`, {
        method: 'DELETE'
      });
      const data = await res.json();
      if (res.ok && data?.status === 'success') {
        setSaveNotification({
          type: 'success',
          title: 'Master Code Deleted',
          message: data.message || `Successfully deleted master code ${cCode}.`,
          timestamp: new Date().toLocaleTimeString()
        });
        loadMatrixData();
        fetch(`${API_BASE_URL}/api/classifications/code-map?company_id=${encodeURIComponent(activeCompany)}`)
          .then(r => r.json())
          .then(cm => { if (cm) setCodeMap(cm); });
      } else {
        setSaveNotification({
          type: 'error',
          title: 'Delete Failed',
          message: data?.detail || 'Failed to delete master code.',
          timestamp: new Date().toLocaleTimeString()
        });
      }
    } catch (err) {
      setSaveNotification({
        type: 'error',
        title: 'Delete Error',
        message: err.message,
        timestamp: new Date().toLocaleTimeString()
      });
    }
  };

  // Race-Condition-Free Data Loading with Cancellation Cleanup
  const loadMatrixData = () => {
    setLoading(true);

    if (platform === 'master') {
      fetch(`${API_BASE_URL}/api/classifications/master-codes?company_id=${encodeURIComponent(activeCompany)}`)
        .then(res => res.json())
        .then(data => {
          let rules = (data.codes || []).map((r, i) => ({
            ...r,
            _row_id: `master__${r.code}__${i}`,
            'Code': cleanText(r.code),
            'Programme Fund': cleanText(r.programme_fund || ''),
            'Fund Code': cleanText(r.fund_code || ''),
            'Department': cleanText(r.department),
            'Office': cleanText(r.office),
            'Portfolio': cleanText(r.portfolio || ''),
            'Heading': cleanText(r.department),
            'Sub-Heading': cleanText(r.office),
            'Country': cleanText(r.country),
            'Zakat Eligibility': cleanText(r.zakat_eligibility),
            'Legacy Non-Zakat GL Code': cleanText(r.legacy_non_zakat_code || ''),
            'Legacy Zakat GL Code': cleanText(r.legacy_zakat_code || ''),
            'Old Code(s)': cleanText(r.old_codes || ''),
            'Description': cleanText(r.description || ''),
            'Campaign Count': r.campaign_count || 0,
            'Total Raised': r.total_raised || 0,
            'is_active': r.is_active
          }));

          setMatrixData({
            total_campaigns: rules.length,
            classified_campaigns: rules.filter(r => r['Department'] && r['Department'] !== 'Unassigned').length,
            unassigned_campaigns: rules.filter(r => !r['Department'] || r['Department'] === 'Unassigned').length,
            rules: rules
          });
          setLoading(false);
        })
        .catch(err => {
          console.error('Error loading master codes:', err);
          setLoading(false);
        });
      return;
    }

    fetch(`${API_BASE_URL}/api/classifications/${platform}?company_id=${encodeURIComponent(activeCompany)}`)
      .then(res => res.json())
      .then(data => {
        let rules = (data.rules || []).map((r, i) => ({
          ...r,
          _row_id: `${r['Campaign Name'] || r['campaign_name']}__${r['Code'] || r['code'] || i}__${i}`,
          'Campaign Name': cleanText(r['Campaign Name']),
          'Community Name': cleanText(r['Community Name']),
          'Donor Name': cleanText(r['Donor Name'] || r['donor_name'] || ''),
          'Donor Email': cleanText(r['Donor Email'] || r['donor_email'] || ''),
          'Department': cleanText(r['Department'] || r['Heading']),
          'Office': cleanText(r['Office'] || r['Sub-Heading']),
          'Portfolio': cleanText(r['Portfolio'] || ''),
          'Heading': cleanText(r['Department'] || r['Heading']),
          'Sub-Heading': cleanText(r['Office'] || r['Sub-Heading']),
          'Country': cleanText(r['Country']),
          'Code': cleanText(r['Code']),
          'Zakat Eligibility': cleanText(r['Zakat Eligibility']),
          'Campaign URL': r['Campaign URL'] || r['campaign_url'] || ''
        }));

        setMatrixData({
          ...data,
          total_campaigns: rules.length,
          classified_campaigns: rules.filter(r => (r['Department'] || r['Heading']) && (r['Department'] || r['Heading']) !== 'Unassigned').length,
          unassigned_campaigns: rules.filter(r => !(r['Department'] || r['Heading']) || (r['Department'] || r['Heading']) === 'Unassigned').length,
          rules: rules
        });
        setLoading(false);
      })
      .catch(err => {
        console.error('Error loading classification matrix:', err);
        setLoading(false);
      });
  };

  // Race-Condition-Free Data Loading
  useEffect(() => {
    loadMatrixData();
  }, [platform, activeCompany]);

  // Dynamic list of all known unique codes (from central code map + active rules + any newly typed codes)
  const knownCodes = useMemo(() => {
    const codeSet = new Set();
    Object.keys(codeMap || {}).forEach(c => {
      const clean = String(c).trim().toUpperCase();
      if (clean && !['UNASSIGNED', 'N/A', 'NONE', 'NAN', ''].includes(clean)) {
        codeSet.add(clean);
      }
    });
    (matrixData?.rules || []).forEach(r => {
      const cd = String(r['Code'] || r['code'] || '').trim().toUpperCase();
      if (cd && !['UNASSIGNED', 'N/A', 'NONE', 'NAN', ''].includes(cd)) {
        codeSet.add(cd);
      }
    });
    return Array.from(codeSet).sort();
  }, [codeMap, matrixData?.rules]);

  // Dynamic cell change handler with Code -> Classification Auto-Fill & Same-Code Auto-Propagation
  const handleCellChange = (rowId, field, value) => {
    if (!isSuperAdmin) return;
    const valClean = cleanText(value);

    // 1. If user is changing Code on a row:
    if (field === 'Code') {
      const newCodeClean = valClean.trim().toUpperCase();
      const newCodeLower = valClean.trim().toLowerCase();

      // Find if we already have classification metadata for this code in codeMap or elsewhere in rules
      let existingInfo = codeMap[newCodeLower];
      if (!existingInfo || Object.values(existingInfo).every(v => !v || v === 'Unassigned')) {
        const matchingRule = (matrixData.rules || []).find(r => {
          const cd = (r['Code'] || r['code'] || '').trim().toLowerCase();
          const dept = r['Department'] || r['Heading'];
          return cd === newCodeLower && dept && dept !== 'Unassigned';
        });
        if (matchingRule) {
          const dept = matchingRule['Department'] || matchingRule['Heading'] || 'Unassigned';
          const off = matchingRule['Office'] || matchingRule['Sub-Heading'] || 'Unassigned';
          existingInfo = {
            Department: dept,
            Office: off,
            Portfolio: matchingRule['Portfolio'] || '',
            Heading: dept,
            'Sub-Heading': off,
            Country: matchingRule['Country'] || 'Unassigned',
            'Zakat Eligibility': matchingRule['Zakat Eligibility'] || 'Unassigned'
          };
        }
      }

      setMatrixData(prev => {
        const updatedRules = prev.rules.map(r => {
          if (r._row_id === rowId) {
            const currentRow = { ...r, Code: newCodeClean };
            if (existingInfo) {
              const dept = existingInfo.Department || existingInfo.Heading;
              const off = existingInfo.Office || existingInfo['Sub-Heading'];
              if (dept && dept !== 'Unassigned') {
                currentRow['Department'] = dept;
                currentRow['Heading'] = dept;
              }
              if (off && off !== 'Unassigned') {
                currentRow['Office'] = off;
                currentRow['Sub-Heading'] = off;
              }
              if (existingInfo.Portfolio !== undefined) {
                currentRow['Portfolio'] = existingInfo.Portfolio;
              }
              if (existingInfo.Country && existingInfo.Country !== 'Unassigned') currentRow['Country'] = existingInfo.Country;
              if (existingInfo['Zakat Eligibility'] && existingInfo['Zakat Eligibility'] !== 'Unassigned') currentRow['Zakat Eligibility'] = existingInfo['Zakat Eligibility'];
            }
            return currentRow;
          }
          return r;
        });

        return {
          ...prev,
          classified_campaigns: updatedRules.filter(r => (r['Department'] || r['Heading']) && (r['Department'] || r['Heading']) !== 'Unassigned').length,
          unassigned_campaigns: updatedRules.filter(r => !(r['Department'] || r['Heading']) || (r['Department'] || r['Heading']) === 'Unassigned').length,
          rules: updatedRules
        };
      });
      return;
    }

    // 2. If user is changing Department, Office, Portfolio, Heading, Sub-Heading, Country, or Zakat Eligibility on a row:
    const classificationFields = ['Department', 'Office', 'Portfolio', 'Heading', 'Sub-Heading', 'Country', 'Zakat Eligibility'];
    if (classificationFields.includes(field)) {
      const targetRow = (matrixData.rules || []).find(r => r._row_id === rowId);
      const codeKey = targetRow?.Code || targetRow?.code || '';
      const codeUpper = (codeKey || '').trim().toUpperCase();
      const codeLower = (codeKey || '').trim().toLowerCase();
      const isValidCode = codeUpper && !['UNASSIGNED', 'N/A', 'NONE', 'NAN', ''].includes(codeUpper);

      // Keep dual aliases in sync
      const extraUpdates = {};
      if (field === 'Department') extraUpdates['Heading'] = valClean;
      if (field === 'Heading') extraUpdates['Department'] = valClean;
      if (field === 'Office') extraUpdates['Sub-Heading'] = valClean;
      if (field === 'Sub-Heading') extraUpdates['Office'] = valClean;

      // Update central codeMap dictionary if code is valid
      if (isValidCode && valClean && valClean !== 'Unassigned') {
        setCodeMap(prevMap => {
          const currentEntry = prevMap[codeLower] || {
            Department: 'Unassigned',
            Office: 'Unassigned',
            Portfolio: '',
            Heading: 'Unassigned',
            'Sub-Heading': 'Unassigned',
            Country: 'Unassigned',
            'Zakat Eligibility': 'Unassigned'
          };
          return {
            ...prevMap,
            [codeLower]: {
              ...currentEntry,
              [field]: valClean,
              ...extraUpdates
            }
          };
        });
      }

      setMatrixData(prev => {
        const updatedRules = prev.rules.map(r => {
          if (r._row_id === rowId) {
            return { ...r, [field]: valClean, ...extraUpdates };
          }
          // AUTO-PROPAGATE to any other row that shares the SAME valid Code:
          if (isValidCode && (r.Code || r.code || '').trim().toUpperCase() === codeUpper) {
            return { ...r, [field]: valClean, ...extraUpdates };
          }
          return r;
        });

        return {
          ...prev,
          classified_campaigns: updatedRules.filter(r => (r['Department'] || r['Heading']) && (r['Department'] || r['Heading']) !== 'Unassigned').length,
          unassigned_campaigns: updatedRules.filter(r => !(r['Department'] || r['Heading']) || (r['Department'] || r['Heading']) === 'Unassigned').length,
          rules: updatedRules
        };
      });
      return;
    }

    // 3. For any other field (e.g. Campaign URL, Community Name)
    setMatrixData(prev => ({
      ...prev,
      rules: prev.rules.map(r => r._row_id === rowId ? { ...r, [field]: valClean } : r)
    }));
  };

  // Add/Duplicate a new code variant rule for the same campaign name
  const handleDuplicateRule = (rule) => {
    if (!isSuperAdmin) return;
    const cName = rule['Campaign Name'] || rule['campaign_name'];
    const newRule = {
      ...rule,
      _row_id: `${cName}__new__${Date.now()}`,
      Code: '',
      Department: 'Unassigned',
      Office: 'Unassigned',
      Portfolio: '',
      Heading: 'Unassigned',
      'Sub-Heading': 'Unassigned',
      Country: 'Unassigned',
      'Zakat Eligibility': 'Unassigned',
      is_primary: false,
      status: 'multi_code',
      variants_count: (rule.variants_count || 1) + 1
    };
    setMatrixData(prev => ({
      ...prev,
      total_campaigns: prev.rules.length + 1,
      unassigned_campaigns: prev.unassigned_campaigns + 1,
      rules: [newRule, ...prev.rules]
    }));
    setSaveNotification({
      type: 'info',
      title: 'Variant Added',
      message: `Added new code variant slot for "${cName}". Specify Code and click "Save Matrix & Sync".`,
      timestamp: new Date().toLocaleTimeString()
    });
  };

  // Toggle Primary/Default Code Variant for a Multi-Code Campaign
  const handleTogglePrimary = (rule) => {
    if (!isSuperAdmin) return;
    const targetRowId = rule._row_id;
    const cName = rule['Campaign Name'] || rule['campaign_name'];
    const targetCode = rule['Code'] || rule['code'] || 'Unassigned';

    setMatrixData(prev => {
      const updatedRules = prev.rules.map(r => {
        const rowName = r['Campaign Name'] || r['campaign_name'];
        if (rowName === cName) {
          return {
            ...r,
            is_primary: r._row_id === targetRowId
          };
        }
        return r;
      });
      return {
        ...prev,
        rules: updatedRules
      };
    });

    setSaveNotification({
      type: 'info',
      title: 'Primary Variant Set',
      message: `Marked "${targetCode}" as Primary code for "${cName}". Click "Save Matrix & Sync" to persist.`,
      timestamp: new Date().toLocaleTimeString()
    });
  };

  // Dynamic status counts calculation
  const { singleCodeCount, multiCodeCount, unassignedCount } = useMemo(() => {
    let single = 0, multi = 0, unassigned = 0;
    (matrixData.rules || []).forEach(r => {
      const isUn = !r['Heading'] || r['Heading'] === 'Unassigned' || !r['Code'] || r['Code'] === 'Unassigned';
      if (isUn) {
        unassigned++;
      } else if (r.status === 'multi_code' || r.variants_count > 1) {
        multi++;
      } else {
        single++;
      }
    });
    return { singleCodeCount: single, multiCodeCount: multi, unassignedCount: unassigned };
  }, [matrixData.rules]);

  // 🔍 Filtered Rules Calculation (Status + Live Search)
  const filteredRules = useMemo(() => {
    let list = matrixData.rules || [];

    // 1. Status Filter
    if (statusFilter === 'SINGLE_CODE') {
      list = list.filter(r => (r.status === 'single_code' || (!r.status && (r.variants_count === 1 || !r.variants_count) && r['Heading'] && r['Heading'] !== 'Unassigned')));
    } else if (statusFilter === 'MULTI_CODE') {
      list = list.filter(r => (r.status === 'multi_code' || r.variants_count > 1));
    } else if (statusFilter === 'UNASSIGNED') {
      list = list.filter(r => (r.status === 'unassigned' || !r['Heading'] || r['Heading'] === 'Unassigned' || !r['Code'] || r['Code'] === 'Unassigned'));
    }

    // 2. Search Query Filter
    if (searchQuery && searchQuery.trim()) {
      const q = searchQuery.trim().toLowerCase();
      list = list.filter(r => {
        return (
          (r['Campaign Name'] && String(r['Campaign Name']).toLowerCase().includes(q)) ||
          (r['Community Name'] && String(r['Community Name']).toLowerCase().includes(q)) ||
          (r['Code'] && String(r['Code']).toLowerCase().includes(q)) ||
          (r['Programme Fund'] && String(r['Programme Fund']).toLowerCase().includes(q)) ||
          (r['Fund Code'] && String(r['Fund Code']).toLowerCase().includes(q)) ||
          (r['Department'] && String(r['Department']).toLowerCase().includes(q)) ||
          (r['Office'] && String(r['Office']).toLowerCase().includes(q)) ||
          (r['Portfolio'] && String(r['Portfolio']).toLowerCase().includes(q)) ||
          (r['Heading'] && String(r['Heading']).toLowerCase().includes(q)) ||
          (r['Sub-Heading'] && String(r['Sub-Heading']).toLowerCase().includes(q)) ||
          (r['Country'] && String(r['Country']).toLowerCase().includes(q)) ||
          (r['Zakat Eligibility'] && String(r['Zakat Eligibility']).toLowerCase().includes(q)) ||
          (r['Old Code(s)'] && String(r['Old Code(s)']).toLowerCase().includes(q)) ||
          (r['Legacy Non-Zakat GL Code'] && String(r['Legacy Non-Zakat GL Code']).toLowerCase().includes(q)) ||
          (r['Legacy Zakat GL Code'] && String(r['Legacy Zakat GL Code']).toLowerCase().includes(q)) ||
          (r['Campaign URL'] && String(r['Campaign URL']).toLowerCase().includes(q))
        );
      });
    }

    return list;
  }, [matrixData.rules, statusFilter, searchQuery]);

  // 📑 Pagination Bounds & Slices
  const effectivePageSize = pageSize === 'All' ? Math.max(1, filteredRules.length) : Number(pageSize);
  const totalPages = Math.max(1, Math.ceil(filteredRules.length / effectivePageSize));
  const safePage = Math.min(Math.max(1, currentPage), totalPages);

  const paginatedRules = useMemo(() => {
    if (pageSize === 'All') return filteredRules;
    const start = (safePage - 1) * effectivePageSize;
    return filteredRules.slice(start, start + effectivePageSize);
  }, [filteredRules, safePage, effectivePageSize, pageSize]);

  const handleSave = async () => {
    if (!isSuperAdmin) return;
    if (isConsolidated) {
      setSaveNotification({
        type: 'error',
        title: 'Action Prohibited',
        message: 'Modifying classification rules in consolidated (All Companies) mode is disabled. Please switch to a specific company.',
        timestamp: new Date().toLocaleTimeString()
      });
      return;
    }
    setSaving(true);
    setSaveNotification({
      type: 'info',
      title: 'Saving & Syncing...',
      message: `Saving classification matrix rules and synchronizing to database records for ${platform.toUpperCase()} (${activeCompany.toUpperCase()})...`,
      timestamp: new Date().toLocaleTimeString()
    });

    try {
      const response = await fetch(`${API_BASE_URL}/api/classifications/save`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_role: user?.role,
          can_edit_matrix: true,
          platform: platform,
          company_id: activeCompany,
          rules: matrixData.rules
        })
      });

      const res = await response.json().catch(() => null);

      if (response.ok && res?.status === 'success') {
        setSaveNotification({
          type: 'success',
          title: 'Matrix Saved & Synced Successfully',
          message: res.message || `Successfully saved ${matrixData.rules.length.toLocaleString()} rules and synced live donor records!`,
          timestamp: new Date().toLocaleTimeString()
        });
        loadMatrixData();
      } else {
        const errorMsg = res?.detail || res?.message || `Server returned error (${response.status}: ${response.statusText})`;
        setSaveNotification({
          type: 'error',
          title: 'Save & Sync Failed',
          message: errorMsg,
          timestamp: new Date().toLocaleTimeString()
        });
      }
    } catch (err) {
      setSaveNotification({
        type: 'error',
        title: 'Connection / Server Error',
        message: err.message || 'Failed to communicate with backend server. Please verify your connection or retry.',
        timestamp: new Date().toLocaleTimeString()
      });
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteRule = async (rule) => {
    if (!isSuperAdmin) return;
    if (isConsolidated) {
      alert('Deleting classification rules is disabled in Consolidated (All Companies) mode.');
      return;
    }
    const cName = rule['Campaign Name'] || rule['campaign_name'];
    const cCode = rule['Code'] || rule['code'] || '';
    if (!window.confirm(`Are you sure you want to delete the classification rule for "${cName}" (Code: ${cCode || 'Unassigned'})?\n\nMatching donor records will be reset to Unassigned.`)) {
      return;
    }

    try {
      const res = await fetch(`${API_BASE_URL}/api/classifications/delete-rule`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_role: user?.role,
          platform: platform,
          company_id: activeCompany,
          campaign_name: cName,
          code: cCode || null,
          community_name: rule['Community Name'] || rule['community_name'] || null
        })
      });
      const data = await res.json();
      if (data?.status === 'success') {
        setSaveNotification({
          type: 'success',
          title: 'Rule Deleted',
          message: data.message || `Successfully deleted rule for "${cName}".`,
          timestamp: new Date().toLocaleTimeString()
        });
        setMatrixData(prev => {
          const filtered = prev.rules.filter(r => {
            const matchName = (r['Campaign Name'] || r['campaign_name']) === cName;
            const matchCode = (r['Code'] || r['code'] || '') === cCode;
            return !(matchName && matchCode);
          });
          return {
            ...prev,
            total_campaigns: filtered.length,
            classified_campaigns: filtered.filter(r => r['Heading'] && r['Heading'] !== 'Unassigned').length,
            unassigned_campaigns: filtered.filter(r => !r['Heading'] || r['Heading'] === 'Unassigned').length,
            rules: filtered
          };
        });
      } else {
        setSaveNotification({
          type: 'error',
          title: 'Delete Failed',
          message: data?.detail || 'Failed to delete rule.',
          timestamp: new Date().toLocaleTimeString()
        });
      }
    } catch (err) {
      setSaveNotification({
        type: 'error',
        title: 'Delete Error',
        message: err.message || 'Error communicating with server.',
        timestamp: new Date().toLocaleTimeString()
      });
    }
  };

  const handleExport = (format = 'csv') => {
    const url = `${API_BASE_URL}/api/classifications/export?platform=${platform}&format=${format}&company_id=${encodeURIComponent(activeCompany)}`;
    window.open(url, '_blank');
  };

  const handleImportSubmit = async (e) => {
    e.preventDefault();
    if (isConsolidated) {
      setImportMsg('Importing rules is disabled in Consolidated (All Companies) mode.');
      return;
    }
    if (!importFile) {
      setImportMsg('Please select a CSV or Excel file.');
      return;
    }

    setImporting(true);
    setImportMsg('');

    const formData = new FormData();
    formData.append('file', importFile);
    formData.append('platform', platform);
    formData.append('mode', importMode);
    formData.append('company_id', activeCompany);
    formData.append('user_role', user?.role || 'user');

    try {
      const res = await fetch(`${API_BASE_URL}/api/classifications/bulk-import`, {
        method: 'POST',
        body: formData
      });
      const data = await res.json();
      setImporting(false);

      if (res.ok && data?.status === 'success') {
        setImportMsg(`✅ ${data.message}`);
        setTimeout(() => {
          setShowImportModal(false);
          setImportFile(null);
          setImportMsg('');
          // Re-fetch active matrix
          setLoading(true);
          fetch(`${API_BASE_URL}/api/classifications/${platform}?company_id=${encodeURIComponent(activeCompany)}`)
            .then(r => r.json())
            .then(d => {
              let rules = (d.rules || []).map(r => ({
                ...r,
                'Campaign Name': cleanText(r['Campaign Name']),
                'Community Name': cleanText(r['Community Name']),
                'Heading': cleanText(r['Heading']),
                'Sub-Heading': cleanText(r['Sub-Heading']),
                'Country': cleanText(r['Country']),
                'Code': cleanText(r['Code']),
                'Zakat Eligibility': cleanText(r['Zakat Eligibility']),
                'Campaign URL': r['Campaign URL'] || r['campaign_url'] || ''
              }));
              setMatrixData({
                ...d,
                total_campaigns: rules.length,
                classified_campaigns: rules.filter(r => r['Heading'] && r['Heading'] !== 'Unassigned').length,
                unassigned_campaigns: rules.filter(r => !r['Heading'] || r['Heading'] === 'Unassigned').length,
                rules: rules
              });
              setLoading(false);
            });
        }, 1500);
      } else {
        setImportMsg(`❌ ${data?.detail || 'Bulk import failed.'}`);
      }
    } catch (err) {
      setImporting(false);
      setImportMsg(`❌ Error uploading file: ${err.message}`);
    }
  };

  // Visual Theme Badges per platform
  const bannerStyles = {
    master: {
      container: 'bg-gradient-to-r from-emerald-500/15 via-teal-500/10 to-transparent border-emerald-500/30 text-emerald-900 dark:text-emerald-200',
      iconBg: 'bg-emerald-600 text-white',
      title: 'text-emerald-700 dark:text-emerald-300 font-extrabold',
      subtitle: 'text-slate-600 dark:text-slate-400 font-medium',
      activePill: 'bg-emerald-600 text-white shadow-emerald-500/30',
      countPill: 'border-emerald-500/40 text-emerald-700 dark:text-emerald-300 bg-emerald-50 dark:bg-emerald-950/40'
    },
    launchgood: {
      container: 'bg-gradient-to-r from-teal-500/15 via-cyan-500/10 to-transparent border-teal-500/30 text-teal-900 dark:text-teal-200',
      iconBg: 'bg-teal-500 text-white',
      title: 'text-teal-700 dark:text-teal-300 font-extrabold',
      subtitle: 'text-slate-600 dark:text-slate-400 font-medium',
      activePill: 'bg-teal-600 text-white shadow-teal-500/30',
      countPill: 'border-teal-500/40 text-teal-700 dark:text-teal-300 bg-teal-50 dark:bg-teal-950/40'
    },
    givebright: {
      container: 'bg-gradient-to-r from-purple-500/15 via-indigo-500/10 to-transparent border-purple-500/30 text-purple-900 dark:text-purple-200',
      iconBg: 'bg-purple-600 text-white',
      title: 'text-purple-700 dark:text-purple-300 font-extrabold',
      subtitle: 'text-slate-600 dark:text-slate-400 font-medium',
      activePill: 'bg-purple-600 text-white shadow-purple-500/30',
      countPill: 'border-purple-500/40 text-purple-700 dark:text-purple-300 bg-purple-50 dark:bg-purple-950/40'
    },
    madinah: {
      container: 'bg-gradient-to-r from-teal-500/15 via-emerald-500/10 to-transparent border-teal-500/30 text-teal-900 dark:text-teal-200',
      iconBg: 'bg-teal-600 text-white',
      title: 'text-teal-700 dark:text-teal-300 font-extrabold',
      subtitle: 'text-slate-600 dark:text-slate-400 font-medium',
      activePill: 'bg-teal-600 text-white shadow-teal-500/30',
      countPill: 'border-teal-500/40 text-teal-700 dark:text-teal-300 bg-teal-50 dark:bg-teal-950/40'
    },
    paysuite: {
      container: 'bg-gradient-to-r from-amber-500/15 via-orange-500/10 to-transparent border-amber-500/30 text-amber-900 dark:text-amber-200',
      iconBg: 'bg-amber-600 text-white',
      title: 'text-amber-700 dark:text-amber-300 font-extrabold',
      subtitle: 'text-slate-600 dark:text-slate-400 font-medium',
      activePill: 'bg-amber-600 text-white shadow-amber-500/30',
      countPill: 'border-amber-500/40 text-amber-700 dark:text-amber-300 bg-amber-50 dark:bg-amber-950/40'
    },
    website: {
      container: 'bg-gradient-to-r from-blue-500/15 via-cyan-500/10 to-transparent border-blue-500/30 text-blue-900 dark:text-blue-200',
      iconBg: 'bg-blue-600 text-white',
      title: 'text-blue-700 dark:text-blue-300 font-extrabold',
      subtitle: 'text-slate-600 dark:text-slate-400 font-medium',
      activePill: 'bg-blue-600 text-white shadow-blue-500/30',
      countPill: 'border-blue-500/40 text-blue-700 dark:text-blue-300 bg-blue-50 dark:bg-blue-950/40'
    }
  };

  const bStyles = bannerStyles[platform] || bannerStyles.launchgood;

  return (
    <div className="flex flex-col gap-6 animate-fade-in pb-16 relative">
      {/* 🔔 Floating Real-Time Save & Sync Notifier Toast */}
      {saveNotification && (
        <div 
          className={`fixed top-6 right-6 z-[9999] max-w-md w-[calc(100vw-3rem)] sm:w-96 p-4 rounded-2xl shadow-2xl backdrop-blur-xl border transition-all duration-300 transform translate-y-0 animate-slide-in ${
            saveNotification.type === 'success'
              ? 'bg-emerald-950/95 text-emerald-100 border-emerald-500/50 shadow-emerald-950/50 ring-1 ring-emerald-500/30'
              : saveNotification.type === 'error'
              ? 'bg-rose-950/95 text-rose-100 border-rose-500/50 shadow-rose-950/50 ring-1 ring-rose-500/30'
              : 'bg-slate-900/95 text-slate-100 border-cyan-500/50 shadow-cyan-950/50 ring-1 ring-cyan-500/30'
          }`}
          role="alert"
        >
          <div className="flex items-start gap-3">
            <div className={`p-2 rounded-xl shrink-0 ${
              saveNotification.type === 'success' 
                ? 'bg-emerald-500/20 text-emerald-400' 
                : saveNotification.type === 'error' 
                ? 'bg-rose-500/20 text-rose-400' 
                : 'bg-cyan-500/20 text-cyan-400'
            }`}>
              {saveNotification.type === 'success' ? (
                <CheckCircle className="w-5 h-5 animate-pulse" />
              ) : saveNotification.type === 'error' ? (
                <AlertCircle className="w-5 h-5 animate-bounce" />
              ) : (
                <Zap className="w-5 h-5 animate-pulse" />
              )}
            </div>

            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between gap-2">
                <h4 className="text-xs font-black tracking-tight text-white uppercase">
                  {saveNotification.title}
                </h4>
                <span className="text-[10px] text-slate-400 font-mono">
                  {saveNotification.timestamp}
                </span>
              </div>
              <p className="text-xs text-slate-200 mt-1 leading-relaxed break-words font-medium">
                {saveNotification.message}
              </p>

              {saveNotification.type === 'error' && (
                <div className="mt-3 flex items-center gap-2">
                  <button
                    onClick={handleSave}
                    disabled={saving}
                    className="px-3 py-1 text-xs font-bold rounded-lg bg-rose-600 hover:bg-rose-500 text-white shadow-sm transition-all cursor-pointer flex items-center gap-1.5"
                  >
                    <RefreshCw className={`w-3 h-3 ${saving ? 'animate-spin' : ''}`} />
                    <span>Retry Save & Sync</span>
                  </button>
                </div>
              )}
            </div>

            <button
              onClick={() => setSaveNotification(null)}
              className="text-slate-400 hover:text-white p-1 rounded-lg hover:bg-white/10 transition-colors cursor-pointer shrink-0"
              title="Dismiss notification"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      {/* Inline Save & Sync Status Banner (when active) */}
      {saveNotification && (
        <div className={`p-3.5 rounded-2xl border flex items-center justify-between gap-3 shadow-md transition-all ${
          saveNotification.type === 'success'
            ? 'bg-emerald-500/10 dark:bg-emerald-950/40 border-emerald-500/30 text-emerald-900 dark:text-emerald-200'
            : saveNotification.type === 'error'
            ? 'bg-rose-500/10 dark:bg-rose-950/40 border-rose-500/30 text-rose-900 dark:text-rose-200'
            : 'bg-cyan-500/10 dark:bg-cyan-950/40 border-cyan-500/30 text-cyan-900 dark:text-cyan-200'
        }`}>
          <div className="flex items-center gap-2.5 min-w-0">
            {saveNotification.type === 'success' ? (
              <CheckCircle className="w-4 h-4 text-emerald-600 dark:text-emerald-400 shrink-0" />
            ) : saveNotification.type === 'error' ? (
              <AlertCircle className="w-4 h-4 text-rose-600 dark:text-rose-400 shrink-0" />
            ) : (
              <Zap className="w-4 h-4 text-cyan-600 dark:text-cyan-400 shrink-0" />
            )}
            <div className="text-xs truncate">
              <span className="font-extrabold uppercase mr-2">[{saveNotification.title}]</span>
              <span className="font-medium">{saveNotification.message}</span>
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {saveNotification.type === 'error' && (
              <button
                onClick={handleSave}
                disabled={saving}
                className="px-2.5 py-0.5 text-xs font-bold rounded-lg bg-rose-600 hover:bg-rose-500 text-white transition-all cursor-pointer flex items-center gap-1"
              >
                <RefreshCw className={`w-3 h-3 ${saving ? 'animate-spin' : ''}`} />
                <span>Retry</span>
              </button>
            )}
            <button
              onClick={() => setSaveNotification(null)}
              className="text-slate-400 hover:text-slate-600 dark:hover:text-white p-1 rounded-lg transition-colors cursor-pointer"
              title="Close"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      )}

      {/* Top Header & Platform Selector Bar */}
      <div className="flex flex-wrap items-center justify-between gap-4 pb-2 border-b border-slate-200 dark:border-white/10">
        <div className="flex items-center gap-3">
          <div className="p-3 bg-gradient-to-tr from-teal-600 to-cyan-500 rounded-2xl shadow-lg shadow-cyan-500/20 text-white">
            <Shield className="w-6 h-6" />
          </div>
          <div>
            <h1 className="text-xl font-black tracking-tight text-slate-900 dark:text-white flex items-center gap-2">
              Campaign Classifications
              <span className="text-xs px-2.5 py-0.5 rounded-full font-bold uppercase bg-cyan-100 text-cyan-800 dark:bg-cyan-500/20 dark:text-cyan-400">
                Master Matrix
              </span>
            </h1>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5 font-medium">
              Dynamic classification rules with instant auto-fill, pagination, and multi-platform sync
            </p>
          </div>
        </div>

        {/* Global Action Buttons */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Master Codes Add Button OR Save & Sync Matrix Button */}
          {isSuperAdmin && (
            platform === 'master' ? (
              <button
                onClick={handleOpenAddMasterCode}
                disabled={isConsolidated}
                className={`px-4 py-2 text-xs font-extrabold rounded-xl text-white transition-all flex items-center gap-2 ${
                  isConsolidated 
                    ? 'bg-slate-400 dark:bg-slate-700 opacity-60 cursor-not-allowed' 
                    : 'bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 shadow-md shadow-emerald-500/20 cursor-pointer'
                }`}
                title={isConsolidated ? "Adding master codes is disabled in consolidated mode" : "Create a new Master Project Code in the canonical registry"}
              >
                <Plus className="w-3.5 h-3.5 text-white" />
                <span>Add Master Code</span>
              </button>
            ) : (
              <button
                onClick={handleSave}
                disabled={saving || isConsolidated}
                className={`px-4 py-2 text-xs font-extrabold rounded-xl text-white transition-all flex items-center gap-2 ${
                  isConsolidated 
                    ? 'bg-slate-400 dark:bg-slate-700 opacity-60 cursor-not-allowed' 
                    : 'bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 shadow-md shadow-emerald-500/20 cursor-pointer disabled:opacity-50'
                }`}
                title={isConsolidated ? "Saving is disabled in consolidated mode" : "Save matrix edits and sync classification rules across all donor records"}
              >
                {saving ? (
                  <>
                    <RefreshCw className="w-3.5 h-3.5 animate-spin text-white" />
                    <span>Saving & Syncing...</span>
                  </>
                ) : (
                  <>
                    <Save className="w-3.5 h-3.5 text-white" />
                    <span>Save Matrix & Sync</span>
                  </>
                )}
              </button>
            )
          )}

          {/* Export Dropdown */}
          <div className="flex items-center rounded-xl overflow-hidden border border-slate-200 dark:border-white/10 bg-slate-100 dark:bg-slate-800/60 shadow-sm">
            <button 
              onClick={() => handleExport('csv')}
              className="px-3 py-2 text-xs font-bold text-slate-700 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors flex items-center gap-1.5 cursor-pointer"
              title="Download Rules as CSV"
            >
              <Download className="w-3.5 h-3.5 text-cyan-600 dark:text-cyan-400" />
              <span>CSV</span>
            </button>
            <div className="w-[1px] h-4 bg-slate-300 dark:bg-white/10"></div>
            <button 
              onClick={() => handleExport('xlsx')}
              className="px-3 py-2 text-xs font-bold text-slate-700 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors flex items-center gap-1.5 cursor-pointer"
              title="Download Rules as Excel Spreadsheet"
            >
              <FileSpreadsheet className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" />
              <span>Excel</span>
            </button>
          </div>
        </div>
      </div>

      {/* Consolidated Mode Alert Banner */}
      {isConsolidated && (
        <div className="flex items-center gap-3 p-3.5 rounded-2xl bg-amber-500/10 border border-amber-500/30 text-amber-900 dark:text-amber-200 animate-fadeIn">
          <AlertCircle className="w-5 h-5 text-amber-500 shrink-0" />
          <div className="text-xs">
            <span className="font-bold">Consolidated Mode (All Companies):</span> Showing aggregated rules across all organizations. Adding, editing, importing, and deleting classification rules is disabled in consolidated view. Switch to a specific company in the top navigation to create or modify rules.
          </div>
        </div>
      )}

      {/* 🚀 Platform Selector Pill Buttons */}
      <div className="flex flex-wrap items-center gap-3">
        {/* Master Project Codes Tab */}
        <button 
          onClick={() => handleSelectPlatform('master')}
          className={`relative px-5 py-3 rounded-xl font-bold text-xs flex items-center gap-2.5 transition-all cursor-pointer ${
            platform === 'master'
              ? 'bg-gradient-to-r from-emerald-600 to-teal-600 text-white shadow-md shadow-emerald-500/30 border border-emerald-400 ring-2 ring-emerald-400/40'
              : 'bg-slate-100 hover:bg-slate-200 text-slate-700 dark:bg-slate-900/60 dark:hover:bg-slate-800/80 dark:text-slate-300 border border-slate-300 dark:border-white/5'
          }`}
        >
          <Shield className={`w-4 h-4 ${platform === 'master' ? 'text-white' : 'text-emerald-600 dark:text-emerald-400'}`} />
          <span className="font-bold">🏷️ Master Project Codes</span>
          {platform === 'master' && (
            <span className="flex h-2.5 w-2.5 relative ml-1">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-white opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-white"></span>
            </span>
          )}
        </button>

        {/* LaunchGood Tab (Rethink & Consolidated only) */}
        {!isIqra && (
          <button 
            onClick={() => handleSelectPlatform('launchgood')}
            className={`relative px-5 py-3 rounded-xl font-bold text-xs flex items-center gap-2.5 transition-all cursor-pointer ${
              platform === 'launchgood'
                ? 'bg-gradient-to-r from-teal-600 to-cyan-600 text-white shadow-md shadow-cyan-500/30 border border-cyan-400 ring-2 ring-cyan-400/40'
                : 'bg-slate-100 hover:bg-slate-200 text-slate-700 dark:bg-slate-900/60 dark:hover:bg-slate-800/80 dark:text-slate-300 border border-slate-300 dark:border-white/5'
            }`}
          >
            <Zap className={`w-4 h-4 ${platform === 'launchgood' ? 'text-white' : 'text-teal-600 dark:text-cyan-400'}`} />
            <span className="font-bold">LaunchGood Matrix</span>
            {platform === 'launchgood' && (
              <span className="flex h-2.5 w-2.5 relative ml-1">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-white opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-white"></span>
              </span>
            )}
          </button>
        )}

        {/* GiveBright Tab (Both Rethink & Iqra) */}
        <button 
          onClick={() => handleSelectPlatform('givebright')}
          className={`relative px-5 py-3 rounded-xl font-bold text-xs flex items-center gap-2.5 transition-all cursor-pointer ${
            platform === 'givebright'
              ? 'bg-gradient-to-r from-purple-700 to-indigo-600 text-white shadow-md shadow-purple-500/30 border border-purple-400 ring-2 ring-purple-400/40'
              : 'bg-slate-100 hover:bg-slate-200 text-slate-700 dark:bg-slate-900/60 dark:hover:bg-slate-800/80 dark:text-slate-300 border border-slate-300 dark:border-white/5'
          }`}
        >
          <Gift className={`w-4 h-4 ${platform === 'givebright' ? 'text-white' : 'text-purple-600 dark:text-purple-400'}`} />
          <span className="font-bold">GiveBright Matrix</span>
          {platform === 'givebright' && (
            <span className="flex h-2.5 w-2.5 relative ml-1">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-white opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-white"></span>
            </span>
          )}
        </button>

        {/* Madinah Tab (Iqra & Consolidated) */}
        {(isIqra || isConsolidated) && (
          <button 
            onClick={() => handleSelectPlatform('madinah')}
            className={`relative px-5 py-3 rounded-xl font-bold text-xs flex items-center gap-2.5 transition-all cursor-pointer ${
              platform === 'madinah'
                ? 'bg-gradient-to-r from-teal-600 to-emerald-600 text-white shadow-md shadow-teal-500/30 border border-teal-400 ring-2 ring-teal-400/40'
                : 'bg-slate-100 hover:bg-slate-200 text-slate-700 dark:bg-slate-900/60 dark:hover:bg-slate-800/80 dark:text-slate-300 border border-slate-300 dark:border-white/5'
            }`}
          >
            <Sparkles className={`w-4 h-4 ${platform === 'madinah' ? 'text-white' : 'text-teal-600 dark:text-teal-400'}`} />
            <span className="font-bold">Madinah Matrix</span>
            {platform === 'madinah' && (
              <span className="flex h-2.5 w-2.5 relative ml-1">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-white opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-white"></span>
              </span>
            )}
          </button>
        )}

        {/* Paysuite Tab (Rethink & Consolidated only) */}
        {!isIqra && (
          <button 
            onClick={() => handleSelectPlatform('paysuite')}
            className={`relative px-5 py-3 rounded-xl font-bold text-xs flex items-center gap-2.5 transition-all cursor-pointer ${
              platform === 'paysuite'
                ? 'bg-gradient-to-r from-amber-600 to-orange-600 text-white shadow-md shadow-amber-500/30 border border-amber-400 ring-2 ring-amber-400/40'
                : 'bg-slate-100 hover:bg-slate-200 text-slate-700 dark:bg-slate-900/60 dark:hover:bg-slate-800/80 dark:text-slate-300 border border-slate-300 dark:border-white/5'
            }`}
          >
            <CreditCard className={`w-4 h-4 ${platform === 'paysuite' ? 'text-white' : 'text-amber-600 dark:text-amber-400'}`} />
            <span className="font-bold">Paysuite Matrix</span>
            {platform === 'paysuite' && (
              <span className="flex h-2.5 w-2.5 relative ml-1">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-white opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-white"></span>
              </span>
            )}
          </button>
        )}

        {/* Website Tab (Rethink & Consolidated only) */}
        {!isIqra && (
          <button 
            onClick={() => handleSelectPlatform('website')}
            className={`relative px-5 py-3 rounded-xl font-bold text-xs flex items-center gap-2.5 transition-all cursor-pointer ${
              platform === 'website'
                ? 'bg-gradient-to-r from-blue-600 to-cyan-600 text-white shadow-md shadow-blue-500/30 border border-blue-400 ring-2 ring-blue-400/40'
                : 'bg-slate-100 hover:bg-slate-200 text-slate-700 dark:bg-slate-900/60 dark:hover:bg-slate-800/80 dark:text-slate-300 border border-slate-300 dark:border-white/5'
            }`}
          >
            <Globe className={`w-4 h-4 ${platform === 'website' ? 'text-white' : 'text-blue-600 dark:text-blue-400'}`} />
            <span className="font-bold">Website Matrix</span>
            {platform === 'website' && (
              <span className="flex h-2.5 w-2.5 relative ml-1">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-white opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-white"></span>
              </span>
            )}
          </button>
        )}
      </div>

      {/* 🎯 High-Contrast Active Matrix Banner Indicator */}
      <div className={`p-4 rounded-2xl border flex flex-wrap items-center justify-between gap-4 transition-all ${bStyles.container}`}>
        <div className="flex items-center gap-3.5">
          <span className={`p-2.5 rounded-xl shadow-sm ${bStyles.iconBg}`}>
            {platform === 'master' ? <Shield className="w-5 h-5" /> :
             platform === 'launchgood' ? <Zap className="w-5 h-5" /> :
             platform === 'givebright' ? <Gift className="w-5 h-5" /> :
             platform === 'madinah' ? <Sparkles className="w-5 h-5" /> :
             platform === 'paysuite' ? <CreditCard className="w-5 h-5" /> :
             <Globe className="w-5 h-5" />}
          </span>
          <div>
            <div className="text-xs uppercase tracking-wider flex items-center gap-2.5">
              <span className={bStyles.title}>
                ACTIVE {platform === 'master' ? 'CATALOG' : 'MATRIX'}: {
                  platform === 'master' ? 'Canonical Master Project Codes (Single Source of Truth)' :
                  platform === 'launchgood' ? 'LaunchGood Campaign Master' :
                  platform === 'givebright' ? 'GiveBright Campaign & URL Master' :
                  platform === 'madinah' ? 'Madinah Campaign & URL Master' :
                  platform === 'paysuite' ? 'Paysuite Direct Debit Master' :
                  'Rethink Website Project Master'
                }
              </span>
              <span className={`text-[10px] px-2.5 py-0.5 rounded-full font-extrabold uppercase shadow-sm ${bStyles.activePill}`}>
                ACTIVE
              </span>
            </div>
            <div className={`text-xs mt-0.5 ${bStyles.subtitle}`}>
              {platform === 'master'
                ? 'Single Source of Truth: Canonical Project Codes ➔ Department, Office, Portfolio, Country, Zakat Eligibility'
                : platform === 'givebright' || platform === 'madinah'
                ? 'Hierarchy: Campaign Name & URL ➔ Code ➔ (Department, Office, Portfolio, Country, Zakat Eligibility)'
                : platform === 'paysuite'
                ? 'Hierarchy: Direct Debit Ref (Bank Ref) ➔ Code ➔ (Department, Office, Portfolio, Country, Zakat Eligibility)'
                : platform === 'website'
                ? 'Hierarchy: Project Name (Campaign) ➔ Appeal Name (Community) ➔ Location (Country)'
                : 'Hierarchy: Campaign Name ➔ Code ➔ (Department, Office, Portfolio, Country, Zakat Eligibility)'}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span className={`text-xs font-mono font-extrabold px-3.5 py-1.5 rounded-xl border shadow-sm ${bStyles.countPill}`}>
            {platform === 'master' 
              ? `${matrixData.rules?.length?.toLocaleString() || 0} Project Codes`
              : `${matrixData.total_campaigns?.toLocaleString()} Rules Active`}
          </span>
        </div>
      </div>

      {/* KPI Cards */}
      {platform === 'master' ? (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="glass-panel p-4 border-l-4 border-emerald-500 dark:border-emerald-400">
            <div className="text-xs font-bold text-slate-500 dark:text-slate-400 uppercase">
              Total Master Project Codes
            </div>
            <div className="text-2xl font-black text-slate-900 dark:text-white mt-1">
              {matrixData.rules?.length?.toLocaleString() || 0}
            </div>
          </div>
          <div className="glass-panel p-4 border-l-4 border-teal-500 dark:border-teal-400">
            <div className="text-xs font-bold text-slate-500 dark:text-slate-400 uppercase">
              Total Linked Campaigns
            </div>
            <div className="text-2xl font-black text-teal-600 dark:text-teal-400 mt-1">
              {(matrixData.rules || []).reduce((acc, r) => acc + (r.campaign_count || r['Campaign Count'] || 0), 0).toLocaleString()}
            </div>
          </div>
          <div className="glass-panel p-4 border-l-4 border-cyan-500 dark:border-cyan-400">
            <div className="text-xs font-bold text-slate-500 dark:text-slate-400 uppercase">
              Total Gross Raised Across Codes
            </div>
            <div className="text-2xl font-black text-cyan-600 dark:text-cyan-400 mt-1 font-mono">
              £{(matrixData.rules || []).reduce((acc, r) => acc + (r.total_raised || r['Total Raised'] || 0), 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </div>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className={`glass-panel p-4 border-l-4 ${platform === 'launchgood' ? 'border-teal-500 dark:border-cyan-400' : platform === 'givebright' ? 'border-purple-500 dark:border-purple-400' : platform === 'paysuite' ? 'border-amber-500 dark:border-amber-400' : 'border-blue-500 dark:border-blue-400'}`}>
            <div className="text-xs font-bold text-slate-500 dark:text-slate-400 uppercase">
              {platform === 'paysuite' ? 'Total Tracked Direct Debits' : 'Unique Tracked Campaigns'}
            </div>
            <div className="text-2xl font-black text-slate-900 dark:text-white mt-1">{matrixData.total_campaigns?.toLocaleString()}</div>
          </div>
          <div className="glass-panel p-4 border-l-4 border-emerald-500 dark:border-emerald-400">
            <div className="text-xs font-bold text-slate-500 dark:text-slate-400 uppercase">
              {platform === 'paysuite' ? 'Fully Classified Debits' : 'Fully Classified Campaigns'}
            </div>
            <div className="text-2xl font-black text-emerald-600 dark:text-emerald-400 mt-1">{matrixData.classified_campaigns?.toLocaleString()}</div>
          </div>
          <div className="glass-panel p-4 border-l-4 border-amber-500 dark:border-amber-400">
            <div className="text-xs font-bold text-slate-500 dark:text-slate-400 uppercase">
              {platform === 'paysuite' ? 'Unassigned Debits' : 'Unassigned Campaigns'}
            </div>
            <div className="text-2xl font-black text-amber-600 dark:text-amber-400 mt-1">{matrixData.unassigned_campaigns?.toLocaleString()}</div>
          </div>
        </div>
      )}

      {/* 🚀 Search, Filter & Quick Pagination Controls Bar */}
      <div className="glass-panel p-3.5 rounded-2xl border flex flex-wrap items-center justify-between gap-3 shadow-sm" style={{ borderColor: 'var(--border-glass)' }}>
        {/* Search Box */}
        <div className="relative flex-1 min-w-[260px] max-w-md">
          <Search className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
          <input 
            type="text"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            placeholder={`Search ${matrixData.total_campaigns?.toLocaleString() || 0} ${platform} rules (Name, Code, Country)...`}
            className="w-full pl-9 pr-8 py-2 rounded-xl text-xs border focus:outline-none focus:border-cyan-500 transition-all font-medium"
            style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', borderColor: 'var(--input-border)' }}
          />
          {searchQuery && (
            <button 
              onClick={() => setSearchQuery('')}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-200 p-1 cursor-pointer"
              title="Clear search"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>

        {/* Status Filter Badges */}
        <div className="flex flex-wrap items-center gap-1.5 p-1 rounded-xl bg-slate-100 dark:bg-slate-900/60 border border-slate-200 dark:border-white/5">
          <button
            onClick={() => setStatusFilter('ALL')}
            className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all cursor-pointer ${
              statusFilter === 'ALL'
                ? 'bg-cyan-500 text-white shadow-sm'
                : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
            }`}
          >
            All ({matrixData.rules?.length?.toLocaleString() || 0})
          </button>
          <button
            onClick={() => setStatusFilter('SINGLE_CODE')}
            className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all cursor-pointer flex items-center gap-1.5 ${
              statusFilter === 'SINGLE_CODE'
                ? 'bg-emerald-600 text-white shadow-sm'
                : 'text-emerald-600 dark:text-emerald-400 hover:bg-emerald-500/10'
            }`}
          >
            <span>🟢 Single Code</span>
            <span className="opacity-80">({singleCodeCount.toLocaleString()})</span>
          </button>
          <button
            onClick={() => setStatusFilter('MULTI_CODE')}
            className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all cursor-pointer flex items-center gap-1.5 ${
              statusFilter === 'MULTI_CODE'
                ? 'bg-amber-500 text-slate-950 font-black shadow-sm'
                : 'text-amber-600 dark:text-amber-400 hover:bg-amber-500/10'
            }`}
          >
            <span>🟡 Multi-Code Splits</span>
            <span className="opacity-80">({multiCodeCount.toLocaleString()})</span>
          </button>
          <button
            onClick={() => setStatusFilter('UNASSIGNED')}
            className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all cursor-pointer flex items-center gap-1.5 ${
              statusFilter === 'UNASSIGNED'
                ? 'bg-rose-600 text-white shadow-sm'
                : 'text-rose-600 dark:text-rose-400 hover:bg-rose-500/10'
            }`}
          >
            <span>🔴 Unassigned</span>
            <span className="opacity-80">({unassignedCount.toLocaleString()})</span>
          </button>
        </div>

        {/* Rows Per Page Selector */}
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold text-slate-500 dark:text-slate-400">Rows per page:</span>
          <select
            value={pageSize}
            onChange={e => setPageSize(e.target.value === 'All' ? 'All' : Number(e.target.value))}
            className="border rounded-xl px-2.5 py-1.5 text-xs font-bold focus:outline-none focus:border-cyan-500 transition-all cursor-pointer"
            style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', borderColor: 'var(--input-border)' }}
          >
            <option value={25}>25</option>
            <option value={50}>50</option>
            <option value={100}>100</option>
            <option value={250}>250</option>
          </select>
        </div>
      </div>

      {/* Matrix Rules Grid */}
      {loading ? (
        <div className="py-24 text-center text-slate-500 dark:text-slate-400 font-semibold animate-pulse flex flex-col items-center gap-3">
          <RefreshCw className="w-8 h-8 animate-spin text-teal-600 dark:text-cyan-400" />
          <span>⚡ Loading {platform.toUpperCase()} Classification Rules...</span>
        </div>
      ) : (
        <div className="glass-panel overflow-hidden border border-slate-200 dark:border-white/10 shadow-lg">
          <div className="overflow-x-auto max-h-[640px]">
            <datalist id="known-codes-list">
              {knownCodes.map((c, i) => <option key={i} value={c} />)}
            </datalist>

            {platform === 'master' ? (
              <table className="crm-table w-full">
                <thead>
                  <tr>
                    <th className="w-36 text-left">Code (Master Link)</th>
                    <th className="min-w-[130px] text-left">Programme Fund</th>
                    <th className="min-w-[110px] text-left">Fund Code</th>
                    <th className="min-w-[150px] text-left">Department</th>
                    <th className="min-w-[160px] text-left">Office</th>
                    <th className="min-w-[130px] text-left">Portfolio</th>
                    <th className="min-w-[120px] text-left">Country</th>
                    <th className="w-32 text-left">Zakat Status</th>
                    <th className="min-w-[150px] text-left">Legacy GL (Non-Z / Z)</th>
                    <th className="min-w-[140px] text-left">Old Code(s)</th>
                    <th className="w-28 text-center">Campaigns</th>
                    <th className="w-32 text-right pr-4">Total Raised</th>
                    {isSuperAdmin && <th className="text-center w-24">Action</th>}
                  </tr>
                </thead>
                <tbody>
                  {paginatedRules.length === 0 ? (
                    <tr>
                      <td colSpan={13} className="py-12 text-center text-slate-500 dark:text-slate-400 text-xs font-bold">
                        No master project codes match the active search.
                      </td>
                    </tr>
                  ) : (
                    paginatedRules.map((r, idx) => (
                      <tr key={r._row_id || idx} className="hover:bg-slate-50 dark:hover:bg-emerald-500/5 transition-colors border-b border-slate-200 dark:border-white/5">
                        <td className="py-3 px-3 w-36">
                          <span className="font-mono font-black text-xs text-emerald-700 dark:text-emerald-400 px-2.5 py-1 bg-emerald-100/60 dark:bg-emerald-950/60 rounded-lg border border-emerald-400/40 shadow-xs">
                            {r['Code']}
                          </span>
                        </td>
                        <td className="py-3 px-3 min-w-[130px] text-xs">
                          {r['Programme Fund'] ? (
                            <span className="inline-flex items-center px-2 py-0.5 rounded-md font-bold text-[11px] bg-purple-100 text-purple-800 dark:bg-purple-950/60 dark:text-purple-300 border border-purple-400/30">
                              {r['Programme Fund']}
                            </span>
                          ) : (
                            <span className="text-slate-400 italic text-[11px]">—</span>
                          )}
                        </td>
                        <td className="py-3 px-3 min-w-[110px] text-xs font-mono text-slate-600 dark:text-slate-300">
                          {r['Fund Code'] || '—'}
                        </td>
                        <td className="py-3 px-3 min-w-[150px] font-bold text-xs text-slate-900 dark:text-slate-100">
                          {r['Department'] || 'Unassigned'}
                        </td>
                        <td className="py-3 px-3 min-w-[160px] font-semibold text-xs text-purple-700 dark:text-purple-300">
                          {r['Office'] || 'Unassigned'}
                        </td>
                        <td className="py-3 px-3 min-w-[130px] text-xs text-slate-600 dark:text-slate-300">
                          {r['Portfolio'] ? (
                            <span className="font-semibold text-amber-700 dark:text-amber-300 px-2 py-0.5 rounded-md bg-amber-50 dark:bg-amber-950/40 border border-amber-400/30">
                              {r['Portfolio']}
                            </span>
                          ) : (
                            <span className="text-slate-400 italic text-[11px]">—</span>
                          )}
                        </td>
                        <td className="py-3 px-3 min-w-[120px] font-medium text-xs text-emerald-700 dark:text-emerald-300">
                          {r['Country'] || 'Unassigned'}
                        </td>
                        <td className="py-3 px-3 w-32 text-xs">
                          <span className={`px-2 py-0.5 rounded-md font-bold text-[10px] uppercase ${
                            r['Zakat Eligibility'] === 'Zakat'
                              ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300 border border-emerald-400/40'
                              : 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300 border border-slate-300 dark:border-white/10'
                          }`}>
                            {r['Zakat Eligibility'] || 'Unassigned'}
                          </span>
                        </td>
                        <td className="py-3 px-3 min-w-[150px] text-xs font-mono">
                          <div className="flex flex-col gap-0.5">
                            <span className="text-[10px] text-slate-500 dark:text-slate-400">
                              NZ: <strong className="text-slate-700 dark:text-slate-200">{r['Legacy Non-Zakat GL Code'] || '—'}</strong>
                            </span>
                            <span className="text-[10px] text-emerald-600 dark:text-emerald-400">
                              Z: <strong>{r['Legacy Zakat GL Code'] || '—'}</strong>
                            </span>
                          </div>
                        </td>
                        <td className="py-3 px-3 min-w-[140px] text-xs font-mono text-slate-500 dark:text-slate-400">
                          {r['Old Code(s)'] ? (
                            <span className="bg-slate-100 dark:bg-slate-800/80 px-2 py-0.5 rounded border border-slate-200 dark:border-white/10 text-[11px]">
                              {r['Old Code(s)']}
                            </span>
                          ) : (
                            <span className="text-slate-400 italic text-[11px]">—</span>
                          )}
                        </td>
                        <td className="py-3 px-3 w-28 text-center">
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-bold bg-teal-50 text-teal-800 dark:bg-teal-950/60 dark:text-teal-300 border border-teal-400/30 shadow-xs">
                            🔗 {r['Campaign Count'] || 0}
                          </span>
                        </td>
                        <td className="py-3 px-3 w-32 text-right pr-4 font-mono font-bold text-xs text-cyan-600 dark:text-cyan-400">
                          £{(r['Total Raised'] || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                        </td>
                        {isSuperAdmin && (
                          <td className="text-center py-3 px-3 w-24">
                            <div className="flex items-center justify-center gap-1.5">
                              <button
                                type="button"
                                onClick={() => handleOpenEditMasterCode(r)}
                                className="p-1.5 text-cyan-600 dark:text-cyan-400 hover:text-cyan-800 dark:hover:text-cyan-200 hover:bg-cyan-500/10 rounded-lg transition-colors cursor-pointer"
                                title="Edit Master Project Code"
                              >
                                <Edit3 className="w-4 h-4" />
                              </button>
                              <button 
                                type="button"
                                onClick={() => handleDeleteMasterCode(r)}
                                className="p-1.5 text-rose-500 hover:text-rose-700 hover:bg-rose-500/10 rounded-lg transition-colors cursor-pointer"
                                title="Delete Master Project Code"
                              >
                                <Trash2 className="w-4 h-4" />
                              </button>
                            </div>
                          </td>
                        )}
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            ) : (
              <table className="crm-table w-full">
                <thead>
                  <tr>
                    <th className="min-w-[220px] text-left">{platform === 'paysuite' ? 'Direct Debit Ref (Bank Ref)' : 'Campaign Name'}</th>
                    
                    {/* Paysuite: Donor Name and Email columns */}
                    {platform === 'paysuite' && (
                      <>
                        <th className="min-w-[120px] text-left">Donor Name</th>
                        <th className="min-w-[150px] text-left">Donor Email</th>
                      </>
                    )}

                    {/* LaunchGood & GiveBright: Campaign URL Column */}
                    {platform !== 'paysuite' && (
                      <th className="w-28 text-center">Campaign URL</th>
                    )}

                    {/* LaunchGood & Paysuite: Community Name column (Hidden for GiveBright & Madinah) */}
                    {platform !== 'givebright' && platform !== 'madinah' && (
                      <th className="min-w-[160px] text-left">{platform === 'paysuite' ? 'Platform Source' : 'Community Name'}</th>
                    )}
                    
                    <th className="w-36 text-left">Code (Master Link)</th>
                    <th className="min-w-[170px] text-left">Department</th>
                    <th className="min-w-[190px] text-left">Office</th>
                    <th className="min-w-[150px] text-left">Portfolio</th>
                    <th className="min-w-[150px] text-left">Country</th>
                    <th className="w-40 text-left">Zakat Eligibility</th>
                    {isSuperAdmin && <th className="text-center w-24">Action</th>}
                  </tr>
                </thead>
                <tbody>
                  {paginatedRules.length === 0 ? (
                    <tr>
                      <td colSpan={platform === 'paysuite' || platform === 'givebright' || platform === 'madinah' ? 8 : 9} className="py-12 text-center text-slate-500 dark:text-slate-400 text-xs font-bold">
                        No classification rules match the active search or status filter.
                      </td>
                    </tr>
                  ) : (
                    paginatedRules.map((r, idx) => {
                      const rowUniqueKey = r._row_id || `${r['Campaign Name'] || r['campaign_name']}__${idx}`;
                      const isMulti = r.variants_count > 1 || r.status === 'multi_code';
                      return (
                        <tr key={rowUniqueKey} className="hover:bg-slate-50 dark:hover:bg-cyan-500/5 transition-colors border-b border-slate-200 dark:border-white/5">
                          {/* Campaign Name */}
                          <td className="font-bold text-slate-800 dark:text-slate-100 text-xs py-2.5 px-3 min-w-[220px] max-w-[300px]" title={r['Campaign Name']}>
                            <div className="truncate font-bold text-slate-900 dark:text-slate-100">{r['Campaign Name']}</div>
                            {isMulti && (
                              <div className="flex items-center gap-1.5 mt-1">
                                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-bold bg-amber-100 text-amber-900 dark:bg-amber-950/60 dark:text-amber-300 border border-amber-400/40 shadow-xs">
                                  🟡 {r.variants_count} Code Variants
                                </span>
                                {r.is_primary && (
                                  <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-md text-[9px] font-extrabold bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300 border border-emerald-400/40">
                                    ⭐ Primary
                                  </span>
                                )}
                              </div>
                            )}
                          </td>

                          {/* Paysuite: Donor Name and Email */}
                          {platform === 'paysuite' && (
                            <>
                              <td className="text-slate-600 dark:text-slate-400 text-xs py-2.5 px-3 min-w-[120px] max-w-[150px]" title={r['Donor Name']}>
                                <div className="truncate font-medium">{r['Donor Name'] || 'N/A'}</div>
                              </td>
                              <td className="text-slate-600 dark:text-slate-400 text-xs py-2.5 px-3 min-w-[150px] max-w-[200px]" title={r['Donor Email']}>
                                <div className="truncate font-medium">{r['Donor Email'] || 'N/A'}</div>
                              </td>
                            </>
                          )}

                          {/* Clickable Campaign URL Cell */}
                          {platform !== 'paysuite' && (
                            <td className="py-2 px-2 text-center w-28">
                              {r['Campaign URL'] && r['Campaign URL'] !== '' && r['Campaign URL'] !== 'Unassigned' && r['Campaign URL'] !== 'None' ? (
                                <a 
                                  href={r['Campaign URL'].startsWith('http') ? r['Campaign URL'] : `https://${r['Campaign URL']}`} 
                                  target="_blank" 
                                  rel="noreferrer" 
                                  className="inline-flex items-center gap-1 px-2.5 py-1 bg-cyan-100 text-cyan-800 dark:bg-cyan-500/10 dark:text-cyan-400 hover:bg-cyan-200 dark:hover:bg-cyan-500/20 border border-cyan-300 dark:border-cyan-500/30 rounded-lg text-[11px] font-bold transition-all max-w-[110px] truncate shadow-sm"
                                  title={r['Campaign URL']}
                                >
                                  <ExternalLink className="w-3 h-3 shrink-0" />
                                  <span className="truncate">Open Link</span>
                                </a>
                              ) : (
                                <input
                                  type="text"
                                  disabled={!isSuperAdmin}
                                  value={r['Campaign URL'] || ''}
                                  onChange={e => handleCellChange(r._row_id, 'Campaign URL', e.target.value)}
                                  placeholder="Paste URL..."
                                  className="bg-white dark:bg-slate-900/90 border border-slate-300 dark:border-white/10 rounded-lg px-2 py-1 text-[11px] text-slate-800 dark:text-slate-300 w-24 focus:outline-none focus:border-cyan-500 disabled:opacity-60 font-mono"
                                  title="Paste or edit campaign URL"
                                />
                              )}
                            </td>
                          )}

                          {/* Community Name Cell (Hidden for GiveBright & Madinah) */}
                          {platform !== 'givebright' && platform !== 'madinah' && (
                            <td className="text-slate-600 dark:text-slate-400 text-xs py-2.5 px-3 min-w-[160px] max-w-[220px]" title={r['Community Name']}>
                              <div className="truncate font-medium">{r['Community Name']}</div>
                            </td>
                          )}

                          {/* Editable Code with Datalist & Instant Auto-Fill */}
                          <td className="py-2 px-2 w-36">
                            <input 
                              type="text" 
                              list="known-codes-list"
                              disabled={!isSuperAdmin}
                              value={r['Code'] || ''} 
                              onChange={e => handleCellChange(r._row_id, 'Code', e.target.value)}
                              placeholder="Type Code..."
                              className="bg-white dark:bg-slate-900/90 border border-cyan-400 dark:border-cyan-500/40 rounded-lg px-2.5 py-1.5 text-xs font-mono text-cyan-800 dark:text-cyan-300 font-extrabold w-full focus:outline-none focus:border-cyan-500 disabled:opacity-60 uppercase shadow-sm"
                              title="Changing Code automatically auto-fills Department, Office, Portfolio, Country, and Zakat!"
                            />
                          </td>

                          {/* Editable Department */}
                          <td className="py-2 px-2 min-w-[170px]">
                            <input 
                              type="text" 
                              disabled={!isSuperAdmin}
                              value={r['Department'] || r['Heading'] || ''} 
                              onChange={e => handleCellChange(r._row_id, 'Department', e.target.value)}
                              className="bg-white dark:bg-slate-900/90 border border-slate-300 dark:border-white/10 rounded-lg px-2.5 py-1.5 text-xs text-slate-800 dark:text-slate-200 font-semibold w-full focus:outline-none focus:border-teal-500 dark:focus:border-cyan-400 disabled:opacity-60 shadow-sm"
                              title={r['Department'] || r['Heading']}
                            />
                          </td>

                          {/* Editable Office */}
                          <td className="py-2 px-2 min-w-[190px]">
                            <input 
                              type="text" 
                              disabled={!isSuperAdmin}
                              value={r['Office'] || r['Sub-Heading'] || ''} 
                              onChange={e => handleCellChange(r._row_id, 'Office', e.target.value)}
                              className="bg-white dark:bg-slate-900/90 border border-slate-300 dark:border-white/10 rounded-lg px-2.5 py-1.5 text-xs text-purple-800 dark:text-purple-300 font-semibold w-full focus:outline-none focus:border-purple-500 dark:focus:border-purple-400 disabled:opacity-60 shadow-sm"
                              title={r['Office'] || r['Sub-Heading']}
                            />
                          </td>

                          {/* Editable Portfolio */}
                          <td className="py-2 px-2 min-w-[150px]">
                            <input 
                              type="text" 
                              disabled={!isSuperAdmin}
                              value={r['Portfolio'] || ''} 
                              onChange={e => handleCellChange(r._row_id, 'Portfolio', e.target.value)}
                              placeholder="Portfolio..."
                              className="bg-white dark:bg-slate-900/90 border border-slate-300 dark:border-white/10 rounded-lg px-2.5 py-1.5 text-xs text-amber-800 dark:text-amber-300 font-semibold w-full focus:outline-none focus:border-amber-500 dark:focus:border-amber-400 disabled:opacity-60 shadow-sm placeholder:italic placeholder:font-normal placeholder:text-slate-400"
                              title={r['Portfolio']}
                            />
                          </td>

                          {/* Editable Country */}
                          <td className="py-2 px-2 min-w-[150px]">
                            <input 
                              type="text" 
                              disabled={!isSuperAdmin}
                              value={r['Country'] || ''} 
                              onChange={e => handleCellChange(r._row_id, 'Country', e.target.value)}
                              className="bg-white dark:bg-slate-900/90 border border-slate-300 dark:border-white/10 rounded-lg px-2.5 py-1.5 text-xs text-emerald-800 dark:text-emerald-300 font-semibold w-full focus:outline-none focus:border-emerald-500 dark:focus:border-emerald-400 disabled:opacity-60 shadow-sm"
                              title={r['Country']}
                            />
                          </td>

                          {/* Editable Zakat Eligibility */}
                          <td className="py-2 px-2 w-40">
                            <select 
                              disabled={!isSuperAdmin}
                              value={r['Zakat Eligibility'] || 'Unassigned'} 
                              onChange={e => handleCellChange(r._row_id, 'Zakat Eligibility', e.target.value)}
                              className="bg-white dark:bg-slate-900/90 border border-slate-300 dark:border-white/10 rounded-lg px-2 py-1.5 text-xs font-bold text-slate-800 dark:text-slate-200 w-full focus:outline-none focus:border-teal-500 dark:focus:border-cyan-400 disabled:opacity-60 cursor-pointer shadow-sm"
                            >
                              <option value="Unassigned">Unassigned</option>
                              <option value="Zakat">Zakat</option>
                              <option value="Non-Zakat">Non-Zakat</option>
                            </select>
                          </td>

                          {/* Super Admin Actions: Primary Toggle, Add Code Variant & Delete */}
                          {isSuperAdmin && (
                            <td className="text-center py-2 px-2 w-24">
                              <div className="flex items-center justify-center gap-1">
                                {isMulti && (
                                  <button
                                    type="button"
                                    onClick={() => handleTogglePrimary(r)}
                                    className={`p-1.5 rounded-lg transition-all cursor-pointer ${
                                      r.is_primary 
                                        ? 'text-amber-500 bg-amber-500/20 border border-amber-400' 
                                        : 'text-slate-400 hover:text-amber-400 hover:bg-slate-100 dark:hover:bg-slate-800'
                                    }`}
                                    title={r.is_primary ? 'Current Primary Code for this Campaign' : 'Click to make this the Primary Code for this Campaign'}
                                  >
                                    <span className="text-xs font-bold">{r.is_primary ? '⭐' : '☆'}</span>
                                  </button>
                                )}
                                <button
                                  type="button"
                                  onClick={() => handleDuplicateRule(r)}
                                  className="p-1.5 text-cyan-600 dark:text-cyan-400 hover:text-cyan-800 dark:hover:text-cyan-200 hover:bg-cyan-500/10 rounded-lg transition-colors cursor-pointer"
                                  title="Add another Code variant rule for this campaign"
                                >
                                  <Plus className="w-4 h-4" />
                                </button>
                                <button 
                                  type="button"
                                  onClick={() => handleDeleteRule(r)}
                                  className="p-1.5 text-rose-500 hover:text-rose-700 hover:bg-rose-500/10 rounded-lg transition-colors cursor-pointer"
                                  title="Delete this classification rule"
                                >
                                  <Trash2 className="w-4 h-4" />
                                </button>
                              </div>
                            </td>
                          )}
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            )}
          </div>

          {/* 📑 Bottom Pagination Footer */}
          <div className="p-4 border-t border-slate-200 dark:border-white/10 flex flex-wrap items-center justify-between gap-4 bg-slate-50/50 dark:bg-slate-900/50">
            <div className="text-xs font-bold text-slate-500 dark:text-slate-400">
              {filteredRules.length === 0 ? (
                'No matching campaigns found'
              ) : (
                <>
                  Showing <span className="text-slate-900 dark:text-white font-black">{((safePage - 1) * effectivePageSize) + 1}</span> to <span className="text-slate-900 dark:text-white font-black">{Math.min(safePage * effectivePageSize, filteredRules.length)}</span> of <span className="text-cyan-600 dark:text-cyan-400 font-black">{filteredRules.length.toLocaleString()}</span> rules
                  {searchQuery && <span className="ml-1 text-[11px] text-slate-400 font-normal">(filtered from {matrixData.total_campaigns?.toLocaleString()} total)</span>}
                </>
              )}
            </div>

            {pageSize !== 'All' && totalPages > 1 && (
              <div className="flex items-center gap-2">
                {/* First Page */}
                <button
                  onClick={() => setCurrentPage(1)}
                  disabled={safePage === 1}
                  className="p-2 rounded-xl border border-slate-200 dark:border-white/10 hover:bg-slate-200 dark:hover:bg-slate-800 disabled:opacity-30 disabled:cursor-not-allowed transition-all cursor-pointer text-slate-700 dark:text-slate-300"
                  title="First Page"
                >
                  <ChevronsLeft className="w-3.5 h-3.5" />
                </button>

                {/* Previous Page */}
                <button
                  onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                  disabled={safePage === 1}
                  className="px-3 py-1.5 rounded-xl border border-slate-200 dark:border-white/10 hover:bg-slate-200 dark:hover:bg-slate-800 disabled:opacity-30 disabled:cursor-not-allowed transition-all cursor-pointer text-xs font-bold flex items-center gap-1 text-slate-700 dark:text-slate-300"
                >
                  <ChevronLeft className="w-3.5 h-3.5" /> Prev
                </button>

                {/* Page Numbers */}
                <div className="flex items-center gap-1">
                  {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                    let pNum;
                    if (totalPages <= 5) {
                      pNum = i + 1;
                    } else if (safePage <= 3) {
                      pNum = i + 1;
                    } else if (safePage >= totalPages - 2) {
                      pNum = totalPages - 4 + i;
                    } else {
                      pNum = safePage - 2 + i;
                    }
                    return (
                      <button
                        key={pNum}
                        onClick={() => setCurrentPage(pNum)}
                        className={`w-8 h-8 rounded-xl text-xs font-black transition-all cursor-pointer ${
                          safePage === pNum
                            ? 'bg-gradient-to-r from-teal-500 to-cyan-500 text-white shadow-md shadow-cyan-500/20 ring-2 ring-cyan-400/50'
                            : 'border border-slate-200 dark:border-white/10 hover:bg-slate-200 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300'
                        }`}
                      >
                        {pNum}
                      </button>
                    );
                  })}
                </div>

                {/* Next Page */}
                <button
                  onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                  disabled={safePage === totalPages}
                  className="px-3 py-1.5 rounded-xl border border-slate-200 dark:border-white/10 hover:bg-slate-200 dark:hover:bg-slate-800 disabled:opacity-30 disabled:cursor-not-allowed transition-all cursor-pointer text-xs font-bold flex items-center gap-1 text-slate-700 dark:text-slate-300"
                >
                  Next <ChevronRight className="w-3.5 h-3.5" />
                </button>

                {/* Last Page */}
                <button
                  onClick={() => setCurrentPage(totalPages)}
                  disabled={safePage === totalPages}
                  className="p-2 rounded-xl border border-slate-200 dark:border-white/10 hover:bg-slate-200 dark:hover:bg-slate-800 disabled:opacity-30 disabled:cursor-not-allowed transition-all cursor-pointer text-slate-700 dark:text-slate-300"
                  title="Last Page"
                >
                  <ChevronsRight className="w-3.5 h-3.5" />
                </button>

                {/* Jump To Page */}
                <div className="flex items-center gap-1.5 ml-2 pl-2 border-l border-slate-200 dark:border-white/10">
                  <span className="text-xs text-slate-400 font-semibold">Go to:</span>
                  <input
                    type="number"
                    min={1}
                    max={totalPages}
                    value={jumpPage}
                    onChange={e => setJumpPage(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === 'Enter') {
                        const val = Number(jumpPage);
                        if (val >= 1 && val <= totalPages) {
                          setCurrentPage(val);
                          setJumpPage('');
                        }
                      }
                    }}
                    placeholder={String(safePage)}
                    className="w-12 border rounded-lg px-1.5 py-1 text-xs text-center font-bold focus:outline-none focus:border-cyan-500"
                    style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', borderColor: 'var(--input-border)' }}
                  />
                  <span className="text-xs text-slate-400">/ {totalPages}</span>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* 📂 Bulk Upload / Importer Modal */}
      {showImportModal && isSuperAdmin && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-fade-in">
          <div className="glass-panel p-6 max-w-lg w-full rounded-2xl border border-white/20 shadow-2xl relative bg-white dark:bg-slate-900">
            <div className="flex items-center justify-between pb-4 border-b border-slate-200 dark:border-white/10">
              <div className="flex items-center gap-2">
                <FileSpreadsheet className="w-5 h-5 text-purple-600 dark:text-purple-400" />
                <h3 className="text-base font-extrabold text-slate-900 dark:text-white">
                  Bulk Import {platform.toUpperCase()} Rules
                </h3>
              </div>
              <button 
                onClick={() => setShowImportModal(false)}
                className="p-1 rounded-lg text-slate-400 hover:text-slate-600 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleImportSubmit} className="mt-4 flex flex-col gap-4">
              <div className="text-xs text-slate-600 dark:text-slate-400 leading-relaxed">
                Upload a CSV or Excel file containing classification rules. Required headers include:
                <div className="mt-1.5 font-mono text-[11px] p-2 bg-slate-100 dark:bg-slate-800 rounded-lg text-slate-800 dark:text-slate-200">
                  {platform === 'paysuite' 
                    ? 'Direct Debit Ref (Bank Ref), Platform Source, Code, Department, Office, Portfolio, Country, Zakat Eligibility'
                    : platform === 'givebright' || platform === 'madinah'
                    ? 'Campaign Name, Campaign URL, Code, Department, Office, Portfolio, Country, Zakat Eligibility'
                    : 'Campaign Name, Community Name, Campaign URL, Code, Department, Office, Portfolio, Country, Zakat Eligibility'}
                </div>
              </div>

              {/* Import Mode Selection */}
              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-bold text-slate-700 dark:text-slate-300">Import Strategy</label>
                <div className="grid grid-cols-2 gap-2">
                  <label className={`flex items-center gap-2 p-2.5 rounded-xl border text-xs font-semibold cursor-pointer transition-all ${
                    importMode === 'merge' 
                      ? 'bg-purple-500/10 border-purple-500/40 text-purple-700 dark:text-purple-300 font-bold' 
                      : 'border-slate-200 dark:border-white/10 text-slate-600 dark:text-slate-400'
                  }`}>
                    <input 
                      type="radio" 
                      name="importMode" 
                      value="merge" 
                      checked={importMode === 'merge'} 
                      onChange={() => setImportMode('merge')}
                      className="text-purple-600"
                    />
                    <span>Merge / Upsert (Recommended)</span>
                  </label>

                  <label className={`flex items-center gap-2 p-2.5 rounded-xl border text-xs font-semibold cursor-pointer transition-all ${
                    importMode === 'replace' 
                      ? 'bg-rose-500/10 border-rose-500/40 text-rose-700 dark:text-rose-300 font-bold' 
                      : 'border-slate-200 dark:border-white/10 text-slate-600 dark:text-slate-400'
                  }`}>
                    <input 
                      type="radio" 
                      name="importMode" 
                      value="replace" 
                      checked={importMode === 'replace'} 
                      onChange={() => setImportMode('replace')}
                      className="text-rose-600"
                    />
                    <span>Replace Entire Matrix</span>
                  </label>
                </div>
              </div>

              {/* File Input */}
              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-bold text-slate-700 dark:text-slate-300">Choose File (.csv, .xlsx, .xls)</label>
                <input 
                  type="file" 
                  ref={fileInputRef}
                  accept=".csv, application/vnd.openxmlformats-officedocument.spreadsheetml.sheet, application/vnd.ms-excel"
                  onChange={e => setImportFile(e.target.files[0] || null)}
                  className="text-xs border border-slate-300 dark:border-white/10 rounded-xl p-2 bg-slate-50 dark:bg-slate-800 text-slate-700 dark:text-slate-300 file:mr-3 file:py-1 file:px-3 file:rounded-lg file:border-0 file:text-xs file:font-bold file:bg-purple-600 file:text-white hover:file:bg-purple-700 cursor-pointer"
                />
              </div>

              {importMsg && (
                <div className={`p-3 rounded-xl text-xs font-bold ${
                  importMsg.includes('✅') 
                    ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border border-emerald-500/30'
                    : 'bg-rose-500/10 text-rose-700 dark:text-rose-300 border border-rose-500/30'
                }`}>
                  {importMsg}
                </div>
              )}

              <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-200 dark:border-white/10">
                <button
                  type="button"
                  onClick={() => setShowImportModal(false)}
                  className="px-4 py-2 text-xs font-bold text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-xl transition-colors cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={importing || !importFile}
                  className="px-4 py-2 text-xs font-bold bg-gradient-to-r from-purple-600 to-indigo-600 text-white rounded-xl shadow-lg shadow-purple-500/20 hover:opacity-90 disabled:opacity-50 flex items-center gap-2 cursor-pointer"
                >
                  {importing ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Upload className="w-3.5 h-3.5" />}
                  <span>{importing ? 'Importing...' : 'Upload & Process'}</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* 🏷️ Add / Edit Master Project Code Modal */}
      {masterCodeModal && isSuperAdmin && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-fade-in">
          <div className="glass-panel p-6 max-w-lg w-full rounded-2xl border border-white/20 shadow-2xl relative bg-white dark:bg-slate-900">
            <div className="flex items-center justify-between pb-4 border-b border-slate-200 dark:border-white/10">
              <div className="flex items-center gap-2">
                <Shield className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
                <h3 className="text-base font-extrabold text-slate-900 dark:text-white">
                  {masterCodeModal.isEdit ? `Edit Master Code: ${masterCodeModal.data.code}` : 'Add New Master Project Code'}
                </h3>
              </div>
              <button 
                onClick={() => setMasterCodeModal(null)}
                className="p-1 rounded-lg text-slate-400 hover:text-slate-600 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleSaveMasterCodeSubmit} className="mt-4 flex flex-col gap-4">
              {masterCodeModalMsg && (
                <div className={`p-3 rounded-xl text-xs font-bold ${
                  masterCodeModalMsg.includes('✅') 
                    ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border border-emerald-500/30'
                    : 'bg-rose-500/10 text-rose-700 dark:text-rose-300 border border-rose-500/30'
                }`}>
                  {masterCodeModalMsg}
                </div>
              )}

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5 text-xs">
                {/* Code */}
                <div className="flex flex-col gap-1.5">
                  <label className="text-slate-700 dark:text-slate-300 font-bold uppercase tracking-wider text-[10px]">
                    Project Code *
                  </label>
                  <input
                    type="text"
                    required
                    disabled={masterCodeModal.isEdit}
                    value={masterCodeModal.data.code}
                    onChange={e => setMasterCodeModal(prev => ({ ...prev, data: { ...prev.data, code: e.target.value.toUpperCase() } }))}
                    placeholder="e.g. EM-2024"
                    className="bg-slate-50 dark:bg-slate-950 border border-slate-300 dark:border-white/10 rounded-xl px-3 py-2 text-slate-900 dark:text-white text-xs font-mono font-bold uppercase focus:outline-none focus:border-emerald-500 disabled:opacity-60"
                  />
                </div>

                {/* Department */}
                <div className="flex flex-col gap-1.5">
                  <label className="text-slate-700 dark:text-slate-300 font-bold uppercase tracking-wider text-[10px]">
                    Department *
                  </label>
                  <input
                    type="text"
                    required
                    value={masterCodeModal.data.department}
                    onChange={e => setMasterCodeModal(prev => ({ ...prev, data: { ...prev.data, department: e.target.value } }))}
                    placeholder="e.g. Emergency"
                    className="bg-slate-50 dark:bg-slate-950 border border-slate-300 dark:border-white/10 rounded-xl px-3 py-2 text-slate-900 dark:text-white text-xs font-semibold focus:outline-none focus:border-emerald-500"
                  />
                </div>

                {/* Office */}
                <div className="flex flex-col gap-1.5">
                  <label className="text-slate-700 dark:text-slate-300 font-bold uppercase tracking-wider text-[10px]">
                    Office *
                  </label>
                  <input
                    type="text"
                    required
                    value={masterCodeModal.data.office}
                    onChange={e => setMasterCodeModal(prev => ({ ...prev, data: { ...prev.data, office: e.target.value } }))}
                    placeholder="e.g. Middle East"
                    className="bg-slate-50 dark:bg-slate-950 border border-slate-300 dark:border-white/10 rounded-xl px-3 py-2 text-slate-900 dark:text-white text-xs font-semibold focus:outline-none focus:border-emerald-500"
                  />
                </div>

                {/* Portfolio */}
                <div className="flex flex-col gap-1.5">
                  <label className="text-slate-700 dark:text-slate-300 font-bold uppercase tracking-wider text-[10px]">
                    Portfolio (Optional)
                  </label>
                  <input
                    type="text"
                    value={masterCodeModal.data.portfolio}
                    onChange={e => setMasterCodeModal(prev => ({ ...prev, data: { ...prev.data, portfolio: e.target.value } }))}
                    placeholder="e.g. Water & Sanitation"
                    className="bg-slate-50 dark:bg-slate-950 border border-slate-300 dark:border-white/10 rounded-xl px-3 py-2 text-slate-900 dark:text-white text-xs font-semibold focus:outline-none focus:border-emerald-500"
                  />
                </div>

                {/* Country */}
                <div className="flex flex-col gap-1.5">
                  <label className="text-slate-700 dark:text-slate-300 font-bold uppercase tracking-wider text-[10px]">
                    Country *
                  </label>
                  <input
                    type="text"
                    required
                    value={masterCodeModal.data.country}
                    onChange={e => setMasterCodeModal(prev => ({ ...prev, data: { ...prev.data, country: e.target.value } }))}
                    placeholder="e.g. Palestine"
                    className="bg-slate-50 dark:bg-slate-950 border border-slate-300 dark:border-white/10 rounded-xl px-3 py-2 text-slate-900 dark:text-white text-xs font-semibold focus:outline-none focus:border-emerald-500"
                  />
                </div>

                {/* Zakat Eligibility */}
                <div className="flex flex-col gap-1.5">
                  <label className="text-slate-700 dark:text-slate-300 font-bold uppercase tracking-wider text-[10px]">
                    Zakat Eligibility
                  </label>
                  <select
                    value={masterCodeModal.data.zakat_eligibility}
                    onChange={e => setMasterCodeModal(prev => ({ ...prev, data: { ...prev.data, zakat_eligibility: e.target.value } }))}
                    className="bg-slate-50 dark:bg-slate-950 border border-slate-300 dark:border-white/10 rounded-xl px-3 py-2 text-slate-900 dark:text-white text-xs font-bold focus:outline-none focus:border-emerald-500 cursor-pointer"
                  >
                    <option value="Zakat">Zakat</option>
                    <option value="Non-Zakat">Non-Zakat</option>
                    <option value="Unassigned">Unassigned</option>
                  </select>
                </div>

                {/* Programme Fund */}
                <div className="flex flex-col gap-1.5">
                  <label className="text-slate-700 dark:text-slate-300 font-bold uppercase tracking-wider text-[10px]">
                    Programme Fund
                  </label>
                  <input
                    type="text"
                    list="programme-fund-options"
                    value={masterCodeModal.data.programme_fund || ''}
                    onChange={e => setMasterCodeModal(prev => ({ ...prev, data: { ...prev.data, programme_fund: e.target.value.toUpperCase() } }))}
                    placeholder="e.g. F1-EMR"
                    className="bg-slate-50 dark:bg-slate-950 border border-slate-300 dark:border-white/10 rounded-xl px-3 py-2 text-slate-900 dark:text-white text-xs font-mono font-bold focus:outline-none focus:border-emerald-500"
                  />
                  <datalist id="programme-fund-options">
                    <option value="F1-EMR">F1-EMR (Emergency)</option>
                    <option value="F2-OWH">F2-OWH (Orphan & Widow Care)</option>
                    <option value="F3-FAM">F3-FAM (Family Support & Food)</option>
                    <option value="F4-EDU">F4-EDU (Education)</option>
                    <option value="F5-WAI">F5-WAI (Water & Sanitation)</option>
                    <option value="F6-ZKT">F6-ZKT (General Zakat)</option>
                  </datalist>
                </div>

                {/* Fund Code */}
                <div className="flex flex-col gap-1.5">
                  <label className="text-slate-700 dark:text-slate-300 font-bold uppercase tracking-wider text-[10px]">
                    Fund Code
                  </label>
                  <input
                    type="text"
                    value={masterCodeModal.data.fund_code || ''}
                    onChange={e => setMasterCodeModal(prev => ({ ...prev, data: { ...prev.data, fund_code: e.target.value } }))}
                    placeholder="e.g. 1001-01"
                    className="bg-slate-50 dark:bg-slate-950 border border-slate-300 dark:border-white/10 rounded-xl px-3 py-2 text-slate-900 dark:text-white text-xs font-mono focus:outline-none focus:border-emerald-500"
                  />
                </div>

                {/* Legacy Non-Zakat GL Code */}
                <div className="flex flex-col gap-1.5">
                  <label className="text-slate-700 dark:text-slate-300 font-bold uppercase tracking-wider text-[10px]">
                    Legacy Non-Zakat GL Code
                  </label>
                  <input
                    type="text"
                    value={masterCodeModal.data.legacy_non_zakat_code || ''}
                    onChange={e => setMasterCodeModal(prev => ({ ...prev, data: { ...prev.data, legacy_non_zakat_code: e.target.value } }))}
                    placeholder="e.g. 5001-01"
                    className="bg-slate-50 dark:bg-slate-950 border border-slate-300 dark:border-white/10 rounded-xl px-3 py-2 text-slate-900 dark:text-white text-xs font-mono focus:outline-none focus:border-emerald-500"
                  />
                </div>

                {/* Legacy Zakat GL Code */}
                <div className="flex flex-col gap-1.5">
                  <label className="text-slate-700 dark:text-slate-300 font-bold uppercase tracking-wider text-[10px]">
                    Legacy Zakat GL Code
                  </label>
                  <input
                    type="text"
                    value={masterCodeModal.data.legacy_zakat_code || ''}
                    onChange={e => setMasterCodeModal(prev => ({ ...prev, data: { ...prev.data, legacy_zakat_code: e.target.value } }))}
                    placeholder="e.g. 5001-02"
                    className="bg-slate-50 dark:bg-slate-950 border border-slate-300 dark:border-white/10 rounded-xl px-3 py-2 text-slate-900 dark:text-white text-xs font-mono focus:outline-none focus:border-emerald-500"
                  />
                </div>

                {/* Old Code(s) */}
                <div className="flex flex-col gap-1.5 sm:col-span-2">
                  <label className="text-slate-700 dark:text-slate-300 font-bold uppercase tracking-wider text-[10px]">
                    Old Code(s) (Comma separated aliases)
                  </label>
                  <input
                    type="text"
                    value={masterCodeModal.data.old_codes || ''}
                    onChange={e => setMasterCodeModal(prev => ({ ...prev, data: { ...prev.data, old_codes: e.target.value } }))}
                    placeholder="e.g. EM-PAL-23, EM-PAL-22"
                    className="bg-slate-50 dark:bg-slate-950 border border-slate-300 dark:border-white/10 rounded-xl px-3 py-2 text-slate-900 dark:text-white text-xs font-mono focus:outline-none focus:border-emerald-500"
                  />
                </div>
              </div>

              {/* Description */}
              <div className="flex flex-col gap-1.5 text-xs">
                <label className="text-slate-700 dark:text-slate-300 font-bold uppercase tracking-wider text-[10px]">
                  Description (Optional)
                </label>
                <input
                  type="text"
                  value={masterCodeModal.data.description}
                  onChange={e => setMasterCodeModal(prev => ({ ...prev, data: { ...prev.data, description: e.target.value } }))}
                  placeholder="Brief notes or scope of this project code..."
                  className="bg-slate-50 dark:bg-slate-950 border border-slate-300 dark:border-white/10 rounded-xl px-3 py-2 text-slate-900 dark:text-white text-xs focus:outline-none focus:border-emerald-500"
                />
              </div>

              <div className="flex items-center justify-end gap-2 pt-3 border-t border-slate-200 dark:border-white/10">
                <button
                  type="button"
                  onClick={() => setMasterCodeModal(null)}
                  className="px-4 py-2 text-xs font-bold text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-xl transition-colors cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={savingMasterCode}
                  className="px-5 py-2 text-xs font-bold bg-gradient-to-r from-emerald-600 to-teal-600 text-white rounded-xl shadow-lg shadow-emerald-500/20 hover:opacity-90 disabled:opacity-50 flex items-center gap-2 cursor-pointer"
                >
                  {savingMasterCode ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
                  <span>{savingMasterCode ? 'Saving...' : 'Save & Cascade'}</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
