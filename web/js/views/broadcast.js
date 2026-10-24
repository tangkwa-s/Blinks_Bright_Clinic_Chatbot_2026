/* Blinks Bright — Broadcast / campaigns view */

import { api } from '../api.js';
import { store } from '../store.js';
import { icon, escapeHtml, num, toast, modal, confirmDialog, loadingBlock, emptyState,
         dateShort, debounce, channelLogo, avatarHTML, initials,
         isEveryBranch, branchSummaryText, branchCheckboxListHtml, wireCheckAll } from '../ui.js';
import { t } from '../i18n.js';

const STAGES = [['', t('bcast.stageAny')], ['new_lead', t('bcast.stageNewLead')], ['interested', t('bcast.stageInterested')],
                ['booked', t('bcast.stageBooked')], ['paid', t('bcast.stagePaid')], ['followup', t('bcast.stageFollowup')]];
const TEMPS = [['', t('bcast.tempAny')], ['hot', t('bcast.tempHot')], ['warm', t('bcast.tempWarm')], ['cold', t('bcast.tempCold')]];
const CHANNELS = [['all', t('bcast.chAll')], ['web', t('bcast.chWeb')]];
const STAGE_LABEL = { new_lead: t('bcast.stageNewLead'), interested: t('bcast.stageInterested'), booked: t('bcast.stageBooked'), paid: t('bcast.stagePaid'), followup: t('bcast.stageFollowup') };
const STATUS_LABEL = { draft: t('bcast.statusDraft'), scheduled: t('bcast.statusScheduled'), sent: t('bcast.statusSent') };

function dtFmt(iso) {
  const d = new Date(iso);
  return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' })
    + ' ' + d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
}

// <input type="datetime-local"> wants "YYYY-MM-DDTHH:MM" in the clinic's own
// time (Asia/Bangkok, UTC+7) — same offset trick bookings.js uses for its
// date picker — so editing a scheduled campaign shows its actual send time.
function toScheduleInput(iso) {
  if (!iso) return '';
  return new Date(new Date(iso).getTime() + 7 * 3600000).toISOString().slice(0, 16);
}

// Module-level (not reset inside renderBroadcast) so switching the topbar's
// active branch — which remounts this whole view — never wipes the search
// text back to empty; only the user clearing it does.
let q = '';

export default async function renderBroadcast(mount) {
  const canEdit = store.canManage() || store.isRole('marketing');
  mount.innerHTML = `<div class="view">
    <div class="view-head">
      <div><h2>${t('bcast.title')}</h2><p>${t('bcast.subtitle')}</p></div>
    </div>
    <div class="row gap-2" style="justify-content:flex-end;margin-bottom:16px">
      <div class="search-box" style="max-width:280px;position:relative">${icon('search', 16)}
        <input class="input" id="camp-search" placeholder="${t('bcast.searchCampaigns')}" value="${escapeHtml(q)}" style="padding-right:36px">
        <button type="button" id="camp-search-clear" title="${t('common.clear')}"
          style="position:absolute;right:12px;top:50%;transform:translateY(-50%);width:20px;height:20px;
            display:${q ? 'flex' : 'none'};align-items:center;justify-content:center;
            border:none;background:transparent;padding:0;border-radius:var(--r-sm);color:var(--muted);cursor:pointer">
          ${icon('close', 14)}</button>
      </div>
      ${canEdit ? `<button class="btn btn-primary" id="new-camp">${icon('broadcast', 16)}<span>${t('bcast.newCampaign')}</span></button>` : ''}
    </div>
    <div id="camp-body" class="results-min-grid">${loadingBlock()}</div>
  </div>`;

  const body = mount.querySelector('#camp-body');
  const searchInput = mount.querySelector('#camp-search');
  const searchClear = mount.querySelector('#camp-search-clear');
  if (canEdit) mount.querySelector('#new-camp').onclick = () => campaignModal(load);

  let allRows = [];

  const debouncedRenderRows = debounce(() => renderRows(), 150);
  searchInput.oninput = () => {
    searchClear.style.display = searchInput.value ? 'flex' : 'none';
    q = searchInput.value.trim().toLowerCase();
    debouncedRenderRows();
  };
  searchClear.onclick = () => {
    searchInput.value = '';
    searchClear.style.display = 'none';
    searchInput.focus();
    q = '';
    renderRows();
  };

  load();

  async function load() {
    body.innerHTML = loadingBlock();
    try { allRows = await api.get('/campaigns'); }
    catch (e) { body.innerHTML = emptyState('alert', t('bcast.loadFailed')); return; }
    renderRows();
  }

  function renderRows() {
    if (!allRows.length) {
      body.innerHTML = `<div class="card">${emptyState('broadcast', t('bcast.emptyTitle'),
        t('bcast.emptySub'))}</div>`;
      return;
    }
    let rows = q ? allRows.filter((c) => (c.name || '').toLowerCase().includes(q)) : allRows;
    // No in-page branch filter — the topbar's own branch selector narrows the
    // list, same convention as Treatments/Knowledge/Retention: a campaign with
    // no branch scope reaches every branch and always shows.
    if (store.branchId && store.branchId !== 'all') {
      const bid = Number(store.branchId);
      rows = rows.filter((c) => {
        const ids = (c.audience && c.audience.branch_ids) || [];
        return !ids.length || ids.includes(bid);
      });
    }
    if (!rows.length) {
      body.innerHTML = `<div class="card span-2">${emptyState('broadcast', t('bcast.noMatches'),
        t('bcast.tryAnotherSearch'))}</div>`;
      return;
    }
    const editable = (c) => canEdit && c.status !== 'sent';
    body.innerHTML = `<div class="grid grid-2">${rows.map((c) => `
      <div class="card card-pad" data-cid="${c.id}" style="cursor:${editable(c) ? 'pointer' : 'default'}">
        <div class="row-between">
          <span class="strong">${escapeHtml(c.name)}</span>
          <span class="badge ${c.status === 'sent' ? 'badge-paid' : c.status === 'scheduled' ? 'badge-interested' : 'badge-soft'}">${STATUS_LABEL[c.status] || c.status}</span>
        </div>
        <div class="row gap-1" style="margin:6px 0 2px;align-items:center">
          ${channelLogo(c.channel || 'all', 15)}
          <span class="muted text-xs">${escapeHtml((CHANNELS.find((x) => x[0] === c.channel) || [, c.channel || t('bcast.chAll')])[1])}
            ${c.created_at ? '· ' + dateShort(c.created_at) : ''}</span>
        </div>
        ${c.status === 'scheduled' && c.scheduled_at
          ? `<div class="text-xs" style="color:var(--clay);margin-top:4px">${icon('clock', 12)} ${t('bcast.autoSendAt', { when: dtFmt(c.scheduled_at) })}</div>` : ''}
        <div class="muted text-sm" style="margin:8px 0">${escapeHtml(c.message || t('bcast.noMessage'))}</div>
        <div class="divider"></div>
        <div class="row gap-4" style="align-items:flex-end">
          <div><div class="muted text-xs">${t('bcast.audience')}</div><div class="strong">${num(c.audience_count)}</div></div>
          <div><div class="muted text-xs">${t('bcast.metricSent')}</div><div class="strong">${num(c.sent_count)}</div></div>
          <div><div class="muted text-xs">${t('bcast.metricResponded')}</div><div class="strong">${num(c.responded_count || 0)} <span class="muted text-xs">(${c.response_rate || 0}%)</span></div></div>
          <span class="spacer"></span>
          <div class="row gap-1">
            <button class="btn btn-ghost btn-sm" data-aud="${c.id}">${icon('users', 14)}<span>${t('bcast.audience')}</span></button>
            ${c.status === 'sent' ? `<button class="btn btn-ghost btn-sm" data-log="${c.id}">${icon('clock', 14)}<span>${t('bcast.logs')}</span></button>` : ''}
            ${canEdit ? `<button class="btn btn-ghost btn-sm" data-reuse="${c.id}" title="${t('bcast.reuseTip')}">${icon('refresh', 14)}<span>${t('bcast.reuse')}</span></button>` : ''}
            ${(c.status === 'draft' || c.status === 'scheduled') && canEdit
              ? `<button class="btn btn-clay btn-sm" data-send="${c.id}">${icon('send', 14)}<span>${c.status === 'scheduled' ? t('bcast.sendNow') : t('bcast.send')}</span></button>`
              : ''}
          </div>
        </div>
      </div>`).join('')}</div>`;

    const byId = (id) => rows.find((c) => String(c.id) === String(id));

    body.querySelectorAll('[data-cid]').forEach((card) => {
      const c = byId(card.dataset.cid);
      if (!editable(c)) return;
      card.onclick = (e) => {
        if (e.target.closest('button')) return;   // the row's own action buttons handle themselves
        campaignModal(load, c, true);
      };
    });
    body.querySelectorAll('[data-aud]').forEach((btn) => {
      btn.onclick = () => audienceModal(byId(btn.dataset.aud));
    });
    body.querySelectorAll('[data-reuse]').forEach((btn) => {
      btn.onclick = () => campaignModal(load, byId(btn.dataset.reuse));
    });
    body.querySelectorAll('[data-send]').forEach((btn) => {
      btn.onclick = async () => {
        btn.disabled = true;
        try {
          const r = await api.post(`/campaigns/${btn.dataset.send}/send`);
          const d = r.delivered || {};
          toast(t('bcast.sentToast', { n: d.sent ?? r.sent_count })
            + (d.failed ? ` · ${t('bcast.failedCount', { n: d.failed })}` : ''), 'success');
          load();
        } catch (e) { toast(e.detail || t('bcast.sendFailed'), 'error'); btn.disabled = false; }
      };
    });
    body.querySelectorAll('[data-log]').forEach((btn) => {
      btn.onclick = () => logModal(byId(btn.dataset.log));
    });
  }
}

/* ---------------- delivery log (who got it, on which channel, status) ---------------- */
async function logModal(c) {
  const m = modal({
    title: `${t('bcast.deliveryLog')} · ${c.name}`,
    wide: true,
    body: `<div id="log-body">${loadingBlock()}</div>`,
    actions: [{ label: t('common.close'), class: 'btn-ghost' }],
  });
  try {
    const r = await api.get(`/campaigns/${c.id}/log`);
    const box = m.el.querySelector('#log-body');
    if (!r.log.length) { box.innerHTML = emptyState('clock', t('bcast.noLog')); return; }
    const badge = (s) => s === 'delivered' ? 'badge-paid' : s === 'failed' ? 'badge-lost' : 'badge-soft';
    const stxt = { delivered: t('bcast.dlvDelivered'), failed: t('bcast.dlvFailed'), unreachable: t('bcast.dlvUnreachable') };
    box.innerHTML = `
      <div class="muted text-sm" style="margin-bottom:8px">${t('bcast.logSummary', { sent: `<strong>${r.sent}</strong>`, audience: r.audience })}
        · ${t('bcast.logResponded', { n: r.responded ?? 0 })}</div>
      <div style="max-height:54vh;overflow:auto"><table class="table">
        <thead><tr><th>${t('bcast.colCustomer')}</th><th>${t('bcast.channel')}</th><th>${t('common.status')}</th><th>${t('bcast.metricResponded')}</th><th>${t('bcast.colTime')}</th></tr></thead>
        <tbody>${r.log.map((l) => `<tr>
          <td class="strong">${escapeHtml(l.name)}</td>
          <td><div class="row gap-1" style="align-items:center">${channelLogo(l.channel, 14)}<span class="text-xs">${escapeHtml(l.channel)}</span></div></td>
          <td><span class="badge ${badge(l.status)}">${stxt[l.status] || l.status}</span></td>
          <td>${l.responded ? `<span class="badge badge-paid">${t('bcast.repliedYes')}</span>` : '<span class="muted">—</span>'}</td>
          <td class="muted text-xs">${l.at ? dtFmt(l.at) : ''}</td>
        </tr>`).join('')}</tbody></table></div>`;
  } catch (e) {
    m.el.querySelector('#log-body').innerHTML = emptyState('alert', t('bcast.logLoadFailed'));
  }
}

/* ---------------- audience detail (who is in this campaign) ---------------- */
function audienceRowHTML(c) {
  const reach = c.reachable
    ? ''
    : `<span class="badge badge-soft" title="${t('bcast.unreachableTip', { channel: c.channel })}">${t('bcast.unreachable')}</span>`;
  return `<div class="row gap-2" style="padding:8px 4px;border-bottom:1px solid var(--border)">
    ${avatarHTML(c.name, c.avatar, 'sm')}
    <div style="flex:1;min-width:0">
      <div class="strong truncate">${escapeHtml(c.name || t('bcast.unknown'))}</div>
      <div class="muted text-xs">${escapeHtml(STAGE_LABEL[c.pipeline_stage] || c.pipeline_stage || '')}
        ${c.temperature ? '· ' + escapeHtml(c.temperature) : ''}</div>
    </div>
    ${channelLogo(c.channel, 16)}
    ${reach}
  </div>`;
}

async function audienceModal(c) {
  const m = modal({
    title: `${t('bcast.audience')} · ${c.name}`,
    wide: true,
    body: `<div id="aud-list">${loadingBlock()}</div>`,
    actions: [{ label: t('common.close'), class: 'btn-ghost' }],
  });
  try {
    const r = await api.get(`/campaigns/${c.id}/audience`);
    const list = m.el.querySelector('#aud-list');
    if (!r.customers.length) {
      list.innerHTML = emptyState('users', t('bcast.noMatch'), t('bcast.noMatchSub'));
      return;
    }
    list.innerHTML = `
      <div class="muted text-sm" style="margin-bottom:8px">
        ${t('bcast.audienceSummary', { count: r.count, reachable: `<strong>${r.reachable}</strong>` })}</div>
      <div style="max-height:52vh;overflow:auto">${r.customers.map(audienceRowHTML).join('')}</div>`;
  } catch (e) {
    m.el.querySelector('#aud-list').innerHTML = emptyState('alert', t('bcast.audienceLoadFailed'));
  }
}

/* ---------------- new / reuse / edit campaign ---------------- */
function campaignModal(reload, preset, isEdit) {
  const p = preset || {};
  const a = p.audience || {};
  const sel = (opts, cur) => opts.map(([v, l]) =>
    `<option value="${v}" ${String(cur || '') === v ? 'selected' : ''}>${l}</option>`).join('');
  const name = isEdit ? (p.name || '') : (p.name ? `${p.name} ${t('bcast.copySuffix')}` : '');
  // Default branches checked: an explicit scope carried over from a reused
  // campaign wins; otherwise fall back to the topbar's current branch (so
  // creating while scoped to one branch defaults the campaign to it too) —
  // same convention as the Treatments modal.
  const initialBranchIds = (Array.isArray(a.branch_ids) && a.branch_ids.length) ? a.branch_ids
    : ((store.branchId && store.branchId !== 'all') ? [Number(store.branchId)] : []);
  const branchField = store.branches.length > 1 ? `
    <div class="field"><label>${t('menu.branch')}</label>
      <details class="tx-branch-msel" id="c-branch-msel">
        <summary class="input"><span class="tx-branch-summary-text" id="c-branch-summary">${
          escapeHtml(branchSummaryText(initialBranchIds))}</span></summary>
        <div class="tx-branch-msel-panel">${branchCheckboxListHtml('c-branch-chk', initialBranchIds)}</div>
      </details>
    </div>` : '';

  modal({
    title: isEdit ? t('bcast.editCampaign') : (preset ? t('bcast.reuseCampaign') : t('bcast.newCampaign')),
    wide: true,
    body: `
      <div class="field"><label>${t('bcast.campaignName')}</label>
        <input class="input" id="c-name" placeholder="${t('bcast.campaignNamePh')}" value="${escapeHtml(name)}"></div>
      <div class="grid grid-3">
        <div class="field"><label>${t('bcast.fieldStage')}</label>
          <select class="select" id="c-stage">${sel(STAGES, a.stage)}</select></div>
        <div class="field"><label>${t('bcast.fieldTemp')}</label>
          <select class="select" id="c-temp">${sel(TEMPS, a.temperature)}</select></div>
        <div class="field"><label>${t('bcast.fieldInactive')}</label>
          <input class="input" type="number" id="c-inactive" placeholder="${t('common.optional')}" value="${escapeHtml(a.inactive_days || '')}"></div>
      </div>
      ${branchField}
      <div class="grid grid-2">
        <div class="field"><label>${t('bcast.channel')}</label>
          <select class="select" id="c-channel">${sel(CHANNELS, p.channel || a.channel || 'all')}</select></div>
        <div class="field"><label>${t('bcast.scheduleSend')} <span class="muted">${t('bcast.scheduleHint')}</span></label>
          <input class="input" type="datetime-local" id="c-schedule" value="${escapeHtml(isEdit ? toScheduleInput(p.scheduled_at) : '')}"></div>
      </div>
      <div class="field"><label>${t('bcast.message')}</label>
        <textarea class="textarea" id="c-message" rows="3" placeholder="${t('bcast.messagePh')}">${escapeHtml(p.message || '')}</textarea></div>
      <div class="card-pad" style="background:var(--primary-soft);border-radius:var(--r-md)">
        <div class="row-between">
          <span>${icon('users', 14)} <span id="c-preview">${t('bcast.audience')}: —</span></span>
          <button type="button" class="btn btn-ghost btn-sm" id="c-viewlist">${t('bcast.viewList')}</button>
        </div>
        <div id="c-list" hidden style="margin-top:10px;max-height:32vh;overflow:auto"></div>
      </div>`,
    actions: [
      ...(isEdit ? [{ label: t('common.delete'), class: 'btn-danger mfoot-left', keepOpen: true,
        onClick: async ({ close }) => {
          const ok = await confirmDialog({
            title: t('bcast.deleteConfirmTitle'),
            message: t('bcast.deleteConfirmMsg', { name: p.name }),
            confirmLabel: t('common.delete'), danger: true });
          if (!ok) return;
          try {
            await api.del(`/campaigns/${p.id}`);
            toast(t('bcast.deleted'), 'success');
            close(); reload();
          } catch (ex) { toast(ex.detail || t('common.deleteFailed'), 'error'); }
        } }] : []),
      { label: t('common.cancel'), class: 'btn-ghost' },
      { label: isEdit ? t('common.save') : (preset ? t('bcast.createFromThis') : t('bcast.createCampaign')),
        class: 'btn-primary', keepOpen: true, onClick: async ({ close, modal: m }) => {
        const nm = m.querySelector('#c-name').value.trim();
        if (!nm) return toast(t('bcast.nameRequired'), 'error');
        const payload = {
          name: nm,
          channel: m.querySelector('#c-channel').value,
          message: m.querySelector('#c-message').value.trim(),
          scheduled_at: m.querySelector('#c-schedule').value || '',
          audience: audienceFilter(m),
        };
        try {
          if (isEdit) await api.patch(`/campaigns/${p.id}`, payload);
          else await api.post('/campaigns', payload);
          toast(isEdit ? t('common.saved') : t('bcast.created'), 'success'); close(); reload();
        } catch (e) { toast(e.detail || t('bcast.failed'), 'error'); }
      } },
    ],
  });

  // live audience preview + recipient list
  setTimeout(() => {
    const m = document.querySelector('.modal');
    if (!m) return;
    let lastCustomers = [];
    const listBox = m.querySelector('#c-list');
    const viewBtn = m.querySelector('#c-viewlist');
    const renderList = () => {
      listBox.innerHTML = lastCustomers.length
        ? lastCustomers.map(audienceRowHTML).join('')
        : `<div class="muted text-sm">${t('bcast.noMatchSegment')}</div>`;
    };
    viewBtn.onclick = () => {
      listBox.hidden = !listBox.hidden;
      viewBtn.textContent = listBox.hidden ? t('bcast.viewList') : t('bcast.hideList');
      if (!listBox.hidden) renderList();
    };
    const preview = debounce(async () => {
      const f = audienceFilter(m);
      const q = new URLSearchParams();
      if (f.stage) q.set('stage', f.stage);
      if (f.temperature) q.set('temperature', f.temperature);
      if (f.inactive_days) q.set('inactive_days', f.inactive_days);
      if (f.channel) q.set('channel', f.channel);
      if (f.branch_ids) f.branch_ids.forEach((id) => q.append('branch_ids', id));
      try {
        const r = await api.get('/campaigns/preview?' + q.toString());
        m.querySelector('#c-preview').textContent =
          t('bcast.previewSummary', { count: r.count, reachable: r.reachable });
        lastCustomers = r.customers || [];
        if (!listBox.hidden) renderList();
      } catch (e) { /* ignore */ }
    }, 250);
    ['#c-stage', '#c-temp', '#c-inactive', '#c-channel'].forEach((s) => {
      const el = m.querySelector(s);
      if (el) { el.onchange = preview; el.oninput = preview; }
    });
    const branchMsel = m.querySelector('#c-branch-msel');
    if (branchMsel) {
      wireCheckAll(branchMsel, 'c-branch-chk', () => {
        const checked = [...branchMsel.querySelectorAll('[data-c-branch-chk]:checked')]
          .map((c) => Number(c.dataset.cBranchChk));
        const summaryEl = branchMsel.querySelector('#c-branch-summary');
        if (summaryEl) summaryEl.textContent = branchSummaryText(checked);
        preview();
      });
    }
    preview();
  }, 50);
}

function audienceFilter(m) {
  const f = {};
  const stage = m.querySelector('#c-stage').value;
  const temp = m.querySelector('#c-temp').value;
  const inactive = m.querySelector('#c-inactive').value;
  const channel = m.querySelector('#c-channel').value;
  if (stage) f.stage = stage;
  if (temp) f.temperature = temp;
  if (inactive) f.inactive_days = Number(inactive);
  if (channel && channel !== 'all') f.channel = channel;
  const branchBoxes = [...m.querySelectorAll('[data-c-branch-chk]:checked')];
  if (branchBoxes.length) {
    const ids = branchBoxes.map((c) => Number(c.dataset.cBranchChk));
    if (!isEveryBranch(ids)) f.branch_ids = ids;
  }
  return f;
}
