/* Blinks Bright — Unified Inbox (Conversations) */

import { api } from '../api.js';
import { store } from '../store.js';
import { setWSHandler } from '../ws.js';
import { icon, escapeHtml, initials, avatarHTML, channelLogo, timeAgo, timeOf, toast, modal, confirmDialog, emptyState, renderMarkdown, paymentCard, markPayCardPaid, stripPayUrls, cleanDashes, applySlipState } from '../ui.js';
import { t } from '../i18n.js';

const CHANNEL_ICON = { web: 'globe' };
const STATUS = [
  ['', t('common.all')], ['new_lead', t('conv.filterNew')], ['interested', t('conv.stageInterested')],
  ['booked', t('conv.stageBooked')], ['paid', t('conv.stagePaid')], ['followup', t('conv.stageFollowup')],
];
const STATUS_BADGE = {
  new_lead: 'badge-new', interested: 'badge-interested', booked: 'badge-booked',
  paid: 'badge-paid', followup: 'badge-followup',
};
const STATUS_LABEL = {
  new_lead: t('conv.stageNewLead'), interested: t('conv.stageInterested'), booked: t('conv.stageBooked'),
  paid: t('conv.stagePaid'), followup: t('conv.stageFollowup'),
};

const PAGE_SIZE = 12;
const BACK_ICON = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 18l-6-6 6-6"/></svg>';

const S = { convs: [], activeId: null, detail: null, filter: '', search: '', seen: new Set(), page: 1,
            hideList: false, hidePanel: false };

/* Collapsible side panels — remembered so the focused chat view sticks. */
const LAYOUT_KEY = 'conv-layout';
function loadLayout() {
  try {
    const o = JSON.parse(localStorage.getItem(LAYOUT_KEY) || '{}');
    S.hideList = !!o.hideList; S.hidePanel = !!o.hidePanel;
  } catch (e) { S.hideList = false; S.hidePanel = false; }
}
function saveLayout() {
  try { localStorage.setItem(LAYOUT_KEY, JSON.stringify({ hideList: S.hideList, hidePanel: S.hidePanel })); }
  catch (e) { /* ignore */ }
}
function applyLayout(mount) {
  const inbox = mount.querySelector('.inbox');
  if (inbox) {
    inbox.classList.toggle('hide-list', S.hideList);
    inbox.classList.toggle('hide-panel', S.hidePanel);
  }
  const lt = mount.querySelector('#toggle-list');
  const pt = mount.querySelector('#toggle-panel');
  if (lt) lt.classList.toggle('on', !S.hideList);   // lit when the panel is visible
  if (pt) pt.classList.toggle('on', !S.hidePanel);
}

export default async function renderConversations(mount, params) {
  S.activeId = params && params[0] ? Number(params[0]) : null;
  // S.filter is module-level and intentionally not reset here so the selected
  // tab survives a branch switch, which re-invokes this view against the same
  // cached module instance (mirrors treatments.js's filterCat/search).
  S.search = '';
  S.page = 1;
  loadLayout();

  mount.innerHTML = `<div class="inbox">
    <div class="inbox-list">
      <div class="inbox-list-head">
        <div class="search-box" style="position:relative">${icon('search')}
          <input class="input" id="conv-search" placeholder="${t('conv.searchPlaceholder')}" style="padding-right:36px">
          <button type="button" id="conv-search-clear" title="${t('common.clear')}"
            style="position:absolute;right:12px;top:50%;transform:translateY(-50%);width:20px;height:20px;
              display:none;align-items:center;justify-content:center;
              border:none;background:transparent;padding:0;border-radius:var(--r-sm);color:var(--muted);cursor:pointer">
            ${icon('close', 14)}</button>
        </div>
      </div>
      <div class="inbox-filters" id="conv-filters">
        ${STATUS.map(([v, l]) => `<button class="seg ${v === S.filter ? 'active' : ''}" data-f="${v}">${l}</button>`).join('')}
      </div>
      <div class="inbox-items" id="conv-items"></div>
      <div class="inbox-pager" id="conv-pager"></div>
    </div>
    <div class="inbox-thread" id="inbox-thread"></div>
    <div class="inbox-panel" id="inbox-panel"></div>
  </div>`;
  applyLayout(mount);

  const search = mount.querySelector('#conv-search');
  const searchClear = mount.querySelector('#conv-search-clear');
  search.oninput = () => {
    searchClear.style.display = search.value ? 'flex' : 'none';
    S.search = search.value.trim(); S.page = 1; renderList(mount);
  };
  searchClear.onclick = () => {
    search.value = '';
    searchClear.style.display = 'none';
    search.focus();
    S.search = ''; S.page = 1; renderList(mount);
  };
  mount.querySelectorAll('#conv-filters .seg').forEach((b) => {
    b.onclick = () => {
      mount.querySelectorAll('#conv-filters .seg').forEach((x) => x.classList.toggle('active', x === b));
      S.filter = b.dataset.f;
      S.page = 1;
      loadList(mount);
    };
  });

  await loadList(mount);
  if (S.activeId) await openConv(mount, S.activeId, true);
  else if (S.convs[0]) await openConv(mount, S.convs[0].id, false);
  else renderThreadEmpty(mount);

  setWSHandler((ev) => handleWS(mount, ev));
}

async function loadList(mount) {
  const params = new URLSearchParams();
  if (S.filter) params.set('status', S.filter);
  if (store.branchId && store.branchId !== 'all') params.set('branch_id', store.branchId);
  try { S.convs = await api.get('/conversations?' + params.toString()); }
  catch (e) { S.convs = []; }
  renderList(mount);
}

function pagerHTML(page, pages) {
  if (pages <= 1) return '';
  const btn = (p, label, o = {}) =>
    `<button class="pg ${o.active ? 'active' : ''}" data-pg="${p}"${o.disabled ? ' disabled' : ''}>${label}</button>`;
  let out = btn(page - 1, '‹', { disabled: page <= 1 });
  const want = new Set([1, pages, page, page - 1, page + 1]);
  const shown = [...want].filter((p) => p >= 1 && p <= pages).sort((a, b) => a - b);
  let prev = 0;
  for (const p of shown) {
    if (p - prev > 1) out += '<span class="pg-gap">…</span>';
    out += btn(p, String(p), { active: p === page });
    prev = p;
  }
  out += btn(page + 1, '›', { disabled: page >= pages });
  return out;
}

function renderList(mount) {
  const box = mount.querySelector('#conv-items');
  const pager = mount.querySelector('#conv-pager');
  let list = S.convs;
  if (S.search) {
    const q = S.search.toLowerCase();
    list = list.filter((c) => c.customer_name.toLowerCase().includes(q)
      || (c.last_message || '').toLowerCase().includes(q));
  }
  if (!list.length) {
    box.innerHTML = emptyState('inbox', t('conv.noConvTitle'), t('conv.noConvSub'));
    if (pager) pager.innerHTML = '';
    return;
  }
  const pages = Math.max(1, Math.ceil(list.length / PAGE_SIZE));
  S.page = Math.min(Math.max(1, S.page), pages);
  const start = (S.page - 1) * PAGE_SIZE;
  const pageItems = list.slice(start, start + PAGE_SIZE);
  box.innerHTML = pageItems.map((c) => `
    <button class="conv-item ${c.id === S.activeId ? 'active' : ''}" data-id="${c.id}">
      ${avatarHTML(c.customer_name, c.customer_avatar)}
      <div class="ci-main">
        <div class="ci-top">
          <span class="ci-name truncate">${escapeHtml(c.customer_name)}</span>
          <span class="ci-time">${c.last_message_at ? timeAgo(c.last_message_at) : ''}</span>
        </div>
        <div class="ci-msg truncate">${c.last_sender === 'ai' ? '🤖 ' : c.last_sender === 'admin' ? '↪ ' : ''}${escapeHtml(cleanDashes(c.last_message || ''))}</div>
        <div class="ci-meta">
          ${channelLogo(c.channel, 16)}
          <span class="badge ${STATUS_BADGE[c.status] || 'badge-soft'}">${STATUS_LABEL[c.status] || c.status}</span>
          ${c.temperature ? `<span class="badge badge-${c.temperature}">${c.temperature}</span>` : ''}
          ${!c.ai_enabled ? `<span class="badge badge-followup">${icon('user', 10)} ${t('conv.human')}</span>` : ''}
          ${c.escalation_reason && c.ai_enabled ? `<span class="badge badge-hot" title="${escapeHtml(c.escalation_reason)}">${icon('alert', 10)} ${t('conv.requestAdmin')}</span>` : ''}
          <span class="spacer"></span>
          ${c.unread ? '<span class="unread-dot"></span>' : ''}
        </div>
      </div>
    </button>`).join('');
  box.querySelectorAll('.conv-item').forEach((el) => {
    el.onclick = () => openConv(mount, Number(el.dataset.id), true);
  });
  if (pager) {
    pager.innerHTML = pagerHTML(S.page, pages);
    pager.querySelectorAll('.pg[data-pg]').forEach((b) => {
      b.onclick = () => {
        if (b.disabled) return;
        const p = Number(b.dataset.pg);
        if (p === S.page) return;
        S.page = p;
        renderList(mount);
        box.scrollTop = 0;
      };
    });
  }
}

async function openConv(mount, id, userInitiated) {
  S.activeId = id;
  S.seen = new Set();
  const inbox = mount.querySelector('.inbox');
  if (inbox && userInitiated) inbox.classList.add('show-thread');  // mobile: slide to the thread
  mount.querySelectorAll('.conv-item').forEach((el) =>
    el.classList.toggle('active', Number(el.dataset.id) === id));
  const thread = mount.querySelector('#inbox-thread');
  thread.innerHTML = '<div class="loading-block"><div class="spinner"></div></div>';
  try {
    S.detail = await api.get(`/conversations/${id}`);
  } catch (e) { thread.innerHTML = emptyState('alert', t('conv.couldNotLoad')); return; }
  renderThread(mount);
  renderPanel(mount);
  const c = S.convs.find((x) => x.id === id);
  if (c) { c.unread = false; }
  window.dispatchEvent(new Event('inbox:read'));  // chat read -> refresh the topbar bell count
  renderList(mount);
}

function sourcesHTML(m) {
  if (m.sender !== 'ai' || !m.sources || !m.sources.length) return '';
  return `<div class="b-src">${icon('search', 11)}<span class="b-src-lbl">${t('conv.sources')}</span>${
    m.sources.map((s) => `<span class="src-chip">${escapeHtml(s)}</span>`).join('')}</div>`;
}

const FLAG_REASON_KEY = { offer: 'conv.flagOffer', discount: 'conv.flagDiscount', payment: 'conv.flagPayment' };

// A reply the deterministic filters could not safely auto-edit (offer/discount claims
// with nothing grounding them, or an unverifiable payment claim) — flagged in meta by
// app/ai/guardrails.py but, before this, never shown anywhere a human would see it.
function flagHTML(m) {
  if (m.sender !== 'ai' || !m.flag_reasons || !m.flag_reasons.length) return '';
  const title = m.flag_reasons.map((r) => t(FLAG_REASON_KEY[r] || r)).join(' · ');
  return `<div style="margin-top:6px"><span class="badge badge-warning" title="${escapeHtml(title)}">${icon('alert', 11)} ${t('conv.needsReview')}</span></div>`;
}

// The AI's raw reference trail for this reply (KB context, catalog prices, admin
// messages, every tool result) — set by app/ai/chat.py::respond, so staff can debug
// a hallucination ("where did THIS come from") instead of guessing. Collapsed by
// default; auto-open exactly when there's already a "needs review" flag, since that's
// when a human needs to look right away.
function groundingHTML(m) {
  if (m.sender !== 'ai' || !m.grounding) return '';
  const open = m.flag_reasons && m.flag_reasons.length ? ' open' : '';
  return `<details class="b-grounding"${open}><summary>${t('conv.viewGrounding')}</summary>`
    + `<pre>${escapeHtml(m.grounding)}</pre></details>`;
}

function adminTag(m) {
  // automation/campaign bubbles get a localized tag (meta flag, with a
  // sender_name==='Automation' fallback for rows persisted before the flag
  // existed); campaign sends keep their campaign name appended.
  const auto = m.automation || m.sender_name === 'Automation';
  if (auto) {
    const extra = m.sender_name && m.sender_name !== 'Automation'
      ? ` · ${escapeHtml(m.sender_name)}` : '';
    return `<div class="b-tag">${t('conv.automationTag')}${extra}</div>`;
  }
  return m.sender_name ? `<div class="b-tag">${escapeHtml(m.sender_name)}</div>` : '';
}

function bubble(m) {
  if (m.sender === 'system') return `<div class="msg-row sys"><div class="bubble sys">${escapeHtml(cleanDashes(m.text))}</div></div>`;
  const out = m.sender === 'ai' || m.sender === 'admin';
  const cls = m.sender === 'ai' ? 'ai' : m.sender === 'admin' ? 'admin' : 'in';
  const tag = m.sender === 'ai' ? `<div class="b-tag">${t('conv.aiAssistant')}</div>`
    : m.sender === 'admin' ? adminTag(m) : '';
  // A photo the customer sent (slip, skin photo, price sign…) — only our own upload dir is
  // ever rendered. Click opens it full size, which is how staff read a transfer slip.
  const photo = m.image && /^\/assets\/images\/chat-uploads\//.test(m.image)
    ? `<a class="msg-photo" href="${escapeHtml(m.image)}" target="_blank" rel="noopener"
         title="${t('conv.openPhoto')}"><img src="${escapeHtml(m.image)}" alt="${t('conv.openPhoto')}" loading="lazy"></a>` : '';
  const body = photo && m.text === '📷' ? ''
    : m.sender === 'ai' ? renderMarkdown(stripPayUrls(m.text))
    : escapeHtml(cleanDashes(m.payment ? stripPayUrls(m.text) : m.text)).replace(/\n/g, '<br>');
  const pay = (m.sender === 'ai' || m.sender === 'admin') && m.payment ? paymentCard(m.payment) : '';
  const failChip = m.sender === 'admin' && m.delivery_failed
    ? `<div style="margin-top:6px"><span class="badge badge-lost">${icon('alert', 11)} ${t('conv.deliveryFailed')}</span></div>` : '';
  return `<div class="msg-row ${out ? 'out' : ''}">
    <div class="bubble ${cls}">${tag}${photo}${body ? `<div class="md-body">${body}</div>` : ''}${pay}${sourcesHTML(m)}${failChip}${flagHTML(m)}${groundingHTML(m)}
      <div class="b-meta">${m.created_at ? timeOf(m.created_at) : ''}</div></div></div>`;
}

function renderThread(mount) {
  const d = S.detail;
  const conv = d.conversation;
  const cust = d.customer;
  d.messages.forEach((m) => S.seen.add(m.id));
  const thread = mount.querySelector('#inbox-thread');
  thread.innerHTML = `
    <div class="thread-head">
      <button class="thread-back" id="thread-back" title="${t('conv.backToList')}">${BACK_ICON}</button>
      <button class="thread-tool" id="toggle-list" title="${t('conv.toggleListTitle')}">${icon('inbox', 16)}</button>
      ${avatarHTML(cust.name, cust.avatar)}
      <div style="flex:1;min-width:0">
        <div class="strong">${escapeHtml(cust.name)}</div>
        <div class="muted text-xs row gap-1" style="align-items:center">
          ${channelLogo(conv.channel, 15)}
          ${conv.channel} &middot; ${escapeHtml(conv.branch_name || t('conv.noBranch'))}
        </div>
      </div>
      ${conv.escalation_reason && conv.ai_enabled ? `<span class="badge badge-hot" title="${escapeHtml(conv.escalation_reason)}">${icon('alert', 12)} ${t('conv.requestAdmin')}</span>` : ''}
      <span class="badge ${conv.ai_enabled ? 'badge-olive' : 'badge-followup'}">
        ${conv.ai_enabled ? icon('ai', 12) + ' ' + t('conv.aiActive') : icon('user', 12) + ' ' + t('conv.human')}</span>
      <button class="thread-tool" id="toggle-panel" title="${t('conv.togglePanelTitle')}">${icon('info', 16)}</button>
    </div>
    <div class="thread-msgs" id="thread-msgs">
      ${d.messages.map(bubble).join('')}
      <div id="typing-slot"></div>
    </div>
    <div class="composer">
      <div class="composer-banner ${conv.ai_enabled ? 'ai' : 'human'}">
        <span>${conv.ai_enabled
          ? t('conv.aiReplyingBanner')
          : t('conv.takenOverBanner')}</span>
        ${conv.ai_enabled
          ? `<button class="btn btn-sm btn-clay" id="takeover-btn">${t('conv.takeOver')}</button>`
          : `<button class="btn btn-sm btn-ghost" id="return-btn">${t('conv.returnToAi')}</button>`}
      </div>
      <div class="composer-row">
        <textarea class="textarea" id="composer-input" rows="1"
          placeholder="${conv.ai_enabled ? t('conv.takeoverToReply') : t('conv.replyPlaceholder')}"
          ${conv.ai_enabled ? 'disabled' : ''}></textarea>
        <button class="btn btn-primary" id="send-btn" ${conv.ai_enabled ? 'disabled' : ''}>${icon('send', 16)}</button>
      </div>
    </div>`;

  d.messages.forEach((m) => { if (m.slip) applySlipState(thread, m.slip); });
  scrollThread(mount);
  const back = thread.querySelector('#thread-back');
  if (back) back.onclick = () => {
    const inbox = mount.querySelector('.inbox');
    if (inbox) inbox.classList.remove('show-thread');  // mobile: back to the list
  };
  const tl = thread.querySelector('#toggle-list');
  if (tl) tl.onclick = () => { S.hideList = !S.hideList; saveLayout(); applyLayout(mount); };
  const tp = thread.querySelector('#toggle-panel');
  if (tp) tp.onclick = () => { S.hidePanel = !S.hidePanel; saveLayout(); applyLayout(mount); };
  applyLayout(mount);  // sync the toggle buttons with the current layout
  const input = thread.querySelector('#composer-input');
  const send = async () => {
    // Replying is only allowed after "Take over" — the composer is disabled while
    // the AI owns the thread, and the server enforces the same rule (409).
    if (conv.ai_enabled) { toast(t('conv.takeoverRequired'), 'error'); return; }
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    try {
      await api.post(`/conversations/${conv.id}/messages`, { text });
    } catch (e) {
      toast(e.detail === 'takeover_required' ? t('conv.takeoverRequired')
        : (e.detail || t('conv.sendFailed')), 'error');
    }
  };
  thread.querySelector('#send-btn').onclick = send;
  input.onkeydown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  };
  const tk = thread.querySelector('#takeover-btn');
  if (tk) tk.onclick = async () => {
    await api.post(`/conversations/${conv.id}/takeover`);
    toast(t('conv.takeoverDone'), 'success');
    openConv(mount, conv.id);
  };
  const rt = thread.querySelector('#return-btn');
  if (rt) rt.onclick = async () => {
    const r = await api.post(`/conversations/${conv.id}/return-to-ai`).catch(() => ({}));
    toast(r.ai_replying ? t('conv.returnedReplying') : t('conv.returnedToAi'), 'success');
    openConv(mount, conv.id);
  };
}

function renderThreadEmpty(mount) {
  mount.querySelector('#inbox-thread').innerHTML =
    `<div class="thread-empty">${emptyState('chat', t('conv.selectConvTitle'), t('conv.selectConvSub'))}</div>`;
}

async function refreshPanel(mount) {
  if (!S.activeId) return;
  try {
    S.detail = await api.get(`/conversations/${S.activeId}`);
    renderPanel(mount);
  } catch (e) { /* keep the current panel if the refresh fails */ }
}

function renderPanel(mount) {
  const c = S.detail.customer;
  const conv = S.detail.conversation;
  const tempColor = { hot: 'var(--hot)', warm: 'var(--warm)', cold: 'var(--cold)' }[c.temperature] || 'var(--muted)';
  mount.querySelector('#inbox-panel').innerHTML = `
    <div class="center" style="margin-bottom:18px">
      <div style="width:52px;margin:0 auto 10px">${avatarHTML(c.name, c.avatar, 'lg')}</div>
      <div class="strong" style="font-size:15px">${escapeHtml(c.name)}${c.nickname ? ` <span class="muted" style="font-weight:500">“${escapeHtml(c.nickname)}”</span>` : ''}</div>
      <div class="muted text-sm">${escapeHtml(c.phone || c.email || conv.channel)}</div>
    </div>
    <div class="panel-section">
      <h4>${t('conv.leadScore')}</h4>
      <div class="row-between"><span class="strong" style="font-size:18px">${c.lead_score}</span>
        <span class="badge badge-${c.temperature}">${c.temperature}</span></div>
      <div class="score-bar"><span style="width:${c.lead_score}%;background:${tempColor}"></span></div>
    </div>
    <div class="panel-section">
      <h4>${t('conv.pipelineStage')}</h4>
      <div class="row wrap gap-1" id="stage-buttons">
        ${['new_lead', 'interested', 'booked', 'paid', 'followup'].map((s) => `
          <button class="badge ${s === conv.status ? (STATUS_BADGE[s]) : 'badge-soft'}" data-s="${s}"
            style="cursor:pointer;border:none">${STATUS_LABEL[s]}</button>`).join('')}
      </div>
    </div>
    <div class="panel-section">
      <h4>${t('conv.details')}</h4>
      <div class="kv"><span class="k">${t('conv.phone')}</span><span class="v">${escapeHtml(c.phone || '—')}</span></div>
      <div class="kv"><span class="k">${t('conv.email')}</span><span class="v" style="word-break:break-all;text-align:right">${escapeHtml(c.email || '—')}</span></div>
      <div class="kv"><span class="k">${t('menu.branch')}</span><span class="v">${escapeHtml(conv.branch_name || '—')}</span></div>
      <div class="kv"><span class="k">${t('conv.budget')}</span><span class="v">${escapeHtml(c.budget || '—')}</span></div>
      <div class="kv"><span class="k">${t('conv.kvInterested')}</span><span class="v">${escapeHtml(c.interested || '—')}</span></div>
      <div class="kv"><span class="k">${t('conv.concern')}</span><span class="v">${escapeHtml(c.concern || '—')}</span></div>
    </div>
    <div class="panel-section">
      <h4 class="row" style="gap:5px;align-items:center">${icon('ai', 13)} ${t('conv.aiSummary')}</h4>
      <div class="text-sm ${conv.ai_summary ? '' : 'muted'}"
        style="background:var(--surface-2);border:1px solid var(--border);border-radius:var(--r-md);padding:9px 11px;line-height:1.55">
        ${conv.ai_summary ? escapeHtml(conv.ai_summary) : t('conv.noSummaryYet')}</div>
    </div>
    ${store.canManage() ? `<button class="btn btn-clay btn-block btn-sm" id="charge-btn" style="margin-bottom:8px">${icon('card', 14)} ${t('conv.chargeCustom')}</button>` : ''}
    <a class="btn btn-ghost btn-block btn-sm" href="#/customers/${c.id}">${t('conv.viewFullProfile')}</a>`;

  mount.querySelectorAll('#stage-buttons [data-s]').forEach((b) => {
    b.onclick = async () => {
      try {
        await api.post(`/conversations/${conv.id}/status`, { status: b.dataset.s });
        toast(t('conv.stageUpdated'), 'success');
        openConv(mount, conv.id);
      } catch (e) { toast(e.detail || t('common.updateFailed'), 'error'); }
    };
  });

  const chargeBtn = mount.querySelector('#charge-btn');
  if (chargeBtn) chargeBtn.onclick = () => chargeModal(conv, c);
}

function chargeModal(conv, c) {
  modal({
    title: t('conv.chargeTitle'),
    body: `
      <div class="field-hint">${t('conv.chargeHint', { name: escapeHtml(c.name) })}</div>
      <div class="field"><label>${t('conv.amountBaht')}</label>
        <input class="input" id="ch-amount" type="number" min="1" step="1" placeholder="${t('conv.amountPlaceholder')}" autofocus></div>
      <div class="field"><label>${t('conv.labelField')} <span class="muted">${t('common.optional')}</span></label>
        <input class="input" id="ch-label" value="${t('conv.servicePayment')}" placeholder="${t('conv.servicePayment')}"></div>`,
    actions: [
      { label: t('common.cancel'), class: 'btn-ghost' },
      { label: t('conv.createSendLink'), class: 'btn-primary', keepOpen: true,
        onClick: async ({ close, modal: m }) => {
          const amount = Number(m.querySelector('#ch-amount').value);
          if (!amount || amount <= 0) { toast(t('conv.enterValidAmount'), 'error'); return; }
          const label = m.querySelector('#ch-label').value.trim();
          const btn = m.querySelector('.modal-foot .btn-primary');
          btn.disabled = true; btn.innerHTML = '<div class="spinner"></div>';
          try {
            await api.post(`/conversations/${conv.id}/charge`, { amount, label });
            toast(t('conv.linkSent'), 'success');
            close();
          } catch (ex) {
            toast(ex.detail || t('conv.createLinkFailed'), 'error');
            btn.disabled = false; btn.textContent = t('conv.createSendLink');
          }
        } },
    ],
  });
}

function scrollThread(mount) {
  const box = mount.querySelector('#thread-msgs');
  if (box) box.scrollTop = box.scrollHeight;
}

function handleWS(mount, ev) {
  if (ev.type === 'stream') {
    if (ev.conversation_id !== S.activeId) return;
    const slot = mount.querySelector('#typing-slot');
    if (!slot) return;
    const tr = mount.querySelector('#typing-row');
    if (tr) tr.remove();
    let sb = mount.querySelector('[data-streaming]');
    if (!sb) {
      slot.insertAdjacentHTML('beforebegin',
        '<div class="msg-row out" data-streaming><div class="bubble ai">'
        + `<div class="b-tag">${t('conv.aiAssistant')}</div><div class="sbody md-body"></div></div></div>`);
      sb = mount.querySelector('[data-streaming]');
    }
    sb.querySelector('.sbody').innerHTML = renderMarkdown(ev.text);
    scrollThread(mount);
    return;
  }

  if (ev.type === 'stream_cancel') {
    // the reply was withheld (human takeover mid-generation) — drop the partial bubble;
    // the system note explaining it arrives as a normal 'message' event right after
    if (ev.conversation_id !== S.activeId) return;
    const sb = mount.querySelector('[data-streaming]');
    if (sb) sb.remove();
    return;
  }

  if (ev.type === 'message') {
    const m = ev.message;
    if (ev.conversation_id === S.activeId && m && !S.seen.has(m.id)) {
      S.seen.add(m.id);
      const tr = mount.querySelector('#typing-row');
      if (tr) tr.remove();
      const sb = mount.querySelector('[data-streaming]');
      if (sb && m.sender === 'ai') {
        sb.removeAttribute('data-streaming');
        sb.querySelector('.sbody').innerHTML = renderMarkdown(stripPayUrls(m.text));
        const b = sb.querySelector('.bubble');
        if (m.payment) b.insertAdjacentHTML('beforeend', paymentCard(m.payment));
        b.insertAdjacentHTML('beforeend', sourcesHTML(m));
        b.insertAdjacentHTML('beforeend', flagHTML(m));
        b.insertAdjacentHTML('beforeend', groundingHTML(m));
        b.insertAdjacentHTML('beforeend', `<div class="b-meta">${m.created_at ? timeOf(m.created_at) : ''}</div>`);
      } else {
        const slot = mount.querySelector('#typing-slot');
        if (slot) slot.insertAdjacentHTML('beforebegin', bubble(m));
      }
      if (m.slip) applySlipState(mount, m.slip);
      scrollThread(mount);
    }
    const c = S.convs.find((x) => x.id === ev.conversation_id);
    if (c && m) {
      c.last_message = m.text;
      c.last_sender = m.sender;
      c.last_message_at = m.created_at;
      if (ev.conversation_id !== S.activeId && m.sender === 'customer') c.unread = true;
      S.convs = [c, ...S.convs.filter((x) => x.id !== c.id)];
      renderList(mount);
    } else {
      loadList(mount);
    }
  } else if (ev.type === 'conversation' && ev.summary) {
    const idx = S.convs.findIndex((x) => x.id === ev.conversation_id);
    if (idx >= 0) { S.convs[idx] = { ...S.convs[idx], ...ev.summary }; renderList(mount); }
    // The active conversation's customer may have just been enriched by post-reply
    // analysis (name / nickname / phone / email / lead score) — refresh the panel.
    if (ev.conversation_id === S.activeId) refreshPanel(mount);
  } else if (ev.type === 'typing' && ev.conversation_id === S.activeId) {
    const slot = mount.querySelector('#typing-slot');
    if (slot && !mount.querySelector('#typing-row') && !mount.querySelector('[data-streaming]')) {
      slot.insertAdjacentHTML('beforebegin',
        '<div class="msg-row" id="typing-row"><div class="bubble ai"><div class="typing"><span></span><span></span><span></span></div></div></div>');
      scrollThread(mount);
    }
  } else if (ev.type === 'payment' && ev.status === 'paid') {
    // settle the pay-card in the open thread (the system confirmation message
    // arrives as its own 'message' event and updates the list separately).
    mount.querySelectorAll(`[data-payment="${ev.payment_id}"]`).forEach((el) => markPayCardPaid(el));
  }
}
