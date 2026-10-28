// URL-based routing without a router library: the address is /<charity>/<page>[#donor=<id>], e.g. /rethink/donors.
// App.jsx keeps it in step with the selected page / charity / donor, and back / forward restore them.
// The open donor goes in the #fragment: browsers never send it to the server, so donor ids (often an email
// address) don't end up in server access logs. /gmail-callback, the #ops hash and a page's own query parameters
// (e.g. Tracker filters) are left alone.

export const TAB_SLUGS = {
  overview: 'dashboard', kanban: 'kanban', ltv: 'ltv', explorer: 'explorer', donors: 'donors', email: 'email',
  fundraisers: 'fundraisers', payouts: 'payouts', tracker: 'tracker', classifications: 'classifications',
  expenses: 'expenses', admin: 'admin', access: 'access',
};
const SLUG_TABS = Object.fromEntries(Object.entries(TAB_SLUGS).map(([tab, slug]) => [slug, tab]));
const RESERVED = new Set(['gmail-callback', 'assets', 'api', 'ws']);

const hashDonor = () => {
  const m = (window.location.hash || '').match(/^#donor=(.+)$/);
  return m ? decodeURIComponent(m[1]) : null;
};

/** {company, tab, donor} from the current address (fields are null when not given). */
export function readRoute() {
  const parts = window.location.pathname.split('/').filter(Boolean).map(p => decodeURIComponent(p).toLowerCase());
  const out = { company: null, tab: null, donor: hashDonor() };
  if (!parts.length || RESERVED.has(parts[0])) return out;
  if (SLUG_TABS[parts[0]]) return { ...out, tab: SLUG_TABS[parts[0]] }; // /donors (no charity)
  out.company = parts[0];
  if (parts[1] && SLUG_TABS[parts[1]]) out.tab = SLUG_TABS[parts[1]];
  return out;
}

export function routePath(company, tab) {
  return `/${encodeURIComponent(company || 'rethink')}/${TAB_SLUGS[tab] || 'dashboard'}`;
}

/** Puts page / charity / donor into the address. A new page, charity or donor adds a history entry (back works);
 *  the first load from a bare address replaces it. */
export function writeRoute(company, tab, donor) {
  if (window.location.pathname === '/gmail-callback') return;
  const path = routePath(company, tab);
  const samePage = window.location.pathname === path;
  const search = samePage ? window.location.search : '';
  const opsHash = (window.location.hash || '').startsWith('#ops') ? window.location.hash : '';
  const hash = donor ? `#donor=${encodeURIComponent(donor)}` : opsHash;
  const url = `${path}${search}${hash}`;
  if (url === `${window.location.pathname}${window.location.search}${window.location.hash}`) return;
  const fromBare = !readRoute().tab;
  const sameDonor = hashDonor() === (donor || null);
  if (fromBare || (samePage && sameDonor)) window.history.replaceState(null, '', url);
  else window.history.pushState(null, '', url);
}
