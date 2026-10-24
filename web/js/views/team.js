/* Blinks Bright — Doctors & Staff (team per branch) + per-branch booking schedule */

import { api } from '../api.js';
import { store } from '../store.js';
import { icon, escapeHtml, initials, toast, modal, confirmDialog, loadingBlock, emptyState,
         dateLongRaw, timeOfRaw, timeAgo, avatarHTML, avatarField, bindAvatarPicker, debounce } from '../ui.js';
import { t } from '../i18n.js';

/* Clinical roles only — this roster is separate from the login accounts in Settings → Team. */
const ROLE_LABEL = {
  doctor: t('role.doctor'), nurse: t('team.roleNurse'), therapist: t('team.roleTherapist'), staff: t('team.roleStaff'),
};
const ROLE_BADGE = {
  doctor: 'badge-paid', nurse: 'badge-booked', therapist: 'badge-interested', staff: 'badge-soft',
};
const BK_BADGE = {
  pending: 'badge-interested', confirmed: 'badge-booked', completed: 'badge-paid',
  cancelled: 'badge-lost', no_show: 'badge-danger', expired: 'badge-soft',
};
const BK_LABEL = {
  pending: t('team.bkPending'), confirmed: t('team.bkConfirmed'), completed: t('team.bkCompleted'),
  cancelled: t('team.bkCancelled'), no_show: t('team.bkNoShow'),
  expired: t('team.bkExpired'),
};
// See bookings.js: 'expired' is set by the hold clock, never by a person.
const EDITABLE_STATUSES = ['pending', 'confirmed', 'completed', 'cancelled', 'no_show'];

const ROLE_FILTERS = ['all', 'doctor', 'nurse', 'therapist', 'staff'];

// schedBranch mirrors the header branch picker (null = all branches) — the schedule
// has no branch filter of its own, so there is only ever one place to change it.
const ST = { staff: [], branches: [], tab: 'team', roleFilter: 'all', search: '', schedBranch: null, schedDate: todayStr() };

function headerBranch() {
  return (store.branchId && store.branchId !== 'all') ? Number(store.branchId) : null;
}

// Local-date helpers (avoid toISOString(), which shifts the day in +tz like Asia/Bangkok)
function ymd(dt) {
  const p = (n) => String(n).padStart(2, '0');
  return `${dt.getFullYear()}-${p(dt.getMonth() + 1)}-${p(dt.getDate())}`;
}
function todayStr() { return ymd(new Date()); }
function shiftDate(d, days) {
  const [y, m, dd] = d.split('-').map(Number);
  return ymd(new Date(y, m - 1, dd + days));   // constructs in local time; day overflow rolls months
}

export default async function renderTeam(mount) {
  mount.innerHTML = `<div class="view">
    <div class="view-head">
      <div><h2>${t('team.title')}</h2>
        <p>${t('team.subtitle')}</p></div>
      <div class="seg-tabs" id="tm-tabs">
        <button class="seg ${ST.tab === 'team' ? 'active' : ''}" data-tab="team">${icon('stethoscope', 14)} ${t('team.tabTeam')}</button>
        <button class="seg ${ST.tab === 'schedule' ? 'active' : ''}" data-tab="schedule">${icon('calendar', 14)} ${t('team.tabSchedule')}</button>
      </div>
    </div>
    <div id="tm-body">${loadingBlock()}</div>
  </div>`;

  const body = mount.querySelector('#tm-body');
  mount.querySelectorAll('#tm-tabs .seg').forEach((b) => {
    b.onclick = () => {
      mount.querySelectorAll('#tm-tabs .seg').forEach((x) => x.classList.toggle('active', x === b));
      ST.tab = b.dataset.tab;
      draw(body);
    };
  });

  try {
    [ST.staff, ST.branches] = await Promise.all([api.get('/team-members'), api.get('/branches')]);
  } catch (e) {
    body.innerHTML = emptyState('alert', t('common.loadFailed'));
    return;
  }
  ST.schedBranch = headerBranch();
  draw(body);
}

function draw(body) {
  if (ST.tab === 'team') renderTeamTab(body);
  else renderScheduleTab(body);
}

/* ------------------------------- Team tab ------------------------------- */
function renderTeamTab(body) {
  const canManage = store.canManage();

  body.innerHTML = `
    <div class="row-between" style="margin-bottom:14px;flex-wrap:wrap;gap:10px">
      <div class="segmented" id="tm-role-filter">
        ${ROLE_FILTERS.map((r) => `<button class="${ST.roleFilter === r ? 'active' : ''}" data-role="${r}">${
          r === 'all' ? t('common.all') : ROLE_LABEL[r]}</button>`).join('')}
      </div>
      <div class="row gap-2" style="flex-wrap:wrap;align-items:center">
        <div class="search-box" style="max-width:280px;flex:1;min-width:200px;position:relative">
          ${icon('search')}<input class="input" id="tm-search" placeholder="${t('team.searchPlaceholder')}"
            value="${escapeHtml(ST.search)}" style="padding-right:36px">
          <button type="button" id="tm-search-clear" title="${t('common.clear')}"
            style="position:absolute;right:12px;top:50%;transform:translateY(-50%);width:20px;height:20px;
              display:${ST.search ? 'flex' : 'none'};align-items:center;justify-content:center;
              border:none;background:transparent;padding:0;border-radius:var(--r-sm);color:var(--muted);cursor:pointer">
            ${icon('close', 14)}</button>
        </div>
        ${canManage ? `<button class="btn btn-primary" id="tm-add">${icon('plus', 16)}<span>${t('team.addStaff')}</span></button>` : ''}
      </div>
    </div>
    <div class="col gap-4 results-min" id="tm-results"></div>`;

  drawResults(body);

  body.querySelectorAll('#tm-role-filter button').forEach((b) => {
    b.onclick = () => {
      body.querySelectorAll('#tm-role-filter button').forEach((x) => x.classList.toggle('active', x === b));
      ST.roleFilter = b.dataset.role;
      drawResults(body);
    };
  });

  const searchInput = body.querySelector('#tm-search');
  const searchClear = body.querySelector('#tm-search-clear');
  const debouncedSearch = debounce(() => { ST.search = searchInput.value.trim(); drawResults(body); }, 180);
  searchInput.oninput = () => {
    searchClear.style.display = searchInput.value ? 'flex' : 'none';
    debouncedSearch();
  };
  searchClear.onclick = () => {
    searchInput.value = '';
    searchClear.style.display = 'none';
    searchInput.focus();
    ST.search = '';
    drawResults(body);
  };

  if (canManage) body.querySelector('#tm-add').onclick = () => staffModal(null, body);
}

function drawResults(body) {
  const canManage = store.canManage();
  const q = ST.search.trim().toLowerCase();
  const filtering = !!q || ST.roleFilter !== 'all';
  const filtered = ST.staff
    .filter((s) => ST.roleFilter === 'all' || s.role === ST.roleFilter)
    .filter((s) => !q || s.name.toLowerCase().includes(q) || (s.phone || '').includes(q));

  const results = body.querySelector('#tm-results');
  if (filtering && !filtered.length) {
    results.innerHTML = `<div class="card">${emptyState('spark', t('team.noMatches'), t('team.noMatchesSub'))}</div>`;
    return;
  }

  const groups = new Map();
  ST.branches.forEach((b) => groups.set(b.id, []));
  groups.set(null, []);
  filtered.forEach((s) => {
    const key = groups.has(s.branch_id) ? s.branch_id : null;
    groups.get(key).push(s);
  });

  const section = (bid, list) => {
    const br = ST.branches.find((b) => b.id === bid);
    const title = br ? escapeHtml(br.name) : t('team.noBranch');
    const docs = list.filter((s) => s.role === 'doctor').length;
    return `<div class="card tm-branch">
      <div class="card-head">
        <h4>${icon('building', 15)} ${title}</h4>
        <span class="muted text-sm">${t('team.peopleCount', { count: list.length })}${docs ? ` · ${t('team.doctorCount', { count: docs })}` : ''}</span>
      </div>
      <div class="card-body">
        ${list.length
          ? list.map(staffRow).join('')
          : `<div class="muted text-sm" style="padding:6px 0">${t('team.noStaffInBranch')}</div>`}
      </div>
    </div>`;
  };

  // Honour the global branch filter (top bar): one branch when a specific one is
  // selected, every branch (+ unassigned) when "All branches".
  const selBid = store.branchId;
  const oneBranch = selBid && selBid !== 'all';
  const shown = oneBranch
    ? ST.branches.filter((b) => String(b.id) === String(selBid))
    : ST.branches;
  // While searching/role-filtering, only show branches that actually have a match —
  // an unmatched branch would otherwise render its "no staff in this branch" placeholder,
  // which is misleading (that branch DOES have staff, they just don't match the filter).
  const shownWithData = filtering ? shown.filter((b) => (groups.get(b.id) || []).length) : shown;

  results.innerHTML = `
    ${shownWithData.map((b) => section(b.id, groups.get(b.id) || [])).join('')}
    ${!oneBranch && groups.get(null).length ? section(null, groups.get(null)) : ''}`;

  if (canManage) {
    results.querySelectorAll('[data-staff]').forEach((el) => {
      el.onclick = () => {
        const s = ST.staff.find((x) => x.id === Number(el.dataset.staff));
        if (s) staffModal(s, body);
      };
    });
  }
}

function staffRow(s) {
  const can = store.canManage();
  const inactive = s.active === false;
  return `<div class="tm-row ${can ? 'row-click' : ''}" ${can ? `data-staff="${s.id}"` : ''}>
    ${avatarHTML(s.name, s.avatar, 'sm')}
    <div class="tm-row-main">
      <div class="row gap-2">
        <span class="strong">${escapeHtml(s.name)}</span>
        <span class="badge ${ROLE_BADGE[s.role] || 'badge-soft'}">${ROLE_LABEL[s.role] || s.role}</span>
        ${inactive ? `<span class="badge badge-lost">${t('common.inactive')}</span>` : ''}
      </div>
      <div class="muted text-sm">${escapeHtml(s.title || '—')}${s.phone ? ' · ' + escapeHtml(s.phone) : ''}</div>
    </div>
    ${can ? `<span class="muted">${icon('edit', 15)}</span>` : ''}
  </div>`;
}

function staffModal(s, body) {
  const isNew = !s;
  const branchOpts = `<option value="">${t('team.noBranchOpt')}</option>` +
    ST.branches.map((b) => `<option value="${b.id}" ${s && s.branch_id === b.id ? 'selected' : ''}>${escapeHtml(b.name)}</option>`).join('');
  const roleOpts = Object.entries(ROLE_LABEL)
    .map(([r, l]) => `<option value="${r}" ${(s ? s.role : 'doctor') === r ? 'selected' : ''}>${l}</option>`).join('');

  const dlg = modal({
    title: isNew ? t('team.addStaff') : t('team.editStaff'),
    body: `
      ${avatarField(s ? s.name : '', s ? s.avatar : '', 'sf-av')}
      <div class="grid grid-2">
        <div class="field"><label>${t('team.fullName')}</label>
          <input class="input" id="sf-name" value="${s ? escapeHtml(s.name) : ''}" autofocus></div>
        <div class="field"><label>${t('team.position')} <span class="muted">${t('common.optional')}</span></label>
          <input class="input" id="sf-title" value="${s ? escapeHtml(s.title || '') : ''}" placeholder="${t('team.positionPh')}"></div>
      </div>
      <div class="grid grid-2">
        <div class="field"><label>${t('team.role')}</label>
          <select class="select" id="sf-role">${roleOpts}</select></div>
        <div class="field"><label>${t('menu.branch')}</label>
          <select class="select" id="sf-branch">${branchOpts}</select></div>
      </div>
      <div class="field"><label>${t('team.phone')} <span class="muted">${t('team.phoneHint')}</span></label>
        <input class="input" id="sf-phone" inputmode="numeric" maxlength="10"
          oninput="this.value=this.value.replace(/\\D/g,'').slice(0,10)"
          value="${s ? escapeHtml(s.phone || '') : ''}" placeholder="0812345678"></div>
      <div class="field"><label>${t('team.icsUrl')} <span class="muted">${t('common.optional')}</span></label>
        <input class="input" id="sf-ics-url" value="${s ? escapeHtml(s.ics_url || '') : ''}" placeholder="${t('team.icsUrlPh')}"></div>
      ${s && s.ics_url ? `<div class="row gap-2" style="align-items:center;margin-top:-4px">
        <div class="field-hint" style="margin:0">${s.ics_last_error
          ? `<span class="text-danger">${t('team.icsSyncFailed')}: ${escapeHtml(s.ics_last_error)}</span>`
          : (s.ics_last_synced_at ? t('team.icsLastSynced', { when: timeAgo(s.ics_last_synced_at) })
                                   : t('team.icsNeverSynced'))}</div>
        <button type="button" class="btn btn-ghost btn-sm" id="sf-ics-sync">${t('team.icsSyncNow')}</button>
      </div>` : ''}
      ${isNew ? '' : `<label class="row gap-2" style="cursor:pointer;margin-top:4px">
        <span class="toggle"><input type="checkbox" id="sf-active" ${s.active !== false ? 'checked' : ''}><span class="track"></span></span>
        <span>${t('team.activeInSystem')}</span></label>`}
      <div class="field-hint">${t('team.rosterHint')}</div>`,
    actions: [
      ...(isNew ? [] : [{ label: t('common.delete'), class: 'btn-danger', keepOpen: true,
        onClick: async ({ close }) => {
          const ok = await confirmDialog({
            title: t('team.delStaffTitle'),
            message: t('team.delStaffMsg', { name: s.name }),
            confirmLabel: t('team.delPermanent'), danger: true,
          });
          if (!ok) return;
          try {
            await api.del(`/team-members/${s.id}`);
            toast(t('team.staffDeleted'), 'success');
            close();
            ST.staff = await api.get('/team-members');
            renderTeamTab(body);
          } catch (ex) { toast(ex.detail || t('common.deleteFailed'), 'error'); }
        } }]),
      { label: t('common.cancel'), class: 'btn-ghost' },
      { label: isNew ? t('team.addStaffBtn') : t('common.save'), class: 'btn-primary', keepOpen: true,
        onClick: async ({ close, modal: m }) => {
          const payload = {
            name: m.querySelector('#sf-name').value.trim(),
            title: m.querySelector('#sf-title').value.trim(),
            role: m.querySelector('#sf-role').value,
            branch_id: m.querySelector('#sf-branch').value || null,
            phone: m.querySelector('#sf-phone').value.replace(/\D/g, '').slice(0, 10),
            ics_url: m.querySelector('#sf-ics-url').value.trim(),
          };
          if (!payload.name) { toast(t('team.enterName'), 'error'); return; }
          if (!isNew) payload.active = m.querySelector('#sf-active').checked;
          if (avatarState.clear) payload.avatar = '';
          const btn = m.querySelector('.modal-foot .btn-primary');
          btn.disabled = true; btn.innerHTML = '<div class="spinner"></div>';
          try {
            const saved = isNew ? await api.post('/team-members', payload)
              : await api.patch(`/team-members/${s.id}`, payload);
            if (avatarState.file) {
              const fd = new FormData(); fd.append('file', avatarState.file);
              try { await api.post(`/team-members/${saved.id}/avatar`, fd); }
              catch (e) { toast(t('team.savedPhotoFailed'), 'warn'); }
            }
            toast(isNew ? t('team.staffAdded') : t('common.saved'), 'success');
            close();
            ST.staff = await api.get('/team-members');
            renderTeamTab(body);
          } catch (ex) {
            toast(ex.detail || t('common.saveFailed'), 'error');
            btn.disabled = false; btn.textContent = isNew ? t('team.addStaffBtn') : t('common.save');
          }
        } },
    ],
  });

  const avatarState = bindAvatarPicker(dlg.el, 'sf-av', s ? s.name : '');
  dlg.el.querySelector('#sf-name').oninput = (e) => { avatarState.name = e.target.value; };

  const syncBtn = dlg.el.querySelector('#sf-ics-sync');
  if (syncBtn) {
    syncBtn.onclick = async () => {
      const url = dlg.el.querySelector('#sf-ics-url').value.trim();
      if (!url) return;
      syncBtn.disabled = true;
      const original = syncBtn.textContent;
      syncBtn.textContent = '...';
      try {
        // "Sync now" must act on whatever is CURRENTLY typed, not the last-saved
        // value — pasting a corrected link and clicking this straight away is the
        // natural flow, and syncing the stale saved URL instead is a confusing trap.
        if (url !== (s.ics_url || '')) {
          await api.patch(`/team-members/${s.id}`, { ics_url: url });
        }
        const updated = await api.post(`/team-members/${s.id}/sync-calendar`);
        ST.staff = await api.get('/team-members');
        const fresh = ST.staff.find((m) => m.id === s.id) || updated;
        toast(fresh.ics_last_error
          ? `${t('team.icsSyncFailed')}: ${fresh.ics_last_error}` : t('common.saved'),
          fresh.ics_last_error ? 'error' : 'success');
        dlg.close();
        staffModal(fresh, body);
      } catch (ex) {
        toast(ex.detail || t('common.saveFailed'), 'error');
        syncBtn.disabled = false;
        syncBtn.textContent = original;
      }
    };
  }
}

/* ----------------------------- Schedule tab ----------------------------- */
function renderScheduleTab(body) {
  if (!ST.branches.length) {
    body.innerHTML = `<div class="card">${emptyState('building', t('team.noBranchesTitle'), t('team.noBranchesSub'))}</div>`;
    return;
  }
  body.innerHTML = `
    <div class="tm-sched-bar">
      <div class="row gap-1">
        <button class="btn-icon btn-ghost" id="sc-prev" title="${t('team.prevDay')}">${icon('chevron-left', 16)}</button>
        <input class="input" type="date" id="sc-date" value="${ST.schedDate}" style="width:158px">
        <button class="btn-icon btn-ghost" id="sc-next" title="${t('team.nextDay')}">${icon('chevron-right', 16)}</button>
      </div>
      <button class="btn btn-ghost btn-sm" id="sc-today">${t('common.today')}</button>
    </div>
    <div id="sc-body">${loadingBlock()}</div>`;

  const reload = () => loadSchedule(body);
  const dateInp = body.querySelector('#sc-date');
  dateInp.onchange = () => { ST.schedDate = dateInp.value || todayStr(); reload(); };
  body.querySelector('#sc-prev').onclick = () => { ST.schedDate = shiftDate(ST.schedDate, -1); reload(); };
  body.querySelector('#sc-next').onclick = () => { ST.schedDate = shiftDate(ST.schedDate, 1); reload(); };
  body.querySelector('#sc-today').onclick = () => { ST.schedDate = todayStr(); reload(); };
  reload();
}

async function loadSchedule(body) {
  const scBody = body.querySelector('#sc-body');
  const dateInp = body.querySelector('#sc-date');
  if (dateInp) dateInp.value = ST.schedDate;
  scBody.innerHTML = loadingBlock();
  let rows = [];
  let busy = [];
  // No branch_id → every branch the user may see (the header's "All branches").
  try {
    [rows, busy] = await Promise.all([
      api.get('/bookings' + (ST.schedBranch ? `?branch_id=${ST.schedBranch}` : '')),
      api.get(`/team-members/busy-blocks?date=${ST.schedDate}`),
    ]);
  } catch (e) { scBody.innerHTML = emptyState('alert', t('team.scheduleLoadFailed')); return; }
  const dayRows = rows
    .filter((b) => b.slot_at.slice(0, 10) === ST.schedDate)
    .sort((a, b) => a.slot_at.localeCompare(b.slot_at));
  const doctors = ST.staff.filter((s) => s.role === 'doctor' && s.active !== false);
  // Same branch scoping as the doctor-assignment dropdown: a doctor with no branch_id
  // works everywhere, so their external busy time is relevant regardless of which
  // branch is selected.
  const dayBusy = busy
    .filter((x) => !ST.schedBranch || x.branch_id == null || x.branch_id === ST.schedBranch)
    .sort((a, b) => a.starts_at.localeCompare(b.starts_at));
  renderScheduleDay(scBody, dayRows, dayBusy, doctors, body);
}

function renderScheduleDay(scBody, rows, busy, doctors, body) {
  const br = ST.branches.find((b) => b.id === ST.schedBranch);
  const scopeName = ST.schedBranch ? (br ? br.name : '') : t('menu.allBranches');
  const head = `<div class="row-between" style="margin-bottom:10px">
    <div class="strong">${dateLongRaw(ST.schedDate)}</div>
    <span class="muted text-sm">${escapeHtml(scopeName)} · ${t('team.bookingCount', { count: rows.length })}</span></div>`;
  if (!rows.length && !busy.length) {
    scBody.innerHTML = head + `<div class="card">${
      emptyState('calendar', t('team.noBookingsTitle'), t('team.noBookingsSub'))}</div>`;
    return;
  }
  const can = store.canManage();
  // Only doctors who work at that booking's branch (or at every branch) can take it —
  // plus whoever is already assigned, so an existing assignment is never silently dropped.
  const docOpts = (sel, branchId) => `<option value="">${t('team.noDoctorOpt')}</option>` +
    doctors.filter((d) => d.branch_id == null || d.branch_id === branchId || d.id === sel)
      .map((d) => `<option value="${d.id}" ${d.id === sel ? 'selected' : ''}>${escapeHtml(d.name)}</option>`).join('');
  // Bookings and busy blocks interleaved by time, so the schedule reads as one timeline
  // rather than "real appointments, then a separate unrelated list."
  const merged = [
    ...rows.map((b) => ({ kind: 'booking', time: b.slot_at, data: b })),
    ...busy.map((x) => ({ kind: 'busy', time: x.starts_at, data: x })),
  ].sort((a, b) => a.time.localeCompare(b.time));
  scBody.innerHTML = head + `<div class="card tm-sched">
    ${merged.map((row) => row.kind === 'booking' ? (() => { const b = row.data; return `
      <div class="tm-slot" data-id="${b.id}">
        <div class="tm-slot-time strong">${timeOfRaw(b.slot_at)}</div>
        <div class="tm-slot-main">
          <div class="strong">${escapeHtml(b.customer_name)}</div>
          <div class="muted text-sm">${escapeHtml(b.service_name)}${
            ST.schedBranch ? '' : ` · ${escapeHtml(b.branch_name)}`}${
            b.created_by === 'ai' ? ' · <span class="badge badge-olive">AI</span>' : ''}</div>
        </div>
        <div class="tm-slot-doc">
          <select class="select" data-doc="${b.id}" ${can ? '' : 'disabled'}>${docOpts(b.doctor_id, b.branch_id)}</select>
        </div>
        <span class="badge ${BK_BADGE[b.status] || 'badge-soft'}">${BK_LABEL[b.status] || b.status}</span>
      </div>`; })() : (() => { const x = row.data; return `
      <div class="tm-slot tm-slot-busy">
        <div class="tm-slot-time strong">${timeOfRaw(x.starts_at)}–${timeOfRaw(x.ends_at)}</div>
        <div class="tm-slot-main">
          <div class="strong">${escapeHtml(x.staff_name || '—')}</div>
          <div class="muted text-sm">${t('team.icsBusyLabel')}</div>
        </div>
        <span class="badge badge-soft">${icon('calendar', 13)} ${t('team.icsBusyBadge')}</span>
      </div>`; })()).join('')}
  </div>`;

  scBody.querySelectorAll('[data-doc]').forEach((sel) => {
    sel.onchange = async () => {
      try {
        await api.patch(`/bookings/${sel.dataset.doc}`, { doctor_id: sel.value ? Number(sel.value) : null });
        toast(t('team.doctorUpdated'), 'success');
      } catch (e) { toast(e.detail || t('common.updateFailed'), 'error'); }
    };
  });
  scBody.querySelectorAll('.tm-slot:not(.tm-slot-busy)').forEach((el) => {
    const doc = el.querySelector('.tm-slot-doc');
    if (doc) doc.onclick = (ev) => ev.stopPropagation();   // don't open the modal when using the dropdown
    el.onclick = () => {
      const b = rows.find((x) => x.id === Number(el.dataset.id));
      if (b) slotModal(b, body);
    };
  });
}

function slotModal(b, body) {
  modal({
    title: t('team.bookingDetails'),
    body: `
      <div class="kv"><span class="k">${t('team.customer')}</span><span class="v">${escapeHtml(b.customer_name)}</span></div>
      <div class="kv"><span class="k">${t('team.service')}</span><span class="v">${escapeHtml(b.service_name)}</span></div>
      <div class="kv"><span class="k">${t('menu.branch')}</span><span class="v">${escapeHtml(b.branch_name)}</span></div>
      <div class="kv"><span class="k">${t('role.doctor')}</span><span class="v">${escapeHtml(b.doctor_name || '—')}</span></div>
      <div class="kv"><span class="k">${t('team.time')}</span><span class="v">${dateLongRaw(b.slot_at)}, ${timeOfRaw(b.slot_at)}</span></div>
      <div class="divider"></div>
      <div class="field"><label>${t('common.status')}</label>
        <select class="select" id="ss-status">
          ${EDITABLE_STATUSES.map((s) => `<option value="${s}" ${s === b.status ? 'selected' : ''}>${BK_LABEL[s]}</option>`).join('')}
          ${b.status === 'expired' ? `<option value="expired" selected>${BK_LABEL.expired}</option>` : ''}
        </select></div>`,
    actions: [
      { label: t('common.close'), class: 'btn-ghost' },
      { label: t('common.save'), class: 'btn-primary', keepOpen: true, onClick: async ({ close, modal: m }) => {
        try {
          await api.patch(`/bookings/${b.id}`, { status: m.querySelector('#ss-status').value });
          toast(t('common.updated'), 'success'); close(); loadSchedule(body);
        } catch (e) { toast(e.detail || t('common.updateFailed'), 'error'); }
      } },
    ],
  });
}
