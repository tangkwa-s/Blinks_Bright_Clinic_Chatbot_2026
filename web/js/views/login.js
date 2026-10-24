/* Blinks Bright — login view */

import { api } from '../api.js';
import { icon, bindPasswordEyes, projectFooter } from '../ui.js';
import { t, langToggle, bindLangToggle } from '../i18n.js';

const DEMO = [
  [t('role.owner'), 'owner@blinksb.co'],
];

export default function renderLogin(app) {
  app.innerHTML = `
  <div class="auth-page">
    <div class="auth-lang" style="position:fixed;top:18px;right:20px;z-index:50">${langToggle()}</div>
    <div class="auth-visual" style="background-image:url('/assets/images/background.png')">
      <div class="auth-brand">
        <img class="wordmark" src="/assets/images/logo_full_trim.png?v=1" alt="Blinks Bright Beauty Clinic">
      </div>
      <div class="auth-hero">
        <div class="auth-eyebrow">${t('auth.eyebrow')}</div>
        <h2 class="quote">${t('auth.heroQuote')}</h2>
        <div class="auth-feats">
          <span>${t('auth.featChat')}</span>
          <span>${t('auth.featAi')}</span>
          <span>${t('auth.featBooking')}</span>
          <span>${t('auth.featPayments')}</span>
          <span>${t('auth.featRetention')}</span>
        </div>
      </div>
    </div>

    <div class="auth-form-wrap">
      <div class="auth-form-inner">
        <div class="auth-card rise">
          <div class="brand-row">
            <img class="wordmark" src="/assets/images/logo_full.png?v=1" alt="Blinks Bright Beauty Clinic">
          </div>
          <h1>${t('auth.welcome')}</h1>
          <p class="sub">${t('auth.subtitle')}</p>

          <form id="login-form">
            <div class="field">
              <label>${t('auth.email')}</label>
              <div class="input-group">${icon('mail')}
                <input class="input" type="email" id="email" placeholder="you@blinksb.co" autocomplete="username" required>
              </div>
            </div>
            <div class="field">
              <label>${t('auth.password')}</label>
              <div class="input-group">${icon('lock')}
                <input class="input" type="password" id="password" placeholder="••••••••" autocomplete="current-password" required>
              </div>
            </div>
            <div class="field-error hidden" id="login-error"></div>
            <button class="btn btn-primary btn-block btn-lg" type="submit" id="login-btn">${t('auth.signIn')}</button>
          </form>

          <div class="demo-accounts">
            <div class="strong" style="margin-bottom:5px">${t('auth.demoAccounts')} <code>demo1234</code></div>
            ${DEMO.map(([r, e]) => `
              <div class="da-row" data-email="${e}">
                <span>${r}</span><span class="muted">${e}</span>
              </div>`).join('')}
          </div>
        </div>
      </div>
      <div class="auth-foot">
        ${icon('lock', 13)}<span>${t('auth.secured')}</span>
      </div>
      ${projectFooter()}
    </div>
  </div>`;

  bindLangToggle(app);

  bindPasswordEyes(app);
  const form = app.querySelector('#login-form');
  const err = app.querySelector('#login-error');

  app.querySelectorAll('.da-row').forEach((row) => {
    row.onclick = () => {
      app.querySelector('#email').value = row.dataset.email;
      app.querySelector('#password').value = 'demo1234';
    };
  });

  form.onsubmit = async (e) => {
    e.preventDefault();
    const btn = app.querySelector('#login-btn');
    err.classList.add('hidden');
    btn.disabled = true;
    btn.textContent = t('auth.signingIn');
    try {
      await api.post('/auth/login', {
        email: app.querySelector('#email').value.trim(),
        password: app.querySelector('#password').value,
      });
      location.reload();
    } catch (ex) {
      err.textContent = ex.detail || t('auth.invalidCreds');
      err.classList.remove('hidden');
      btn.disabled = false;
      btn.textContent = t('auth.signIn');
    }
  };
}
