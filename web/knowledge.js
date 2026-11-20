/* Full-page graphical knowledge library. Reads /api/knowledge-graph, /api/knowledge-node/{id}, /api/knowledge-search and
   /api/agents/activity from the read-only service. Every request carries the point-in-time cutoff; nothing here computes
   market numbers. API text is inserted with textContent only. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const qs = new URLSearchParams(location.search);
  const SYMBOLS = { agent_finding: d3.symbolDiamond, pipeline_notice: d3.symbolSquare, backtest: d3.symbolTriangle, alpha_synthesis: d3.symbolStar,
    noaa_discussion: d3.symbolWye, weather: d3.symbolCircle, price: d3.symbolCircle, storage: d3.symbolCross, production: d3.symbolCross, carbon: d3.symbolCircle };
  const FILLED = new Set(["price", "storage", "weather", "production", "carbon"]);         // measured-derived summaries are filled
  let cutoff = qs.get("as_of") || null, graph = null, sel = qs.get("node") || null, hits = new Set();
  const hiddenDomains = new Set(), hiddenEdges = new Set(["semantic_neighbor"]);
  let svg, gRoot, zoom, nodesSel, linksSel, sim;

  function el(tag, attrs, kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === "text") n.textContent = v; else if (k === "class") n.className = v; else n.setAttribute(k, v);
    }
    for (const c of [].concat(kids || [])) if (c != null) n.append(c);
    return n;
  }
  const clear = (n) => { while (n.firstChild) n.removeChild(n.firstChild); return n; };
  const tag = (text, cls) => el("span", { class: "tag " + (cls || ""), text });
  const iso = (d) => d.toISOString().slice(0, 19) + "Z";
  const shortAgent = (a) => (a || "").replace(/^Agent_/, "").replace(/_/g, " ");

  async function getJSON(url, opts) {
    const r = await fetch(url, opts);
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.detail || `HTTP ${r.status}`);
    return j;
  }
  const withCutoff = (url) => (cutoff ? url + (url.includes("?") ? "&" : "?") + "as_of=" + encodeURIComponent(cutoff) : url);
  function syncUrl() {
    const p = new URLSearchParams();
    if (cutoff) p.set("as_of", cutoff);
    if (sel) p.set("node", sel);
    history.replaceState(null, "", location.pathname + (p.toString() ? "?" + p : ""));
  }

  /* ---------- point-in-time controls ---------- */
  function setCutoffFromSlider() {
    const days = +$("kl-slider").value;
    cutoff = days === 0 ? null : iso(new Date(Date.now() - days * 86400000));
    $("kl-date").value = cutoff ? cutoff.slice(0, 16) : "";
  }
  let timer = null;
  $("kl-slider").addEventListener("input", () => { setCutoffFromSlider(); $("asof").textContent = "as of " + (cutoff || "now") + " …"; clearTimeout(timer); timer = setTimeout(load, 350); });
  $("kl-date").addEventListener("change", () => {
    const v = $("kl-date").value; if (!v) return;
    cutoff = v.length === 16 ? v + ":00Z" : v + "Z";
    $("kl-slider").value = Math.max(0, Math.min(730, Math.round((Date.now() - Date.parse(cutoff)) / 86400000)));
    load();
  });
  $("kl-now").addEventListener("click", () => { cutoff = null; $("kl-slider").value = 0; $("kl-date").value = ""; load(); });
  $("kl-limit").addEventListener("change", load);
  $("kl-fit").addEventListener("click", () => fit(false));
  $("kl-form").addEventListener("submit", search);

  /* ---------- graph ---------- */
  async function load() {
    syncUrl();
    try { graph = await getJSON(withCutoff(`/api/knowledge-graph?limit=${$("kl-limit").value}`)); }
    catch (e) { graph = null; clear($("kl-tags")).append(tag("unavailable: " + e.message, "gap")); return; }
    $("asof").textContent = "as of " + graph.as_of.replace("T", " ");
    $("kl-foot").textContent = `${graph.total_nodes} knowledge objects available at the cutoff · showing the ${graph.nodes.length} most recent`;
    renderFilters(); draw();
    if (sel && graph.nodes.some((n) => n.id === sel)) inspect(sel, false); else if (sel) { sel = null; syncUrl(); }
  }

  function renderFilters() {
    const tg = clear($("kl-tags"));
    tg.append(tag(`${graph.total_nodes} objects`, "on"), tag(`${graph.links.length} edges`));
    const st = {}; graph.nodes.forEach((n) => { if (n.status) st[n.status] = (st[n.status] || 0) + 1; });
    Object.entries(st).forEach(([k, v]) => tg.append(tag(`${k} ${v}`, k === "valid" || k === "evaluated" ? "gold" : "")));
    const dc = clear($("kl-domains"));
    Object.entries(graph.domains).sort((a, b) => b[1] - a[1]).forEach(([d, n]) => {
      const b = el("button", { type: "button", class: "chip", "aria-pressed": String(!hiddenDomains.has(d)), text: `${d.replace(/_/g, " ")} ${n}` });
      b.addEventListener("click", () => { hiddenDomains.has(d) ? hiddenDomains.delete(d) : hiddenDomains.add(d); renderFilters(); draw(); });
      dc.append(b);
    });
    const ec = clear($("kl-edges"));
    const counts = {}; graph.links.forEach((l) => { counts[l.type] = (counts[l.type] || 0) + 1; });
    Object.keys(graph.edge_legend).forEach((t) => {
      const b = el("button", { type: "button", class: "chip edge-" + t, "aria-pressed": String(!hiddenEdges.has(t)), text: `${t.replace(/_/g, " ")} ${counts[t] || 0}` });
      NGLTip.bind(b, () => ({ title: "Link type: " + t.replace(/_/g, " "), value: `${counts[t] || 0} links`, what: graph.edge_legend[t], read: "Click the chip to show or hide these links. Semantic similarity is a retrieval aid, not evidence of a real relationship." }), "edge_" + t);
      b.addEventListener("click", () => { hiddenEdges.has(t) ? hiddenEdges.delete(t) : hiddenEdges.add(t); renderFilters(); draw(); });
      ec.append(b);
    });
    const lg = clear($("kl-legend"));
    const sym = (s, filled, cls) => { const sv = d3.create("svg").attr("width", 14).attr("height", 14); sv.append("path").attr("transform", "translate(7,7)").attr("d", d3.symbol(s, 60)()).attr("class", "kl-node " + (filled ? "filled " : "") + (cls || "")); return sv.node(); };
    [["agent finding (gold = valid / evaluated, dashed = rejected or superseded)", SYMBOLS.agent_finding, false, "finding valid"], ["pipeline notice", SYMBOLS.pipeline_notice],
     ["backtest result", SYMBOLS.backtest], ["/execute thesis", SYMBOLS.alpha_synthesis], ["forecast discussion", SYMBOLS.noaa_discussion],
     ["measured-data summary (price, weather, storage, production, carbon)", d3.symbolCircle, true]].forEach(([t, s, f, c]) => lg.append(el("span", {}, [sym(s, f, c), el("span", { text: t })])));
  }

  function draw() {
    svg = d3.select("#kl-svg"); svg.selectAll("*").remove(); if (sim) sim.stop();
    if (!graph) return;
    const w = $("kl-svg").clientWidth || 900, h = $("kl-svg").clientHeight || 640;
    svg.attr("viewBox", `0 0 ${w} ${h}`);
    const nodes = graph.nodes.filter((n) => !hiddenDomains.has(n.domain)).map((n) => ({ ...n }));
    const ids = new Set(nodes.map((n) => n.id));
    const links = graph.links.filter((l) => !hiddenEdges.has(l.type) && ids.has(l.source) && ids.has(l.target)).map((l) => ({ ...l }));
    const deg = {}; links.forEach((l) => { deg[l.source] = (deg[l.source] || 0) + 1; deg[l.target] = (deg[l.target] || 0) + 1; });
    gRoot = svg.append("g");
    zoom = d3.zoom().scaleExtent([0.2, 6]).on("zoom", (ev) => gRoot.attr("transform", ev.transform));
    svg.call(zoom).on("dblclick.zoom", null);
    sim = d3.forceSimulation(nodes)
      .force("link", d3.forceLink(links).id((d) => d.id).distance((l) => (l.type === "semantic_neighbor" ? 110 : l.type === "evidence_for" ? 60 : 40))
        .strength((l) => (l.type === "semantic_neighbor" ? 0.04 : 0.45)))
      .force("charge", d3.forceManyBody().strength(-60)).force("x", d3.forceX(w / 2).strength(0.04)).force("y", d3.forceY(h / 2).strength(0.06))
      .force("collide", d3.forceCollide(7)).stop();
    for (let i = 0; i < 320; i++) sim.tick();                 // deterministic layout before the first paint
    linksSel = gRoot.append("g").selectAll("line").data(links).join("line").attr("class", (d) => "kl-edge " + d.type);
    nodesSel = gRoot.append("g").selectAll("path").data(nodes).join("path")
      .attr("d", (d) => d3.symbol(SYMBOLS[d.domain] || d3.symbolCircle, 40 + 14 * Math.min(10, deg[d.id] || 0))())
      .attr("class", (d) => "kl-node" + (FILLED.has(d.domain) ? " filled" : "") + (d.domain === "agent_finding" ? " finding " + (d.status || "unchecked") : ""))
      .attr("tabindex", 0).attr("role", "button").attr("aria-label", (d) => `${d.domain}: ${d.title}`)
      .on("click", (_, d) => inspect(d.id, true)).on("keydown", (ev, d) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); inspect(d.id, true); } })
      .call(d3.drag().on("start", (ev, d) => { if (!ev.active) sim.alphaTarget(0.2).restart(); d.fx = d.x; d.fy = d.y; })
        .on("drag", (ev, d) => { d.fx = ev.x; d.fy = ev.y; }).on("end", (ev, d) => { if (!ev.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }));
    nodesSel.each(function (d) {
      NGLTip.bind(this, () => ({ title: d.title, value: d.domain.replace(/_/g, " "), badge: { text: (d.provenance || "").replace(/_/g, " "), cls: d.provenance === "model_hypothesis" || d.provenance === "backtest_result" ? "estimate" : "measured" },
        what: ((d.document || "").slice(0, 280)) + ((d.document || "").length > 280 ? "…" : ""), read: "Click to open the full object, its links and its checks. Drag to move it.",
        sections: [{ h: "Where it came from", rows: [["Available (PIT)", (d.available_timestamp || "—").replace("T", " ")], ["Published", (d.published_timestamp || "—").replace("T", " ")], ["Source", d.source_id], ["Agents", (d.agent_ids || "").split(",").filter(Boolean).map(shortAgent).join(", ")],
          ["Verdict", d.status || null], ["Raw payload", d.raw_payload_hash ? d.raw_payload_hash.slice(0, 16) + "…" : null, "hash"], ["Object id", d.id, "hash"]] }],
        notes: ["An object is only returned for a cutoff after it became available, so older cutoffs cannot see it."] }), "kg_" + d.id, { pin: false });
    });
    const paint = () => {
      linksSel.attr("x1", (d) => d.source.x).attr("y1", (d) => d.source.y).attr("x2", (d) => d.target.x).attr("y2", (d) => d.target.y);
      nodesSel.attr("transform", (d) => `translate(${d.x},${d.y})`);
    };
    sim.on("tick", paint);
    paint(); fit(true); mark();
  }

  function fit(instant) {
    if (!graph || !nodesSel) return;
    const ns = nodesSel.data(); if (!ns.length) return;
    const xs = ns.map((d) => d.x), ys = ns.map((d) => d.y);
    const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
    const w = $("kl-svg").clientWidth || 900, h = $("kl-svg").clientHeight || 640;
    const k = Math.min(4, 0.9 / Math.max((x1 - x0) / w, (y1 - y0) / h, 1e-3));
    const t = d3.zoomIdentity.translate(w / 2, h / 2).scale(k).translate(-(x0 + x1) / 2, -(y0 + y1) / 2);
    if (instant === true) svg.call(zoom.transform, t); else svg.transition().duration(400).call(zoom.transform, t);
  }
  function focus(id) {
    const d = nodesSel && nodesSel.data().find((n) => n.id === id); if (!d) return;
    const w = $("kl-svg").clientWidth || 900, h = $("kl-svg").clientHeight || 640;
    const k = Math.max(1.6, d3.zoomTransform(svg.node()).k);
    svg.transition().duration(350).call(zoom.transform, d3.zoomIdentity.translate(w / 2, h / 2).scale(k).translate(-d.x, -d.y));
  }
  function mark() {
    if (!nodesSel) return;
    const nb = new Set();
    linksSel.each((l) => { if (l.source.id === sel || l.source === sel) nb.add(l.target.id || l.target); if (l.target.id === sel || l.target === sel) nb.add(l.source.id || l.source); });
    nodesSel.classed("sel", (d) => d.id === sel).classed("hit", (d) => hits.has(d.id)).classed("nb", (d) => nb.has(d.id))
      .classed("dimmed", (d) => (sel || hits.size) && d.id !== sel && !nb.has(d.id) && !hits.has(d.id));
    linksSel.classed("sel", (l) => sel && ((l.source.id || l.source) === sel || (l.target.id || l.target) === sel));
  }

  /* ---------- inspector ---------- */
  async function inspect(id, zoomTo) {
    sel = id; syncUrl(); mark(); if (zoomTo) focus(id);
    const box = clear($("kl-detail")); box.append(el("div", { class: "dim", text: "Loading…" }));
    let r;
    try { r = await getJSON(withCutoff(`/api/knowledge-node/${encodeURIComponent(id)}`)); }
    catch (e) { clear(box).append(el("div", { text: "Unavailable: " + e.message })); return; }
    const n = r.node; clear(box);
    box.append(el("div", { class: "kl-kind", text: `${n.domain.replace(/_/g, " ")} · ${n.provenance}` }), el("h3", { text: n.title }));
    if (n.status) box.append(el("div", { class: "kl-status " + n.status.status, text: `${n.status.status.toUpperCase()} — ${n.status.reason} (${n.status.checker}, ${n.status.checked_at})` }));
    if (n.provenance === "model_hypothesis") box.append(el("div", { class: "kl-warn", text: "Model-generated hypothesis: not a measured observation." }));
    box.append(el("p", { class: "kl-doc", text: n.document }));
    const dl = el("dl");
    const add = (k, v) => dl.append(el("dt", { text: k }), el("dd", { text: v == null || v === "" ? "—" : String(v) }));
    add("id", n.id); add("available", n.available_timestamp); add("published", n.published_timestamp); add("period", n.period); add("series", n.series_key);
    add("source", n.source_id); add("agents", (n.agent_ids || "").split(",").filter(Boolean).map(shortAgent).join(", ")); add("raw payload sha256", n.raw_payload_hash);
    add("stored", n.created);
    box.append(dl);
    if (n.raw_payload) {
      box.append(el("h4", { text: "Source payload (archived, hash-verified)" }));
      const p = el("dl"); Object.entries(n.raw_payload).forEach(([k, v]) => p.append(el("dt", { text: k.replace(/_/g, " ") }), el("dd", { text: String(v) })));
      box.append(p);
    }
    if (n.extraction) {
      box.append(el("h4", { text: "Agent extraction" }));
      const p = el("dl"); Object.entries(n.extraction).forEach(([k, v]) => p.append(el("dt", { text: k.replace(/_/g, " ") }), el("dd", { text: v == null || v === "" ? "—" : String(v) })));
      box.append(p);
    }
    if (n.edges.length) {
      box.append(el("h4", { text: `Linked objects (${n.edges.length})` }));
      const order = ["evidence_for", "evaluated_by", "builds_on", "previous_in_series", "same_period", "semantic_neighbor"];
      n.edges.sort((a, b) => order.indexOf(a.type) - order.indexOf(b.type));
      for (const e of n.edges) {
        const row = el("button", { type: "button", class: "kl-link" }, [el("span", { class: "dim", text: `${e.direction === "out" ? "→" : "←"} ${e.type.replace(/_/g, " ")}${e.weight ? " " + Number(e.weight).toFixed(3) : ""}` }),
          el("span", { text: `${e.title}` }), el("span", { class: "dim", text: `${e.domain} · ${e.available_timestamp}` })]);
        row.addEventListener("click", () => inspect(e.id, true)); box.append(row);
      }
    }
  }

  /* ---------- search ---------- */
  async function search(ev) {
    ev.preventDefault();
    const q = $("kl-q").value.trim(); if (q.length < 2) return;
    const box = clear($("kl-detail")); box.append(el("div", { class: "dim", text: "Searching…" }));
    let r;
    try { r = await getJSON("/api/knowledge-search", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query: q, limit: 12, as_of: cutoff }) }); }
    catch (e) { clear(box).append(el("div", { text: "Search unavailable: " + e.message })); return; }
    hits = new Set(r.results.map((x) => x.id)); sel = null; mark();
    clear(box).append(el("h3", { text: `${r.results.length} results for “${r.query}”` }), el("div", { class: "dim", text: `as of ${r.as_of}. ${r.note}` }));
    for (const x of r.results) {
      const row = el("button", { type: "button", class: "kl-link" }, [el("span", { class: "dim", text: `${x.similarity.toFixed(3)} · ${x.domain}` }), el("span", { text: x.title }),
        el("span", { class: "dim", text: `available ${x.available_timestamp} · ${x.provenance}` })]);
      row.addEventListener("click", () => { hits = new Set(); inspect(x.id, true); }); box.append(row);
    }
  }

  /* ---------- agent activity ---------- */
  async function activity() {
    let a;
    try { a = await getJSON("/api/agents/activity?limit=15"); } catch (e) { clear($("kl-act-tags")).append(tag("unavailable", "gap")); return; }
    const tg = clear($("kl-act-tags"));
    Object.entries(a.topics || {}).forEach(([k, v]) => tg.append(tag(`${k.replace(/_/g, " ")} ${v}`)));
    Object.entries(a.finding_status || {}).forEach(([k, v]) => tg.append(tag(`${k} ${v}`, k === "valid" || k === "evaluated" ? "gold" : "")));
    const row = (cells) => el("tr", {}, cells.map((c) => el("td", { text: c == null ? "—" : String(c) })));
    const rb = clear(document.querySelector("#kl-runs tbody"));
    a.runs.forEach((r) => rb.append(row([r.agent, r.finished, r.ok ? "yes" : "FAILED", JSON.stringify(r.summary).slice(0, 160)])));
    const mb = clear(document.querySelector("#kl-msgs tbody"));
    a.messages.forEach((m) => mb.append(row([m.id, m.from, m.topic, (m.consumed_by || []).join(", ") || "pending"])));
    const lb = clear(document.querySelector("#kl-llm tbody"));
    a.llm_calls.forEach((c) => lb.append(row([c.agent, c.task, c.model, c.calls, c.ok, c.fallback, c.avg_ms])));
  }

  if (cutoff) { $("kl-date").value = cutoff.slice(0, 16); $("kl-slider").value = Math.max(0, Math.min(730, Math.round((Date.now() - Date.parse(cutoff)) / 86400000))); }
  load(); activity();
  setInterval(activity, 60000);
  window.addEventListener("resize", () => { clearTimeout(timer); timer = setTimeout(draw, 300); });
})();
