/* Blinks Bright — Clinic Picker (workspace lobby, shown before the app shell) */

import { api } from '../api.js';
import { store } from '../store.js';
import { icon, escapeHtml, initials, toast, modal, confirmDialog,
         loadingBlock, projectFooter } from '../ui.js';
import { t, langToggle, bindLangToggle } from '../i18n.js';

/* Curated brand-accent palette for the edit dialog (drawn from the design tokens). */
const SWATCHES = ['#4E57C4', '#17788E', '#8E6FE0', '#2BA8C4',
                  '#C4455F', '#E0A341', '#2F7D5E', '#E0719E'];

/* Default cover photography (used until a clinic has its own uploaded cover). */
const COVERS = [
  '/assets/images/treatment-room.png',
  '/assets/images/treatment-facial.png',
  '/assets/images/treatment-skinbooster.png',
  '/assets/images/background.png',
  '/assets/images/treatment-laser.png',
  '/assets/images/treatment-filler.png',
];

export default function renderClinics(app) {
  const firstName = escapeHtml((store.user?.name || '').split(' ')[0] || t('picker.guestName'));
  app.innerHTML = `
  <div class="picker-page">
    <div class="picker-top">
      <div class="row gap-2">
        <div class="logo-mark"><img src="/assets/images/logo_b.png?v=5" alt="R"
             onerror="this.replaceWith(document.createTextNode('R'))"></div>
        <strong style="font-size:15px;letter-spacing:-.01em">Blinks Bright</strong>
      </div>
      <div class="row gap-2">
        ${langToggle()}
        <button class="btn btn-ghost btn-sm" id="pk-logout">
          ${icon('logout', 15)}<span>${t('picker.logout')}</span></button>
      </div>
    </div>
    <div class="picker-body">
      <div class="picker-head">
        <span class="picker-eyebrow">${t('picker.eyebrow')}</span>
        <h1>${t('picker.chooseTitle')}</h1>
        <p>${t('picker.chooseSub', { name: firstName })}</p>
      </div>
      <div class="clinic-grid" id="clinic-grid">${loadingBlock()}</div>
    </div>
    ${projectFooter()}
  </div>`;

  bindLangToggle(app);

  app.querySelector('#pk-logout').onclick = async () => {
    try { await api.post('/auth/logout'); } catch (e) { /* ignore */ }
    location.reload();
  };

  loadClinics(app);
}

async function loadClinics(app) {
  const grid = app.querySelector('#clinic-grid');
  let data;
  try { data = await api.get('/clinics'); }
  catch (e) {
    grid.innerHTML = `<div class="empty-state">${icon('alert', 40)}
      <div class="es-title">${t('picker.loadFail')}</div></div>`;
    return;
  }

  const cards = data.clinics.map((c, i) => clinicCard(c, data.can_manage, i)).join('');
  const newCard = data.can_manage ? `
    <button class="clinic-card cc-new" id="cc-new">
      <div class="cc-plus">${icon('plus', 26)}</div>
      <div class="strong">${t('picker.newClinic')}</div>
      <div class="muted text-sm">${t('picker.newClinicSub')}</div>
    </button>` : '';

  if (!data.clinics.length && !data.can_manage) {
    grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1">${icon('building', 40)}
      <div class="es-title">${t('picker.noClinicTitle')}</div>
      <div>${t('picker.noClinicSub')}</div></div>`;
    return;
  }
  grid.innerHTML = cards + newCard;

  grid.querySelectorAll('[data-enter]').forEach((b) => {
    b.onclick = async () => {
      b.disabled = true;
      b.innerHTML = '<div class="spinner"></div>';
      try {
        await api.post(`/clinics/${b.dataset.enter}/enter`);
        location.reload();
      } catch (ex) {
        toast(ex.detail || t('picker.openFail'), 'error');
        b.disabled = false;
        b.innerHTML = `<span>${t('picker.enterClinic')}</span>${icon('arrow-right', 16)}`;
      }
    };
  });
  grid.querySelectorAll('[data-edit]').forEach((b) => {
    b.onclick = () => {
      const c = data.clinics.find((x) => String(x.id) === b.dataset.edit);
      if (c) editClinic(app, c);
    };
  });
  grid.querySelectorAll('[data-del]').forEach((b) => {
    b.onclick = async () => {
      const ok = await confirmDialog({
        title: t('picker.removeTitle'),
        message: t('picker.removeMsg', { name: b.dataset.name }),
        confirmLabel: t('picker.removeTitle'), danger: true,
      });
      if (!ok) return;
      try {
        await api.del(`/clinics/${b.dataset.del}`);
        toast(t('picker.clinicRemoved'), 'success');
        loadClinics(app);
      } catch (ex) { toast(ex.detail || t('picker.removeFail'), 'error'); }
    };
  });
  grid.querySelectorAll('[data-logo]').forEach((inp) => {
    inp.onchange = () => {
      if (inp.files[0]) changeImage(app, 'logo', inp.dataset.logo, inp.files[0]);
    };
  });
  grid.querySelectorAll('[data-cover]').forEach((inp) => {
    inp.onchange = () => {
      if (inp.files[0]) changeImage(app, 'cover', inp.dataset.cover, inp.files[0]);
    };
  });
  const nc = grid.querySelector('#cc-new');
  if (nc) nc.onclick = () => createClinic(app);
}

function clinicCard(c, canManage, i) {
  const accent = c.accent || 'var(--primary)';
  const cover = c.cover || COVERS[i % COVERS.length];
  const inner = c.logo
    ? `<img src="${escapeHtml(c.logo)}" alt="">`
    : escapeHtml(initials(c.name));
  const logoEl = canManage
    ? `<label class="cc-logo cc-logo-edit" title="${t('picker.changeLogo')}">
         <input type="file" accept="image/png,image/jpeg,image/webp" hidden data-logo="${c.id}">
         ${inner}<span class="cc-logo-cam">${icon('edit', 14)}</span></label>`
    : `<div class="cc-logo">${inner}</div>`;
  const coverInner = `
    <img class="cc-cover-img" src="${escapeHtml(cover)}" alt="" loading="lazy"
         onerror="this.style.visibility='hidden'">
    <div class="cc-cover-wash"></div>`;
  const coverEl = canManage
    ? `<label class="cc-cover cc-cover-edit" title="${t('picker.changeCover')}">
         <input type="file" accept="image/png,image/jpeg,image/webp" hidden data-cover="${c.id}">
         ${coverInner}
         <span class="cc-cover-hint">${icon('image', 14)}<span>${t('picker.changeCoverShort')}</span></span>
       </label>`
    : `<div class="cc-cover">${coverInner}</div>`;
  const tools = canManage ? `
    <div class="cc-tools">
      <button class="cc-tool" data-edit="${c.id}" title="${t('picker.editClinic')}">${icon('edit', 14)}</button>
      <button class="cc-tool cc-tool-danger" data-del="${c.id}"
        data-name="${escapeHtml(c.name)}" title="${t('picker.removeTitle')}">${icon('trash', 14)}</button>
    </div>` : '';
  return `<div class="clinic-card" style="--cc-accent:${escapeHtml(accent)}">
    <div class="cc-banner">
      ${coverEl}
      ${tools}
    </div>
    <div class="cc-body">
      <div class="cc-badge-row">${logoEl}</div>
      <div class="cc-name">${escapeHtml(c.name)}</div>
      <div class="cc-tag">${escapeHtml(c.tagline || t('picker.aestheticClinic'))}</div>
      <div class="cc-stats">
        <span>${icon('building', 13)} ${c.branches} ${c.branches === 1 ? t('picker.branch') : t('picker.branches')}</span>
        <span>${icon('users', 13)} ${c.customers}</span>
        <span>${icon('user', 13)} ${c.staff}</span>
      </div>
      <button class="btn btn-primary btn-block cc-enter" data-enter="${c.id}">
        <span>${t('picker.enterClinic')}</span>${icon('arrow-right', 16)}</button>
    </div>
  </div>`;
}

async function changeImage(app, kind, id, file) {
  const fd = new FormData();
  fd.append('file', file);
  try {
    await api.post(`/clinics/${id}/${kind}`, fd);
    toast(kind === 'cover' ? t('picker.coverUpdated') : t('picker.logoUpdated'), 'success');
    loadClinics(app);
  } catch (ex) { toast(ex.detail || t('picker.uploadFail'), 'error'); }
}

function editClinic(app, c) {
  const current = (c.accent && /^#[0-9a-f]{6}$/i.test(c.accent)) ? c.accent : '#4E57C4';
  const swatches = SWATCHES.map((hex) =>
    `<button type="button" class="ec-swatch${hex.toLowerCase() === current.toLowerCase() ? ' on' : ''}"
       data-hex="${hex}" style="background:${hex}" title="${hex}"></button>`).join('');

  modal({
    title: t('picker.editClinic'),
    body: `
      <div class="field"><label>${t('picker.clinicName')}</label>
        <input class="input" id="ec-name" value="${escapeHtml(c.name)}" autofocus></div>
      <div class="field"><label>${t('picker.tagline')} <span class="muted">${t('common.optional')}</span></label>
        <input class="input" id="ec-tag" value="${escapeHtml(c.tagline || '')}"
          placeholder="${t('picker.taglinePh')}"></div>
      <div class="field"><label>${t('picker.brandAccent')}</label>
        <div class="ec-swatches" id="ec-swatches">${swatches}
          <label class="ec-custom" title="${t('picker.customColour')}">
            <input type="color" id="ec-color" value="${current}">${icon('plus', 14)}
          </label>
        </div>
        <input type="hidden" id="ec-accent" value="${escapeHtml(current)}"></div>
      <div class="field-hint">${t('picker.editHint')}</div>`,
    actions: [
      { label: t('common.cancel'), class: 'btn-ghost' },
      { label: t('picker.saveChanges'), class: 'btn-primary', keepOpen: true,
        onClick: async ({ close, modal: m }) => {
          const name = m.querySelector('#ec-name').value.trim();
          if (!name) { toast(t('picker.enterName'), 'error'); return; }
          const btn = m.querySelector('.modal-foot .btn-primary');
          btn.disabled = true;
          btn.innerHTML = '<div class="spinner"></div>';
          try {
            await api.patch(`/clinics/${c.id}`, {
              name,
              tagline: m.querySelector('#ec-tag').value.trim(),
              accent: m.querySelector('#ec-accent').value,
            });
            toast(t('picker.clinicUpdated'), 'success');
            close();
            loadClinics(app);
          } catch (ex) {
            toast(ex.detail || t('picker.saveChangesFail'), 'error');
            btn.disabled = false;
            btn.textContent = t('picker.saveChanges');
          }
        } },
    ],
  });

  const swEl = document.getElementById('ec-swatches');
  const accentInput = document.getElementById('ec-accent');
  const colorInput = document.getElementById('ec-color');
  const clearActive = () => swEl.querySelectorAll('.ec-swatch').forEach((x) => x.classList.remove('on'));
  swEl.querySelectorAll('.ec-swatch').forEach((s) => {
    s.onclick = () => { accentInput.value = s.dataset.hex; clearActive(); s.classList.add('on'); };
  });
  colorInput.onchange = () => { accentInput.value = colorInput.value; clearActive(); };
}

function createClinic(app) {
  modal({
    title: t('picker.newClinic'),
    body: `
      <div class="field"><label>${t('picker.clinicName')}</label>
        <input class="input" id="nc-name" placeholder="${t('picker.namePh')}" autofocus></div>
      <div class="field"><label>${t('picker.tagline')} <span class="muted">${t('common.optional')}</span></label>
        <input class="input" id="nc-tag" placeholder="${t('picker.taglinePh')}"></div>
      <div class="field"><label>${t('picker.businessImage')} <span class="muted">${t('common.optional')}</span></label>
        <label class="nc-logo-pick">
          <input type="file" accept="image/png,image/jpeg,image/webp" hidden id="nc-logo">
          <span class="nc-logo-preview" id="nc-logo-preview">${icon('building', 22)}</span>
          <span class="muted text-sm" id="nc-logo-label">${t('picker.uploadHint')}</span>
        </label></div>
      <div class="field-hint">${t('picker.newClinicHint')}</div>`,
    actions: [
      { label: t('common.cancel'), class: 'btn-ghost' },
      { label: t('picker.createClinic'), class: 'btn-primary', keepOpen: true,
        onClick: async ({ close, modal: m }) => {
          const name = m.querySelector('#nc-name').value.trim();
          if (!name) { toast(t('picker.enterName'), 'error'); return; }
          const btn = m.querySelector('.modal-foot .btn-primary');
          btn.disabled = true;
          btn.innerHTML = '<div class="spinner"></div>';
          try {
            const clinic = await api.post('/clinics', {
              name, tagline: m.querySelector('#nc-tag').value.trim(),
            });
            const f = m.querySelector('#nc-logo').files[0];
            if (f) {
              const fd = new FormData();
              fd.append('file', f);
              try { await api.post(`/clinics/${clinic.id}/logo`, fd); }
              catch (e) { toast(t('picker.createdImageFail'), 'warn'); }
            }
            toast(t('picker.clinicCreated'), 'success');
            close();
            loadClinics(app);
          } catch (ex) {
            toast(ex.detail || t('picker.createFail'), 'error');
            btn.disabled = false;
            btn.textContent = t('picker.createClinic');
          }
        } },
    ],
  });

  const inp = document.getElementById('nc-logo');
  if (inp) inp.onchange = () => {
    const f = inp.files[0];
    if (!f) return;
    const r = new FileReader();
    r.onload = () => {
      document.getElementById('nc-logo-preview').innerHTML = `<img src="${r.result}" alt="">`;
      document.getElementById('nc-logo-label').textContent = f.name;
    };
    r.readAsDataURL(f);
  };
}
