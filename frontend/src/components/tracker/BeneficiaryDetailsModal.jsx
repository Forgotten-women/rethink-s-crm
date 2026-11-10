import React, { useState, useEffect } from 'react';
import {
  X, ExternalLink, FileText, Video, Folder, Mail, Phone, Copy, Check,
  Calendar, User, Users, Clock, Sparkles, Send, Edit3, AlertCircle,
  CheckCircle2, MessageSquare, MapPin, Heart, Building2, ChevronRight,
  RefreshCw, ShieldCheck, Tag
} from 'lucide-react';
import { API_BASE_URL } from '../../config';

const getEmbeddableDocUrl = (url) => {
  if (!url) return '';
  const trimmed = url.trim();
  const driveMatch = trimmed.match(/\/d\/([a-zA-Z0-9_-]+)/) || trimmed.match(/[?&]id=([a-zA-Z0-9_-]+)/);
  if (driveMatch && driveMatch[1]) {
    return `https://drive.google.com/file/d/${driveMatch[1]}/preview`;
  }
  return trimmed;
};

const COMMUNICATION_STATUS_OPTIONS = [
  { value: 'Pending Profile', label: '⏳ Pending Profile (Not Mailed)', badgeBg: 'bg-amber-50 dark:bg-amber-950/60 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-800' },
  { value: 'First Mailed', label: '✉️ First Mailed (Profile Intro)', badgeBg: 'bg-blue-50 dark:bg-blue-950/60 text-blue-700 dark:text-blue-300 border-blue-200 dark:border-blue-800' },
  { value: 'Update Sent', label: '📹 Update Sent (Video / Progress)', badgeBg: 'bg-indigo-50 dark:bg-indigo-950/60 text-indigo-700 dark:text-indigo-300 border-indigo-200 dark:border-indigo-800' },
  { value: 'Feedback Sent', label: '📋 Feedback Sent (Annual Report)', badgeBg: 'bg-purple-50 dark:bg-purple-950/60 text-purple-700 dark:text-purple-300 border-purple-200 dark:border-purple-800' },
  { value: 'Renewal Sent', label: '🔄 Renewal Sent', badgeBg: 'bg-orange-50 dark:bg-orange-950/60 text-orange-700 dark:text-orange-300 border-orange-200 dark:border-orange-800' },
  { value: 'Donor Replied', label: '💬 Donor Replied', badgeBg: 'bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800' },
];

export default function BeneficiaryDetailsModal({
  beneficiary,
  isOpen,
  onClose,
  onStatusUpdated,
  onEditBeneficiary,
  onSendEmail,
  onPreviewMedia,
  onOpenDonor,
  onAllocate
}) {
  const [data, setData] = useState(beneficiary || {});
  const [loading, setLoading] = useState(false);
  const [updatingStatus, setUpdatingStatus] = useState(false);
  const [copiedCode, setCopiedCode] = useState(false);
  const [statusSuccess, setStatusSuccess] = useState(false);
  const [activeTab, setActiveTab] = useState('overview'); // 'overview' | 'donors' | 'media' | 'feedbacks' | 'comms'

  useEffect(() => {
    if (beneficiary && isOpen) {
      setData(beneficiary);
      fetchFullDetails(beneficiary.id);
    }
  }, [beneficiary?.id, isOpen]);

  const fetchFullDetails = async (benId) => {
    if (!benId) return;
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/tracker/beneficiaries/${benId}`);
      if (res.ok) {
        const fullData = await res.json();
        setData(fullData);
      }
    } catch (err) {
      console.error('Error fetching beneficiary full details:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleUpdateStatus = async (newStatus) => {
    if (!data?.id || updatingStatus) return;
    setUpdatingStatus(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/tracker/beneficiaries/${data.id}/status`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ communication_status: newStatus })
      });
      if (res.ok) {
        const updated = {
          ...data,
          communication_status: newStatus,
          last_contacted_at: new Date().toISOString()
        };
        setData(updated);
        setStatusSuccess(true);
        setTimeout(() => setStatusSuccess(false), 2000);
        if (onStatusUpdated) onStatusUpdated(updated);
      }
    } catch (err) {
      console.error('Failed to update communication status:', err);
    } finally {
      setUpdatingStatus(false);
    }
  };

  const handleUpdateTeam = async (newTeam) => {
    if (!data?.id || updatingStatus) return;
    setUpdatingStatus(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/tracker/beneficiaries/${data.id}/status`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ team: newTeam })
      });
      if (res.ok) {
        const updated = { ...data, team: newTeam };
        setData(updated);
        if (onStatusUpdated) onStatusUpdated(updated);
      }
    } catch (err) {
      console.error('Failed to update team:', err);
    } finally {
      setUpdatingStatus(false);
    }
  };

  const copyToClipboard = (text) => {
    if (!text) return;
    navigator.clipboard.writeText(text);
    setCopiedCode(true);
    setTimeout(() => setCopiedCode(false), 2000);
  };

  if (!isOpen || !beneficiary) return null;

  const team = (data.team || 'RT').toUpperCase();
  const isSP = team === 'SP';
  const commStatus = data.communication_status || (data.allocation_id ? 'Pending Profile' : 'Unallocated');
  const donorsList = data.donors && data.donors.length > 0 
    ? data.donors 
    : data.donor_name 
      ? [{ donor_name: data.donor_name, donor_email: data.donor_email, donor_phone: data.donor_phone, donor_id: data.donor_id, is_primary: 1 }] 
      : [];

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="relative bg-white dark:bg-slate-900 rounded-2xl max-w-4xl w-full shadow-2xl border border-slate-200 dark:border-slate-800 overflow-hidden flex flex-col max-h-[90vh] animate-in fade-in zoom-in-95 duration-200">
        
        {/* Header */}
        <div className="px-6 py-5 border-b border-slate-200 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-850 flex items-start justify-between gap-4">
          <div className="flex items-start gap-4">
            <div className={`w-12 h-12 rounded-xl flex items-center justify-center font-bold text-xl shadow-xs border ${
              isSP 
                ? 'bg-rose-100 dark:bg-rose-950/80 text-rose-600 dark:text-rose-300 border-rose-200 dark:border-rose-800' 
                : 'bg-purple-100 dark:bg-purple-950/80 text-purple-600 dark:text-purple-300 border-purple-200 dark:border-purple-800'
            }`}>
              {isSP ? <Heart className="w-6 h-6 fill-rose-500/20" /> : <Building2 className="w-6 h-6" />}
            </div>

            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <h2 className="text-xl font-bold text-slate-900 dark:text-white">
                  {data.name || 'Unnamed Beneficiary'}
                </h2>

                {/* Team Badge with Quick Switcher */}
                <span className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-bold border ${
                  isSP
                    ? 'bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-950/60 dark:text-rose-300 dark:border-rose-800'
                    : 'bg-purple-50 text-purple-700 border-purple-200 dark:bg-purple-950/60 dark:text-purple-300 dark:border-purple-800'
                }`}>
                  {isSP ? "Sisters' Project (SP)" : "Rethink Charity (RT)"}
                </span>

                {/* Sponsorship Type Badge */}
                <span className="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-semibold bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700">
                  {data.sponsorship_type}
                </span>

                {/* Allocation Status Badge */}
                <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-bold border ${
                  data.allocation_id
                    ? 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/60 dark:text-emerald-300 dark:border-emerald-800'
                    : 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950/60 dark:text-amber-300 dark:border-amber-800'
                }`}>
                  {data.allocation_id ? <CheckCircle2 className="w-3.5 h-3.5" /> : <AlertCircle className="w-3.5 h-3.5" />}
                  {data.allocation_id ? 'Allocated' : 'Unallocated'}
                </span>
              </div>

              {/* Project Code & Quick Meta */}
              <div className="flex items-center gap-3 mt-1.5 text-xs text-slate-500 dark:text-slate-400">
                <span className="inline-flex items-center gap-1 font-mono font-bold text-slate-700 dark:text-slate-300 bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded">
                  {data.project_code || 'NO-CODE'}
                  <button
                    onClick={() => copyToClipboard(data.project_code)}
                    className="hover:text-blue-600 transition-colors ml-0.5"
                    title="Copy Project Code"
                  >
                    {copiedCode ? <Check className="w-3 h-3 text-emerald-600" /> : <Copy className="w-3 h-3" />}
                  </button>
                </span>

                {data.location && (
                  <span className="inline-flex items-center gap-1">
                    <MapPin className="w-3.5 h-3.5 text-slate-400" />
                    {data.location}
                  </span>
                )}

                {data.company_id && (
                  <span className="capitalize text-slate-400 font-medium">
                    · {data.company_id}
                  </span>
                )}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {onEditBeneficiary && (
              <button
                onClick={() => {
                  onClose();
                  onEditBeneficiary(data);
                }}
                className="p-2 rounded-lg text-slate-500 hover:text-slate-800 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                title="Edit Beneficiary Details"
              >
                <Edit3 className="w-4 h-4" />
              </button>
            )}
            <button
              onClick={onClose}
              className="p-2 rounded-lg text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Status & Outreach Interactive Control Bar */}
        <div className="bg-slate-100/80 dark:bg-slate-800/80 px-6 py-3 border-b border-slate-200 dark:border-slate-800 flex flex-wrap items-center justify-between gap-3 text-xs">
          <div className="flex items-center gap-3">
            <span className="font-bold text-slate-600 dark:text-slate-300 flex items-center gap-1.5">
              <Mail className="w-3.5 h-3.5 text-blue-500" />
              Outreach Status:
            </span>

            {/* Communication Status Dropdown */}
            <div className="relative inline-flex items-center">
              <select
                value={data.communication_status || 'Pending Profile'}
                disabled={updatingStatus || !data.allocation_id}
                onChange={(e) => handleUpdateStatus(e.target.value)}
                className="pl-3 pr-8 py-1.5 rounded-lg border border-slate-300 dark:border-slate-650 bg-white dark:bg-slate-900 text-xs font-bold text-slate-800 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-blue-500 cursor-pointer disabled:opacity-50"
              >
                {COMMUNICATION_STATUS_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
              {updatingStatus && (
                <RefreshCw className="w-3.5 h-3.5 text-blue-500 animate-spin absolute right-2 pointer-events-none" />
              )}
            </div>

            {statusSuccess && (
              <span className="text-emerald-600 dark:text-emerald-400 font-bold flex items-center gap-1 text-[11px] animate-fade-in">
                <Check className="w-3.5 h-3.5" /> Updated!
              </span>
            )}

            {!data.allocation_id && (
              <span className="text-slate-400 italic text-[11px]">
                (Allocate to a donor to enable outreach tracking)
              </span>
            )}
          </div>

          {/* Quick Team Classifier */}
          <div className="flex items-center gap-2">
            <span className="font-semibold text-slate-500 dark:text-slate-400">Team:</span>
            <div className="inline-flex p-0.5 rounded-lg bg-slate-200 dark:bg-slate-700 text-[11px]">
              <button
                type="button"
                onClick={() => handleUpdateTeam('SP')}
                className={`px-2.5 py-0.5 rounded-md font-bold transition-all ${
                  isSP
                    ? 'bg-rose-500 text-white shadow-xs'
                    : 'text-slate-600 dark:text-slate-300 hover:text-slate-900'
                }`}
              >
                SP (Sisters')
              </button>
              <button
                type="button"
                onClick={() => handleUpdateTeam('RT')}
                className={`px-2.5 py-0.5 rounded-md font-bold transition-all ${
                  !isSP
                    ? 'bg-purple-600 text-white shadow-xs'
                    : 'text-slate-600 dark:text-slate-300 hover:text-slate-900'
                }`}
              >
                RT (Rethink)
              </button>
            </div>
          </div>
        </div>

        {/* Modal Navigation Tabs */}
        <div className="flex border-b border-slate-200 dark:border-slate-800 px-6 bg-white dark:bg-slate-900 text-xs font-bold gap-6">
          <button
            onClick={() => setActiveTab('overview')}
            className={`py-3 border-b-2 transition-all ${
              activeTab === 'overview'
                ? 'border-blue-600 text-blue-600 dark:text-blue-400 font-extrabold'
                : 'border-transparent text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
            }`}
          >
            Overview & Profile
          </button>
          <button
            onClick={() => setActiveTab('donors')}
            className={`py-3 border-b-2 transition-all flex items-center gap-1.5 ${
              activeTab === 'donors'
                ? 'border-blue-600 text-blue-600 dark:text-blue-400 font-extrabold'
                : 'border-transparent text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
            }`}
          >
            Assigned Donor(s)
            {donorsList.length > 0 && (
              <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300">
                {donorsList.length}
              </span>
            )}
          </button>
          <button
            onClick={() => setActiveTab('media')}
            className={`py-3 border-b-2 transition-all flex items-center gap-1.5 ${
              activeTab === 'media'
                ? 'border-blue-600 text-blue-600 dark:text-blue-400 font-extrabold'
                : 'border-transparent text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
            }`}
          >
            Media Assets
            {(data.profile_link || data.video_link || data.donor_folder_link) && (
              <span className="w-2 h-2 rounded-full bg-emerald-500 inline-block" />
            )}
          </button>
          <button
            onClick={() => setActiveTab('feedbacks')}
            className={`py-3 border-b-2 transition-all flex items-center gap-1.5 ${
              activeTab === 'feedbacks'
                ? 'border-blue-600 text-blue-600 dark:text-blue-400 font-extrabold'
                : 'border-transparent text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
            }`}
          >
            Annual Reports & Feedbacks
            {data.feedbacks?.length > 0 && (
              <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-purple-100 dark:bg-purple-950/80 text-purple-700 dark:text-purple-300 font-bold">
                {data.feedbacks.length}
              </span>
            )}
          </button>
          <button
            onClick={() => setActiveTab('comms')}
            className={`py-3 border-b-2 transition-all flex items-center gap-1.5 ${
              activeTab === 'comms'
                ? 'border-blue-600 text-blue-600 dark:text-blue-400 font-extrabold'
                : 'border-transparent text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
            }`}
          >
            Sent Communications
            {data.communications?.length > 0 && (
              <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-blue-100 dark:bg-blue-950/80 text-blue-700 dark:text-blue-300 font-bold">
                {data.communications.length}
              </span>
            )}
          </button>
        </div>

        {/* Tab Content Body */}
        <div className="p-6 overflow-y-auto space-y-6 flex-1 text-slate-700 dark:text-slate-200 text-xs md:text-sm">
          
          {/* TAB 1: OVERVIEW */}
          {activeTab === 'overview' && (
            <div className="space-y-6">
              {/* Primary Attributes Grid */}
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4">
                <div className="p-4 rounded-xl bg-slate-50 dark:bg-slate-800/60 border border-slate-200/80 dark:border-slate-800">
                  <div className="text-slate-400 text-xs font-semibold uppercase tracking-wider mb-1">
                    Sponsorship Target
                  </div>
                  <div className="text-lg font-bold text-slate-900 dark:text-white">
                    £{Number(data.allocated_amount || (data.sponsorship_type === 'Hafiz' ? 240 : 480)).toLocaleString()}
                  </div>
                  <div className="text-[11px] text-slate-500 mt-0.5">
                    Annual commitment rate
                  </div>
                </div>

                <div className="p-4 rounded-xl bg-slate-50 dark:bg-slate-800/60 border border-slate-200/80 dark:border-slate-800">
                  <div className="text-slate-400 text-xs font-semibold uppercase tracking-wider mb-1">
                    Cycle & Status
                  </div>
                  <div className="text-sm font-bold text-slate-900 dark:text-white capitalize">
                    {data.renewal_status || 'Year 1 Active'}
                  </div>
                  <div className="text-[11px] text-slate-500 mt-0.5">
                    {data.renewal_count ? `${data.renewal_count} renewals completed` : 'Initial year of support'}
                  </div>
                </div>

                <div className="p-4 rounded-xl bg-slate-50 dark:bg-slate-800/60 border border-slate-200/80 dark:border-slate-800">
                  <div className="text-slate-400 text-xs font-semibold uppercase tracking-wider mb-1">
                    Last Contacted
                  </div>
                  <div className="text-sm font-bold text-slate-900 dark:text-white">
                    {data.last_contacted_at ? new Date(data.last_contacted_at).toLocaleDateString() : 'Never'}
                  </div>
                  <div className="text-[11px] text-slate-500 mt-0.5">
                    {data.last_contacted_at ? new Date(data.last_contacted_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'No emails sent yet'}
                  </div>
                </div>

                <div className="p-4 rounded-xl bg-slate-50 dark:bg-slate-800/60 border border-slate-200/80 dark:border-slate-800">
                  <div className="text-slate-400 text-xs font-semibold uppercase tracking-wider mb-1">
                    Assigned Cohort
                  </div>
                  <div className="text-sm font-bold text-slate-900 dark:text-white flex items-center gap-1.5">
                    {isSP ? (
                      <span className="text-rose-600 dark:text-rose-400 font-extrabold flex items-center gap-1">
                        <Heart className="w-4 h-4 fill-rose-500/20" /> Sisters' Project
                      </span>
                    ) : (
                      <span className="text-purple-600 dark:text-purple-400 font-extrabold flex items-center gap-1">
                        <Building2 className="w-4 h-4" /> Rethink Charity
                      </span>
                    )}
                  </div>
                  <div className="text-[11px] text-slate-500 mt-0.5">
                    Team: {team}
                  </div>
                </div>
              </div>

              {/* Quick Donor Banner */}
              <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-xs">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="font-bold text-sm text-slate-900 dark:text-white flex items-center gap-2">
                    <User className="w-4 h-4 text-blue-500" />
                    Sponsorship Allocation
                  </h3>
                  {data.allocation_id && onSendEmail && (
                    <button
                      onClick={() => {
                        onClose();
                        onSendEmail({
                          id: data.allocation_id,
                          beneficiary_id: data.id,
                          beneficiary_name: data.name,
                          project_code: data.project_code,
                          sponsorship_type: data.sponsorship_type,
                          company_id: data.company_id || 'rethink',
                          donor_email: data.donor_email,
                          donor_name: data.donor_name,
                          donor_id: data.donor_id
                        });
                      }}
                      className="px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-bold text-xs flex items-center gap-1.5 transition-all shadow-xs"
                    >
                      <Send className="w-3.5 h-3.5" />
                      Send Outlook Email
                    </button>
                  )}
                </div>

                {data.allocation_id ? (
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4 bg-slate-50 dark:bg-slate-800/50 p-3.5 rounded-lg">
                    <div>
                      <div className="text-slate-400 text-xs">Primary Donor</div>
                      <div className="font-bold text-slate-900 dark:text-white">
                        {data.donor_name || 'Anonymous Donor'}
                      </div>
                      {data.donor_email && (
                        <a
                          href={`mailto:${data.donor_email}`}
                          className="text-xs text-blue-600 dark:text-blue-400 hover:underline flex items-center gap-1 mt-0.5"
                        >
                          <Mail className="w-3 h-3" /> {data.donor_email}
                        </a>
                      )}
                    </div>

                    <div>
                      <div className="text-slate-400 text-xs">Campaign / Source</div>
                      <div className="font-semibold text-slate-800 dark:text-slate-200">
                        {data.campaign_name || 'Direct Allocation'}
                      </div>
                      <div className="text-xs text-slate-500 mt-0.5">
                        Type: {data.allocation_type || 'individual'}
                      </div>
                    </div>

                    <div className="flex items-center justify-end">
                      {onOpenDonor && (data.donor_email || data.donor_id) && (
                        <button
                          onClick={() => {
                            onClose();
                            onOpenDonor(data.donor_email || data.donor_id);
                          }}
                          className="px-3 py-1.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 hover:bg-slate-100 dark:hover:bg-slate-700 text-xs font-bold text-slate-700 dark:text-slate-200 flex items-center gap-1"
                        >
                          View Donor Profile <ChevronRight className="w-3.5 h-3.5" />
                        </button>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="flex flex-col sm:flex-row items-center justify-between gap-3 p-4 bg-amber-50/70 dark:bg-amber-950/40 border border-amber-200/80 dark:border-amber-900/60 rounded-lg">
                    <div className="flex items-center gap-3">
                      <AlertCircle className="w-5 h-5 text-amber-600 dark:text-amber-400 shrink-0" />
                      <div>
                        <div className="font-bold text-amber-900 dark:text-amber-200">
                          Beneficiary is not currently allocated
                        </div>
                        <div className="text-xs text-amber-700 dark:text-amber-400">
                          Assign this beneficiary to a qualifying donor to begin sponsorship outreach and send progress updates.
                        </div>
                      </div>
                    </div>
                    {onAllocate && (
                      <button
                        onClick={() => {
                          onClose();
                          onAllocate(data);
                        }}
                        className="px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-700 text-white font-bold text-xs shrink-0 transition-all shadow-xs"
                      >
                        Quick Allocate
                      </button>
                    )}
                  </div>
                )}
              </div>

              {/* Media Previews Bar */}
              <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-xs">
                <h3 className="font-bold text-sm text-slate-900 dark:text-white flex items-center gap-2 mb-3">
                  <FileText className="w-4 h-4 text-emerald-500" />
                  Media Assets & Documents
                </h3>
                <div className="flex flex-wrap items-center gap-3">
                  {data.profile_link ? (
                    <button
                      onClick={() => onPreviewMedia && onPreviewMedia({
                        type: 'pdf',
                        url: getEmbeddableDocUrl(data.profile_link),
                        rawUrl: data.profile_link,
                        title: `Profile: ${data.name} (${data.project_code})`
                      })}
                      className="px-3 py-2 rounded-lg bg-blue-50 dark:bg-blue-950/60 text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-800 font-bold text-xs flex items-center gap-1.5 hover:bg-blue-100 transition-all"
                    >
                      <FileText className="w-4 h-4" />
                      View Profile PDF Stream
                    </button>
                  ) : (
                    <span className="text-slate-400 text-xs italic px-3 py-2 bg-slate-50 dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700">
                      No Profile PDF attached
                    </span>
                  )}

                  {data.video_link ? (
                    <button
                      onClick={() => onPreviewMedia && onPreviewMedia({
                        type: 'video',
                        url: data.video_link,
                        title: `Video Update: ${data.name}`
                      })}
                      className="px-3 py-2 rounded-lg bg-rose-50 dark:bg-rose-950/60 text-rose-600 dark:text-rose-400 border border-rose-200 dark:border-rose-800 font-bold text-xs flex items-center gap-1.5 hover:bg-rose-100 transition-all"
                    >
                      <Video className="w-4 h-4" />
                      Watch Video Update
                    </button>
                  ) : (
                    <span className="text-slate-400 text-xs italic px-3 py-2 bg-slate-50 dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700">
                      No Video link
                    </span>
                  )}

                  {data.donor_folder_link && (
                    <a
                      href={data.donor_folder_link}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="px-3 py-2 rounded-lg bg-amber-50 dark:bg-amber-950/60 text-amber-600 dark:text-amber-400 border border-amber-200 dark:border-amber-800 font-bold text-xs flex items-center gap-1.5 hover:bg-amber-100 transition-all"
                    >
                      <Folder className="w-4 h-4" />
                      Open Google Drive Folder
                      <ExternalLink className="w-3 h-3 ml-0.5" />
                    </a>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* TAB 2: ASSIGNED DONOR(S) */}
          {activeTab === 'donors' && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="font-bold text-sm text-slate-900 dark:text-white flex items-center gap-2">
                  <Users className="w-4 h-4 text-blue-500" />
                  Assigned Sponsoring Donors
                </h3>
              </div>

              {donorsList.length > 0 ? (
                <div className="divide-y divide-slate-100 dark:divide-slate-800 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden bg-white dark:bg-slate-900">
                  {donorsList.map((d, idx) => (
                    <div key={d.id || idx} className="p-4 flex items-center justify-between gap-4 hover:bg-slate-50 dark:hover:bg-slate-850 transition-colors">
                      <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-full bg-blue-100 dark:bg-blue-950/70 text-blue-600 dark:text-blue-400 flex items-center justify-center font-bold text-sm">
                          {(d.donor_name || d.donor_email || 'D')[0].toUpperCase()}
                        </div>
                        <div>
                          <div className="font-bold text-slate-900 dark:text-white flex items-center gap-2">
                            {d.donor_name || 'Anonymous Donor'}
                            {d.is_primary ? (
                              <span className="text-[10px] font-bold px-1.5 py-0.2 rounded bg-emerald-100 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300">
                                Primary
                              </span>
                            ) : null}
                          </div>
                          <div className="flex items-center gap-3 text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                            {d.donor_email && (
                              <a href={`mailto:${d.donor_email}`} className="hover:underline flex items-center gap-1">
                                <Mail className="w-3 h-3" /> {d.donor_email}
                              </a>
                            )}
                            {d.donor_phone && (
                              <a href={`tel:${d.donor_phone}`} className="hover:underline flex items-center gap-1">
                                <Phone className="w-3 h-3" /> {d.donor_phone}
                              </a>
                            )}
                          </div>
                        </div>
                      </div>

                      <div className="flex items-center gap-3">
                        {d.contribution_amount && (
                          <div className="text-right">
                            <div className="font-bold text-slate-900 dark:text-white">
                              £{Number(d.contribution_amount).toLocaleString()}
                            </div>
                            <div className="text-[10px] text-slate-400">
                              Contribution
                            </div>
                          </div>
                        )}
                        {onOpenDonor && (d.donor_email || d.donor_id) && (
                          <button
                            onClick={() => {
                              onClose();
                              onOpenDonor(d.donor_email || d.donor_id);
                            }}
                            className="px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 text-xs font-bold hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                          >
                            Profile
                          </button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="p-8 text-center text-slate-400 bg-slate-50 dark:bg-slate-800/40 rounded-xl border border-dashed border-slate-200 dark:border-slate-800">
                  <User className="w-8 h-8 mx-auto mb-2 opacity-50" />
                  <p className="font-semibold">No donors currently allocated to this beneficiary.</p>
                </div>
              )}
            </div>
          )}

          {/* TAB 3: MEDIA ASSETS */}
          {activeTab === 'media' && (
            <div className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* Profile PDF Card */}
                <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900">
                  <div className="flex items-center justify-between mb-3">
                    <span className="font-bold text-sm text-slate-900 dark:text-white flex items-center gap-2">
                      <FileText className="w-4 h-4 text-blue-500" />
                      Beneficiary Profile PDF
                    </span>
                    {data.profile_link ? (
                      <span className="text-[10px] font-bold text-emerald-600 bg-emerald-50 dark:bg-emerald-950 px-2 py-0.5 rounded">
                        Available
                      </span>
                    ) : (
                      <span className="text-[10px] font-bold text-slate-400 bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded">
                        Missing
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-slate-500 dark:text-slate-400 mb-4">
                    The formal sponsorship profile sheet sent to the donor upon their initial qualification and sponsorship setup.
                  </p>
                  {data.profile_link ? (
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => onPreviewMedia && onPreviewMedia({
                          type: 'pdf',
                          url: getEmbeddableDocUrl(data.profile_link),
                          rawUrl: data.profile_link,
                          title: `Profile: ${data.name}`
                        })}
                        className="px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-bold text-xs flex items-center gap-1.5 transition-all"
                      >
                        <FileText className="w-3.5 h-3.5" /> View In-App Stream
                      </button>
                      <a
                        href={data.profile_link}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 text-xs font-semibold flex items-center gap-1 hover:bg-slate-50 dark:hover:bg-slate-800"
                      >
                        Open Raw URL <ExternalLink className="w-3 h-3" />
                      </a>
                    </div>
                  ) : (
                    <div className="text-xs text-slate-400 italic">
                      No Google Drive or PDF link attached to this record.
                    </div>
                  )}
                </div>

                {/* Video Update Card */}
                <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900">
                  <div className="flex items-center justify-between mb-3">
                    <span className="font-bold text-sm text-slate-900 dark:text-white flex items-center gap-2">
                      <Video className="w-4 h-4 text-rose-500" />
                      Video Update Link
                    </span>
                    {data.video_link ? (
                      <span className="text-[10px] font-bold text-emerald-600 bg-emerald-50 dark:bg-emerald-950 px-2 py-0.5 rounded">
                        Available
                      </span>
                    ) : (
                      <span className="text-[10px] font-bold text-slate-400 bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded">
                        Missing
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-slate-500 dark:text-slate-400 mb-4">
                    Video message or greetings recorded for donors to observe their sponsored individual's wellbeing.
                  </p>
                  {data.video_link ? (
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => onPreviewMedia && onPreviewMedia({
                          type: 'video',
                          url: data.video_link,
                          title: `Video: ${data.name}`
                        })}
                        className="px-3 py-1.5 rounded-lg bg-rose-600 hover:bg-rose-700 text-white font-bold text-xs flex items-center gap-1.5 transition-all"
                      >
                        <Video className="w-3.5 h-3.5" /> Watch Video Player
                      </button>
                      <a
                        href={data.video_link}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 text-xs font-semibold flex items-center gap-1 hover:bg-slate-50 dark:hover:bg-slate-800"
                      >
                        Open Video Link <ExternalLink className="w-3 h-3" />
                      </a>
                    </div>
                  ) : (
                    <div className="text-xs text-slate-400 italic">
                      No video update link provided.
                    </div>
                  )}
                </div>

                {/* Donor Drive Folder */}
                <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 md:col-span-2">
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-bold text-sm text-slate-900 dark:text-white flex items-center gap-2">
                      <Folder className="w-4 h-4 text-amber-500" />
                      Shared Google Drive Folder
                    </span>
                  </div>
                  <p className="text-xs text-slate-500 dark:text-slate-400 mb-3">
                    The parent Google Drive directory where receipts, report PDFs, photos, and high-resolution video files are archived.
                  </p>
                  {data.donor_folder_link ? (
                    <a
                      href={data.donor_folder_link}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-500 hover:bg-amber-600 text-white font-bold text-xs transition-all"
                    >
                      <Folder className="w-3.5 h-3.5" /> Open Google Drive Folder
                      <ExternalLink className="w-3 h-3 ml-0.5" />
                    </a>
                  ) : (
                    <span className="text-xs text-slate-400 italic">
                      No Drive folder linked.
                    </span>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* TAB 4: ANNUAL REPORTS & FEEDBACKS */}
          {activeTab === 'feedbacks' && (
            <div className="space-y-4">
              <h3 className="font-bold text-sm text-slate-900 dark:text-white flex items-center gap-2">
                <FileText className="w-4 h-4 text-purple-500" />
                Annual Progress & Feedback Reports
              </h3>

              {data.feedbacks && data.feedbacks.length > 0 ? (
                <div className="space-y-3">
                  {data.feedbacks.map((f) => (
                    <div key={f.id} className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 hover:border-purple-300 dark:hover:border-purple-800 transition-all">
                      <div className="flex items-center justify-between gap-3 mb-2">
                        <div className="font-bold text-slate-900 dark:text-white">
                          {f.feedback_title || f.year_label || 'Annual Progress Report'}
                        </div>
                        <div className="text-xs text-slate-400 flex items-center gap-1">
                          <Calendar className="w-3 h-3" />
                          {f.feedback_date || new Date(f.created_at).toLocaleDateString()}
                        </div>
                      </div>

                      {f.progress_summary && (
                        <p className="text-xs text-slate-600 dark:text-slate-300 mb-3 bg-slate-50 dark:bg-slate-800/60 p-2.5 rounded-lg">
                          {f.progress_summary}
                        </p>
                      )}

                      <div className="flex items-center gap-2 pt-1">
                        {f.report_link && (
                          <button
                            onClick={() => onPreviewMedia && onPreviewMedia({
                              type: 'pdf',
                              url: getEmbeddableDocUrl(f.report_link),
                              rawUrl: f.report_link,
                              title: `Report: ${f.feedback_title || data.name}`
                            })}
                            className="px-2.5 py-1 rounded bg-purple-50 dark:bg-purple-950/60 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-800 text-xs font-semibold flex items-center gap-1 hover:bg-purple-100"
                          >
                            <FileText className="w-3 h-3" /> View Report PDF
                          </button>
                        )}
                        {f.video_link && (
                          <button
                            onClick={() => onPreviewMedia && onPreviewMedia({
                              type: 'video',
                              url: f.video_link,
                              title: `Feedback Video: ${data.name}`
                            })}
                            className="px-2.5 py-1 rounded bg-rose-50 dark:bg-rose-950/60 text-rose-700 dark:text-rose-300 border border-rose-200 dark:border-rose-800 text-xs font-semibold flex items-center gap-1 hover:bg-rose-100"
                          >
                            <Video className="w-3 h-3" /> Video Clip
                          </button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="p-8 text-center text-slate-400 bg-slate-50 dark:bg-slate-800/40 rounded-xl border border-dashed border-slate-200 dark:border-slate-800">
                  <FileText className="w-8 h-8 mx-auto mb-2 opacity-50" />
                  <p className="font-semibold">No annual feedback reports recorded for this beneficiary yet.</p>
                </div>
              )}
            </div>
          )}

          {/* TAB 5: SENT COMMUNICATIONS */}
          {activeTab === 'comms' && (
            <div className="space-y-4">
              <h3 className="font-bold text-sm text-slate-900 dark:text-white flex items-center gap-2">
                <Mail className="w-4 h-4 text-blue-500" />
                Dispatched Donor Communications
              </h3>

              {data.communications && data.communications.length > 0 ? (
                <div className="divide-y divide-slate-100 dark:divide-slate-800 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden bg-white dark:bg-slate-900">
                  {data.communications.map((c) => (
                    <div key={c.id} className="p-4 hover:bg-slate-50 dark:hover:bg-slate-850 transition-colors">
                      <div className="flex items-center justify-between gap-3 mb-1">
                        <div className="font-bold text-xs text-slate-900 dark:text-white flex items-center gap-2">
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-mono uppercase bg-blue-100 dark:bg-blue-950 text-blue-700 dark:text-blue-300">
                            {c.template_type || 'email'}
                          </span>
                          {c.subject}
                        </div>
                        <span className="text-[11px] text-slate-400">
                          {c.sent_at ? new Date(c.sent_at).toLocaleString() : ''}
                        </span>
                      </div>
                      <div className="flex items-center gap-4 text-xs text-slate-500 dark:text-slate-400 mt-1">
                        <span>To: <strong className="text-slate-700 dark:text-slate-300">{c.recipient_email}</strong></span>
                        {c.sender_email && <span>From: {c.sender_email}</span>}
                        <span className="ml-auto text-[10px] font-bold text-emerald-600 bg-emerald-50 dark:bg-emerald-950 px-2 py-0.5 rounded">
                          {c.delivery_status || 'Delivered'}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="p-8 text-center text-slate-400 bg-slate-50 dark:bg-slate-800/40 rounded-xl border border-dashed border-slate-200 dark:border-slate-800">
                  <Mail className="w-8 h-8 mx-auto mb-2 opacity-50" />
                  <p className="font-semibold">No emails dispatched for this beneficiary's allocation yet.</p>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Modal Footer */}
        <div className="px-6 py-4 border-t border-slate-200 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-850 flex items-center justify-between">
          <div className="text-xs text-slate-400">
            Beneficiary ID: <span className="font-mono font-bold text-slate-600 dark:text-slate-300">#{data.id}</span>
          </div>

          <div className="flex items-center gap-3">
            {data.allocation_id && onSendEmail && (
              <button
                onClick={() => {
                  onClose();
                  onSendEmail({
                    id: data.allocation_id,
                    beneficiary_id: data.id,
                    beneficiary_name: data.name,
                    project_code: data.project_code,
                    sponsorship_type: data.sponsorship_type,
                    company_id: data.company_id || 'rethink',
                    donor_email: data.donor_email,
                    donor_name: data.donor_name,
                    donor_id: data.donor_id
                  });
                }}
                className="px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-700 text-white font-bold text-xs flex items-center gap-1.5 transition-all shadow-xs"
              >
                <Send className="w-3.5 h-3.5" />
                Dispatch Email
              </button>
            )}

            <button
              onClick={onClose}
              className="px-4 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 hover:bg-slate-50 dark:hover:bg-slate-750 text-slate-700 dark:text-slate-200 font-bold text-xs transition-colors"
            >
              Close
            </button>
          </div>
        </div>

      </div>
    </div>
  );
}
