// Job Hunt form helpers. Paste this whole file into javascript_tool once per page, then call:
//   __formcheck()                      -> every field's label and current value (use before submitting, any site)
//   await __gh(texts, combos)          -> bulk-fill a Greenhouse form
//        texts:  [[labelRegex, value], ...]           fills empty text inputs/textareas whose label matches
//        combos: [[labelRegex, typeText, optionRegex?], ...]  opens a react-select, types, clicks the matching option
// Labels are matched case-insensitively against the nearest <label>/<legend> text.
window.__label = (e) => { let n = e; for (let i = 0; i < 8 && n; i++) { n = n.parentElement; const l = n?.querySelector('label,legend'); if (l) return l.innerText; } return e.getAttribute('aria-label') || e.placeholder || ''; };
window.__gh = async (texts, combos = []) => {
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const setv = (e, v) => { const proto = e.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype; Object.getOwnPropertyDescriptor(proto, 'value').set.call(e, v); e.dispatchEvent(new Event('input', { bubbles: true })); e.dispatchEvent(new Event('change', { bubbles: true })); };
  const out = [];
  const fields = [...document.querySelectorAll('form input:not([type=hidden]):not([type=file]):not([type=checkbox]):not([type=radio]), form textarea')];
  for (const [k, v] of texts) {
    const e = fields.find(f => f.getAttribute('role') !== 'combobox' && new RegExp(k, 'i').test(__label(f)) && !f.value);
    if (!e) { out.push('MISS text ' + k); continue; }
    setv(e, v); e.dispatchEvent(new Event('blur', { bubbles: true })); out.push('ok ' + k);
  }
  for (const [k, v, pick] of combos) {
    const e = fields.find(f => f.getAttribute('role') === 'combobox' && new RegExp(k, 'i').test(__label(f)));
    if (!e) { out.push('MISS combo ' + k); continue; }
    e.focus(); e.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    setv(e, v); await sleep(900);
    const opts = [...document.querySelectorAll('.select__option, [role=option]')];
    const re = new RegExp(pick || ('^' + v), 'i');
    const o = opts.find(o => re.test(o.innerText.trim()));
    if (!o) { out.push('NOOPT ' + k + ' :: ' + opts.slice(0, 6).map(o => o.innerText).join('/')); e.blur(); continue; }
    o.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); o.click(); await sleep(300);
    const sv = e.closest('.select__control')?.querySelector('.select__single-value, .select__multi-value')?.innerText;
    out.push((sv ? 'ok ' : 'UNSET ') + k + ' => ' + sv);
  }
  return out.join('\n');
};
window.__formcheck = () => {
  return [...document.querySelectorAll('form input:not([type=hidden]), form textarea, form select, input:not([type=hidden]), textarea, select')]
    .filter((e, i, a) => a.indexOf(e) === i)
    .map(e => {
      let v;
      if (e.getAttribute('role') === 'combobox') v = e.closest('.select__control')?.querySelector('.select__single-value, .select__multi-value')?.innerText || e.value || '(empty)';
      else if (e.type === 'file') v = e.files && e.files.length ? 'FILE ' + [...e.files].map(f => f.name).join(',') : null;
      else if (e.type === 'checkbox' || e.type === 'radio') v = e.checked ? 'X' : null;
      else if (e.tagName === 'SELECT') v = e.options[e.selectedIndex]?.text || '(empty)';
      else v = e.value || '(empty)';
      return v === null ? null : __label(e).slice(0, 70).replace(/\n/g, ' ') + ' => ' + String(v).slice(0, 80);
    }).filter(Boolean).join('\n');
};
'form helpers loaded';
