/* Blinks Bright — AI Analytics view */

import { api } from '../api.js';
import { icon, escapeHtml, num, loadingBlock, emptyState } from '../ui.js';
import { barList } from '../charts.js';
import { t } from '../i18n.js';

const STAGE_LABEL = {
  new_lead: t('anl.stageNewLead'), interested: t('anl.stageInterested'),
  booked: t('anl.stageBooked'), paid: t('anl.stagePaid'),
};

function stat(label, value, ic, color, sub) {
  return `<div class="stat-card" style="--ic:${color || 'var(--primary)'}">
    <div class="stat-top"><span class="stat-label">${label}</span>
      <span class="stat-ic">${icon(ic, 16)}</span></div>
    <div class="stat-value">${value}</div>
    ${sub ? `<div class="muted text-xs" style="margin-top:2px">${sub}</div>` : ''}</div>`;
}

export default async function renderAnalytics(mount) {
  mount.innerHTML = `<div class="view">
    <div class="view-head">
      <div><h2>${t('anl.title')}</h2>
        <p>${t('anl.subtitle')}</p></div>
    </div>
    <div id="an-body">${loadingBlock()}</div>
  </div>`;

  const body = mount.querySelector('#an-body');
  let d;
  try { d = await api.get('/analytics'); }
  catch (e) { body.innerHTML = emptyState('alert', t('anl.loadFailed')); return; }
  const a = d.ai_stats;
  const u = d.ai_usage || {};

  body.innerHTML = `
    <div class="grid grid-4" style="margin-bottom:16px">
      ${stat(t('anl.statReplies'), num(a.ai_messages), 'ai', 'var(--chart-1)')}
      ${stat(t('anl.statGrounded'), a.grounded_pct + '%', 'check-circle', 'var(--chart-3)')}
      ${stat(t('anl.statEscalations'), num(a.escalations), 'alert', 'var(--chart-4)')}
      ${stat(t('anl.statTakeovers'), num(a.takeovers), 'user', 'var(--chart-5)')}
      ${stat(t('anl.statCost'), '฿' + (u.cost_thb || 0).toFixed(2), 'dollar', 'var(--chart-7)',
        t('anl.costSub', { tokens: num(u.total_tokens || 0), calls: num(u.calls || 0) }))}
    </div>

    <div class="grid grid-2" style="margin-bottom:16px">
      <div class="card">
        <div class="card-head"><h4>${t('anl.whatCustomersAsk')}</h4></div>
        <div class="card-body">${d.intents.length
          ? barList(d.intents, { color: 'var(--chart-1)' })
          : emptyState('chat', t('anl.noIntentData'))}</div>
      </div>
      <div class="card">
        <div class="card-head"><h4>${t('anl.topConverting')}</h4></div>
        <div class="card-body">${d.top_converting.length
          ? barList(d.top_converting, { color: 'var(--chart-3)' })
          : emptyState('spark', t('common.noData'))}</div>
      </div>
    </div>

    <div class="grid grid-2">
      <div class="card">
        <div class="card-head"><h4>${t('anl.funnelDropoff')}</h4>
          <span class="sub">${t('anl.funnelDropoffSub')}</span></div>
        <div class="card-body">
          ${d.drop_off.map((s) => `
            <div class="barlist-row">
              <div class="barlist-top">
                <span>${STAGE_LABEL[s.from]} → ${STAGE_LABEL[s.to]}</span>
                <span class="strong">${s.kept_pct}% ${t('anl.kept')}</span>
              </div>
              <div class="bar-track"><div class="bar-fill"
                style="width:${s.kept_pct}%;background:${s.kept_pct < 40 ? 'var(--danger)' : 'var(--chart-3)'}"></div></div>
            </div>`).join('')}
        </div>
      </div>
      <div class="card">
        <div class="card-head"><h4>${t('anl.unknownQuestions')}</h4>
          <span class="sub">${t('anl.unknownQuestionsSub')}</span></div>
        <div class="card-body">
          ${d.unknown_intents.length ? d.unknown_intents.map((u) => `
            <div class="insight-row">
              <span class="ins-rank" style="background:var(--warning-bg);color:var(--warning)">?</span>
              <div style="flex:1"><div class="text-sm">${escapeHtml(u.question)}</div>
                <div class="muted text-xs">${t('anl.predictedLine', { intent: escapeHtml(u.intent), confidence: u.confidence })}</div></div>
            </div>`).join('') : emptyState('check-circle', t('anl.noUnclassified'), t('anl.noUnclassifiedSub'))}
        </div>
      </div>
    </div>

    <div class="card" style="margin-top:16px">
      <div class="card-head"><h4>${t('anl.commonObjections')}</h4>
        <span class="sub">${t('anl.commonObjectionsSub')}</span></div>
      <div class="card-body">
        ${(d.objections || []).length ? d.objections.map((o) => `
          <div class="insight-row">
            <span class="ins-rank" style="background:var(--st-followup-bg);color:var(--st-followup)">!</span>
            <div style="flex:1" class="text-sm">${escapeHtml(o)}</div>
          </div>`).join('') : emptyState('check-circle', t('anl.noObjections'),
            t('anl.noObjectionsSub'))}
      </div>
    </div>`;
}
