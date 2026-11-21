/* Drill-down panel: every number on the page opens the derivation of that number, one level at a time (docs/DRILLDOWN_SPEC.md).
   The tree is built on the server (GET /api/derivation); this file only displays one node at a time.
   L0 value, label, unit and the cutoff · L1 the formula in math notation (KaTeX, vendored in web/vendor/katex) with a legend per symbol ·
   L2 the same formula with the actual numbers and each arithmetic step · L3 each operand opens its own L1/L2, window operands list every input row ·
   L4 the stored point-in-time row, with a link to the archived raw payload when there is one. A pending operand shows "withheld", never a number.
   Keys: Esc steps up one level, Esc at L0 closes. Every string from the API is inserted with textContent. */
(function () {
  "use strict";
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  let panel = null, body = null, crumbs = null, backBtn = null, stack = [], ctx = () => ({}), opener = null, busy = 0;

  function tex(target, src, display) {
    if (!src) return target;
    if (window.katex) { try { window.katex.render(src, target, { displayMode: !!display, throwOnError: false, trust: false, strict: "ignore" }); return target; } catch (e) { /* fall through to plain text */ } }
    target.textContent = src;
    return target;
  }
  function ensure() {
    if (panel) return;
    panel = mk("aside", "drill"); panel.id = "drill"; panel.hidden = true; panel.setAttribute("role", "dialog"); panel.setAttribute("aria-label", "How this number is calculated"); panel.tabIndex = -1;
    const hd = mk("div", "drill-hd");
    backBtn = mk("button", "drill-back", "‹ Back"); backBtn.type = "button"; backBtn.addEventListener("click", up);
    crumbs = mk("nav", "drill-crumbs"); crumbs.setAttribute("aria-label", "Levels");
    const x = mk("button", "drill-close", "✕"); x.type = "button"; x.title = "Close (Esc)"; x.addEventListener("click", close);
    hd.append(backBtn, crumbs, x);
    body = mk("div", "drill-body");
    panel.append(hd, body);
    document.body.append(panel);
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !panel.hidden) { e.preventDefault(); e.stopPropagation(); up(); }
    }, true);
  }

  async function fetchNode(entry, opts) {
    const c = ctx(), q = new URLSearchParams({ metric: entry.metric, timeframe: c.timeframe || "seasonal" });
    const product = entry.product || c.product; if (product) q.set("product", product);
    if (c.as_of) q.set("as_of", c.as_of);
    if (entry.node) q.set("node", entry.node);
    q.set("rows_offset", String(opts && opts.offset != null ? opts.offset : -1));          // long windows open on their newest page
    const r = await fetch("/api/derivation?" + q.toString());
    if (!r.ok) throw new Error(`derivation unavailable (${r.status})`);
    return r.json();
  }

  function open(metric, o) {
    ensure(); o = o || {};
    stack = [{ metric, product: o.product, node: null }];
    opener = document.activeElement;
    panel.hidden = false; document.body.classList.add("drill-open");
    show(0);
    panel.focus();
  }
  function close() {
    if (!panel) return;
    panel.hidden = true; stack = []; document.body.classList.remove("drill-open");
    if (opener && opener.focus) { try { opener.focus(); } catch (e) { /* element may be gone after a re-render */ } }
  }
  function up() { if (stack.length > 1) { stack.pop(); show(stack.length - 1); } else close(); }
  async function push(nodeId) {
    const top = stack[stack.length - 1];
    stack.push({ metric: top.metric, product: top.product, node: nodeId });
    show(stack.length - 1);
  }
  async function show(i, opts) {
    const token = ++busy, entry = stack[i];
    body.setAttribute("aria-busy", "true");
    if (!entry.view || (opts && opts.offset != null)) {
      body.replaceChildren(mk("div", "drill-note", "loading…"));
      try { entry.view = (await fetchNode(entry, opts)).node; }
      catch (e) { if (token === busy) { body.replaceChildren(mk("div", "drill-note warn", String(e.message || e))); body.removeAttribute("aria-busy"); } return; }
    }
    if (token !== busy) return;
    renderCrumbs(i);
    render(entry.view, i);
    body.removeAttribute("aria-busy");
    body.scrollTop = 0;
  }
  function renderCrumbs(i) {
    crumbs.replaceChildren();
    backBtn.disabled = false; backBtn.textContent = stack.length > 1 ? "‹ Back" : "✕ Close";
    stack.forEach((e, k) => {
      if (k) crumbs.append(mk("span", "sep", "›"));
      const lab = k === 0 ? "L0" : (e.view ? e.view.label : "…");
      const b = mk("button", "crumb" + (k === i ? " cur" : ""), k === 0 && e.view ? `L0 · ${e.view.label}` : lab.length > 28 ? lab.slice(0, 27) + "…" : lab);
      b.type = "button"; b.title = e.view ? e.view.label : "";
      if (k !== i) b.addEventListener("click", () => { stack = stack.slice(0, k + 1); show(k); });
      crumbs.append(b);
    });
  }

  const row = (k, v, cls) => { const r = mk("div", "kvr"); r.append(mk("span", "k", k), mk("span", "v" + (cls ? " " + cls : ""), v == null || v === "" ? "—" : String(v))); return r; };
  const section = (h) => { const s = mk("section", "drill-sec"); s.append(mk("h4", null, h)); return s; };

  function render(n, depth) {
    body.replaceChildren();
    // ---- L0
    const l0 = mk("div", "drill-l0");
    l0.append(mk("div", "lvl", depth === 0 ? "L0 · displayed value" : `Level ${depth} · ${n.op === "leaf" ? "stored row" : "operand"}`), mk("div", "lab", n.label));
    const val = mk("div", "val" + (n.status === "withheld" ? " withheld" : ""));
    val.append(mk("span", "n", n.display), n.status !== "withheld" && n.unit ? mk("span", "u", " " + n.unit) : "");
    l0.append(val, mk("div", "asof", `as of cutoff ${n.cutoff}`));
    if (n.status === "withheld") l0.append(mk("div", "drill-note warn", n.text && n.text !== "withheld" ? n.text : "withheld: an operand has no data, so no number is shown"));
    body.append(l0);
    const ask = mk("button", "drill-ask", "Ask Ollama about this"); ask.type = "button";
    ask.addEventListener("click", () => { window.dispatchEvent(new CustomEvent("ngl-ask", { detail: { metric: (stack[0] && stack[0].metric || "").split(":")[0], agent: n.leaf ? n.leaf.agent_id : null, title: n.label } })); window.scrollTo({ top: 0, behavior: "smooth" }); });
    l0.append(ask);
    if (n.note) body.append(mk("div", "drill-note", n.note));
    // ---- L4: a stored row
    if (n.leaf) {
      const s = section("L4 · the stored point-in-time row");
      const L = n.leaf;
      [["agent_id", L.agent_id], ["series", L.series], ["value", L.value == null ? "withheld (no collector)" : `${L.value} ${L.unit || ""}`], ["t_target", L.t_target], ["t_published", L.t_published || "not supplied by the source"], ["t_retrieved", L.t_retrieved],
        ["t_available", L.t_available], ["provenance", L.provenance], ["quality_status", L.quality_status], ["source_id", L.source_id], ["intended_source", L.intended_source], ["raw_payload_hash", L.raw_payload_hash]]
        .forEach(([k, v]) => { if (v != null || L.value == null) s.append(row(k, v, k === "raw_payload_hash" ? "hash" : "")); });
      if (L.raw_url) { const a = mk("a", "drill-raw", "view the archived raw payload (read-only) ↗"); a.href = L.raw_url; a.target = "_blank"; a.rel = "noopener noreferrer"; s.append(a); }
      else if (L.raw_payload_hash) s.append(mk("div", "drill-note", "this payload's bytes are not archived on this host"));
      if (L.source_url) s.append(row("source_url", L.source_url));
      body.append(s);
      return;
    }
    // ---- L1
    if (n.formula_tex) {
      const s = section("L1 · definition");
      s.append(tex(mk("div", "tex"), n.formula_tex, true));
      if (n.symbols && n.symbols.length) { const lg = mk("div", "drill-legend"); n.symbols.forEach((y) => { const r = mk("div", "kvr"); const k = mk("span", "k"); tex(k, y.sym, false); r.append(k, mk("span", "v", `${y.meaning}${y.unit ? " · " + y.unit : ""}`)); lg.append(r); }); s.append(lg); }
      body.append(s);
    }
    // ---- L2
    if (n.tex_sub || (n.steps && n.steps.length)) {
      const s = section("L2 · with the actual numbers");
      if (n.tex_sub) s.append(tex(mk("div", "tex"), "= " + n.tex_sub, true));
      (n.steps || []).forEach((st) => s.append(tex(mk("div", "tex step"), st, true)));
      body.append(s);
    }
    // ---- L3: operands
    if (n.operands && n.operands.length) {
      const s = section("L3 · operands (click one to open its own definition)");
      n.operands.forEach((o) => {
        const b = mk("button", "operand" + (o.status === "withheld" ? " withheld" : ""));
        b.type = "button";
        const nm = mk("span", "nm"); tex(nm, o.name, false);
        b.append(nm, mk("span", "lb", o.label), mk("span", "vv", o.status === "withheld" ? "withheld" : `${o.display}${o.unit ? " " + o.unit : ""}`), mk("span", "op", o.op === "leaf" ? "stored row" : o.op));
        if (o.status === "withheld" && o.text) b.title = o.text;
        b.addEventListener("click", () => push(o.id));
        s.append(b);
      });
      body.append(s);
    }
    // ---- L3: window rows
    if (n.rows) {
      const s = section(`L3 · every input row of the window (${n.rows_total})`);
      if (n.stats) s.append(mk("div", "stats", `n ${n.stats.n} · sum ${fmt(n.stats.sum)} · mean ${fmt(n.stats.mean)} · σ ${fmt(n.stats.std)} · min ${fmt(n.stats.min)} · max ${fmt(n.stats.max)}`));
      const tbl = mk("table", "rows"), tb = mk("tbody");
      (n.rows || []).forEach((r) => {
        const tr = mk("tr"); tr.append(mk("td", null, r.d), mk("td", "num", r.v == null ? "—" : String(r.v)), mk("td", "dim", r.title || (r.i != null ? "swing point" : "")));
        const nid = r.doc ? `doc:${r.doc}` : (n.params && n.params.agent && /^\d{4}-\d\d-\d\d$/.test(r.d) ? `leaf:${n.params.agent}:${r.d}` : (n.params && n.params.agents ? `leaf:${r.d}:latest` : null));
        if (nid) { tr.className = "clk"; tr.tabIndex = 0; tr.addEventListener("click", () => push(nid)); tr.addEventListener("keydown", (e) => { if (e.key === "Enter") push(nid); }); }
        tb.append(tr);
      });
      tbl.append(tb); s.append(tbl);
      if (n.rows_total > (n.rows || []).length) {
        const nav = mk("div", "pager"), off = n.rows_offset || 0, lim = (n.rows || []).length;
        const older = mk("button", null, "‹ older"), newer = mk("button", null, "newer ›"), newest = mk("button", null, "newest");
        [older, newer, newest].forEach((b) => { b.type = "button"; });
        older.disabled = off <= 0; newer.disabled = off + lim >= n.rows_total;
        const go = (o) => { const e = stack[stack.length - 1]; show(stack.length - 1, { offset: o }); };
        older.addEventListener("click", () => go(Math.max(0, off - lim)));
        newer.addEventListener("click", () => go(Math.min(n.rows_total - lim, off + lim)));
        newest.addEventListener("click", () => go(-1));
        nav.append(older, mk("span", null, `rows ${off + 1}–${off + lim} of ${n.rows_total}`), newer, newest);
        s.append(nav);
      }
      body.append(s);
    }
  }
  const fmt = (v) => (v == null ? "—" : Math.abs(v) >= 1000 ? v.toLocaleString("en-US", { maximumFractionDigits: 2 }) : String(Math.round(v * 10000) / 10000));

  /* bind(el, metric, {product}): the element becomes a keyboard-focusable button that opens the drill-down; its click never pins a tooltip. */
  function bind(node, metric, o) {
    if (!node || !metric) return node;
    node.classList.add("dd");
    node.dataset.dd = metric;
    if (node.tagName !== "BUTTON" && node.tagName !== "A") { node.setAttribute("role", "button"); if (!node.hasAttribute("tabindex")) node.setAttribute("tabindex", "0"); }
    node.setAttribute("aria-label", (node.getAttribute("aria-label") || node.textContent || "").trim().slice(0, 60) + " · show how this is calculated");
    const go = (e) => { if (e.type === "keydown" && !(e.key === "Enter" || e.key === " ")) return; e.stopPropagation(); e.preventDefault(); open(metric, o); };
    node.addEventListener("click", go);
    node.addEventListener("keydown", go);
    if (window.NGLTip && window.NGLTip.noPin) window.NGLTip.noPin(node);
    return node;
  }
  window.NGLDrill = { open, close, bind, setContext: (f) => { ctx = f; }, _stack: () => stack };
})();
