/* Blinks Bright — hash-based SPA router with lazy-loaded views */

import { emptyState } from './ui.js';
import { t } from './i18n.js';

const DEFAULT = 'dashboard';
const cache = {};
export const BUST = Date.now();  // per-load cache-bust so view edits always appear (used by app.js too)

export const router = {
  _onChange: null,

  init(onChange) {
    this._onChange = onChange;
    window.addEventListener('hashchange', () => this.resolve());
    this.resolve();
  },

  parse() {
    const raw = location.hash.replace(/^#\/?/, '');
    const parts = raw.split('/').filter(Boolean);
    return { route: parts[0] || DEFAULT, params: parts.slice(1) };
  },

  go(path) {
    const next = '#/' + String(path).replace(/^#?\/?/, '');
    if (location.hash === next) this.resolve();
    else location.hash = next;
  },

  async resolve() {
    const { route, params } = this.parse();
    if (this._onChange) this._onChange(route, params);
  },

  /* Render a view module into `mount`. Views live at /js/views/<route>.js
     and export a default async function (mount, params). Missing modules
     fall back to a tasteful placeholder. */
  async render(route, params, mount) {
    mount.innerHTML = '<div class="loading-block"><div class="spinner"></div></div>';
    try {
      let mod = cache[route];
      if (!mod) {
        mod = await import(`/js/views/${route}.js?v=${BUST}`);
        cache[route] = mod;
      }
      const fn = mod.default || mod.render;
      if (typeof fn !== 'function') throw new Error('no view export');
      mount.innerHTML = '';
      await fn(mount, params);
    } catch (err) {
      console.warn('view load failed:', route, err);
      mount.innerHTML = `<div class="view"><div class="card card-pad rise">${
        emptyState('spark', t('common.viewFailTitle'), t('common.viewFailSub'))
      }</div></div>`;
    }
  },
};
