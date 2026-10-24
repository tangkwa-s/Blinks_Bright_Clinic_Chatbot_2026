/* Blinks Bright — API client */

import { t } from './i18n.js';

export class ApiError extends Error {
  constructor(status, detail) { super(detail || t('common.requestFailed')); this.status = status; this.detail = detail; }
}

async function request(method, path, body) {
  const opts = { method, headers: {}, credentials: 'include' };
  if (body !== undefined && !(body instanceof FormData)) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  } else if (body instanceof FormData) {
    opts.body = body;
  }
  let res;
  try {
    res = await fetch('/api' + path, opts);
  } catch (e) {
    throw new ApiError(0, t('common.networkError'));
  }
  if (res.status === 401) {
    window.dispatchEvent(new CustomEvent('auth:expired'));
    throw new ApiError(401, t('common.sessionExpired'));
  }
  const ct = res.headers.get('content-type') || '';
  const data = ct.includes('application/json') ? await res.json() : await res.text();
  if (res.status === 409 && data && data.detail === 'no_clinic') {
    window.dispatchEvent(new CustomEvent('clinic:required'));
    throw new ApiError(409, 'no_clinic');
  }
  if (!res.ok) {
    const detail = (data && data.detail) ? data.detail : `Error ${res.status}`;
    throw new ApiError(res.status, typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return data;
}

export const api = {
  get: (p) => request('GET', p),
  post: (p, b) => request('POST', p, b),
  put: (p, b) => request('PUT', p, b),
  patch: (p, b) => request('PATCH', p, b),
  del: (p) => request('DELETE', p),
  url: (p) => '/api' + p,
};
