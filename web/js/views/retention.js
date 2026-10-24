/* Blinks Bright — Retention view (metrics, reminders, automation engine) */

import { api } from '../api.js';
import { store } from '../store.js';
import { icon, money, num, escapeHtml, toast, loadingBlock, emptyState,
         timeAgo, dateShort } from '../ui.js';
import { barList } from '../charts.js';
import { t } from '../i18n.js';

const REMINDER_LABEL = {
  pre_appointment: t('retn.remPreAppointment'), treatment_due: t('retn.remTreatmentDue'),
  followup_d1: t('retn.remFollowupD1'), followup_d7: t('retn.remFollowupD7'),
  followup_d14: t('retn.remFollowupD14'), winback: t('retn.remWinback'), birthday: t('retn.remBirthday'),
  package_expiry: t('retn.remPackageExpiry'), lead_nurture: t('retn.remLeadNurture'),
};

// Each automation rule's Thai label + description, grouped into the two engines.
const AUTO_META = {
  pre_appointment: { icon: 'calendar', label: t('retn.metaPreApptLabel'),
    desc: t('retn.metaPreApptDesc') },
  followup_d1: { icon: 'heart', label: t('retn.metaD1Label'),
    desc: t('retn.metaD1Desc') },
  followup_d7: { icon: 'heart', label: t('retn.metaD7Label'),
    desc: t('retn.metaD7Desc') },
  followup_d14: { icon: 'spark', label: t('retn.metaD14Label'),
    desc: t('retn.metaD14Desc') },
  lead_nurture: { icon: 'chat', label: t('retn.metaLeadLabel'),
    desc: t('retn.metaLeadDesc') },
  treatment_due: { icon: 'refresh', label: t('retn.metaDueLabel'),
    desc: t('retn.metaDueDesc') },
  winback: { icon: 'refresh', label: t('retn.metaWinbackLabel'),
    desc: t('retn.metaWinbackDesc') },
  birthday: { icon: 'star', label: t('retn.metaBirthdayLabel'),
    desc: t('retn.metaBirthdayDesc') },
  package_expiry: { icon: 'clock', label: t('retn.metaPkgLabel'),
    desc: t('retn.metaPkgDesc') },
};
const CATEGORIES = [
  { title: t('retn.catReminders'), icon: 'calendar',
    types: ['pre_appointment', 'followup_d1', 'followup_d7', 'followup_d14', 'lead_nurture'] },
  { title: t('retn.catWinback'), icon: 'refresh',
    types: ['treatment_due', 'winback', 'birthday', 'package_expiry'] },
];

const REMINDER_TYPES = ['pre_appointment', 'treatment_due', 'followup_d1', 'followup_d7',
  'followup_d14', 'winback', 'birthday', 'package_expiry', 'lead_nurture'];
const REMINDER_STATUSES = ['sent', 'scheduled', 'failed'];
const STATUS_LABEL = { sent: () => t('retn.statusSent'), scheduled: () => t('retn.statusPending'),
  failed: () => t('retn.statusFailed') };

function dueFmt(iso) {
  const d = new Date(iso);
  return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' })
    + ' ' + d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
}

function stat(label, value, ic, color) {
  return `<div class="stat-card" style="--ic:${color || 'var(--primary)'}">
    <div class="stat-top"><span class="stat-label">${label}</span>
      <span class="stat-ic">${icon(ic, 16)}</span></div>
    <div class="stat-value">${value}</div></div>`;
}

// Module-level (not reset inside renderRetention) so switching the topbar's
// active branch — which remounts this whole view — never wipes the user's
// tab or reminder filters; only picking a different one does. Defaults:
// Reminders tab, "all" types, "all" statuses, empty search.
let activeTab = 'reminders';
const reminderFilters = { type: 'all', status: 'all', search: '' };

export default async function renderRetention(mount) {
  mount.innerHTML = `<div class="view">
    <div class="view-head">
      <div><h2>${t('retn.title')}</h2>
        <p>${t('retn.subtitle')}</p></div>
      <button class="btn btn-primary" id="run-auto">${icon('zap', 16)}<span>${t('retn.runAutomations')}</span></button>
    </div>
    <div id="ret-metrics">${loadingBlock()}</div>
    <div class="tabs" style="margin-top:6px">
      <button class="tab${activeTab === 'reminders' ? ' active' : ''}" data-tab="reminders">${t('retn.tabReminders')}</button>
      <button class="tab${activeTab === 'automations' ? ' active' : ''}" data-tab="automations">${t('retn.tabAutomations')}</button>
    </div>
    <div id="ret-tab">${loadingBlock()}</div>
  </div>`;

  const params = new URLSearchParams();
  if (store.branchId && store.branchId !== 'all') params.set('branch_id', store.branchId);
  loadMetrics(mount, params);

  showTab(mount, activeTab);
  mount.querySelectorAll('.tab').forEach((t) => {
    t.onclick = () => {
      mount.querySelectorAll('.tab').forEach((x) => x.classList.toggle('active', x === t));
      showTab(mount, t.dataset.tab);
    };
  });

  mount.querySelector('#run-auto').onclick = async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    btn.innerHTML = '<div class="spinner"></div>';
    try {
      const r = await api.post('/retention/run');
      if (r.failed > 0) {
        toast(t('retn.automationsRanFailed',
          { generated: r.generated, sent: r.sent, failed: r.failed }), 'error');
      } else {
        toast(t('retn.automationsRan', { generated: r.generated, sent: r.sent }), 'success');
      }
      loadMetrics(mount, params);
      showTab(mount, activeTab);
    } catch (ex) { toast(ex.detail || t('retn.failed'), 'error'); }
    btn.disabled = false;
    btn.innerHTML = `${icon('zap', 16)}<span>${t('retn.runAutomations')}</span>`;
  };
}

async function loadMetrics(mount, params) {
  let m;
  try { m = await api.get('/retention/metrics?' + params.toString()); }
  catch (e) { return; }
  mount.querySelector('#ret-metrics').innerHTML = `
    <div class="grid grid-5" style="margin-bottom:16px">
      ${stat(t('retn.statRepeatRate'), m.repeat_rate + '%', 'refresh', 'var(--chart-3)')}
      ${stat(t('retn.statInactive'), num(m.inactive), 'clock', 'var(--chart-6)')}
      ${stat(t('retn.statClv'), money(m.clv), 'dollar', 'var(--chart-2)')}
      ${stat(t('retn.statActiveMembers'), num(m.active_members), 'star', 'var(--chart-1)')}
      ${stat(t('retn.statFollowupConversion'), (m.followup_conversion ?? 0) + '%', 'heart', 'var(--chart-4)')}
    </div>
    <div class="grid grid-2" style="margin-bottom:16px">
      <div class="card"><div class="card-head"><h4>${t('retn.retentionByBranch')}</h4></div>
        <div class="card-body">${m.retention_by_branch.length
          ? barList(m.retention_by_branch, { color: 'var(--chart-1)' })
          : emptyState('building', t('common.noData'))}</div></div>
      <div class="card"><div class="card-head"><h4>${t('retn.topReturningTreatments')}</h4></div>
        <div class="card-body">${m.top_returning_treatments.length
          ? barList(m.top_returning_treatments, { color: 'var(--chart-3)' })
          : emptyState('spark', t('retn.noRepeatTreatments'))}</div></div>
    </div>`;
}

function matchesStatusSearch(r, filters) {
  if (filters.status !== 'all' && r.status !== filters.status) return false;
  if (filters.search) {
    const name = r.customer || '';
    try {
      if (!new RegExp(filters.search, 'i').test(name)) return false;
    } catch (e) {
      if (!name.toLowerCase().includes(filters.search.toLowerCase())) return false;
    }
  }
  return true;
}

function reminderRowsHtml(rows, filters) {
  const filtered = rows.filter((r) =>
    (filters.type === 'all' || r.type === filters.type) && matchesStatusSearch(r, filters));
  return filtered.length ? filtered.map((r) => `
    <tr>
      <td><span class="badge badge-soft">${REMINDER_LABEL[r.type] || r.type}</span></td>
      <td class="strong">${escapeHtml(r.customer)}</td>
      <td class="muted truncate" style="max-width:360px">${escapeHtml(r.body)}</td>
      <td class="muted text-sm">${r.due_at ? dueFmt(r.due_at) : '—'}</td>
      <td><span class="badge ${r.status === 'sent' ? 'badge-paid' : r.status === 'failed' ? 'badge-lost' : 'badge-interested'}">${r.status === 'sent' ? t('retn.statusSent') : r.status === 'failed' ? t('retn.statusFailed') : t('retn.statusPending')}</span></td>
    </tr>`).join('') : `<tr><td colspan="5">${emptyState('clock', t('retn.emptyRemindersTitle'), t('retn.emptyRemindersSub'))}</td></tr>`;
}

function chipsHtml(rows, filters) {
  const counts = {};
  rows.filter((r) => matchesStatusSearch(r, filters))
    .forEach((r) => { counts[r.type] = (counts[r.type] || 0) + 1; });
  return Object.entries(counts).sort((a, b) => b[1] - a[1])
    .map(([tp, n]) => `<span class="badge badge-soft">${REMINDER_LABEL[tp] || tp} · ${n}</span>`).join(' ');
}

function renderReminders(box, rows, filters) {
  box.innerHTML = `
    <div class="row gap-2" style="flex-wrap:wrap;margin-bottom:12px;align-items:center">
      <div class="search-box" style="max-width:260px;flex:1;position:relative">
        ${icon('search', 16)}
        <input class="input" id="rem-filter-search" type="text" placeholder="${t('retn.filterSearchPlaceholder')}"
          value="${escapeHtml(filters.search)}" style="padding-right:36px">
        <button type="button" id="rem-filter-search-clear" title="${t('common.clear')}"
          style="position:absolute;right:12px;top:50%;transform:translateY(-50%);width:20px;height:20px;
            display:${filters.search ? 'flex' : 'none'};align-items:center;justify-content:center;
            border:none;background:transparent;padding:0;border-radius:var(--r-sm);color:var(--muted);cursor:pointer">
          ${icon('close', 14)}</button>
      </div>
      <select class="select" id="rem-filter-type" style="max-width:220px">
        <option value="all">${t('retn.filterAllTypes')}</option>
        ${REMINDER_TYPES.map((tp) => `<option value="${tp}" ${filters.type === tp ? 'selected' : ''}>${REMINDER_LABEL[tp] || tp}</option>`).join('')}
      </select>
      <select class="select" id="rem-filter-status" style="max-width:180px">
        <option value="all">${t('retn.filterAllStatuses')}</option>
        ${REMINDER_STATUSES.map((s) => `<option value="${s}" ${filters.status === s ? 'selected' : ''}>${STATUS_LABEL[s]()}</option>`).join('')}
      </select>
    </div>
    <div id="rem-chips" class="row gap-2" style="flex-wrap:wrap;margin-bottom:12px">${chipsHtml(rows, filters)}</div>
    <div class="card results-min"><table class="table">
    <thead><tr><th>${t('retn.colType')}</th><th>${t('retn.colCustomer')}</th><th>${t('retn.colMessage')}</th><th>${t('retn.colDue')}</th><th>${t('common.status')}</th></tr></thead>
    <tbody id="rem-tbody">${reminderRowsHtml(rows, filters)}</tbody>
    </table></div>`;

  const typeSel = box.querySelector('#rem-filter-type');
  const statusSel = box.querySelector('#rem-filter-status');
  const searchInput = box.querySelector('#rem-filter-search');
  const searchClear = box.querySelector('#rem-filter-search-clear');
  typeSel.value = filters.type;
  statusSel.value = filters.status;
  const rerenderRows = () => {
    box.querySelector('#rem-tbody').innerHTML = reminderRowsHtml(rows, filters);
  };
  const rerenderChips = () => {
    box.querySelector('#rem-chips').innerHTML = chipsHtml(rows, filters);
  };
  typeSel.onchange = () => { filters.type = typeSel.value; rerenderRows(); };
  statusSel.onchange = () => { filters.status = statusSel.value; rerenderRows(); rerenderChips(); };
  let searchDebounce;
  searchInput.oninput = () => {
    searchClear.style.display = searchInput.value ? 'flex' : 'none';
    clearTimeout(searchDebounce);
    searchDebounce = setTimeout(() => {
      filters.search = searchInput.value;
      rerenderRows();
      rerenderChips();
    }, 300);
  };
  searchClear.onclick = () => {
    clearTimeout(searchDebounce);
    searchInput.value = '';
    searchClear.style.display = 'none';
    filters.search = '';
    searchInput.focus();
    rerenderRows();
    rerenderChips();
  };
}

async function showTab(mount, tab) {
  activeTab = tab;
  const box = mount.querySelector('#ret-tab');
  box.innerHTML = loadingBlock();
  if (tab === 'reminders') {
    let rows = [];
    try { rows = await api.get('/retention/reminders'); } catch (e) {}
    renderReminders(box, rows, reminderFilters);
  } else {
    let rules = [];
    try { rules = await api.get('/retention/automations'); } catch (e) {}
    const byType = Object.fromEntries(rules.map((r) => [r.type, r]));
    const canEdit = store.canManage() || store.isRole('marketing');
    const card = (type) => {
      const r = byType[type];
      if (!r) return '';
      const m = AUTO_META[type] || { icon: 'zap', label: r.name, desc: r.description };
      return `<div class="card card-pad">
        <div class="row-between">
          <div class="row gap-2"><span class="stat-ic">${icon(m.icon, 15)}</span>
            <span class="strong">${escapeHtml(m.label)}</span></div>
          <label class="toggle">
            <input type="checkbox" data-rule="${r.id}" ${r.enabled ? 'checked' : ''} ${canEdit ? '' : 'disabled'}>
            <span class="track"></span></label>
        </div>
        <div class="muted text-sm" style="margin-top:8px">${escapeHtml(m.desc)}</div>
      </div>`;
    };
    box.innerHTML = CATEGORIES.map((cat) => `
      <div class="row gap-2" style="margin:10px 0;font-weight:600;color:var(--ink)">
        ${icon(cat.icon, 16)}<span>${cat.title}</span></div>
      <div class="grid grid-2" style="margin-bottom:20px">${cat.types.map(card).join('')}</div>`).join('');
    box.querySelectorAll('[data-rule]').forEach((cb) => {
      cb.onchange = async () => {
        try {
          await api.patch(`/retention/automations/${cb.dataset.rule}`, { enabled: cb.checked });
          toast(t('common.updated'), 'success');
        } catch (e) { toast(e.detail || t('retn.failed'), 'error'); cb.checked = !cb.checked; }
      };
    });
  }
}
