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

