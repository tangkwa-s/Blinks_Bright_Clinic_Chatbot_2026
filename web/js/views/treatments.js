/* Blinks Bright — Treatments: the live service menu the AI sells, prices & books from */

import { api } from '../api.js';
import { store } from '../store.js';
import { icon, toast, modal, escapeHtml, money, emptyState, loadingBlock,
         confirmDialog, debounce, isEveryBranch, branchSummaryText,
         branchCheckboxListHtml, wireCheckAll } from '../ui.js';
import { t } from '../i18n.js';

let services = [];
let filterCat = 'all';
let search = '';
let root = null;
let canEdit = false;

export default async function renderTreatments(mount) {
  root = mount;
  canEdit = store.canManage() || store.isRole('marketing');
  mount.innerHTML = `<div class="view">
    <div class="view-head">
      <div>
        <h2>${t('treat.title')}</h2>
        <p>${t('treat.subtitle')}</p>
      </div>
      <div class="row gap-2">
        ${canEdit ? `<button class="btn btn-ghost" id="tx-sync">${icon('refresh')}<span>${t('treat.syncAI')}</span></button>` : ''}
      </div>
    </div>
    <div class="grid grid-4" id="tx-stats" style="margin-bottom:20px"></div>
    <div class="tx-toolbar">
      <div class="tx-cats" id="tx-cats"></div>
      <div class="row gap-2">
        <div class="search-box tx-search" style="position:relative">${icon('search', 16)}
          <input class="input" id="tx-search-input" placeholder="${t('treat.searchPlaceholder')}" value="${escapeHtml(search)}" style="padding-right:36px">
          <button type="button" id="tx-search-clear" title="${t('common.clear')}"
            style="position:absolute;right:12px;top:50%;transform:translateY(-50%);width:20px;height:20px;
              display:${search ? 'flex' : 'none'};align-items:center;justify-content:center;
              border:none;background:transparent;padding:0;border-radius:var(--r-sm);color:var(--muted);cursor:pointer">
            ${icon('close', 14)}</button>
        </div>
        ${canEdit ? `<button class="btn btn-primary" id="tx-add">${icon('plus', 16)}<span>${t('treat.addTreatment')}</span></button>` : ''}
      </div>
    </div>
    <div id="tx-body" class="results-min-grid">${loadingBlock()}</div>
  </div>`;

  const addBtn = mount.querySelector('#tx-add');
  if (addBtn) addBtn.onclick = () => serviceModal(null);
  const syncBtn = mount.querySelector('#tx-sync');
  if (syncBtn) syncBtn.onclick = () => syncAI(syncBtn);
  const searchInput = mount.querySelector('#tx-search-input');
  const searchClear = mount.querySelector('#tx-search-clear');
  const debouncedSearch = debounce(() => { search = searchInput.value.trim().toLowerCase(); renderGrid(); }, 180);
  searchInput.oninput = () => {
    searchClear.style.display = searchInput.value ? 'flex' : 'none';
    debouncedSearch();
  };
  searchClear.onclick = () => {
    searchInput.value = '';
    searchClear.style.display = 'none';
    searchInput.focus();
    search = '';
    renderGrid();
  };

  await reload();
}

async function reload() {
  try { services = await api.get('/services'); } catch (e) { services = []; }
  loadStats();
  renderCats();
  renderGrid();
}

async function loadStats() {
  const total = services.length;
  const active = services.filter((s) => s.active).length;
  const cats = new Set(services.map((s) => s.category).filter(Boolean)).size;
  let indexed = '—';
  try { const o = await api.get('/knowledge/overview'); indexed = `${o.embedded}/${o.chunks}`; } catch (e) { /* ignore */ }
  const el = root.querySelector('#tx-stats');
  if (!el) return;
  el.innerHTML = [
    [t('treat.title'), total, 'spark', 'var(--chart-2)', ''],
    [t('common.active'), active, 'check-circle', 'var(--chart-3)', ''],
    [t('treat.statCategories'), cats, 'sliders', 'var(--chart-1)', ''],
    [t('treat.statAiKnowledge'), indexed, 'ai', 'var(--chart-4)',
     t('treat.aiKnowledgeTip')],
  ].map(([label, val, ic, color, tip]) => `
    <div class="stat-card" style="--ic:${color}"${tip ? ` title="${escapeHtml(tip)}"` : ''}>
      <div class="stat-top"><span class="stat-label">${label}</span>
        <span class="stat-ic">${icon(ic, 16)}</span></div>
      <div class="stat-value">${val}</div>
    </div>`).join('');
}

function renderCats() {
  const el = root.querySelector('#tx-cats');
  if (!el) return;
  const cats = [...new Set(services.map((s) => s.category).filter(Boolean))].sort();
  if (filterCat !== 'all' && !cats.includes(filterCat)) filterCat = 'all';
  const pill = (key, label) =>
    `<button class="tx-cat${filterCat === key ? ' active' : ''}" data-cat="${escapeHtml(key)}">${escapeHtml(label)}</button>`;
  el.innerHTML = pill('all', t('common.all')) + cats.map((c) => pill(c, c)).join('');
  el.querySelectorAll('[data-cat]').forEach((b) => {
    b.onclick = () => {
      filterCat = b.dataset.cat;
      el.querySelectorAll('[data-cat]').forEach((x) => x.classList.toggle('active', x === b));
      renderGrid();
    };
  });
}

function renderGrid() {
  const body = root.querySelector('#tx-body');
  if (!body) return;
  let list = services.slice();
  // No in-page branch filter — the topbar's own branch selector narrows the menu.
  if (store.branchId && store.branchId !== 'all') {
    const bid = Number(store.branchId);
    list = list.filter((s) => !s.branch_ids.length || s.branch_ids.includes(bid));
  }
  if (filterCat !== 'all') list = list.filter((s) => s.category === filterCat);
  if (search) list = list.filter((s) => s.name.toLowerCase().includes(search));

  if (!list.length) {
    body.innerHTML = `<div class="card">${emptyState('spark',
      services.length ? t('treat.noMatches') : t('treat.noTreatmentsYet'),
      services.length ? t('treat.noMatchesSub')
        : (canEdit ? t('treat.emptyEditSub') : t('treat.emptyViewSub')))}</div>`;
    return;
  }
  body.innerHTML = `<div class="grid grid-3">${list.map((s) => card(s)).join('')}</div>`;
  if (canEdit) body.querySelectorAll('[data-id]').forEach((c) => {
    c.onclick = () => serviceModal(services.find((s) => s.id === Number(c.dataset.id)));
  });
}

function card(s) {
  const bg = s.image ? `style="background-image:url('${escapeHtml(s.image)}')"` : '';
  return `<div class="card tx-card${s.active ? '' : ' is-hidden'}" data-id="${s.id}"
       style="overflow:hidden;cursor:${canEdit ? 'pointer' : 'default'}">
    <div class="tx-thumb" ${bg}>
      ${s.image ? '' : `<span class="tx-thumb-ph">${icon('spark', 28)}</span>`}
      ${s.active ? '' : `<span class="tx-flag">${t('treat.hidden')}</span>`}
    </div>
    <div class="card-pad">
      <div class="row-between">
        <span class="chip">${escapeHtml(s.category || t('treat.general'))}</span>
        <span class="strong">${money(s.base_price)}</span>
      </div>
      <div class="strong" style="margin:8px 0 4px">${escapeHtml(s.name)}</div>
      ${s.branch_ids.length && store.branches.length > 1
        ? `<div class="muted text-sm truncate">${icon('building', 13)} ${
            escapeHtml(s.branch_ids.map((id) => store.branchName(id)).join(', '))}</div>` : ''}
      <div class="muted text-sm truncate">${escapeHtml(s.description || t('treat.noDescription'))}</div>
      <div class="tx-meta">${icon('clock', 13)} ${s.duration_min} ${t('treat.minUnit')}${
        s.recommended_interval_days ? ` · ${t('treat.repeatEvery', { n: s.recommended_interval_days })}` : ''}</div>
    </div>
  </div>`;
}

async function syncAI(btn) {
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<div class="spinner"></div>';
  try {
    const r = await api.post('/knowledge/reindex');
    toast(t('treat.aiSynced', { n: r.chunks }), 'success');
    loadStats();
  } catch (ex) { toast(ex.detail || t('treat.syncFailed'), 'error'); }
  btn.disabled = false;
  btn.innerHTML = orig;
}

function serviceModal(svc) {
  const isNew = !svc;
  const s = svc || { id: null, name: '', category: '', description: '', base_price: 0,
    duration_min: 45, recommended_interval_days: 0, prep_notes: '', aftercare_notes: '',
    contraindications: '', image: '', active: true, deposit: 0, hold_minutes: 0,
    prices: {}, branch_ids: [] };
  let stagedFile = null;   // a chosen-but-not-yet-uploaded photo
  let removeImg = false;   // user cleared the existing photo

  // A category is not a record — it is just a string on each service, so this list is
  // derived from whatever the treatments currently carry.
  const cats = [...new Set(services.map((x) => x.category).filter(Boolean))].sort();
  const fld = (label, id, val, type = 'text', attrs = '') =>
    `<div class="field"><label>${label}</label><input class="input" id="${id}" type="${type}" value="${escapeHtml(val)}" ${attrs}></div>`;
  const area = (label, id, val) =>
    `<div class="field"><label>${label}</label><textarea class="textarea" id="${id}" rows="2">${escapeHtml(val)}</textarea></div>`;

  // Sane limits so a typo / paste can't store an absurd value (mirrored server-side).
  const MAX_DURATION = 1440;     // one full day (minutes)
  const MAX_INTERVAL = 3650;     // ten years (days)
  const MAX_PRICE = 10000000;    // ฿10M
  const MAX_HOLD_MINUTES = 180;  // mirrors app/services/booking.py::MAX_HOLD_MINUTES
  const basePrice0 = Number(s.base_price) || 0;

  // A stored per-branch price equal to the base price is an implicit seed, not a
  // real override — show it blank so saving doesn't echo a stale copy back (which
  // used to pin the old price after a base-price edit).
  const bpVal = (bid) => {
    const v = s.prices ? s.prices[bid] : null;
    return (v != null && Number(v) !== basePrice0) ? v : '';
  };
  // Default branches checked: for a new treatment, the topbar's current branch
  // (so adding while scoped to one branch defaults the new treatment to it);
  // for an existing one, whatever it's already restricted to. Checking EVERY
  // branch collapses to "all branches" (see isEveryBranch/branchSummaryText).
  const allBranchIds = store.branches.map((b) => b.id);
  const initialChecked = new Set(
    isNew
      ? ((store.branchId && store.branchId !== 'all') ? [Number(store.branchId)] : allBranchIds)
      : (s.branch_ids.length ? s.branch_ids : allBranchIds));
  const multiBranch = store.branches.length > 1;
  const isAutoAll = isEveryBranch;
  const branchField = multiBranch ? `
    <div class="field"><label>${t('menu.branch')}</label>
      <details class="tx-branch-msel" id="tx-branch-msel">
        <summary class="input"><span class="tx-branch-summary-text" id="tx-branch-summary">${
          escapeHtml(branchSummaryText([...initialChecked]))}</span></summary>
        <div class="tx-branch-msel-panel">${branchCheckboxListHtml('branch-chk', [...initialChecked])}</div>
      </details>
      <div class="field-hint">${t('treat.branchMultiHint')}</div>
    </div>` : '';
  // The branches a price-override row makes sense for: every branch when
  // unrestricted ("Auto"), else exactly the checked ones. A single branch
  // (checked or the clinic's only one) never needs its own row — the base
  // price already applies there and nowhere else.
  const effectiveBranches = (checked) => (isAutoAll(checked) ? allBranchIds : checked);
  const bpValues = {};   // branchId -> currently-typed price string, preserved as rows come/go
  store.branches.forEach((b) => { bpValues[b.id] = bpVal(b.id); });
  const renderBpRows = (branchIds) => branchIds.map((bid) => {
    const b = store.branches.find((x) => x.id === bid);
    return `<div class="tx-bp-row">
      <span class="muted text-sm truncate">${escapeHtml(b.name)}</span>
      <input class="input" type="number" data-bprice="${bid}"
        min="1" max="${MAX_PRICE}"
        value="${bpValues[bid] || ''}"
        placeholder="${s.base_price || 0}">
    </div>`;
  }).join('');
  const initialEffective = effectiveBranches([...initialChecked]);
  const perBranch = multiBranch ? `
    <div class="field" id="tx-perbranch-wrap"${initialEffective.length > 1 ? '' : ' style="display:none"'}>
      <label>${t('treat.perBranchPrice')} <span class="muted">${t('treat.perBranchHint')}</span></label>
      <div class="tx-branch-prices">${initialEffective.length > 1 ? renderBpRows(initialEffective) : ''}</div>
    </div>` : '';

  const m = modal({
    title: isNew ? t('treat.newTreatment') : t('treat.editTreatment'),
    wide: true,
    body: `
      <div class="tx-img-pick">
        <div class="tx-img-prev" id="tx-img-prev">${
          s.image ? `<img src="${escapeHtml(s.image)}" alt="">` : icon('spark', 28)}</div>
        <div class="tx-img-side">
          <div class="row gap-2">
            <label class="btn btn-ghost btn-sm">${icon('download', 15)}<span>${t('treat.uploadPhoto')}</span>
              <input type="file" accept="image/png,image/jpeg,image/webp" hidden id="tx-img-file"></label>
            <button type="button" class="btn btn-ghost btn-sm" id="tx-img-clear"
              ${s.image ? '' : 'style="display:none"'}>${icon('trash', 15)}<span>${t('common.remove')}</span></button>
          </div>
          <div class="field-hint">${t('treat.photoHint')}</div>
        </div>
      </div>
      ${fld(t('common.name'), 'f-name', s.name)}
      ${branchField}
      <div class="grid grid-3">
        <div class="field"><label>${t('treat.category')}</label>
          <div class="combo" id="f-cat-combo">
            <input class="input" id="f-cat" value="${escapeHtml(s.category)}" autocomplete="off"
              placeholder="${t('treat.categoryPlaceholder')}">
            ${cats.length ? `<button type="button" class="combo-caret" id="f-cat-caret"
              tabindex="-1" aria-label="${t('treat.categoryPick')}">${icon('chevron-down', 16)}</button>
            <div class="combo-list" id="f-cat-list" hidden>
              ${cats.map((c) => `<button type="button" class="combo-opt" data-v="${escapeHtml(c)}">${escapeHtml(c)}</button>`).join('')}
            </div>` : ''}
          </div>
        </div>
        ${fld(t('treat.basePrice'), 'f-price', s.base_price, 'number', `min="0" max="${MAX_PRICE}" step="1"`)}
        ${fld(t('treat.duration'), 'f-dur', s.duration_min, 'number', `min="0" max="${MAX_DURATION}" step="5"`)}
      </div>
      <div class="grid grid-2">
        ${fld(t('treat.recommendedInterval'), 'f-interval', s.recommended_interval_days, 'number', `min="0" max="${MAX_INTERVAL}" step="1"`)}
        <div class="field"><label>${t('treat.deposit')} <span class="muted">${t('treat.depositHint')}</span></label>
          <input class="input" id="f-deposit" type="number" min="0" ${basePrice0 > 0 ? `max="${basePrice0}"` : ''} value="${s.deposit || ''}"
            placeholder="${t('treat.auto')} ฿${Math.round(basePrice0 * 0.2 / 100) * 100}"></div>
      </div>
      <div class="field"><label>${t('treat.holdMinutes')} <span class="muted">${t('treat.holdMinutesHint')}</span></label>
        <input class="input" id="f-hold-minutes" type="number" min="0" max="${MAX_HOLD_MINUTES}"
          value="${s.hold_minutes || ''}" placeholder="${t('treat.inheritClinic')}"></div>
      ${area(t('treat.description'), 'f-desc', s.description)}
      ${perBranch}
      ${area(t('treat.prepNotes'), 'f-prep', s.prep_notes)}
      ${area(t('treat.aftercareNotes'), 'f-after', s.aftercare_notes)}
      ${area(t('treat.contraindications'), 'f-contra', s.contraindications)}
      <label class="row gap-2" style="cursor:pointer;margin-top:4px">
        <span class="toggle"><input type="checkbox" id="f-active" ${s.active ? 'checked' : ''}><span class="track"></span></span>
        <span>${t('treat.visibleOnMenu')}</span></label>`,
    actions: [
      ...(isNew ? [] : [{ label: t('common.delete'), class: 'btn-danger mfoot-left', keepOpen: true,
        onClick: async ({ close }) => {
          let message = t('treat.deleteConfirmMsg', { name: s.name });
          if (store.branches.length > 1) {
            const branches = s.branch_ids.length
              ? s.branch_ids.map((id) => store.branchName(id)).join(', ')
              : t('menu.allBranches');
            message += '\n' + t('treat.deleteConfirmBranches', { branches });
          }
          const ok = await confirmDialog({
            title: t('treat.deleteConfirmTitle'),
            message,
            confirmLabel: t('common.delete'), danger: true });
          if (!ok) return;
          try {
            const r = await api.del(`/services/${s.id}`);
            toast(r.archived ? t('treat.treatmentHidden') : t('treat.treatmentDeleted'), 'success');
            close(); await reload();
          } catch (ex) { toast(ex.detail || t('common.deleteFailed'), 'error'); }
        } }]),
      { label: t('common.cancel'), class: 'btn-ghost' },
      { label: t('common.save'), class: 'btn-primary', keepOpen: true, onClick: async ({ close, modal: mEl }) => {
        const name = mEl.querySelector('#f-name').value.trim();
        const checkedBoxes = [...mEl.querySelectorAll('[data-branch-chk]:checked')];
        const checkedIds = checkedBoxes.map((c) => Number(c.dataset.branchChk));
        // Selecting every branch (or none, e.g. a single-branch clinic with no
        // multi-select at all) means "all branches" — an empty branch_ids list.
        const branchIds = (!mEl.querySelector('[data-branch-chk]') || isAutoAll(checkedIds)) ? [] : checkedIds;
        const basePrice = Number(mEl.querySelector('#f-price').value) || 0;
        const duration = Number(mEl.querySelector('#f-dur').value) || 45;
        const interval = Number(mEl.querySelector('#f-interval').value) || 0;
        const deposit = Number(mEl.querySelector('#f-deposit').value) || 0;
        const holdMinutes = Number(mEl.querySelector('#f-hold-minutes').value) || 0;
        if (!name) return toast(t('treat.nameRequired'), 'error');
        // A name only collides with a treatment whose branch scope OVERLAPS this
        // one — disjoint branch subsets may reuse a name for their own version.
        const branchSet = new Set(branchIds);
        if (services.some((x) => x.id !== s.id
            && (!branchSet.size || !x.branch_ids.length || x.branch_ids.some((id) => branchSet.has(id)))
            && (x.name || '').trim().toLowerCase() === name.toLowerCase()))
          return toast(t('treat.nameDuplicate', { name }), 'error');
        if (basePrice < 0 || basePrice > MAX_PRICE) return toast(t('treat.basePriceRange', { max: MAX_PRICE.toLocaleString() }), 'error');
        if (duration < 0 || duration > MAX_DURATION) return toast(t('treat.durationRange', { max: MAX_DURATION }), 'error');
        if (interval < 0 || interval > MAX_INTERVAL) return toast(t('treat.intervalRange', { max: MAX_INTERVAL }), 'error');
        if (deposit < 0) return toast(t('treat.depositNegative'), 'error');
        if (deposit > basePrice) return toast(t('treat.depositExceeds'), 'error');
        if (holdMinutes < 0 || holdMinutes > MAX_HOLD_MINUTES)
          return toast(t('treat.holdMinutesRange', { max: MAX_HOLD_MINUTES }), 'error');
        // A branch price is an override, so it has to be a real amount: 0 and below
        // are refused outright. It may sit ABOVE the base price — that is a premium
        // branch, and the AI already announces the difference (tools._price_change_note).
        for (const inp of mEl.querySelectorAll('[data-bprice]')) {
          if (inp.value.trim() === '') continue;
          const v = Number(inp.value);
          if (!Number.isFinite(v) || v <= 0 || v > MAX_PRICE)
            return toast(t('treat.branchPriceRange', { max: MAX_PRICE.toLocaleString() }), 'error');
        }
        const payload = {
          name,
          branch_ids: branchIds,
          // Same snap as on blur, in case the field never lost focus (Enter, or a
          // click straight onto Save).
          category: (() => {
            const v = mEl.querySelector('#f-cat').value.trim();
            return cats.find((c) => c.toLowerCase() === v.toLowerCase()) || v;
          })(),
          base_price: basePrice,
          duration_min: duration,
          recommended_interval_days: interval,
          deposit,
          hold_minutes: holdMinutes,
          description: mEl.querySelector('#f-desc').value.trim(),
          prep_notes: mEl.querySelector('#f-prep').value.trim(),
          aftercare_notes: mEl.querySelector('#f-after').value.trim(),
          contraindications: mEl.querySelector('#f-contra').value.trim(),
          active: mEl.querySelector('#f-active').checked,
        };
        if (removeImg) payload.image = '';
        // Per-branch price rows are only ever shown for the currently-checked
        // branches (see #tx-perbranch-wrap), so submitting whatever's rendered
        // always matches the current selection.
        if (mEl.querySelector('[data-bprice]')) {
          const prices = {};
          mEl.querySelectorAll('[data-bprice]').forEach((inp) => {
            const v = inp.value.trim();
            prices[inp.dataset.bprice] = v === '' ? null : Number(v);
          });
          payload.prices = prices;
        }

        const saveBtn = mEl.querySelector('.modal-foot .btn-primary');
        saveBtn.disabled = true;
        saveBtn.innerHTML = '<div class="spinner"></div>';
        try {
          const saved = isNew ? await api.post('/services', payload)
                              : await api.patch(`/services/${s.id}`, payload);
          if (stagedFile) {
            const fd = new FormData();
            fd.append('file', stagedFile);
            try { await api.post(`/services/${saved.id}/image`, fd); }
            catch (e) { toast(t('treat.savedPhotoFailed'), 'warn'); }
          }
          toast(t('treat.savedSyncing'), 'success');
          close(); await reload();
        } catch (ex) {
          toast(ex.detail || t('common.saveFailed'), 'error');
          saveBtn.disabled = false;
          saveBtn.textContent = t('common.save');
        }
      } },
    ],
  });

  // Category is a free-text field with the existing categories hanging off it —
  // a native <datalist> could not do this, because it FILTERS itself down to what
  // has been typed, so the moment you start a new name the other categories vanish
  // and you cannot see what the clinic already uses. Here the list is complete and
  // unfiltered whenever it is open, and typing something new is always allowed.
  const catInput = m.el.querySelector('#f-cat');
  const catList = m.el.querySelector('#f-cat-list');
  if (catList) {
    const markCurrent = () => {
      const v = catInput.value.trim().toLowerCase();
      catList.querySelectorAll('.combo-opt').forEach((o) => {
        o.classList.toggle('is-on', o.dataset.v.toLowerCase() === v);
      });
    };
    const openList = (on) => {
      catList.hidden = !on;
      if (on) markCurrent();
    };
    m.el.querySelector('#f-cat-caret').onclick = () => openList(catList.hidden);
    // Opens on CLICK, not on focus. Picking an option closes the list and returns
    // focus to the input so you can keep typing — and a focus handler would fire on
    // exactly that, reopening the list the click had just closed.
    catInput.onclick = () => openList(true);
    catInput.oninput = markCurrent;
    // Snap to an existing category that differs only in case or spacing, so typing
    // "injectables" joins Injectables instead of quietly starting a rival spelling
    // that then shows up as its own filter pill forever.
    catInput.onblur = () => {
      const v = catInput.value.trim();
      const hit = cats.find((c) => c.toLowerCase() === v.toLowerCase());
      catInput.value = hit || v;
    };
    catList.onclick = (e) => {
      const opt = e.target.closest('.combo-opt');
      if (!opt) return;
      catInput.value = opt.dataset.v;
      openList(false);
      catInput.focus();
    };
    // Close on a click elsewhere in the modal, and on Escape — but let Escape reach
    // the modal itself once the list is already shut, so it still closes the dialog.
    m.el.addEventListener('mousedown', (e) => {
      if (!e.target.closest('#f-cat-combo')) openList(false);
    });
    catInput.onkeydown = (e) => {
      if (e.key === 'Escape' && !catList.hidden) {
        e.stopPropagation();
        openList(false);
      }
    };
  }

  // The branch multi-select: re-summarise the closed label and rebuild the
  // per-branch-price rows (checking every box, or the clinic's only branch,
  // both collapse the section — see effectiveBranches) whenever a box toggles.
  const getChecked = () => [...m.el.querySelectorAll('[data-branch-chk]:checked')]
    .map((c) => Number(c.dataset.branchChk));
  const syncBranchUI = () => {
    // preserve whatever the user typed before the rows underneath get rebuilt
    m.el.querySelectorAll('[data-bprice]').forEach((inp) => {
      bpValues[Number(inp.dataset.bprice)] = inp.value;
    });
    const checked = getChecked();
    const summaryEl = m.el.querySelector('#tx-branch-summary');
    if (summaryEl) summaryEl.textContent = branchSummaryText(checked);
    const wrap = m.el.querySelector('#tx-perbranch-wrap');
    if (!wrap) return;
    const effective = effectiveBranches(checked);
    if (effective.length > 1) {
      wrap.style.display = '';
      wrap.querySelector('.tx-branch-prices').innerHTML = renderBpRows(effective);
      const bp = Number(m.el.querySelector('#f-price').value) || 0;
      wrap.querySelectorAll('[data-bprice]').forEach((inp) => { inp.max = bp; });
    } else {
      wrap.style.display = 'none';
      wrap.querySelector('.tx-branch-prices').innerHTML = '';
    }
  };
  wireCheckAll(m.el, 'branch-chk', syncBranchUI);

  // keep the deposit cap (max = base price), the auto-20% hint, and the per-branch
  // price caps (0..base price) in step as the base price changes
  const priceInp = m.el.querySelector('#f-price');
  const depositInp = m.el.querySelector('#f-deposit');
  if (priceInp && depositInp) priceInp.oninput = () => {
    const bp = Number(priceInp.value) || 0;
    depositInp.max = bp > 0 ? bp : '';
    depositInp.placeholder = t('treat.auto') + ' ฿' + (Math.round(bp * 0.2 / 100) * 100);
    if ((Number(depositInp.value) || 0) > bp) depositInp.value = bp || '';
    // re-query live — the per-branch rows are rebuilt whenever branches toggle
    m.el.querySelectorAll('[data-bprice]').forEach((inp) => {
      inp.max = bp;
      inp.placeholder = bp || 0;
      if (Number(inp.value) > bp) inp.value = bp || '';
    });
  };

  // wire the photo picker
  const fileInp = m.el.querySelector('#tx-img-file');
  const prev = m.el.querySelector('#tx-img-prev');
  const clearBtn = m.el.querySelector('#tx-img-clear');
  fileInp.onchange = () => {
    const f = fileInp.files[0];
    if (!f) return;
    if (f.size > 4 * 1024 * 1024) { toast(t('treat.imageTooLarge'), 'error'); fileInp.value = ''; return; }
    stagedFile = f;
    removeImg = false;
    const r = new FileReader();
    r.onload = () => { prev.innerHTML = `<img src="${r.result}" alt="">`; };
    r.readAsDataURL(f);
    clearBtn.style.display = '';
  };
  clearBtn.onclick = () => {
    stagedFile = null;
    removeImg = true;
    fileInp.value = '';
    prev.innerHTML = icon('spark', 28);
    clearBtn.style.display = 'none';
  };
}
