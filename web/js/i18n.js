/* Blinks Bright — tiny build-less i18n (Thai / English).

   One flat catalog (`locales.js`) keyed by dot-string, each value `{en, th}`.
   `t(key, vars)` looks up the active language, falls back to English, then to the
   key itself, and interpolates `{var}` placeholders. The active language lives in
   `localStorage` ('lang'); switching it reloads the SPA so every view re-renders
   in the new language (the app is render-on-navigate, not reactive). */

import { CATALOG } from './locales.js';

export const SUPPORTED = ['th', 'en'];
const DEFAULT_LANG = 'th';   // Thai-default per product decision; EN remembered on toggle

function resolve() {
  let saved = '';
  try { saved = (localStorage.getItem('lang') || '').toLowerCase(); } catch (e) { /* private mode */ }
  return SUPPORTED.includes(saved) ? saved : DEFAULT_LANG;
}

export let LANG = resolve();
export function getLang() { return LANG; }
export function isThai() { return LANG === 'th'; }

/* Translate. `t('common.save')` → "บันทึก" / "Save". Missing keys degrade to the
   key string so a not-yet-merged key is visible rather than blank. */
export function t(key, vars) {
  const entry = CATALOG[key];
  let s = entry ? (entry[LANG] != null ? entry[LANG] : (entry.en != null ? entry.en : key)) : key;
  if (vars) s = String(s).replace(/\{(\w+)\}/g, (m, k) => (vars[k] != null ? vars[k] : m));
  return s;
}

/* Pick one of two literal strings by language — for the rare spot where a value is
   not worth a catalog key (e.g. an inline join word). Prefer `t()` everywhere else. */
export function pick(th, en) { return LANG === 'th' ? th : en; }

export function setLang(l) {
  if (!SUPPORTED.includes(l) || l === LANG) return;
  try { localStorage.setItem('lang', l); } catch (e) { /* ignore */ }
  location.reload();   // simplest robust re-render: boot the whole SPA in the new language
}

/* Reflect the active language on <html lang> for accessibility + correct font shaping. */
export function initLang() { try { document.documentElement.lang = LANG; } catch (e) { /* ignore */ } }

/* A compact TH|EN segmented switch reused by both shells, login and the picker. */
export function langToggle() {
  const th = LANG === 'th';
  return `<div class="lang-toggle" role="group" aria-label="Language">
    <button type="button" data-lang="th" class="${th ? 'active' : ''}" aria-pressed="${th}">ไทย</button>
    <button type="button" data-lang="en" class="${th ? '' : 'active'}" aria-pressed="${!th}">EN</button>
  </div>`;
}
export function bindLangToggle(root) {
  (root || document).querySelectorAll('.lang-toggle [data-lang]').forEach((b) => {
    b.onclick = () => setLang(b.dataset.lang);
  });
}
