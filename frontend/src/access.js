// What the signed-in person may see and do, from the access the SERVER computed (user.access from /api/auth/me).
// This only decides what to show: every action is checked again on the server, so hiding a button is never the
// only protection. The page refreshes user.access live when an admin changes it (App.jsx, `access` stream event).

export const isSuperAdmin = (user) => user?.role === 'super_admin';

const companyPerms = (user, company) => {
  const companies = user?.access?.companies || {};
  return companies[(company || '').toLowerCase()] || [];
};

/** Charities the person can open at all. */
export function accessibleCompanies(user) {
  if (isSuperAdmin(user)) return null; // all
  return Object.keys(user?.access?.companies || {});
}

/** Does the person hold `perm` in `company`? 'all' = in every charity they could see consolidated. */
export function can(user, perm, company) {
  if (!user) return false;
  if (isSuperAdmin(user)) return true;
  const comp = (company || '').toLowerCase();
  if (!comp || comp === 'all') {
    const all = Object.values(user?.access?.companies || {});
    return all.length > 0 && all.every(p => p.includes(perm)) && (user.allowed_companies || []).includes('ALL');
  }
  return companyPerms(user, comp).includes(perm);
}

export const canAny = (user, perms, company) => perms.some(p => can(user, p, company));

/** Held in at least one charity (for screens that aren't about a single charity, e.g. Users & Access). */
export function canSomewhere(user, perm) {
  if (isSuperAdmin(user)) return true;
  return Object.values(user?.access?.companies || {}).some(p => p.includes(perm));
}

/** The record scope (e.g. fundraiser ids) the person is limited to in this charity, or null = not limited. */
export function recordScope(user, company, resource) {
  if (isSuperAdmin(user)) return null;
  const ids = user?.access?.scopes?.[(company || '').toLowerCase()]?.[resource];
  return ids && ids.length ? ids : null;
}

// Sidebar tab -> any of these permissions shows it.
export const TAB_PERMISSIONS = {
  overview: ['dashboard.view'],
  kanban: ['dashboard.view'],
  ltv: ['dashboard.view'],
  explorer: ['explorer.view'],
  donors: ['donors.view'],
  email: ['email.view'],
  fundraisers: ['fundraisers.view'],
  payouts: ['payouts.view', 'stripe.view'],
  tracker: ['tracker.view'],
  classifications: ['classifications.view'],
  expenses: ['expenses.view'],
  admin: ['data.view', 'data.upload', 'data.tags', 'data.purge', 'charities.edit'],
  access: ['users.view'],
};

// Tabs that respect a "limited to specific fundraisers" scope; the server refuses every other page there.
const SCOPED_TABS = ['explorer', 'donors', 'fundraisers'];

export function canSeeTab(user, tabId, company) {
  if (tabId === 'access') return canSomewhere(user, 'users.view');
  if (recordScope(user, company, 'fundraiser') && !SCOPED_TABS.includes(tabId)) return false;
  const perms = TAB_PERMISSIONS[tabId];
  return !perms || canAny(user, perms, company);
}

// For components that read the session from localStorage instead of receiving `user` as a prop.
export function storedUser() {
  try { return JSON.parse(localStorage.getItem('analytics_user') || 'null'); } catch { return null; }
}
export function storedCompany() {
  try { return localStorage.getItem('crm_active_company') || 'rethink'; } catch { return 'rethink'; }
}

/** For send / save buttons in components without `user`: true (after telling the person) when they lack `perm`
 *  in the active charity. The server refuses the action anyway; this just explains it up front. */
export function denyUnless(perm, company) {
  if (can(storedUser(), perm, company || storedCompany())) return false;
  window.alert("Your access doesn't include this action. Ask an admin if you need it.");
  return true;
}
