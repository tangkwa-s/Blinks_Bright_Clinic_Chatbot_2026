/* Blinks Bright — UI helpers: icons, toasts, modals, formatters */

import { LANG, t } from './i18n.js';
import { store } from './store.js';

const ICONS = {
  dashboard: '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
  chat: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
  calendar: '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
  users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
  card: '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/>',
  book: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
  retention: '<path d="M21 2v6h-6"/><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M3 22v-6h6"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/>',
  analytics: '<path d="M3 3v18h18"/><path d="M8 17v-5M13 17V8M18 17v-9"/>',
  broadcast: '<path d="m3 11 15-6v14L3 13z"/><path d="M3 11v2a3 3 0 0 0 3 3l1.5 4"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5V21a2 2 0 0 1-4 0v-.1A1.6 1.6 0 0 0 9 19.4a1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H3a2 2 0 0 1 0-4h.1A1.6 1.6 0 0 0 4.6 9a1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1H21a2 2 0 0 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z"/>',
  flask: '<path d="M9 3h6M10 3v7L4.5 19A1.5 1.5 0 0 0 6 21h12a1.5 1.5 0 0 0 1.5-2L14 10V3"/><path d="M7 15h10"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
  bell: '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.9 1.9 0 0 0 3.4 0"/>',
  'chevron-down': '<path d="m6 9 6 6 6-6"/>',
  'chevron-right': '<path d="m9 18 6-6-6-6"/>',
  'chevron-left': '<path d="m15 18-6-6 6-6"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  close: '<path d="M18 6 6 18M6 6l12 12"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  'check-circle': '<circle cx="12" cy="12" r="9"/><path d="m8.5 12 2.5 2.5 4.5-5"/>',
  send: '<path d="M22 2 11 13M22 2l-7 20-4-9-9-4z"/>',
  filter: '<path d="M22 3H2l8 9.5V19l4 2v-8.5z"/>',
  dots: '<circle cx="12" cy="5" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="12" cy="19" r="1.4"/>',
  edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
  trash: '<path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/>',
  logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5M21 12H9"/>',
  building: '<rect x="4" y="2" width="16" height="20" rx="2"/><path d="M9 22v-4h6v4M9 6h.5M14.5 6h.5M9 10h.5M14.5 10h.5M9 14h.5M14.5 14h.5"/>',
  phone: '<path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8.1 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2z"/>',
  mail: '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-10 6L2 7"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  star: '<path d="m12 2 3 6.3 6.9 1-5 4.9 1.2 6.8L12 18l-6.1 3 1.2-6.8-5-4.9 6.9-1z"/>',
  ai: '<path d="m12 3 2 5.5L19.5 11 14 13l-2 5.5L10 13 4.5 11 10 8.5z"/><path d="m19 14 .9 2.3L22 17l-2.1.7L19 20l-.9-2.3L16 17l2.1-.7z"/>',
  alert: '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 16v-4M12 8h.01"/>',
  eye: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/>',
  eyeClosed: '<path d="M2 10s3.5 5 10 5 10-5 10-5"/><path d="M4.5 13.2 3 15.5M9 14.7 8.3 17.3M15 14.7l.7 2.6M19.5 13.2 21 15.5"/>',
  image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.6"/><path d="m21 15-4.5-4.5L5 22"/>',
  stethoscope: '<path d="M11 2v2M5 2v2"/><path d="M5 4H4a2 2 0 0 0-2 2v3a6 6 0 0 0 12 0V6a2 2 0 0 0-2-2h-1"/><path d="M8 15a6 6 0 0 0 12 0v-3"/><circle cx="20" cy="10" r="2"/>',
  external: '<path d="M15 3h6v6M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
  lock: '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
  copy: '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21v-1a6 6 0 0 1 6-6h4a6 6 0 0 1 6 6v1"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a15 15 0 0 1 0 18 15 15 0 0 1 0-18z"/>',
  'trending-up': '<path d="m3 17 6-6 4 4 8-8"/><path d="M17 7h4v4"/>',
  target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.4"/>',
  gift: '<rect x="3" y="8" width="18" height="4" rx="1"/><path d="M12 8v13M5 12v9h14v-9"/><path d="M12 8S11 3 8 3a2.5 2.5 0 0 0 0 5M12 8s1-5 4-5a2.5 2.5 0 0 1 0 5"/>',
  heart: '<path d="M20.8 5.6a5 5 0 0 0-7.1 0L12 7.3l-1.7-1.7a5 5 0 1 0-7.1 7.1L12 21.5l8.8-8.8a5 5 0 0 0 0-7.1z"/>',
  zap: '<path d="M13 2 3 14h8l-1 8 10-12h-8z"/>',
  'arrow-up': '<path d="M12 19V5M5 12l7-7 7 7"/>',
  'arrow-down': '<path d="M12 5v14M19 12l-7 7-7-7"/>',
  'arrow-right': '<path d="M5 12h14M12 5l7 7-7 7"/>',
  refresh: '<path d="M3 12a9 9 0 0 1 9-9 9 9 0 0 1 6.7 3L21 8M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9 9 0 0 1-6.7-3L3 16M3 21v-5h5"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5M12 15V3"/>',
  play: '<path d="M6 4v16l14-8z"/>',
  pause: '<rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/>',
  inbox: '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.5 5.1 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.5-6.9A2 2 0 0 0 16.8 4H7.2a2 2 0 0 0-1.7 1.1z"/>',
  file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M9 13h6M9 17h6"/>',
  dollar: '<path d="M12 1v22M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>',
  package: '<path d="m12 2 9 5v10l-9 5-9-5V7z"/><path d="m3 7 9 5 9-5M12 12v10"/>',
  sliders: '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/>',
  message: '<path d="M21 11.5a8.5 8.5 0 0 1-12.5 7.5L3 21l2-5.5A8.5 8.5 0 1 1 21 11.5z"/>',
  'calendar-check': '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18M8.5 16l2.5 2.5 4.5-5"/>',
  spark: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M18.4 5.6l-2.8 2.8M8.4 15.6l-2.8 2.8"/>',
  dot: '<circle cx="12" cy="12" r="3"/>',
};

export function icon(name, size = 18) {
  const p = ICONS[name] || ICONS.dot;
  return `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${p}</svg>`;
}

/* ---------- project notice + authors (login, picker, every workspace page) ---------- */
export function projectFooter() {
  return `<footer class="project-foot"><p>${t('common.projectNote')}</p><p>${t('common.projectCredit')}</p></footer>`;
}

/* ---------- password eye ----------
   Adds a show/hide button to every password input under `root`: eye closed =
   hidden (the default), eye open = shown. Safe to call twice on the same root. */
export function bindPasswordEyes(root) {
  root.querySelectorAll('input[type="password"]').forEach((input) => {
    if (input.closest('.pw-wrap')) return;
    const wrap = document.createElement('span');
    wrap.className = 'pw-wrap';
    input.replaceWith(wrap);
    wrap.appendChild(input);
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'pw-eye';
    const paint = () => {
      const shown = input.type === 'text';
      btn.innerHTML = icon(shown ? 'eye' : 'eyeClosed', 18);
      btn.setAttribute('aria-label', t(shown ? 'common.hidePassword' : 'common.showPassword'));
      btn.setAttribute('aria-pressed', String(shown));
    };
    btn.onclick = () => { input.type = input.type === 'password' ? 'text' : 'password'; paint(); input.focus(); };
    paint();
    wrap.appendChild(btn);
  });
}

/* ---------- formatters ---------- */
export function money(n, symbol = true) {
  const v = Math.round(Number(n) || 0).toLocaleString('en-US');
  return symbol ? '฿' + v : v;
}
export function num(n) { return (Number(n) || 0).toLocaleString('en-US'); }
export function pct(n, dp = 1) { return (Number(n) || 0).toFixed(dp) + '%'; }
export function escapeHtml(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
export function initials(name) {
  return String(name || '?').trim().split(/\s+/).slice(0, 2).map((w) => w[0] || '').join('').toUpperCase();
}

/* Avatar markup — a profile image when present (e.g. an uploaded photo), with the
   initials underneath as a fallback if the image is missing or fails to load. */
export function avatarHTML(name, url, extra = '') {
  const cls = ('avatar ' + extra).trim();
  const ini = escapeHtml(initials(name));
  if (url) {
    return `<div class="${cls} has-img">${ini}<img src="${escapeHtml(url)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()"></div>`;
  }
  return `<div class="${cls}">${ini}</div>`;
}

/* A profile-photo upload field for the staff / user modals. Render `avatarField`
   in the modal body, then call `bindAvatarPicker` to preview the chosen file and
   stage it. The returned state ({file, clear}) tells the save handler whether to
   POST a new image or clear the existing one. */
export function avatarField(name, url, id = 'av', label = t('ui.profilePhoto')) {
  return `<div class="field"><label>${label} <span class="muted">${t('common.optional')}</span></label>
    <div class="avatar-pick">
      <label class="avatar-pick-drop" title="${t('ui.uploadPhotoTitle')}">
        <input type="file" accept="image/png,image/jpeg,image/webp" hidden id="${id}-file">
        <span class="avatar-pick-preview" id="${id}-preview">${avatarHTML(name, url, 'lg')}</span>
        <span class="avatar-pick-cam">${icon('image', 13)}</span>
      </label>
      <div class="avatar-pick-actions">
        <button type="button" class="btn btn-ghost btn-sm" id="${id}-pick">${icon('image', 14)}<span>${t('ui.uploadPhoto')}</span></button>
        <button type="button" class="btn btn-ghost btn-sm${url ? '' : ' hidden'}" id="${id}-clear">${t('common.remove')}</button>
        <span class="muted text-sm">${t('ui.photoHint')}</span>
      </div>
    </div></div>`;
}

export function bindAvatarPicker(root, id, name) {
  const file = root.querySelector(`#${id}-file`);
  const preview = root.querySelector(`#${id}-preview`);
  const pick = root.querySelector(`#${id}-pick`);
  const clear = root.querySelector(`#${id}-clear`);
  const state = { file: null, clear: false, name };
  if (pick) pick.onclick = () => file.click();
  file.onchange = () => {
    const f = file.files[0];
    if (!f) return;
    state.file = f; state.clear = false;
    if (clear) clear.classList.remove('hidden');
    const r = new FileReader();
    r.onload = () => { preview.innerHTML = avatarHTML(state.name, r.result, 'lg'); };
    r.readAsDataURL(f);
  };
  if (clear) clear.onclick = () => {
    state.file = null; state.clear = true; file.value = '';
    clear.classList.add('hidden');
    preview.innerHTML = avatarHTML(state.name, '', 'lg');
  };
  return state;
}

/* Channel logo — a gradient app-icon chip for the web chat, in the clinic's own
   olive brand. Each gradient gets a unique id so multiple chips on one screen
   never share (and clobber) a fill. */
let _chGid = 0;
const CHANNEL_LOGOS = {
  web: (s) => {
    const g = 'chw' + (++_chGid);
    return `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" aria-hidden="true">`
      + `<defs><linearGradient id="${g}" x1="4" y1="3" x2="20" y2="21" gradientUnits="userSpaceOnUse">`
      + `<stop stop-color="#646E50"/><stop offset="1" stop-color="#3E442F"/></linearGradient></defs>`
      + `<rect width="24" height="24" rx="6" fill="url(#${g})"/>`
      + `<g fill="none" stroke="#F3EFE4" stroke-width="1.35" stroke-linecap="round" stroke-linejoin="round">`
      + `<circle cx="12" cy="12" r="5"/><path d="M7 12h10"/>`
      + `<path d="M12 7c1.65 1.4 2.5 3.05 2.5 5s-.85 3.6-2.5 5c-1.65-1.4-2.5-3.05-2.5-5s.85-3.6 2.5-5z"/></g></svg>`;
  },
};
export function channelLogo(channel, size = 16) {
  const fn = CHANNEL_LOGOS[channel] || CHANNEL_LOGOS.web;
  return `<span class="ch-logo" title="${escapeHtml(channel || 'web')}">${fn(size)}</span>`;
}
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const TZ = 'Asia/Bangkok';  // the clinic timezone — all audit times render here (+07:00)

// Backend audit timestamps (created_at, last_message_at, paid_at, …) are NAIVE
// UTC ISO strings with no timezone designator. Left to `new Date()` they'd be
// parsed as the browser's local time and shown 7h off. Tag them as UTC so the
// formatters below can convert them to Asia/Bangkok regardless of browser TZ.
function _d(v) {
  if (v == null || v === '') return null;
  if (v instanceof Date) return isNaN(v) ? null : v;
  let s = String(v);
  if (/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(s) && !/([zZ]|[+-]\d{2}:?\d{2})$/.test(s)) {
    s = s.replace(' ', 'T') + 'Z';  // naive datetime → treat as UTC
  }
  const d = new Date(s);
  return isNaN(d) ? null : d;
}
// Asia/Bangkok wall-clock parts for an absolute instant.
function _bkk(d) {
  const o = {};
  for (const p of new Intl.DateTimeFormat('en-US', {
    timeZone: TZ, year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(d)) o[p.type] = p.value;
  return o;
}
/* Thai reads years in the Buddhist Era; English keeps the Common Era. Every year the
   UI prints goes through here so the two never appear side by side — the bookings
   agenda sits directly under the date picker, and 2569 above 2026 reads as a bug. */
export function displayYear(y) { return LANG === 'th' ? Number(y) + 543 : Number(y); }

export function dateShort(v) { const d = _d(v); if (!d) return '—'; const p = _bkk(d); return `${p.day} ${p.month}`; }
export function dateLong(v) { const d = _d(v); if (!d) return '—'; const p = _bkk(d); return `${p.day} ${p.month} ${displayYear(p.year)}`; }
export function dateTime(v) { const d = _d(v); if (!d) return '—'; const p = _bkk(d); return `${p.day} ${p.month}, ${p.hour}:${p.minute}`; }
export function timeOf(v) { const d = _d(v); if (!d) return '—'; const p = _bkk(d); return `${p.hour}:${p.minute}`; }
export function timeAgo(v) {
  const d = _d(v); if (!d) return '—';
  const s = (Date.now() - d.getTime()) / 1000;
  if (s < 60) return t('time.justNow');
  if (s < 3600) return t('time.mAgo', { n: Math.floor(s / 60) });
  if (s < 86400) return t('time.hAgo', { n: Math.floor(s / 3600) });
  if (s < 604800) return t('time.dAgo', { n: Math.floor(s / 86400) });
  return dateShort(d);
}

// Raw wall-clock formatters — for values that are ALREADY local wall-clock and
// must NOT be tz-shifted: booking slot times (`slot_at`) the team/AI picked are
// stored naive (e.g. a 14:00 appointment is the literal 14:00, not UTC).
const _dRaw = (v) => { const d = v instanceof Date ? v : new Date(v); return isNaN(d) ? null : d; };
const _p2 = (n) => String(n).padStart(2, '0');
export function dateLongRaw(v) { const d = _dRaw(v); return d ? `${d.getDate()} ${MONTHS[d.getMonth()]} ${displayYear(d.getFullYear())}` : '—'; }
export function timeOfRaw(v) { const d = _dRaw(v); return d ? `${_p2(d.getHours())}:${_p2(d.getMinutes())}` : '—'; }
/* Short weekday, translated — the month names above are English-only by design, but a
   date RANGE reads as a plan for the week ("จ. 4 ส.ค. - อา. 10 ส.ค."), so the day has
   to be in the operator's language for the span to be legible at a glance. */
export function dayNameRaw(v) { const d = _dRaw(v); return d ? t(`time.dow${d.getDay()}`) : '—'; }

/* Normalise the em / en dashes the AI still emits (it ignores the prompt's
   "no em dash" rule) to a plain spaced hyphen, so replies read cleanly. */
export function cleanDashes(s) {
  return String(s == null ? '' : s).replace(/\s*[—–]\s*/g, ' - ');
}

/* ---------- markdown (safe subset for AI replies: bold/italic/lists/tables) ---------- */
function _mdInline(s) {
  let t = escapeHtml(s);                                                   // escape first — output stays XSS-safe
  t = t.replace(/`([^`\n]+)`/g, (_m, c) => `<code class="md-code">${c}</code>`);
  t = t.replace(/\*\*([^\n]+?)\*\*/g, '<strong>$1</strong>');
  t = t.replace(/__([^\n_]+?)__/g, '<strong>$1</strong>');
  t = t.replace(/(^|[^*])\*([^*\n]+?)\*(?!\*)/g, '$1<em>$2</em>');
  t = t.replace(/(^|[^\w])_([^_\n]+?)_(?=[^\w]|$)/g, '$1<em>$2</em>');
  t = t.replace(/~~([^~\n]+?)~~/g, '<del>$1</del>');
  t = t.replace(/\[([^\]\n]+)\]\(([^)\s]+)\)/g, (_m, txt, url) =>
    `<a href="${/^(https?:|mailto:|tel:)/i.test(url) ? url : '#'}" target="_blank" rel="noopener noreferrer">${txt}</a>`);
  return t;
}
const _mdRow = (line) => line.replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|').map((c) => c.trim());
const _mdSep = (s) => s.includes('-') && /^\s*\|?(\s*:?-{1,}:?\s*\|)+\s*:?-{1,}:?\s*\|?\s*$/.test(s);

export function renderMarkdown(src) {
  const lines = cleanDashes(src).replace(/\r\n?/g, '\n').split('\n');
  const n = lines.length, out = [];
  const special = (k) => /^\s*([-*+]\s+|\d+\.\s+|#{1,6}\s+|>\s?)/.test(lines[k])
    || /^\s*([-*_])\1{2,}\s*$/.test(lines[k])
    || (lines[k].includes('|') && k + 1 < n && _mdSep(lines[k + 1]));
  let i = 0;
  while (i < n) {
    const line = lines[i];
    if (/^\s*$/.test(line)) { i++; continue; }
    if (line.includes('|') && i + 1 < n && _mdSep(lines[i + 1])) {          // GFM table
      const head = _mdRow(line); i += 2; const body = [];
      while (i < n && lines[i].includes('|') && !/^\s*$/.test(lines[i])) { body.push(_mdRow(lines[i])); i++; }
      out.push(`<div class="md-tablewrap"><table class="md-table"><thead><tr>${
        head.map((c) => `<th>${_mdInline(c)}</th>`).join('')}</tr></thead><tbody>${
        body.map((r) => `<tr>${head.map((_c, ci) => `<td>${_mdInline(r[ci] || '')}</td>`).join('')}</tr>`).join('')
      }</tbody></table></div>`);
      continue;
    }
    if (/^\s*[-*+]\s+/.test(line)) {                                        // unordered list
      const items = [];
      while (i < n && /^\s*[-*+]\s+/.test(lines[i])) { items.push(lines[i].replace(/^\s*[-*+]\s+/, '')); i++; }
      out.push(`<ul class="md-list">${items.map((it) => `<li>${_mdInline(it)}</li>`).join('')}</ul>`);
      continue;
    }
    if (/^\s*\d+\.\s+/.test(line)) {                                        // ordered list
      const items = [];
      while (i < n && /^\s*\d+\.\s+/.test(lines[i])) { items.push(lines[i].replace(/^\s*\d+\.\s+/, '')); i++; }
      out.push(`<ol class="md-list">${items.map((it) => `<li>${_mdInline(it)}</li>`).join('')}</ol>`);
      continue;
    }
    const h = line.match(/^\s*(#{1,6})\s+(.*)$/);
    if (h) { out.push(`<div class="md-h md-h${h[1].length}">${_mdInline(h[2])}</div>`); i++; continue; }
    if (/^\s*>\s?/.test(line)) {                                            // blockquote
      const q = [];
      while (i < n && /^\s*>\s?/.test(lines[i])) { q.push(lines[i].replace(/^\s*>\s?/, '')); i++; }
      out.push(`<blockquote class="md-quote">${q.map(_mdInline).join('<br>')}</blockquote>`);
      continue;
    }
    if (/^\s*([-*_])\1{2,}\s*$/.test(line)) { out.push('<hr class="md-hr">'); i++; continue; }
    const para = [];                                                        // paragraph (soft breaks → <br>)
    while (i < n && !/^\s*$/.test(lines[i]) && !special(i)) { para.push(lines[i]); i++; }
    out.push(`<p class="md-p">${para.map(_mdInline).join('<br>')}</p>`);
  }
  return out.join('');
}
export function debounce(fn, ms = 250) {
  let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

/* ---------- payment button (rendered from a message's payment meta) ---------- */
// Drop raw card-checkout URLs from AI text — only messages from before payments moved
// to the QR carry one, and the pay-card already stands in for them.
export function stripPayUrls(text) {
  return String(text == null ? '' : text)
    .replace(/https?:\/\/checkout\.stripe\.com\/\S+/gi, '')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}
export function paymentCard(payment) {
  if (!payment || !payment.url) return '';
  const amt = payment.amount ? money(payment.amount) : '';
  const label = escapeHtml(payment.label || t('pay.label'));
  const pid = escapeHtml(String(payment.payment_id || ''));
  if (payment.paid) {
    return `<div class="pay-card paid" data-payment="${pid}">
      <span class="pay-card-info">
        <span class="pay-card-label">${label}${amt ? ` <b>${amt}</b>` : ''}</span>
        <span class="pay-card-sub">${icon('check', 13)} ${t('pay.paidNote')}</span>
      </span>
      <span class="pay-card-cta">${t('pay.paidCta')} ${icon('check', 15)}</span>
    </div>`;
  }
  const url = /^https?:\/\//i.test(payment.url) ? payment.url : '#';
  // The countdown text is filled in by tickPayCountdowns() on the next 1s tick — the
  // markup ships with the hold deadline in data-hold-until (naive Bangkok wall-clock,
  // same "Raw" convention as slot_at everywhere else in this app) and nothing else, so
  // there's no flash of a stale/wrong remaining time before JS takes over.
  const countdown = payment.hold_expires_at
    ? `<span class="pay-card-countdown" data-hold-until="${escapeHtml(payment.hold_expires_at)}"></span>`
    : '';
  if (countdown) ensurePayCountdownTicking();
  if (payment.kind === 'qr') {
    // bank-transfer QR sent instead of a card link — confirm it on Payments once the slip checks out
    return `<div class="pay-card pay-qr" data-payment="${pid}">
      <span class="pay-card-info">
        <span class="pay-card-label">${label}${amt ? ` <b>${amt}</b>` : ''}</span>
        <span class="pay-card-sub">${icon('image', 13)} ${t('pay.qrSent')}</span>
        ${countdown}
      </span>
      <img class="pay-qr-thumb" src="${escapeHtml(payment.url)}" alt="QR">
    </div>`;
  }
  return `<a class="pay-card" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer"
      data-payment="${pid}">
      <span class="pay-card-info">
        <span class="pay-card-label">${label}${amt ? ` <b>${amt}</b>` : ''}</span>
        <span class="pay-card-sub">${icon('card', 13)} ${t('pay.method')}</span>
        ${countdown}
      </span>
      <span class="pay-card-cta">${t('pay.cta')} ${icon('arrow-right', 15)}</span>
    </a>`;
}

/* Live "holding this slot for X:XX more" text on every unpaid pay-card's countdown span.
   One shared interval for the whole page (started lazily, first call) rather than one
   per card — cards come and go with the message list, a per-card timer would leak. Reads
   data-hold-until fresh each tick, so cards rendered after the interval started are
   picked up automatically; a paid card gets marked and stops updating on its own. */
let _payCountdownTimer = null;
function _tickPayCountdowns() {
  const now = Date.now();
  document.querySelectorAll('.pay-card-countdown[data-hold-until]').forEach((el) => {
    if (el.closest('.pay-card.paid')) { el.textContent = ''; return; }
    const deadline = new Date(el.dataset.holdUntil).getTime();
    const ms = deadline - now;
    if (isNaN(deadline)) { el.textContent = ''; return; }
    if (ms <= 0) {
      el.textContent = t('pay.holdExpired');
      el.classList.add('warn');
      return;
    }
    const totalSec = Math.floor(ms / 1000);
    const mm = String(Math.floor(totalSec / 60)).padStart(2, '0');
    const ss = String(totalSec % 60).padStart(2, '0');
    el.textContent = t('pay.holdCountdown', { mm, ss });
    el.classList.toggle('warn', ms <= 120000);   // last 2 minutes
  });
}
export function ensurePayCountdownTicking() {
  if (_payCountdownTimer) return;
  _tickPayCountdowns();
  _payCountdownTimer = setInterval(_tickPayCountdowns, 1000);
}

/* A slip waiting for staff pauses the hold (services/slips.py); the pay-card still carries
   the old deadline, so stop its countdown — or restart it after a rejected slip. */
export function applySlipState(root, slip) {
  if (!slip || slip.payment_id == null) return;
  root.querySelectorAll(`.pay-card[data-payment="${slip.payment_id}"] .pay-card-countdown`).forEach((el) => {
    el.classList.remove('warn');
    if (slip.state === 'received') {
      el.removeAttribute('data-hold-until');
      el.textContent = t('pay.slipChecking');
    } else if (slip.state === 'rejected' && slip.hold_expires_at) {
      el.dataset.holdUntil = slip.hold_expires_at;
      ensurePayCountdownTicking();
    }
  });
}

/* Flip a live pay-card to its settled state when a {type:'payment'} event lands. */
export function markPayCardPaid(el) {
  if (!el || el.classList.contains('paid')) return;
  el.classList.add('paid');
  el.removeAttribute('href');
  el.style.pointerEvents = 'none';
  const sub = el.querySelector('.pay-card-sub');
  if (sub) sub.innerHTML = `${icon('check', 13)} ${t('pay.paidNote')}`;
  const cta = el.querySelector('.pay-card-cta');
  if (cta) cta.innerHTML = `${t('pay.paidCta')} ${icon('check', 15)}`;
  const countdown = el.querySelector('.pay-card-countdown');
  if (countdown) { countdown.textContent = ''; countdown.classList.remove('warn'); }
}

/* ---------- toast ---------- */
export function toast(message, type = 'info', ms = 3400) {
  const root = document.getElementById('toast-root');
  if (!root) return;
  const ic = { success: 'check-circle', error: 'alert', warn: 'alert', info: 'info' }[type] || 'info';
  const t = document.createElement('div');
  t.className = 'toast ' + (type === 'warn' ? 'warn' : type);
  t.innerHTML = `<span style="color:var(--${type === 'warn' ? 'warning' : type === 'error' ? 'danger' : type === 'success' ? 'success' : 'info'})">${icon(ic, 18)}</span><span>${escapeHtml(message)}</span>`;
  root.appendChild(t);
  setTimeout(() => { t.style.opacity = '0'; t.style.transition = 'opacity .25s'; setTimeout(() => t.remove(), 260); }, ms);
}

/* ---------- modal ---------- */
export function modal({ title = '', body = '', actions = [], wide = false, onClose } = {}) {
  const root = document.getElementById('modal-root');
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  const close = () => { overlay.remove(); document.removeEventListener('keydown', onKey); if (onClose) onClose(); };
  const onKey = (e) => { if (e.key === 'Escape') close(); };

  const m = document.createElement('div');
  m.className = 'modal' + (wide ? ' wide' : '');
  m.innerHTML = `
    <div class="modal-head">
      <h3>${escapeHtml(title)}</h3>
      <button class="btn-icon btn-subtle" data-x>${icon('close', 18)}</button>
    </div>
    <div class="modal-body"></div>
    ${actions.length ? '<div class="modal-foot"></div>' : ''}`;
  const bodyEl = m.querySelector('.modal-body');
  if (typeof body === 'string') bodyEl.innerHTML = body;
  else if (body) bodyEl.appendChild(body);

  const foot = m.querySelector('.modal-foot');
  if (foot) actions.forEach((a) => {
    const b = document.createElement('button');
    b.className = 'btn ' + (a.class || 'btn-ghost');
    b.textContent = a.label;
    b.onclick = () => { const r = a.onClick ? a.onClick({ close, modal: m }) : undefined; if (r !== false && !a.keepOpen) close(); };
    foot.appendChild(b);
  });
  m.querySelector('[data-x]').onclick = close;
  overlay.onclick = (e) => { if (e.target === overlay) close(); };
  document.addEventListener('keydown', onKey);
  overlay.appendChild(m);
  root.appendChild(overlay);
  return { close, el: m };
}

export function confirmDialog({ title = t('common.areYouSure'), message = '', confirmLabel = t('common.confirm'), danger = false } = {}) {
  return new Promise((resolve) => {
    modal({
      title,
      body: `<p style="color:var(--ink-2);white-space:pre-line">${escapeHtml(message)}</p>`,
      onClose: () => resolve(false),
      actions: [
        { label: t('common.cancel'), class: 'btn-ghost', onClick: () => resolve(false) },
        { label: confirmLabel, class: danger ? 'btn-danger' : 'btn-primary', onClick: () => resolve(true) },
      ],
    });
  });
}

/* ---------- misc ---------- */
export function emptyState(iconName, title, sub) {
  return `<div class="empty-state">${icon(iconName, 40)}<div class="es-title">${escapeHtml(title)}</div>${sub ? `<div>${escapeHtml(sub)}</div>` : ''}</div>`;
}
export function loadingBlock() { return '<div class="loading-block"><div class="spinner"></div></div>'; }

/* ---------- branch multi-select (checkbox dropdown, shared by treatments.js
   and broadcast.js) — a <details> so it needs no custom open/close JS; an
   explicit "All branches" checkbox keeps every individual one in sync. ---------- */
export function isEveryBranch(checkedIds) {
  return checkedIds.length === 0 || checkedIds.length === store.branches.length;
}
export function branchSummaryText(checkedIds) {
  return isEveryBranch(checkedIds) ? t('menu.allBranches')
    : checkedIds.map((id) => store.branchName(id)).join(', ');
}
// ``dataAttr`` (e.g. "branch-chk") names both the individual checkboxes' data
// attribute and the "all" checkbox's id (`${dataAttr}-all`).
export function branchCheckboxListHtml(dataAttr, checkedIds) {
  // "All branches" (nothing, or literally every id, passed in) must show every
  // individual box checked too — not just the "all" meta-checkbox — so the two
  // never visually disagree.
  const allChecked = isEveryBranch(checkedIds);
  return `
    <label class="tx-branch-msel-opt tx-branch-msel-all">
      <input type="checkbox" id="${dataAttr}-all"${allChecked ? ' checked' : ''}>
      <span>${t('menu.allBranches')}</span>
    </label>
    ${store.branches.map((b) => `
      <label class="tx-branch-msel-opt">
        <input type="checkbox" data-${dataAttr}="${b.id}"${(allChecked || checkedIds.includes(b.id)) ? ' checked' : ''}>
        <span>${escapeHtml(b.name)}</span>
      </label>`).join('')}`;
}
// Wires a "select all" checkbox (`#${dataAttr}-all`) to check/uncheck every
// individual `[data-${dataAttr}]` box together, and keeps it in sync (checked
// only once every box is) as they are toggled. ``onChange`` fires after either.
// Nothing here is branch-specific — the duplicate-customer merge list uses it too.
export function wireCheckAll(container, dataAttr, onChange) {
  const allBox = container.querySelector(`#${dataAttr}-all`);
  if (!allBox) return;
  const itemBoxes = () => [...container.querySelectorAll(`[data-${dataAttr}]`)];
  allBox.onchange = () => {
    itemBoxes().forEach((b) => { b.checked = allBox.checked; });
    onChange();
  };
  itemBoxes().forEach((b) => {
    b.onchange = () => {
      allBox.checked = itemBoxes().every((x) => x.checked);
      onChange();
    };
  });
}
