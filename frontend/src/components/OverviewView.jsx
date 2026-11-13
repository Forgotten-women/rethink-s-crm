import React, { useEffect, useState } from 'react';
import { Download, X, ChevronLeft, ChevronRight, Loader2 } from 'lucide-react';
import { API_BASE_URL, downloadFile } from '../config';
import { can } from '../access';

function buildParams(filters, activeCompany, extra = {}) {
  const params = new URLSearchParams();
  params.append('company_id', activeCompany);
  if (filters) {
    ['payment_type', 'tier', 'source', 'heading', 'subheading', 'country', 'code', 'zakat',
      'donor_country', 'campaign_search', 'gift_aid', 'start_date', 'end_date', 'programme_fund'
    ].forEach(k => { if (filters[k]) params.append(k, filters[k]); });
  }
  Object.entries(extra).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== '') params.append(k, v); });
  return params;
}

const money = (v, dp = 0) => `£${Number(v || 0).toLocaleString(undefined, { minimumFractionDigits: dp, maximumFractionDigits: dp })}`;

function Pager({ page, totalPages, onPage }) {
  if (totalPages <= 1) return null;
  const pages = [];
  for (let p = 1; p <= totalPages; p++) {
    if (p === 1 || p === totalPages || Math.abs(p - page) <= 1) pages.push(p);
    else if (pages[pages.length - 1] !== '…') pages.push('…');
  }
  return (
    <div className="flex items-center justify-center gap-1 py-3">
      <button type="button" disabled={page <= 1} onClick={() => onPage(page - 1)}
        className="p-1.5 rounded-md border border-slate-200 dark:border-slate-700 disabled:opacity-40 hover:border-blue-400">
        <ChevronLeft className="w-3.5 h-3.5" />
      </button>
      {pages.map((p, i) => p === '…' ? (
        <span key={`e${i}`} className="px-1.5 text-xs text-slate-400">…</span>
      ) : (
        <button key={p} type="button" onClick={() => onPage(p)}
          className={`min-w-[28px] px-2 py-1 rounded-md text-xs font-bold border ${p === page
            ? 'bg-blue-600 text-white border-blue-600'
            : 'border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:border-blue-400'}`}>
          {p}
        </button>
      ))}
      <button type="button" disabled={page >= totalPages} onClick={() => onPage(page + 1)}
        className="p-1.5 rounded-md border border-slate-200 dark:border-slate-700 disabled:opacity-40 hover:border-blue-400">
        <ChevronRight className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}

function ExportButton({ visible, onClick, title = 'Download CSV' }) {
  if (!visible) return null;
  return (
    <button type="button" onClick={onClick} title={title}
      className="p-1.5 rounded-md border border-slate-200 dark:border-slate-700 text-slate-500 dark:text-slate-400 hover:text-blue-500 hover:border-blue-400 transition-colors">
      <Download className="w-3.5 h-3.5" />
    </button>
  );
}

function BreakdownBar({ label, value, max, count }) {
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between text-xs font-semibold gap-2">
        <span className="text-slate-700 dark:text-slate-300 truncate">{label}</span>
        <span className="text-slate-900 dark:text-white font-bold whitespace-nowrap">
          {money(value)}{count != null && <span className="text-slate-400 font-semibold"> · {count} gifts</span>}
        </span>
      </div>
      <div className="w-full h-1.5 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden">
        <div className="h-full bg-blue-500 rounded-full" style={{ width: `${Math.min(100, (value / (max || 1)) * 100)}%` }} />
      </div>
    </div>
  );
}

function Modal({ title, subtitle, onClose, children, footer }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50" onClick={onClose}>
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-white/10 rounded-2xl shadow-2xl w-full max-w-3xl max-h-[88vh] flex flex-col"
        onClick={e => e.stopPropagation()}>
        <div className="px-6 py-4 border-b border-slate-100 dark:border-white/5 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="text-base font-black text-slate-800 dark:text-white truncate">{title}</h3>
            {subtitle && <p className="text-xs font-semibold text-slate-500 dark:text-slate-400">{subtitle}</p>}
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {footer}
            <button type="button" onClick={onClose} className="p-1.5 rounded-md hover:bg-slate-100 dark:hover:bg-slate-800">
              <X className="w-4 h-4 text-slate-500" />
            </button>
          </div>
        </div>
        <div className="p-6 overflow-y-auto flex flex-col gap-6">{children}</div>
      </div>
    </div>
  );
}

function StatTiles({ tiles }) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      {tiles.map(([label, value]) => (
        <div key={label} className="rounded-xl border border-slate-200 dark:border-white/10 p-3 flex flex-col gap-0.5">
          <span className="text-[10px] font-extrabold uppercase tracking-wider text-slate-400">{label}</span>
          <span className="text-sm font-black text-slate-800 dark:text-white">{value}</span>
        </div>
      ))}
    </div>
  );
}

function CampaignBreakdownModal({ campaign, filters, activeCompany, canExport, onClose }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const params = buildParams(filters, activeCompany, { campaign });
    fetch(`${API_BASE_URL}/api/overview/campaign-breakdown?${params.toString()}`)
      .then(r => r.ok ? r.json() : r.json().then(j => Promise.reject(j.detail || 'Failed to load')))
      .then(setData).catch(e => setError(String(e)));
  }, [campaign, filters, activeCompany]);

  const exportDonations = () => {
    const params = buildParams(filters, activeCompany, { section: 'campaign_donations', campaign });
    downloadFile(`${API_BASE_URL}/api/overview/export?${params.toString()}`, 'campaign_donations.csv');
  };

  const maxPage = data?.by_page?.[0]?.total_raised || 1;
  const maxPlat = data?.by_platform?.[0]?.total_raised || 1;
  return (
    <Modal title={campaign} subtitle="Campaign breakdown — where the money came from" onClose={onClose}
      footer={<ExportButton visible={canExport} onClick={exportDonations} title="Download this campaign's donations (CSV)" />}>
      {error && <div className="p-3 rounded-lg bg-rose-50 dark:bg-rose-950/40 text-rose-700 dark:text-rose-300 text-sm">{error}</div>}
      {!data && !error && <div className="py-10 flex justify-center"><Loader2 className="w-5 h-5 animate-spin text-slate-400" /></div>}
      {data && (
        <>
          <StatTiles tiles={[
            ['Total raised', money(data.total_raised, 2)],
            ['Donations', Number(data.donation_count).toLocaleString()],
            ['Donors', Number(data.donor_count).toLocaleString()],
            ['Share of funds', `${data.pct_of_total}%`],
          ]} />
          <div className="flex flex-col gap-1">
            <span className="text-[10px] font-extrabold uppercase tracking-wider text-slate-400">Contribution to all funds raised (under current filters)</span>
            <div className="w-full h-2.5 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden">
              <div className="h-full bg-emerald-500 rounded-full" style={{ width: `${Math.min(100, data.pct_of_total)}%` }} />
            </div>
          </div>
          {data.by_page?.length > 0 && (
            <div className="flex flex-col gap-3">
              <h4 className="text-[11px] font-extrabold uppercase tracking-widest text-slate-500 dark:text-slate-400">Pages the money came through</h4>
              {data.by_page.map(p => <BreakdownBar key={p.page} label={p.page} value={p.total_raised} max={maxPage} count={p.donation_count} />)}
            </div>
          )}
          {data.by_platform?.length > 0 && (
            <div className="flex flex-col gap-3">
              <h4 className="text-[11px] font-extrabold uppercase tracking-widest text-slate-500 dark:text-slate-400">By platform</h4>
              {data.by_platform.map(p => <BreakdownBar key={p.platform} label={p.platform || 'Unknown'} value={p.total_raised} max={maxPlat} count={p.donation_count} />)}
            </div>
          )}
          {data.by_payment_type?.length > 0 && (
            <div className="flex flex-col gap-3">
              <h4 className="text-[11px] font-extrabold uppercase tracking-widest text-slate-500 dark:text-slate-400">By payment type</h4>
              {data.by_payment_type.map(p => <BreakdownBar key={p.payment_type} label={p.payment_type || 'Unknown'} value={p.total_raised} max={data.by_payment_type[0]?.total_raised || 1} count={p.donation_count} />)}
            </div>
          )}
          {data.recent_donations?.length > 0 && (
            <div className="flex flex-col gap-2">
              <h4 className="text-[11px] font-extrabold uppercase tracking-widest text-slate-500 dark:text-slate-400">Recent donations</h4>
              <div className="border border-slate-200 dark:border-white/10 rounded-xl overflow-hidden">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="bg-slate-50 dark:bg-slate-800/60 text-[10px] uppercase tracking-wider text-slate-400">
                      <th className="px-3 py-2">Date</th><th className="px-3 py-2">Donor</th>
                      <th className="px-3 py-2">Amount</th><th className="px-3 py-2">Platform</th><th className="px-3 py-2">Page</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 dark:divide-white/5">
                    {data.recent_donations.slice(0, 25).map((d, i) => (
                      <tr key={i}>
                        <td className="px-3 py-2 whitespace-nowrap text-slate-500">{d.date}</td>
                        <td className="px-3 py-2 font-semibold text-slate-700 dark:text-slate-300">{d.donor}</td>
                        <td className="px-3 py-2 font-bold text-slate-900 dark:text-white">{money(d.amount, 2)}</td>
                        <td className="px-3 py-2 text-slate-500">{d.platform}</td>
                        <td className="px-3 py-2 text-slate-500 truncate max-w-[160px]">{d.page}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </Modal>
  );
}

function CategoryBreakdownModal({ category, kind, filters, activeCompany, canExport, onClose }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const params = buildParams(filters, activeCompany, { category, kind });
    fetch(`${API_BASE_URL}/api/overview/category-breakdown?${params.toString()}`)
      .then(r => r.ok ? r.json() : r.json().then(j => Promise.reject(j.detail || 'Failed to load')))
      .then(setData).catch(e => setError(String(e)));
  }, [category, kind, filters, activeCompany]);

  const exportCampaigns = () => {
    const params = buildParams(filters, activeCompany, { section: 'category_campaigns', category, kind });
    downloadFile(`${API_BASE_URL}/api/overview/export?${params.toString()}`, 'category_breakdown.csv');
  };

  return (
    <Modal title={category} subtitle={`${kind === 'heading' ? 'Category' : 'Sub-category'} breakdown — where the money came from`}
      onClose={onClose}
      footer={<ExportButton visible={canExport} onClick={exportCampaigns} title="Download this category's campaign breakdown (CSV)" />}>
      {error && <div className="p-3 rounded-lg bg-rose-50 dark:bg-rose-950/40 text-rose-700 dark:text-rose-300 text-sm">{error}</div>}
      {!data && !error && <div className="py-10 flex justify-center"><Loader2 className="w-5 h-5 animate-spin text-slate-400" /></div>}
      {data && (
        <>
          <StatTiles tiles={[
            ['Total raised', money(data.total_raised, 2)],
            ['Donations', Number(data.donation_count).toLocaleString()],
            ['Donors', Number(data.donor_count).toLocaleString()],
            ['Share of funds', `${data.pct_of_total}%`],
          ]} />
          <div className="flex flex-col gap-1">
            <span className="text-[10px] font-extrabold uppercase tracking-wider text-slate-400">
              Contribution to total funds ({money(data.total_all_filtered)} under current filters)
            </span>
            <div className="w-full h-2.5 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden">
              <div className="h-full bg-emerald-500 rounded-full" style={{ width: `${Math.min(100, data.pct_of_total)}%` }} />
            </div>
          </div>
          {data.by_campaign?.length > 0 && (
            <div className="flex flex-col gap-3">
              <h4 className="text-[11px] font-extrabold uppercase tracking-widest text-slate-500 dark:text-slate-400">Campaign pages the money came from</h4>
              {data.by_campaign.map(c => <BreakdownBar key={c.campaign} label={c.campaign} value={c.total_raised} max={data.by_campaign[0]?.total_raised || 1} count={c.donation_count} />)}
            </div>
          )}
          {data.by_platform?.length > 0 && (
            <div className="flex flex-col gap-3">
              <h4 className="text-[11px] font-extrabold uppercase tracking-widest text-slate-500 dark:text-slate-400">By platform</h4>
              {data.by_platform.map(p => <BreakdownBar key={p.platform} label={p.platform || 'Unknown'} value={p.total_raised} max={data.by_platform[0]?.total_raised || 1} count={p.donation_count} />)}
            </div>
          )}
          {data.by_subheading?.length > 0 && (
            <div className="flex flex-col gap-3">
              <h4 className="text-[11px] font-extrabold uppercase tracking-widest text-slate-500 dark:text-slate-400">By sub-category</h4>
              {data.by_subheading.map(s => <BreakdownBar key={s.sub_heading} label={s.sub_heading} value={s.total_raised} max={data.by_subheading[0]?.total_raised || 1} count={s.donation_count} />)}
            </div>
          )}
        </>
      )}
    </Modal>
  );
}

export default function OverviewView({ filters, user, metrics, accentColor, activeCompany = 'rethink' }) {
  const [headings, setHeadings] = useState([]);
  const [subheadings, setSubheadings] = useState([]);
  const [campaignData, setCampaignData] = useState({ items: [], total_count: 0, page: 1, total_pages: 1, max_raised: 0 });
  const [campaignPage, setCampaignPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [showAllCategories, setShowAllCategories] = useState(false);
  const [showAllSubs, setShowAllSubs] = useState(false);
  const [drill, setDrill] = useState(null); // {type: 'campaign'|'category', name, kind}

  const canExport = can(user, 'dashboard.export', activeCompany);

  useEffect(() => { setCampaignPage(1); }, [filters, activeCompany]);

  useEffect(() => {
    setLoading(true);
    const base = buildParams(filters, activeCompany);
    Promise.all([
      fetch(`${API_BASE_URL}/api/overview/headings?${buildParams(filters, activeCompany, { limit: 0 }).toString()}`).then(r => r.json()),
      fetch(`${API_BASE_URL}/api/overview/subheadings?${buildParams(filters, activeCompany, { limit: 0 }).toString()}`).then(r => r.json()),
    ]).then(([headData, subData]) => {
      setHeadings(Array.isArray(headData) ? headData : []);
      setSubheadings(Array.isArray(subData) ? subData : []);
      setLoading(false);
    }).catch(err => {
      console.error('Error loading overview data:', err);
      setLoading(false);
    });
  }, [filters, activeCompany]);

  useEffect(() => {
    const params = buildParams(filters, activeCompany, { page: campaignPage, page_size: 8 });
    fetch(`${API_BASE_URL}/api/overview/campaigns?${params.toString()}`)
      .then(r => r.json())
      .then(d => setCampaignData(d && d.items ? d : { items: [], total_count: 0, page: 1, total_pages: 1, max_raised: 0 }))
      .catch(err => console.error('Error loading campaigns:', err));
  }, [filters, activeCompany, campaignPage]);

  const exportSection = (section) => {
    const params = buildParams(filters, activeCompany, { section });
    downloadFile(`${API_BASE_URL}/api/overview/export?${params.toString()}`, `overview_${section}.csv`);
  };

  if (loading) {
    return (
      <div className="py-24 text-center text-slate-400 font-semibold animate-pulse">
        ⚡ Loading Executive Overview Analytics...
      </div>
    );
  }

  const colorMaps = {
    cyan: { text: 'text-cyan-500', bg: 'bg-cyan-500' },
    emerald: { text: 'text-emerald-500', bg: 'bg-emerald-500' },
    purple: { text: 'text-purple-500', bg: 'bg-purple-500' },
    rose: { text: 'text-rose-500', bg: 'bg-rose-500' }
  };
  const tColors = colorMaps[accentColor] || colorMaps.cyan;

  const now = new Date();
  const formattedDate = now.toLocaleDateString('en-US', { weekday: 'long', day: 'numeric', month: 'long' });
  const hour = now.getHours();
  const greeting = hour < 12 ? 'GOOD MORNING' : hour < 18 ? 'GOOD AFTERNOON' : 'GOOD EVENING';
  const rawName = user?.username || user?.email?.split('@')[0] || 'Admin';
  const displayName = rawName.charAt(0).toUpperCase() + rawName.slice(1);

  const maxCampaignRaised = campaignData.max_raised || 1;
  const visibleCategories = showAllCategories ? headings : headings.slice(0, 5);
  const visibleSubs = showAllSubs ? subheadings : subheadings.slice(0, 4);

  return (
    <div className="flex flex-col gap-8 pb-10">
      <div className="flex flex-col gap-1.5 pt-2">
        <span className="text-[10px] font-black uppercase tracking-widest text-slate-400 dark:text-slate-500">{greeting}</span>
        <h2 className="text-2xl sm:text-3xl font-black text-slate-800 dark:text-white tracking-tight">
          {displayName}, here is your overview
        </h2>
        <p className="text-xs font-semibold text-slate-500 dark:text-slate-400 mt-1">
          {formattedDate} • {Number(metrics?.total_txns || 0).toLocaleString()} donations tracked
        </p>
      </div>

      <div className="flex flex-col lg:flex-row gap-6 lg:gap-8 items-start">

        {/* LEFT COLUMN: Top Campaigns Table */}
        <div className="w-full lg:flex-[2] bg-white dark:bg-slate-900 border border-slate-200 dark:border-white/10 rounded-2xl shadow-[0_2px_10px_-3px_rgba(6,81,237,0.05)] overflow-hidden">
          <div className="px-6 py-4 border-b border-slate-100 dark:border-white/5 flex items-center justify-between">
            <h3 className="text-[11px] font-extrabold uppercase tracking-widest text-slate-500 dark:text-slate-400">
              Top Performing Campaigns
              <span className="ml-2 text-slate-400 normal-case tracking-normal font-bold">({Number(campaignData.total_count).toLocaleString()})</span>
            </h3>
            <ExportButton visible={canExport} onClick={() => exportSection('campaigns')} title="Download all campaigns (CSV)" />
          </div>

          <div className="w-full overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-slate-100 dark:border-white/5 bg-slate-50/50 dark:bg-slate-900/50">
                  <th className="px-6 py-3 text-[10px] font-extrabold uppercase tracking-wider text-slate-400">Campaign Name</th>
                  <th className="px-6 py-3 text-[10px] font-extrabold uppercase tracking-wider text-slate-400">Total Raised</th>
                  <th className="px-6 py-3 text-[10px] font-extrabold uppercase tracking-wider text-slate-400">Performance</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-white/5">
                {campaignData.items.map((camp, idx) => (
                  <tr key={idx} onClick={() => setDrill({ type: 'campaign', name: camp.campaign })}
                    className="hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors cursor-pointer">
                    <td className="px-6 py-3.5">
                      <div className="flex items-center gap-3">
                        <div className={`w-8 h-8 rounded-full ${tColors.bg}/10 flex items-center justify-center ${tColors.text} font-bold text-xs`}>
                          {camp.campaign.substring(0, 1).toUpperCase()}
                        </div>
                        <div className="flex flex-col min-w-0">
                          <span className="text-sm font-bold text-slate-800 dark:text-slate-200 truncate max-w-[250px]">{camp.campaign}</span>
                          <span className="text-[10px] font-semibold text-slate-400">{Number(camp.donation_count || 0).toLocaleString()} donations · click for breakdown</span>
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-3.5">
                      <span className="text-sm font-black text-slate-800 dark:text-slate-200">
                        £{camp.total_raised?.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                      </span>
                    </td>
                    <td className="px-6 py-3.5">
                      <div className="flex items-center gap-2">
                        <div className="w-24 h-1.5 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden">
                          <div className={`h-full ${tColors.bg} rounded-full`}
                            style={{ width: `${(camp.total_raised / maxCampaignRaised) * 100}%` }} />
                        </div>
                        <span className={`text-[10px] font-bold ${tColors.text} px-2 py-0.5 rounded-full ${tColors.bg}/10`}>
                          {Math.round((camp.total_raised / maxCampaignRaised) * 100)}%
                        </span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pager page={campaignData.page} totalPages={campaignData.total_pages} onPage={setCampaignPage} />
        </div>

        {/* RIGHT COLUMN: Widgets */}
        <div className="w-full lg:flex-[1] flex flex-col gap-6 lg:gap-8">

          {/* Category Distribution */}
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-white/10 rounded-2xl p-6 shadow-[0_2px_10px_-3px_rgba(6,81,237,0.05)] flex flex-col gap-6">
            <div className="flex items-center justify-between">
              <h3 className="text-[11px] font-extrabold uppercase tracking-widest text-slate-500 dark:text-slate-400">Category Distribution</h3>
              <ExportButton visible={canExport} onClick={() => exportSection('headings')} title="Download all categories (CSV)" />
            </div>

            <div className="flex flex-col gap-4">
              {visibleCategories.map((cat, idx) => (
                <button key={idx} type="button" onClick={() => setDrill({ type: 'category', name: cat.category, kind: 'heading' })}
                  className="flex flex-col gap-2 text-left group">
                  <div className="flex items-center justify-between text-xs font-semibold">
                    <span className="text-slate-700 dark:text-slate-300 truncate group-hover:text-blue-500 transition-colors">{cat.category}</span>
                    <span className="text-slate-900 dark:text-white font-bold">{money(cat.total_raised)}</span>
                  </div>
                  <div className="w-full h-1.5 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden">
                    <div className="h-full bg-slate-800 dark:bg-slate-400 rounded-full group-hover:bg-blue-500 dark:group-hover:bg-blue-400 transition-colors"
                      style={{ width: `${(cat.total_raised / (headings[0]?.total_raised || 1)) * 100}%` }} />
                  </div>
                </button>
              ))}
            </div>
            {headings.length > 5 && (
              <button type="button" onClick={() => setShowAllCategories(v => !v)}
                className="text-xs font-bold text-blue-500 hover:text-blue-600 self-start">
                {showAllCategories ? 'Show top 5' : `Show all ${headings.length} categories`}
              </button>
            )}
          </div>

          {/* Sub-Categories */}
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-white/10 rounded-2xl p-6 shadow-[0_2px_10px_-3px_rgba(6,81,237,0.05)] flex flex-col gap-5">
            <div className="flex items-center justify-between">
              <h3 className="text-[11px] font-extrabold uppercase tracking-widest text-slate-500 dark:text-slate-400">Top Sub-Categories</h3>
              <ExportButton visible={canExport} onClick={() => exportSection('subheadings')} title="Download all sub-categories (CSV)" />
            </div>

            <div className="flex flex-col gap-4 divide-y divide-slate-100 dark:divide-white/5">
              {visibleSubs.map((sub, idx) => (
                <button key={idx} type="button" onClick={() => setDrill({ type: 'category', name: sub.sub_heading, kind: 'subheading' })}
                  className="pt-4 first:pt-0 flex flex-col gap-1 text-left group">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-bold text-slate-800 dark:text-slate-200 group-hover:text-blue-500 transition-colors">{sub.sub_heading}</span>
                    <span className="text-[10px] font-bold text-slate-600 dark:text-slate-400 bg-slate-100 dark:bg-slate-800 px-2 py-1 rounded-md">
                      {money(sub.total_raised)}
                    </span>
                  </div>
                  <span className="text-xs text-slate-500 dark:text-slate-500">{Number(sub.donation_count || 0).toLocaleString()} gifts · click for breakdown</span>
                </button>
              ))}
            </div>
            {subheadings.length > 4 && (
              <button type="button" onClick={() => setShowAllSubs(v => !v)}
                className="text-xs font-bold text-blue-500 hover:text-blue-600 self-start">
                {showAllSubs ? 'Show top 4' : `Show all ${subheadings.length} sub-categories`}
              </button>
            )}
          </div>

        </div>
      </div>

      {drill?.type === 'campaign' && (
        <CampaignBreakdownModal campaign={drill.name} filters={filters} activeCompany={activeCompany}
          canExport={canExport} onClose={() => setDrill(null)} />
      )}
      {drill?.type === 'category' && (
        <CategoryBreakdownModal category={drill.name} kind={drill.kind} filters={filters} activeCompany={activeCompany}
          canExport={canExport} onClose={() => setDrill(null)} />
      )}
    </div>
  );
}
