/* Blinks Bright — application bootstrap & app shell */

import { api } from './api.js';
import { store } from './store.js';
import { router, BUST } from './router.js';
import { initWS, setWSHandler, setGlobalWSHandler } from './ws.js';
import { icon, initials, escapeHtml, modal, avatarHTML, projectFooter } from './ui.js';
import { t, initLang, langToggle, bindLangToggle } from './i18n.js';

/* Role → human label (translated), falling back to the raw role if unmapped. */
function roleLabel(r) {
  const v = t('role.' + r);
  return v === 'role.' + r ? String(r || '').replace('_', ' ') : v;
}

/* ---- notification bell: shows the UNREAD count and holds it until those chats
   are actually read (it does NOT clear on click or page change) ---- */
let bellCount = 0;
function renderBellBadge() {
  const el = document.getElementById('bell-badge');
  if (!el) return;
  if (bellCount > 0) { el.textContent = bellCount > 99 ? '99+' : String(bellCount); el.hidden = false; }
  else el.hidden = true;
}
function setBellCount(n) { bellCount = Math.max(0, n); renderBellBadge(); }
function refreshBell() {  // the authoritative unread count from the server
  api.get('/conversations/counts').then((c) => setBellCount(c.unread || 0)).catch(() => {});
}
function setupBell() {
  const btn = document.getElementById('bell-btn');
  if (btn) btn.onclick = () => router.go('conversations');  // jump to the inbox, do NOT clear
  refreshBell();
  // a new inbound customer message raises it; opening a chat (read) lowers it
  setGlobalWSHandler((ev) => {
    if (ev && ev.type === 'message' && ev.message && ev.message.sender === 'customer') refreshBell();
  });
  window.addEventListener('inbox:read', refreshBell);
}

const NAV = [
  // Hidden for the final-project scope, like the block further down: the sales overview
  // dashboard (the brief asks for no dashboard). Staff land on the first screen below
  // that their role can open (homeRoute) instead.
  //   { route: 'dashboard',     label: t('nav.dashboard'),     icon: 'dashboard' },
  { route: 'conversations', label: t('nav.conversations'), icon: 'chat' },
  { route: 'bookings',      label: t('nav.bookings'),      icon: 'calendar' },
  { route: 'team',          label: t('nav.team'),          icon: 'stethoscope' },
  { route: 'customers',     label: t('nav.customers'),     icon: 'users' },
  { route: 'payments',      label: t('nav.payments'),      icon: 'card' },
  { route: 'treatments',    label: t('nav.treatments'),    icon: 'spark' },
  { route: 'knowledge',     label: t('nav.knowledge'),     icon: 'book' },
  // Hidden for the final-project scope (marketing tools the brief does not ask for).
  // The views and their APIs are untouched; a route missing from NAV falls back to
  // the home screen in router.init, so restoring a line here brings the screen back.
  // The Test console is a developer tool, not something the clinic owner uses.
  //   { route: 'retention',     label: t('nav.retention'),     icon: 'retention' },
  //   { route: 'analytics',     label: t('nav.analytics'),     icon: 'analytics' },
  //   { route: 'chat-analysis', label: t('nav.chatAnalysis'), icon: 'message' },
  //   { route: 'broadcast',     label: t('nav.broadcast'),     icon: 'broadcast' },
  { route: 'settings',      label: t('nav.settings'),      icon: 'settings' },
  //   { route: 'test',          label: t('nav.test'),          icon: 'flask' },
];
const LABELS = Object.fromEntries(NAV.map((n) => [n.route, n.label]));

// Tier-1 system console — a separate shell, not scoped to any one clinic.
const SYSTEM_NAV = [
  { route: 'system-dashboard', label: t('nav.systemDashboard'), icon: 'dashboard' },
  { route: 'system-clinics',   label: t('nav.systemClinics'),   icon: 'building' },
  { route: 'system-users',     label: t('nav.systemUsers'),     icon: 'users' },
];
const SYSTEM_LABELS = Object.fromEntries(SYSTEM_NAV.map((n) => [n.route, n.label]));
const SYSTEM_DEFAULT = 'system-dashboard';

const ALL_ROLES = ['owner', 'super_admin', 'branch_manager', 'sales', 'doctor', 'marketing'];
const NAV_ROLES = {
  dashboard: ALL_ROLES,
  conversations: ['owner', 'super_admin', 'branch_manager', 'sales', 'doctor'],
  bookings: ['owner', 'super_admin', 'branch_manager', 'sales', 'doctor'],
  team: ['owner', 'super_admin', 'branch_manager', 'doctor', 'sales'],
  customers: ['owner', 'super_admin', 'branch_manager', 'sales', 'doctor', 'marketing'],
  payments: ['owner', 'super_admin', 'branch_manager'],
  treatments: ALL_ROLES,
  knowledge: ['owner', 'super_admin', 'branch_manager', 'marketing', 'doctor'],
  retention: ['owner', 'super_admin', 'branch_manager', 'marketing'],
  analytics: ['owner', 'super_admin', 'branch_manager', 'marketing'],
  'chat-analysis': ['owner', 'super_admin', 'branch_manager', 'marketing'],
  broadcast: ['owner', 'super_admin', 'marketing'],
  settings: ['owner', 'super_admin', 'branch_manager'],
  test: ['owner', 'super_admin'],
};
const SEES_ALL_BRANCHES = ['owner', 'super_admin', 'marketing'];
const canSee = (route) => (NAV_ROLES[route] || ALL_ROLES).includes(store.user.role);
// Where a role lands: the first menu entry it can open (every role can open treatments).
const homeRoute = () => (NAV.find((n) => canSee(n.route)) || { route: 'treatments' }).route;

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? t('shell.greetMorning') : h < 18 ? t('shell.greetAfternoon') : t('shell.greetEvening');
}

// Only reload on a mid-session expiry — not on the initial logged-out probe.
window.addEventListener('auth:expired', () => { if (store.user) location.reload(); });
// The active clinic became unavailable mid-session → back to the picker.
window.addEventListener('clinic:required', () => { if (store.user) location.reload(); });

/* ---- per-clinic brand theming -------------------------------------------
   The whole design centralises on the `--primary` token family, so entering a
   clinic re-binds that family to the clinic's `accent` — the workspace (active
   nav, buttons, toggles, tabs, progress, focus rings, brand mark) instantly
   adopts the clinic's colour. The system console and login leave it cleared,
   so they always show the default olive. */
const _THEME_VARS = ['--primary', '--primary-hover', '--primary-soft', '--on-primary'];
function _hexRgb(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec((hex || '').trim());
  if (!m) return null;
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
function _mix(a, b, t) {  // t = weight of a (0..1)
  const c = (i) => Math.round(a[i] * t + b[i] * (1 - t));
  return `rgb(${c(0)}, ${c(1)}, ${c(2)})`;
}
function _luminance([r, g, b]) {  // WCAG relative luminance
  const f = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}
function _contrast(l1, l2) {  // WCAG contrast ratio
  const a = Math.max(l1, l2) + 0.05, b = Math.min(l1, l2) + 0.05;
  return a / b;
}
// These three MUST track tokens.css: --on-primary, --ink and --canvas. They are the
// values the contrast maths below compares against, so a palette change that lands
// here late makes the app pick white-on-pale (or ink-on-dark) for some clinic accents.
const _L_GLASS = _luminance([244, 247, 255]);  // default --on-primary
const _L_INK = _luminance([28, 34, 56]);       // --ink

function applyClinicTheme(accent) {
  const rgb = _hexRgb(accent);
  const root = document.documentElement.style;
  if (!rgb) { clearClinicTheme(); return; }
  const CANVAS = [238, 241, 250];   // --canvas, for a pale tint
  const lp = _luminance(rgb);
  // Readable text on the accent: keep the pale glass tone when it's legible enough
  // (dark / saturated accents), otherwise flip to dark ink (light accents like gold).
  const onPrimary = _contrast(lp, _L_GLASS) >= 3.2 ? '#F4F7FF'
    : (_contrast(lp, _L_INK) >= _contrast(lp, _L_GLASS) ? '#1C2238' : '#F4F7FF');
  root.setProperty('--primary', `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`);
  root.setProperty('--primary-hover', _mix(rgb, [0, 0, 0], 0.84));   // ~16% darker
  root.setProperty('--primary-soft', _mix(rgb, CANVAS, 0.18));        // pale accent tint
  root.setProperty('--on-primary', onPrimary);
}
function clearClinicTheme() {
  const root = document.documentElement.style;
  _THEME_VARS.forEach((v) => root.removeProperty(v));
}

async function boot() {
  const app = document.getElementById('app');
  initLang();          // reflect the active language on <html lang>
  clearClinicTheme();  // default olive until a clinic workspace opts in
  let me = null;
  try { me = await api.get('/auth/me'); } catch (e) { /* not authenticated */ }

  if (!me) {
    const mod = await import(`/js/views/login.js?v=${BUST}`);
    app.innerHTML = '';
    mod.default(app);
    return;
  }

  store.user = me.user;
  store.canManageClinics = !!me.can_manage_clinics;
  store.tier = me.tier || (me.user.role === 'super_admin' ? 'system' : 'clinic');

  // logged in but no clinic chosen → route by tier
  if (!me.active_clinic) {
    // Tier 1 (system admin) → the global console, no clinic needed
    if (store.tier === 'system') { renderSystemShell(app); return; }

    // Tier 2 → step into their clinic. With exactly one, skip the picker.
    let picked = null;
    try {
      const data = await api.get('/clinics');
      if (data.clinics.length === 1) {
        await api.post(`/clinics/${data.clinics[0].id}/enter`);
        picked = data.clinics[0];
      }
    } catch (e) { /* fall through to the picker */ }

    if (!picked) {
      const mod = await import(`/js/views/clinics.js?v=${BUST}`);
      app.innerHTML = '';
      mod.default(app);
      return;
    }
    store.clinic = picked;
  } else {
    store.clinic = me.active_clinic;
  }

  try { store.branches = await api.get('/branches'); } catch (e) { store.branches = []; }
  renderShell(app);
}

/* ----------------------- Tier-1 system console shell ----------------------- */
function renderSystemShell(app) {
  const u = store.user;
  clearClinicTheme();  // the platform console always shows the default olive brand
  app.innerHTML = `
  <div class="app-shell">
    <aside class="sidebar sidebar-system">
      <div class="sidebar-brand sidebar-brand-static">
        <div class="logo-mark logo-mark-system"><img src="/assets/images/logo_b.png?v=5" alt="Blinks Bright"></div>
        <div class="brand-text">
          <div class="brand-name truncate">Blinks Bright</div>
          <div class="brand-sub">${t('shell.systemConsole')}</div>
        </div>
      </div>
      <nav class="sidebar-nav">
        ${SYSTEM_NAV.map((n) => `
          <button class="nav-item" data-route="${n.route}">
            ${icon(n.icon)}<span>${n.label}</span>
          </button>`).join('')}
      </nav>
      <div class="sidebar-foot">
        <button class="user-chip" id="user-chip" title="${t('shell.account')}">
          ${avatarHTML(u.name, u.avatar, 'sm')}
          <div class="meta">
            <div class="name truncate">${escapeHtml(u.name)}</div>
            <div class="role">${t('shell.sysadmin')}</div>
          </div>
          <span class="uc-caret">${icon('dots', 18)}</span>
        </button>
      </div>
    </aside>
    <div class="main">
      <header class="topbar">
        <div class="greeting">
          <h2 id="tb-title">${t('nav.systemDashboard')}</h2>
          <p id="tb-sub">${greeting()}, ${escapeHtml(u.name.split(' ')[0])} &middot; ${t('shell.managingAll')}</p>
        </div>
        <div class="topbar-actions">
          ${langToggle()}
          <span class="badge badge-olive">${icon('lock', 13)} ${t('shell.platform')}</span>
          <div class="brand-lockup" title="Blinks Bright Beauty Clinic">
            <img class="wordmark" src="/assets/images/logo_full_trim.png?v=1" alt="Blinks Bright Beauty Clinic">
          </div>
        </div>
      </header>
      <main id="view"></main>
      ${projectFooter()}
    </div>
  </div>`;

  app.querySelectorAll('.nav-item').forEach((btn) => {
    btn.onclick = () => router.go(btn.dataset.route);
  });
  app.querySelector('#user-chip').onclick = openSystemMenu;
  bindLangToggle(app);

  router.init((route, params) => {
    if (!SYSTEM_LABELS[route]) route = SYSTEM_DEFAULT;
    app.querySelectorAll('.nav-item').forEach((b) =>
      b.classList.toggle('active', b.dataset.route === route));
    document.getElementById('tb-title').textContent = SYSTEM_LABELS[route] || t('nav.systemDashboard');
    setWSHandler(null);
    router.render(route, params, document.getElementById('view'));
  });
}

function openSystemMenu() {
  const u = store.user;
  modal({
    title: u.name,
    body: `
      <div class="kv"><span class="k">${t('menu.role')}</span><span class="v">${t('shell.sysadmin')}</span></div>
      <div class="kv"><span class="k">${t('menu.email')}</span><span class="v">${escapeHtml(u.email)}</span></div>
      <div class="kv"><span class="k">${t('menu.scope')}</span><span class="v">${t('menu.allClinics')}</span></div>`,
    actions: [
      { label: t('shell.logout'), class: 'btn-danger', onClick: doLogout },
      { label: t('common.close'), class: 'btn-ghost' },
    ],
  });
}

function renderShell(app) {
  const u = store.user;
  const c = store.clinic;
  applyClinicTheme(c.accent);  // re-skin the workspace in this clinic's brand colour
  const accent = c.accent || 'var(--primary)';
  const logoInner = c.logo
    ? `<img src="${escapeHtml(c.logo)}" alt="">`
    : escapeHtml(initials(c.name));
  app.innerHTML = `
  <div class="app-shell">
    <aside class="sidebar">
      <button class="sidebar-brand" id="brand-btn" title="${t('shell.switchClinic')}">
        <div class="logo-mark" style="background:${escapeHtml(accent)}">${logoInner}</div>
        <div class="brand-text">
          <div class="brand-name truncate">${escapeHtml(c.name)}</div>
          <div class="brand-sub">${t('shell.switchClinic')}</div>
        </div>
        <span class="brand-switch">${icon('refresh', 14)}</span>
      </button>
      <nav class="sidebar-nav">
        ${NAV.filter((n) => canSee(n.route)).map((n) => `
          <button class="nav-item" data-route="${n.route}">
            ${icon(n.icon)}<span>${n.label}</span>
          </button>`).join('')}
      </nav>
      <div class="sidebar-foot">
        <button class="user-chip" id="user-chip" title="${t('shell.account')}">
          ${avatarHTML(u.name, u.avatar, 'sm')}
          <div class="meta">
            <div class="name truncate">${escapeHtml(u.name)}</div>
            <div class="role">${escapeHtml(roleLabel(u.role))}</div>
          </div>
          <span class="uc-caret">${icon('dots', 18)}</span>
        </button>
      </div>
    </aside>
    <div class="main">
      <header class="topbar">
        <div class="greeting">
          <h2 id="tb-title">${LABELS[homeRoute()]}</h2>
          <p id="tb-sub">${greeting()}, ${escapeHtml(u.name.split(' ')[0])} &middot; ${escapeHtml(c.name)}</p>
        </div>
        <div class="topbar-actions">
          ${langToggle()}
          <div class="filter-pill">
            ${icon('building', 15)}
            <select id="branch-select" style="border:none;background:none;font-weight:500;outline:none;cursor:pointer">
            </select>
          </div>
          <button class="btn-icon btn-ghost bell-btn" id="bell-btn" title="${t('shell.notifications')}">${icon('bell')}<span class="bell-badge" id="bell-badge" hidden></span></button>
          <div class="brand-lockup" title="Blinks Bright Beauty Clinic">
            <img class="wordmark" src="/assets/images/logo_full_trim.png?v=1" alt="Blinks Bright Beauty Clinic">
          </div>
        </div>
      </header>
      <main id="view"></main>
      ${projectFooter()}
    </div>
  </div>`;

  const sel = app.querySelector('#branch-select');
  if (SEES_ALL_BRANCHES.includes(u.role)) {
    sel.innerHTML = `<option value="all">${t('menu.allBranches')}</option>` +
      store.branches.map((b) => `<option value="${b.id}">${escapeHtml(b.name)}</option>`).join('');
    sel.value = store.branchId;
    sel.onchange = () => { store.set('branchId', sel.value); router.resolve(); };
  } else {
    // branch-scoped roles are locked to their own branch
    if (u.branch_id) store.branchId = String(u.branch_id);
    sel.innerHTML = `<option>${escapeHtml(u.branch_name || t('shell.myBranch'))}</option>`;
    sel.disabled = true;
  }

  app.querySelectorAll('.nav-item').forEach((btn) => {
    btn.onclick = () => router.go(btn.dataset.route);
  });
  app.querySelector('#user-chip').onclick = openUserMenu;
  app.querySelector('#brand-btn').onclick = switchClinic;
  bindLangToggle(app);

  initWS();
  setupBell();

  router.init((route, params) => {
    if (!LABELS[route] || !canSee(route)) route = homeRoute();
    refreshBell();  // re-sync the unread count on navigation (e.g. after reading chats)
    app.querySelectorAll('.nav-item').forEach((b) =>
      b.classList.toggle('active', b.dataset.route === route));
    document.getElementById('tb-title').textContent = LABELS[route];
    setWSHandler(null);  // detach the previous view's realtime handler
    router.render(route, params, document.getElementById('view'));
  });
}

async function switchClinic() {
  try { await api.post('/clinics/leave'); } catch (e) { /* ignore */ }
  location.reload();
}

function openUserMenu() {
  const u = store.user;
  const c = store.clinic || {};
  modal({
    title: u.name,
    body: `
      <div class="kv"><span class="k">${t('menu.role')}</span><span class="v cap">${escapeHtml(roleLabel(u.role))}</span></div>
      <div class="kv"><span class="k">${t('menu.title')}</span><span class="v">${escapeHtml(u.title || '—')}</span></div>
      <div class="kv"><span class="k">${t('menu.email')}</span><span class="v">${escapeHtml(u.email)}</span></div>
      <div class="kv"><span class="k">${t('menu.clinic')}</span><span class="v">${escapeHtml(c.name || '—')}</span></div>
      <div class="kv"><span class="k">${t('menu.branch')}</span><span class="v">${escapeHtml(u.branch_name || t('menu.allBranches'))}</span></div>`,
    actions: [
      { label: t('shell.logout'), class: 'btn-danger', onClick: doLogout },
      { label: t('shell.switchClinic'), class: 'btn-ghost', onClick: switchClinic },
      { label: t('common.close'), class: 'btn-ghost' },
    ],
  });
}

async function doLogout() {
  try { await api.post('/auth/logout'); } catch (e) { /* ignore */ }
  location.reload();
}

boot();
