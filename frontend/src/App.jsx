import React, { useEffect, useState } from 'react';
import Navbar from './components/Navbar';
import HorizontalFilters from './components/HorizontalFilters';
import NavigationSidebar from './components/NavigationSidebar';
import OverviewView from './components/OverviewView';
import LtvView from './components/LtvView';
import KanbanBoard from './components/KanbanBoard';
import ExplorerView from './components/ExplorerView';
import ClassificationView from './components/ClassificationView';
import ExpenseView from './components/ExpenseView';
import AdminView from './components/AdminView';
import TrackerView from './components/TrackerView';
import PayoutsView from './components/PayoutsView';
import FundraiserView from './components/FundraiserView';
import DonorDrawer from './components/DonorDrawer';
import LoginView from './components/LoginView';

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
        fetch(`${API_BASE_URL}/api/auth/me?user_identity=${parsed.email || parsed.username}`)
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

  const handleLoginSuccess = (userData) => {
    const sessionData = {
      ...userData,
      login_timestamp: Date.now()
    };
    setUser(sessionData);
    localStorage.setItem('analytics_user', JSON.stringify(sessionData));
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

            {/* Active Tab Main Content */}
            <div className="w-full min-w-0">
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
            </div>

          </div>
        </main>
      </div>

      {/* Donor 360° Profile Drawer Modal */}
      <DonorDrawer donorId={selectedDonor} onClose={() => setSelectedDonor(null)} />
    </div>
  );
}
