import React, { useEffect, useState } from 'react';
import { 
  Database, HardDrive, Server, Trash2, Edit, ShieldCheck, UserCheck, Key, 
  Check, X, ShieldAlert, Sparkles, Mail, Save, Upload, FileSpreadsheet, 
  RefreshCw, Building, Image, FileUp, Palette, Plus, Eye 
} from 'lucide-react';
import { API_BASE_URL } from '../config';

export default function AdminView({ user, onDataChange, activeCompany = 'rethink', companies = [], onCompaniesChange }) {
  const [status, setStatus] = useState(null);
  const [tags, setTags] = useState([]);
  const [usersList, setUsersList] = useState([]);
  const [loading, setLoading] = useState(true);
  
  const [oldTag, setOldTag] = useState('');
  const [newTag, setNewTag] = useState('');
  const [msg, setMsg] = useState('');
  const [userMsg, setUserMsg] = useState('');

  const [approvalEmail, setApprovalEmail] = useState('');
  const [emailSaveMsg, setEmailSaveMsg] = useState('');
  const [editingUser, setEditingUser] = useState(null);

  // Upload Raw Dataset State
  const [uploadFile, setUploadFile] = useState(null);
  const [uploadPlatform, setUploadPlatform] = useState('auto');
  const [uploadMode, setUploadMode] = useState('merge');
  const [uploadTargetCompany, setUploadTargetCompany] = useState(activeCompany !== 'all' ? activeCompany : 'rethink');
  const [uploading, setUploading] = useState(false);
  const [uploadMsg, setUploadMsg] = useState('');

  // Multi-Company & Brand Settings State
  const [companiesList, setCompaniesList] = useState(companies || []);
  const [companyModal, setCompanyModal] = useState(null); // { isEdit: bool, data: { id, name, short_code, accent_color, is_active } }
  const [savingCompany, setSavingCompany] = useState(false);
  const [uploadLogoModal, setUploadLogoModal] = useState(null); // { companyId, companyName }
  const [logoFile, setLogoFile] = useState(null);
  const [logoPreview, setLogoPreview] = useState(null);
  const [uploadingLogo, setUploadingLogo] = useState(false);
  const [companyMsg, setCompanyMsg] = useState('');

  // Purge Database State
  const [purgeConfirm, setPurgeConfirm] = useState(false);
  const [purging, setPurging] = useState(false);

  // Purge Payout State
  const [purgePayoutConfirm, setPurgePayoutConfirm] = useState(false);
  const [purgingPayout, setPurgingPayout] = useState(false);

  const isSuperAdmin = user?.role === 'super_admin';
  const canManageTags = isSuperAdmin || user?.can_manage_tags === 1;
  const canPurgeData = isSuperAdmin || user?.can_purge_data === 1;

  const handlePurgePayouts = () => {
    if (!isSuperAdmin) return;
    if (!purgePayoutConfirm) {
      setMsg('❌ Please check the confirmation box before purging payout data.');
      return;
    }
    if (!window.confirm("⚠️ ARE YOU SURE?\nThis will delete all LaunchGood payout settlement records. Raw donor contribution data will remain untouched.")) {
      return;
    }

    setPurgingPayout(true);
    setMsg('');

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
        setPurgingPayout(false);
        if (res?.status === 'success') {
          setMsg(`✅ ${res.message}`);
          setPurgePayoutConfirm(false);
          loadAdminData();
          if (onDataChange) onDataChange();
        } else {
          setMsg(`❌ ${res?.detail || 'Failed to purge payout data.'}`);
        }
      })
      .catch(err => {
        setPurgingPayout(false);
        setMsg(`❌ Error purging payout data: ${err.message}`);
      });
  };

  const handlePurgeDatabase = () => {
    if (!isSuperAdmin) return;
    if (!purgeConfirm) {
      setMsg('❌ Please check the confirmation box before purging database records.');
      return;
    }
    if (!window.confirm("⚠️ ARE YOU ABSOLUTELY SURE?\nThis will permanently wipe all transaction records from the system. This action cannot be undone.")) {
      return;
    }

    setPurging(true);
    setMsg('');

    fetch(`${API_BASE_URL}/api/admin/purge`, {
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
          setMsg(`✅ ${res.message}`);
          setPurgeConfirm(false);
          loadAdminData();
          if (onDataChange) onDataChange();
        } else {
          setMsg(`❌ ${res?.detail || 'Failed to purge database.'}`);
        }
      })
      .catch(err => {
        setPurging(false);
        setMsg(`❌ Error purging database: ${err.message}`);
      });
  };

  const handleUploadData = (e) => {
    e.preventDefault();
    if (!uploadFile) return;
    setUploading(true);
    setUploadMsg('');

    const formData = new FormData();
    formData.append('user_role', user?.role || 'admin');
    formData.append('upload_mode', uploadMode);
    formData.append('platform', uploadPlatform);
    formData.append('company_id', uploadTargetCompany);
    formData.append('file', uploadFile);

    fetch(`${API_BASE_URL}/api/admin/upload-data`, {
      method: 'POST',
      body: formData,
    })
      .then(r => r.json())
      .then(res => {
        setUploading(false);
        if (res.status === 'success') {
          setUploadMsg(`✅ ${res.message}`);
          setUploadFile(null);
          loadAdminData();
          if (onDataChange) onDataChange();
        } else {
          setUploadMsg(`❌ ${res.detail || res.message || 'Failed to upload dataset.'}`);
        }
      })
      .catch(err => {
        setUploading(false);
        setUploadMsg(`❌ Error uploading file: ${err.message}`);
      });
  };

  const loadAdminData = (company = activeCompany) => {
    setLoading(true);
    const compQuery = company ? `?company_id=${encodeURIComponent(company)}` : '';

    fetch(`${API_BASE_URL}/api/admin/status${compQuery}`)
      .then(r => r.ok ? r.json() : null)
      .then(stData => { if (stData) setStatus(stData); })
      .catch(err => console.error('Status fetch error:', err));

    fetch(`${API_BASE_URL}/api/admin/tags${compQuery}`)
      .then(r => r.ok ? r.json() : [])
      .then(tagData => {
        if (Array.isArray(tagData)) {
          setTags(tagData);
          if (tagData.length > 0) setOldTag(tagData[0].source_tag);
          else setOldTag('');
        }
      })
      .catch(err => console.error('Tags fetch error:', err));

    fetch(`${API_BASE_URL}/api/admin/users`)
      .then(r => r.ok ? r.json() : [])
      .then(uData => {
        if (Array.isArray(uData)) setUsersList(uData);
      })
      .catch(err => console.error('Users fetch error:', err));

    fetch(`${API_BASE_URL}/api/expenses/settings`)
      .then(r => r.ok ? r.json() : null)
      .then(expSettings => {
        if (expSettings?.approval_email) setApprovalEmail(expSettings.approval_email);
      })
      .catch(err => console.error('Settings fetch error:', err));

    fetch(`${API_BASE_URL}/api/admin/companies`)
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        if (d?.companies && Array.isArray(d.companies)) {
          setCompaniesList(d.companies);
        }
      })
      .catch(err => console.error('Companies fetch error:', err))
      .finally(() => setLoading(false));
  };

  const loadCompanies = () => {
    fetch(`${API_BASE_URL}/api/admin/companies`)
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        if (d?.companies && Array.isArray(d.companies)) {
          setCompaniesList(d.companies);
        }
      })
      .catch(err => console.error('Error fetching companies:', err));
  };

  const handleSaveCompany = async (e) => {
    e.preventDefault();
    if (!isSuperAdmin || !companyModal?.data) return;
    setSavingCompany(true);
    setCompanyMsg('');

    try {
      const res = await fetch(`${API_BASE_URL}/api/admin/companies`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_role: user?.role,
          id: companyModal.data.id.trim().toLowerCase(),
          name: companyModal.data.name.trim(),
          short_code: companyModal.data.short_code.trim().toUpperCase(),
          accent_color: companyModal.data.accent_color.trim(),
          is_active: companyModal.data.is_active !== undefined ? companyModal.data.is_active : 1
        })
      });
      const data = await res.json();
      setSavingCompany(false);
      if (res.ok && data?.status === 'success') {
        setCompanyMsg(`✅ ${data.message || 'Company saved successfully.'}`);
        setCompanyModal(null);
        loadCompanies();
        if (onCompaniesChange) onCompaniesChange();
        if (onDataChange) onDataChange();
      } else {
        setCompanyMsg(`❌ ${data?.detail || 'Failed to save company.'}`);
      }
    } catch (err) {
      setSavingCompany(false);
      setCompanyMsg(`❌ Error: ${err.message}`);
    }
  };

  const handleUploadLogo = async (e) => {
    e.preventDefault();
    if (!isSuperAdmin || !uploadLogoModal?.companyId || !logoFile) return;
    setUploadingLogo(true);
    setCompanyMsg('');

    const formData = new FormData();
    formData.append('file', logoFile);

    try {
      const res = await fetch(`${API_BASE_URL}/api/admin/companies/${uploadLogoModal.companyId}/logo?user_role=${encodeURIComponent(user?.role)}`, {
        method: 'POST',
        body: formData
      });
      const data = await res.json();
      setUploadingLogo(false);
      if (res.ok && data?.status === 'success') {
        setCompanyMsg(`✅ ${data.message || 'Brand logo uploaded successfully.'}`);
        setUploadLogoModal(null);
        setLogoFile(null);
        setLogoPreview(null);
        loadCompanies();
        if (onCompaniesChange) onCompaniesChange();
        if (onDataChange) onDataChange();
      } else {
        setCompanyMsg(`❌ ${data?.detail || 'Failed to upload brand logo.'}`);
      }
    } catch (err) {
      setUploadingLogo(false);
      setCompanyMsg(`❌ Error: ${err.message}`);
    }
  };

  useEffect(() => {
    loadAdminData(activeCompany);
    if (activeCompany !== 'all') {
      setUploadTargetCompany(activeCompany);
    }
  }, [activeCompany]);

  const handleTogglePermission = (u, field) => {
    if (!isSuperAdmin) return;
    setUserMsg('');

    const updated = {
      user_role: user?.role,
      target_email: u.email,
      new_role: u.role,
      can_edit_donors: field === 'can_edit_donors' ? !u.can_edit_donors : Boolean(u.can_edit_donors),
      can_edit_matrix: field === 'can_edit_matrix' ? !u.can_edit_matrix : Boolean(u.can_edit_matrix),
      can_manage_tags: field === 'can_manage_tags' ? !u.can_manage_tags : Boolean(u.can_manage_tags),
      can_purge_data: field === 'can_purge_data' ? !u.can_purge_data : Boolean(u.can_purge_data),
    };

    fetch(`${API_BASE_URL}/api/admin/users/permissions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updated)
    })
      .then(r => r.json())
      .then(res => {
        if (res?.status === 'success') {
          setUserMsg(`✅ ${res.message}`);
          loadAdminData();
        } else {
          setUserMsg(`❌ ${res.detail || 'Failed to update user permissions.'}`);
        }
      });
  };

  const handleSaveUserEdit = () => {
    if (!isSuperAdmin || !editingUser) return;
    setUserMsg('');

    fetch(`${API_BASE_URL}/api/admin/users/edit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_role: user?.role,
        user_id: editingUser.id,
        email: editingUser.email,
        username: editingUser.username,
        password: editingUser.password || null
      })
    })
      .then(r => r.json())
      .then(res => {
        if (res?.status === 'success') {
          setUserMsg(`✅ ${res.message}`);
          setEditingUser(null);
          loadAdminData();
        } else {
          setUserMsg(`❌ ${res.detail || 'Failed to update user details.'}`);
        }
      })
      .catch(err => {
        setUserMsg(`❌ Error: ${err.message}`);
      });
  };

  const handleAssignPreset = (targetEmail, presetName) => {
    if (!isSuperAdmin) return;
    setUserMsg('');

    fetch(`${API_BASE_URL}/api/admin/users/preset`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_role: user?.role,
        target_email: targetEmail,
        preset_name: presetName
      })
    })
      .then(r => r.json())
      .then(res => {
        if (res?.status === 'success') {
          setUserMsg(`✅ ${res.message}`);
          loadAdminData();
        } else {
          setUserMsg(`❌ ${res.detail || 'Failed to assign preset.'}`);
        }
      });
  };

  const handleRenameTag = (e) => {
    e.preventDefault();
    if (!canManageTags) return;

    fetch(`${API_BASE_URL}/api/admin/tags/rename`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_role: user?.role,
        old_tag: oldTag,
        new_tag: newTag
      })
    })
      .then(r => r.json())
      .then(res => {
        if (res?.status === 'success') {
          setMsg(`✅ ${res.message}`);
          setNewTag('');
          loadAdminData();
        } else {
          setMsg(`❌ ${res.detail || 'Failed to rename tag.'}`);
        }
      });
  };

  const handleDeleteTag = () => {
    if (!canManageTags) return;

    fetch(`${API_BASE_URL}/api/admin/tags/delete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_role: user?.role,
        tag_name: oldTag
      })
    })
      .then(r => r.json())
      .then(res => {
        if (res?.status === 'success') {
          setMsg(`✅ ${res.message}`);
          loadAdminData();
        } else {
          setMsg(`❌ ${res.detail || 'Failed to delete tag.'}`);
        }
      });
  };

  const handleSaveApprovalEmail = (e) => {
    e.preventDefault();
    if (!isSuperAdmin) return;
    setEmailSaveMsg('');

    fetch(`${API_BASE_URL}/api/expenses/settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_role: user?.role,
        approval_email: approvalEmail
      })
    })
      .then(r => r.json())
      .then(res => {
        if (res?.status === 'success') {
          setEmailSaveMsg(`✅ ${res.message}`);
          setTimeout(() => setEmailSaveMsg(''), 3000);
        } else {
          setEmailSaveMsg(`❌ ${res?.detail || 'Failed to update email.'}`);
        }
      });
  };

  const predefinedRoles = [
    {
      name: 'Super Admin',
      preset: 'super_admin',
      badge: 'badge-purple',
      desc: 'Full System Authority. Edit Donors, Classification Matrix, Tags, and Purge Database.',
      donors: true, matrix: true, tags: true, purge: true
    },
    {
      name: 'Data Editor',
      preset: 'data_editor',
      badge: 'badge-cyan',
      desc: 'Operations & Maintenance. Edit Donor Records & Classification Matrix rules. No tag delete or purge.',
      donors: true, matrix: true, tags: false, purge: false
    },
    {
      name: 'Standard Admin',
      preset: 'admin',
      badge: 'badge-emerald',
      desc: 'Read-Only Analyst. View dashboards, search donors, export CSV data. Zero write permissions.',
      donors: false, matrix: false, tags: false, purge: false
    }
  ];

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="text-xl font-extrabold text-white flex items-center gap-2">
          <Database className="w-5 h-5 text-cyan-400" /> System Settings & Access Control Management
        </h2>
        <p className="text-xs text-slate-400">Configure role-based access control (RBAC), assign permissions, inspect storage engines, and manage dataset tags.</p>
      </div>

      {/* System Status Widgets */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="glass-panel p-4 border-l-4 border-cyan-400">
          <div className="text-xs font-bold text-slate-400 uppercase">Total Loaded Records</div>
          <div className="text-2xl font-black text-cyan-400 mt-1">{status?.total_records?.toLocaleString()}</div>
          <div className="text-[11px] text-slate-500 mt-0.5">Parquet & SQLite Query Engine</div>
        </div>

        <div className="glass-panel p-4 border-l-4 border-emerald-400">
          <div className="text-xs font-bold text-slate-400 uppercase">Parquet Storage Size</div>
          <div className="text-2xl font-black text-emerald-400 mt-1">{status?.parquet_size}</div>
          <div className="text-[11px] text-slate-500 mt-0.5">Binary Columnar File Cache</div>
        </div>

        <div className="glass-panel p-4 border-l-4 border-emerald-400">
          <div className="text-xs font-bold text-slate-400 uppercase">Cloud Sync Status</div>
          <div className={`text-2xl font-black mt-1 ${status?.cloud_sync_status === 'ERROR' ? 'text-rose-400' : 'text-emerald-400'}`}>
            {status?.cloud_sync_status === 'SUCCESS' ? 'ACTIVE' : (status?.cloud_sync_status || 'ACTIVE')}
          </div>
          <div className="text-[11px] text-slate-500 mt-0.5">Relational Engine Connected</div>
        </div>
      </div>

      {/* 🏢 Multi-Company Partitioning & Brand Identity Settings Card */}
      {isSuperAdmin && (
        <div className="glass-panel p-5 border-l-4 border-cyan-500 flex flex-col gap-4">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div>
              <h3 className="text-sm font-extrabold text-white flex items-center gap-2">
                <Building className="w-5 h-5 text-cyan-400" /> Multi-Company & Brand Identity Settings
              </h3>
              <p className="text-xs text-slate-400 mt-0.5">
                Manage organization partitions, brand accent colors, and custom brand logos displayed in the top navbar and sidebar navigation.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setCompanyModal({ isEdit: false, data: { id: '', name: '', short_code: '', accent_color: '#06B6D4', is_active: 1 } })}
                className="btn-primary text-xs flex items-center gap-1.5 px-3.5 py-1.5 shadow-md shadow-cyan-500/20 cursor-pointer"
              >
                <Plus className="w-3.5 h-3.5" /> Add Company
              </button>
            </div>
          </div>

          {companyMsg && (
            <div className={`text-xs font-bold p-2.5 rounded-lg border ${
              companyMsg.includes('✅') ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400' : 'bg-rose-500/10 border-rose-500/30 text-rose-400'
            }`}>
              {companyMsg}
            </div>
          )}

          {/* Companies Grid */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {companiesList.map(comp => (
              <div 
                key={comp.id}
                className="bg-slate-900/80 border border-white/10 rounded-2xl p-4 flex flex-col justify-between gap-4 transition-all hover:border-white/20 shadow-lg"
                style={{ borderTop: `4px solid ${comp.accent_color || '#06B6D4'}` }}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-center gap-3">
                    {comp.logo_url ? (
                      <div className="w-12 h-12 rounded-xl bg-white/5 border border-white/10 p-1.5 flex items-center justify-center shrink-0 overflow-hidden shadow-inner">
                        <img 
                          src={comp.logo_url.startsWith('http') ? comp.logo_url : `${API_BASE_URL}${comp.logo_url}`} 
                          alt={comp.name} 
                          className="w-full h-full object-contain"
                          onError={(e) => { e.target.style.display = 'none'; }}
                        />
                      </div>
                    ) : (
                      <div 
                        className="w-12 h-12 rounded-xl flex items-center justify-center font-black text-sm text-white shrink-0 shadow-md"
                        style={{ backgroundColor: comp.accent_color || '#06B6D4' }}
                      >
                        {comp.short_code || comp.id.slice(0, 3).toUpperCase()}
                      </div>
                    )}
                    <div>
                      <div className="font-extrabold text-white text-sm flex items-center gap-1.5">
                        {comp.name}
                        {comp.id === activeCompany && (
                          <span className="text-[9px] px-1.5 py-0.5 rounded font-bold uppercase bg-cyan-500/20 text-cyan-300 border border-cyan-500/30">Active</span>
                        )}
                      </div>
                      <div className="text-[11px] text-slate-400 font-mono mt-0.5">
                        ID: <span className="text-cyan-400">{comp.id}</span>
                      </div>
                    </div>
                  </div>

                  <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ${
                    comp.is_active ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30' : 'bg-rose-500/15 text-rose-400 border border-rose-500/30'
                  }`}>
                    {comp.is_active ? 'Active' : 'Inactive'}
                  </span>
                </div>

                <div className="flex items-center justify-between pt-2 border-t border-white/5 text-xs">
                  <div className="flex items-center gap-2">
                    <span className="text-slate-400 text-[11px]">Brand Color:</span>
                    <span className="w-3.5 h-3.5 rounded-full border border-white/20 inline-block" style={{ backgroundColor: comp.accent_color || '#06B6D4' }}></span>
                    <span className="font-mono text-[10px] text-slate-300">{comp.accent_color || '#06B6D4'}</span>
                  </div>

                  <div className="flex items-center gap-1.5">
                    <button
                      onClick={() => {
                        setUploadLogoModal({ companyId: comp.id, companyName: comp.name });
                        setLogoFile(null);
                        setLogoPreview(comp.logo_url ? (comp.logo_url.startsWith('http') ? comp.logo_url : `${API_BASE_URL}${comp.logo_url}`) : null);
                        setCompanyMsg('');
                      }}
                      className="btn-secondary text-[11px] px-2.5 py-1 text-cyan-400 hover:bg-cyan-500/10 flex items-center gap-1 cursor-pointer"
                      title="Upload custom brand logo"
                    >
                      <Image className="w-3 h-3" /> Logo
                    </button>
                    <button
                      onClick={() => setCompanyModal({
                        isEdit: true,
                        data: {
                          id: comp.id,
                          name: comp.name,
                          short_code: comp.short_code || comp.id.toUpperCase(),
                          accent_color: comp.accent_color || '#06B6D4',
                          is_active: comp.is_active !== undefined ? comp.is_active : 1
                        }
                      })}
                      className="btn-secondary text-[11px] px-2.5 py-1 text-slate-300 hover:bg-white/10 flex items-center gap-1 cursor-pointer"
                      title="Edit Company Details"
                    >
                      <Edit className="w-3 h-3" /> Edit
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Expense Approval Notification Email Settings Card */}
      {isSuperAdmin && (
        <div className="glass-panel p-5 border-l-4 border-cyan-400 flex flex-col gap-4">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div>
              <h3 className="text-sm font-bold text-slate-200 flex items-center gap-2">
                <Mail className="w-4 h-4 text-cyan-400" /> Expense Approval Notification Email Settings
              </h3>
              <p className="text-xs text-slate-400">Configure the Super Admin email address that receives expense approval notification links.</p>
            </div>
            {emailSaveMsg && <div className="text-xs font-bold text-emerald-400">{emailSaveMsg}</div>}
          </div>

          <form onSubmit={handleSaveApprovalEmail} className="flex items-center gap-3 max-w-lg">
            <input 
              type="email" 
              required
              disabled={!isSuperAdmin}
              value={approvalEmail}
              onChange={e => setApprovalEmail(e.target.value)}
              className="bg-slate-900 border border-white/15 rounded-lg px-3 py-2 text-xs text-cyan-300 font-medium flex-1 focus:outline-none focus:border-cyan-400 disabled:opacity-50"
              placeholder="superadmin@analytics.com"
            />
            {isSuperAdmin && (
              <button type="submit" className="btn-primary text-xs flex items-center gap-1.5 whitespace-nowrap">
                <Save className="w-4 h-4" /> Save Email Settings
              </button>
            )}
          </form>
        </div>
      )}

      {/* 📤 Raw Data Ingestion & File Upload Card */}
      <div className="glass-panel p-5 border-l-4 border-emerald-400 flex flex-col gap-4">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div>
            <h3 className="text-sm font-bold text-slate-200 flex items-center gap-2">
              <Upload className="w-4 h-4 text-emerald-400" /> Raw Data Ingestion & File Upload
            </h3>
            <p className="text-xs text-slate-400">
              Upload raw transaction datasets (.csv, .xlsx, .xls) for {uploadTargetCompany === 'iqra' ? 'GiveBrite or Madinah' : 'LaunchGood, GiveBright, Paysuite, or Rethink Website'}.
            </p>
          </div>
          {uploadMsg && (
            <div className={`text-xs font-bold ${uploadMsg.includes('✅') ? 'text-emerald-400' : 'text-rose-400'}`}>
              {uploadMsg}
            </div>
          )}
        </div>

        <form onSubmit={handleUploadData} className="grid grid-cols-1 md:grid-cols-5 gap-3 bg-slate-900/60 p-4 rounded-xl border border-white/10">
          {/* File Input */}
          <div className="flex flex-col gap-1 md:col-span-2">
            <label className="text-[11px] font-bold text-slate-300">Select Dataset File (.csv, .xlsx)</label>
            <input 
              type="file" 
              required
              accept=".csv, .xlsx, .xls"
              onChange={e => setUploadFile(e.target.files[0] || null)}
              className="text-xs text-slate-300 file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:text-xs file:font-bold file:bg-emerald-600 file:text-white hover:file:bg-emerald-700 cursor-pointer"
            />
          </div>

          {/* Target Company Selector */}
          <div className="flex flex-col gap-1">
            <label className="text-[11px] font-bold text-slate-300">Target Company Partition</label>
            <select
              value={uploadTargetCompany}
              onChange={e => {
                const target = e.target.value;
                setUploadTargetCompany(target);
                if (target === 'iqra' && !['auto', 'givebright', 'madinah'].includes(uploadPlatform)) {
                  setUploadPlatform('auto');
                }
              }}
              className="bg-slate-900 border border-white/15 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-emerald-400 cursor-pointer"
            >
              {companiesList.map(c => (
                <option key={c.id} value={c.id}>
                  {c.name} ({c.id})
                </option>
              ))}
            </select>
          </div>

          {/* Platform Platform Selector */}
          <div className="flex flex-col gap-1">
            <label className="text-[11px] font-bold text-slate-300">Data Platform Source</label>
            <select
              value={uploadPlatform}
              onChange={e => setUploadPlatform(e.target.value)}
              className="bg-slate-900 border border-white/15 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-emerald-400 cursor-pointer"
            >
              <option value="auto">Auto-Detect Platform</option>
              {uploadTargetCompany === 'iqra' ? (
                <>
                  <option value="givebright">GiveBrite</option>
                  <option value="madinah">Madinah</option>
                </>
              ) : (
                <>
                  <option value="launchgood">LaunchGood (Raw Donations)</option>
                  <option value="launchgood payout">LaunchGood Payout Settlement</option>
                  <option value="givebright">GiveBright</option>
                  <option value="paysuite">Paysuite</option>
                  <option value="website">Rethink Website</option>
                </>
              )}
            </select>
          </div>

          {/* Upload Strategy */}
          <div className="flex flex-col gap-1">
            <label className="text-[11px] font-bold text-slate-300">Upload Strategy</label>
            <select
              value={uploadMode}
              onChange={e => setUploadMode(e.target.value)}
              className="bg-slate-900 border border-white/15 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-emerald-400 cursor-pointer"
            >
              <option value="merge">Append / Merge Batch</option>
              <option value="replace">Replace Entire Dataset</option>
            </select>
          </div>

          {/* Submit Button */}
          <div className="md:col-span-5 flex justify-end pt-1">
            <button
              type="submit"
              disabled={uploading || !uploadFile}
              className="btn-primary text-xs flex items-center gap-2 px-5 py-2 disabled:opacity-50 cursor-pointer"
            >
              {uploading ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Upload className="w-3.5 h-3.5" />}
              <span>{uploading ? 'Processing & Classifying...' : 'Upload & Auto-Classify Dataset'}</span>
            </button>
          </div>
        </form>
      </div>

      {/* Predefined RBAC Roles Matrix Table */}
      <div className="glass-panel p-5 border-l-4 border-purple-400 flex flex-col gap-4">
        <h3 className="text-sm font-bold text-slate-200 flex items-center gap-2">
          <ShieldCheck className="w-4 h-4 text-purple-400" /> Predefined Role-Based Access Matrix Table
        </h3>

        <div className="overflow-x-auto">
          <table className="crm-table">
            <thead>
              <tr>
                <th>Role Profile</th>
                <th>Description</th>
                <th>Edit Donors</th>
                <th>Edit Matrix</th>
                <th>Manage Tags</th>
                <th>Purge Data</th>
              </tr>
            </thead>
            <tbody>
              {predefinedRoles.map((r, idx) => (
                <tr key={idx}>
                  <td>
                    <span className={`badge ${r.badge}`}>{r.name}</span>
                  </td>
                  <td className="text-xs text-slate-400 max-w-[280px]">{r.desc}</td>
                  <td>{r.donors ? <span className="text-emerald-400 font-bold text-xs flex items-center gap-1"><Check className="w-3.5 h-3.5" /> Allowed</span> : <span className="text-slate-500 text-xs flex items-center gap-1"><X className="w-3.5 h-3.5" /> Restricted</span>}</td>
                  <td>{r.matrix ? <span className="text-emerald-400 font-bold text-xs flex items-center gap-1"><Check className="w-3.5 h-3.5" /> Allowed</span> : <span className="text-slate-500 text-xs flex items-center gap-1"><X className="w-3.5 h-3.5" /> Restricted</span>}</td>
                  <td>{r.tags ? <span className="text-emerald-400 font-bold text-xs flex items-center gap-1"><Check className="w-3.5 h-3.5" /> Allowed</span> : <span className="text-slate-500 text-xs flex items-center gap-1"><X className="w-3.5 h-3.5" /> Restricted</span>}</td>
                  <td>{r.purge ? <span className="text-emerald-400 font-bold text-xs flex items-center gap-1"><Check className="w-3.5 h-3.5" /> Allowed</span> : <span className="text-slate-500 text-xs flex items-center gap-1"><X className="w-3.5 h-3.5" /> Restricted</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* User Accounts & Granular Permission Assign/Revoke Section */}
      {isSuperAdmin && (
        <div className="glass-panel p-5 border-l-4 border-cyan-400 flex flex-col gap-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-bold text-slate-200 flex items-center gap-2">
              <Key className="w-4 h-4 text-cyan-400" /> User Accounts & Access Control Settings
            </h3>
          </div>

          {userMsg && <div className="text-xs font-bold text-emerald-400">{userMsg}</div>}

          <div className="overflow-x-auto">
            <table className="crm-table">
              <thead>
                <tr>
                  <th>User Identity</th>
                  <th>Role</th>
                  <th>Edit Donors</th>
                  <th>Edit Matrix</th>
                  <th>Manage Tags</th>
                  <th>Purge Data</th>
                  <th>Assign Predefined Role</th>
                  {isSuperAdmin && <th>Edit Details</th>}
                </tr>
              </thead>
              <tbody>
                {usersList.map((u, idx) => (
                  <tr key={idx}>
                    <td className="font-bold text-slate-200">
                      {editingUser && editingUser.id === u.id ? (
                        <div className="flex flex-col gap-2 max-w-[200px]">
                          <div className="flex flex-col gap-0.5">
                            <span className="text-[9px] text-slate-500 uppercase font-black">Email Address</span>
                            <input 
                              type="email" 
                              value={editingUser.email}
                              onChange={e => setEditingUser({ ...editingUser, email: e.target.value })}
                              className="bg-slate-900 border border-white/10 rounded px-2.5 py-1 text-xs text-white focus:outline-none focus:border-cyan-400"
                              placeholder="Email"
                            />
                          </div>
                          <div className="flex flex-col gap-0.5">
                            <span className="text-[9px] text-slate-500 uppercase font-black">Username</span>
                            <input 
                              type="text"
                              value={editingUser.username}
                              onChange={e => setEditingUser({ ...editingUser, username: e.target.value })}
                              className="bg-slate-900 border border-white/10 rounded px-2.5 py-1 text-xs text-white focus:outline-none focus:border-cyan-400"
                              placeholder="Username"
                            />
                          </div>
                          <div className="flex flex-col gap-0.5">
                            <span className="text-[9px] text-slate-500 uppercase font-black">Reset Password</span>
                            <input 
                              type="password"
                              value={editingUser.password}
                              onChange={e => setEditingUser({ ...editingUser, password: e.target.value })}
                              className="bg-slate-900 border border-white/10 rounded px-2.5 py-1 text-[10px] text-white focus:outline-none focus:border-cyan-400"
                              placeholder="Type new password (optional)"
                            />
                          </div>
                        </div>
                      ) : (
                        <>
                          <div>{u.email}</div>
                          <div className="text-[10px] text-slate-500 font-normal">@{u.username}</div>
                        </>
                      )}
                    </td>
                    <td>
                      <span className={`badge ${u.role === 'super_admin' ? 'badge-purple' : u.role === 'data_editor' ? 'badge-cyan' : 'badge-emerald'}`}>
                        {u.role}
                      </span>
                    </td>

                    {/* Toggle Granular Permissions */}
                    <td className="text-center">
                      <button 
                        disabled={!isSuperAdmin || u.role === 'super_admin'}
                        onClick={() => handleTogglePermission(u, 'can_edit_donors')}
                        className={`btn-secondary text-[11px] px-2.5 py-1 ${u.can_edit_donors || u.role === 'super_admin' ? 'text-emerald-400 border-emerald-500/30' : 'text-slate-500'}`}
                      >
                        {u.can_edit_donors || u.role === 'super_admin' ? '✓ YES' : '✗ NO'}
                      </button>
                    </td>

                    <td className="text-center">
                      <button 
                        disabled={!isSuperAdmin || u.role === 'super_admin'}
                        onClick={() => handleTogglePermission(u, 'can_edit_matrix')}
                        className={`btn-secondary text-[11px] px-2.5 py-1 ${u.can_edit_matrix || u.role === 'super_admin' ? 'text-emerald-400 border-emerald-500/30' : 'text-slate-500'}`}
                      >
                        {u.can_edit_matrix || u.role === 'super_admin' ? '✓ YES' : '✗ NO'}
                      </button>
                    </td>

                    <td className="text-center">
                      <button 
                        disabled={!isSuperAdmin || u.role === 'super_admin'}
                        onClick={() => handleTogglePermission(u, 'can_manage_tags')}
                        className={`btn-secondary text-[11px] px-2.5 py-1 ${u.can_manage_tags || u.role === 'super_admin' ? 'text-emerald-400 border-emerald-500/30' : 'text-slate-500'}`}
                      >
                        {u.can_manage_tags || u.role === 'super_admin' ? '✓ YES' : '✗ NO'}
                      </button>
                    </td>

                    <td className="text-center">
                      <button 
                        disabled={!isSuperAdmin || u.role === 'super_admin'}
                        onClick={() => handleTogglePermission(u, 'can_purge_data')}
                        className={`btn-secondary text-[11px] px-2.5 py-1 ${u.can_purge_data || u.role === 'super_admin' ? 'text-emerald-400 border-emerald-500/30' : 'text-slate-500'}`}
                      >
                        {u.can_purge_data || u.role === 'super_admin' ? '✓ YES' : '✗ NO'}
                      </button>
                    </td>

                    {/* Quick Preset Assignment */}
                    <td>
                      <div className="flex gap-1">
                        <button 
                          disabled={!isSuperAdmin}
                          onClick={() => handleAssignPreset(u.email, 'super_admin')}
                          className="btn-secondary text-[10px] px-2 py-1 text-purple-400 hover:bg-purple-500/20"
                        >
                          Super Admin
                        </button>
                        <button 
                          disabled={!isSuperAdmin}
                          onClick={() => handleAssignPreset(u.email, 'data_editor')}
                          className="btn-secondary text-[10px] px-2 py-1 text-cyan-400 hover:bg-cyan-500/20"
                        >
                          Data Editor
                        </button>
                        <button 
                          disabled={!isSuperAdmin}
                          onClick={() => handleAssignPreset(u.email, 'admin')}
                          className="btn-secondary text-[10px] px-2 py-1 text-emerald-400 hover:bg-emerald-500/20"
                        >
                          Admin
                        </button>
                      </div>
                    </td>

                    {/* Actions Column */}
                    {isSuperAdmin && (
                      <td>
                        {editingUser && editingUser.id === u.id ? (
                          <div className="flex items-center gap-1.5">
                            <button 
                              onClick={handleSaveUserEdit}
                              className="btn-primary text-[10px] px-2 py-1 text-emerald-400 hover:bg-emerald-500/10 flex items-center gap-0.5"
                              title="Save"
                            >
                              <Check className="w-3.5 h-3.5" /> Save
                            </button>
                            <button 
                              onClick={() => setEditingUser(null)}
                              className="btn-secondary text-[10px] px-2 py-1 text-rose-400 hover:bg-rose-500/10 flex items-center gap-0.5"
                              title="Cancel"
                            >
                              <X className="w-3.5 h-3.5" /> Cancel
                            </button>
                          </div>
                        ) : (
                          <button 
                            onClick={() => setEditingUser({ id: u.id, email: u.email, username: u.username, password: '' })}
                            className="btn-secondary text-[10px] px-2.5 py-1 text-cyan-400 hover:bg-cyan-500/10 flex items-center gap-1"
                            title="Edit User Details"
                          >
                            <Edit className="w-3.5 h-3.5" /> Edit
                          </button>
                        )}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Dataset Tag Manager */}
      <div className={`grid grid-cols-1 ${canManageTags ? 'lg:grid-cols-2' : ''} gap-6`}>
        <div className="glass-panel p-5 border-l-4 border-amber-400 flex flex-col gap-4">
          <h3 className="text-sm font-bold text-slate-200">🏷️ Active Dataset Source Tags ({tags.length})</h3>

          <div className="overflow-x-auto">
            <table className="crm-table">
              <thead>
                <tr>
                  <th>Source Tag</th>
                  <th>Record Count</th>
                </tr>
              </thead>
              <tbody>
                {tags.map((t, idx) => (
                  <tr key={idx}>
                    <td className="font-bold text-slate-200">{t.source_tag}</td>
                    <td className="font-semibold text-cyan-400">{t.record_count?.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Tag Operations */}
        {canManageTags && (
          <div className="glass-panel p-5 border-l-4 border-cyan-400 flex flex-col gap-4">
            <h3 className="text-sm font-bold text-slate-200">✏️ Tag Operations & Batch Management</h3>

            <form onSubmit={handleRenameTag} className="flex flex-col gap-3">
              <div>
                <label className="text-xs text-slate-400 font-bold mb-1 block">Select Dataset Tag</label>
                <select 
                  value={oldTag} 
                  onChange={e => setOldTag(e.target.value)}
                  className="w-full bg-slate-900 border border-white/10 rounded-xl p-2 text-xs text-white"
                >
                  {tags.map((t, idx) => <option key={idx} value={t.source_tag}>{t.source_tag}</option>)}
                </select>
              </div>

              <div>
                <label className="text-xs text-slate-400 font-bold mb-1 block">New Corrected Tag Name</label>
                <input 
                  type="text"
                  placeholder="e.g. Ramadan 2025"
                  value={newTag}
                  onChange={e => setNewTag(e.target.value)}
                  className="w-full bg-slate-900 border border-white/10 rounded-xl p-2 text-xs text-white"
                />
              </div>

              <div className="flex gap-2 mt-2">
                <button type="submit" className="btn-primary text-xs flex-1">✏️ Rename Selected Tag</button>
                <button type="button" onClick={handleDeleteTag} className="btn-secondary text-xs hover:bg-rose-500/20 hover:text-rose-400">🗑️ Delete Batch</button>
              </div>
            </form>
          </div>
        )}
      </div>

      {/* 🔥 Purge LaunchGood Payout Settlement Data Only (Super Admin Only) */}
      {canPurgeData && (
        <div className="glass-panel p-5 border-l-4 border-amber-500 bg-amber-500/5 flex flex-col gap-4">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div>
              <h3 className="text-sm font-black text-amber-600 dark:text-amber-400 flex items-center gap-2 uppercase tracking-wider">
                <Trash2 className="w-5 h-5 text-amber-500" /> Purge LaunchGood Payout Data Only
              </h3>
              <p className="text-xs text-slate-600 dark:text-slate-400 mt-1 font-medium">
                Deletes all LaunchGood payout settlement transaction records from database storage. Raw donor contribution reports will <span className="font-bold text-emerald-500">NOT</span> be deleted.
              </p>
            </div>
            <span className="px-2.5 py-1 rounded-full text-[10px] font-extrabold uppercase bg-amber-500/20 text-amber-400 border border-amber-500/30">
              SUPER ADMIN ACTION
            </span>
          </div>

          <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4 p-4 rounded-xl border border-amber-500/20 bg-amber-950/20">
            <label className="flex items-center gap-3 text-xs font-bold text-slate-700 dark:text-slate-300 cursor-pointer select-none">
              <input 
                type="checkbox" 
                checked={purgePayoutConfirm}
                onChange={e => setPurgePayoutConfirm(e.target.checked)}
                className="w-4 h-4 text-amber-600 rounded border-slate-300 focus:ring-amber-500 cursor-pointer"
              />
              <span>I confirm that I want to delete all LaunchGood payout settlement records.</span>
            </label>

            <button
              onClick={handlePurgePayouts}
              disabled={purgingPayout || !purgePayoutConfirm}
              className="px-5 py-2 rounded-xl text-xs font-black bg-gradient-to-r from-amber-600 to-orange-700 hover:from-amber-700 hover:to-orange-800 text-white shadow-lg shadow-amber-500/20 disabled:opacity-40 disabled:cursor-not-allowed transition-all flex items-center gap-2 cursor-pointer shrink-0"
            >
              {purgingPayout ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
              <span>{purgingPayout ? 'Purging Payouts...' : '🔥 Purge Payout Data'}</span>
            </button>
          </div>
        </div>
      )}

      {/* 🔥 Purge All Database Records (Super Admin Only) */}
      {canPurgeData && (
        <div className="glass-panel p-5 border-l-4 border-rose-500 bg-rose-500/5 flex flex-col gap-4">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div>
              <h3 className="text-sm font-black text-rose-600 dark:text-rose-400 flex items-center gap-2 uppercase tracking-wider">
                <ShieldAlert className="w-5 h-5 text-rose-500 animate-pulse" /> Purge All Database Records
              </h3>
              <p className="text-xs text-slate-600 dark:text-slate-400 mt-1 font-medium">
                Wipes all donor transactions from SQLite and Parquet database storage. Classification rules and user accounts will remain intact.
              </p>
            </div>
            <span className="px-2.5 py-1 rounded-full text-[10px] font-extrabold uppercase bg-rose-500/20 text-rose-400 border border-rose-500/30">
              SUPER ADMIN ACTION
            </span>
          </div>

          <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4 p-4 rounded-xl border border-rose-500/20 bg-rose-950/20">
            <label className="flex items-center gap-3 text-xs font-bold text-slate-700 dark:text-slate-300 cursor-pointer select-none">
              <input 
                type="checkbox" 
                checked={purgeConfirm}
                onChange={e => setPurgeConfirm(e.target.checked)}
                className="w-4 h-4 text-rose-600 rounded border-slate-300 focus:ring-rose-500 cursor-pointer"
              />
              <span>I confirm that I want to permanently delete all donation records.</span>
            </label>

            <button
              onClick={handlePurgeDatabase}
              disabled={purging || !purgeConfirm}
              className="px-5 py-2 rounded-xl text-xs font-black bg-gradient-to-r from-rose-600 to-red-700 hover:from-rose-700 hover:to-red-800 text-white shadow-lg shadow-rose-500/20 disabled:opacity-40 disabled:cursor-not-allowed transition-all flex items-center gap-2 cursor-pointer shrink-0"
            >
              {purging ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
              <span>{purging ? 'Purging Database...' : '🔥 Purge All Data'}</span>
            </button>
          </div>
        </div>
      )}

      {/* 🏢 Create / Edit Company Modal */}
      {companyModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-fadeIn">
          <div className="glass-panel max-w-md w-full p-6 rounded-2xl border border-cyan-500/30 shadow-2xl bg-slate-900 text-white flex flex-col gap-4">
            <div className="flex items-center justify-between border-b border-white/10 pb-3">
              <h3 className="text-sm font-extrabold flex items-center gap-2">
                <Building className="w-4 h-4 text-cyan-400" />
                {companyModal.isEdit ? `Edit Company: ${companyModal.data.name}` : 'Register New Company Partition'}
              </h3>
              <button onClick={() => setCompanyModal(null)} className="text-slate-400 hover:text-white cursor-pointer">
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleSaveCompany} className="flex flex-col gap-3">
              <div>
                <label className="text-xs font-bold text-slate-300 block mb-1">Company ID (Unique Slug)</label>
                <input
                  type="text"
                  required
                  disabled={companyModal.isEdit}
                  placeholder="e.g. iqra, sp, charity_uk"
                  value={companyModal.data.id}
                  onChange={e => setCompanyModal({
                    ...companyModal,
                    data: { ...companyModal.data, id: e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, '') }
                  })}
                  className="w-full bg-slate-950 border border-white/15 rounded-xl px-3 py-2 text-xs text-white focus:outline-none focus:border-cyan-400 disabled:opacity-50 font-mono"
                />
                <span className="text-[10px] text-slate-500">Lowercase letters, numbers, hyphens, or underscores only.</span>
              </div>

              <div>
                <label className="text-xs font-bold text-slate-300 block mb-1">Display Name</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Iqra International"
                  value={companyModal.data.name}
                  onChange={e => setCompanyModal({
                    ...companyModal,
                    data: { ...companyModal.data, name: e.target.value }
                  })}
                  className="w-full bg-slate-950 border border-white/15 rounded-xl px-3 py-2 text-xs text-white focus:outline-none focus:border-cyan-400"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-bold text-slate-300 block mb-1">Short Code / Badge</label>
                  <input
                    type="text"
                    required
                    maxLength={6}
                    placeholder="e.g. IQRA"
                    value={companyModal.data.short_code}
                    onChange={e => setCompanyModal({
                      ...companyModal,
                      data: { ...companyModal.data, short_code: e.target.value.toUpperCase() }
                    })}
                    className="w-full bg-slate-950 border border-white/15 rounded-xl px-3 py-2 text-xs text-white focus:outline-none focus:border-cyan-400 font-mono"
                  />
                </div>

                <div>
                  <label className="text-xs font-bold text-slate-300 block mb-1">Brand Accent Color</label>
                  <div className="flex items-center gap-2">
                    <input
                      type="color"
                      value={companyModal.data.accent_color || '#06B6D4'}
                      onChange={e => setCompanyModal({
                        ...companyModal,
                        data: { ...companyModal.data, accent_color: e.target.value }
                      })}
                      className="w-8 h-8 rounded-lg border-0 bg-transparent cursor-pointer"
                    />
                    <input
                      type="text"
                      value={companyModal.data.accent_color || '#06B6D4'}
                      onChange={e => setCompanyModal({
                        ...companyModal,
                        data: { ...companyModal.data, accent_color: e.target.value }
                      })}
                      className="w-full bg-slate-950 border border-white/15 rounded-xl px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-cyan-400 font-mono"
                    />
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-2 pt-2">
                <label className="flex items-center gap-2 text-xs font-bold text-slate-300 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={companyModal.data.is_active === 1}
                    onChange={e => setCompanyModal({
                      ...companyModal,
                      data: { ...companyModal.data, is_active: e.target.checked ? 1 : 0 }
                    })}
                    className="rounded border-white/20 text-cyan-500 focus:ring-cyan-500 cursor-pointer"
                  />
                  <span>Active & Accessible in Company Switcher</span>
                </label>
              </div>

              <div className="flex justify-end gap-2 pt-3 border-t border-white/10 mt-2">
                <button
                  type="button"
                  onClick={() => setCompanyModal(null)}
                  className="btn-secondary text-xs px-4 py-2 cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={savingCompany}
                  className="btn-primary text-xs px-5 py-2 flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
                >
                  {savingCompany ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
                  <span>{savingCompany ? 'Saving...' : 'Save Company'}</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* 🖼️ Upload Brand Logo Modal */}
      {uploadLogoModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-fadeIn">
          <div className="glass-panel max-w-md w-full p-6 rounded-2xl border border-cyan-500/30 shadow-2xl bg-slate-900 text-white flex flex-col gap-4">
            <div className="flex items-center justify-between border-b border-white/10 pb-3">
              <h3 className="text-sm font-extrabold flex items-center gap-2">
                <Image className="w-4 h-4 text-cyan-400" />
                Upload Brand Logo for {uploadLogoModal.companyName}
              </h3>
              <button onClick={() => setUploadLogoModal(null)} className="text-slate-400 hover:text-white cursor-pointer">
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleUploadLogo} className="flex flex-col gap-4">
              <p className="text-xs text-slate-400">
                Upload a transparent PNG, SVG, or high-res JPG/WebP logo. It will automatically update the CRM top navbar and sidebar.
              </p>

              {logoPreview && (
                <div className="p-4 rounded-xl bg-slate-950/60 border border-white/10 flex flex-col items-center justify-center gap-2">
                  <span className="text-[10px] text-slate-500 uppercase font-black">Logo Preview</span>
                  <div className="w-32 h-16 flex items-center justify-center p-2 rounded-lg bg-white/5 border border-white/10">
                    <img src={logoPreview} alt="Preview" className="max-h-full max-w-full object-contain" />
                  </div>
                </div>
              )}

              <div>
                <label className="text-xs font-bold text-slate-300 block mb-1.5">Select Image File</label>
                <input
                  type="file"
                  required
                  accept="image/png, image/jpeg, image/svg+xml, image/webp"
                  onChange={e => {
                    const f = e.target.files[0];
                    setLogoFile(f || null);
                    if (f) {
                      const reader = new FileReader();
                      reader.onload = (re) => setLogoPreview(re.target.result);
                      reader.readAsDataURL(f);
                    }
                  }}
                  className="text-xs text-slate-300 file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:text-xs file:font-bold file:bg-cyan-600 file:text-white hover:file:bg-cyan-700 cursor-pointer"
                />
              </div>

              <div className="flex justify-end gap-2 pt-3 border-t border-white/10">
                <button
                  type="button"
                  onClick={() => setUploadLogoModal(null)}
                  className="btn-secondary text-xs px-4 py-2 cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={uploadingLogo || !logoFile}
                  className="btn-primary text-xs px-5 py-2 flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
                >
                  {uploadingLogo ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Upload className="w-3.5 h-3.5" />}
                  <span>{uploadingLogo ? 'Uploading...' : 'Save & Apply Logo'}</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
