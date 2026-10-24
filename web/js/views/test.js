/* Blinks Bright — Test Console (live chat simulator) */

import { api } from '../api.js';
import { store } from '../store.js';
import { setWSHandler } from '../ws.js';
import { icon, escapeHtml, initials, channelLogo, timeOf, toast, emptyState, renderMarkdown, paymentCard, markPayCardPaid, stripPayUrls } from '../ui.js';
import { t } from '../i18n.js';

const CHANNELS = [
  ['web', t('test.chWeb'), 'globe'],
];
const CHANNEL_LABEL = Object.fromEntries(CHANNELS.map(([v, l]) => [v, l]));

// Session state for the simulated customer — module-level (not reset inside
// renderTestConsole) so switching the topbar's active branch, which remounts
// this whole view, never wipes the active tab or an in-progress simulated
// chat; only clicking "New" (start over) does.
const S = { name: '', channel: 'web', uid: null, convId: null, started: false, seen: new Set(), tab: 'chat' };

function newUid(channel, name) {
  const slug = (name || 'visitor').toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 20) || 'visitor';
  return `${channel}_sim_${slug}_${Date.now().toString(36)}${Math.floor(Math.random() * 1e4)}`;
}

export default async function renderTestConsole(mount) {
  if (!store.isRole('owner', 'super_admin')) {
    mount.innerHTML = `<div class="view"><div class="card card-pad">${
      emptyState('lock', t('test.restrictedTitle'), t('test.restrictedSub'))
    }</div></div>`;
    return;
  }

  mount.innerHTML = `<div class="view tc-view">
    <div class="view-head">
      <div><h2>${t('test.title')}</h2>
        <p>${t('test.subtitle')}</p></div>
      <div class="seg-tabs" id="tc-tabs">
        <button class="seg${S.tab === 'chat' ? ' active' : ''}" data-tab="chat">${icon('chat', 14)} ${t('test.tabChat')}</button>
        <button class="seg${S.tab === 'tools' ? ' active' : ''}" data-tab="tools">${icon('zap', 14)} ${t('test.tabTools')}</button>
      </div>
    </div>
    <div id="tc-chat-panel" class="tc-sim" ${S.tab === 'tools' ? 'hidden' : ''}></div>
    <div id="tc-tools-panel" ${S.tab === 'chat' ? 'hidden' : ''}></div>
  </div>`;

  const tabs = mount.querySelector('#tc-tabs');
  const chatPanel = mount.querySelector('#tc-chat-panel');
  const toolsPanel = mount.querySelector('#tc-tools-panel');
  tabs.querySelectorAll('.seg').forEach((b) => {
    b.onclick = () => {
      tabs.querySelectorAll('.seg').forEach((x) => x.classList.toggle('active', x === b));
      S.tab = b.dataset.tab;
      const chat = S.tab === 'chat';
      chatPanel.hidden = !chat;
      toolsPanel.hidden = chat;
      if (!chat && !toolsPanel.dataset.ready) renderTools(toolsPanel);
    };
  });

  if (S.tab === 'tools') renderTools(toolsPanel);
  // Resume an in-progress simulated chat (e.g. after a branch-switch remount)
  // instead of always dropping back to the setup screen.
  if (S.started) renderChat(mount); else renderSetup(mount);
  // one global realtime handler for the whole view; it filters by the active sim conversation
  setWSHandler((ev) => handleWS(mount, ev));
}

/* ----------------------------- setup screen ----------------------------- */
async function renderSetup(mount) {
  const panel = mount.querySelector('#tc-chat-panel');
  panel.innerHTML = `
    <div class="tc-setup card">
      <div class="tc-setup-icon">${icon('chat', 26)}</div>
      <h3>${t('test.setupTitle')}</h3>
      <p class="muted">${t('test.setupSub')}</p>

      <div class="field"><label>${t('test.nameLabel')}</label>
        <input class="input" id="tc-name" placeholder="${t('test.namePlaceholder')}" value="${escapeHtml(S.name)}"></div>

      <button class="btn btn-primary btn-block" id="tc-start">${icon('send', 16)} &nbsp;${t('test.startChat')}</button>
    </div>`;

  const nameEl = panel.querySelector('#tc-name');
  const start = () => {
    S.name = nameEl.value.trim() || t('test.testerName', { channel: CHANNEL_LABEL[S.channel] });
    S.uid = newUid(S.channel, S.name);
    S.convId = null;
    S.started = true;
    S.seen = new Set();
    renderChat(mount);
  };
  panel.querySelector('#tc-start').onclick = start;
  nameEl.onkeydown = (e) => { if (e.key === 'Enter') start(); };
}

/* ------------------------------ chat screen ----------------------------- */
async function renderChat(mount) {
  const panel = mount.querySelector('#tc-chat-panel');
  const accent = (store.clinic && store.clinic.accent) || 'var(--primary)';
  const chIc = (CHANNELS.find((c) => c[0] === S.channel) || [, , 'globe'])[2];
  panel.innerHTML = `
    <div class="tc-chat">
      <div class="tc-chat-head" style="background:${escapeHtml(accent)}">
        <div class="avatar">${escapeHtml(initials(S.name))}</div>
        <div class="tc-chat-id">
          <div class="strong">${escapeHtml(S.name)}</div>
          <div class="tc-chat-sub">${channelLogo(S.channel, 14)} ${escapeHtml(CHANNEL_LABEL[S.channel])} · ${t('test.simCustomer')}</div>
        </div>
        <a class="btn btn-sm tc-head-btn" id="tc-open" style="display:none" title="${t('test.openInConversations')}">${icon('external', 13)} ${t('test.records')}</a>
        <button class="btn btn-sm tc-head-btn" id="tc-new" title="${t('test.startOver')}">${icon('refresh', 13)} ${t('test.newBtn')}</button>
      </div>

      <div class="tc-chat-msgs" id="tc-msgs">
        <div class="tc-chat-hello">${emptyState('chat', t('test.firstMsgTitle'), t('test.firstMsgSub', { name: escapeHtml(S.name) }))}</div>
        <div id="tc-typing-slot"></div>
      </div>

      <div class="composer">
        <div class="composer-row">
          <textarea class="textarea" id="tc-input" rows="1" placeholder="${t('test.inputPlaceholder')}"></textarea>
          <button class="btn btn-primary" id="tc-send">${icon('send', 16)}</button>
        </div>
      </div>
    </div>`;

  panel.querySelector('#tc-new').onclick = () => { S.started = false; renderSetup(mount); };

  const input = panel.querySelector('#tc-input');
  const send = async () => {
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    const hello = panel.querySelector('.tc-chat-hello');
    if (hello) hello.remove();
    appendBubble(mount, 'customer', text, new Date().toISOString());
    showTyping(mount);
    try {
      const r = await api.post('/test/simulate', {
        channel: S.channel, name: S.name, channel_user_id: S.uid, text,
      });
      S.convId = r.conversation_id;
      const open = panel.querySelector('#tc-open');
      if (open) { open.href = `#/conversations/${S.convId}`; open.style.display = ''; }
      // Safety net: realtime should stream the reply, but if a WS frame is missed
      // (timing on the first message, a dropped connection), pull it from the DB.
      const cid = r.conversation_id;
      [1600, 4000, 8000, 13000].forEach((ms) => setTimeout(() => pollReply(mount, cid), ms));
    } catch (e) {
      const tr = mount.querySelector('#tc-typing-row'); if (tr) tr.remove();
      toast(e.detail || t('test.sendFailed'), 'error');
    }
  };
  panel.querySelector('#tc-send').onclick = send;
  input.onkeydown = (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } };
  input.focus();

  // Resuming an already-started session (e.g. after a branch-switch remount)
  // — replay the transcript so the chat doesn't look empty despite still
  // being the same simulated conversation underneath.
  if (S.convId) {
    const open = panel.querySelector('#tc-open');
    if (open) { open.href = `#/conversations/${S.convId}`; open.style.display = ''; }
    try {
      const d = await api.get(`/conversations/${S.convId}`);
      if (d && d.messages && d.messages.length) {
        const hello = panel.querySelector('.tc-chat-hello');
        if (hello) hello.remove();
        d.messages.forEach((m) => {
          if (m.sender === 'system') return;
          S.seen.add(m.id);
          appendBubble(mount, m.sender, m.text, m.created_at, m.payment);
        });
      }
    } catch (e) { /* a fresh-looking chat is an acceptable fallback */ }
  }
}

function bubbleHTML(sender, text, created_at, payment) {
  const isCustomer = sender === 'customer';
  const tag = sender === 'ai' ? `<div class="b-tag">${t('test.tagAI')}</div>`
            : sender === 'admin' ? `<div class="b-tag">${t('test.tagStaff')}</div>` : '';
  const body = sender === 'ai' ? renderMarkdown(stripPayUrls(text))
             : escapeHtml(payment ? stripPayUrls(text) : text).replace(/\n/g, '<br>');
  // admin (human staff) messages can carry a pay-card too — e.g. a custom charge
  const pay = (sender === 'ai' || sender === 'admin') && payment ? paymentCard(payment) : '';
  return `<div class="msg-row ${isCustomer ? 'out' : ''}">
    <div class="bubble ${isCustomer ? 'admin' : 'ai'}">${tag}
      <div class="md-body">${body}</div>${pay}
      <div class="b-meta">${created_at ? timeOf(created_at) : ''}</div></div></div>`;
}

function appendBubble(mount, sender, text, created_at, payment) {
  const slot = mount.querySelector('#tc-typing-slot');
  if (!slot) return;
  slot.insertAdjacentHTML('beforebegin', bubbleHTML(sender, text, created_at, payment));
  scrollMsgs(mount);
}

function scrollMsgs(mount) {
  const box = mount.querySelector('#tc-msgs');
  if (box) box.scrollTop = box.scrollHeight;
}

function showTyping(mount) {
  const slot = mount.querySelector('#tc-typing-slot');
  if (slot && !mount.querySelector('#tc-typing-row') && !mount.querySelector('[data-tc-stream]')) {
    slot.insertAdjacentHTML('beforebegin',
      '<div class="msg-row" id="tc-typing-row"><div class="bubble ai"><div class="typing"><span></span><span></span><span></span></div></div></div>');
    scrollMsgs(mount);
  }
}

/* An incoming clinic note (e.g. a payment confirmation back to the customer). */
function appendNotice(mount, text) {
  const slot = mount.querySelector('#tc-typing-slot');
  if (!slot) return;
  slot.insertAdjacentHTML('beforebegin',
    `<div class="msg-row"><div class="bubble ai"><div class="md-body">${escapeHtml(text)}</div></div></div>`);
  scrollMsgs(mount);
}

/* Fallback: if a realtime event is missed (timing / a dropped WS frame), fetch the
   AI reply straight from the server so the Test Console never sits silent. */
async function pollReply(mount, convId) {
  if (S.convId !== convId) return;
  let d;
  try { d = await api.get(`/conversations/${convId}`); } catch (e) { return; }
  if (S.convId !== convId || !d || !d.messages) return;
  let added = false;
  for (const m of d.messages) {
    if (m.sender === 'customer' || m.sender === 'system' || S.seen.has(m.id)) continue;
    S.seen.add(m.id);
    const tr = mount.querySelector('#tc-typing-row'); if (tr) tr.remove();
    const sb = mount.querySelector('[data-tc-stream]'); if (sb) sb.remove();
    appendBubble(mount, m.sender, m.text, m.created_at, m.payment);
    added = true;
  }
  if (added) scrollMsgs(mount);
}

/* --------------------------- realtime handler --------------------------- */
function handleWS(mount, ev) {
  if (!S.convId || ev.conversation_id !== S.convId) return;
  const slot = mount.querySelector('#tc-typing-slot');
  if (!slot) return;

  if (ev.type === 'payment' && ev.status === 'paid') {
    // settle the pay-card, and tell the customer once it actually flips to paid
    const cards = [...mount.querySelectorAll(`[data-payment="${ev.payment_id}"]`)];
    const wasUnpaid = cards.some((el) => !el.classList.contains('paid'));
    cards.forEach((el) => markPayCardPaid(el));
    if (wasUnpaid) appendNotice(mount, t('test.paymentReceived'));
    return;
  }

  if (ev.type === 'typing') {
    if (!mount.querySelector('#tc-typing-row') && !mount.querySelector('[data-tc-stream]')) {
      slot.insertAdjacentHTML('beforebegin',
        '<div class="msg-row" id="tc-typing-row"><div class="bubble ai"><div class="typing"><span></span><span></span><span></span></div></div></div>');
      scrollMsgs(mount);
    }
    return;
  }

  if (ev.type === 'stream') {
    const tr = mount.querySelector('#tc-typing-row'); if (tr) tr.remove();
    let sb = mount.querySelector('[data-tc-stream]');
    if (!sb) {
      slot.insertAdjacentHTML('beforebegin',
        `<div class="msg-row" data-tc-stream><div class="bubble ai"><div class="b-tag">${t('test.tagAI')}</div><div class="sbody md-body"></div></div></div>`);
      sb = mount.querySelector('[data-tc-stream]');
    }
    sb.querySelector('.sbody').innerHTML = renderMarkdown(ev.text);
    scrollMsgs(mount);
    return;
  }

  if (ev.type === 'message') {
    const m = ev.message;
    // the customer's own message is already shown; system notes stay internal.
    // AI *and* human-agent ("admin") replies are delivered to the customer → show both.
    if (!m || m.sender === 'customer' || m.sender === 'system') return;
    const tr = mount.querySelector('#tc-typing-row'); if (tr) tr.remove();
    const sb = mount.querySelector('[data-tc-stream]');
    if (S.seen.has(m.id)) { if (sb) sb.remove(); return; }   // already shown (poll fallback)
    S.seen.add(m.id);
    if (m.sender === 'ai' && sb) {
      sb.removeAttribute('data-tc-stream');
      sb.querySelector('.sbody').innerHTML = renderMarkdown(stripPayUrls(m.text));
      const b = sb.querySelector('.bubble');
      if (m.payment) b.insertAdjacentHTML('beforeend', paymentCard(m.payment));
      b.insertAdjacentHTML('beforeend', `<div class="b-meta">${m.created_at ? timeOf(m.created_at) : ''}</div>`);
    } else {
      if (sb) sb.removeAttribute('data-tc-stream');  // drop any stray streaming bubble
      appendBubble(mount, m.sender, m.text, m.created_at, m.payment);
    }
    scrollMsgs(mount);
  }
}

/* ---------------------- diagnostics (secondary tab) --------------------- */
function renderTools(panel) {
  panel.dataset.ready = '1';
  panel.innerHTML = `
    <div class="tc-grid">
      <div class="card span-2">
        <div class="card-head"><h4>${icon('zap', 16)} &nbsp;${t('test.connChecks')}</h4>
          <button class="btn btn-ghost btn-sm" id="conn-btn">${t('test.runChecks')}</button></div>
        <div class="card-body" id="conn-result">
          <div class="muted">${t('test.connHint')}</div></div>
      </div>
      <div class="card">
        <div class="card-head"><h4>${icon('ai', 16)} &nbsp;${t('test.aiSandbox')}</h4></div>
        <div class="card-body">
          <div class="field"><label>${t('test.askAILabel')}</label>
            <textarea class="textarea" id="sb-text" rows="3" placeholder="${t('test.askAIPlaceholder')}"></textarea></div>
          <button class="btn btn-primary btn-block" id="sb-btn">${t('test.runAI')}</button>
          <div id="sb-result" class="mt-3"></div>
        </div>
      </div>
    </div>`;

  panel.querySelector('#conn-btn').onclick = async (e) => {
    const out = panel.querySelector('#conn-result');
    e.target.disabled = true;
    out.innerHTML = '<div class="loading-block"><div class="spinner"></div></div>';
    try {
      const r = await api.get('/test/connections');
      const labels = { openai: t('test.connOpenai'), gemini: t('test.connGemini'),
        payment_qr: t('test.connPaymentQr') };
      out.innerHTML = Object.entries(labels).map(([k, label]) => {
        const s = r[k] || { ok: false, detail: '—' };
        return `<div class="conn-row"><span class="conn-dot ${s.ok ? 'ok' : 'bad'}"></span>
          <span class="strong" style="width:230px">${label}</span>
          <span class="muted text-sm">${escapeHtml(s.detail)}</span></div>`;
      }).join('');
    } catch (err) { out.innerHTML = `<div class="field-error">${escapeHtml(err.detail || t('test.failed'))}</div>`; }
    e.target.disabled = false;
  };

  panel.querySelector('#sb-btn').onclick = async (e) => {
    const text = panel.querySelector('#sb-text').value.trim();
    if (!text) return toast(t('test.enterQuestion'), 'error');
    const out = panel.querySelector('#sb-result');
    e.target.disabled = true;
    out.innerHTML = '<div class="loading-block"><div class="spinner"></div></div>';
    try {
      const r = await api.post('/test/ai-sandbox', { text });
      out.innerHTML = `
        <div class="b-tag" style="color:var(--primary);font-weight:700;font-size:10px">${t('test.aiReply')}</div>
        <div class="card card-pad md-body" style="margin:4px 0 10px;background:var(--primary-soft)">
          ${renderMarkdown(r.reply || t('test.noReply'))}</div>
        <div class="muted text-xs" style="margin-bottom:4px">${t('test.retrievedKb', { count: r.chunks.length })}</div>
        ${r.chunks.map((c) => `<div class="sandbox-chunk">
            <span class="sc-score">${(c.score * 100).toFixed(0)}%</span>
            &nbsp;<strong>${escapeHtml(c.title)}</strong>
            <span class="badge badge-soft" style="margin-left:4px">${c.source_type}</span></div>`).join('')
        || `<div class="muted text-xs">${t('test.noKbChunks')}</div>`}`;
    } catch (err) { out.innerHTML = `<div class="field-error">${escapeHtml(err.detail || t('test.failed'))}</div>`; }
    e.target.disabled = false;
  };
}
