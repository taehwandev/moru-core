// Page-side scripts the observer evaluates in the browser: they find controls, read the page and check what
// pointer input would reach. Plain strings, no state; observe.mjs drives them.

export const FIND_PRIMARY = `(() => {
  const pattern = /(take.?off|launch|start|begin|initiate|play|go\\b|fly|run|deploy)/i;
  const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 4 && r.height > 4 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const nodes = [...document.querySelectorAll('button, [role=button], a, input[type=button]')].filter(visible);
  const label = (el) => (el.innerText || el.value || el.getAttribute('aria-label') || '').trim();
  const hit = nodes.find((el) => pattern.test(label(el)));
  if (!hit) return null;
  const r = hit.getBoundingClientRect();
  return { text: label(hit).slice(0, 60), x: r.left + r.width / 2, y: r.top + r.height / 2 };
})()`;

export const FIND_SECONDARY = `(() => {
  const allow = /(orbit|chase|follow|tower|cockpit|drone|cam|view|zoom|pan|^\\s*[+\u2212-]\\s*$)/i;
  const deny = /(reset|land|return|abort|restart|stop|pause|again|reload|clear|exit|close|mute|sound|audio|speed|help|guide|\\?)/i;
  const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 4 && r.height > 4 && r.bottom > 0 && r.top < innerHeight && s.visibility !== 'hidden' && s.display !== 'none'; };
  const label = (el) => (el.innerText || el.value || el.getAttribute('aria-label') || el.title || '').replace(/\\s+/g, ' ').trim();
  const out = [];
  for (const el of document.querySelectorAll('button, [role=button], [role=tab], input[type=button]')) {
    const text = label(el);
    if (!visible(el) || !text || text.length > 24 || deny.test(text) || !allow.test(text)) continue;
    const r = el.getBoundingClientRect();
    out.push({ text, x: r.left + r.width / 2, y: r.top + r.height / 2 });
  }
  return out.slice(0, 8);
})()`;

export const SNAPSHOT = `(() => ({
  text: (document.body.innerText || '').replace(/\\s+/g, ' ').slice(0, 1200),
  overflowX: document.documentElement.scrollWidth - innerWidth,
  canvases: [...document.querySelectorAll('canvas')].map((c) => ({ w: c.width, h: c.height })),
}))()`;
// What sits under a point: the control or scene it should reach, or something else, and whether that
// something is invisible (fully transparent or hidden) yet still swallowing the pointer.
export const hitScript = (points, label) => `(() => {
  const want = ${JSON.stringify(label || '')}.replace(/\\s+/g, ' ').trim().toLowerCase();
  const canvas = [...document.querySelectorAll('canvas')].sort((a, b) => b.width * b.height - a.width * a.height)[0] || null;
  const describe = (e) => e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') +
    (typeof e.className === 'string' && e.className.trim() ? '.' + e.className.trim().split(/\\s+/)[0] : '');
  const invisible = (e) => {
    let opacity = 1;
    for (let n = e; n && n.nodeType === 1; n = n.parentElement) {
      const style = getComputedStyle(n);
      opacity *= parseFloat(style.opacity);
      if (style.visibility === 'hidden' || n.getAttribute('aria-hidden') === 'true') return true;
    }
    return opacity < 0.05;
  };
  return ${JSON.stringify(points)}.map(([x, y]) => {
    const top = document.elementFromPoint(x, y);
    const control = top && top.closest('button,a,[role=button],input,select,label,summary');
    const reaches = want
      ? !!control && ((control.textContent || '') + ' ' + (control.getAttribute('aria-label') || '')).replace(/\\s+/g, ' ')
          .toLowerCase().includes(want.slice(0, 12))
      : !!(top && canvas && (top === canvas || canvas.contains(top)));
    return { x: Math.round(x), y: Math.round(y), reaches, by: reaches || !top ? null : describe(top),
      text: reaches || !top ? '' : (top.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 40),
      invisible: reaches || !top ? false : invisible(top) };
  });
})()`;

export const CANVAS_AREA = `(() => {
  const c = [...document.querySelectorAll('canvas')].sort((a, b) => b.width * b.height - a.width * a.height)[0];
  if (!c) return null;
  const r = c.getBoundingClientRect();
  return { x0: Math.max(0, r.x), y0: Math.max(0, r.y), x1: Math.min(innerWidth, r.right), y1: Math.min(innerHeight, r.bottom) };
})()`;
