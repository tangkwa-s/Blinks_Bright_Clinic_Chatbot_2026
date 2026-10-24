/* Blinks Bright — System console: users & role access across all clinics (Tier 1) */

import { api } from '../api.js';
import { icon, escapeHtml, toast, modal, debounce, loadingBlock, emptyState,
         avatarHTML, avatarField, bindAvatarPicker, bindPasswordEyes } from '../ui.js';
import { t } from '../i18n.js';

const ROLE_LABEL = {
  super_admin: t('sysusers.roleSystemAdmin'), owner: t('role.owner'), branch_manager: t('role.branch_manager'),
  sales: t('sysusers.roleSalesAdmin'), doctor: t('role.doctor'), marketing: t('role.marketing'),
};
const ROLE_BADGE = {
  super_admin: 'badge-olive', owner: 'badge-olive', branch_manager: 'badge-booked',
  doctor: 'badge-paid', sales: 'badge-interested', marketing: 'badge-new',
};

const ST = { clinics: [], filter: { clinic_id: '', role: '', q: '' } };

export default async function renderSystemUsers(mount) {
  mount.innerHTML = `<div class="view">
    <div class="view-head">
      <div><h2>${t('sysusers.title')}</h2><p>${t('sysusers.subtitle')}</p></div>
      <button class="btn btn-primary" id="su-new">${icon('plus', 16)}<span>${t('sysusers.addUser')}</span></button>
    </div>
    <div class="row gap-2" style="margin-bottom:14px;flex-wrap:wrap">
      <div class="filter-pill">${icon('building', 15)}
        <select id="su-fc" style="border:none;background:none;outline:none;cursor:pointer"></select></div>
      <div class="filter-pill">${icon('users', 15)}
        <select id="su-fr" style="border:none;background:none;outline:none;cursor:pointer">
          <option value="">${t('sysusers.allRoles')}</option>
          ${Object.entries(ROLE_LABEL).map(([v, l]) => `<option value="${v}">${l}</option>`).join('')}
        </select></div>
      <div class="filter-pill" style="flex:1;min-width:180px">${icon('search', 15)}
        <input id="su-q" placeholder="${t('sysusers.searchPh')}"
          style="border:none;background:none;outline:none;width:100%"></div>
    </div>
    <div id="su-body">${loadingBlock()}</div>
  </div>`;

  const body = mount.querySelector('#su-body');

  try { ST.clinics = await api.get('/admin/clinics'); }
  catch (e) { ST.clinics = []; }

  mount.querySelector('#su-fc').innerHTML = `<option value="">${t('sysusers.allClinics')}</option>` +
    ST.clinics.map((c) => `<option value="${c.id}">${escapeHtml(c.name)}</option>`).join('');

  mount.querySelector('#su-new').onclick = () => userModal(null, () => load(body));
  mount.querySelector('#su-fc').onchange = (e) => { ST.filter.clinic_id = e.target.value; load(body); };
  mount.querySelector('#su-fr').onchange = (e) => { ST.filter.role = e.target.value; load(body); };
  mount.querySelector('#su-q').oninput = debounce((e) => { ST.filter.q = e.target.value; load(body); }, 250);

  load(body);
}

async function load(body) {
  body.innerHTML = loadingBlock();
  const p = new URLSearchParams();
  if (ST.filter.clinic_id) p.set('clinic_id', ST.filter.clinic_id);
  if (ST.filter.role) p.set('role', ST.filter.role);
  if (ST.filter.q.trim()) p.set('q', ST.filter.q.trim());
  let users;
  try { users = await api.get('/admin/users?' + p.toString()); }
  catch (e) { body.innerHTML = emptyState('alert', t('sysusers.loadUsersFailed')); return; }
  if (!users.length) { body.innerHTML = emptyState('users', t('sysusers.emptyTitle'), t('sysusers.emptySub')); return; }

  body.innerHTML = `<div class="card"><table class="table">
    <thead><tr><th>${t('common.name')}</th><th>${t('sysusers.role')}</th><th>${t('sysusers.clinic')}</th><th>${t('menu.branch')}</th><th>${t('common.status')}</th><th></th></tr></thead>
    <tbody>
      ${users.map((u) => `<tr data-id="${u.id}">
        <td><div class="row gap-2">
          ${avatarHTML(u.name, u.avatar, 'sm')}
          <div><div class="strong">${escapeHtml(u.name)}</div>
            <div class="muted text-sm">${escapeHtml(u.email)}</div></div></div></td>
        <td><span class="badge ${ROLE_BADGE[u.role] || 'badge-soft'}">${ROLE_LABEL[u.role] || u.role}</span></td>
        <td class="muted">${escapeHtml(u.clinic_name || t('sysusers.platformDash'))}</td>
        <td class="muted">${escapeHtml(u.branch_name || t('menu.allBranches'))}</td>
        <td><span class="badge ${u.active ? 'badge-paid' : 'badge-soft'}">${u.active ? t('common.active') : t('sysusers.disabled')}</span></td>
        <td style="text-align:right"><button class="btn-icon btn-subtle" data-edit>${icon('edit', 15)}</button></td>
      </tr>`).join('')}
    </tbody></table></div>`;

  body.querySelectorAll('[data-edit]').forEach((b) =>
    (b.onclick = () => {
      const u = users.find((x) => x.id === Number(b.closest('[data-id]').dataset.id));
      if (u) userModal(u, () => load(body));
    }));
}

function branchOptionsFor(clinicId, selected) {
  const c = ST.clinics.find((x) => String(x.id) === String(clinicId));
  const branches = (c && c.branches) || [];
  return `<option value="">${t('menu.allBranches')}</option>` +
    branches.map((b) => `<option value="${b.id}" ${String(selected) === String(b.id) ? 'selected' : ''}>${escapeHtml(b.name)}</option>`).join('');
}

function userModal(u, onSaved) {
  const isNew = !u;
  const roleOpts = Object.entries(ROLE_LABEL)
    .map(([v, l]) => `<option value="${v}" ${(u ? u.role : 'sales') === v ? 'selected' : ''}>${l}</option>`).join('');
  const clinicOpts = `<option value="">${t('sysusers.platformNoClinic')}</option>` +
    ST.clinics.map((c) => `<option value="${c.id}" ${u && String(u.clinic_id) === String(c.id) ? 'selected' : ''}>${escapeHtml(c.name)}</option>`).join('');

  const dlg = modal({
    title: isNew ? t('sysusers.addUser') : t('sysusers.editUser'),
    body: `
      ${avatarField(u ? u.name : '', u ? u.avatar : '', 'um-av')}
      <div class="field"><label>${t('sysusers.fullName')}</label>
        <input class="input" id="um-name" value="${u ? escapeHtml(u.name) : ''}" autofocus></div>
      <div class="grid grid-2">
        <div class="field"><label>${t('sysusers.email')}${isNew ? t('sysusers.loginSuffix') : ''}</label>
          <input class="input" id="um-email" value="${u ? escapeHtml(u.email) : ''}" ${isNew ? '' : 'disabled'} placeholder="name@clinic.co"></div>
        <div class="field"><label>${t('sysusers.role')}</label><select class="select" id="um-role">${roleOpts}</select></div>
      </div>
      <div class="grid grid-2">
        <div class="field"><label>${t('sysusers.clinic')}</label><select class="select" id="um-clinic">${clinicOpts}</select></div>
        <div class="field"><label>${t('menu.branch')}</label><select class="select" id="um-branch">${
          branchOptionsFor(u ? u.clinic_id : '', u ? u.branch_id : '')}</select></div>
      </div>
      <div class="field"><label>${isNew ? t('sysusers.password') : t('sysusers.resetPassword') + ' ' + t('common.optional')}</label>
        <input class="input" type="password" autocomplete="new-password" id="um-pass" placeholder="${isNew ? t('sysusers.passMin') : t('sysusers.passKeep')}"></div>
      <div class="field-hint">${t('sysusers.clinicHint')}</div>
      ${isNew ? '' : `<label class="row gap-2" style="cursor:pointer;margin-top:4px">
        <span class="toggle"><input type="checkbox" id="um-active" ${u.active ? 'checked' : ''}><span class="track"></span></span>
        <span class="strong">${t('common.active')}</span></label>`}`,
    actions: [
      { label: t('common.cancel'), class: 'btn-ghost' },
      { label: isNew ? t('sysusers.createUser') : t('sysusers.saveChanges'), class: 'btn-primary', keepOpen: true,
        onClick: async ({ close, modal: m }) => {
          const name = m.querySelector('#um-name').value.trim();
          const role = m.querySelector('#um-role').value;
          const clinic_id = m.querySelector('#um-clinic').value;
          const branch_id = m.querySelector('#um-branch').value;
          if (!name) { toast(t('sysusers.enterName'), 'error'); return; }
          if (role !== 'super_admin' && !clinic_id) { toast(t('sysusers.chooseClinic'), 'error'); return; }
          const payload = {
            name, role,
            clinic_id: clinic_id ? Number(clinic_id) : null,
            branch_id: branch_id ? Number(branch_id) : null,
          };
          const pass = m.querySelector('#um-pass').value.trim();
          if (pass) payload.password = pass;
          if (isNew) {
            payload.email = m.querySelector('#um-email').value.trim();
            if (!payload.email || !pass) { toast(t('sysusers.emailPassRequired'), 'error'); return; }
          } else {
            payload.active = m.querySelector('#um-active').checked;
          }
          if (avatarState.clear) payload.avatar = '';
          const btn = m.querySelector('.modal-foot .btn-primary');
          btn.disabled = true; btn.innerHTML = '<div class="spinner"></div>';
          try {
            const saved = isNew ? await api.post('/admin/users', payload)
              : await api.patch(`/admin/users/${u.id}`, payload);
            if (avatarState.file) {
              const fd = new FormData(); fd.append('file', avatarState.file);
              try { await api.post(`/admin/users/${saved.id}/avatar`, fd); }
              catch (e) { toast(t('sysusers.savedPhotoFailed'), 'warn'); }
            }
            toast(isNew ? t('sysusers.userCreated') : t('sysusers.userUpdated'), 'success');
            close(); onSaved();
          } catch (ex) {
            toast(ex.detail || t('sysusers.saveFailed'), 'error');
            btn.disabled = false; btn.textContent = isNew ? t('sysusers.createUser') : t('sysusers.saveChanges');
          }
        } },
    ],
  });

  // rebuild branch options when the clinic changes
  const root = dlg.el;
  bindPasswordEyes(root);
  const avatarState = bindAvatarPicker(root, 'um-av', u ? u.name : '');
  root.querySelector('#um-name').oninput = (e) => { avatarState.name = e.target.value; };
  root.querySelector('#um-clinic').onchange = (e) => {
    root.querySelector('#um-branch').innerHTML = branchOptionsFor(e.target.value, '');
  };
}
