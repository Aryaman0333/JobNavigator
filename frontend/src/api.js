import axios from 'axios';

const api = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' },
  withCredentials: true,  // send jn_session + jn_account cookies on every request
});

// Attach API key from localStorage as a fallback header (extension + API client parity)
api.interceptors.request.use((config) => {
  const apiKey = localStorage.getItem('jobnavigator_api_key') || '';
  if (apiKey) {
    config.headers['X-API-Key'] = apiKey;
  }
  return config;
});

// What an auth failure asks the UI to do (backend/accounts/auth.py, MT-10/11):
//   'account'      401 `account_required` (header X-JN-Auth: account): the install
//                  password is fine but this browser has picked no account → picker
//   'pin_required' 401 from /auth/switch (or a PIN change): the account needs its PIN
//   'wrong_pin'    401 + `tries_left`
//   'pin_cooldown' 429 + Retry-After seconds (5 wrong tries → 30 s)
//   'login'        any other 401: the install password is missing or wrong → sign-in
// null for everything else (including a 429 that is not a PIN cooldown).
export const PIN_FAILURES = ['pin_required', 'wrong_pin', 'pin_cooldown'];
export function authFailure(error) {
  const r = error?.response;
  if (!r) return null;
  const detail = typeof r.data?.detail === 'string' ? r.data.detail : '';
  const header = String(r.headers?.['x-jn-auth'] || '').toLowerCase();
  if (r.status === 401 && (detail === 'account_required' || detail === 'invalid_account' || header === 'account')) {
    return { kind: 'account' };
  }
  if (r.status === 401 && detail === 'pin_required') return { kind: 'pin_required' };
  if (r.status === 401 && detail === 'wrong_pin') {
    const n = Number(r.data?.tries_left);
    return { kind: 'wrong_pin', triesLeft: Number.isFinite(n) ? n : null };
  }
  if (r.status === 429 && detail === 'pin_cooldown') {
    const s = parseInt(r.headers?.['retry-after'], 10);
    return { kind: 'pin_cooldown', retryAfter: Number.isFinite(s) && s > 0 ? s : 30 };
  }
  if (r.status === 401) return { kind: 'login' };
  return null;
}

// Broadcast a global event so the app can show the right overlay: the account
// picker for `account_required`, the install-password sign-in for any other 401.
// PIN answers are the caller's own business (the PIN pad shows them), never an overlay.
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const f = authFailure(error);
    if (f?.kind === 'account') {
      window.dispatchEvent(new CustomEvent('jn:account-required'));
    } else if (f?.kind === 'login') {
      window.dispatchEvent(new CustomEvent('jn:unauthorized'));
    }
    return Promise.reject(error);
  }
);

export default api;
