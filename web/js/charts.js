/* Blinks Bright — lightweight SVG/HTML charts (dependency-free) */

import { escapeHtml, num } from './ui.js';

/** Catmull-Rom → cubic-bezier smoothing. pts: [[x,y],...] → SVG path data. */
function smoothPath(pts, clampY) {
  if (pts.length < 2) return '';
  const f = (n) => n.toFixed(1);
  if (pts.length === 2)
    return `M${f(pts[0][0])} ${f(pts[0][1])} L${f(pts[1][0])} ${f(pts[1][1])}`;
  // A cubic Bézier stays within its control points' convex hull, so clamping the control
  // ys to the plot's [top, baseline] keeps a sharp 0->peak->0 curve from overshooting below
  // zero (a "negative" dip) or above the top.
  const cy = clampY ? (y) => Math.max(clampY[0], Math.min(clampY[1], y)) : (y) => y;
  let d = `M${f(pts[0][0])} ${f(pts[0][1])}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] || pts[i];
    const p1 = pts[i];
    const p2 = pts[i + 1];
    const p3 = pts[i + 2] || p2;
    const c1x = p1[0] + (p2[0] - p0[0]) / 6;
    const c1y = cy(p1[1] + (p2[1] - p0[1]) / 6);
    const c2x = p2[0] - (p3[0] - p1[0]) / 6;
    const c2y = cy(p2[1] - (p3[1] - p1[1]) / 6);
    d += ` C${f(c1x)} ${f(c1y)} ${f(c2x)} ${f(c2y)} ${f(p2[0])} ${f(p2[1])}`;
  }
  return d;
}

/** Donut chart. segments: [{label, value, color}] */
export function donut(segments, { size = 168, thickness = 26, centerLabel = '', centerSub = '' } = {}) {
  const total = segments.reduce((s, x) => s + x.value, 0) || 1;
  const r = (size - thickness) / 2;
  const c = size / 2;
  const circ = 2 * Math.PI * r;
  const live = segments.filter((s) => s.value > 0);
  const gap = live.length > 1 ? 3.5 : 0;
  let offset = 0;
  const arcs = live.map((seg) => {
    const slot = (seg.value / total) * circ;
    const len = Math.max(slot - gap, 0.6);
    const el = `<circle cx="${c}" cy="${c}" r="${r}" fill="none" stroke="${seg.color}"
      stroke-width="${thickness}"
      stroke-dasharray="${len.toFixed(2)} ${(circ - len).toFixed(2)}"
      stroke-dashoffset="${(-offset).toFixed(2)}" transform="rotate(-90 ${c} ${c})"/>`;
    offset += slot;
    return el;
  }).join('');
  return `<svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}">
    <circle cx="${c}" cy="${c}" r="${r}" fill="none" stroke="var(--surface-3)" stroke-width="${thickness}"/>
    ${arcs}
    <text x="${c}" y="${c - 1}" text-anchor="middle" font-size="25" font-weight="700"
      fill="var(--ink)" font-family="Inter">${escapeHtml(centerLabel)}</text>
    <text x="${c}" y="${c + 17}" text-anchor="middle" font-size="10.5"
      fill="var(--muted)" font-family="Inter">${escapeHtml(centerSub)}</text>
  </svg>`;
}

/** Chart legend. segments: [{label, value, color}] */
export function legend(segments) {
  return `<div class="chart-legend">${segments.map((s) => `
    <div class="leg-item">
      <span class="leg-dot" style="background:${s.color}"></span>
      <span class="leg-label">${escapeHtml(s.label)}</span>
      <span class="leg-val">${escapeHtml(String(s.display ?? s.value))}</span>
    </div>`).join('')}</div>`;
}

/** Round a value up to a clean axis maximum (1 / 2 / 5 × 10ⁿ). */
function niceCeil(v) {
  if (!(v > 0)) return 1;
  const pow = Math.pow(10, Math.floor(Math.log10(v)));
  const n = v / pow;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * pow;
}

/** Compact money label for axis ticks (฿4k, ฿1.2M). */
function moneyShort(v) {
  v = Math.round(v);
  if (v >= 1e6) return '฿' + (v / 1e6).toFixed(v % 1e6 ? 1 : 0) + 'M';
  if (v >= 1e3) return '฿' + (v / 1e3).toFixed(v % 1e3 ? 1 : 0) + 'k';
  return '฿' + v;
}

// One delegated hover handler for EVERY line chart (charts are re-rendered on
// filter changes, so delegation keeps working without re-binding).
let _lineHoverReady = false;
function initLineHover() {
  if (_lineHoverReady || typeof document === 'undefined') return;
  _lineHoverReady = true;
  const hideAll = () => document.querySelectorAll('.lc-wrap').forEach((w) => {
    const c = w.querySelector('.lc-cursor'); if (c) c.style.opacity = '0';
    const t = w.querySelector('.lc-tip'); if (t) t.classList.remove('on');
  });
  document.addEventListener('pointermove', (e) => {
    const wrap = e.target.closest && e.target.closest('.lc-wrap');
    if (!wrap) { hideAll(); return; }
    const svg = wrap.querySelector('.line-chart');
    if (!svg) return;
    let series;
    try { series = JSON.parse(svg.dataset.series || '[]'); } catch (x) { return; }
    if (!series.length) return;
    const VW = +svg.dataset.w, VH = +svg.dataset.h;
    const r = svg.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * VW;     // pointer X → viewBox units
    let best = series[0], bd = Infinity;
    for (const s of series) { const d = Math.abs(s.x - px); if (d < bd) { bd = d; best = s; } }
    const cur = wrap.querySelector('.lc-cursor');
    cur.style.opacity = '1';
    cur.querySelectorAll('line').forEach((l) => { l.setAttribute('x1', best.x); l.setAttribute('x2', best.x); });
    const dot = cur.querySelector('circle'); dot.setAttribute('cx', best.x); dot.setAttribute('cy', best.y);
    const tip = wrap.querySelector('.lc-tip');
    tip.innerHTML = `<b>฿${escapeHtml(num(Math.round(best.v)))}</b>${best.lb ? `<span>${escapeHtml(best.lb)}</span>` : ''}`;
    tip.classList.add('on');
    tip.style.left = ((best.x / VW) * r.width) + 'px';
    tip.style.top = Math.max(2, (best.y / VH) * r.height - 10) + 'px';
  });
}

/** Smooth area line chart with a Y axis + hover tooltip. Pass color2 for a gradient stroke. */
export function lineChart(values, { color = 'var(--primary)', color2 = '', labels = [] } = {}) {
  if (!values || values.length < 2)
    return `<div class="muted text-sm" style="padding:30px;text-align:center">Not enough data yet</div>`;
  const W = 760, H = 220;
  const mL = 50, mR = 18, mT = 12, mB = 28;     // margins for the Y / X axis labels
  const plotW = W - mL - mR, plotH = H - mT - mB, baseY = mT + plotH;
  const top = niceCeil(Math.max(...values, 1));
  const xAt = (i) => mL + (i / (values.length - 1)) * plotW;
  const yAt = (v) => mT + plotH - (v / top) * plotH;
  const pts = values.map((v, i) => [xAt(i), yAt(v)]);
  const line = smoothPath(pts, [mT, baseY]);   // never dip below ฿0 or above the top
  const area = `${line} L${xAt(values.length - 1).toFixed(1)} ${baseY.toFixed(1)} L${mL} ${baseY.toFixed(1)} Z`;
  const uid = 'lc' + Math.random().toString(36).slice(2, 8);

  // Y axis — 5 gridlines + value labels
  const yAxis = [0, 0.25, 0.5, 0.75, 1].map((f) => {
    const yy = baseY - f * plotH;
    return `<line x1="${mL}" x2="${W - mR}" y1="${yy.toFixed(1)}" y2="${yy.toFixed(1)}"
        stroke="var(--border-2)" stroke-width="1" opacity="${f === 0 ? '0.9' : '0.45'}"
        ${f === 0 ? '' : 'stroke-dasharray="2 5"'}/>
      <text x="${mL - 8}" y="${(yy + 3.4).toFixed(1)}" text-anchor="end" font-size="10.5"
        fill="var(--muted)" font-family="Inter">${moneyShort(top * f)}</text>`;
  }).join('');

  // X axis — at most ~6 labels; the first/last are anchored start/end so they never clip
  const last = labels.length - 1;
  const stride = Math.max(1, Math.ceil(labels.length / 6));
  const xAxis = labels.map((lb, i) => {
    if (i !== 0 && i !== last && i % stride !== 0) return '';
    const anchor = i === 0 ? 'start' : i === last ? 'end' : 'middle';
    return `<text x="${xAt(i).toFixed(1)}" y="${H - 8}" text-anchor="${anchor}" font-size="10.5"
      fill="var(--muted)" font-family="Inter">${escapeHtml(lb)}</text>`;
  }).join('');

  const series = values.map((v, i) => ({ x: +xAt(i).toFixed(1), y: +yAt(v).toFixed(1), v, lb: labels[i] || '' }));
  initLineHover();

  return `<div class="lc-wrap">
    <svg class="line-chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet"
         style="width:100%;height:auto;display:block"
         data-w="${W}" data-h="${H}" data-series='${escapeHtml(JSON.stringify(series))}'>
      <defs>
        <linearGradient id="${uid}a" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stop-color="${color}" stop-opacity="0.26"/>
          <stop offset="1" stop-color="${color}" stop-opacity="0"/>
        </linearGradient>
        ${color2 ? `<linearGradient id="${uid}s" x1="0" x2="1" y1="0" y2="0">
          <stop offset="0" stop-color="${color}"/><stop offset="1" stop-color="${color2}"/>
        </linearGradient>` : ''}
      </defs>
      ${yAxis}
      <path d="${area}" fill="url(#${uid}a)"/>
      <path d="${line}" fill="none" stroke="${color2 ? `url(#${uid}s)` : color}" stroke-width="2.4"
        stroke-linejoin="round" stroke-linecap="round"/>
      ${xAxis}
      <g class="lc-cursor" style="opacity:0;pointer-events:none">
        <line y1="${mT}" y2="${baseY.toFixed(1)}" stroke="var(--ink)" stroke-width="1" stroke-dasharray="3 3" opacity="0.4"/>
        <circle r="4.5" fill="var(--surface)" stroke="${color}" stroke-width="2.6"/>
      </g>
    </svg>
    <div class="lc-tip"></div>
  </div>`;
}

/** Vertical funnel — trapezoid bands with a label gutter. stages: [{label, value}] */
export function funnel(stages, { colors } = {}) {
  const PAL = colors || ['#5B6BE0', '#4E8BC4', '#2BA8C4', '#2E7F86', '#1F5F6E'];
  const N = stages.length;
  if (!N) return `<div class="muted text-sm">No data</div>`;
  const W = 320, bandH = 36, gap = 9, padY = 8;
  const H = padY * 2 + N * bandH + (N - 1) * gap;
  const wbase = Math.max(...stages.map((s) => s.value), 1);
  const pbase = Math.max(stages[0].value, 1);
  const cx = 86, maxHalf = 74, minHalf = 9;
  const half = stages.map((s) =>
    Math.max(Math.min(s.value / wbase, 1) * maxHalf, minHalf));
  let body = '';
  for (let i = 0; i < N; i++) {
    const y = padY + i * (bandH + gap);
    const t = half[i];
    const b = i < N - 1 ? half[i + 1] : Math.max(t * 0.62, minHalf * 0.7);
    body += `<path d="M${(cx - t).toFixed(1)} ${y} L${(cx + t).toFixed(1)} ${y} `
      + `L${(cx + b).toFixed(1)} ${y + bandH} L${(cx - b).toFixed(1)} ${y + bandH} Z" `
      + `fill="${PAL[i % PAL.length]}"/>`;
    const pct = Math.round((stages[i].value / pbase) * 100);
    const my = y + bandH / 2;
    body += `<text x="194" y="${my - 2}" font-size="12.5" font-weight="600"
      fill="var(--ink)" font-family="Inter">${escapeHtml(stages[i].label)}</text>`;
    body += `<text x="194" y="${my + 13}" font-size="11" fill="var(--muted)"
      font-family="Inter">${num(stages[i].value)} · ${pct}%</text>`;
  }
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" class="funnel-svg" aria-hidden="true">${body}</svg>`;
}

/** Horizontal bar list. items: [{label, value, display?, color?}] */
export function barList(items, { color = 'var(--primary)' } = {}) {
  if (!items.length) return `<div class="muted text-sm">No data</div>`;
  const max = Math.max(...items.map((i) => i.value), 1);
  return `<div class="barlist">${items.map((it) => {
    const c = it.color || color;
    const pct = (it.value / max * 100).toFixed(0);
    return `<div class="barlist-row">
      <div class="barlist-top">
        <span class="truncate">${escapeHtml(it.label)}</span>
        <span class="strong">${escapeHtml(String(it.display ?? it.value))}</span>
      </div>
      <div class="bar-track">
        <div class="bar-fill" style="width:${pct}%;background:${c};background:linear-gradient(90deg, color-mix(in srgb, ${c} 46%, #fff), ${c})"></div>
      </div>
    </div>`;
  }).join('')}</div>`;
}

/** Compact smoothed sparkline from an array of numbers — for stat cards. */
export function sparkline(values, { color = 'var(--chart-2)', height = 42 } = {}) {
  if (!values || values.length < 2) return '';
  const width = 200, padY = 5;
  const max = Math.max(...values), min = Math.min(...values);
  const range = (max - min) || 1;
  const h = height - padY * 2;
  const pts = values.map((v, i) => [
    (i / (values.length - 1)) * width,
    padY + h - ((v - min) / range) * h,
  ]);
  const line = smoothPath(pts, [padY, padY + h]);   // keep the spark within its band
  const area = `${line} L${width} ${height} L0 ${height} Z`;
  const id = 'sp' + Math.random().toString(36).slice(2, 8);
  return `<svg viewBox="0 0 ${width} ${height}" width="100%" height="${height}"
    preserveAspectRatio="none" aria-hidden="true">
    <defs><linearGradient id="${id}" x1="0" x2="0" y1="0" y2="1">
      <stop offset="0" stop-color="${color}" stop-opacity="0.36"/>
      <stop offset="0.6" stop-color="${color}" stop-opacity="0.10"/>
      <stop offset="1" stop-color="${color}" stop-opacity="0"/></linearGradient></defs>
    <path d="${area}" fill="url(#${id})"/>
    <path d="${line}" fill="none" stroke="${color}" stroke-width="2.25"
      stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>
  </svg>`;
}
