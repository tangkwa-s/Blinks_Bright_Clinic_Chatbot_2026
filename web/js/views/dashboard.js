/* Blinks Bright — Overview dashboard */

import { api } from '../api.js';
import { store } from '../store.js';
import { router } from '../router.js';
import { icon, money, num, escapeHtml, loadingBlock, emptyState } from '../ui.js';
import { donut, legend, lineChart, funnel, barList, sparkline } from '../charts.js';
import { t } from '../i18n.js';

const CH = {
  web: { label: t('dash.chWeb'), color: 'var(--chart-1)' },
};
const STAGE_LABEL = {
  new_lead: t('dash.stageNewLead'), interested: t('dash.stageInterested'), booked: t('dash.stageBooked'),
  paid: t('dash.stagePaid'), followup: t('dash.stageFollowup'),
};
const STATUS_BADGE = {
  new_lead: 'badge-new', interested: 'badge-interested', booked: 'badge-booked',
  paid: 'badge-paid', followup: 'badge-followup',
};

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? t('dash.goodMorning') : h < 18 ? t('dash.goodAfternoon') : t('dash.goodEvening');
}

export default async function renderDashboard(mount) {
  const name = escapeHtml((store.user?.name || t('dash.guestName')).split(' ')[0]);
  mount.innerHTML = `<div class="view">
    <div class="dash-hero">
      <div><h2>${greeting()}, ${name}</h2>
        <p class="muted">${t('dash.subtitle')}</p></div>
      <div class="segmented" id="dash-range">
        <button data-r="7d" class="${store.dateRange === '7d' ? 'active' : ''}">${t('dash.days7')}</button>
        <button data-r="30d" class="${store.dateRange === '30d' ? 'active' : ''}">${t('dash.days30')}</button>
        <button data-r="90d" class="${store.dateRange === '90d' ? 'active' : ''}">${t('dash.days90')}</button>
        <button data-r="1y" class="${store.dateRange === '1y' ? 'active' : ''}">${t('dash.days365')}</button>
        <button data-r="all" class="${store.dateRange === 'all' ? 'active' : ''}">${t('common.all')}</button>
      </div>
    </div>
    <div id="dash-body">${loadingBlock()}</div>
  </div>`;

  const body = mount.querySelector('#dash-body');

  // Shared with the Payments page's own range toggle (store.dateRange) — one
  // "which period am I looking at" state, not two that silently disagree.
  mount.querySelectorAll('#dash-range button').forEach((b) => {
    b.onclick = () => {
      mount.querySelectorAll('#dash-range button').forEach((x) => x.classList.toggle('active', x === b));
      store.set('dateRange', b.dataset.r);
      load();
    };
  });

  async function load() {
    body.innerHTML = loadingBlock();
    const p = new URLSearchParams({ period: store.dateRange });
    if (store.branchId && store.branchId !== 'all') p.set('branch_id', store.branchId);
    let d;
    try { d = await api.get('/dashboard?' + p.toString()); }
    catch (e) { body.innerHTML = emptyState('alert', t('dash.loadFailed')); return; }
    body.innerHTML = renderBody(d);
    body.querySelectorAll('[data-conv]').forEach((el) =>
      (el.onclick = () => router.go('conversations/' + el.dataset.conv)));
  }
  load();
}

function statCard(label, value, ic, opts = {}) {
  return `<div class="stat-card" style="--ic:${opts.color || 'var(--primary)'}">
    <div class="stat-top"><span class="stat-label">${label}</span>
      <span class="stat-ic">${icon(ic, 16)}</span></div>
    <div class="stat-value">${value}</div>
    ${opts.sub ? `<div class="muted text-xs" style="margin-top:2px">${opts.sub}</div>` : ''}
    ${opts.delta ? `<div class="stat-delta up">${icon('trending-up', 12)} ${opts.delta}</div>` : ''}
    ${opts.spark && opts.spark.length
      ? `<div class="stat-spark">${sparkline(opts.spark, { color: opts.color })}</div>` : ''}
  </div>`;
}

function renderBody(d) {
  const s = d.stats;
  const chSeg = Object.entries(d.by_channel).map(([k, v]) => ({
    label: (CH[k] || {}).label || k, value: v, color: (CH[k] || {}).color || 'var(--chart-2)',
  }));
  const totalLeads = chSeg.reduce((a, b) => a + b.value, 0);
  const fStages = ['new_lead', 'interested', 'booked', 'paid', 'followup']
    .map((k) => ({ label: STAGE_LABEL[k], value: d.funnel[k] || 0 }));

  return `
    <div class="grid grid-4" style="margin-bottom:16px">
      ${statCard(t('dash.statRevenue'), money(s.revenue), 'dollar', { spark: d.sparks?.revenue, color: 'var(--chart-2)' })}
      ${statCard(t('dash.statLeads'), num(s.leads), 'users', { spark: d.sparks?.leads, color: 'var(--chart-1)' })}
      ${statCard(t('dash.statBookings'), num(s.bookings), 'calendar', { spark: d.sparks?.bookings, color: 'var(--chart-5)' })}
      ${statCard(t('dash.statDepositPaid'), num(s.deposit_paid), 'card', { spark: d.sparks?.deposit_paid, color: 'var(--chart-6)' })}
      ${statCard(t('dash.statPaid'), num(s.paid), 'card', { spark: d.sparks?.paid, color: 'var(--chart-8)' })}
      ${statCard(t('dash.statPending'), num(s.pending), 'clock', { spark: d.sparks?.pending, color: 'var(--chart-4)' })}
      ${statCard(t('dash.statFollowups'), num(s.followups), 'refresh', { spark: d.sparks?.followups, color: 'var(--chart-3)' })}
      ${statCard(t('dash.statConversion'), s.conversion + '%', 'target', { spark: d.sparks?.conversion, color: 'var(--chart-4)' })}
    </div>

    <div class="grid grid-3" style="margin-bottom:16px">
      <div class="card span-2">
        <div class="card-head"><h4>${t('dash.revenueTrend')}</h4>
          <span class="sub">${t('dash.collected', { amount: money(s.revenue) })}</span></div>
        <div class="card-body">${lineChart(d.trend.values, { labels: d.trend.labels, color: 'var(--chart-2)', color2: 'var(--chart-4)' })}</div>
      </div>
      <div class="card">
        <div class="card-head"><h4>${t('dash.leadsByChannel')}</h4></div>
        <div class="card-body" style="display:flex;flex-direction:column;align-items:center;gap:16px">
          ${donut(chSeg, { centerLabel: num(totalLeads), centerSub: t('dash.leads') })}
          ${legend(chSeg)}
        </div>
      </div>
    </div>

    <div class="grid grid-3" style="margin-bottom:16px">
      <div class="card">
        <div class="card-head"><h4>${t('dash.leadFunnel')}</h4></div>
        <div class="card-body">${funnel(fStages)}</div>
      </div>
      <div class="card">
        <div class="card-head"><h4>${t('dash.topTreatments')}</h4></div>
        <div class="card-body">${barList(d.top_treatments.map((t2) => ({ ...t2, color: 'var(--chart-2)' })))}</div>
      </div>
      <div class="card">
        <div class="card-head"><h4>${t('dash.branchPerformance')}</h4></div>
        <div class="card-body">
          ${d.branch_performance.map((b) => `
            <div class="kv"><span class="k">${escapeHtml(b.name)}</span>
              <span class="v">${t('dash.branchStat', { revenue: money(b.revenue), count: b.bookings })}</span></div>`).join('')
            || `<div class="muted text-sm">${t('common.noData')}</div>`}
        </div>
      </div>
    </div>

    <div class="grid grid-3">
      <div class="card span-2">
        <div class="card-head"><h4>${t('dash.recentConversations')}</h4>
          <a class="sub" href="#/conversations">${t('common.viewAll')} →</a></div>
        <div class="card-body" style="padding:0">
          <table class="table"><tbody>
            ${d.recent_conversations.map((c) => `
              <tr class="row-click" data-conv="${c.id}">
                <td class="strong" style="width:130px">${escapeHtml(c.customer)}</td>
                <td class="muted truncate">${escapeHtml(c.last_message)}</td>
                <td style="width:96px"><span class="badge ${STATUS_BADGE[c.status] || 'badge-soft'}">${STAGE_LABEL[c.status] || c.status}</span></td>
              </tr>`).join('') || `<tr><td class="muted">${t('dash.noConversations')}</td></tr>`}
          </tbody></table>
        </div>
      </div>
      <div class="card">
        <div class="card-head"><h4>${t('dash.topClosers')}</h4></div>
        <div class="card-body">
          ${d.admin_performance.map((a, i) => `
            <div class="insight-row">
              <span class="ins-rank">${i + 1}</span>
              <div style="flex:1"><div class="strong text-sm">${escapeHtml(a.name)}</div>
                <div class="muted text-xs">${t('dash.closerStat', { closed: a.closed, total: a.total })}</div></div>
            </div>`).join('') || `<div class="muted text-sm">${t('common.noData')}</div>`}
        </div>
      </div>
    </div>`;
}
