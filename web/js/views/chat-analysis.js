/* Blinks Bright — Chat Analysis: what customers write, how they feel, when they come.

   All charts are dependency-free and deterministic, mirroring the backend
   (app/services/chat_insights.py). Design notes:
   - Sentiment uses a CVD-safe diverging pair (sky = positive, deep amber = negative,
     warm gray = the neutral midpoint) — green↔rose fails deutan ΔE and is avoided.
   - The word cloud is all-horizontal (rotated Thai is unreadable) and sized by
     sqrt(count); color carries KIND only (clinic treatment vs general term).
   - Channel colors + labels are the SAME entities as the Overview dashboard
     (color follows the entity across pages, never re-assigned per page). */

import { api } from '../api.js';
import { store } from '../store.js';
import { router } from '../router.js';
import { icon, num, escapeHtml, loadingBlock, emptyState } from '../ui.js';
import { donut, legend, barList } from '../charts.js';
import { t } from '../i18n.js';

const CH = {
  web: { label: t('dash.chWeb'), color: 'var(--chart-1)' },
};
const POS = 'var(--senti-pos)', NEG = 'var(--senti-neg)', NEU = 'var(--senti-neu)';

export default async function renderChatAnalysis(mount) {
  mount.innerHTML = `<div class="view chatanl">
    <div class="dash-hero">
      <div><h2>${t('chatanl.title')}</h2>
        <p class="muted">${t('chatanl.subtitle')}</p></div>
      <div class="segmented" id="ca-range">
        ${['7d', '30d', '90d', '1y', 'all'].map((r) => `
          <button data-r="${r}" class="${store.dateRange === r ? 'active' : ''}">${
            r === 'all' ? t('common.all') : t('dash.days' + { '7d': 7, '30d': 30, '90d': 90, '1y': 365 }[r])
          }</button>`).join('')}
      </div>
    </div>
    <div id="ca-body">${loadingBlock()}</div>
  </div>`;

  const body = mount.querySelector('#ca-body');
  mount.querySelectorAll('#ca-range button').forEach((b) => {
    b.onclick = () => {
      mount.querySelectorAll('#ca-range button').forEach((x) => x.classList.toggle('active', x === b));
      store.set('dateRange', b.dataset.r);   // shared with Dashboard + Payments
      load();
    };
  });

  async function load() {
    body.innerHTML = loadingBlock();
    const p = new URLSearchParams({ period: store.dateRange });
    if (store.branchId && store.branchId !== 'all') p.set('branch_id', store.branchId);
    let d;
    try { d = await api.get('/chat-analysis?' + p.toString()); }
    catch (e) { body.innerHTML = emptyState('alert', t('chatanl.loadFailed')); return; }
    if (!d.totals.customer_msgs) {
      body.innerHTML = emptyState('chat', t('chatanl.noData'))
        + (store.dateRange !== 'all'
          ? `<div style="text-align:center;margin-top:-6px">
               <button class="btn btn-primary btn-sm" id="ca-all">${t('chatanl.viewAllTime')}</button></div>`
          : '');
      const b = body.querySelector('#ca-all');
      if (b) b.onclick = () => {
        store.set('dateRange', 'all');
        mount.querySelectorAll('#ca-range button').forEach((x) =>
          x.classList.toggle('active', x.dataset.r === 'all'));
        load();
      };
      return;
    }
    body.innerHTML = renderBody(d);
    renderWordcloud(body.querySelector('#ca-cloud'), d.words);
    body.querySelectorAll('[data-conv]').forEach((el) =>
      (el.onclick = () => router.go('conversations/' + el.dataset.conv)));
  }
  load();
}

/* ---------------- KPI tiles ---------------- */

function statCard(label, value, ic, color) {
  return `<div class="stat-card" style="--ic:${color}">
    <div class="stat-top"><span class="stat-label">${label}</span>
      <span class="stat-ic">${icon(ic, 16)}</span></div>
    <div class="stat-value">${value}</div>
  </div>`;
}

function fmtDuration(sec) {
  if (sec == null) return '—';
  if (sec < 90) return t('chatanl.seconds', { n: sec });
  if (sec < 5400) return t('chatanl.minutes', { n: Math.round(sec / 60) });
  return t('chatanl.hoursUnit', { n: (sec / 3600).toFixed(1) });
}

/* ---------------- sentiment ---------------- */

function sentiShare(s) {
  const total = s.positive + s.neutral + s.negative || 1;
  const pct = Math.round((s.positive / total) * 100);
  const seg = (v, color) => (v ? `<div style="flex:${v};background:${color}"></div>` : '');
  const rows = [
    { label: t('chatanl.positive'), value: s.positive, color: POS },
    { label: t('chatanl.neutral'), value: s.neutral, color: NEU },
    { label: t('chatanl.negative'), value: s.negative, color: NEG },
  ];
  return `
    <div class="senti-lead"><span class="senti-pct">${pct}%</span>
      <span class="muted text-sm">${t('chatanl.positiveShare')}</span></div>
    <div class="senti-bar">${seg(s.positive, POS)}${seg(s.neutral, NEU)}${seg(s.negative, NEG)}</div>
    ${legend(rows)}`;
}

/* Diverging daily/monthly columns — positive up, negative down from one baseline. */
function sentiTrend(trend, mode) {
  if (!trend.length) return `<div class="muted text-sm">${t('common.noData')}</div>`;
  const W = 760, H = 200, mL = 34, mR = 10, mT = 14, mB = 24;
  const plotW = W - mL - mR, half = (H - mT - mB) / 2, mid = mT + half;
  const peak = Math.max(1, ...trend.map((x) => Math.max(x.positive, x.negative)));
  const slot = plotW / trend.length;
  const bw = Math.min(24, Math.max(3, slot - 2));
  const yScale = (v) => (v / peak) * (half - 4);
  const fmt = (lb) => {
    if (mode === 'month') {
      const [y, m] = lb.split('-');
      return `${t('time.month' + (Number(m) - 1))} ${y.slice(2)}`;
    }
    const [, m, d] = lb.split('-');
    return `${Number(d)}/${Number(m)}`;
  };
  let bars = '', labels = '';
  const stride = Math.max(1, Math.ceil(trend.length / 8));
  trend.forEach((x, i) => {
    const cx = mL + i * slot + slot / 2;
    const tip = `<title>${escapeHtml(fmt(x.label))} · ${t('chatanl.positive')} ${x.positive} · ${t('chatanl.negative')} ${x.negative} · ${t('chatanl.neutral')} ${x.neutral}</title>`;
    if (x.positive) {
      const h = yScale(x.positive);
      bars += `<g>${tip}<rect x="${(cx - bw / 2).toFixed(1)}" y="${(mid - 1 - h).toFixed(1)}"
        width="${bw.toFixed(1)}" height="${h.toFixed(1)}" rx="2" fill="${POS}"/></g>`;
    }
    if (x.negative) {
      const h = yScale(x.negative);
      bars += `<g>${tip}<rect x="${(cx - bw / 2).toFixed(1)}" y="${mid + 1}"
        width="${bw.toFixed(1)}" height="${h.toFixed(1)}" rx="2" fill="${NEG}"/></g>`;
    }
    if (!x.positive && !x.negative && x.neutral) {
      // a chatty-but-neutral day still exists — a quiet tick on the baseline, so the
      // chart never reads as "no conversations" when there were plenty
      bars += `<g>${tip}<rect x="${(cx - bw / 2).toFixed(1)}" y="${mid - 1.5}"
        width="${bw.toFixed(1)}" height="3" rx="1.5" fill="${NEU}"/></g>`;
    }
    if (i % stride === 0 || i === trend.length - 1) {
      const anchor = i === 0 ? 'start' : i === trend.length - 1 ? 'end' : 'middle';
      labels += `<text x="${cx.toFixed(1)}" y="${H - 7}" text-anchor="${anchor}" font-size="10.5"
        fill="var(--muted)" font-family="Inter">${escapeHtml(fmt(x.label))}</text>`;
    }
  });
  return `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto;display:block">
    <line x1="${mL}" x2="${W - mR}" y1="${mid}" y2="${mid}" stroke="var(--border-2)" stroke-width="1"/>
    <text x="${mL - 6}" y="${mT + 8}" text-anchor="end" font-size="10" fill="var(--muted)" font-family="Inter">${num(peak)}</text>
    <text x="${mL - 6}" y="${H - mB + 2}" text-anchor="end" font-size="10" fill="var(--muted)" font-family="Inter">${num(peak)}</text>
    ${bars}${labels}
  </svg>
  <div class="muted text-xs" style="margin-top:4px">${t('chatanl.trendHint')}</div>`;
}

/* ---------------- busiest hours (7×24, Bangkok) ---------------- */

function heatmap(hours) {
  const max = Math.max(1, ...hours.flat());
  // rows arrive [Mon..Sun]; time.dow* keys are JS getDay() order (0 = Sunday)
  const rows = hours.map((row, i) => {
    const dow = t('time.dow' + ((i + 1) % 7));
    const cells = row.map((c, h) => {
      const bg = c ? `color-mix(in srgb, var(--chart-2) ${Math.round(10 + (c / max) * 76)}%, var(--surface))` : 'var(--surface-2)';
      return `<div class="hm-cell" style="background:${bg}" title="${dow} ${String(h).padStart(2, '0')}:00 · ${c} ${t('chatanl.msgsUnit')}"></div>`;
    }).join('');
    return `<div class="hm-dow">${dow}</div><div class="hm-row">${cells}</div>`;
  }).join('');
  const ticks = [0, 3, 6, 9, 12, 15, 18, 21]
    .map((h) => `<span style="left:${(h / 24) * 100}%">${String(h).padStart(2, '0')}</span>`).join('');
  return `<div class="hm-grid">${rows}
    <div></div><div class="hm-ticks">${ticks}</div></div>
  <div class="muted text-xs" style="margin-top:6px">${t('chatanl.busyHint')}</div>`;
}

/* ---------------- word cloud (spiral placement, all horizontal) ---------------- */

function renderWordcloud(host, words) {
  if (!host) return;
  if (!words.length) { host.innerHTML = `<div class="muted text-sm" style="padding:28px;text-align:center">${t('common.noData')}</div>`; return; }
  const W = Math.max(host.clientWidth || 640, 320), H = 292;
  const ctx = document.createElement('canvas').getContext('2d');
  const counts = words.map((w) => w.count);
  const max = Math.max(...counts), min = Math.min(...counts);
  const fsize = (c) => 13 + Math.sqrt((c - min) / Math.max(max - min, 1)) * 32;
  const placed = [];
  const fits = (x, y, w, h) =>
    x - w / 2 > 2 && x + w / 2 < W - 2 && y - h / 2 > 2 && y + h / 2 < H - 2 &&
    !placed.some((p) => Math.abs(x - p.x) < (w + p.w) / 2 + 4 && Math.abs(y - p.y) < (h + p.h) / 2 + 3);
  let out = '';
  for (const wd of words) {
    const fs = fsize(wd.count);
    ctx.font = `600 ${fs}px Inter, 'Noto Sans Thai', sans-serif`;
    const w = ctx.measureText(wd.text).width + 6, h = fs * 1.3;
    let x = W / 2, y = H / 2, ok = fits(x, y, w, h);
    for (let a = 0.6; !ok && a < 220; a += 0.32) {
      const r = 3.1 * a;
      if (r > W) break;
      x = W / 2 + r * Math.cos(a);
      y = H / 2 + r * 0.58 * Math.sin(a);
      ok = fits(x, y, w, h);
    }
    if (!ok) continue;
    placed.push({ x, y, w, h });
    const color = wd.kind === 'treatment' ? 'var(--chart-2)' : 'var(--ink-2)';
    out += `<text x="${x.toFixed(1)}" y="${y.toFixed(1)}" text-anchor="middle" dominant-baseline="middle"
      font-size="${fs.toFixed(1)}" font-weight="600" fill="${color}"
      font-family="Inter, 'Noto Sans Thai', sans-serif"><title>${escapeHtml(wd.text)} · ${t('chatanl.mentions', { n: wd.count })}</title>${escapeHtml(wd.text)}</text>`;
  }
  host.innerHTML = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto;display:block">${out}</svg>`;
}

/* ---------------- page body ---------------- */

function renderBody(d) {
  const s = d.sentiment;
  const chSeg = d.channels.map((c) => ({
    label: (CH[c.channel] || {}).label || c.channel,
    value: c.count,
    color: (CH[c.channel] || {}).color || 'var(--chart-7)',
  }));
  const totalCh = chSeg.reduce((a, b) => a + b.value, 0);

  return `
    <div class="grid grid-5" style="margin-bottom:16px">
      ${statCard(t('chatanl.statMessages'), num(d.totals.customer_msgs), 'chat', 'var(--chart-1)')}
      ${statCard(t('chatanl.statCustomers'), num(d.totals.customers), 'users', 'var(--chart-2)')}
      ${statCard(t('chatanl.statAiReplies'), num(d.totals.ai_msgs), 'ai', 'var(--chart-5)')}
      ${statCard(t('chatanl.statTakeovers'), num(d.totals.takeovers), 'user', 'var(--chart-6)')}
      ${statCard(t('chatanl.statReplyTime'), fmtDuration(d.totals.median_reply_seconds), 'clock', 'var(--chart-4)')}
    </div>

    <div class="grid grid-3" style="margin-bottom:16px">
      <div class="card span-2">
        <div class="card-head"><h4>${t('chatanl.wordcloud')}</h4>
          <span class="sub">${legendInline()}</span></div>
        <div class="card-body" id="ca-cloud" style="min-height:292px"></div>
      </div>
      <div class="card">
        <div class="card-head"><h4>${t('chatanl.sentiment')}</h4></div>
        <div class="card-body">${sentiShare(s)}</div>
      </div>
    </div>

    <div class="grid grid-3" style="margin-bottom:16px">
      <div class="card span-2">
        <div class="card-head"><h4>${t('chatanl.sentimentTrend')}</h4></div>
        <div class="card-body">${sentiTrend(s.trend, s.mode)}</div>
      </div>
      <div class="card">
        <div class="card-head"><h4>${t('chatanl.byChannel')}</h4></div>
        <div class="card-body" style="display:flex;flex-direction:column;align-items:center;gap:14px">
          ${donut(chSeg, { centerLabel: num(totalCh), centerSub: t('chatanl.msgsUnit') })}
          ${legend(chSeg)}
        </div>
      </div>
    </div>

    <div class="grid grid-3">
      <div class="card">
        <div class="card-head"><h4>${t('chatanl.topTopics')}</h4></div>
        <div class="card-body">${d.topics.length
          ? barList(d.topics.map((x) => ({ label: x.name, value: x.count })), { color: 'var(--chart-2)' })
          : `<div class="muted text-sm">${t('common.noData')}</div>`}</div>
      </div>
      <div class="card">
        <div class="card-head"><h4>${t('chatanl.busyHours')}</h4></div>
        <div class="card-body">${heatmap(d.hours)}</div>
      </div>
      <div class="card">
        <div class="card-head"><h4>${t('chatanl.attention')}</h4>
          <span class="sub">${t('chatanl.attentionHint')}</span></div>
        <div class="card-body" style="padding-top:6px">
          ${d.attention.length ? d.attention.map((a) => `
            <div class="att-row" data-conv="${a.conversation_id}">
              <span class="att-dot"></span>
              <div class="att-main">
                <div class="att-top"><span class="strong text-sm">${escapeHtml(a.customer)}</span>
                  <span class="muted text-xs">${escapeHtml(fmtAt(a.at))}</span></div>
                <div class="muted text-sm truncate">${escapeHtml(a.text)}</div>
              </div>
            </div>`).join('')
          : `<div class="muted text-sm" style="padding-top:8px">${t('chatanl.noNegative')}</div>`}
        </div>
      </div>
    </div>`;
}

function legendInline() {
  return `<span class="wc-leg"><i style="background:var(--chart-2)"></i>${t('chatanl.wcTreatment')}</span>
    <span class="wc-leg"><i style="background:var(--ink-2)"></i>${t('chatanl.wcGeneral')}</span>`;
}

function fmtAt(iso) {
  // backend sends Bangkok-local "YYYY-MM-DDTHH:MM"
  const [date, time] = String(iso).split('T');
  if (!time) return iso;
  const [, m, day] = date.split('-');
  return `${time} · ${Number(day)}/${Number(m)}`;
}
