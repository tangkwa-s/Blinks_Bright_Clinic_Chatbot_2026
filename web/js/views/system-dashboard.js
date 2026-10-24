/* Blinks Bright — System console: cross-clinic overview (Tier 1, super_admin) */

import { api } from '../api.js';
import { icon, money, num, escapeHtml, initials, toast, loadingBlock,
         emptyState } from '../ui.js';
import { barList } from '../charts.js';
import { t } from '../i18n.js';

function statCard(label, value, ic, color) {
  return `<div class="stat-card" style="--ic:${color || 'var(--primary)'}">
    <div class="stat-top"><span class="stat-label">${label}</span>
      <span class="stat-ic">${icon(ic, 16)}</span></div>
    <div class="stat-value">${value}</div>
  </div>`;
}

export default async function renderSystemDashboard(mount) {
  mount.innerHTML = `<div class="view">
    <div class="dash-hero">
      <div><h2>${t('sysdash.title')}</h2>
        <p class="muted">${t('sysdash.subtitle')}</p></div>
      <div class="segmented" id="sd-range">
        <button data-r="7d">${t('sysdash.days7')}</button>
        <button class="active" data-r="30d">${t('sysdash.days30')}</button>
        <button data-r="90d">${t('sysdash.days90')}</button>
        <button data-r="all">${t('common.all')}</button>
      </div>
    </div>
    <div id="sd-body">${loadingBlock()}</div>
  </div>`;

  const body = mount.querySelector('#sd-body');
  let range = '30d';

  mount.querySelectorAll('#sd-range button').forEach((b) => {
    b.onclick = () => {
      mount.querySelectorAll('#sd-range button').forEach((x) => x.classList.toggle('active', x === b));
      range = b.dataset.r;
      load();
    };
  });

  async function load() {
    body.innerHTML = loadingBlock();
    let d;
    try { d = await api.get('/admin/overview?period=' + range); }
    catch (e) { body.innerHTML = emptyState('alert', t('sysdash.loadFailed')); return; }
    body.innerHTML = renderBody(d);
    body.querySelectorAll('[data-enter]').forEach((btn) => {
      btn.onclick = async () => {
        btn.disabled = true;
        btn.innerHTML = '<div class="spinner"></div>';
        try { await api.post(`/clinics/${btn.dataset.enter}/enter`); location.reload(); }
        catch (ex) {
          toast(ex.detail || t('sysdash.openFailed'), 'error');
          btn.disabled = false;
          btn.innerHTML = `${icon('arrow-right', 14)}<span>${t('sysdash.open')}</span>`;
        }
      };
    });
  }
  load();
}

function renderBody(d) {
  const tot = d.totals;
  const rev = d.clinics
    .map((c) => ({ label: c.name, value: c.revenue, display: money(c.revenue),
                   color: c.accent || 'var(--chart-2)' }))
    .filter((r) => r.value > 0)
    .sort((a, b) => b.value - a.value);   // highest revenue first
  const rows = [...d.clinics].sort((a, b) => b.revenue - a.revenue);
  const periodLabel = d.period === 'all' ? t('sysdash.allTime') : t('sysdash.lastPeriod', { period: d.period });

  return `
    <div class="grid grid-4" style="margin-bottom:16px">
      ${statCard(t('sysdash.statClinics'), num(tot.clinics), 'building', 'var(--chart-7)')}
      ${statCard(t('sysdash.statRevenue'), money(tot.revenue), 'dollar', 'var(--chart-2)')}
      ${statCard(t('sysdash.statLeads'), num(tot.leads), 'users', 'var(--chart-1)')}
      ${statCard(t('sysdash.statBookings'), num(tot.bookings), 'calendar', 'var(--chart-5)')}
      ${statCard(t('sysdash.statDepositPaid'), num(tot.deposit_paid), 'card', 'var(--chart-6)')}
      ${statCard(t('sysdash.statPaid'), num(tot.paid), 'card', 'var(--chart-8)')}
      ${statCard(t('sysdash.statFollowups'), num(tot.followups), 'refresh', 'var(--chart-3)')}
      ${statCard(t('sysdash.statConversion'), tot.conversion + '%', 'target', 'var(--chart-4)')}
    </div>
    <div class="grid grid-2" style="align-items:start;margin-bottom:16px">
      <div class="card card-pad">
        <div class="card-head"><h4>${t('sysdash.revenueByClinic')}</h4>
          <span class="muted text-sm">${periodLabel}</span></div>
        ${rev.length ? barList(rev) : emptyState('analytics', t('sysdash.noRevenue'))}
      </div>
      <div class="card card-pad">
        <div class="card-head"><h4>${t('sysdash.platformTotals')}</h4></div>
        <div class="kv"><span class="k">${t('sysdash.activeLogins')}</span><span class="v strong">${num(tot.users)}</span></div>
        <div class="kv"><span class="k">${t('sysdash.customers')}</span><span class="v">${num(tot.customers)}</span></div>
        <div class="kv"><span class="k">${t('sysdash.conversations')}</span><span class="v">${num(tot.conversations)}</span></div>
        <div class="kv"><span class="k">${t('sysdash.bookings')} (${periodLabel})</span><span class="v">${num(tot.bookings)}</span></div>
      </div>
    </div>
    <div class="card">
      <div class="card-head card-pad" style="padding-bottom:0"><h4>${t('sysdash.allClinics')}</h4></div>
      <table class="table">
        <thead><tr><th>${t('sysdash.thClinic')}</th><th>${t('sysdash.thCustomers')}</th><th>${t('sysdash.thLeads')}</th><th>${t('sysdash.thDepositPaid')}</th><th>${t('sysdash.thPaid')}</th><th>${t('sysdash.thFollowup')}</th>
          <th>${t('sysdash.thBookings')}</th><th>${t('sysdash.thRevenue')}</th><th>${t('sysdash.thConversion')}</th><th></th></tr></thead>
        <tbody>
          ${rows.map((c) => `<tr>
            <td><div class="row gap-2">
              <span class="avatar sm clinic-mark" style="background:${escapeHtml(c.accent || 'var(--primary)')};color:#fff">${
                c.logo ? `<img src="${escapeHtml(c.logo)}" alt="">` : escapeHtml(initials(c.name))}</span>
              <span class="strong">${escapeHtml(c.name)}</span></div></td>
            <td>${num(c.customers)}</td>
            <td>${num(c.leads)}</td>
            <td>${num(c.deposit_paid)}</td>
            <td>${num(c.paid)}</td>
            <td>${num(c.followups)}</td>
            <td>${num(c.bookings)}</td>
            <td class="strong">${money(c.revenue)}</td>
            <td>${c.conversion}%</td>
            <td style="text-align:right">
              <button class="btn btn-ghost btn-sm" data-enter="${c.clinic_id}">${icon('arrow-right', 14)}<span>${t('sysdash.open')}</span></button>
            </td>
          </tr>`).join('')}
        </tbody>
      </table>
    </div>`;
}
