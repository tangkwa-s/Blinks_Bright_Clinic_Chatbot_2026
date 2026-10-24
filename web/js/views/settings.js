/* Blinks Bright — Settings view (branches, team, AI, calendar) */

import { api } from '../api.js';
import { store } from '../store.js';
import { icon, toast, modal, escapeHtml, initials, loadingBlock, emptyState,
         avatarHTML, avatarField, bindAvatarPicker, confirmDialog, bindPasswordEyes } from '../ui.js';
import { t } from '../i18n.js';

const ROLE_LABEL = {
  owner: t('role.owner'), super_admin: t('role.super_admin'), branch_manager: t('role.branch_manager'),
  sales: t('role.sales'), doctor: t('role.doctor'), marketing: t('role.marketing'),
};

const DAYS = [['mon', t('settings.dayMon'), t('settings.dayMonShort')],
              ['tue', t('settings.dayTue'), t('settings.dayTueShort')],
              ['wed', t('settings.dayWed'), t('settings.dayWedShort')],
              ['thu', t('settings.dayThu'), t('settings.dayThuShort')],
              ['fri', t('settings.dayFri'), t('settings.dayFriShort')],
              ['sat', t('settings.daySat'), t('settings.daySatShort')],
              ['sun', t('settings.daySun'), t('settings.daySunShort')]];

/* Normalise Branch.hours (per-day, legacy weekday/weekend, or empty) to a 7-day map. */
function normalizeHours(raw) {
  const out = {};
  const days = (raw && raw.days) || null;
  DAYS.forEach(([k]) => {
    if (days && days[k]) {
      out[k] = { open: days[k].open || '10:00', close: days[k].close || '20:00', closed: !!days[k].closed };
    } else if (raw && (raw.weekday || raw.weekend)) {
      const wknd = (k === 'sat' || k === 'sun');
      const [o, c] = ((wknd ? raw.weekend : raw.weekday) || (wknd ? '10:00-19:00' : '10:00-20:00')).split('-');
      out[k] = { open: o || '10:00', close: c || '20:00', closed: false };
    } else {
      out[k] = { open: '10:00', close: '20:00', closed: false };
    }
  });
  return out;
}

/* Collapse consecutive identical days → ["Mon–Fri 10:00–20:00", "Sat–Sun Closed"]. */
function hoursSegments(h) {
  const segs = [];
  DAYS.forEach(([k], i) => {
    const sig = h[k].closed ? t('settings.closed') : `${h[k].open}–${h[k].close}`;
    const last = segs[segs.length - 1];
    if (last && last.sig === sig) last.end = i;
    else segs.push({ sig, start: i, end: i });
  });
  const lbl = (i) => DAYS[i][2];
  return segs.map((s) => `${s.start === s.end ? lbl(s.start) : `${lbl(s.start)}–${lbl(s.end)}`} ${s.sig}`);
}

function hoursSummary(h) {
  return hoursSegments(h).join(' · ');
}

// Module-level (not reset inside renderSettings) so switching the topbar's
// active branch — which remounts this whole view — never jumps back to the
// Branches tab; only the user picking a different tab does.
let activeTab = 'branches';

export default async function renderSettings(mount) {
  const canEdit = store.canManage();
  mount.innerHTML = `<div class="view">
    <div class="view-head">
      <div><h2>${t('settings.title')}</h2><p>${t('settings.subtitle')}</p></div>
    </div>
    <div class="tabs">
      <button class="tab${activeTab === 'branches' ? ' active' : ''}" data-tab="branches">${t('settings.tabBranches')}</button>
      <button class="tab${activeTab === 'team' ? ' active' : ''}" data-tab="team">${t('settings.tabTeam')}</button>
      <button class="tab${activeTab === 'ai' ? ' active' : ''}" data-tab="ai">${t('settings.tabAI')}</button>
      <button class="tab${activeTab === 'calendar' ? ' active' : ''}" data-tab="calendar">${t('settings.tabCalendar')}</button>
    </div>
    <div id="set-body">${loadingBlock()}</div>
  </div>`;

  const body = mount.querySelector('#set-body');
  render();

  mount.querySelectorAll('.tab').forEach((t) => {
    t.onclick = () => {
      mount.querySelectorAll('.tab').forEach((x) => x.classList.toggle('active', x === t));
      activeTab = t.dataset.tab;
      render();
    };
  });

  async function render() {
    body.innerHTML = loadingBlock();
    if (activeTab === 'branches') await branchesTab(body, canEdit);
    else if (activeTab === 'team') await teamTab(body, canEdit);
    else if (activeTab === 'calendar') await calendarTab(body);
    else await aiTab(body);
  }
}

async function branchesTab(body, canEdit) {
  let branches = [];
  try { branches = await api.get('/branches'); } catch (e) {}
  body.innerHTML = `
    ${canEdit ? `<div class="row" style="justify-content:flex-end;margin-bottom:var(--sp-4)">
      <button class="btn btn-primary btn-sm" id="add-branch">${icon('plus', 15)}<span>${t('settings.addBranch')}</span></button></div>` : ''}
    <div class="grid grid-3">
    ${branches.map((b) => `
      <div class="card card-pad" data-id="${b.id}">
        <div class="row-between">
          <div class="stat-ic">${icon('building', 17)}</div>
          ${canEdit ? `<button class="btn-icon btn-subtle" data-edit>${icon('edit', 15)}</button>` : ''}
        </div>
        <div class="strong" style="margin:10px 0 2px">${escapeHtml(b.name)}</div>
        <div class="muted text-sm">${escapeHtml(b.code)} &middot; ${escapeHtml(b.phone)}</div>
        <div class="divider"></div>
        <div class="kv"><span class="k">${t('settings.address')}</span><span class="v" style="max-width:160px">${escapeHtml(b.address)}</span></div>
        <div class="kv" style="align-items:flex-start"><span class="k">${t('settings.hours')}</span>
          <span class="v" style="display:flex;flex-direction:column;gap:2px;align-items:flex-end;text-align:right">${
            hoursSegments(normalizeHours(b.hours)).map((s) => `<span style="white-space:nowrap">${escapeHtml(s)}</span>`).join('')}</span></div>
      </div>`).join('')}
  </div>`;

  if (canEdit) {
    body.querySelector('#add-branch').onclick = () => branchModal(body, canEdit, null);
    body.querySelectorAll('[data-edit]').forEach((btn) => {
      btn.onclick = () => {
        const b = branches.find((x) => x.id === Number(btn.closest('[data-id]').dataset.id));
        branchModal(body, canEdit, b);
      };
    });
  }
}

function branchModal(body, canEdit, b) {
  const isNew = !b;
  b = b || { name: '', code: '', phone: '', address: '', open_hour: 10, close_hour: 20, hours: {} };
  const h = normalizeHours(b.hours);
  // Full day in 15-minute steps (00:00 … 24:00). Setting 00:00–24:00 means open 24 hours.
  const TIMES = [];
  for (let t = 0; t <= 24 * 60; t += 15) {
    TIMES.push(`${String(Math.floor(t / 60)).padStart(2, '0')}:${String(t % 60).padStart(2, '0')}`);
  }
  const toMin = (s) => { const p = String(s).split(':'); return (parseInt(p[0], 10) || 0) * 60 + (parseInt(p[1], 10) || 0); };
  const sel = (id, val) => `<select class="select" id="${id}">${
    TIMES.map((t) => `<option ${t === val ? 'selected' : ''}>${t}</option>`).join('')}</select>`;

  const m = modal({
    title: isNew ? t('settings.addBranch') : t('settings.editBranch'),
    wide: true,
    body: `
      <div class="field"><label>${t('common.name')}</label><input class="input" id="f-name" value="${escapeHtml(b.name)}" placeholder="${t('settings.branchNamePh')}"></div>
      <div class="grid grid-2">
        <div class="field"><label>${t('settings.code')}</label><input class="input" id="f-code" value="${escapeHtml(b.code)}" placeholder="${t('settings.codePh')}"></div>
        <div class="field"><label>${t('settings.phone')}</label><input class="input" id="f-phone" value="${escapeHtml(b.phone)}"></div>
      </div>
      <div class="field"><label>${t('settings.address')}</label><input class="input" id="f-addr" value="${escapeHtml(b.address)}"></div>
      <div class="field"><label>${t('settings.openingHours')} <span class="muted">${t('settings.openingHoursHint')}</span></label>
        <div class="kb-hours-edit">
          ${DAYS.map(([k, label]) => `
            <div class="kb-he-row${h[k].closed ? ' is-closed' : ''}" data-day="${k}">
              <span class="kb-he-day">${label}</span>
              <label class="toggle" title="${t('settings.openClosed')}"><input type="checkbox" data-open ${h[k].closed ? '' : 'checked'}><span class="track"></span></label>
              <span class="kb-he-times">${sel(`o-${k}`, h[k].open)}<span class="muted">–</span>${sel(`c-${k}`, h[k].close)}</span>
            </div>`).join('')}
        </div>
        <button type="button" class="btn btn-ghost btn-sm" id="h-copy" style="margin-top:10px">${icon('download', 14)}<span>${t('settings.applyMonday')}</span></button>
      </div>`,
    actions: [
      { label: t('common.cancel'), class: 'btn-ghost' },
      { label: isNew ? t('settings.createBranch') : t('common.save'), class: 'btn-primary', keepOpen: true, onClick: async ({ close, modal: mEl }) => {
        const name = mEl.querySelector('#f-name').value.trim();
        if (!name) { toast(t('settings.branchNameRequired'), 'error'); return; }
        const days = {};
        let bad = false;
        DAYS.forEach(([k]) => {
          const open = mEl.querySelector(`[data-day="${k}"] [data-open]`).checked;
          if (!open) { days[k] = { closed: true }; return; }
          const o = mEl.querySelector(`#o-${k}`).value, c = mEl.querySelector(`#c-${k}`).value;
          if (toMin(c) <= toMin(o)) bad = true;
          days[k] = { open: o, close: c };
        });
        if (bad) { toast(t('settings.closeAfterOpen'), 'error'); return; }
        const opens = DAYS.map(([k]) => days[k]).filter((d) => !d.closed);
        const payload = {
          name,
          code: mEl.querySelector('#f-code').value.trim(),
          phone: mEl.querySelector('#f-phone').value.trim(),
          address: mEl.querySelector('#f-addr').value.trim(),
          hours: { days },
          open_hour: opens.length ? Math.min(...opens.map((d) => parseInt(d.open, 10))) : 10,
          close_hour: opens.length ? Math.max(...opens.map((d) => parseInt(d.close, 10))) : 20,
        };
        const btn = mEl.querySelector('.modal-foot .btn-primary');
        btn.disabled = true; btn.innerHTML = '<div class="spinner"></div>';
        try {
          if (isNew) await api.post('/branches', payload);
          else await api.patch(`/branches/${b.id}`, payload);
          try { store.branches = await api.get('/branches'); } catch (e) { /* keep old */ }
          toast(isNew ? t('settings.branchAdded') : t('settings.branchUpdated'), 'success');
          close(); branchesTab(body, canEdit);
        } catch (ex) {
          toast(ex.detail || t('common.saveFailed'), 'error');
          btn.disabled = false; btn.textContent = isNew ? t('settings.createBranch') : t('common.save');
        }
      } },
    ],
  });

  // toggle open/closed dims that day's time pickers
  m.el.querySelectorAll('[data-open]').forEach((cb) => {
    cb.onchange = () => cb.closest('.kb-he-row').classList.toggle('is-closed', !cb.checked);
  });
  // "Apply Monday to every day" convenience
  m.el.querySelector('#h-copy').onclick = () => {
    const open = m.el.querySelector('[data-day="mon"] [data-open]').checked;
    const o = m.el.querySelector('#o-mon').value, c = m.el.querySelector('#c-mon').value;
    DAYS.forEach(([k]) => {
      if (k === 'mon') return;
      const row = m.el.querySelector(`[data-day="${k}"]`);
      row.querySelector('[data-open]').checked = open;
      row.classList.toggle('is-closed', !open);
      m.el.querySelector(`#o-${k}`).value = o;
      m.el.querySelector(`#c-${k}`).value = c;
    });
    toast(t('settings.appliedMonday'), 'info');
  };
}

async function teamTab(body, canEdit) {
  let staff = [];
  try { staff = await api.get('/staff'); } catch (e) {}
  body.innerHTML = `
    ${canEdit ? `<div class="row" style="justify-content:flex-end;margin-bottom:var(--sp-4)">
      <button class="btn btn-primary btn-sm" id="add-staff">${icon('plus', 15)}<span>${t('settings.addTeamMember')}</span></button></div>` : ''}
    <div class="card"><table class="table">
    <thead><tr><th>${t('common.name')}</th><th>${t('settings.role')}</th><th>${t('settings.colTitle')}</th><th>${t('menu.branch')}</th><th>${t('common.status')}</th>${canEdit ? '<th></th>' : ''}</tr></thead>
    <tbody>
      ${staff.map((u) => `
        <tr data-id="${u.id}">
          <td><div class="row gap-2">
            ${avatarHTML(u.name, u.avatar, 'sm')}
            <div><div class="strong">${escapeHtml(u.name)}</div>
              <div class="muted text-sm">${escapeHtml(u.email)}</div></div>
          </div></td>
          <td><span class="badge badge-olive">${ROLE_LABEL[u.role] || u.role}</span></td>
          <td class="muted">${escapeHtml(u.title || '—')}</td>
          <td class="muted">${escapeHtml(u.branch_name || t('menu.allBranches'))}</td>
          <td><span class="badge ${u.active ? 'badge-paid' : 'badge-soft'}">${u.active ? t('common.active') : t('common.inactive')}</span></td>
          ${canEdit ? `<td style="text-align:right"><div class="row gap-1" style="justify-content:flex-end">
            <button class="btn-icon btn-subtle" data-edit-staff>${icon('edit', 15)}</button>
            ${u.id === (store.user && store.user.id) ? '' : `<button class="btn-icon btn-subtle" data-del-staff data-name="${escapeHtml(u.name)}" title="${t('settings.deleteAccount')}" style="color:#c0552f">${icon('trash', 15)}</button>`}
          </div></td>` : ''}
        </tr>`).join('')}
    </tbody></table></div>`;

  if (canEdit) {
    body.querySelector('#add-staff').onclick = () => staffModal(body, canEdit, null);
    body.querySelectorAll('[data-edit-staff]').forEach((btn) => {
      btn.onclick = () => {
        const u = staff.find((x) => x.id === Number(btn.closest('[data-id]').dataset.id));
        staffModal(body, canEdit, u);
      };
    });
    body.querySelectorAll('[data-del-staff]').forEach((btn) => {
      btn.onclick = async () => {
        const u = staff.find((x) => x.id === Number(btn.closest('[data-id]').dataset.id));
        const ok = await confirmDialog({
          title: t('settings.delTeamTitle'),
          message: t('settings.delTeamMsg', { name: u.name }),
          confirmLabel: t('settings.deleteAccount'), danger: true,
        });
        if (!ok) return;
        try { await api.del(`/staff/${u.id}/purge`); toast(t('settings.teamMemberDeleted'), 'success'); teamTab(body, canEdit); }
        catch (ex) { toast(ex.detail || t('common.deleteFailed'), 'error'); }
      };
    });
  }
}

async function staffModal(body, canEdit, u) {
  const isNew = !u;
  u = u || { name: '', email: '', role: 'sales', title: '', branch_id: null, active: true };
  let branches = [];
  try { branches = await api.get('/branches'); } catch (e) {}
  const elevated = store.isRole('owner', 'super_admin');
  // super_admin is a platform role — /staff always 403s it, so never offer it here
  const roleOpts = Object.entries(ROLE_LABEL)
    .filter(([v]) => v !== 'super_admin' && (elevated || v !== 'owner'))
    .map(([v, l]) => `<option value="${v}" ${u.role === v ? 'selected' : ''}>${l}</option>`).join('');
  const branchOpts = `<option value="">${t('menu.allBranches')}</option>` +
    branches.map((b) => `<option value="${b.id}" ${String(u.branch_id) === String(b.id) ? 'selected' : ''}>${escapeHtml(b.name)}</option>`).join('');
  const dlg = modal({
    title: isNew ? t('settings.addTeamMember') : t('settings.editTeamMember'),
    body: `
      ${avatarField(u.name, u.avatar, 's-av')}
      <div class="field"><label>${t('common.name')}</label><input class="input" id="s-name" value="${escapeHtml(u.name)}" placeholder="${t('settings.staffNamePh')}"></div>
      <div class="grid grid-2">
        <div class="field"><label>${t('settings.email')}${isNew ? ' ' + t('settings.loginSuffix') : ''}</label>
          <input class="input" id="s-email" value="${escapeHtml(u.email)}" placeholder="name@clinic.co"></div>
        <div class="field"><label>${t('settings.role')}</label><select class="select" id="s-role">${roleOpts}</select></div>
      </div>
      <div class="grid grid-2">
        <div class="field"><label>${t('settings.colTitle')}</label><input class="input" id="s-title" value="${escapeHtml(u.title || '')}" placeholder="${t('settings.titlePh')}"></div>
        <div class="field"><label>${t('menu.branch')}</label><select class="select" id="s-branch">${branchOpts}</select></div>
      </div>
      <div class="field"><label>${isNew ? t('settings.tempPassword') : t('settings.resetPassword') + ' ' + t('common.optional')}</label>
        <input class="input" type="password" autocomplete="new-password" id="s-pass" placeholder="${isNew ? t('settings.setInitialPass') : t('settings.leaveBlank')}"></div>
      ${isNew ? '' : `<label class="row gap-2" style="cursor:pointer">
        <span class="toggle"><input type="checkbox" id="s-active" ${u.active ? 'checked' : ''}><span class="track"></span></span>
        <span class="strong">${t('common.active')}</span></label>`}`,
    actions: [
      { label: t('common.cancel'), class: 'btn-ghost' },
      { label: isNew ? t('settings.createMember') : t('common.save'), class: 'btn-primary', keepOpen: true, onClick: async ({ close, modal: m }) => {
        const payload = {
          name: m.querySelector('#s-name').value.trim(),
          role: m.querySelector('#s-role').value,
          title: m.querySelector('#s-title').value.trim(),
          branch_id: m.querySelector('#s-branch').value || null,
        };
        const pass = m.querySelector('#s-pass').value.trim();
        if (pass) payload.password = pass;
        if (avatarState.clear) payload.avatar = '';
        try {
          let saved;
          if (isNew) {
            payload.email = m.querySelector('#s-email').value.trim();
            if (!payload.name || !payload.email || !payload.password) {
              toast(t('settings.nameEmailPassRequired'), 'error'); return;
            }
            saved = await api.post('/staff', payload);
          } else {
            payload.active = m.querySelector('#s-active').checked;
            payload.email = m.querySelector('#s-email').value.trim();
            if (!payload.email) { toast(t('settings.emailRequired'), 'error'); return; }
            saved = await api.patch(`/staff/${u.id}`, payload);
          }
          if (avatarState.file) {
            const fd = new FormData(); fd.append('file', avatarState.file);
            try { await api.post(`/staff/${saved.id}/avatar`, fd); }
            catch (e) { toast(t('settings.savedPhotoFailed'), 'warn'); }
          }
          toast(isNew ? t('settings.teamMemberAdded') : t('settings.teamMemberUpdated'), 'success');
          close(); teamTab(body, canEdit);
        } catch (ex) { toast(ex.detail || t('common.saveFailed'), 'error'); }
      } },
    ],
  });

  bindPasswordEyes(dlg.el);
  const avatarState = bindAvatarPicker(dlg.el, 's-av', u.name);
  dlg.el.querySelector('#s-name').oninput = (e) => { avatarState.name = e.target.value; };
}

const AI_INSTRUCTIONS_MAX = 2000;
const MAX_HOLD_MINUTES = 180;  // mirrors app/services/booking.py::MAX_HOLD_MINUTES

async function aiTab(body) {
  // Mirrors the backend MANAGER guard: branch_manager + marketing (+ elevated).
  const canEditAI = store.canManage() || store.isRole('marketing');
  let s = { ai_name: '', ai_instructions: '', hold_minutes: 0 };
  try { s = await api.get('/clinic/ai-settings'); } catch (e) {}
  body.innerHTML = `<div class="card card-pad" style="max-width:640px">
    <div class="row gap-2" style="margin-bottom:2px">
      <div class="stat-ic">${icon('ai', 17)}</div>
      <div class="strong">${t('settings.aiTitle')}</div>
    </div>
    <div class="muted text-sm">${t('settings.aiDesc')}</div>
    <div class="divider"></div>
    <div class="field"><label>${t('settings.aiNameLabel')}</label>
      <input class="input" id="ai-name" maxlength="60" value="${escapeHtml(s.ai_name || '')}"
        placeholder="${t('settings.aiNamePh')}" ${canEditAI ? '' : 'disabled'}></div>
    <div class="field"><label>${t('settings.aiInstrLabel')}</label>
      <textarea class="textarea" id="ai-instr" rows="5" maxlength="${AI_INSTRUCTIONS_MAX}"
        placeholder="${t('settings.aiInstrPh')}" ${canEditAI ? '' : 'disabled'}>${escapeHtml(s.ai_instructions || '')}</textarea>
      <div class="muted text-sm" id="ai-count" style="text-align:right;margin-top:4px"></div></div>
    <div class="field"><label>${t('settings.holdMinutesLabel')}</label>
      <input class="input" id="ai-hold-minutes" type="number" min="0" max="${MAX_HOLD_MINUTES}"
        value="${s.hold_minutes || ''}" placeholder="${t('settings.holdMinutesPh')}"
        ${canEditAI ? '' : 'disabled'}>
      <div class="field-hint">${t('settings.holdMinutesHint')}</div></div>
    <div class="field-hint">${t('settings.aiSafetyHint')}</div>
    ${canEditAI ? `<button class="btn btn-primary btn-sm" id="ai-save" style="margin-top:10px">${icon('check', 14)}<span>${t('common.save')}</span></button>` : ''}
  </div>`;

  const instr = body.querySelector('#ai-instr');
  const count = body.querySelector('#ai-count');
  const updateCount = () => { count.textContent = `${instr.value.length} / ${AI_INSTRUCTIONS_MAX}`; };
  instr.oninput = updateCount;
  updateCount();

  const save = body.querySelector('#ai-save');
  if (save) {
    save.onclick = async () => {
      save.disabled = true;
      try {
        const holdInp = body.querySelector('#ai-hold-minutes');
        const holdMinutes = Math.max(0, Math.min(Number(holdInp.value) || 0, MAX_HOLD_MINUTES));
        const saved = await api.patch('/clinic/ai-settings', {
          ai_name: body.querySelector('#ai-name').value.trim(),
          ai_instructions: instr.value.trim(),
          hold_minutes: holdMinutes,
        });
        body.querySelector('#ai-name').value = saved.ai_name || '';
        instr.value = saved.ai_instructions || '';
        holdInp.value = saved.hold_minutes || '';
        updateCount();
        toast(t('settings.aiSaved'), 'success');
      } catch (ex) {
        toast(ex.detail || t('common.saveFailed'), 'error');
      }
      save.disabled = false;
    };
  }
}

async function calendarTab(body) {
  const fetchUrl = async (branchId) => {
    try {
      const r = await api.get(`/calendar/feed-url${branchId ? `?branch_id=${branchId}` : ''}`);
      return r.url || '';
    } catch (e) { return ''; }
  };
  const url = await fetchUrl('');
  const branches = store.branches || [];
  body.innerHTML = `<div class="card card-pad" style="max-width:640px">
    <div class="row gap-2" style="margin-bottom:2px">
      <div class="stat-ic">${icon('calendar', 17)}</div>
      <div class="strong">${t('settings.calTitle')}</div>
    </div>
    <div class="muted text-sm">${t('settings.calDesc')}</div>
    <div class="divider"></div>
    ${branches.length > 1 ? `<div class="field"><label>${t('menu.branch')}</label>
      <select class="select" id="cal-branch">
        <option value="">${t('settings.calBranchAll')}</option>
        ${branches.map((b) => `<option value="${b.id}">${escapeHtml(b.name)}</option>`).join('')}
      </select></div>` : ''}
    <div class="field"><label>${t('settings.calUrlLabel')}</label>
      <input class="input" id="cal-url" value="${escapeHtml(url)}" readonly style="background:var(--surface-2)"></div>
    <div class="field-hint">${t('settings.calSecretHint')}</div>
    <button class="btn btn-primary btn-sm" id="cal-copy" style="margin-top:10px">${icon('copy', 14)}<span>${t('settings.calCopy')}</span></button>
  </div>`;

  const input = body.querySelector('#cal-url');
  const sel = body.querySelector('#cal-branch');
  if (sel) sel.onchange = async () => { input.value = await fetchUrl(sel.value); };
  body.querySelector('#cal-copy').onclick = async () => {
    try {
      await navigator.clipboard.writeText(input.value);
      toast(t('settings.calCopied'), 'success');
    } catch (e) {
      input.select();
      toast(t('settings.calCopyFailed'), 'error');
    }
  };
}
