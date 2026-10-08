import React, { Suspense, lazy, useEffect, useRef, useState } from 'react';
import { reloadForNewBuild } from './config';
import Navbar from './components/Navbar';
import HorizontalFilters from './components/HorizontalFilters';
import NavigationSidebar from './components/NavigationSidebar';
// Lazy page that survives deploys: if its chunk is gone (tab opened on an older build), reload once.
const lazyPage = (loader) => lazy(() => loader().catch((err) => {
  if (reloadForNewBuild()) return new Promise(() => {}); // page is reloading
  throw err;
}));
const OverviewView = lazyPage(() => import('./components/OverviewView'));
const LtvView = lazyPage(() => import('./components/LtvView'));
const KanbanBoard = lazyPage(() => import('./components/KanbanBoard'));
const ExplorerView = lazyPage(() => import('./components/ExplorerView'));
const ClassificationView = lazyPage(() => import('./components/ClassificationView'));
const ExpenseView = lazyPage(() => import('./components/ExpenseView'));
const AdminView = lazyPage(() => import('./components/AdminView'));
const TrackerView = lazyPage(() => import('./components/TrackerView'));
const PayoutsView = lazyPage(() => import('./components/PayoutsView'));
const FundraiserView = lazyPage(() => import('./components/FundraiserView'));
import DonorDrawer from './components/DonorDrawer';
import LoginView from './components/LoginView';
const OpsConsole = lazyPage(() => import('./components/ops/OpsConsole'));

import { TrendingUp, Crown, Columns, Table, Shield, CreditCard, Database, Target, Gift, Layers, DollarSign, Filter, ChevronUp, ChevronDown } from 'lucide-react';

import { API_BASE_URL } from './config';


const INITIAL_FILTERS = {
  payment_type: 'All Payment Types',
  tier: 'All Classifications',
  source: 'All Sources (Combined)',
  programme_fund: 'All Programme Funds',
  heading: 'All Headings',
  subheading: 'All Sub-Headings',
  country: 'All Project Countries',
  code: 'All Codes',
  zakat: 'All Zakat Status',
  donor_country: 'All Donor Countries',
  campaign: 'All Campaigns',
  campaign_search: '',
  gift_aid: 'All Gift Aid Status',
  start_date: '',
  end_date: ''
};

const DEFAULT_COMPANIES_FALLBACK = [
  { id: 'rethink', name: 'Rethink Charity', short_code: 'Rethink', accent_color: 'cyan', logo_url: '', is_active: 1 },
  { id: 'iqra', name: 'Iqra', short_code: 'Iqra', accent_color: 'emerald', logo_url: '', is_active: 1 }
];

export default function App() {
  const [user, setUser] = useState(null);
  const [activeTab, setActiveTab] = useState('overview');
  const [selectedDonor, setSelectedDonor] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [filters, setFilters] = useState(INITIAL_FILTERS);
  
  // Multi-Company State
  const [companies, setCompanies] = useState(() => {
    try {
      const cached = localStorage.getItem('crm_companies');
      if (cached) {
        const parsed = JSON.parse(cached);
        return parsed.filter(c => c.id !== 'sp');
      }
    } catch (e) {}
    return DEFAULT_COMPANIES_FALLBACK;
  });

  const [activeCompany, setActiveCompany] = useState(() => {
    const saved = localStorage.getItem('crm_active_company') || 'rethink';
    return saved === 'sp' ? 'rethink' : saved;
  });

  const [accentColor, setAccentColor] = useState(() => {
    return localStorage.getItem('crm_accent') || 'cyan';
  });

  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [showFilters, setShowFilters] = useState(true);
  const [metricsExpanded, setMetricsExpanded] = useState(true);
  const [filtersHovered, setFiltersHovered] = useState(false);
  const [dataVersion, setDataVersion] = useState(0);

  const fetchCompanies = () => {
    fetch(`${API_BASE_URL}/api/admin/companies`)
      .then(r => r.json())
      .then(data => {
        if (data.status === 'success' && data.companies?.length > 0) {
          setCompanies(data.companies);
          try {
            localStorage.setItem('crm_companies', JSON.stringify(data.companies));
          } catch (e) {}
        }
      })
      .catch(err => console.warn('Could not fetch registered companies:', err));
  };

  useEffect(() => {
    fetchCompanies();
  }, [dataVersion]);

  // If previous session had a removed company (such as 'sp') or invalid tenant, auto-reset to rethink
  useEffect(() => {
    if (activeCompany !== 'all' && companies.length > 0) {
      const exists = companies.some(c => c.id === activeCompany);
      if (!exists || activeCompany === 'sp') {
        setActiveCompany('rethink');
        try {
          localStorage.setItem('crm_active_company', 'rethink');
        } catch (e) {}
      }
    }
  }, [companies, activeCompany]);

  const handleSwitchCompany = (newCompanyId) => {
    const cid = String(newCompanyId).toLowerCase().trim();
    setActiveCompany(cid);
    try {
      localStorage.setItem('crm_active_company', cid);
    } catch (e) {}
    
    // Auto-align accent color if switching to a company with specific branding
    if (cid !== 'all') {
      const comp = companies.find(c => c.id === cid);
      if (comp && comp.accent_color) {
        setAccentColor(comp.accent_color);
        try {
          localStorage.setItem('crm_accent', comp.accent_color);
        } catch (e) {}
      }
    }
    setDataVersion(v => v + 1);
  };

  // Auto-collapse sidebar after 3 seconds of switching tab
  const handleSetActiveTab = (tabId) => {
    setActiveTab(tabId);
    setTimeout(() => {
      setSidebarCollapsed(true);
    }, 3000);
  };

  const [theme, setTheme] = useState(() => {
    const savedTheme = localStorage.getItem('crm_theme');
    if (savedTheme === 'light' || savedTheme === 'dark') return savedTheme;
    return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  });

  const handleSignOut = () => {
    setUser(null);
    localStorage.removeItem('analytics_user');
    localStorage.removeItem('analytics_token');
  };

  // Auto-restore session from localStorage
  useEffect(() => {
    const savedUser = localStorage.getItem('analytics_user');
    if (savedUser) {
      try {
        const parsed = JSON.parse(savedUser);
        
        // Check Session Expiry (24 hours = 86400000 ms)
        const EXPIRY_MS = 24 * 60 * 60 * 1000;
        if (parsed.login_timestamp && (Date.now() - parsed.login_timestamp > EXPIRY_MS)) {
          console.warn("Session expired after 24 hours.");
          handleSignOut();
          return;
        }

        setUser(parsed);

        // Real-time verification & permission sync with backend
        const token = localStorage.getItem('analytics_token');
        const headers = token ? { 'Authorization': `Bearer ${token}` } : {};
        fetch(`${API_BASE_URL}/api/auth/me?user_identity=${encodeURIComponent(parsed.email || parsed.username)}`, { headers })
          .then(res => {
            if (res.status === 401 || res.status === 404) {
              throw new Error('Invalid user session');
            }
            return res.json();
          })
          .then(data => {
            if (data.status === 'success' && data.user) {
              const updatedUser = {
                ...data.user,
                login_timestamp: parsed.login_timestamp || Date.now()
              };
              setUser(updatedUser);
              localStorage.setItem('analytics_user', JSON.stringify(updatedUser));
            } else {
              handleSignOut();
            }
          })
          .catch(err => {
            if (err.message === 'Invalid user session') {
              handleSignOut();
            }
          });
      } catch (e) {
        console.error("Error restoring session:", e);
        handleSignOut();
      }
    }
  }, []);

  // Update theme class on HTML root element
  useEffect(() => {
    document.documentElement.classList.remove('theme-light', 'theme-dark');
    document.documentElement.classList.add(theme === 'light' ? 'theme-light' : 'theme-dark');
    document.documentElement.style.colorScheme = theme;
    localStorage.setItem('crm_theme', theme);
  }, [theme]);

  useEffect(() => {
    localStorage.setItem('crm_accent', accentColor);
  }, [accentColor]);

  const handleToggleTheme = () => {
    setTheme(prev => (prev === 'dark' ? 'light' : 'dark'));
  };

  const handleDataChange = () => {
    setDataVersion(v => v + 1);
  };

  // Fetch Live Summary Metrics with company_id
  useEffect(() => {
    if (!user) return;
    const params = new URLSearchParams();
    params.append('company_id', activeCompany);

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
      if (filters.campaign && filters.campaign !== 'All Campaigns') params.append('campaign', filters.campaign);
      if (filters.gift_aid) params.append('gift_aid', filters.gift_aid);
      if (filters.start_date) params.append('start_date', filters.start_date);
      if (filters.end_date) params.append('end_date', filters.end_date);
    }
    fetch(`${API_BASE_URL}/api/metrics/summary?${params.toString()}`)
      .then(res => res.json())
      .then(data => setMetrics(data))
      .catch(err => console.error('Error fetching metrics summary:', err));
  }, [user, filters, dataVersion, activeCompany]);

  const handleFilterChange = (key, value) => {
    setFilters(prev => ({ ...prev, [key]: value }));
  };

  const handleResetFilters = () => {
    setFilters(INITIAL_FILTERS);
  };

  // ---- Hidden ops console (super admins): Konami code ↑ ↑ ↓ ↓ ← → ← → B A ----
  const [opsOpen, setOpsOpen] = useState(false); // false | 'status' | 'logs' | 'sessions' | 'cache'
  const [opsHealth, setOpsHealth] = useState(null);
  const isSuperAdmin = user?.role === 'super_admin';
  useEffect(() => {
    if (!isSuperAdmin) return undefined;
    const SEQUENCE = ['arrowup', 'arrowup', 'arrowdown', 'arrowdown', 'arrowleft', 'arrowright', 'arrowleft', 'arrowright', 'b', 'a'];
    let pos = 0;
    let last = 0;
    const onKey = (e) => {
      const tag = (e.target?.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'textarea' || tag === 'select' || e.target?.isContentEditable) return;
      const key = (e.key || '').toLowerCase();
      // Shortcut: Ctrl+Alt+O (Cmd+Option+O on Mac). e.code is used because Option changes e.key on Mac.
      if ((e.ctrlKey || e.metaKey) && e.altKey && (e.code === 'KeyO' || key === 'o')) {
        e.preventDefault();
        setOpsOpen('status');
        return;
      }
      const now = Date.now();
      if (now - last > 3000) pos = 0;
      last = now;
      pos = key === SEQUENCE[pos] ? pos + 1 : (key === SEQUENCE[0] ? 1 : 0);
      if (pos === SEQUENCE.length) { pos = 0; setOpsOpen('status'); }
    };
    // Direct links: /#ops-status, /#ops-logs, /#ops-sessions, /#ops-cache (or just /#ops)
    const fromHash = () => {
      const m = (window.location.hash || '').match(/^#ops(?:-(status|logs|sessions|cache))?$/);
      if (m) setOpsOpen(m[1] || 'status');
    };
    fromHash();
    window.addEventListener('keydown', onKey);
    window.addEventListener('hashchange', fromHash);
    return () => { window.removeEventListener('keydown', onKey); window.removeEventListener('hashchange', fromHash); };
  }, [isSuperAdmin]);
  useEffect(() => {
    if (!isSuperAdmin) return undefined;
    const check = () => fetch(`${API_BASE_URL}/api/ops/status`).then(r => (r.ok ? r.json() : null)).then(d => setOpsHealth(d?.overall || null)).catch(() => {});
    check();
    const t = setInterval(check, 5 * 60 * 1000);
    return () => clearInterval(t);
  }, [isSuperAdmin]);

  // ---- "New data available" notice: poll the cheap data-version token (works across all workers) ----
  const [dataUpdated, setDataUpdated] = useState(false);
  const versionTokenRef = useRef(null);
  useEffect(() => {
    if (!user) return undefined;
    versionTokenRef.current = null;
    setDataUpdated(false);
    const check = () => fetch(`${API_BASE_URL}/api/cache/versions?company_id=${encodeURIComponent(activeCompany)}`)
      .then(r => (r.ok ? r.json() : null))
      .then(d => {
        if (!d?.token) return;
        if (versionTokenRef.current && versionTokenRef.current !== d.token) setDataUpdated(true);
        versionTokenRef.current = d.token;
      })
      .catch(() => {});
    check();
    const t = setInterval(check, 60000);
    const onFocus = () => check();
    window.addEventListener('focus', onFocus);
    return () => { clearInterval(t); window.removeEventListener('focus', onFocus); };
  }, [user, activeCompany, dataVersion]);

  const handleLoginSuccess = (userData, accessToken) => {
    const sessionData = {
      ...userData,
      login_timestamp: Date.now()
    };
    setUser(sessionData);
    localStorage.setItem('analytics_user', JSON.stringify(sessionData));
    if (accessToken) {
      localStorage.setItem('analytics_token', accessToken);
    }
  };

  if (!user) {
    return <LoginView theme={theme} onToggleTheme={handleToggleTheme} onLoginSuccess={handleLoginSuccess} />;
  }

  const showFiltersForTab = ['overview', 'ltv', 'kanban', 'explorer', 'tracker'].includes(activeTab);
  const currentCompany = companies.find(c => c.id === activeCompany) || {
    id: activeCompany,
    name: activeCompany === 'all' ? 'All Companies (Consolidated)' : 'Rethink Charity',
    short_code: activeCompany === 'all' ? 'All' : 'Rethink',
    accent_color: accentColor,
    logo_url: ''
  };

  return (
    <div className="h-screen w-full flex overflow-hidden bg-slate-50 dark:bg-slate-900 transition-colors">
      
      {/* Left Navigation Sidebar */}
      <NavigationSidebar 
        activeTab={activeTab} 
        setActiveTab={handleSetActiveTab} 
        accentColor={accentColor}
        setAccentColor={setAccentColor}
        activeCompany={activeCompany}
        currentCompany={currentCompany}
        companies={companies}
      />

      {/* Main Right Area */}
      <div className="flex-1 flex flex-col h-screen min-w-0 overflow-hidden relative">
        {/* Top Navbar with Company Switcher */}
        <Navbar 
          user={user} 
          theme={theme} 
          onToggleTheme={handleToggleTheme} 
          onSignOut={handleSignOut} 
          accentColor={accentColor}
          setAccentColor={setAccentColor}
          metrics={metrics}
          activeCompany={activeCompany}
          onSwitchCompany={handleSwitchCompany}
          companies={companies}
          currentCompany={currentCompany}
        />

        {/* Scrollable Main Workspace */}
        <main className="flex-1 overflow-y-auto px-5 py-5 pb-24 custom-scrollbar">
          <div className="max-w-[1680px] w-full mx-auto flex flex-col gap-5">
            
            {/* Horizontal Filter Pills Bar */}
            {showFiltersForTab && (
              <HorizontalFilters 
                filters={filters} 
                onFilterChange={handleFilterChange} 
                onResetFilters={handleResetFilters} 
                accentColor={accentColor}
                activeCompany={activeCompany}
              />
            )}

            {/* Active Tab Main Content (each view is a separate, lazily loaded chunk) */}
            <div className="w-full min-w-0">
              <Suspense fallback={<div className="py-24 flex justify-center"><div className="w-6 h-6 border-2 border-slate-300 border-t-blue-500 rounded-full animate-spin" /></div>}>
              {activeTab === 'overview' && (
                <OverviewView 
                  key={`${activeCompany}-${dataVersion}`} 
                  filters={filters} 
                  user={user} 
                  metrics={metrics} 
                  accentColor={accentColor} 
                  activeCompany={activeCompany}
                />
              )}
              {activeTab === 'ltv' && (
                <LtvView 
                  key={`${activeCompany}-${dataVersion}`} 
                  filters={filters} 
                  activeCompany={activeCompany}
                />
              )}
              {activeTab === 'kanban' && (
                <KanbanBoard 
                  key={`${activeCompany}-${dataVersion}`} 
                  filters={filters} 
                  onSelectDonor={setSelectedDonor} 
                  activeCompany={activeCompany}
                />
              )}
              {activeTab === 'explorer' && (
                <ExplorerView 
                  key={`${activeCompany}-${dataVersion}`} 
                  user={user} 
                  filters={filters} 
                  onSelectDonor={setSelectedDonor} 
                  onDataChange={handleDataChange} 
                  activeCompany={activeCompany}
                  companies={companies}
                />
              )}
              {activeTab === 'fundraisers' && (
                <FundraiserView 
                  key={`${activeCompany}-${dataVersion}`} 
                  user={user} 
                  accentColor={accentColor} 
                  activeCompany={activeCompany}
                />
              )}
              {activeTab === 'payouts' && (
                <PayoutsView 
                  key={`${activeCompany}-${dataVersion}`} 
                  user={user} 
                  accentColor={accentColor} 
                  onDataChange={handleDataChange} 
                  activeCompany={activeCompany}
                />
              )}
              {activeTab === 'tracker' && (
                <TrackerView 
                  key={`${activeCompany}-${dataVersion}`} 
                  user={user} 
                  filters={filters} 
                  onSelectDonor={setSelectedDonor} 
                  accentColor={accentColor} 
                  activeCompany={activeCompany}
                />
              )}
              {activeTab === 'classifications' && (
                <ClassificationView 
                  key={`${activeCompany}-${dataVersion}`} 
                  user={user} 
                  onDataChange={handleDataChange} 
                  activeCompany={activeCompany}
                />
              )}
              {activeTab === 'expenses' && (
                <ExpenseView 
                  key={`${activeCompany}-${dataVersion}`} 
                  user={user} 
                  activeCompany={activeCompany}
                  companies={companies}
                />
              )}
              {activeTab === 'admin' && (
                <AdminView 
                  key={`${activeCompany}-${dataVersion}`} 
                  user={user} 
                  onDataChange={handleDataChange} 
                  activeCompany={activeCompany}
                  companies={companies}
                  onCompaniesChange={fetchCompanies}
                />
              )}
              </Suspense>
            </div>

          </div>
        </main>
      </div>

      {/* Donor 360° Profile Drawer Modal */}
      <DonorDrawer donorId={selectedDonor} onClose={() => setSelectedDonor(null)} activeCompany={activeCompany} />

      {isSuperAdmin && opsHealth === 'down' && !opsOpen && (
        <button type="button" onClick={() => setOpsOpen('status')} title="A platform integration is not working - open the ops console"
          className="fixed bottom-3 right-3 z-[70] w-3 h-3 rounded-full bg-rose-500 animate-pulse shadow" aria-label="Integration problem" />
      )}
      {isSuperAdmin && opsOpen && (
        <Suspense fallback={null}>
          <OpsConsole initialTab={opsOpen} onClose={() => {
            setOpsOpen(false);
            if ((window.location.hash || '').startsWith('#ops')) window.history.replaceState(null, '', window.location.pathname + window.location.search);
          }} />
        </Suspense>
      )}

      {dataUpdated && (
        <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-[65] px-4 py-2.5 rounded-xl bg-slate-900 text-white text-xs shadow-xl flex items-center gap-3">
          <span>New data is available (synced donations or changes by a colleague).</span>
          <button type="button" onClick={() => { setDataUpdated(false); handleDataChange(); }} className="px-2.5 py-1 rounded-lg bg-blue-600 hover:bg-blue-700 font-bold">Refresh</button>
          <button type="button" onClick={() => setDataUpdated(false)} className="text-slate-400 hover:text-white">Later</button>
        </div>
      )}
    </div>
  );
}
