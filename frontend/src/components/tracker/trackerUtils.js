// Shared helpers for the Sponsorship Tracker components.

export const clean = (v) => {
  const s = (v ?? '').toString().trim();
  return ['n/a', 'nan', 'none', 'null'].includes(s.toLowerCase()) ? '' : s;
};

/** Normalises a donor from qualifying-donors / search-any-donor / a campaign organizer into an editor row. */
export const toDraftDonor = (d, role = 'donor') => ({
  key: `${d.donor_id || d.donor_email || d.email || d.name}_${Math.random().toString(36).slice(2, 7)}`,
  donor_id: clean(d.donor_id),
  donor_name: clean(d.donor_name || d.name),
  donor_email: clean(d.donor_email || d.email),
  donor_phone: clean(d.donor_phone || d.phone),
  contribution_amount: Number(d.contribution_amount || 0),
  is_primary: Boolean(d.is_primary),
  is_manual: Boolean(d.is_manual),
  role,
  slots: d.remaining_slots !== undefined ? { remaining: d.remaining_slots, max: d.max_slots, used: d.allocated_count } : null
});

const PLACEHOLDER_IDS = new Set(['', 'missing email', 'no email', 'noemail', 'unknown', 'n/a', 'na', 'none', 'nan', 'null', 'anonymous', 'anonymous donor', '-']);

/**
 * Key used to open a donor's profile. Prefers a real email; a donor row on a sponsorship without one is
 * opened by its own row id (ad_<id>) so placeholder ids like "missing email" never merge different people.
 */
export const donorKeyFor = (d) => {
  if (!d) return null;
  const id = clean(d.donor_id);
  if (d.is_manual && id.startsWith('manual_')) return id;
  const email = clean(d.donor_email || d.email);
  if (email.includes('@')) return email;
  if (typeof d.id === 'number') return `ad_${d.id}`;
  if (d.allocation_donor_id) return `ad_${d.allocation_donor_id}`;
  return PLACEHOLDER_IDS.has(id.toLowerCase()) ? null : id;
};

/** Template rows are stored per theme; Sisters' Project under Rethink is saved as 'sp_rethink'. */
export const themeStorageKey = (themeId, companyId) => (themeId === 'sp' && companyId === 'rethink' ? 'sp_rethink' : themeId);

/** Filter values <-> URL query (prefixed per tab), so filters survive a reload and can be shared. */
export const readFiltersFromUrl = (prefix) => {
  const out = {};
  try {
    new URLSearchParams(window.location.search).forEach((v, k) => {
      if (k.startsWith(`${prefix}.`)) out[k.slice(prefix.length + 1)] = v === 'true' ? true : v;
    });
  } catch { /* ignore */ }
  return out;
};

export const writeFiltersToUrl = (prefix, values) => {
  try {
    const params = new URLSearchParams(window.location.search);
    [...params.keys()].filter(k => k.startsWith(`${prefix}.`)).forEach(k => params.delete(k));
    Object.entries(values).forEach(([k, v]) => {
      if (v !== '' && v !== undefined && v !== null && v !== 'all' && v !== false) params.set(`${prefix}.${k}`, String(v));
    });
    const qs = params.toString();
    window.history.replaceState(null, '', `${window.location.pathname}${qs ? `?${qs}` : ''}${window.location.hash}`);
  } catch { /* ignore */ }
};

export const filtersToParams = (values) => {
  const p = new URLSearchParams();
  Object.entries(values).forEach(([k, v]) => {
    if (v !== '' && v !== undefined && v !== null && v !== 'all' && v !== false) p.append(k, String(v));
  });
  return p;
};
