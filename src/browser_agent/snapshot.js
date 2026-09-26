// Walk the task page once and return everything the encoders need, as plain JSON.
//
// Every element gets a stable `data-ba-id` stamp the first time it is seen, so an element keeps
// its index across steps and the action layer can address it by `[data-ba-id="N"]`. The stamp is
// stripped from every HTML string returned here, so no encoding ever pays for it or sees it.
//
// Excluded from every encoding alike: the instruction (#query, which the agent is given
// separately) and MiniWoB's own harness chrome (reward display, sync cover, click canvas).
(excludedIds) => {
  const SKIP_TAGS = new Set(['SCRIPT', 'STYLE', 'LINK', 'META', 'NOSCRIPT', 'TEMPLATE']);
  const STAMP = / data-ba-id="\d+"/g;
  if (window.__baNext === undefined) window.__baNext = 1;
  const excluded = new Set(excludedIds);
  const nodes = [];

  const isExcluded = (el) => excluded.has(el.id);

  const visit = (el, parent) => {
    if (SKIP_TAGS.has(el.tagName) || isExcluded(el)) return null;
    if (!el.hasAttribute('data-ba-id')) el.setAttribute('data-ba-id', String(window.__baNext++));
    const id = Number(el.getAttribute('data-ba-id'));
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    const attrs = [];
    for (const a of el.attributes) if (a.name !== 'data-ba-id') attrs.push([a.name, a.value]);
    const node = {
      id,
      parent,
      tag: el.tagName.toLowerCase(),
      attrs,
      children: [],
      shown: el.checkVisibility({ opacityProperty: true, visibilityProperty: true }),
      rect: [rect.x, rect.y, rect.width, rect.height].map((v) => Math.round(v)),
      cursor: style.cursor,
      value: null,
      checked: null,
      outer: el.outerHTML.replace(STAMP, ''),
    };
    const tag = el.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA') {
      node.value = el.value;
      if (el.type === 'checkbox' || el.type === 'radio') node.checked = el.checked;
    } else if (tag === 'SELECT') {
      node.value = Array.from(el.selectedOptions).map((o) => o.textContent.trim()).join(', ');
    } else if (tag === 'OPTION') {
      node.checked = el.selected;
    }
    nodes.push(node);
    for (const child of el.childNodes) {
      if (child.nodeType === Node.TEXT_NODE) {
        const text = child.textContent.replace(/\s+/g, ' ');
        if (text.trim()) node.children.push(text);
      } else if (child.nodeType === Node.ELEMENT_NODE) {
        const cid = visit(child, id);
        if (cid !== null) node.children.push(cid);
      }
    }
    return id;
  };

  const roots = [];
  for (const child of document.body.children) {
    const cid = visit(child, -1);
    if (cid !== null) roots.push(cid);
  }

  const clone = document.body.cloneNode(true);
  for (const id of excludedIds) {
    const hit = clone.querySelector('#' + CSS.escape(id));
    if (hit) hit.remove();
  }
  return { nodes, roots, raw_html: clone.outerHTML.replace(STAMP, '') };
}
