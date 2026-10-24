/* Blinks Bright — Bookings view */

import { api } from '../api.js';
import { store } from '../store.js';
import { icon, escapeHtml, money, toast, modal, confirmDialog, loadingBlock, emptyState,
         dateLongRaw, dayNameRaw, timeOfRaw } from '../ui.js';
import { t } from '../i18n.js';
import { mountDateRange } from '../daterange.js';

const BK_BADGE = {
  pending: 'badge-interested', confirmed: 'badge-booked', completed: 'badge-paid',
  cancelled: 'badge-lost', no_show: 'badge-danger', expired: 'badge-soft',
};
const BK_LABEL = {
  pending: t('book.statusPending'), confirmed: t('book.statusConfirmed'), completed: t('book.statusCompleted'),
  cancelled: t('book.statusCancelled'), no_show: t('book.statusNoShow'),
  expired: t('book.statusExpired'),
};
// What a HUMAN may set. Deliberately not Object.keys(BK_LABEL): 'expired' means the
// clinic's own hold clock ran out, which is not a decision staff make, and picking it by
// hand would leave hold_expires_at empty — a booking stuck out of every reader's view.
const EDITABLE_STATUSES = ['pending', 'confirmed', 'completed', 'cancelled', 'no_show'];
const FILTERS = [['', t('common.all')], ['upcoming', t('book.filterUpcoming')], ['pending', t('book.statusPending')],
                 ['confirmed', t('book.statusConfirmed')], ['completed', t('book.statusCompleted')],
                 ['no_show', t('book.statusNoShow')], ['expired', t('book.statusExpired')]];

// Module-level (not per-render) so the selected tab survives a branch switch,
// which re-invokes this view function against the same cached module instance.
let filter = '';

/* ---- date range ------------------------------------------------------- */
const ymd = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

/* Monday of the week containing `d`. getDay() is Sunday-based (0), and a clinic week
   reads Monday to Sunday, so Sunday has to walk back six days rather than none. */
function mondayOf(d) {
  const m = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  m.setDate(m.getDate() - ((m.getDay() + 6) % 7));
  return m;
}

function weekOf(d) {
  const from = mondayOf(d);
  const to = new Date(from);
  to.setDate(to.getDate() + 6);
  return { from: ymd(from), to: ymd(to) };
}

/* Survives a branch switch for the same reason `filter` does. Defaults to the
   current Monday-Sunday week, the span a clinic actually plans against. */
let range = weekOf(new Date());

/* The shortcuts in the picker. "เดือนนี้" is the calendar month; the multi-month ones
   are a planning horizon FORWARD from today, which is what a clinic looks at a
   bookings list for. Each is a function, not a fixed value, so they stay correct in a
   tab left open across midnight. */
const PRESETS = [
  { id: 'today', label: t('book.rangeToday'), range: () => todayOnly() },
  { id: 'week', label: t('book.rangeThisWeek'), range: () => weekOf(new Date()) },
  { id: 'month', label: t('book.rangeThisMonth'), range: () => thisMonth() },
  { id: '3m', label: t('book.range3m'), range: () => monthsAhead(3) },
  { id: '6m', label: t('book.range6m'), range: () => monthsAhead(6) },
];

function todayOnly() {
  const d = ymd(new Date());
  return { from: d, to: d };
}

function thisMonth() {
  const n = new Date();
  return { from: ymd(new Date(n.getFullYear(), n.getMonth(), 1)),
    to: ymd(new Date(n.getFullYear(), n.getMonth() + 1, 0)) };   // day 0 = last of month
}

function monthsAhead(n) {
  const start = new Date();
  const end = new Date(start.getFullYear(), start.getMonth() + n, start.getDate());
  // Clamp a day the target month does not have: 31 Aug + 6 months must land on 28/29
  // Feb, not roll over into March.
  if (end.getDate() !== start.getDate()) end.setDate(0);
  return { from: ymd(start), to: ymd(end) };
}

/* "จ. 4 ส.ค. - อา. 10 ส.ค. 2026", or the open-ended forms when a side is cleared. */
function rangeLabel() {
  if (!range.from && !range.to) return t('book.rangeAll');
  const one = (v) => (v ? `${dayNameRaw(v)} ${dateLongRaw(v)}` : '');
  if (!range.to) return `${t('book.rangeFrom')} ${one(range.from)}`;
  if (!range.from) return `${t('book.rangeTo')} ${one(range.to)}`;
  return `${one(range.from)} - ${one(range.to)}`;
}

export default async function renderBookings(mount) {
  mount.innerHTML = `<div class="view">
    <div class="view-head">
      <div><h2>${t('book.title')}</h2><p>${t('book.subtitle')}</p></div>
      <button class="btn btn-primary" id="new-booking">${icon('plus', 16)}<span>${t('book.newBooking')}</span></button>
    </div>
    <div class="segmented" id="bk-filters" style="margin-bottom:14px">
      ${FILTERS.map(([v, l]) => `<button class="${v === filter ? 'active' : ''}" data-f="${v}">${l}</button>`).join('')}
    </div>
    <div class="bk-daterange">
      <div id="bk-picker"></div>
      <span class="muted text-sm bk-range-label" id="bk-label">${escapeHtml(rangeLabel())}</span>
    </div>
    <div id="bk-body" class="results-min">${loadingBlock()}</div>
  </div>`;

  const body = mount.querySelector('#bk-body');

  // The picker applies a range only when the customer presses ยืนยัน, so a half-open
  // draft never triggers a query. A backwards range cannot be built in it either
  // (clicking before the start restarts the range), but guard anyway — `range` is
  // module-level and outlives any one render.
  function setRange(next) {
    if (next.from && next.to && next.from > next.to) {
      toast(t('book.rangeInvalid'), 'error');
      picker.set(range);
      return;
    }
    range = { from: next.from || '', to: next.to || '' };
    picker.set(range);
    mount.querySelector('#bk-label').textContent = rangeLabel();
    load();
  }

  const picker = mountDateRange(mount.querySelector('#bk-picker'), {
    from: range.from, to: range.to, onApply: setRange, presets: PRESETS,
  });

  mount.querySelectorAll('#bk-filters button').forEach((b) => {
    b.onclick = () => {
      mount.querySelectorAll('#bk-filters button').forEach((x) => x.classList.toggle('active', x === b));
      filter = b.dataset.f;
      load();
    };
  });
  mount.querySelector('#new-booking').onclick = () => newBookingModal(load);

  async function load() {
    body.innerHTML = loadingBlock();
    const params = new URLSearchParams();
    if (filter === 'upcoming') params.set('scope', 'upcoming');
    else if (filter) params.set('status', filter);
    // Pending is future-only: past pendings auto-transition to no-show after the
    // grace period and live under the No-show tab (or All) instead.
    if (filter === 'pending') params.set('scope', 'upcoming');
    if (store.branchId && store.branchId !== 'all') params.set('branch_id', store.branchId);
    if (range.from) params.set('date_from', range.from);
    if (range.to) params.set('date_to', range.to);
    let rows = [];
    try { rows = await api.get('/bookings?' + params.toString()); }
    catch (e) { body.innerHTML = emptyState('alert', t('book.loadFailed')); return; }
    mount.querySelector('#bk-label').textContent =
      `${rangeLabel()} · ${t('book.rangeCount', { n: rows.length })}`;
    renderAgenda(body, rows, load);
  }
  load();
}

function renderAgenda(body, rows, reload) {
  if (!rows.length) {
    // With a range on, "no bookings" is almost always "not in THESE dates" — say that
    // instead, so the fix (widen the range) is the obvious next move.
    const sub = (range.from || range.to) ? t('book.emptyRangeSub') : t('book.emptySub');
    body.innerHTML = `<div class="card">${emptyState('calendar', t('book.emptyTitle'), sub)}</div>`;
    return;
  }
  const groups = {};
  rows.forEach((b) => {
    const key = b.slot_at.slice(0, 10);
    (groups[key] = groups[key] || []).push(b);
  });
  body.innerHTML = Object.keys(groups).sort().map((day) => `
    <div style="margin-bottom:20px">
      <div class="strong" style="margin-bottom:8px">${dateLongRaw(day)}</div>
      <div class="card">
        ${groups[day].map((b) => `
          <div class="conv-item row-click" data-id="${b.id}" style="border-bottom:1px solid var(--border)">
            <div style="width:62px" class="strong">${timeOfRaw(b.slot_at)}</div>
            <div class="ci-main">
              <div class="strong">${escapeHtml(b.customer_name)}</div>
              <div class="muted text-sm">${escapeHtml(b.service_name)} &middot; ${escapeHtml(b.branch_name)}${b.doctor_name ? ' &middot; ' + escapeHtml(b.doctor_name) : ''}${isSeries(b) ? ` <span class="badge badge-soft">${escapeHtml(b.notes)}</span>` : ''}</div>
            </div>
            <div class="row gap-2">
              ${b.deposit_paid ? `<span class="badge badge-paid">${icon('check', 10)} ${t('book.deposit')}</span>` : ''}
              ${b.created_by === 'ai' ? `<span class="badge badge-olive">${icon('ai', 10)} AI</span>` : ''}
              <span class="badge ${BK_BADGE[b.status] || 'badge-soft'}">${BK_LABEL[b.status] || b.status}</span>
            </div>
          </div>`).join('')}
      </div>
    </div>`).join('');

  body.querySelectorAll('[data-id]').forEach((el) => {
    el.onclick = () => bookingModal(rows.find((b) => b.id === Number(el.dataset.id)), reload);
  });
}

function isSeries(b) {
  return b.notes && /ครั้งที่ \d+\/\d+/.test(b.notes);
}

// Free slots for a branch/date (optionally for one doctor, optionally letting a
// booking keep its own slot). Returns ISO strings.
async function fetchSlots({ branchId, date, doctorId, excludeBookingId }) {
  const q = new URLSearchParams({ branch_id: branchId, date });
  if (doctorId) q.set('doctor_id', doctorId);
  if (excludeBookingId) q.set('exclude_booking_id', excludeBookingId);
  const r = await api.get('/bookings/availability?' + q.toString());
  return r.slots || [];
}

function slotOptions(slots, selectedIso) {
  if (!slots.length) return `<option value="" disabled selected>${t('book.noSlots')}</option>`;
  return slots.map((s) => `<option value="${s}" ${s === selectedIso ? 'selected' : ''}>${s.slice(11, 16)}</option>`).join('');
}

function bookingModal(b, reload) {
  const { el } = modal({
    title: t('book.detailsTitle'),
    body: `
      <div class="kv"><span class="k">${t('book.customer')}</span><span class="v">${escapeHtml(b.customer_name)}</span></div>
      <div class="kv"><span class="k">${t('book.treatment')}</span><span class="v">${escapeHtml(b.service_name)}${isSeries(b) ? ` <span class="badge badge-soft">${escapeHtml(b.notes)}</span>` : ''}</span></div>
      <div class="kv"><span class="k">${t('menu.branch')}</span><span class="v">${escapeHtml(b.branch_name)}</span></div>
      <div class="kv"><span class="k">${t('book.doctor')}</span><span class="v">${escapeHtml(b.doctor_name || '—')}</span></div>
      <div class="kv"><span class="k">${t('book.when')}</span><span class="v">${dateLongRaw(b.slot_at)}, ${timeOfRaw(b.slot_at)}</span></div>
      <div class="kv"><span class="k">${t('book.price')}</span><span class="v">${money(b.price)}</span></div>
      <div class="kv"><span class="k">${t('book.deposit')}</span><span class="v">${money(b.deposit_required)} ${b.deposit_paid ? '· ' + t('book.paid') + ' ✓' : '· ' + t('book.unpaid')}</span></div>
      ${b.hold_expires_at && b.status === 'pending' ? `
      <div class="kv"><span class="k">${t('book.heldUntil')}</span><span class="v">${timeOfRaw(b.hold_expires_at)} · ${t('book.holdNote')}</span></div>` : ''}
      <div class="divider"></div>
      <div class="field"><label>${t('common.status')}</label>
        <select class="select" id="bk-status">
          ${EDITABLE_STATUSES.map((s) => `<option value="${s}" ${s === b.status ? 'selected' : ''}>${BK_LABEL[s]}</option>`).join('')}
          ${b.status === 'expired' ? `<option value="expired" selected>${BK_LABEL.expired}</option>` : ''}
        </select></div>
      <div class="grid grid-2">
        <div class="field"><label>${t('book.date')}</label>
          <input class="input" type="date" id="bk-date" value="${b.slot_at.slice(0, 10)}"></div>
        <div class="field"><label>${t('book.time')}</label>
          <select class="select" id="bk-time"><option value="${b.slot_at}" selected>${timeOfRaw(b.slot_at)}</option></select></div>
      </div>`,
    actions: [
      { label: t('common.delete'), class: 'btn-danger', keepOpen: true, onClick: async ({ close }) => {
        const ok = await confirmDialog({
          title: t('book.delConfirmTitle'),
          message: t('book.delConfirmMsg', {
            name: b.customer_name, service: b.service_name,
            when: `${dateLongRaw(b.slot_at)}, ${timeOfRaw(b.slot_at)}`,
          }),
          confirmLabel: t('common.delete'), danger: true,
        });
        if (!ok) return;
        try {
          const r = await api.del(`/bookings/${b.id}`);
          toast(r.cancelled ? t('book.cancelledKept') : t('book.deletedMsg'), 'success');
          close(); reload();
        } catch (e) { toast(e.detail || t('common.deleteFailed'), 'error'); }
      } },
      { label: t('book.sendPayLink'), class: 'btn-clay', keepOpen: true, onClick: async ({ modal: m }) => {
        const btn = m.querySelector('.btn-clay');
        btn.disabled = true;
        try {
          const r = await api.post('/payments/link', { booking_id: b.id, type: 'deposit' });
          window.open(r.qr_url, '_blank');
          toast(t('book.payLinkOpened'), 'success');
        } catch (e) { toast(e.detail || t('book.linkFailed'), 'error'); }
        btn.disabled = false;
      } },
      { label: t('common.cancel'), class: 'btn-ghost' },
      { label: t('common.save'), class: 'btn-primary', keepOpen: true, onClick: async ({ close, modal: m }) => {
        const payload = { status: m.querySelector('#bk-status').value };
        const newSlot = m.querySelector('#bk-time').value;
        if (newSlot && newSlot !== b.slot_at) payload.slot_at = newSlot;
        try {
          await api.patch(`/bookings/${b.id}`, payload);
          toast(t('book.updatedMsg'), 'success'); close(); reload();
        } catch (e) { toast(e.detail || t('common.updateFailed'), 'error'); }
      } },
    ],
  });

  // reschedule: picking another date reloads that day's free slots
  const dateEl = el.querySelector('#bk-date');
  const timeEl = el.querySelector('#bk-time');
  dateEl.onchange = async () => {
    timeEl.innerHTML = `<option value="" disabled selected>…</option>`;
    try {
      const slots = await fetchSlots({
        branchId: b.branch_id, date: dateEl.value,
        doctorId: b.doctor_id, excludeBookingId: b.id,
      });
      timeEl.innerHTML = slotOptions(slots, b.slot_at);
    } catch (e) {
      timeEl.innerHTML = `<option value="" disabled selected>${t('book.noSlots')}</option>`;
    }
  };
}

async function newBookingModal(reload) {
  let customers = [], services = [], team = [];
  try {
    [customers, services, team] = await Promise.all([
      api.get('/customers?limit=300'), api.get('/services'), api.get('/team-members')]);
  } catch (e) { toast(t('book.loadFormFailed'), 'error'); return; }
  const doctors = team.filter((m) => m.active && m.role === 'doctor');
  // default to TODAY in the clinic's timezone (Asia/Bangkok, +7) — same-day booking is allowed
  const today = new Date(Date.now() + 7 * 3600000).toISOString().slice(0, 10);
  // A treatment scoped to one branch (see treatments.js) must never be booked at
  // another branch — only offer it in this dropdown while that branch is selected.
  const defaultBranchId = store.branches[0] ? store.branches[0].id : null;
  const serviceOptions = (branchId) => services
    .filter((sv) => !sv.branch_ids.length || sv.branch_ids.includes(Number(branchId)))
    .map((sv) => `<option value="${sv.id}">${escapeHtml(sv.name)} — ${money(sv.base_price)}</option>`).join('');

  const { el } = modal({
    title: t('book.newBooking'),
    body: `
      <div class="field"><label>${t('book.customer')}</label>
        <select class="select" id="nb-customer">
          ${customers.map((c) => `<option value="${c.id}">${escapeHtml(c.name)} · ${escapeHtml(c.phone || '')}</option>`).join('')}
        </select></div>
      <div class="field"><label>${t('book.treatment')}</label>
        <select class="select" id="nb-service">
          ${serviceOptions(defaultBranchId)}
        </select></div>
      <div class="grid grid-2">
        <div class="field"><label>${t('menu.branch')}</label>
          <select class="select" id="nb-branch">
            ${store.branches.map((b) => `<option value="${b.id}">${escapeHtml(b.name)}</option>`).join('')}
          </select></div>
        <div class="field"><label>${t('book.doctorSelect')}</label>
          <select class="select" id="nb-doctor">
            <option value="">${t('book.anyDoctor')}</option>
            ${doctors.map((d) => `<option value="${d.id}">${escapeHtml(d.name)}</option>`).join('')}
          </select></div>
      </div>
      <div class="grid grid-2">
        <div class="field"><label>${t('book.date')}</label><input class="input" type="date" id="nb-date" value="${today}" min="${today}"></div>
        <div class="field"><label>${t('book.time')}</label>
          <select class="select" id="nb-time"><option value="" disabled selected>…</option></select></div>
      </div>
      <label class="row gap-2" style="align-items:center;margin-bottom:10px;cursor:pointer">
        <input type="checkbox" id="nb-bundle"><span>${t('book.bundleToggle')}</span>
      </label>
      <div class="grid grid-2" id="nb-bundle-fields" style="display:none">
        <div class="field"><label>${t('book.bundleSessions')}</label>
          <input class="input" type="number" id="nb-bundle-n" value="3" min="2" max="12"></div>
        <div class="field"><label>${t('book.bundleInterval')}</label>
          <input class="input" type="number" id="nb-bundle-m" value="1" min="1" max="12"></div>
      </div>`,
    actions: [
      { label: t('common.cancel'), class: 'btn-ghost' },
      { label: t('book.createBooking'), class: 'btn-primary', keepOpen: true, onClick: async ({ close, modal: m }) => {
        const slot = m.querySelector('#nb-time').value;
        if (!slot) { toast(t('book.noSlots'), 'error'); return; }
        const bundle = m.querySelector('#nb-bundle').checked;
        try {
          const r = await api.post('/bookings', {
            customer_id: Number(m.querySelector('#nb-customer').value),
            service_id: Number(m.querySelector('#nb-service').value),
            branch_id: Number(m.querySelector('#nb-branch').value),
            doctor_id: Number(m.querySelector('#nb-doctor').value) || null,
            slot_at: slot,
            bundle_sessions: bundle ? Number(m.querySelector('#nb-bundle-n').value) : 1,
            bundle_interval_months: bundle ? Number(m.querySelector('#nb-bundle-m').value) : 1,
            status: 'confirmed',
          });
          toast(r.series_count > 1
            ? (r.series_adjusted
                ? t('book.seriesCreatedAdjusted', { n: r.series_count, m: r.series_adjusted })
                : t('book.seriesCreated', { n: r.series_count }))
            : t('book.createdMsg'), 'success');
          close(); reload();
        } catch (e) { toast(e.detail || t('book.createFailed'), 'error'); }
      } },
    ],
  });

  // free slots follow the chosen branch + date + doctor
  const refreshSlots = async () => {
    const timeEl = el.querySelector('#nb-time');
    timeEl.innerHTML = `<option value="" disabled selected>…</option>`;
    try {
      const slots = await fetchSlots({
        branchId: el.querySelector('#nb-branch').value,
        date: el.querySelector('#nb-date').value,
        doctorId: el.querySelector('#nb-doctor').value,
      });
      timeEl.innerHTML = slotOptions(slots, null);
    } catch (e) {
      timeEl.innerHTML = `<option value="" disabled selected>${t('book.noSlots')}</option>`;
    }
  };
  // Prefill (not lock) the course interval from the chosen service's recommended
  // interval — the field stays user-editable and is read back on submit.
  const prefillInterval = () => {
    const svc = services.find((s) => s.id === Number(el.querySelector('#nb-service').value));
    const days = svc && svc.recommended_interval_days;
    if (!days) return; // no recommendation → keep the current value
    el.querySelector('#nb-bundle-m').value = Math.min(12, Math.max(1, Math.round(days / 30)));
  };
  // Re-scope the treatment dropdown to whichever branch is now selected, keeping
  // the current pick when it's still offered there, else falling back to the first.
  const refreshServiceOptions = () => {
    const svcEl = el.querySelector('#nb-service');
    const prevVal = svcEl.value;
    svcEl.innerHTML = serviceOptions(el.querySelector('#nb-branch').value);
    if ([...svcEl.options].some((o) => o.value === prevVal)) svcEl.value = prevVal;
    prefillInterval();
  };
  el.querySelector('#nb-branch').onchange = () => { refreshServiceOptions(); refreshSlots(); };
  ['#nb-date', '#nb-doctor'].forEach((sel) => {
    el.querySelector(sel).onchange = refreshSlots;
  });
  el.querySelector('#nb-bundle').onchange = (e) => {
    el.querySelector('#nb-bundle-fields').style.display = e.target.checked ? '' : 'none';
  };
  el.querySelector('#nb-service').onchange = prefillInterval;
  prefillInterval();
  refreshSlots();
}
