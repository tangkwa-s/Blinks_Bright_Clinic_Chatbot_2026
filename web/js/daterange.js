/* Blinks Bright — date-range picker
 *
 * Two read-only fields ("ตั้งแต่วันที่" / "ถึงวันที่") that open a two-month calendar
 * popover. Selection is a DRAFT until the customer presses ยืนยัน: picking a start
 * date momentarily leaves the range half-open, and re-querying on every click would
 * flash a wrong list at them. Clicking away or pressing Escape throws the draft away.
 *
 *   const picker = mountDateRange(el, { from, to, onApply({from, to}) {} });
 *   picker.set({ from, to });        // e.g. after a "this week" button elsewhere
 *
 * Dates are plain YYYY-MM-DD strings throughout — the same shape the API takes, and
 * immune to the timezone shifts a Date round-trip would introduce.
 */
import { displayYear, icon } from './ui.js';
import { t } from './i18n.js';

const p2 = (n) => String(n).padStart(2, '0');
export const ymd = (d) => `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())}`;
const parse = (s) => (s ? new Date(`${s}T00:00:00`) : null);

/* "06/09/2569 (อา.)" — day-first with the weekday, and the year in the era the reader
   uses: Buddhist in Thai, Common in English. */
export function prettyDate(s) {
  const d = parse(s);
  if (!d) return '';
  return `${p2(d.getDate())}/${p2(d.getMonth() + 1)}/${displayYear(d.getFullYear())}`;
}

export function weekdayShort(s) {
  const d = parse(s);
  return d ? t(`time.dow${d.getDay()}`) : '';
}

/* How one day cell paints, given the range being built.
 *
 * `hover` stands in for the end while only the start is picked, so the span about to
 * be chosen is visible BEFORE the second click lands. Pure and exported because there
 * is no DOM test environment here — tools/check_daterange.mjs is the only thing that
 * can catch an end date that silently stops highlighting.
 */
export function rangeCellClass(day, from, to, hover = '', active = '') {
  if (!day || !from) return '';
  // While the aim is on "ถึงวันที่" the day under the cursor IS the end being chosen,
  // so it outranks the end already stored — without this, opening on a complete range
  // (the default week) shows a frozen band and moving the mouse paints nothing.
  const end = (active === 'to' && hover > from) ? hover
    : (to || (hover > from ? hover : ''));
  const cls = [];
  if (day === from) cls.push('is-edge', 'is-start');
  if (end && day === end && day !== from) cls.push('is-edge', 'is-end');
  if (end && day > from && day < end) cls.push('is-between');
  // A lone start, or a single-day range, is a chip rather than the end of a band.
  if (day === from && (!end || end === from)) cls.push('is-solo');
  return cls.join(' ');
}

/* What a click on `day` does to the range being built, given which field is aimed at.
 *
 * Returns the next `{from, to, active}`. Pure and exported for the same reason as
 * rangeCellClass: this is the behaviour a screenshot cannot verify, and it is where
 * "the second click sets ถึงวันที่" actually lives.
 */
export function rangeAfterClick(day, { from, to, active }) {
  if (active === 'from') {
    // Keep an end that still makes sense; drop one the new start has overtaken.
    return { from: day, to: to && to >= day ? to : '', active: 'to' };
  }
  // Picking an "end" before the start reads as starting over, not as an error.
  if (!from || day < from) return { from: day, to: '', active: 'to' };
  // The range is complete, so the aim goes back to the start: the next click begins a
  // new selection. It also stops the hover preview, which would otherwise keep
  // dragging the band off the day just clicked and make the click look ignored.
  return { from, to: day, active: 'from' };
}

/* Exported for the headless check in tools/check_daterange.mjs — there is no DOM test
   environment in this repo, so the calendar maths is verified on its own. */
export function monthGrid(year, month) {
  const first = new Date(year, month, 1);
  const days = new Date(year, month + 1, 0).getDate();
  const cells = Array(first.getDay()).fill(null);      // Sunday-first, like the reference
  for (let i = 1; i <= days; i++) cells.push(ymd(new Date(year, month, i)));
  while (cells.length % 7) cells.push(null);
  return cells;
}

/* Which preset (if any) the current range IS — so picking one, or landing on the same
   span by hand, lights the same button. Compared on the plain date strings. */
export function activePreset(presets, { from, to }) {
  const hit = (presets || []).find((p) => {
    const r = p.range();
    return r.from === from && r.to === to;
  });
  return hit ? hit.id : '';
}

export function mountDateRange(host, { from = '', to = '', onApply, presets = [] } = {}) {
  let applied = { from, to };
  let draft = { from, to };
  let hover = '';
  let view = parse(from) || new Date();                // left-hand month
  view = new Date(view.getFullYear(), view.getMonth(), 1);
  let open = false;
  // Which field the next calendar click fills. Clicking a field aims it there, so the
  // end can be changed on its own without re-picking the start.
  let active = 'from';

  host.classList.add('drp');
  host.innerHTML = `
    <div class="drp-fields">
      <button type="button" class="drp-field" data-side="from">
        ${icon('calendar', 18)}
        <span class="drp-text">
          <span class="drp-label">${t('book.rangeFromLabel')}</span>
          <span class="drp-value" data-v="from"></span>
        </span>
      </button>
      <button type="button" class="drp-field" data-side="to">
        <span class="drp-text">
          <span class="drp-label">${t('book.rangeToLabel')}</span>
          <span class="drp-value" data-v="to"></span>
        </span>
      </button>
    </div>
    <div class="drp-pop" hidden>
      <div class="drp-body">
        ${presets.length ? `<div class="drp-presets">${presets.map((p) => `
          <button type="button" class="drp-preset" data-preset="${p.id}">${p.label}</button>`
          ).join('')}</div>` : ''}
        <div class="drp-months"></div>
      </div>
      <div class="drp-foot">
        <button type="button" class="btn btn-ghost drp-pill" data-act="clear">${t('book.rangeClear')}</button>
        <button type="button" class="btn btn-primary drp-pill" data-act="apply">${t('book.rangeApply')}</button>
      </div>
    </div>`;

  const pop = host.querySelector('.drp-pop');
  const months = host.querySelector('.drp-months');

  function fieldText() {
    // While the popover is open the fields track the DRAFT: clicking 4 and 21 in the
    // calendar has to show 04 and 21 up top immediately, or the click looks ignored.
    // They fall back to the applied range once it closes.
    const shown = open ? draft : applied;
    host.querySelectorAll('.drp-value').forEach((el) => {
      const v = shown[el.dataset.v];
      el.innerHTML = v
        ? `${prettyDate(v)} <small>(${weekdayShort(v)})</small>`
        : `<span class="drp-empty">DD/MM/YYYY</span>`;
    });
    host.querySelectorAll('.drp-field').forEach((f) => {
      f.classList.toggle('is-active', open && f.dataset.side === active);
    });
  }

  const cellClass = (day) => rangeCellClass(day, draft.from, draft.to, hover, active);

  function renderMonths() {
    const y = view.getFullYear();
    const m = view.getMonth();
    const panes = [[y, m], [m === 11 ? y + 1 : y, (m + 1) % 12]];
    const dows = Array.from({ length: 7 }, (_, i) => `<span>${t(`time.dow${i}`)}</span>`).join('');
    months.innerHTML = panes.map(([py, pm], i) => `
      <div class="drp-month">
        <div class="drp-mhead">
          ${i === 0 ? `<button type="button" class="drp-nav" data-nav="-1" aria-label="${t('book.rangePrevMonth')}">${icon('chevron-left', 16)}</button>` : '<span></span>'}
          <div class="drp-mtitle">${t(`time.month${pm}`)} ${displayYear(py)}</div>
          ${i === 1 ? `<button type="button" class="drp-nav" data-nav="1" aria-label="${t('book.rangeNextMonth')}">${icon('chevron-right', 16)}</button>` : '<span></span>'}
        </div>
        <div class="drp-dow">${dows}</div>
        <div class="drp-grid">
          ${monthGrid(py, pm).map((day) => (day
            ? `<button type="button" class="drp-day ${cellClass(day)}" data-day="${day}">${Number(day.slice(8))}</button>`
            : '<span class="drp-day is-blank"></span>')).join('')}
        </div>
      </div>`).join('');
    paintPresets();
  }

  /* Repaint the cells that are already on screen, touching only their class.
   *
   * NEVER rebuild the grid in response to a pointer move or a day click. Rewriting
   * months.innerHTML replaces the very node the pointer is over, which re-fires
   * mouseover on the fresh node (an endless re-render) and, worse, leaves mousedown
   * and mouseup on two different elements — so the browser never dispatches `click`
   * at all. That is exactly why the second click, the one that sets ถึงวันที่, did
   * nothing. Only a month change or (re)opening may call renderMonths.
   */
  /* Light the preset the range currently IS — whether it was picked from the list or
     landed on by hand. */
  function paintPresets() {
    const on = activePreset(presets, draft);
    host.querySelectorAll('.drp-preset').forEach((b) => {
      b.classList.toggle('is-on', b.dataset.preset === on);
    });
  }

  function paintDays() {
    months.querySelectorAll('[data-day]').forEach((el) => {
      el.className = `drp-day ${cellClass(el.dataset.day)}`.trimEnd();
    });
    paintPresets();
  }

  /* Show the month holding `anchor` on the left, unless it is already on screen —
     jumping the calendar under a cursor that is mid-selection is disorienting. */
  function focusMonth(anchor) {
    const d = parse(anchor);
    if (!d) return;
    const shown = [view.getMonth(), (view.getMonth() + 1) % 12];
    const sameYear = [view.getFullYear(), view.getMonth() === 11 ? view.getFullYear() + 1
      : view.getFullYear()];
    if (shown.some((m, i) => m === d.getMonth() && sameYear[i] === d.getFullYear())) return;
    view = new Date(d.getFullYear(), d.getMonth(), 1);
  }

  function setOpen(next, side = 'from') {
    open = next;
    pop.hidden = !open;
    host.classList.toggle('is-open', open);
    if (open) {
      draft = { ...applied };
      hover = '';
      active = side;
      view = parse(draft[side] || draft.from) || new Date();
      view = new Date(view.getFullYear(), view.getMonth(), 1);
      renderMonths();
    }
    fieldText();
  }

  host.querySelectorAll('.drp-field').forEach((f) => {
    const side = f.dataset.side;
    f.onclick = () => {
      if (!open) return setOpen(true, side);
      // Aiming at the end with no start yet is meaningless — take the start first.
      active = (side === 'to' && !draft.from) ? 'from' : side;
      focusMonth(draft[active]);
      hover = '';
      fieldText();
      renderMonths();
    };
  });

  months.onclick = (e) => {
    const nav = e.target.closest('[data-nav]');
    if (nav) {
      view = new Date(view.getFullYear(), view.getMonth() + Number(nav.dataset.nav), 1);
      renderMonths();
      return;
    }
    const cell = e.target.closest('[data-day]');
    if (!cell) return;
    const next = rangeAfterClick(cell.dataset.day, { ...draft, active });
    draft = { from: next.from, to: next.to };
    active = next.active;
    hover = '';
    fieldText();
    paintDays();
  };

  months.onmouseover = (e) => {
    const cell = e.target.closest('[data-day]');
    // Preview whenever the end is what the next click sets — with or without one
    // already stored. Aiming at the start previews nothing: there is no span yet.
    if (!cell || !draft.from || active !== 'to') return;
    if (hover === cell.dataset.day) return;      // same cell — nothing to repaint
    hover = cell.dataset.day;
    paintDays();
  };
  months.onmouseleave = () => {
    if (!hover) return;
    hover = '';
    paintDays();
  };

  const presetBar = pop.querySelector('.drp-presets');
  if (presetBar) {
    presetBar.onclick = (e) => {
      const btn = e.target.closest('[data-preset]');
      if (!btn) return;
      const p = presets.find((x) => x.id === btn.dataset.preset);
      if (!p) return;
      draft = p.range();
      hover = '';
      active = 'from';                 // the span is whole; the next click starts over
      focusMonth(draft.from);
      fieldText();
      renderMonths();                  // the month almost always changes, so rebuild
    };
  }

  pop.querySelector('[data-act="clear"]').onclick = () => {
    draft = { from: '', to: '' };
    hover = '';
    active = 'from';
    fieldText();
    paintDays();
  };
  pop.querySelector('[data-act="apply"]').onclick = () => {
    // A start with no end reads as "from this date onwards", which the API supports.
    applied = { ...draft };
    setOpen(false);
    if (onApply) onApply({ ...applied });
  };

  const onDocDown = (e) => { if (open && !host.contains(e.target)) setOpen(false); };
  const onKey = (e) => { if (open && e.key === 'Escape') setOpen(false); };
  document.addEventListener('mousedown', onDocDown);
  document.addEventListener('keydown', onKey);

  fieldText();
  return {
    get value() { return { ...applied }; },
    set(next) { applied = { from: next.from || '', to: next.to || '' }; fieldText(); },
    destroy() {
      document.removeEventListener('mousedown', onDocDown);
      document.removeEventListener('keydown', onKey);
    },
  };
}
