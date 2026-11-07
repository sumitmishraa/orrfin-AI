// Browser API client. Cookies carry the session; mutating requests also send the CSRF token.
let csrf = '';
export const setCsrf = (token: string) => { csrf = token; };

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) { super(message); this.status = status; }
}

type Init = { method?: string; body?: unknown; form?: FormData; headers?: Record<string, string> };

async function request<T>(path: string, init: Init, extra: Record<string, string> = {}): Promise<T> {
  const method = init.method || (init.body !== undefined || init.form ? 'POST' : 'GET');
  const headers: Record<string, string> = { ...extra, ...(init.headers || {}) };
  if (method !== 'GET' && csrf) headers['X-Orrfin-CSRF'] = csrf;
  let body: BodyInit | undefined;
  if (init.form) body = init.form;
  else if (init.body !== undefined) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(init.body); }
  const response = await fetch(path, { method, headers, body, credentials: 'same-origin' });
  if (!response.ok) {
    let message = `Request failed (${response.status}).`;
    try {
      const data = await response.json();
      if (typeof data.detail === 'string') message = data.detail;
      else if (Array.isArray(data.detail)) message = data.detail.map((item: any) => `${(item.loc || []).slice(1).join(' ')}: ${item.msg}`).join('; ');
    } catch { /* Non-JSON error body: keep the generic message. */ }
    throw new ApiError(message, response.status);
  }
  const type = response.headers.get('content-type') || '';
  return (type.includes('application/json') ? response.json() : response.text()) as Promise<T>;
}

export function api<T = any>(path: string, init: Init = {}): Promise<T> {
  return request<T>(path, init);
}

export function portalApi<T = any>(path: string, token: string, init: Init = {}): Promise<T> {
  return request<T>(path, init, { 'X-Portal-Token': token });
}

const rupees = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 });
export const inr = (value: string | number | null | undefined) => (value === null || value === undefined || value === '' ? '-' : rupees.format(Number(value)));
export const compactInr = (value: string | number) => {
  const n = Number(value);
  if (n >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`;
  if (n >= 1e5) return `₹${(n / 1e5).toFixed(2)} L`;
  return rupees.format(n);
};
export const day = (value: string | null | undefined) => (value ? new Date(value).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }) : '-');
export const qty = (value: string | number | null | undefined) => (value === null || value === undefined ? '-' : Number(value).toLocaleString('en-IN', { maximumFractionDigits: 3 }));
