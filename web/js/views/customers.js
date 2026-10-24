/* Blinks Bright — Customers / CRM view (list, pipeline kanban, profile) */

import { api } from '../api.js';
import { store } from '../store.js';
import { router } from '../router.js';
import { icon, escapeHtml, money, toast, loadingBlock, emptyState, initials, avatarHTML,
         channelLogo, timeAgo, dateLongRaw, modal, confirmDialog,
         wireCheckAll } from '../ui.js';
import { t } from '../i18n.js';

const STAGE_LABEL = {
  new_lead: t('cust.stageNewLead'), interested: t('cust.stageInterested'), booked: t('cust.stageBooked'),
  paid: t('cust.stagePaid'), followup: t('cust.stageFollowup'), lost: t('cust.stageLost'),
};
const STAGE_BADGE = {
  new_lead: 'badge-new', interested: 'badge-interested', booked: 'badge-booked',
  paid: 'badge-paid', followup: 'badge-followup', lost: 'badge-lost',
};
const KANBAN = ['new_lead', 'interested', 'booked', 'paid', 'followup'];
const CHANNEL_ICON = { web: 'globe' };
const STAGES = Object.keys(STAGE_LABEL);
const TEMPS = ['hot', 'warm', 'cold'];
const TEMP_LABEL = { hot: t('cust.tempHot'), warm: t('cust.tempWarm'), cold: t('cust.tempCold') };
const BK_STATUS = {
  pending: t('cust.bkPending'), confirmed: t('cust.bkConfirmed'), completed: t('cust.bkCompleted'),
  cancelled: t('cust.bkCancelled'), no_show: t('cust.bkNoShow'),
  expired: t('cust.bkExpired'),
};
const PAY_STATUS = {
  pending: t('cust.payPending'), paid: t('cust.payPaid'), failed: t('cust.payFailed'), refunded: t('cust.payRefunded'),
};
const PAY_TYPE = { deposit: t('cust.payTypeDeposit'), full: t('cust.payTypeFull') };

// Module-level (not reset inside renderList) so switching the topbar's active
// branch — which remounts this whole view — never wipes the pipeline/list tab
// or any filter back to its default; only the user changing them does.
const listState = { view: 'pipeline', stage: 'all', temp: 'all', search: '' };

export default async function renderCustomers(mount, params) {
  if (params && params[0]) return renderProfile(mount, Number(params[0]));
  return renderList(mount);
}

/* ============ list / pipeline ============ */
async function renderList(mount) {
  mount.innerHTML = `<div class="view">
    <div class="view-head">
      <div><h2>${t('cust.title')}</h2><p>${t('cust.subtitle')}</p></div>
      <div class="segmented" id="cust-view">
        <button class="${listState.view === 'pipeline' ? 'active' : ''}" data-v="pipeline">${t('cust.tabPipeline')}</button>
        <button class="${listState.view === 'list' ? 'active' : ''}" data-v="list">${t('cust.tabList')}</button>
      </div>
    </div>
    <div class="row gap-2" style="flex-wrap:wrap;margin-bottom:16px;align-items:center">
      <div class="search-box" style="max-width:340px;flex:1;min-width:200px;position:relative">
        ${icon('search')}<input class="input" id="cust-search" placeholder="${t('cust.searchPlaceholder')}" value="${escapeHtml(listState.search)}" style="padding-right:36px">
        <button type="button" id="cust-search-clear" title="${t('common.clear')}"
          style="position:absolute;right:12px;top:50%;transform:translateY(-50%);width:20px;height:20px;
            display:${listState.search ? 'flex' : 'none'};align-items:center;justify-content:center;
            border:none;background:transparent;padding:0;border-radius:var(--r-sm);color:var(--muted);cursor:pointer">
          ${icon('close', 14)}</button>
      </div>
      <select class="select" id="cust-filter-stage" style="max-width:180px">
        <option value="all" ${listState.stage === 'all' ? 'selected' : ''}>${t('cust.filterAllStages')}</option>
        ${STAGES.map((s) => `<option value="${s}" ${listState.stage === s ? 'selected' : ''}>${STAGE_LABEL[s]}</option>`).join('')}
      </select>
      <select class="select" id="cust-filter-temp" style="max-width:160px">
        <option value="all" ${listState.temp === 'all' ? 'selected' : ''}>${t('cust.filterAllTemps')}</option>
        ${TEMPS.map((tp) => `<option value="${tp}" ${listState.temp === tp ? 'selected' : ''}>${TEMP_LABEL[tp]}</option>`).join('')}
      </select>
    </div>
    <div id="dup-banner"></div>
    <div id="cust-body" class="results-min">${loadingBlock()}</div>
  </div>`;

  let customers = [];
  const body = mount.querySelector('#cust-body');
  const search = mount.querySelector('#cust-search');
  const searchClear = mount.querySelector('#cust-search-clear');
  const stageFilter = mount.querySelector('#cust-filter-stage');
  const tempFilter = mount.querySelector('#cust-filter-temp');

  const params = new URLSearchParams();
  if (store.branchId && store.branchId !== 'all') params.set('branch_id', store.branchId);
  try { customers = await api.get('/customers?' + params.toString()); }
  catch (e) { body.innerHTML = emptyState('alert', t('cust.loadFailed')); return; }

  function draw() {
    const q = listState.search.trim().toLowerCase();
    const rows = customers.filter((c) =>
      (listState.stage === 'all' || c.pipeline_stage === listState.stage)
      && (listState.temp === 'all' || c.temperature === listState.temp)
      && (!q || c.name.toLowerCase().startsWith(q) || (c.phone || '').startsWith(q)));
    body.innerHTML = listState.view === 'pipeline' ? kanbanHtml(rows) : listHtml(rows);
    body.querySelectorAll('[data-cid]').forEach((el) => {
      el.onclick = () => router.go(`customers/${el.dataset.cid}`);
    });
  }
  search.oninput = () => {
    searchClear.style.display = search.value ? 'flex' : 'none';
    listState.search = search.value;
    draw();
  };
  searchClear.onclick = () => {
    search.value = '';
    searchClear.style.display = 'none';
    search.focus();
    listState.search = '';
    draw();
  };
  stageFilter.onchange = () => { listState.stage = stageFilter.value; draw(); };
  tempFilter.onchange = () => { listState.temp = tempFilter.value; draw(); };
  mount.querySelectorAll('#cust-view button').forEach((b) => {
    b.onclick = () => {
      mount.querySelectorAll('#cust-view button').forEach((x) => x.classList.toggle('active', x === b));
      listState.view = b.dataset.v;
      draw();
    };
  });
  draw();
  if (store.canManage()) loadDuplicates(mount);
}

/* ============ golden records: same-phone duplicate suggestions ============ */
async function loadDuplicates(mount) {
  let data;
  try { data = await api.get('/customers/duplicates'); } catch (e) { return; }
  const banner = mount.querySelector('#dup-banner');
  if (!banner) return;
  if (!data.groups || !data.groups.length) { banner.innerHTML = ''; return; }
  banner.innerHTML = `<div class="dup-banner">
    <span class="dup-banner-ic">${icon('users', 18)}</span>
    <div style="flex:1">
      <div class="strong">${t('cust.dupFound', { n: data.groups.length })}</div>
      <div class="muted text-sm">${t('cust.dupHint')}</div>
    </div>
    <button class="btn btn-clay btn-sm" id="dup-review">${icon('users', 14)} ${t('cust.dupReview')}</button>
  </div>`;
  banner.querySelector('#dup-review').onclick = () => dupModal(data.groups, () => renderList(mount));
}

// Richest record first (most LTV / bookings, then oldest) — nothing is ticked by
// default, so this is only a reading order: the strongest merge candidate is the
// one the eye lands on first.
function dupRanked(customers) {
  return [...customers].sort((a, b) =>
    (b.ltv - a.ltv) || (b.bookings - a.bookings) || ((a.created_at || '').localeCompare(b.created_at || '')));
}

function dupGroupBlock(g, gi) {
  const reason = g.match.includes('phone') && g.match.includes('email') ? t('cust.dupReasonBoth')
    : g.match.includes('email') ? t('cust.dupReasonEmail') : t('cust.dupReasonPhone');
  return `<div class="dup-group" data-group="${gi}">
    <div class="dup-group-head">${icon('users', 12)} ${escapeHtml(reason)}${g.shared_phone ? ` · ${escapeHtml(g.shared_phone)}` : ''}</div>
    ${dupRanked(g.customers).map((c) => `
      <label class="dup-cand" data-row="${c.id}">
        <input type="checkbox" data-dup-chk-${gi}="${c.id}">
        <span class="avatar sm">${c.avatar ? `<img src="${escapeHtml(c.avatar)}" alt="">` : escapeHtml(initials(c.name))}</span>
        <span class="dup-cand-info">
          <span class="strong">${escapeHtml(c.name)}${c.nickname ? ` <span class="muted">(${escapeHtml(c.nickname)})</span>` : ''}<span class="dup-primary-tag" hidden>${t('cust.dupPrimaryTag')}</span></span>
          <span class="muted text-xs">${channelLogo(c.channel, 12)} ${escapeHtml(c.phone || c.email || '—')} · ${STAGE_LABEL[c.pipeline_stage] || c.pipeline_stage} · ${money(c.ltv)} · ${c.bookings} ${t('cust.unitBookings')} · ${c.conversations} ${t('cust.unitChats')}</span>
        </span>
      </label>`).join('')}
    <div class="dup-group-foot">
      <div class="dup-foot-left">
        <label class="dup-all">
          <input type="checkbox" id="dup-chk-${gi}-all">
          <span>${t('cust.dupSelectAll')}</span>
        </label>
        <span class="muted text-xs">${t('cust.dupPickHint')}</span>
      </div>
      <button class="btn btn-clay btn-sm" data-merge></button>
    </div>
  </div>`;
}

function dupModal(groups, onDone) {
  let changed = false;
  const dlg = modal({
    title: t('cust.dupModalTitle', { n: groups.length }),
    wide: true,
    body: `<div class="dup-groups">${groups.map((g, gi) => dupGroupBlock(g, gi)).join('')}</div>`,
    actions: [{ label: t('common.close'), class: 'btn-ghost' }],
    onClose: () => { if (changed) onDone(); },
  });
  const root = dlg.el;
  let remaining = groups.length;
  groups.forEach((g, gi) => {
    const block = root.querySelector(`[data-group="${gi}"]`);
    const btn = block.querySelector('[data-merge]');
    const nameOf = (id) => (g.customers.find((c) => c.id === id) || {}).name || '';
    // Ticked ids in the order they were TICKED (not display order) — the first one
    // the user picks is the golden record, so the choice survives ticking more rows
    // above it. Nothing starts ticked: merging is always a deliberate pick.
    let order = [];
    const idOf = (b) => Number(b.getAttribute(`data-dup-chk-${gi}`));

    const sync = () => {
      const boxes = [...block.querySelectorAll(`[data-dup-chk-${gi}]`)];
      const checked = boxes.filter((b) => b.checked).map(idOf);
      // Reconcile here rather than in per-box handlers, so "select all" (which flips
      // several boxes at once) and merged-away rows land in the same code path.
      order = order.filter((id) => checked.includes(id))
        .concat(checked.filter((id) => !order.includes(id)));
      block.querySelectorAll('[data-row]').forEach((row) => {
        const tag = row.querySelector('.dup-primary-tag');
        if (tag) tag.hidden = Number(row.dataset.row) !== order[0];
      });
      const allBox = block.querySelector(`#dup-chk-${gi}-all`);
      if (allBox) allBox.checked = boxes.length > 0 && boxes.every((b) => b.checked);
      btn.disabled = order.length < 2;
      btn.textContent = order.length > 1 ? t('cust.mergeBtnN', { n: order.length }) : t('cust.mergeBtn');
    };
    wireCheckAll(block, `dup-chk-${gi}`, sync);
    sync();

    btn.onclick = async () => {
      if (order.length < 2) { toast(t('cust.dupPickTwo'), 'error'); return; }
      const [primaryId, ...dupIds] = order;
      const ok = await confirmDialog({
        title: t('cust.mergeBtn'),
        message: t('cust.mergeConfirm', { n: dupIds.length, name: nameOf(primaryId) }),
        confirmLabel: t('cust.mergeNow'), danger: true,
      });
      if (!ok) return;
      btn.disabled = true; btn.innerHTML = '<div class="spinner"></div>';
      try {
        await api.post('/customers/merge', { primary_id: primaryId, duplicate_ids: dupIds });
        toast(t('cust.mergeSuccess'), 'success');
        changed = true;
        // Drop only what was merged. Records left unticked stay on screen so a group
        // that holds two different people can be merged in more than one pass.
        dupIds.forEach((id) => block.querySelector(`[data-row="${id}"]`)?.remove());
        g.customers = g.customers.filter((c) => !dupIds.includes(c.id));
        if (block.querySelectorAll('[data-row]').length < 2) {
          block.remove();
          remaining -= 1;
          if (remaining <= 0) dlg.close();   // onClose refreshes the list
        } else {
          sync();
        }
      } catch (ex) {
        toast(ex.detail || t('cust.mergeFailed'), 'error');
        sync();
      }
    };
  });
}

function kanbanHtml(rows) {
  return `<div class="kanban">
    ${KANBAN.map((stage) => {
      const items = rows.filter((c) => c.pipeline_stage === stage);
      return `<div class="kan-col">
        <div class="kan-col-head">
          <span><span class="badge ${STAGE_BADGE[stage]}">${STAGE_LABEL[stage]}</span></span>
          <span class="muted">${items.length}</span>
        </div>
        <div class="kan-cards">
          ${items.slice(0, 40).map((c) => `
            <div class="kan-card" data-cid="${c.id}">
              <div class="row-between">
                <span class="strong">${escapeHtml(c.name)}</span>
                <span class="channel-dot channel-${c.channel}">${icon(CHANNEL_ICON[c.channel] || 'globe', 11)}</span>
              </div>
              <div class="muted text-xs" style="margin:3px 0 7px">${escapeHtml(c.interested || t('cust.noInterest'))}</div>
              <div class="row gap-2">
                <span class="badge badge-${c.temperature}">${TEMP_LABEL[c.temperature] || c.temperature}</span>
                <span class="muted text-xs">${t('cust.score')} ${c.lead_score}</span>
                ${c.ltv > 0 ? `<span class="spacer"></span><span class="text-xs strong">${money(c.ltv)}</span>` : ''}
              </div>
            </div>`).join('') || '<div class="muted text-xs" style="padding:8px">—</div>'}
        </div>
      </div>`;
    }).join('')}
  </div>`;
}

function listHtml(rows) {
  if (!rows.length) return `<div class="card">${emptyState('users', t('cust.noCustomers'))}</div>`;
  return `<div class="card"><table class="table">
    <thead><tr><th>${t('cust.colCustomer')}</th><th>${t('cust.colChannel')}</th><th>${t('cust.colStage')}</th><th>${t('cust.colTemp')}</th>
      <th>${t('cust.colScore')}</th><th>${t('cust.colLtv')}</th><th>${t('cust.colLastActive')}</th></tr></thead>
    <tbody>${rows.map((c) => `
      <tr class="row-click" data-cid="${c.id}">
        <td><div class="row gap-2">${avatarHTML(c.name, c.avatar, 'sm')}
          <div><div class="strong">${escapeHtml(c.name)}</div>
            <div class="muted text-xs">${escapeHtml(c.phone || c.email || '')}</div></div></div></td>
        <td>${channelLogo(c.channel, 17)}</td>
        <td><span class="badge ${STAGE_BADGE[c.pipeline_stage]}">${STAGE_LABEL[c.pipeline_stage]}</span></td>
        <td><span class="badge badge-${c.temperature}">${TEMP_LABEL[c.temperature] || c.temperature}</span></td>
        <td class="strong">${c.lead_score}</td>
        <td class="strong">${c.ltv > 0 ? money(c.ltv) : '—'}</td>
        <td class="muted text-sm">${c.last_activity_at ? timeAgo(c.last_activity_at) : '—'}</td>
      </tr>`).join('')}
    </tbody></table></div>`;
}

/* ============ customer profile ============ */
async function renderProfile(mount, cid) {
  mount.innerHTML = `<div class="view">${loadingBlock()}</div>`;
  let data, timeline = [], notes = [];
  try {
    [data, timeline, notes] = await Promise.all([
      api.get(`/customers/${cid}`),
      api.get(`/customers/${cid}/timeline`),
      api.get(`/customers/${cid}/notes`),
    ]);
  } catch (e) {
    mount.innerHTML = `<div class="view">${emptyState('alert', t('cust.notFound'))}</div>`;
    return;
  }
  const c = data.customer;
  const tempColor = { hot: 'var(--hot)', warm: 'var(--warm)', cold: 'var(--cold)' }[c.temperature];
  const prods = data.interested_services || [];

  mount.innerHTML = `<div class="view">
    <a class="btn btn-ghost btn-sm" href="#/customers" style="margin-bottom:14px">${icon('chevron-left', 14)}<span>${t('cust.allCustomers')}</span></a>
    <div class="card card-pad" style="margin-bottom:16px">
      <div class="row gap-3">
        <div style="width:52px">${avatarHTML(c.name, c.avatar, 'lg')}</div>
        <div style="flex:1">
          <div class="row gap-2"><h3>${escapeHtml(c.name)}</h3>
            ${c.nickname ? `<span class="muted" style="font-size:15px;font-weight:500">“${escapeHtml(c.nickname)}”</span>` : ''}
            <span class="badge ${STAGE_BADGE[c.pipeline_stage]}">${STAGE_LABEL[c.pipeline_stage]}</span>
            <span class="badge badge-${c.temperature}">${TEMP_LABEL[c.temperature] || c.temperature}</span></div>
          <div class="cust-meta">${[
            c.phone ? `<a class="cm-item" href="tel:${encodeURIComponent(c.phone)}"><span class="cm-ic">${icon('phone', 13)}</span>${escapeHtml(c.phone)}</a>` : '',
            c.email ? `<a class="cm-item" href="mailto:${encodeURIComponent(c.email)}"><span class="cm-ic">${icon('mail', 13)}</span>${escapeHtml(c.email)}</a>` : '',
            `<span class="cm-item"><span class="cm-ic">${icon('building', 13)}</span>${escapeHtml(data.branch_name || t('cust.noBranch'))}</span>`,
          ].filter(Boolean).join('<span class="cm-sep">·</span>')}</div>
        </div>
        <div class="row gap-2">
          <button class="btn btn-ghost btn-sm" id="cust-edit">${icon('edit', 14)}<span>${t('common.edit')}</span></button>
          ${data.conversation_id ? `<a class="btn btn-ghost btn-sm" href="#/conversations/${data.conversation_id}">${icon('chat', 14)}<span>${t('cust.openChat')}</span></a>` : ''}
          ${store.canManage() ? `<button class="btn btn-ghost btn-sm" id="cust-delete" style="color:var(--danger)">${icon('trash', 14)}<span>${t('common.delete')}</span></button>` : ''}
        </div>
      </div>
    </div>

    <div class="grid grid-3">
      <div class="span-2 col gap-4">
        <div class="card">
          <div class="card-head"><h4>${t('cust.activityTimeline')}</h4></div>
          <div class="card-body" id="timeline"></div>
        </div>
        <div class="card">
          <div class="card-head"><h4>${t('cust.bookingsPayments')}</h4></div>
          <div class="card-body" id="bk-pay"></div>
        </div>
        <div class="card">
          <div class="card-head"><h4>${t('cust.notes')}</h4></div>
          <div class="card-body">
            <div class="row gap-2" style="margin-bottom:12px">
              <input class="input" id="note-input" placeholder="${t('cust.notePlaceholder')}">
              <button class="btn btn-primary btn-sm" id="note-add">${t('common.add')}</button>
            </div>
            <div id="notes-list"></div>
          </div>
        </div>
      </div>

      <div class="col gap-4">
        <div class="card card-pad">
          <h4 style="margin-bottom:8px">${t('cust.leadScore')}</h4>
          <div class="row-between"><span class="strong" style="font-size:22px">${c.lead_score}</span>
            <span class="badge badge-${c.temperature}">${TEMP_LABEL[c.temperature] || c.temperature}</span></div>
          <div class="score-bar" style="margin-top:6px"><span style="width:${c.lead_score}%;background:${tempColor}"></span></div>
        </div>
        <div class="card card-pad">
          <h4 style="margin-bottom:10px">${t('cust.pipelineStage')}</h4>
          <select class="select" id="stage-select">
            ${Object.keys(STAGE_LABEL).map((s) => `<option value="${s}" ${s === c.pipeline_stage ? 'selected' : ''}>${STAGE_LABEL[s]}</option>`).join('')}
          </select>
        </div>
        <div class="card card-pad">
          <h4 style="margin-bottom:10px">${t('cust.productsOfInterest')}</h4>
          ${prods.length ? prods.map((p) => `
            <div class="cust-prod">
              <div class="cust-prod-ic">${p.image ? `<img src="${escapeHtml(p.image)}" alt="">` : icon('spark', 16)}</div>
              <div class="cust-prod-main">
                <div class="strong text-sm">${escapeHtml(p.name)}</div>
                <div class="muted text-xs">${escapeHtml(p.category || t('cust.serviceFallback'))}${p.price ? ' · ' + money(p.price) : ''}</div>
              </div>
              <span class="badge ${p.source === 'booked' ? 'badge-booked' : 'badge-interested'}">${p.source === 'booked' ? STAGE_LABEL.booked : STAGE_LABEL.interested}</span>
            </div>`).join('')
          : `<div class="muted text-sm">${c.interested ? escapeHtml(c.interested) : t('cust.noInterest')}</div>`}
        </div>
        <div class="card card-pad">
          <h4 style="margin-bottom:8px">${t('cust.details')}</h4>
          <div class="kv"><span class="k">${t('cust.nickname')}</span><span class="v">${escapeHtml(c.nickname || '—')}</span></div>
          <div class="kv"><span class="k">${t('cust.interested')}</span><span class="v">${escapeHtml(c.interested || '—')}</span></div>
          <div class="kv"><span class="k">${t('cust.budget')}</span><span class="v">${escapeHtml(c.budget || '—')}</span></div>
          <div class="kv"><span class="k">${t('cust.concern')}</span><span class="v">${escapeHtml(c.concern || '—')}</span></div>
          <div class="kv"><span class="k">${t('cust.lifetimeValue')}</span><span class="v strong">${money(c.ltv)}</span></div>
          <div class="kv"><span class="k">${t('cust.owner')}</span><span class="v">${escapeHtml(data.assigned_user_name || '—')}</span></div>
        </div>
        ${data.membership ? `<div class="card card-pad">
          <h4 style="margin-bottom:8px">${t('cust.membership')}</h4>
          <div class="row-between"><span class="badge badge-olive cap">${data.membership.tier}</span>
            <span class="strong">${data.membership.points} ${t('cust.pointsUnit')}</span></div>
        </div>` : ''}
        ${data.packages.length ? `<div class="card card-pad">
          <h4 style="margin-bottom:8px">${t('cust.packages')}</h4>
          ${data.packages.map((p) => `<div style="margin-bottom:8px">
            <div class="text-sm strong">${escapeHtml(p.name)}</div>
            <div class="progress" style="margin-top:4px"><span style="width:${p.total ? (p.used / p.total * 100) : 0}%"></span></div>
            <div class="muted text-xs mt-1">${t('cust.sessionsLeft', { remaining: p.remaining, total: p.total })}</div>
          </div>`).join('')}
        </div>` : ''}
      </div>
    </div>
  </div>`;

  // timeline
  mount.querySelector('#timeline').innerHTML = timeline.length ? timeline.map((t2) => `
    <div class="row gap-3" style="padding:7px 0;border-bottom:1px solid var(--border)">
      <span class="stat-ic" style="width:26px;height:26px">${icon(timelineIcon(t2.type), 13)}</span>
      <div style="flex:1"><div class="text-sm">${escapeHtml(t2.summary)}</div></div>
      <span class="muted text-xs">${t2.at ? timeAgo(t2.at) : ''}</span>
    </div>`).join('') : emptyState('clock', t('cust.noActivity'));

  // bookings & payments
  const bkPay = mount.querySelector('#bk-pay');
  if (!data.bookings.length && !data.payments.length) {
    bkPay.innerHTML = emptyState('calendar', t('cust.noBookingsPayments'));
  } else {
    bkPay.innerHTML = data.bookings.map((b) => `
      <div class="kv"><span class="k">${icon('calendar', 12)} ${escapeHtml(b.service)}</span>
        <span class="v">${dateLongRaw(b.slot_at)} · <span class="badge badge-soft">${BK_STATUS[b.status] || b.status}</span></span></div>`).join('')
      + data.payments.map((p) => `
      <div class="kv"><span class="k">${icon('card', 12)} ${t('cust.paymentRow', { type: PAY_TYPE[p.type] || p.type })}</span>
        <span class="v">${money(p.amount)} · <span class="badge ${p.status === 'paid' ? 'badge-paid' : 'badge-interested'}">${PAY_STATUS[p.status] || p.status}</span></span></div>`).join('');
  }

  // notes
  function drawNotes() {
    mount.querySelector('#notes-list').innerHTML = notes.length ? notes.map((n) => `
      <div style="padding:8px 0;border-bottom:1px solid var(--border)">
        <div class="text-sm">${escapeHtml(n.text)}</div>
        <div class="muted text-xs mt-1">${escapeHtml(n.author)} · ${n.at ? timeAgo(n.at) : ''}</div>
      </div>`).join('') : `<div class="muted text-sm">${t('cust.noNotes')}</div>`;
  }
  drawNotes();
  mount.querySelector('#note-add').onclick = async () => {
    const input = mount.querySelector('#note-input');
    const text = input.value.trim();
    if (!text) return;
    try {
      const n = await api.post(`/customers/${cid}/notes`, { text });
      notes.unshift(n);
      input.value = '';
      drawNotes();
      toast(t('cust.noteAdded'), 'success');
    } catch (e) { toast(e.detail || t('cust.actionFailed'), 'error'); }
  };

  mount.querySelector('#stage-select').onchange = async (e) => {
    try {
      await api.patch(`/customers/${cid}`, { pipeline_stage: e.target.value });
      toast(t('cust.stageUpdated'), 'success');
    } catch (ex) { toast(ex.detail || t('cust.actionFailed'), 'error'); }
  };

  mount.querySelector('#cust-edit').onclick = () => editCustomer(mount, cid, c);

  const delBtn = mount.querySelector('#cust-delete');
  if (delBtn) delBtn.onclick = async () => {
    const ok = await confirmDialog({
      title: t('cust.deleteTitle', { name: c.name }),
      message: t('cust.deleteMsg'),
      confirmLabel: t('cust.deleteEverything'), danger: true,
    });
    if (!ok) return;
    delBtn.disabled = true;
    try {
      await api.del(`/customers/${cid}`);
      toast(t('cust.deleteSuccess'), 'success');
      router.go('customers');
    } catch (e) {
      toast(e.detail || t('common.deleteFailed'), 'error');
      delBtn.disabled = false;
    }
  };
}

function editCustomer(mount, cid, c) {
  modal({
    title: t('cust.editTitle'),
    body: `
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:var(--sp-3)">
        ${avatarHTML(c.name, c.avatar, 'lg')}
        <div>
          <div class="strong" style="font-size:15px">${escapeHtml(c.name)}${c.nickname ? ` <span class="muted">“${escapeHtml(c.nickname)}”</span>` : ''}</div>
          <div class="muted" style="font-size:13px;display:flex;align-items:center;gap:6px">${channelLogo(c.channel, 14)}${escapeHtml(c.channel || 'web')}</div>
        </div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:var(--sp-3)">
        <div class="field"><label>${t('common.name')}</label>
          <input class="input" id="ec-name" value="${escapeHtml(c.name)}" autofocus></div>
        <div class="field"><label>${t('cust.nickname')} <span class="muted">${t('common.optional')}</span></label>
          <input class="input" id="ec-nick" value="${escapeHtml(c.nickname || '')}" placeholder="${t('cust.nickPlaceholder')}"></div>
        <div class="field"><label>${t('cust.phone')}</label>
          <input class="input" id="ec-phone" value="${escapeHtml(c.phone || '')}" placeholder="08x-xxx-xxxx"></div>
        <div class="field"><label>${t('cust.email')}</label>
          <input class="input" id="ec-email" value="${escapeHtml(c.email || '')}" placeholder="name@email.com"></div>
      </div>
      <div class="field"><label>${t('cust.interestedIn')}</label>
        <input class="input" id="ec-interested" value="${escapeHtml(c.interested || '')}" placeholder="${t('cust.interestedPlaceholder')}"></div>
      <div class="field"><label>${t('cust.budget')}</label>
        <input class="input" id="ec-budget" value="${escapeHtml(c.budget || '')}" placeholder="${t('cust.budgetPlaceholder')}"></div>
      <div class="field"><label>${t('cust.concern')}</label>
        <textarea class="textarea" id="ec-concern" rows="2"
          placeholder="${t('cust.concernPlaceholder')}">${escapeHtml(c.concern || '')}</textarea></div>`,
    actions: [
      { label: t('common.cancel'), class: 'btn-ghost' },
      { label: t('cust.saveChanges'), class: 'btn-primary', keepOpen: true,
        onClick: async ({ close, modal: mEl }) => {
          const name = mEl.querySelector('#ec-name').value.trim();
          if (!name) { toast(t('cust.enterName'), 'error'); return; }
          const btn = mEl.querySelector('.modal-foot .btn-primary');
          btn.disabled = true;
          btn.innerHTML = '<div class="spinner"></div>';
          try {
            await api.patch(`/customers/${cid}`, {
              name,
              nickname: mEl.querySelector('#ec-nick').value.trim(),
              phone: mEl.querySelector('#ec-phone').value.trim(),
              email: mEl.querySelector('#ec-email').value.trim(),
              interested: mEl.querySelector('#ec-interested').value.trim(),
              budget: mEl.querySelector('#ec-budget').value.trim(),
              concern: mEl.querySelector('#ec-concern').value.trim(),
            });
            toast(t('cust.customerUpdated'), 'success');
            close();
            renderProfile(mount, cid);
          } catch (ex) {
            toast(ex.detail || t('cust.saveChangesFailed'), 'error');
            btn.disabled = false;
            btn.textContent = t('cust.saveChanges');
          }
        } },
    ],
  });
}

function timelineIcon(type) {
  return { booking: 'calendar', payment: 'card', status: 'arrow-right',
           note: 'edit', message: 'chat', system: 'spark' }[type] || 'dot';
}
