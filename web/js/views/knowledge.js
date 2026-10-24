/* Blinks Bright — Knowledge Base view (Articles & FAQ · Promotions) */

import { api } from '../api.js';
import { store } from '../store.js';
import { icon, toast, modal, escapeHtml, emptyState, loadingBlock,
         confirmDialog, debounce, isEveryBranch, branchSummaryText,
         branchCheckboxListHtml, wireCheckAll } from '../ui.js';
import { t } from '../i18n.js';

const TYPE_META = {
  faq:       { label: t('kb.typeFaq'),       icon: 'info',  color: 'var(--chart-1)' },
  policy:    { label: t('kb.typePolicy'),    icon: 'lock',  color: 'var(--chart-6)' },
  prep:      { label: t('kb.typePrep'),      icon: 'clock', color: 'var(--chart-4)' },
  aftercare: { label: t('kb.typeAftercare'), icon: 'heart', color: 'var(--chart-3)' },
  general:   { label: t('kb.typeGeneral'),   icon: 'book',  color: 'var(--chart-2)' },
};
const TYPES = Object.keys(TYPE_META);

let services = [];
// Module-level (not reset inside articlesTab/promotionsTab/renderKnowledge) so
// switching the topbar's active branch — which remounts this whole view —
// never wipes the user's tab or type/status filter; only picking a different
// one does. Defaults: Articles & FAQ tab, "all" for both filters.
let activeTab = 'articles';
let typeFilter = 'all';
let statusFilter = 'all';

export default async function renderKnowledge(mount) {
  const canEdit = store.canManage() || store.isRole('marketing');
  mount.innerHTML = `<div class="view">
    <div class="view-head">
      <div>
        <h2>${t('kb.title')}</h2>
        <p>${t('kb.subtitle')}</p>
      </div>
      ${canEdit ? `<button class="btn btn-ghost" id="reindex-btn">${icon('refresh')}<span>${t('kb.reindexAi')}</span></button>` : ''}
    </div>
    <div class="grid grid-4" id="kb-stats" style="margin-bottom:20px"></div>
    <div class="tabs">
      <button class="tab${activeTab === 'articles' ? ' active' : ''}" data-tab="articles">${t('kb.tabArticles')}</button>
      <button class="tab${activeTab === 'promotions' ? ' active' : ''}" data-tab="promotions">${t('kb.tabPromotions')}</button>
    </div>
    <div id="kb-body">${loadingBlock()}</div>
  </div>`;

  const body = mount.querySelector('#kb-body');
  try { services = await api.get('/services'); } catch (e) { services = []; }

  loadStats(mount);
  showTab(activeTab);

  mount.querySelectorAll('.tab').forEach((t) => {
    t.onclick = () => {
      mount.querySelectorAll('.tab').forEach((x) => x.classList.toggle('active', x === t));
      showTab(t.dataset.tab);
    };
  });

  const reBtn = mount.querySelector('#reindex-btn');
  if (reBtn) reBtn.onclick = async () => {
    reBtn.disabled = true;
    reBtn.innerHTML = '<div class="spinner"></div>';
    try {
      const r = await api.post('/knowledge/reindex');
      toast(t('kb.reindexed', { chunks: r.chunks, embedded: r.embedded }), 'success');
      loadStats(mount);
    } catch (ex) { toast(ex.detail || t('kb.reindexFailed'), 'error'); }
    reBtn.disabled = false;
    reBtn.innerHTML = `${icon('refresh')}<span>${t('kb.reindexAi')}</span>`;
  };

  async function showTab(tab) {
    activeTab = tab;
    body.innerHTML = loadingBlock();
    if (tab === 'promotions') await promotionsTab(body, canEdit);
    else await articlesTab(body, canEdit);
  }
}

async function loadStats(mount) {
  try {
    const s = await api.get('/knowledge/overview');
    mount.querySelector('#kb-stats').innerHTML = [
      [t('kb.statArticles'), s.articles, 'file', 'var(--chart-1)'],
      [t('kb.statTreatments'), s.services, 'spark', 'var(--chart-2)'],
      [t('kb.statPromotions'), s.promotions, 'gift', 'var(--chart-6)'],
      [t('kb.statIndexed'), `${s.embedded}/${s.chunks}`, 'ai', 'var(--chart-3)'],
    ].map(([label, val, ic, color]) => `
      <div class="stat-card" style="--ic:${color}">
        <div class="stat-top"><span class="stat-label">${label}</span>
          <span class="stat-ic">${icon(ic, 16)}</span></div>
        <div class="stat-value">${val}</div>
      </div>`).join('');
  } catch (e) { /* ignore */ }
}

/* ---------------- Articles ---------------- */
async function articlesTab(body, canEdit) {
  let articles = [];
  try { articles = await api.get('/knowledge/articles'); } catch (e) {}
  let q = '';
  body.innerHTML = `
    <div class="row-between" style="margin-bottom:10px;gap:12px;flex-wrap:wrap;align-items:center">
      <div class="segmented" id="kb-type-filter">
        <button class="${typeFilter === 'all' ? 'active' : ''}" data-type="all">${t('common.all')}</button>
        ${TYPES.map((ty) => `<button class="${typeFilter === ty ? 'active' : ''}" data-type="${ty}">${TYPE_META[ty].label}</button>`).join('')}
      </div>
      <div class="row gap-2">
        <div class="search-box" style="min-width:220px;position:relative">${icon('search', 16)}
          <input class="input" id="kb-search" placeholder="${t('kb.searchArticles')}" style="padding-right:36px">
          <button type="button" id="kb-search-clear" title="${t('common.clear')}"
            style="position:absolute;right:12px;top:50%;transform:translateY(-50%);width:20px;height:20px;
              display:none;align-items:center;justify-content:center;
              border:none;background:transparent;padding:0;border-radius:var(--r-sm);color:var(--muted);cursor:pointer">
            ${icon('close', 14)}</button>
        </div>
        ${canEdit ? `<button class="btn btn-ghost btn-sm" id="upload-article">${icon('file', 15)}<span>${t('kb.uploadDoc')}</span></button>
          <input type="file" id="upload-file" accept=".pdf,.docx,.txt" hidden>
          <button class="btn btn-primary btn-sm" id="add-article">${icon('plus', 15)}<span>${t('kb.addArticle')}</span></button>` : ''}
      </div>
    </div>
    <div class="card results-min"><div id="kb-art-list"></div></div>`;

  const list = body.querySelector('#kb-art-list');
  // No in-page branch filter — the topbar's own branch selector narrows the list.
  const branchScoped = store.branchId && store.branchId !== 'all';
  function draw() {
    const rows = articles.filter((a) =>
      (typeFilter === 'all' || a.type === typeFilter)
      && (!branchScoped || !a.branch_id || String(a.branch_id) === String(store.branchId))
      && (!q || a.title.toLowerCase().includes(q)));
    if (!rows.length) {
      const filtered = q || typeFilter !== 'all';
      list.innerHTML = emptyState('book', filtered ? t('kb.noMatches') : t('kb.noArticles'),
        filtered ? t('kb.tryAnotherSearch') : t('kb.noArticlesHint'));
      return;
    }
    list.innerHTML = rows.map((a) => {
      const m = TYPE_META[a.type] || { label: a.type, icon: 'file', color: 'var(--ink-2)' };
      return `<div class="kb-art-row row" data-id="${a.id}"
           style="gap:14px;padding:13px 16px;border-bottom:1px solid var(--border);cursor:${canEdit ? 'pointer' : 'default'}">
          <span class="kb-type" style="--c:${m.color}">${icon(m.icon, 12)} ${m.label}</span>
          <div style="flex:1;min-width:0">
            <div class="strong">${escapeHtml(a.title)}</div>
            <div class="muted text-sm truncate">${escapeHtml(a.content)}</div>
          </div>
          ${canEdit ? `<span class="btn-icon btn-subtle">${icon('edit', 15)}</span>` : ''}
        </div>`;
    }).join('');
    if (canEdit) list.querySelectorAll('[data-id]').forEach((el) => {
      el.onclick = () => articleModal(body, canEdit, articles.find((a) => a.id === Number(el.dataset.id)));
    });
  }
  draw();

  body.querySelectorAll('#kb-type-filter button').forEach((b) => {
    b.onclick = () => {
      body.querySelectorAll('#kb-type-filter button').forEach((x) => x.classList.toggle('active', x === b));
      typeFilter = b.dataset.type;
      draw();
    };
  });

  const se = body.querySelector('#kb-search');
  const seClear = body.querySelector('#kb-search-clear');
  const debouncedDraw = debounce(() => { q = se.value.trim().toLowerCase(); draw(); }, 150);
  if (se) se.oninput = () => {
    seClear.style.display = se.value ? 'flex' : 'none';
    debouncedDraw();
  };
  if (seClear) seClear.onclick = () => {
    se.value = '';
    seClear.style.display = 'none';
    se.focus();
    q = '';
    draw();
  };
  if (canEdit) {
    body.querySelector('#add-article').onclick = () => articleModal(body, canEdit, null);
    const upBtn = body.querySelector('#upload-article');
    const upFile = body.querySelector('#upload-file');
    upBtn.onclick = () => upFile.click();
    upFile.onchange = async () => {
      const f = upFile.files[0];
      upFile.value = '';  // re-selecting the same file must re-fire onchange
      if (!f) return;
      const ext = (f.name.split('.').pop() || '').toLowerCase();
      if (!['pdf', 'docx', 'txt'].includes(ext)) return toast(t('kb.fileUnsupported'), 'error');
      if (f.size > 10 * 1024 * 1024) return toast(t('kb.fileTooLarge'), 'error');
      upBtn.disabled = true;
      upBtn.innerHTML = '<div class="spinner"></div>';
      try {
        const fd = new FormData();
        fd.append('file', f);
        const a = await api.post('/knowledge/upload', fd);
        toast(t('kb.uploaded', { title: a.title }), 'success');
        articlesTab(body, canEdit);
      } catch (ex) {
        toast(ex.detail || t('kb.uploadFailed'), 'error');
        upBtn.disabled = false;
        upBtn.innerHTML = `${icon('file', 15)}<span>${t('kb.uploadDoc')}</span>`;
      }
    };
  }
}

function articleModal(body, canEdit, article) {
  const a = article || { type: 'faq', title: '', content: '', active: true };
  modal({
    title: article ? t('kb.editArticle') : t('kb.newArticle'),
    wide: true,
    body: `
      <div class="field"><label>${t('kb.fieldType')}</label>
        <select class="select" id="f-type">
          ${TYPES.map((ty) => `<option value="${ty}" ${ty === a.type ? 'selected' : ''}>${TYPE_META[ty].label}</option>`).join('')}
        </select></div>
      <div class="field"><label>${t('kb.fieldTitle')}</label>
        <input class="input" id="f-title" value="${escapeHtml(a.title)}" placeholder="${t('kb.titlePlaceholder')}"></div>
      <div class="field"><label>${t('kb.fieldContent')}</label>
        <textarea class="textarea" id="f-content" rows="6" placeholder="${t('kb.contentPlaceholder')}">${escapeHtml(a.content)}</textarea></div>`,
    actions: [
      ...(article ? [{ label: t('common.delete'), class: 'btn-danger', keepOpen: true, onClick: async ({ close }) => {
        if (await confirmDialog({ title: t('kb.deleteArticleConfirm'), message: a.title, confirmLabel: t('common.delete'), danger: true })) {
          await api.del(`/knowledge/articles/${a.id}`);
          toast(t('kb.articleDeleted'), 'success'); close(); articlesTab(body, canEdit);
        }
      } }] : []),
      { label: t('common.cancel'), class: 'btn-ghost' },
      { label: t('common.save'), class: 'btn-primary', keepOpen: true, onClick: async ({ close, modal: m }) => {
        const payload = {
          type: m.querySelector('#f-type').value,
          title: m.querySelector('#f-title').value.trim(),
          content: m.querySelector('#f-content').value.trim(),
        };
        if (!payload.title) return toast(t('kb.titleRequired'), 'error');
        try {
          if (article) await api.patch(`/knowledge/articles/${a.id}`, payload);
          else await api.post('/knowledge/articles', payload);
          toast(t('common.saved'), 'success'); close(); articlesTab(body, canEdit);
        } catch (ex) { toast(ex.detail || t('common.saveFailed'), 'error'); }
      } },
    ],
  });
}

/* Treatments live in their own top-level view (web/js/views/treatments.js).
   Opening hours & contact live with each branch (Settings → Branches) and the
   AI pulls them from there. `services` is loaded above so the promotion editor
   can link offers to a treatment. */

/* ---------------- Promotions ---------------- */
async function promotionsTab(body, canEdit) {
  let promos = [];
  try { promos = await api.get('/promotions'); } catch (e) {}
  let q = '';
  body.innerHTML = `
    <div class="row-between" style="margin-bottom:14px;gap:12px;flex-wrap:wrap;align-items:center">
      <div class="segmented" id="kb-promo-status-filter">
        <button class="${statusFilter === 'all' ? 'active' : ''}" data-status="all">${t('common.all')}</button>
        <button class="${statusFilter === 'active' ? 'active' : ''}" data-status="active">${t('common.active')}</button>
        <button class="${statusFilter === 'inactive' ? 'active' : ''}" data-status="inactive">${t('common.inactive')}</button>
      </div>
      <div class="row gap-2">
        <div class="search-box" style="min-width:220px;position:relative">${icon('search', 16)}
          <input class="input" id="kb-promo-search" placeholder="${t('kb.searchPromotions')}" style="padding-right:36px">
          <button type="button" id="kb-promo-search-clear" title="${t('common.clear')}"
            style="position:absolute;right:12px;top:50%;transform:translateY(-50%);width:20px;height:20px;
              display:none;align-items:center;justify-content:center;
              border:none;background:transparent;padding:0;border-radius:var(--r-sm);color:var(--muted);cursor:pointer">
            ${icon('close', 14)}</button>
        </div>
        ${canEdit ? `<button class="btn btn-primary btn-sm" id="add-promo">${icon('plus', 15)}<span>${t('kb.addPromotion')}</span></button>` : ''}
      </div>
    </div>
    <div class="grid grid-2" id="kb-promo-grid"></div>`;

  const grid = body.querySelector('#kb-promo-grid');
  // No in-page branch filter — the topbar's own branch selector narrows the list.
  const branchScoped = store.branchId && store.branchId !== 'all';
  function draw() {
    const rows = promos.filter((p) =>
      (statusFilter === 'all' || (statusFilter === 'active' ? p.active : !p.active))
      // Empty branch_ids = runs everywhere. Reading the old single branch_id here
      // would silently stop filtering, because the API no longer sets it.
      && (!branchScoped || !(p.branch_ids || []).length
          || p.branch_ids.includes(Number(store.branchId)))
      && (!q || p.title.toLowerCase().includes(q)));
    grid.innerHTML = rows.length ? rows.map((p) => {
      const dval = (v) => (v ? String(v).slice(0, 10) : '…');
      // Server-side the promo stops matching once `now` passes valid_to
      // (date-only input is stored as that day's midnight) — same comparison.
      const expired = p.valid_to && new Date(p.valid_to) < new Date();
      const quotaFull = p.quota > 0 && (p.used || 0) >= p.quota;
      return `
      <div class="card card-pad" data-id="${p.id}" style="cursor:${canEdit ? 'pointer' : 'default'}">
        <div class="row-between">
          <span class="row gap-1">
            <span class="badge ${p.active ? 'badge-paid' : 'badge-soft'}">${p.active ? t('common.active') : t('common.inactive')}</span>
            ${expired ? `<span class="badge badge-danger">${t('kb.expired')}</span>` : ''}
            ${quotaFull ? `<span class="badge badge-danger">${t('kb.quotaFull')}</span>` : ''}
          </span>
          <span class="badge badge-olive">${escapeHtml(p.discount_label || t('kb.offer'))}</span>
        </div>
        <div class="strong" style="margin:8px 0 4px">${escapeHtml(p.title)}</div>
        <div class="muted text-sm">${escapeHtml(p.detail)}</div>
        ${(p.valid_from || p.valid_to) ? `<div class="muted text-sm" style="margin-top:6px">${t('kb.validRange', { from: dval(p.valid_from), to: dval(p.valid_to) })}</div>` : ''}
        <div class="muted text-sm" ${(p.valid_from || p.valid_to) ? '' : 'style="margin-top:6px"'}>${p.quota > 0 ? t('kb.quotaUsed', { used: p.used || 0, quota: p.quota }) : t('kb.quotaUnlimited')}</div>
      </div>`;
    }).join('') : `<div class="card span-2">${emptyState('gift',
      (q || statusFilter !== 'all') ? t('kb.noMatches') : t('kb.noPromotions'),
      (q || statusFilter !== 'all') ? t('kb.tryAnotherSearch') : t('kb.noPromotionsHint'))}</div>`;
    if (canEdit) grid.querySelectorAll('[data-id]').forEach((c) => {
      c.onclick = async () => {
        const promos2 = await api.get('/promotions');
        promoModal(body, promos2.find((p) => p.id === Number(c.dataset.id)));
      };
    });
  }
  draw();

  body.querySelectorAll('#kb-promo-status-filter button').forEach((b) => {
    b.onclick = () => {
      body.querySelectorAll('#kb-promo-status-filter button').forEach((x) => x.classList.toggle('active', x === b));
      statusFilter = b.dataset.status;
      draw();
    };
  });

  const se = body.querySelector('#kb-promo-search');
  const seClear = body.querySelector('#kb-promo-search-clear');
  const debouncedDraw = debounce(() => { q = se.value.trim().toLowerCase(); draw(); }, 150);
  se.oninput = () => {
    seClear.style.display = se.value ? 'flex' : 'none';
    debouncedDraw();
  };
  seClear.onclick = () => {
    se.value = '';
    seClear.style.display = 'none';
    se.focus();
    q = '';
    draw();
  };
  if (canEdit) body.querySelector('#add-promo').onclick = () => promoModal(body, null);
}

function promoModal(body, promo) {
  const p = promo || { title: '', detail: '', discount_label: '', promo_price: null,
    service_id: null, branch_ids: [], active: true, valid_from: null, valid_to: null,
    quota: 0, used: 0 };
  // Same convention as a treatment's branches: an empty list means every branch, and
  // ticking every one collapses back to that (isEveryBranch).
  const multiBranch = store.branches.length > 1;
  const initialBranches = new Set(p.branch_ids || []);
  const dval = (v) => (v ? String(v).slice(0, 10) : '');
  const pm = modal({
    title: promo ? t('kb.editPromotion') : t('kb.newPromotion'),
    wide: true,
    body: `
      <div class="field"><label>${t('kb.fieldTitle')}</label><input class="input" id="f-title" value="${escapeHtml(p.title)}"></div>
      <div class="field"><label>${t('kb.fieldDetail')}</label><textarea class="textarea" id="f-detail" rows="3">${escapeHtml(p.detail)}</textarea></div>
      <div class="grid grid-2">
        <div class="field"><label>${t('kb.fieldDiscountLabel')}</label><input class="input" id="f-label" value="${escapeHtml(p.discount_label)}" placeholder="${t('kb.discountPlaceholder')}"></div>
        <div class="field"><label>${t('kb.fieldPromoPrice')}</label><input class="input" type="number" id="f-price" value="${p.promo_price || ''}"></div>
      </div>
      <div class="grid grid-2">
        <div class="field"><label>${t('kb.fieldTreatment')}</label>
          <select class="select" id="f-svc"><option value="">${t('kb.anyTreatment')}</option>
            ${services.map((s) => `<option value="${s.id}" ${s.id === p.service_id ? 'selected' : ''}>${escapeHtml(s.name)}</option>`).join('')}</select></div>
        ${multiBranch ? `<div class="field"><label>${t('menu.branch')}</label>
          <details class="tx-branch-msel" id="promo-branch-msel">
            <summary class="input"><span class="tx-branch-summary-text" id="promo-branch-summary">${
              escapeHtml(branchSummaryText([...initialBranches]))}</span></summary>
            <div class="tx-branch-msel-panel">${branchCheckboxListHtml('branch-chk', [...initialBranches])}</div>
          </details>
          <div class="field-hint">${t('kb.promoBranchHint')}</div>
        </div>` : ''}
      </div>
      <div class="grid grid-2">
        <div class="field"><label>${t('kb.fieldValidFrom')}</label><input class="input" type="date" id="f-from" value="${dval(p.valid_from)}"></div>
        <div class="field"><label>${t('kb.fieldValidTo')}</label><input class="input" type="date" id="f-to" value="${dval(p.valid_to)}"></div>
      </div>
      <div class="field"><label>${t('kb.fieldQuota')}</label>
        <input class="input" type="number" min="0" step="1" id="f-quota" value="${p.quota || 0}">
        <div class="muted text-sm" style="margin-top:4px">${t('kb.quotaHint')}${p.quota > 0 ? ` · ${t('kb.quotaUsed', { used: p.used || 0, quota: p.quota })}` : ''}</div></div>
      <label class="row gap-2" style="cursor:pointer"><span class="toggle"><input type="checkbox" id="f-active" ${p.active ? 'checked' : ''}><span class="track"></span></span> ${t('common.active')}</label>`,
    actions: [
      ...(promo ? [{ label: t('common.delete'), class: 'btn-danger mfoot-left', keepOpen: true,
        onClick: async ({ close }) => {
          const ok = await confirmDialog({
            title: t('kb.deletePromoTitle'),
            message: t('kb.deletePromoMsg', { title: p.title }),
            confirmLabel: t('common.delete'), danger: true });
          if (!ok) return;
          try {
            const r = await api.del(`/promotions/${p.id}`);
            toast(r.archived ? t('kb.promoArchived') : t('kb.promoDeleted'), 'success');
            close(); promotionsTab(body, true);
          } catch (ex) { toast(ex.detail || t('common.deleteFailed'), 'error'); }
        } }] : []),
      { label: t('common.cancel'), class: 'btn-ghost' },
      { label: t('common.save'), class: 'btn-primary', keepOpen: true, onClick: async ({ close, modal: m }) => {
        const payload = {
          title: m.querySelector('#f-title').value.trim(),
          detail: m.querySelector('#f-detail').value.trim(),
          discount_label: m.querySelector('#f-label').value.trim(),
          promo_price: Number(m.querySelector('#f-price').value) || null,
          service_id: Number(m.querySelector('#f-svc').value) || null,
          // Every branch ticked (or a single-branch clinic with no picker) is "all
          // branches", which the API stores as no rows at all.
          branch_ids: (() => {
            const checked = [...m.querySelectorAll('[data-branch-chk]:checked')]
              .map((c) => Number(c.dataset.branchChk));
            return (!m.querySelector('[data-branch-chk]') || isEveryBranch(checked))
              ? [] : checked;
          })(),
          valid_from: m.querySelector('#f-from').value || null,
          valid_to: m.querySelector('#f-to').value || null,
          quota: Math.max(0, Math.floor(Number(m.querySelector('#f-quota').value) || 0)),
          active: m.querySelector('#f-active').checked,
        };
        if (!payload.title) return toast(t('kb.titleRequired'), 'error');
        try {
          if (promo) await api.patch(`/promotions/${p.id}`, payload);
          else await api.post('/promotions', payload);
          toast(t('common.saved'), 'success'); close(); promotionsTab(body, true);
        } catch (ex) { toast(ex.detail || t('common.saveFailed'), 'error'); }
      } },
    ],
  });

  // Keep the collapsed summary honest as boxes toggle, and let the "all branches"
  // master checkbox drive the rest — same wiring the treatment modal uses.
  if (multiBranch) {
    const syncSummary = () => {
      const checked = [...pm.el.querySelectorAll('[data-branch-chk]:checked')]
        .map((c) => Number(c.dataset.branchChk));
      pm.el.querySelector('#promo-branch-summary').textContent = branchSummaryText(checked);
    };
    wireCheckAll(pm.el, 'branch-chk', syncSummary);
    syncSummary();
  }
}
