/* Blinks Bright — Payments view */

import { api } from '../api.js';
import { store } from '../store.js';
import { icon, escapeHtml, money, toast, loadingBlock, emptyState, dateTime, confirmDialog } from '../ui.js';
import { t } from '../i18n.js';

const PAY_BADGE = {
  paid: 'badge-paid', booked: 'badge-booked', pending: 'badge-interested',
  failed: 'badge-danger', refunded: 'badge-soft',
};
const STATUS_LABEL = {
  paid: t('payments.statusPaid'), booked: t('payments.statusBooked'), pending: t('payments.statusPending'),
  failed: t('payments.statusFailed'), refunded: t('payments.statusRefunded'),
};
const TYPE_LABEL = {
  deposit: t('payments.typeDeposit'), full: t('payments.typeFull'),
};
const METHOD_LABEL = {
  card: t('payments.methodCard'), promptpay: t('payments.methodPromptpay'),
};
const FILTERS = [['', t('common.all')], ['paid', t('payments.statusPaid')], ['booked', t('payments.statusBooked')], ['pending', t('payments.statusPending')]];
const RANGES = [['7d', t('payments.days7')], ['30d', t('payments.days30')], ['90d', t('payments.days90')], ['1y', t('payments.days365')], ['all', t('common.all')]];

// A paid deposit means the slot is booked (not yet fully settled); a paid
// full payment is fully settled. Same underlying `status='paid'` row, different label.
function displayStatus(p) {
  return p.status === 'paid' && p.type === 'deposit' ? 'booked' : p.status;
}
// The amount read off the slip disagrees with the amount due (services/slips.py) —
// same 1-satang tolerance as amounts_match there.
function slipMismatch(p) {
  return p.slip_amount != null && Math.abs(Number(p.slip_amount) - Number(p.amount || 0)) >= 0.01;
}

// Module-level (not per-render) so the selected tab survives a branch switch,
// which re-invokes this view function against the same cached module instance.
let filter = '';

export default async function renderPayments(mount) {
  mount.innerHTML = `<div class="view">
    <div class="view-head">
      <div><h2>${t('payments.title')}</h2><p>${t('payments.subtitle')}</p></div>
      <div class="segmented" id="pay-range">
        ${RANGES.map(([v, l]) => `<button class="${v === store.dateRange ? 'active' : ''}" data-r="${v}">${l}</button>`).join('')}
      </div>
    </div>
    <div class="grid grid-4" id="pay-stats" style="margin-bottom:18px"></div>
    <div class="segmented" id="pay-filters" style="margin-bottom:14px">
      ${FILTERS.map(([v, l]) => `<button class="${v === filter ? 'active' : ''}" data-f="${v}">${l}</button>`).join('')}
    </div>
    <div id="pay-body">${loadingBlock()}</div>
  </div>`;

  const body = mount.querySelector('#pay-body');

  loadStats(mount);
  mount.querySelectorAll('#pay-filters button').forEach((b) => {
    b.onclick = () => {
      mount.querySelectorAll('#pay-filters button').forEach((x) => x.classList.toggle('active', x === b));
      filter = b.dataset.f;
      load();
    };
  });
  // Shared with the Dashboard's own range toggle (store.dateRange) so picking a
  // window on either page carries over to the other — one "which period am I
  // looking at" state, not two that silently disagree.
  mount.querySelectorAll('#pay-range button').forEach((b) => {
    b.onclick = () => {
      mount.querySelectorAll('#pay-range button').forEach((x) => x.classList.toggle('active', x === b));
      store.set('dateRange', b.dataset.r);
      loadStats(mount);
      load();
    };
  });

  async function load() {
    body.innerHTML = loadingBlock();
    const params = new URLSearchParams({ period: store.dateRange });
    if (filter) params.set('status', filter);
    if (store.branchId && store.branchId !== 'all') params.set('branch_id', store.branchId);
    let rows = [];
    try { rows = await api.get('/payments?' + params.toString()); }
    catch (e) { body.innerHTML = emptyState('alert', t('payments.loadFailed')); return; }
    if (!rows.length) {
      body.innerHTML = `<div class="card">${emptyState('card', t('payments.emptyTitle'), t('payments.emptySub'))}</div>`;
      return;
    }
    body.innerHTML = `<div class="card"><table class="table">
      <thead><tr><th>${t('payments.colCustomer')}</th><th>${t('payments.colDescription')}</th><th>${t('payments.colType')}</th><th>${t('payments.colAmount')}</th>
        <th>${t('payments.colMethod')}</th><th>${t('common.status')}</th><th>${t('payments.colDate')}</th></tr></thead>
      <tbody>${rows.map((p) => { const st = displayStatus(p); return `
        <tr>
          <td class="strong">${escapeHtml(p.customer_name)}</td>
          <td class="muted">${escapeHtml(p.description || '—')}</td>
          <td><span class="chip">${TYPE_LABEL[p.type] || escapeHtml(p.type)}</span></td>
          <td class="strong">${money(p.amount)}</td>
          <td class="muted">${p.method ? (METHOD_LABEL[p.method] || escapeHtml(p.method)) : '—'}</td>
          <td><span class="badge ${PAY_BADGE[st] || 'badge-soft'}">${STATUS_LABEL[st] || escapeHtml(st)}</span>
            ${p.status === 'pending' && p.slip_image ? `<div class="slip-row">
              <a class="slip-thumb" href="${escapeHtml(p.slip_image)}" target="_blank" rel="noopener"
                title="${t('payments.viewSlip')}"><img src="${escapeHtml(p.slip_image)}" alt="${t('payments.viewSlip')}"></a>
              <span class="badge badge-interested">${t('payments.slipWaiting')}</span>
              ${slipMismatch(p) ? `<span class="badge badge-danger" title="${t('payments.slipMismatchTip')}">${
                t('payments.slipMismatch', { amount: money(p.slip_amount) })}</span>` : ''}</div>` : ''}
            ${p.status === 'pending' ? `<button class="btn btn-sm btn-ghost pay-confirm" data-id="${p.id}"
              data-amount="${p.amount}" data-name="${escapeHtml(p.customer_name)}">${icon('check', 13)} ${t('payments.confirmPaid')}</button>` : ''}
            ${p.status === 'pending' && p.slip_image ? `<button class="btn btn-sm btn-ghost slip-reject" data-id="${p.id}"
              data-name="${escapeHtml(p.customer_name)}">${icon('close', 13)} ${t('payments.rejectSlip')}</button>` : ''}</td>
          <td class="muted text-sm">${p.paid_at ? dateTime(p.paid_at) : dateTime(p.created_at)}</td>
        </tr>`; }).join('')}
      </tbody></table></div>`;
    body.querySelectorAll('.slip-reject').forEach((btn) => {
      btn.onclick = async () => {
        const ok = await confirmDialog({
          title: t('payments.rejectSlipTitle'),
          message: t('payments.rejectSlipMsg', { name: btn.dataset.name }),
          confirmLabel: t('payments.rejectSlip'), danger: true,
        });
        if (!ok) return;
        btn.disabled = true;
        try {
          await api.post(`/payments/${btn.dataset.id}/reject-slip`, {});
          toast(t('payments.slipRejected'), 'success');
          loadStats(mount);
          load();
        } catch (e) {
          btn.disabled = false;
          toast(e.message || t('payments.markPaidFailed'), 'error');
        }
      };
    });
    body.querySelectorAll('.pay-confirm').forEach((btn) => {
      btn.onclick = async () => {
        const ok = await confirmDialog({
          title: t('payments.confirmPaidTitle'),
          message: t('payments.confirmPaidMsg', { amount: money(btn.dataset.amount), name: btn.dataset.name }),
          confirmLabel: t('payments.confirmPaid'),
        });
        if (!ok) return;
        btn.disabled = true;
        try {
          const r = await api.post(`/payments/${btn.dataset.id}/mark-paid`, {});
          toast(r.already_paid ? t('payments.alreadyPaid') : t('payments.markedPaid'), 'success');
          loadStats(mount);
          load();
        } catch (e) {
          btn.disabled = false;
          toast(e.message || t('payments.markPaidFailed'), 'error');
        }
      };
    });
  }
  load();
}

async function loadStats(mount) {
  try {
    const params = new URLSearchParams({ period: store.dateRange });
    if (store.branchId && store.branchId !== 'all') params.set('branch_id', store.branchId);
    const s = await api.get('/payments/summary?' + params.toString());
    mount.querySelector('#pay-stats').innerHTML = [
      [t('payments.statRevenue'), money(s.revenue), 'dollar', 'var(--chart-2)'],
      [t('payments.statDepositPaid'), s.deposit_paid, 'card', 'var(--chart-6)'],
      [t('payments.statPaid'), s.paid, 'check-circle', 'var(--chart-3)'],
      [t('payments.statusPending'), s.pending, 'clock', 'var(--chart-4)'],
    ].map(([label, val, ic, color]) => `
      <div class="stat-card" style="--ic:${color}">
        <div class="stat-top"><span class="stat-label">${label}</span>
          <span class="stat-ic">${icon(ic, 16)}</span></div>
        <div class="stat-value">${val}</div>
      </div>`).join('');
  } catch (e) { /* ignore */ }
}
