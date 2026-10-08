// Frontend API Configuration
// In production on Vercel, requests to /api are proxied to FastAPI Cloud via vercel.json edge rewrites, completely preventing CORS restrictions.
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '';

/**
 * Generates authenticated request headers for API calls.
 * Automatically injects the JWT Bearer token and user context headers.
 */
export const getAuthHeaders = (extra = {}, user = null) => {
  const token = localStorage.getItem('analytics_token');
  const userStr = localStorage.getItem('analytics_user');
  let parsedUser = null;
  if (userStr) {
    try {
      parsedUser = JSON.parse(userStr);
    } catch (e) {}
  }
  const headers = { ...extra };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  const email = user?.email || parsedUser?.email;
  const username = user?.username || parsedUser?.username;
  const role = user?.role || parsedUser?.role;

  if (email) headers['X-User-Email'] = email;
  if (username || email) headers['X-User-Identity'] = username || email;
  if (role) headers['X-User-Role'] = role;
  return headers;
};

const isApiRequest = (url) => {
  if (!url) return false;
  if (url.startsWith('/api')) return true;
  if (API_BASE_URL && url.startsWith(`${API_BASE_URL}/api`)) return true;
  try {
    const parsed = new URL(url, window.location.origin);
    return parsed.origin === window.location.origin && parsed.pathname.startsWith('/api');
  } catch {
    return false;
  }
};

/**
 * Wraps window.fetch so every /api request carries the JWT Bearer token, and an
 * expired/invalid session sends the user back to the login screen. The backend no
 * longer trusts unsigned identity headers, so this is what keeps calls authenticated.
 */
export const installAuthFetch = () => {
  if (window.__authFetchInstalled) return;
  window.__authFetchInstalled = true;
  const nativeFetch = window.fetch.bind(window);

  window.fetch = async (input, init = {}) => {
    const url = typeof input === 'string' ? input : input?.url || '';
    if (!isApiRequest(url)) return nativeFetch(input, init);

    const token = localStorage.getItem('analytics_token');
    const headers = new Headers(init.headers || (input instanceof Request ? input.headers : undefined));
    if (token && !headers.has('Authorization')) headers.set('Authorization', `Bearer ${token}`);

    const response = await nativeFetch(input, { ...init, headers });
    const isLogin = url.includes('/api/auth/login');
    if (response.status === 401 && !isLogin && localStorage.getItem('analytics_user')) {
      localStorage.removeItem('analytics_user');
      localStorage.removeItem('analytics_token');
      window.location.reload();
    }
    return response;
  };
};

