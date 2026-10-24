/* Blinks Bright — System console: manage every clinic (Tier 1, super_admin) */

import { api } from '../api.js';
import { icon, escapeHtml, initials, num, money, toast, modal, confirmDialog,
         loadingBlock, emptyState, avatarField, bindAvatarPicker } from '../ui.js';
import { t } from '../i18n.js';

const SWATCHES = ['#4E57C4', '#17788E', '#8E6FE0', '#2BA8C4',
                  '#C4455F', '#E0A341', '#2F7D5E', '#E0719E'];

export default async function renderSystemClinics(mount) {
  mount.innerHTML = `<div class="view">
    <div class="view-head">
      <div><h2>${t('sysclin.title')}</h2><p>${t('sysclin.subtitle')}</p></div>
      <button class="btn btn-primary" id="sc-new">${icon('plus', 16)}<span>${t('sysclin.newClinic')}</span></button>
    </div>
    <div id="sc-body">${loadingBlock()}</div>
  </div>`;

  const body = mount.querySelector('#sc-body');
  mount.querySelector('#sc-new').onclick = () => clinicModal(null, () => load(body));
  load(body);
}

async function load(body) {
  body.innerHTML = loadingBlock();
  let clinics;
  try { clinics = await api.get('/admin/clinics'); }
  catch (e) { body.innerHTML = emptyState('alert', t('sysclin.loadFailed')); return; }
  if (!clinics.length) { body.innerHTML = emptyState('building', t('sysclin.emptyTitle'), t('sysclin.emptySub')); return; }

  body.innerHTML = `<div class="card"><table class="table">
    <thead><tr><th>${t('sysclin.colClinic')}</th><th>${t('sysclin.colBranches')}</th><th>${t('sysclin.colStaff')}</th><th>${t('sysclin.colCustomers')}</th><th>${t('sysclin.colDepositPaid')}</th><th>${t('sysclin.colPaid')}</th><th>${t('sysclin.colRevenue')}</th><th>${t('common.status')}</th><th></th></tr></thead>
    <tbody>
      ${clinics.map((c) => `<tr data-id="${c.id}">
        <td><div class="row gap-2">
          <span class="avatar sm clinic-mark" style="background:${escapeHtml(c.accent || 'var(--primary)')};color:#fff">${
            c.logo ? `<img src="${escapeHtml(c.logo)}" alt="">` : escapeHtml(initials(c.name))}</span>
          <div><div class="strong">${escapeHtml(c.name)}</div>
            <div class="muted text-sm">${escapeHtml(c.tagline || '/' + c.slug)}</div></div></div></td>
        <td>${num(c.branch_count)}</td>
        <td>${num(c.staff)}</td>
        <td>${num(c.customers)}</td>
        <td>${num(c.deposit_paid)}</td>
        <td>${num(c.paid)}</td>
        <td class="strong">${money(c.revenue)}</td>
        <td><span class="badge ${c.status === 'active' ? 'badge-paid' : 'badge-soft'}">${
          c.status === 'active' ? t('common.active') : t('sysclin.statusArchived')}</span></td>
        <td style="text-align:right"><div class="row gap-1" style="justify-content:flex-end">
          ${c.status === 'active'
            ? `<button class="btn btn-ghost btn-sm" data-open="${c.id}">${icon('arrow-right', 14)}<span>${t('sysclin.open')}</span></button>`
            : `<button class="btn btn-ghost btn-sm" data-restore="${c.id}">${icon('refresh', 14)}<span>${t('sysclin.restore')}</span></button>`}
          <button class="btn-icon btn-subtle" data-edit="${c.id}" title="${t('common.edit')}">${icon('edit', 15)}</button>
          ${c.status === 'active'
            ? `<button class="btn-icon btn-subtle" data-archive="${c.id}" data-name="${escapeHtml(c.name)}" title="${t('sysclin.archive')}">${icon('trash', 15)}</button>`
            : `<button class="btn-icon btn-subtle" data-delete="${c.id}" data-name="${escapeHtml(c.name)}" title="${t('sysclin.deletePermanently')}" style="color:#c0552f">${icon('trash', 15)}</button>`}
        </div></td>
      </tr>`).join('')}
    </tbody></table></div>`;

  const byId = (id) => clinics.find((x) => String(x.id) === String(id));
  body.querySelectorAll('[data-open]').forEach((b) => {
    b.onclick = async () => {
      b.disabled = true; b.innerHTML = '<div class="spinner"></div>';
      try { await api.post(`/clinics/${b.dataset.open}/enter`); location.reload(); }
      catch (ex) { toast(ex.detail || t('sysclin.openFailed'), 'error'); load(body); }
    };
  });
  body.querySelectorAll('[data-edit]').forEach((b) =>
    (b.onclick = () => clinicModal(byId(b.dataset.edit), () => load(body))));
  body.querySelectorAll('[data-restore]').forEach((b) =>
    (b.onclick = async () => {
      try { await api.patch(`/admin/clinics/${b.dataset.restore}`, { status: 'active' });
        toast(t('sysclin.restored'), 'success'); load(body); }
      catch (ex) { toast(ex.detail || t('sysclin.restoreFailed'), 'error'); }
    }));
  body.querySelectorAll('[data-archive]').forEach((b) =>
    (b.onclick = async () => {
      const ok = await confirmDialog({
        title: t('sysclin.archiveTitle'),
        message: t('sysclin.archiveMsg', { name: b.dataset.name }),
        confirmLabel: t('sysclin.archive'), danger: true,
      });
      if (!ok) return;
      try { await api.del(`/admin/clinics/${b.dataset.archive}`);
        toast(t('sysclin.archived'), 'success'); load(body); }
      catch (ex) { toast(ex.detail || t('sysclin.archiveFailed'), 'error'); }
    }));
  body.querySelectorAll('[data-delete]').forEach((b) =>
    (b.onclick = async () => {
      const ok = await confirmDialog({
        title: t('sysclin.deleteTitle'),
        message: t('sysclin.deleteMsg', { name: b.dataset.name }),
        confirmLabel: t('sysclin.deleteForever'), danger: true,
      });
      if (!ok) return;
      try { await api.del(`/admin/clinics/${b.dataset.delete}/purge`);
        toast(t('sysclin.deletedPermanently'), 'success'); load(body); }
      catch (ex) { toast(ex.detail || t('common.deleteFailed'), 'error'); }
    }));
}

function clinicModal(c, onSaved) {
  const isNew = !c;
  const current = (c && /^#[0-9a-f]{6}$/i.test(c.accent || '')) ? c.accent : '#4E57C4';
  const swatches = SWATCHES.map((hex) =>
    `<button type="button" class="ec-swatch${hex.toLowerCase() === current.toLowerCase() ? ' on' : ''}"
       data-hex="${hex}" style="background:${hex}" title="${hex}"></button>`).join('');

  const dlg = modal({
    title: isNew ? t('sysclin.newClinic') : t('sysclin.editClinic'),
    body: `
      ${avatarField(c ? c.name : t('sysclin.clinicFallback'), c ? c.logo : '', 'cm-img', t('sysclin.clinicImage'))}
      <div class="field"><label>${t('sysclin.clinicName')}</label>
        <input class="input" id="cm-name" value="${c ? escapeHtml(c.name) : ''}" placeholder="${t('sysclin.namePlaceholder')}" autofocus></div>
      <div class="field"><label>${t('sysclin.tagline')} <span class="muted">${t('common.optional')}</span></label>
        <input class="input" id="cm-tag" value="${c ? escapeHtml(c.tagline || '') : ''}" placeholder="${t('sysclin.taglinePlaceholder')}"></div>
      <div class="field"><label>${t('sysclin.brandAccent')}</label>
        <div class="ec-swatches" id="cm-swatches">${swatches}
          <label class="ec-custom" title="${t('sysclin.customColour')}"><input type="color" id="cm-color" value="${current}">${icon('plus', 14)}</label>
        </div>
        <input type="hidden" id="cm-accent" value="${escapeHtml(current)}"></div>
      ${isNew ? `<div class="field-hint">${t('sysclin.starterHint')}</div>` : ''}`,
    actions: [
      { label: t('common.cancel'), class: 'btn-ghost' },
      { label: isNew ? t('sysclin.createClinic') : t('sysclin.saveChanges'), class: 'btn-primary', keepOpen: true,
        onClick: async ({ close, modal: m }) => {
          const name = m.querySelector('#cm-name').value.trim();
          if (!name) { toast(t('sysclin.enterName'), 'error'); return; }
          const payload = {
            name,
            tagline: m.querySelector('#cm-tag').value.trim(),
            accent: m.querySelector('#cm-accent').value,
          };
          if (imgState.clear) payload.logo = '';
          const btn = m.querySelector('.modal-foot .btn-primary');
          btn.disabled = true; btn.innerHTML = '<div class="spinner"></div>';
          try {
            const saved = isNew ? await api.post('/admin/clinics', payload)
              : await api.patch(`/admin/clinics/${c.id}`, payload);
            if (imgState.file) {
              const fd = new FormData(); fd.append('file', imgState.file);
              try { await api.post(`/clinics/${saved.id}/logo`, fd); }
              catch (e) { toast(t('sysclin.imageUploadFailed'), 'warn'); }
            }
            toast(isNew ? t('sysclin.created') : t('common.updated'), 'success');
            close(); onSaved();
          } catch (ex) {
            toast(ex.detail || t('common.saveFailed'), 'error');
            btn.disabled = false; btn.textContent = isNew ? t('sysclin.createClinic') : t('sysclin.saveChanges');
          }
        } },
    ],
  });

  const root = dlg.el;
  const imgState = bindAvatarPicker(root, 'cm-img', c ? c.name : t('sysclin.clinicFallback'));
  const accentInput = root.querySelector('#cm-accent');
  const clearActive = () => root.querySelectorAll('.ec-swatch').forEach((x) => x.classList.remove('on'));
  root.querySelectorAll('.ec-swatch').forEach((s) =>
    (s.onclick = () => { accentInput.value = s.dataset.hex; clearActive(); s.classList.add('on'); }));
  root.querySelector('#cm-color').onchange = (e) => { accentInput.value = e.target.value; clearActive(); };
}
