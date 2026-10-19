import React, { useState, useEffect, useMemo } from 'react';
import { 
  HeartHandshake, X, Calendar, Layers, Search, Check, RefreshCw, CheckCircle2, Link2, AlertTriangle, Loader2
} from 'lucide-react';
import { API_BASE_URL } from '../config';

export default function FundraiserFormModal({
  isOpen,
  onClose,
  editingFundraiser,
  availableCampaigns = [],
  onSuccess,
  isSuperAdmin,
  user,
  activeCompany = 'rethink'
}) {
  // Form fields state (decoupled so typing in text inputs doesn't trigger campaign re-filtering)
  const [formFields, setFormFields] = useState({
    name: '',
    email: '',
    phone: '',
    target_goal: '',
    start_date: '',
    status: 'ACTIVE',
    notes: ''
  });

  // Assigned campaigns state
  const [assignedCampaigns, setAssignedCampaigns] = useState([]);

  // Campaign search & filter toolbar
  const [campaignSearch, setCampaignSearch] = useState('');
  const [platformFilter, setPlatformFilter] = useState('ALL');
  const [assignmentFilter, setAssignmentFilter] = useState('ALL'); // 'ALL', 'UNASSIGNED', 'ASSIGNED_THIS'

  // Page links (fundraiser page / community-team page / campaign link) - attributed live, by URL
  const [pageLinks, setPageLinks] = useState([]);
  const [linkType, setLinkType] = useState('fundraiser_url');
  const [linkInput, setLinkInput] = useState('');
  const [linkCheck, setLinkCheck] = useState(null);   // { loading } | { error } | resolve-link result
  const [statusOptions, setStatusOptions] = useState(['ACTIVE', 'PAUSED', 'COMPLETED', 'RAMADAN']);
  const [customStatus, setCustomStatus] = useState(false);
  const [pageGroup, setPageGroup] = useState('');  // '' automatic | 'MAIN' | 'SP'

  // Submission & feedback state
  const [submitting, setSubmitting] = useState(false);
  const [formMsg, setFormMsg] = useState('');

  // Sync state whenever modal opens or editingFundraiser changes
  useEffect(() => {
    if (!isOpen) return;

    if (editingFundraiser) {
      setFormFields({
        name: editingFundraiser.name || '',
        email: editingFundraiser.email || '',
        phone: editingFundraiser.phone || '',
        target_goal: editingFundraiser.target_goal || '',
        start_date: editingFundraiser.start_date !== 'N/A' ? editingFundraiser.start_date : '',
        status: editingFundraiser.status || 'ACTIVE',
        notes: editingFundraiser.notes || ''
      });
      setPageGroup(editingFundraiser.page_group_explicit ? (editingFundraiser.page_group || '') : '');
      // Pre-fill from what is actually SAVED for this fundraiser (tracked_pages), not from every campaign its
      // donations came from - an assigned campaign now claims all of its donations.
      if (Array.isArray(editingFundraiser.tracked_pages)) {
        const saved = editingFundraiser.tracked_pages;
        setAssignedCampaigns(saved.filter(p => p.match_type === 'campaign_name').map(p => ({
          campaign_name: p.value, code: p.code || 'ALL', platform: 'ALL'
        })));
        setPageLinks(saved.filter(p => p.match_type !== 'campaign_name').map(p => ({
          match_type: p.match_type, match_value: p.value, donations: p.donations_all_time, raised: p.raised_all_time
        })));
      } else {
        setAssignedCampaigns(
          (editingFundraiser.assigned_campaigns || []).map(c => ({
            campaign_name: c.campaign_name,
            code: c.code || 'ALL',
            platform: c.platform || 'ALL'
          }))
        );
        setPageLinks([]);
      }
    } else {
      setFormFields({
        name: '',
        email: '',
        phone: '',
        target_goal: '',
        start_date: '',
        status: 'ACTIVE',
        notes: ''
      });
      setAssignedCampaigns([]);
      setPageLinks([]);
      setPageGroup('');
    }
    setLinkInput('');
    setLinkCheck(null);
    setCustomStatus(false);
    fetch(`${API_BASE_URL}/api/fundraisers/statuses?company_id=${encodeURIComponent(activeCompany)}`)
      .then(r => (r.ok ? r.json() : null))
      .then(d => { if (d?.statuses) setStatusOptions(d.statuses); })
      .catch(() => {});

    setFormMsg('');
    setCampaignSearch('');
    setPlatformFilter('ALL');
    setAssignmentFilter('ALL');
  }, [isOpen, editingFundraiser]);

  // Fast O(1) Set lookup for assigned campaigns
  // Key format: lowercase campaign_name ::: lowercase code
  const assignedKeysSet = useMemo(() => {
    const set = new Set();
    for (const c of assignedCampaigns) {
      const cname = (c.campaign_name || '').toLowerCase().trim();
      const code = (c.code || 'ALL').toLowerCase().trim();
      set.add(`${cname}:::${code}`);
    }
    return set;
  }, [assignedCampaigns]);

  // Filter available campaigns: only recomputes when campaign filters or assignments change
  // Completely immune to typing in name, goal, email, phone, etc.!
  const filteredAvailableCampaigns = useMemo(() => {
    const q = campaignSearch.toLowerCase().trim();
    const p = platformFilter.toLowerCase();

    return availableCampaigns.filter(c => {
      if (q) {
        const matchSearch =
          (c.campaign_name && c.campaign_name.toLowerCase().includes(q)) ||
          (c.code && c.code.toLowerCase().includes(q)) ||
          (c.heading && c.heading.toLowerCase().includes(q)) ||
          (c.country && c.country.toLowerCase().includes(q));
        if (!matchSearch) return false;
      }

      if (platformFilter !== 'ALL') {
        if ((c.platform || '').toLowerCase() !== p) return false;
      }

      if (assignmentFilter !== 'ALL') {
        const key = `${(c.campaign_name || '').toLowerCase().trim()}:::${(c.code || 'ALL').toLowerCase().trim()}`;
        const isAssigned = assignedKeysSet.has(key);
        if (assignmentFilter === 'UNASSIGNED' && isAssigned) return false;
        if (assignmentFilter === 'ASSIGNED_THIS' && !isAssigned) return false;
      }

      return true;
    });
  }, [availableCampaigns, campaignSearch, platformFilter, assignmentFilter, assignedKeysSet]);

  // Cap rendered DOM elements to 80 items to prevent massive browser layout/paint lag
  const displayedCampaigns = useMemo(() => {
    return filteredAvailableCampaigns.slice(0, 80);
  }, [filteredAvailableCampaigns]);

  // Toggle Campaign Assignment
  const handleToggleCampaignAssignment = (camp) => {
    const key = `${(camp.campaign_name || '').toLowerCase().trim()}:::${(camp.code || 'ALL').toLowerCase().trim()}`;
    if (assignedKeysSet.has(key)) {
      setAssignedCampaigns(prev =>
        prev.filter(
          c =>
            `${(c.campaign_name || '').toLowerCase().trim()}:::${(c.code || 'ALL').toLowerCase().trim()}` !== key
        )
      );
    } else {
      setAssignedCampaigns(prev => [
        ...prev,
        {
          campaign_name: camp.campaign_name,
          code: camp.code || 'ALL',
          platform: camp.platform || 'ALL'
        }
      ]);
    }
  };

  const LINK_TYPES = [
    ['fundraiser_url', 'Fundraiser page'],
    ['community_url', 'Community / team page'],
    ['campaign_url', 'Campaign link'],
  ];
  const linkLabel = (t) => (LINK_TYPES.find(x => x[0] === t) || [t, t])[1];

  const checkLink = () => {
    const url = linkInput.trim();
    if (!url) return;
    setLinkCheck({ loading: true });
    const qs = new URLSearchParams({ company_id: activeCompany, url, match_type: linkType });
    if (editingFundraiser?.id) qs.set('exclude_fundraiser_id', editingFundraiser.id);
    fetch(`${API_BASE_URL}/api/fundraisers/resolve-link?${qs.toString()}`)
      .then(async r => { const j = await r.json(); if (!r.ok) throw new Error(j.detail || 'Could not read that link'); return j; })
      .then(setLinkCheck)
      .catch(err => setLinkCheck({ error: err.message }));
  };

  const addLink = () => {
    if (!linkCheck || linkCheck.loading || linkCheck.error || linkCheck.assigned_to) return;
    if (pageLinks.some(l => l.key === linkCheck.match_key)) { setLinkInput(''); setLinkCheck(null); return; }
    setPageLinks(prev => [...prev, { match_type: linkType, match_value: linkInput.trim(), key: linkCheck.match_key,
      donations: linkCheck.donations, raised: linkCheck.raised }]);
    setLinkInput('');
    setLinkCheck(null);
  };

  // Submit Form
  const handleSubmit = (e) => {
    e.preventDefault();
    if (!isSuperAdmin) {
      setFormMsg('❌ Managing fundraisers is strictly restricted to Super Admin accounts.');
      return;
    }

    setSubmitting(true);
    setFormMsg('');

    const payload = {
      company_id: activeCompany,
      name: formFields.name.trim(),
      email: formFields.email.trim(),
      phone: formFields.phone.trim(),
      target_goal: parseFloat(formFields.target_goal || 0),
      start_date: formFields.start_date || '',
      status: formFields.status,
      notes: formFields.notes,
      page_group: pageGroup,
      assigned_campaigns: [
        ...assignedCampaigns.map(c => ({ ...c, match_type: 'campaign_name' })),
        ...pageLinks.map(l => ({ campaign_name: l.match_value, match_type: l.match_type, match_value: l.match_value }))
      ],
      user_role: user?.role || 'super_admin',
      can_edit_donors: user?.can_edit_donors === 1 || user?.role === 'super_admin'
    };

    const isEdit = !!editingFundraiser;
    const url = isEdit
      ? `${API_BASE_URL}/api/fundraisers/${editingFundraiser.id}`
      : `${API_BASE_URL}/api/fundraisers`;
    const method = isEdit ? 'PUT' : 'POST';

    fetch(url, {
      method: method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
      .then(r => r.json())
      .then(res => {
        setSubmitting(false);
        if (res.status === 'success') {
          setFormMsg(`✅ ${res.message}`);
          if (onSuccess) onSuccess();
          setTimeout(() => {
            onClose();
            setFormMsg('');
          }, 1000);
        } else {
          // FastAPI 422 detail is an array of error objects; safely stringify it
          const detail = res.detail;
          const detailStr = Array.isArray(detail)
            ? detail.map(d => `${(d.loc || []).slice(-1)[0] || 'field'}: ${d.msg}`).join('; ')
            : (typeof detail === 'object' && detail !== null ? JSON.stringify(detail) : String(detail || 'Failed to save fundraiser.'));
          setFormMsg(`❌ ${detailStr}`);
        }
      })
      .catch(err => {
        setSubmitting(false);
        setFormMsg(`❌ Error: ${err.message}`);
      });
  };

  if (!isOpen || !isSuperAdmin) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
      <div 
        className="glass-panel w-full max-w-2xl max-h-[90vh] flex flex-col shadow-2xl rounded-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-200 border"
        style={{ backgroundColor: 'var(--bg-card)', borderColor: 'var(--border-glass)', color: 'var(--text-main)' }}
      >
        {/* Modal Header */}
        <div className="flex items-center justify-between p-4 border-b" style={{ borderColor: 'var(--border-glass)' }}>
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-xl bg-cyan-500/15 text-cyan-500">
              <HeartHandshake className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-sm font-black" style={{ color: 'var(--text-main)' }}>
                {editingFundraiser ? `Edit Fundraiser: ${editingFundraiser.name}` : 'Create New Fundraiser'}
              </h3>
              <p className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
                Assign campaigns &amp; multi-codes. Campaigns are assigned in real-time.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded-lg text-slate-400 hover:text-slate-700 dark:hover:text-white hover:bg-slate-200 dark:bg-slate-800 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="flex-1 overflow-y-auto p-4 custom-scrollbar flex flex-col gap-3.5">
          {formMsg && (
            <div className={`p-2.5 rounded-lg text-xs font-bold border ${
              formMsg.startsWith('✅') ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/30' : 'bg-rose-500/10 text-rose-600 dark:text-rose-400 border-rose-500/30'
            }`}>
              {formMsg}
            </div>
          )}

          <form onSubmit={handleSubmit} id="fundraiser-form" className="flex flex-col gap-3.5">
            {/* Row 1: Name & Target Goal */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-bold mb-1" style={{ color: 'var(--text-main)' }}>
                  Fundraiser Name *
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Kamrul, Team Alpha, Fatima"
                  value={formFields.name}
                  onChange={e => setFormFields(prev => ({ ...prev, name: e.target.value }))}
                  className="w-full rounded-lg px-3 py-1.5 text-xs focus:outline-none"
                  style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' }}
                />
              </div>

              <div>
                <label className="block text-xs font-bold mb-1" style={{ color: 'var(--text-main)' }}>
                  Target Fundraising Goal (£)
                </label>
                <input
                  type="number"
                  min="0"
                  step="100"
                  placeholder="e.g. 50000"
                  value={formFields.target_goal}
                  onChange={e => setFormFields(prev => ({ ...prev, target_goal: e.target.value }))}
                  className="w-full rounded-lg px-3 py-1.5 text-xs focus:outline-none"
                  style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' }}
                />
              </div>
            </div>

            {/* Page group: the charity's own pages vs SP pages */}
            <div>
              <label className="block text-xs font-bold mb-1" style={{ color: 'var(--text-main)' }}>Pages belong to</label>
              <div className="flex gap-1" role="group" aria-label="Page group">
                {[['', 'Automatic'], ['MAIN', `${activeCompany === 'iqra' ? 'Iqra' : 'Rethink'} pages`], ['SP', 'SP pages']].map(([g, label]) => (
                  <button key={g || 'auto'} type="button" onClick={() => setPageGroup(g)}
                    className={`px-3 py-1.5 rounded-lg text-xs font-bold border ${pageGroup === g ? 'border-cyan-500 bg-cyan-500/15 text-cyan-700 dark:text-cyan-300' : ''}`}
                    style={pageGroup === g ? undefined : { borderColor: 'var(--input-border)', color: 'var(--text-muted)' }}>
                    {label}
                  </button>
                ))}
              </div>
              {pageGroup === '' && <p className="text-[10px] mt-0.5" style={{ color: 'var(--text-muted)' }}>Automatic: SP when the name or a page/campaign is an SP one (e.g. "SP-…", sp_… links, "Sisters Project").</p>}
            </div>

            {/* Row 2: Status & Optional Manual Start Date */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-bold mb-1" style={{ color: 'var(--text-main)' }}>
                  Status
                </label>
                {customStatus ? (
                  <div className="flex gap-1">
                    <input
                      type="text"
                      autoFocus
                      maxLength={30}
                      placeholder="e.g. DHUL HIJJAH"
                      value={formFields.status}
                      onChange={e => setFormFields(prev => ({ ...prev, status: e.target.value.toUpperCase() }))}
                      className="w-full rounded-lg px-3 py-1.5 text-xs focus:outline-none"
                      style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' }}
                    />
                    <button type="button" onClick={() => { setCustomStatus(false); setFormFields(prev => ({ ...prev, status: 'ACTIVE' })); }}
                      className="px-2 text-xs rounded-lg" style={{ color: 'var(--text-muted)', border: '1px solid var(--input-border)' }}>List</button>
                  </div>
                ) : (
                  <select
                    value={statusOptions.includes(formFields.status) ? formFields.status : formFields.status || 'ACTIVE'}
                    onChange={e => {
                      if (e.target.value === '__custom__') { setCustomStatus(true); setFormFields(prev => ({ ...prev, status: '' })); return; }
                      setFormFields(prev => ({ ...prev, status: e.target.value }));
                    }}
                    className="w-full rounded-lg px-3 py-1.5 text-xs focus:outline-none"
                    style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' }}
                  >
                    {[...new Set([...statusOptions, formFields.status].filter(Boolean))].map(s => <option key={s} value={s}>{s}</option>)}
                    <option value="__custom__">+ Custom status…</option>
                  </select>
                )}
              </div>

              <div>
                <label className="block text-xs font-bold mb-1" style={{ color: 'var(--text-main)' }}>
                  <Calendar className="w-3 h-3 inline mr-1 text-cyan-500" /> Manual Start Date (Optional)
                </label>
                <input
                  type="date"
                  value={formFields.start_date}
                  onChange={e => setFormFields(prev => ({ ...prev, start_date: e.target.value }))}
                  className="w-full rounded-lg px-3 py-1.5 text-xs focus:outline-none"
                  style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' }}
                />
                <span className="text-[10px] block mt-0.5" style={{ color: 'var(--text-sub)' }}>
                  Defaults automatically to the earliest donation date in dataset.
                </span>
              </div>
            </div>

            {/* Row 3: Email & Phone (Optional) */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-bold mb-1" style={{ color: 'var(--text-main)' }}>
                  Contact Email (Optional)
                </label>
                <input
                  type="email"
                  placeholder="fundraiser@example.com"
                  value={formFields.email}
                  onChange={e => setFormFields(prev => ({ ...prev, email: e.target.value }))}
                  className="w-full rounded-lg px-3 py-1.5 text-xs focus:outline-none"
                  style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' }}
                />
              </div>

              <div>
                <label className="block text-xs font-bold mb-1" style={{ color: 'var(--text-main)' }}>
                  Contact Phone (Optional)
                </label>
                <input
                  type="text"
                  placeholder="+44 7123 456789"
                  value={formFields.phone}
                  onChange={e => setFormFields(prev => ({ ...prev, phone: e.target.value }))}
                  className="w-full rounded-lg px-3 py-1.5 text-xs focus:outline-none"
                  style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' }}
                />
              </div>
            </div>

            {/* ── Campaign & Code Assignment Section ──────────────── */}
            {/* Page links: fundraiser page / community-team page / campaign link */}
            <div className="mt-1 border-t pt-3" style={{ borderColor: 'var(--border-glass)' }}>
              <label className="block text-xs font-black flex items-center gap-1.5" style={{ color: 'var(--text-main)' }}>
                <Link2 className="w-3.5 h-3.5 text-cyan-500" /> Track by page link
              </label>
              <p className="text-[11px] mb-1.5" style={{ color: 'var(--text-muted)' }}>
                Every donation made through the page counts for this fundraiser, live. A fundraiser page beats a team page, which beats a campaign link or name.
              </p>
              {pageLinks.length > 0 && (
                <div className="flex flex-col gap-1 mb-2">
                  {pageLinks.map((l, i) => (
                    <div key={`${l.match_value}-${i}`} className="flex items-center gap-2 px-2 py-1 rounded text-[11px] border border-cyan-500/30 bg-cyan-500/10">
                      <span className="px-1.5 rounded bg-cyan-500/25 font-bold shrink-0">{linkLabel(l.match_type)}</span>
                      <span className="truncate flex-1" title={l.match_value} style={{ color: 'var(--text-main)' }}>{l.match_value}</span>
                      {l.donations !== undefined && <span className="shrink-0" style={{ color: 'var(--text-muted)' }}>{l.donations} gifts · £{Number(l.raised || 0).toLocaleString()}</span>}
                      <button type="button" aria-label="Remove link" onClick={() => setPageLinks(prev => prev.filter((_, j) => j !== i))} className="hover:text-rose-500"><X className="w-3 h-3" /></button>
                    </div>
                  ))}
                </div>
              )}
              <div className="flex gap-1.5 flex-wrap">
                <select value={linkType} onChange={e => { setLinkType(e.target.value); setLinkCheck(null); }}
                  className="rounded-lg px-2 py-1.5 text-xs focus:outline-none"
                  style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' }}>
                  {LINK_TYPES.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
                </select>
                <input type="text" value={linkInput} placeholder="Paste the page URL"
                  onChange={e => { setLinkInput(e.target.value); setLinkCheck(null); }}
                  onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); if (linkCheck && !linkCheck.error && !linkCheck.loading) addLink(); else checkLink(); } }}
                  className="flex-1 min-w-[200px] rounded-lg px-3 py-1.5 text-xs focus:outline-none"
                  style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' }} />
                <button type="button" onClick={checkLink} disabled={!linkInput.trim()}
                  className="px-3 py-1.5 rounded-lg text-xs font-bold border border-cyan-500/40 text-cyan-700 dark:text-cyan-300 disabled:opacity-40">Check</button>
                <button type="button" onClick={addLink} disabled={!linkCheck || linkCheck.loading || !!linkCheck.error || !!linkCheck.assigned_to}
                  className="px-3 py-1.5 rounded-lg text-xs font-bold bg-cyan-600 text-white disabled:opacity-40">Add</button>
              </div>
              {linkCheck?.loading && <div className="text-[11px] mt-1 flex items-center gap-1" style={{ color: 'var(--text-muted)' }}><Loader2 className="w-3 h-3 animate-spin" /> Checking donations…</div>}
              {linkCheck?.error && <div className="text-[11px] mt-1 text-rose-600 flex items-center gap-1"><AlertTriangle className="w-3 h-3" /> {linkCheck.error}</div>}
              {linkCheck && !linkCheck.loading && !linkCheck.error && (
                <div className="text-[11px] mt-1 p-2 rounded-lg" style={{ backgroundColor: 'var(--bg-card-inner)', color: 'var(--text-main)' }}>
                  <b>{linkCheck.platform}</b> {linkLabel(linkCheck.match_type)} <span className="font-mono">{linkCheck.slug}</span>:{' '}
                  {linkCheck.donations > 0
                    ? <>{linkCheck.donations} donations · £{Number(linkCheck.raised).toLocaleString()} · latest {linkCheck.latest_donation_date || 'n/a'}{linkCheck.campaigns?.length ? ` · ${linkCheck.campaigns.slice(0, 2).join(', ')}` : ''}</>
                    : <>no donations yet - it will start counting the moment one arrives.</>}
                  {linkCheck.currently_credited_to?.length > 0 && (
                    <div style={{ color: 'var(--text-muted)' }}>Currently credited to: {linkCheck.currently_credited_to.map(c => `${c.fundraiser} (${c.donations})`).join(', ')}</div>
                  )}
                  {linkCheck.assigned_to && <div className="text-rose-600 font-semibold">Already assigned to '{linkCheck.assigned_to}' - remove it there first.</div>}
                </div>
              )}
            </div>

            <div className="mt-1 border-t pt-3" style={{ borderColor: 'var(--border-glass)' }}>
              <div className="flex items-center justify-between mb-1.5">
                <div>
                  <label className="block text-xs font-black flex items-center gap-1.5" style={{ color: 'var(--text-main)' }}>
                    <Layers className="w-3.5 h-3.5 text-cyan-500" /> Assign Campaigns &amp; Multi-Codes *
                  </label>
                  <p className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
                    Select the campaigns belonging to this fundraiser ({assignedCampaigns.length} assigned)
                  </p>
                </div>
              </div>

              {/* Selected Badges */}
              {assignedCampaigns.length > 0 && (
                <div 
                  className="p-2.5 rounded-lg border mb-2.5 flex flex-wrap gap-1 max-h-24 overflow-y-auto custom-scrollbar"
                  style={{ backgroundColor: 'var(--bg-card-inner)', borderColor: 'var(--border-glass)' }}
                >
                  {assignedCampaigns.map((c, i) => (
                    <span 
                      key={i}
                      className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-bold bg-cyan-500/15 text-cyan-700 dark:text-cyan-300 border border-cyan-500/30"
                    >
                      <span className="truncate max-w-[180px]">{c.campaign_name}</span>
                      <span className="px-1 rounded bg-cyan-500/25 text-cyan-900 dark:text-white text-[9px] font-black">
                        {c.code || 'ALL'}
                      </span>
                      <button
                        type="button"
                        onClick={() => handleToggleCampaignAssignment(c)}
                        className="hover:text-rose-500 ml-0.5"
                      >
                        <X className="w-3 h-3" />
                      </button>
                    </span>
                  ))}
                </div>
              )}

              {/* Search, Platform Filter, and Assignment Filter Toolbar */}
              <div className="flex items-center gap-2 mb-2 flex-wrap">
                <div className="relative flex-1 min-w-[160px]">
                  <Search className="w-3 h-3 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
                  <input
                    type="text"
                    placeholder="Search available campaigns..."
                    value={campaignSearch}
                    onChange={e => setCampaignSearch(e.target.value)}
                    className="w-full pl-7 pr-3 py-1.5 text-xs rounded-lg focus:outline-none"
                    style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' }}
                  />
                </div>

                <select
                  value={platformFilter}
                  onChange={e => setPlatformFilter(e.target.value)}
                  className="px-2 py-1.5 text-xs rounded-lg focus:outline-none"
                  style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' }}
                >
                  <option value="ALL">All Platforms</option>
                  <option value="LaunchGood">LaunchGood</option>
                  <option value="GiveBrite">GiveBrite</option>
                  <option value="Paysuite">Paysuite</option>
                  <option value="Rethink Website">Rethink Website</option>
                </select>

                <select
                  value={assignmentFilter}
                  onChange={e => setAssignmentFilter(e.target.value)}
                  className="px-2 py-1.5 text-xs rounded-lg focus:outline-none"
                  style={{ backgroundColor: 'var(--input-bg)', color: 'var(--input-text)', border: '1px solid var(--input-border)' }}
                >
                  <option value="ALL">All Campaigns</option>
                  <option value="UNASSIGNED">Unassigned Only</option>
                  <option value="ASSIGNED_THIS">Assigned to this Fundraiser</option>
                </select>
              </div>

              {/* Available Campaigns Multi-Select List */}
              <div 
                className="border rounded-lg p-1.5 max-h-44 overflow-y-auto custom-scrollbar flex flex-col gap-1"
                style={{ borderColor: 'var(--border-glass)', backgroundColor: 'var(--bg-card-inner)' }}
              >
                {displayedCampaigns.length === 0 ? (
                  <div className="text-center py-4 text-xs" style={{ color: 'var(--text-sub)' }}>
                    No matching campaigns found.
                  </div>
                ) : (
                  <>
                    {displayedCampaigns.map((camp, idx) => {
                      const key = `${(camp.campaign_name || '').toLowerCase().trim()}:::${(camp.code || 'ALL').toLowerCase().trim()}`;
                      const isAssignedToThis = assignedKeysSet.has(key);

                      return (
                        <div
                          key={idx}
                          onClick={() => handleToggleCampaignAssignment(camp)}
                          className={`p-1.5 rounded-md text-xs flex items-center justify-between gap-2 transition-colors cursor-pointer ${
                            isAssignedToThis
                              ? 'bg-cyan-500/20 text-cyan-800 dark:text-cyan-200 border border-cyan-500/40 font-bold'
                              : 'hover:bg-slate-200/60 dark:hover:bg-slate-800/60 border border-transparent'
                          }`}
                          style={{ color: isAssignedToThis ? undefined : 'var(--text-main)' }}
                        >
                          <div className="flex items-center gap-2 min-w-0">
                            <div className={`w-3.5 h-3.5 rounded flex items-center justify-center text-[9px] font-bold shrink-0 ${
                              isAssignedToThis 
                                ? 'bg-cyan-500 text-white' 
                                : 'border border-slate-400'
                            }`}>
                              {isAssignedToThis ? <Check className="w-2.5 h-2.5 stroke-[3]" /> : null}
                            </div>
                            <div className="truncate">
                              <span className="font-semibold text-xs">{camp.campaign_name}</span>
                              <span 
                                className="ml-1.5 px-1 py-0.5 rounded text-[9px] font-mono border"
                                style={{ backgroundColor: 'var(--bg-card)', color: 'var(--accent-cyan)', borderColor: 'var(--border-glass)' }}
                              >
                                {camp.code}
                              </span>
                            </div>
                          </div>

                          <div className="flex items-center gap-2 shrink-0">
                            <span className="text-[10px]" style={{ color: 'var(--text-sub)' }}>
                              {camp.platform} • {camp.heading}
                            </span>
                          </div>
                        </div>
                      );
                    })}

                    {filteredAvailableCampaigns.length > displayedCampaigns.length && (
                      <div className="text-[10px] text-center py-1.5 text-slate-400 border-t" style={{ borderColor: 'var(--border-glass)' }}>
                        Showing 80 of {filteredAvailableCampaigns.length} campaigns. Type in search to narrow down.
                      </div>
                    )}
                  </>
                )}
              </div>
            </div>
          </form>
        </div>

        {/* Modal Footer */}
        <div className="p-3.5 border-t flex items-center justify-end gap-2.5" style={{ borderColor: 'var(--border-glass)' }}>
          <button
            type="button"
            onClick={onClose}
            className="btn-secondary text-xs px-3.5 py-1.5"
          >
            Cancel
          </button>
          <button
            type="submit"
            form="fundraiser-form"
            disabled={submitting}
            className="btn-primary text-xs flex items-center gap-1.5 px-4 py-1.5 shadow-md shadow-cyan-500/20 font-bold"
          >
            {submitting ? <RefreshCw className="w-3 h-3 animate-spin" /> : <CheckCircle2 className="w-3 h-3" />}
            {editingFundraiser ? 'Save Changes' : 'Create Fundraiser'}
          </button>
        </div>
      </div>
    </div>
  );
}
