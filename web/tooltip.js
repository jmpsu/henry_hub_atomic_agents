/* Rich tooltips for the NGL dashboard. One floating panel, filled from a structured spec; every string is inserted with textContent
   (never as HTML). Works with mouse (hover), keyboard (focus), touch (tap) and can be pinned (click) so values can be selected and copied.

   spec = { id, title, badge: {text, cls}, value, what, formula, params: {k: v}, sections: [{h, rows: [[label, value, cls]]}], notes: [text], read }
   NGLTip.bind(element, spec | () => spec)       element becomes focusable and shows the spec on hover/focus/tap
   NGLTip.hover(svgNode, {pick(i) -> spec|null, index(evt) -> i, onMove(i)})   crosshair-style tooltip over a chart
   NGLTip.reset() / NGLTip.restore()              around a re-render, keeps a pinned tooltip open on the refreshed element
   ?tip=<id> in the URL opens that tooltip pinned (shareable, and what a screenshot or print needs). */
(function () {
  "use strict";
  const reg = new Map();            // id -> { el, spec }
  const bound = new WeakMap();      // element -> spec | fn
  const ids = new WeakMap();        // element -> registry id
  const nopin = new WeakSet();      // elements whose click already has another job (hover/focus still show the tooltip)
  let box = null, cur = null, pinned = null, pinnedId = null, showT = null, hideT = null, count = 0, hoverEl = null;

  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  function ensure() {
    if (box) return box;
    box = mk("div", "ngl-tip"); box.id = "ngl-tip"; box.setAttribute("role", "tooltip"); box.hidden = true;
    document.body.append(box);
    return box;
  }
  const val = (v) => (v == null || v === "" ? "—" : String(v));

  function fill(spec) {
    const b = ensure(); while (b.firstChild) b.removeChild(b.firstChild);
    const hd = mk("div", "tip-hd"); hd.append(mk("span", "tip-title", spec.title || ""));
    if (spec.badge && spec.badge.text) hd.append(mk("span", "tip-badge " + (spec.badge.cls || ""), spec.badge.text));
    b.append(hd);
    if (spec.value != null) b.append(mk("div", "tip-val", spec.value));
    if (spec.what) b.append(mk("p", "tip-what", spec.what));
    const section = (h, build) => { const s = mk("div", "tip-sec"); s.append(mk("h4", null, h)); build(s); b.append(s); };
    if (spec.formula || (spec.params && Object.keys(spec.params).length)) section("How it is calculated", (s) => {
      if (spec.formula) s.append(mk("code", "tip-formula", spec.formula));
      const ks = Object.entries(spec.params || {});
      if (ks.length) { const dl = mk("dl"); for (const [k, v] of ks) { dl.append(mk("dt", null, k.replace(/_/g, " ")), mk("dd", null, val(v))); } s.append(dl); }
    });
    for (const sec of spec.sections || []) {
      const rows = (sec.rows || []).filter((r) => r && r[1] != null && r[1] !== "");       // callers pass "—" themselves when an empty value is meaningful
      if (!rows.length) continue;
      section(sec.h, (s) => { const dl = mk("dl"); for (const [k, v, cls] of rows) { dl.append(mk("dt", null, k), mk("dd", cls || null, val(v))); } s.append(dl); });
    }
    if (spec.read) b.append(mk("p", "tip-read", spec.read));
    for (const n of spec.notes || []) if (n) b.append(mk("p", "tip-note", n));
    if (spec.ask && pinned) {                                         // click-to-ask: hands the metric id and agent to the chat; the server rebuilds the facts, nothing is trusted from here
      const bt = mk("button", "tip-ask", "Ask Ollama about this"); bt.type = "button";
      bt.addEventListener("click", (e) => { e.stopPropagation(); window.dispatchEvent(new CustomEvent("ngl-ask", { detail: spec.ask })); unpin(); });
      b.append(bt);
    }
    b.append(mk("div", "tip-ft", pinned ? "pinned · click elsewhere or press Esc to close" : "click to pin · Esc closes"));
  }
  function place(x, y, anchor) {
    const b = box, pad = 12, vw = document.documentElement.clientWidth, vh = window.innerHeight;
    b.style.left = "0px"; b.style.top = "0px"; b.hidden = false;
    const r = b.getBoundingClientRect();
    let left, top;
    if (anchor) { const a = anchor.getBoundingClientRect(); left = a.left; top = a.bottom + 8; if (top + r.height > vh - pad) top = Math.max(pad, a.top - r.height - 8); }
    else { left = x + 16; top = y + 16; if (left + r.width > vw - pad) left = x - r.width - 16; if (top + r.height > vh - pad) top = y - r.height - 16; }
    left = Math.max(pad, Math.min(left, vw - r.width - pad)); top = Math.max(pad, Math.min(top, vh - r.height - pad));
    b.style.left = left + "px"; b.style.top = top + "px";
  }
  function show(spec, x, y, anchor, el) {
    clearTimeout(hideT); fill(spec); place(x, y, anchor); cur = el || null;
    if (el && el.setAttribute) el.setAttribute("aria-describedby", "ngl-tip");
  }
  function hide(force) {
    if (pinned && !force) return;
    clearTimeout(showT); if (cur && cur.removeAttribute) cur.removeAttribute("aria-describedby"); cur = null;
    if (box) box.hidden = true; box && box.classList.remove("pinned");
  }
  function unpin() { if (pinned && pinned.classList) pinned.classList.remove("tip-pinned"); pinned = null; pinnedId = null; hide(true); }
  function specOf(el) { const s = bound.get(el); return typeof s === "function" ? s() : s; }

  function bind(el, spec, id, opts) {
    if (!el) return el;
    bound.set(el, spec);
    if (opts && opts.pin === false) nopin.add(el);
    el.classList.add("has-tip");
    if (!el.hasAttribute("tabindex") && !/^(A|BUTTON|INPUT)$/.test(el.tagName)) el.setAttribute("tabindex", "0");
    const rid = id || (typeof spec === "function" ? null : spec.id);
    if (rid) { reg.set(rid, { el }); ids.set(el, rid); } count++;
    return el;
  }
  function target(e) { let n = e.target; while (n && n !== document) { if (n.nodeType === 1 && bound.has(n)) return n; n = n.parentNode; } return null; }

  document.addEventListener("mouseover", (e) => {
    if (pinned) return;
    const el = target(e); if (!el) return;
    hoverEl = el;
    clearTimeout(showT); showT = setTimeout(() => { const s = specOf(el); if (s) show(s, e.clientX, e.clientY, null, el); }, 90);
  });
  document.addEventListener("mousemove", (e) => { if (!pinned && box && !box.hidden && cur && !cur.dataset.tipChart) { const el = target(e); if (el === cur) place(e.clientX, e.clientY, null); } });
  document.addEventListener("mouseout", (e) => {
    if (pinned) return;
    const el = target(e);
    if (el && !el.contains(e.relatedTarget)) {
      if (hoverEl === el) hoverEl = null;
      clearTimeout(showT);
      hideT = setTimeout(() => { if (!hoverEl) hide(); }, 80);                       // the pointer may already be on another tooltip target
    }
  });
  document.addEventListener("focusin", (e) => { const el = target(e); if (el && !pinned) { const s = specOf(el); if (s) show(s, 0, 0, el, el); } });
  document.addEventListener("focusout", (e) => { if (target(e) && !pinned) hide(); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { unpin(); return; }
    if ((e.key === "Enter" || e.key === " ") && target(e) && !nopin.has(target(e)) && !/^(A|BUTTON|INPUT)$/.test(e.target.tagName)) { e.preventDefault(); pin(target(e), null); }
  });
  function pin(el, evt) {
    const s = specOf(el); if (!s) return;
    if (pinned === el) { unpin(); return; }
    if (pinned && pinned.classList) pinned.classList.remove("tip-pinned");
    pinned = el; pinnedId = ids.get(el) || null; el.classList && el.classList.add("tip-pinned");
    fill(s); box.classList.add("pinned"); place(evt ? evt.clientX : 0, evt ? evt.clientY : 0, evt ? null : el); cur = el;
  }
  document.addEventListener("click", (e) => {
    if (box && box.contains(e.target)) return;
    const el = target(e);
    if (el && !nopin.has(el) && !/^(A|BUTTON|INPUT|LABEL)$/.test(el.tagName)) { pin(el, e); return; }
    if (pinned) unpin();
  });

  /* Chart crosshair: pointer position -> data index -> spec. `index(evt)` maps a mouse event to a data index (or null). */
  function hover(svg, o) {
    const node = svg.node ? svg.node() : svg;
    node.dataset.tipChart = "1";
    const guide = o.guide;                              // optional d3 selection of a vertical line to move
    node.addEventListener("mousemove", (e) => {
      const i = o.index(e); if (i == null) return;
      const s = o.pick(i); if (!s) return;
      if (guide) o.onMove && o.onMove(i);
      if (!pinned) show(s, e.clientX, e.clientY, null, null);
    });
    node.addEventListener("mouseleave", () => { if (o.onLeave) o.onLeave(); hide(); });
    node.addEventListener("click", (e) => {
      const i = o.index(e); if (i == null) return; const s = o.pick(i); if (!s) return;
      if (pinned === node) { unpin(); return; }
      pinned = node; pinnedId = null; fill(s); box.classList.add("pinned"); place(e.clientX, e.clientY, null); e.stopPropagation();
    });
  }

  function reset() { const keep = pinnedId; reg.clear(); count = 0; if (!keep) { if (pinned) unpin(); } return keep; }
  function restore(id) {
    const want = id || new URLSearchParams(location.search).get("tip");
    if (!want) return false;
    const r = reg.get(want); if (!r) { if (pinned) unpin(); return false; }
    if (r.el.scrollIntoView && !pinnedId) r.el.scrollIntoView({ block: "center" });
    pinned = null; pin(r.el, null); return true;
  }
  window.NGLTip = { noPin: (el) => nopin.add(el), bind, hover, reset, restore, specOf, hide: () => hide(true), ids: () => [...reg.keys()], size: () => reg.size, count: () => count, _fill: fill };
})();
