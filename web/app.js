/* NGL visual intelligence front end. Renders /api/state.json (the same document ngl-term.py renders).
   Nothing here computes market numbers: it only draws what the read-only service returns. Text from the API is
   always inserted with textContent, never as HTML. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const PENDING = "pending_collector";
  const qs = new URLSearchParams(location.search);
  const sel = { product: qs.get("product"), timeframe: qs.get("timeframe") || "seasonal" };
  let state = null, graph = null, map = null, mapReady = false, basemap = null, overlay = null, markers = [], overlayMarkers = [], mapHover = null;
  let mapOverlays = { routes: [], chokepoints: [], scenarios: [] }, mapLayerState = { routes: true, risk: true, shock: false };
  let selectedRoute = null, activeScenario = null, lastRouteFit = null, mapOverlaySerial = 0, mapLayersReady = false;
  const idle = (fn) => (window.requestIdleCallback ? window.requestIdleCallback(fn, { timeout: 250 }) : setTimeout(fn, 0));

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
  const num = (v, d) => (v == null || Number.isNaN(v) ? "—" : Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }));
  const signed = (v, d) => (v == null ? "—" : (v > 0 ? "+" : "") + num(v, d));
  const dec = (unit) => (unit === "cents/gal" ? 1 : unit === "USD/bbl" ? 2 : 3);
  const short = (a) => a.replace(/^Agent_/, "").replace(/_/g, " ");
  const tag = (text, cls) => el("span", { class: "tag " + (cls || ""), text });

  /* ---------- rich tooltips: specs are built from the API payload (state.explain + lineage in state.sources) at hover time ---------- */
  const X = (id) => (state && state.explain && state.explain[id]) || { title: id.replace(/_/g, " "), what: "", params: {} };
  const fts = (v) => (v ? String(v).replace("T", " ") : "—");
  const fv = (v, d) => (v == null || !Number.isFinite(v) ? "—" : num(v, d));
  const badgeOf = (p) => (p ? { text: ({ extracted_estimate: "estimate", unverified_seed: "unverified seed", pending_collector: "pending collector" })[p] || String(p).replace(/_/g, " "),
    cls: p === "pending_collector" || p === "unverified_seed" ? "is-pending" : p === "extracted_estimate" ? "estimate" : "measured" } : null);
  function lineage(agent) {
    const r = state && state.sources.find((x) => x.agent_id === agent);
    if (!r) return { h: "Data lineage", rows: [["Agent", agent], ["Roster", "not in the platform roster, so no intended source is assigned", "dim"]] };
    if (r.status !== "collected") return { h: "Why there is no value", rows: [["Agent", r.agent_id], ["Series", r.series], ["Intended source", r.intended_source], ["Status", "no collector writes this series yet", "warn"], ["Simulated?", "never: the cell stays blank until real data arrives", "dim"]] };
    return { h: "Data lineage", rows: [["Agent", r.agent_id], ["Series", r.series], ["Source", r.source_id], ["Roster source note", r.intended_source], ["Observation date", r.latest_target_timestamp ? r.latest_target_timestamp.slice(0, 10) : null],
      ["Retrieved", fts(r.retrieved_timestamp)], ["Available (PIT)", fts(r.available_timestamp)], ["Quality", (r.quality_status || "").replace(/_/g, " ")], ["Provenance", (r.provenance || "").replace(/_/g, " ")],
      ["Payload", r.raw_payload_hash ? r.raw_payload_hash.slice(0, 16) + "…" + (r.raw_payload_archived ? " · archived" : "") : null, "hash"], ["Age", r.age_days == null ? null : num(r.age_days, 1) + " days"]] };
  }
  function spec(id, x) {
    const d = X(id); x = x || {};
    return { ask: { metric: id, agent: x.agent || null, title: x.title || d.title }, title: x.title || d.title, badge: x.badge, value: x.value, what: x.what || d.what, formula: x.formula === undefined ? d.formula : x.formula, params: x.params || d.params,
      sections: x.sections, notes: [].concat(x.notes || [], d.caveat || []), read: x.read === undefined ? d.read : x.read };
  }
  /* T(id, node, extra, registryId): documented metric `id` shown when `node` is hovered, focused or tapped; extra (object or function) adds live values and lineage */
  const KVDRILL = { "Frac spread": "frac_spread", "Mont Belvieu − Conway": "hub_spread", "Forward curve": "regime", "Shale gas, six basins": "shale_total", "Working gas in storage": "storage_total",
    "HDD vs 30-yr normal": "hdd_anomaly", "Live flow meters": "flow_count", "Critical notices, 7 days": "notices_7d", "Force majeure, 30 days": "fm_30d" };
  const D = (node, metric, o) => (window.NGLDrill ? window.NGLDrill.bind(node, metric, o) : node);          // click opens the derivation of this number (drill.js)
  const T = (id, node, x, tid, opts) => NGLTip.bind(node, () => spec(id, typeof x === "function" ? x() : x), tid || id, opts);

  function pending(node, title, lines) {
    if (typeof below === "function" && node.id) below(node, null);
    clear(node).append(el("div", { class: "pending" }, [el("b", { text: title })].concat((lines || []).map((t) => el("span", { text: t })))));
  }

  /* ---------- generic hairline chart ---------- */
  function chart(node, c) {
    clear(node);
    const w = node.clientWidth || 600, h = node.clientHeight || 200, m = { t: 8, r: 52, b: 18, l: 4 };
    const svg = d3.select(node).append("svg").attr("viewBox", `0 0 ${w} ${h}`).attr("preserveAspectRatio", "none");
    const n = c.x.length, xs = d3.scaleLinear().domain([0, Math.max(1, n - 1)]).range([m.l, w - m.r]);
    let vals = [];
    (c.lines || []).forEach((l) => vals.push(...l.y));
    (c.areas || []).forEach((a) => vals.push(...a.y0, ...a.y1));
    if (c.bars) vals.push(...c.bars.y, 0);
    (c.hlines || []).forEach((l) => { if (l.fit !== false) vals.push(l.y); });
    vals = vals.filter((v) => v != null && Number.isFinite(v));
    let dom = c.yDomain || d3.extent(vals);
    if (!c.yDomain) { const pad = (dom[1] - dom[0] || Math.abs(dom[0]) || 1) * 0.06; dom = [dom[0] - pad, dom[1] + pad]; }
    const ys = d3.scaleLinear().domain(dom).range([h - m.b, m.t]);
    const yt = ys.ticks(c.yTicks || 4);
    const g = svg.append("g").attr("class", "grid");
    yt.forEach((t) => g.append("line").attr("x1", m.l).attr("x2", w - m.r).attr("y1", ys(t)).attr("y2", ys(t)));
    const ax = svg.append("g").attr("class", "axis");
    yt.forEach((t) => ax.append("text").attr("x", w - m.r + 5).attr("y", ys(t) + 3).text(c.yFmt ? c.yFmt(t) : d3.format("~g")(t)));
    ax.append("line").attr("x1", m.l).attr("x2", w - m.r).attr("y1", h - m.b).attr("y2", h - m.b);
    const ticks = c.xTicks || d3.range(0, 6).map((i) => Math.round((i * (n - 1)) / 5)).filter((v, i, a) => a.indexOf(v) === i);
    ticks.forEach((i) => {
      const lab = c.xFmt ? c.xFmt(c.x[i], i) : String(c.x[i] ?? "");
      ax.append("text").attr("x", xs(i)).attr("y", h - 5).attr("text-anchor", i === 0 ? "start" : i >= n - 1 ? "end" : "middle").text(lab);
    });
    const def = (v) => v != null && Number.isFinite(v);
    (c.areas || []).forEach((a) => {
      const area = d3.area().defined((d, i) => def(a.y0[i]) && def(a.y1[i])).x((d, i) => xs(i)).y0((d, i) => ys(a.y0[i])).y1((d, i) => ys(a.y1[i]));
      svg.append("path").attr("class", "band " + (a.cls || "")).attr("d", area(a.y0));
    });
    if (c.bars) {
      const bw = Math.max(1, ((w - m.r - m.l) / Math.max(1, n)) * 0.7);
      c.bars.y.forEach((v, i) => {
        if (!def(v)) return;
        svg.append("rect").attr("class", "bar" + (v < 0 ? " neg" : "")).attr("x", xs(i) - bw / 2).attr("width", bw)
          .attr("y", Math.min(ys(v), ys(0))).attr("height", Math.max(0.5, Math.abs(ys(v) - ys(0))));
      });
    }
    (c.hlines || []).forEach((l) => {
      if (l.y < dom[0] || l.y > dom[1]) return;
      svg.append("line").attr("class", "hl " + (l.cls || "")).attr("x1", m.l).attr("x2", w - m.r).attr("y1", ys(l.y)).attr("y2", ys(l.y));
      if (l.label) {
        const tl = svg.append("text").attr("class", "hl-label " + (l.cls || "")).attr("x", m.l + 3).attr("y", ys(l.y) - 3).text(l.label);
        if (l.drill) D(tl.node(), l.drill);
      }
    });
    (c.lines || []).forEach((l) => {
      const line = d3.line().defined((d) => def(d)).x((d, i) => xs(i)).y((d) => ys(d));
      svg.append("path").attr("class", "ln " + (l.cls || "")).attr("d", line(l.y));
    });
    (c.markers || []).forEach((k) => {
      if (k.i < 0 || !def(k.y)) return;
      svg.append("circle").attr("class", "mk " + (k.cls || "")).attr("cx", xs(k.i)).attr("cy", ys(k.y)).attr("r", k.r || 3.5).style("pointer-events", "none");
      const hit = svg.append("circle").attr("class", "mk-hit").attr("cx", xs(k.i)).attr("cy", ys(k.y)).attr("r", 10).style("fill", "transparent");
      if (k.tipId) T(k.tipId, hit.node(), k.tip, k.tid);
      if (k.drill) D(hit.node(), k.drill);
    });
    if (c.pick) {
      const vl = svg.append("line").attr("class", "xhair").attr("y1", m.t).attr("y2", h - m.b).style("display", "none");
      NGLTip.hover(svg.node(), {
        index: (e) => { const px = d3.pointer(e, svg.node())[0]; return Math.max(0, Math.min(n - 1, Math.round(xs.invert(px)))); },
        pick: c.pick, guide: true,
        onMove: (i) => vl.attr("x1", xs(i)).attr("x2", xs(i)).style("display", null), onLeave: () => vl.style("display", "none"),
      });
    }
  }
  function below(node, child) {
    /* captions and legends sit AFTER the fixed-height chart box, so they never overlap the next element */
    const nx = node.nextElementSibling;
    if (nx && nx.dataset.for === node.id) nx.remove();
    if (child) { child.dataset.for = node.id; node.after(child); }
  }
  function legend(node, items) {
    below(node, el("div", { class: "legend-row" }, items.map(([cls, text]) => el("span", {}, [el("i", { class: cls }), text]))));
  }
  const dateFmt = (span) => (d) => (d ? (span > 400 ? d.slice(0, 7) : d.slice(5)) : "");
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  /* ---------- hero ---------- */
  function renderHero(s) {
    const p = s.product, t = s.technicals, u = s.price.unit, d = dec(u);
    $("hero-title").textContent = `Seasonal patterns & key technical levels — ${p.label}`;
    const tags = clear($("hero-tags"));
    T("timeframe", tags.appendChild(tag(s.timeframe.label, "on")), { value: s.timeframe.label, what: s.timeframe.note + "." }, "tag_timeframe");
    if (s.price.status !== "measured") {
      T("pending", tags.appendChild(tag("pending collector", "gap")), () => ({ title: p.label, sections: [lineage(p.agent_id)] }), "tag_pending");
      for (const id of ["price-chart", "seasonal-chart"]) pending($(id), "PENDING COLLECTOR", [s.price.note || "", "Agent: " + p.agent_id]);
      for (const id of ["rsi-chart", "macd-chart", "levels"]) clear($(id));
      return;
    }
    T("provenance", tags.appendChild(tag("measured", "on")), { value: "measured" }, "tag_measured");
    const sm = t.summary;
    if (sm.bollinger_squeeze) T("squeeze", D(tags.appendChild(tag("Bollinger squeeze", "gold")), "squeeze"), { value: "active", sections: [{ h: "Now", rows: [["Bandwidth", num(sm.bandwidth_pct, 1) + "%"], ["Squeeze threshold", num(t.bollinger.squeeze_threshold_pct, 1) + "%"]] }] }, "tag_squeeze");
    if (sm.triangle !== "none") T("triangle", D(tags.appendChild(tag(sm.triangle.replace(/_/g, " "), "gold")), "tri_pattern"), { value: sm.triangle.replace(/_/g, " ") }, "tag_triangle");
    if (sm.divergence_rsi !== "none") T("divergence_rsi", D(tags.appendChild(tag(sm.divergence_rsi + " RSI divergence", "gold")), "divergence:rsi"), { value: sm.divergence_rsi }, "tag_div_rsi");
    if (sm.divergence_macd !== "none") T("divergence_macd", D(tags.appendChild(tag(sm.divergence_macd + " MACD divergence", "gold")), "divergence:macd"), { value: sm.divergence_macd }, "tag_div_macd");
    const x = s.series.dates, n = x.length, fmt = dateFmt(n), pv = (v) => `${fv(v, d)} ${u}`;
    $("price-cap").textContent = `${p.label} (${u}) — ${s.timeframe.note}`;
    const lines = [
      { y: t.bollinger.upper, cls: "thin" }, { y: t.bollinger.lower, cls: "thin" },
      { y: t.sma200, cls: "dot" }, { y: t.sma50, cls: "dash" }, { y: s.series.values, cls: "bold" },
    ];
    const tri = t.triangle;
    if (tri.pattern !== "none" && tri.upper) {
      const i0 = x.indexOf(tri.upper.start_date), i1 = x.indexOf(tri.upper.end_date);
      if (i0 >= 0 && i1 > i0) for (const side of [tri.upper, tri.lower]) {
        lines.push({ y: x.map((_, i) => (i < i0 || i > i1 ? null : side.start + ((side.end - side.start) * (i - i0)) / (i1 - i0))), cls: "gold dash" });
      }
    }
    const fib = t.fibonacci, hl = [];
    if (fib.status === "ok") for (const k of ["23.6%", "38.2%", "50.0%", "61.8%", "78.6%"]) {
      hl.push({ drill: "fib:" + (parseFloat(k) / 100).toString(), y: fib.levels[k], label: `${k}  ${num(fib.levels[k], d)}`, cls: ["38.2%", "50.0%", "61.8%"].includes(k) ? "gold" : "", fit: false });
    }
    const sq = t.bollinger.squeeze;
    const px = (i) => ({ title: x[i], value: pv(s.series.values[i]), badge: badgeOf(s.price.provenance), what: "Close for this session, with the indicators as they stood on it.", formula: null, params: {}, read: null,
      sections: [{ h: "Indicators on this date", rows: [["50-day average", fv(t.sma50[i], d)], ["200-day average", fv(t.sma200[i], d)], ["Bollinger upper / lower", `${fv(t.bollinger.upper[i], d)} / ${fv(t.bollinger.lower[i], d)}`],
        ["Bandwidth", t.bollinger.bandwidth_pct[i] == null ? "—" : fv(t.bollinger.bandwidth_pct[i], 1) + "%"], ["RSI (14)", fv(t.rsi14[i], 1)], ["MACD histogram", fv(t.macd.hist[i], 3)]] }]
        .concat(i === n - 1 ? [lineage(p.agent_id)] : [{ h: "Lineage", rows: [["Source", s.price.source_id], ["Note", "per-session availability times are in the database; the latest session's are shown on the last point", "dim"]] }]) });
    chart($("price-chart"), {
      x, xFmt: fmt, lines, hlines: hl, pick: (i) => spec("price", px(i)),
      areas: [{ y0: t.bollinger.lower, y1: t.bollinger.upper }, { y0: t.bollinger.lower.map((v, i) => (sq[i] ? v : null)), y1: t.bollinger.upper.map((v, i) => (sq[i] ? v : null)), cls: "sq" }],
      markers: t.crossovers.map((c, k) => ({ i: x.indexOf(c.date), y: c.price, cls: "gold", tipId: "crossover", tid: "cross_" + k, tip: { title: c.type.replace("_", " "), value: `${c.date} · ${pv(c.price)}` } }))
        .concat([{ i: n - 1, y: s.series.values[n - 1], r: 3, tipId: "price", tid: "last_point", tip: px(n - 1), drill: "price" }]),
    });
    legend($("price-chart"), [["", "price"], ["dash", "50-day"], ["dot", "200-day"], ["dim", "Bollinger 20, 2σ"], ["gold dash", "triangle / Fibonacci"]]);
    chart($("rsi-chart"), { x, xFmt: () => "", lines: [{ y: t.rsi14 }], yDomain: [0, 100], yTicks: 3, hlines: [{ y: 70, label: "70" }, { y: 30, label: "30" }],
      pick: (i) => spec("rsi14", { title: `RSI (14) · ${x[i]}`, value: fv(t.rsi14[i], 1), sections: [{ h: "Same date", rows: [["Price", pv(s.series.values[i])]] }] }) });
    chart($("macd-chart"), { x, xFmt: fmt, bars: { y: t.macd.hist }, lines: [{ y: t.macd.signal, cls: "dash thin" }, { y: t.macd.line }], yTicks: 3,
      pick: (i) => spec("macd", { title: `MACD · ${x[i]}`, value: `hist ${fv(t.macd.hist[i], 3)}`, sections: [{ h: "On this date", rows: [["MACD line", fv(t.macd.line[i], 3)], ["Signal line", fv(t.macd.signal[i], 3)], ["Histogram", fv(t.macd.hist[i], 3)]] }] }) });
    const se = s.seasonal, g = se.day_of_year;
    $("seasonal-cap").textContent = `Seasonal overlay — ${se.history_years.length}-year band (${se.history_years[0] || "?"}–${se.history_years[se.history_years.length - 1] || "?"}) vs ${se.current_year}`;
    chart($("seasonal-chart"), {
      x: g, xTicks: [0, 13, 26, 39, g.length - 1], xFmt: (v) => MONTHS[Math.min(11, Math.floor(((v - 1) / 365) * 12))],
      areas: [{ y0: se.band_min, y1: se.band_max }],
      lines: Object.values(se.lines).map((y) => ({ y, cls: "thin" })).concat([{ y: se.band_avg, cls: "dash" }, { y: se.current, cls: "gold bold" }]),
      pick: (i) => spec("seasonal_band", { title: `${MONTHS[Math.min(11, Math.floor(((g[i] - 1) / 365) * 12))]} · day ${g[i]} of the year`, value: se.current[i] == null ? `${se.current_year}: no data yet` : `${se.current_year}: ${fv(se.current[i], d)} ${u}`,
        formula: null, params: {}, sections: [{ h: `Band of ${se.history_years.length} prior years`, rows: [["Maximum", fv(se.band_max[i], d)], ["Average", fv(se.band_avg[i], d)], ["Minimum", fv(se.band_min[i], d)]] },
          { h: "Each year on this day", rows: Object.entries(se.lines).map(([yr, ys]) => [yr, fv(ys[i], d)]) }] }),
    });
    legend($("seasonal-chart"), [["gold", String(se.current_year)], ["dash", "average"], ["dim", "prior years"]]);
    const lv = clear($("levels"));
    const DRILL = { "Last": "price", "50-day avg": "sma50", "200-day avg": "sma200", "Trend": "trend", "50/200 regime": "ma_regime", "RSI (14)": "rsi14", "MACD hist": "macd_hist", "Bandwidth": "bandwidth",
      "Triangle": "tri_pattern", "Breakout above": "tri_upper", "Breakdown below": "tri_lower", "RSI divergence": "divergence:rsi", "MACD divergence": "divergence:macd", "Swing high": "fib_high", "Swing low": "fib_low" };
    const cell = (k, v, gold, id, x2, tid) => { const c = el("div", { class: gold ? "gold" : "" }, [el("span", { text: k }), v]); lv.append(c); if (id) T(id, c, x2, tid); if (DRILL[k]) D(c, DRILL[k]); return c; };
    cell("Last", `${num(sm.last, d)} ${u}`, false, "price", () => ({ value: pv(sm.last), badge: badgeOf(s.price.provenance), sections: [{ h: "Changes", rows: [["1-day", `${signed(s.price.change_1d, d)} (${signed(s.price.change_1d_pct, 2)}%)`], ["5-day", `${signed(s.price.change_5d, d)} (${signed(s.price.change_5d_pct, 2)}%)`], ["Price date", s.price.date], ["Window high / low", `${fv(s.price.window_high, d)} / ${fv(s.price.window_low, d)}`]] }, lineage(p.agent_id)] }), "lvl_price");
    cell("50-day avg", num(sm.sma50, d), false, "sma50", () => ({ value: pv(sm.sma50), sections: [{ h: "Compared with", rows: [["Last", pv(sm.last)], ["200-day average", pv(sm.sma200)]] }] }));
    cell("200-day avg", num(sm.sma200, d), false, "sma200", () => ({ value: pv(sm.sma200), sections: [{ h: "Compared with", rows: [["Last", pv(sm.last)], ["50-day average", pv(sm.sma50)]] }] }));
    cell("Trend", sm.trend.replace(/_/g, " "), false, "trend", () => ({ value: sm.trend.replace(/_/g, " "), sections: [{ h: "Inputs", rows: [["Last", pv(sm.last)], ["200-day average", pv(sm.sma200)]] }] }));
    cell("50/200 regime", sm.ma_regime === "golden" ? "golden cross" : sm.ma_regime === "death" ? "death cross" : sm.ma_regime.replace(/_/g, " "), false, "ma_regime", () => ({ value: sm.ma_regime, sections: [{ h: "Inputs", rows: [["50-day average", pv(sm.sma50)], ["200-day average", pv(sm.sma200)]] }, { h: "Recent crossovers", rows: t.crossovers.slice(-3).map((c) => [c.date, c.type.replace("_", " ")]) }] }));
    cell("RSI (14)", num(sm.rsi14, 1), false, "rsi14", () => ({ value: fv(sm.rsi14, 1) }));
    cell("MACD hist", signed(sm.macd_hist, 3), false, "macd_hist", () => ({ value: signed(sm.macd_hist, 3), sections: [{ h: "Last session", rows: [["MACD line", fv(t.macd.line[n - 1], 3)], ["Signal line", fv(t.macd.signal[n - 1], 3)]] }] }));
    cell("Bandwidth", num(sm.bandwidth_pct, 1) + "%" + (sm.bollinger_squeeze ? " squeeze" : ""), sm.bollinger_squeeze, "bandwidth", () => ({ value: num(sm.bandwidth_pct, 1) + "%",
      sections: [{ h: "Squeeze test", rows: [["Squeeze threshold", num(t.bollinger.squeeze_threshold_pct, 1) + "%"], ["Squeeze active", sm.bollinger_squeeze ? "yes" : "no"]] }] }));
    cell("Triangle", sm.triangle.replace(/_/g, " "), sm.triangle !== "none", "triangle", () => ({ value: sm.triangle.replace(/_/g, " "),
      sections: tri.upper ? [{ h: "Fitted lines", rows: [["Window", `${tri.lookback} sessions`], ["Upper", `${fv(tri.upper.start, d)} → ${fv(tri.upper.end, d)}`], ["Lower", `${fv(tri.lower.start, d)} → ${fv(tri.lower.end, d)}`], ["Converging", tri.converging ? "yes" : "no"], ["Swing highs / lows used", `${tri.swing_highs} / ${tri.swing_lows}`]].concat(tri.bars_to_apex != null ? [["Bars to apex", num(tri.bars_to_apex, 0)]] : []) }] : [] }));
    if (tri.pattern !== "none") { cell("Breakout above", num(tri.breakout_above, d), true, "breakout", { value: pv(tri.breakout_above) }, "lvl_breakout"); cell("Breakdown below", num(tri.breakdown_below, d), true, "breakout", { value: pv(tri.breakdown_below) }, "lvl_breakdown"); }
    cell("RSI divergence", sm.divergence_rsi, sm.divergence_rsi !== "none", "divergence_rsi", { value: sm.divergence_rsi });
    cell("MACD divergence", sm.divergence_macd, sm.divergence_macd !== "none", "divergence_macd", { value: sm.divergence_macd });
    {
      const gi = (() => { const doy = Math.floor((new Date(x[n - 1]) - new Date(new Date(x[n - 1]).getFullYear(), 0, 0)) / 864e5); let b = 0; g.forEach((v, i) => { if (Math.abs(v - doy) < Math.abs(g[b] - doy)) b = i; }); return b; })();
      for (const [lab, arr, m] of [["Seasonal avg (this week)", se.band_avg, "seasonal_avg"], ["Seasonal min", se.band_min, "seasonal_min"], ["Seasonal max", se.band_max, "seasonal_max"]]) {
        const c = el("div", {}, [el("span", { text: lab }), arr[gi] == null ? "—" : num(arr[gi], d)]); lv.append(c); if (arr[gi] != null) D(c, `${m}:${g[gi]}`);
      }
    }
    if (fib.status === "ok") {
      cell("Swing high", `${num(fib.swing_high, d)} · ${fib.swing_high_date}`, false, "swing_high", { value: pv(fib.swing_high), sections: [{ h: "Date", rows: [["Swing high", fib.swing_high_date], ["Swing low", `${pv(fib.swing_low)} · ${fib.swing_low_date}`]] }] });
      cell("Swing low", `${num(fib.swing_low, d)} · ${fib.swing_low_date}`, false, "swing_low", { value: pv(fib.swing_low), sections: [{ h: "Date", rows: [["Swing low", fib.swing_low_date], ["Swing high", `${pv(fib.swing_high)} · ${fib.swing_high_date}`]] }] });
    }
  }

  /* ---------- right-hand stack ---------- */
  function renderPricing(s) {
    const box = clear($("pricing"));
    const tb = el("tbody"), w = s.curves.ngl_to_wti_pct.wti;
    const wtiRow = () => (w.value == null ? ["WTI", "pending"] : ["WTI", `${num(w.value, 2)} USD/bbl · ${w.date}`]);
    for (const p of s.products) {
      const pend = p.status === PENDING;
      const tr = el("tr", { class: p.id === s.active_product ? "active" : "" }, [
        el("td", { text: `${p.label.replace("Mont Belvieu ", "")}` }),
        el("td", { class: "num" + (pend ? " dim" : ""), text: pend ? "pending" : `${num(p.latest, dec(p.unit))} ${p.unit === "cents/gal" ? "¢/gal" : "$/MMBtu"}` }),
        el("td", { class: "num dim", text: p.pct_of_wti == null ? "—" : num(p.pct_of_wti, 1) + "%" }),
      ]);
      tb.append(tr);
      if (!pend) { D(tr.children[1], "price", { product: p.id }); if (p.pct_of_wti != null) D(tr.children[2], "pct_of_wti", { product: p.id }); }
      T(pend ? "pending" : "price", tr, () => ({ title: p.label, value: pend ? "pending collector" : `${num(p.latest, dec(p.unit))} ${p.unit}`, badge: pend ? { text: "pending collector", cls: "is-pending" } : { text: "measured", cls: "measured" },
        what: pend ? X("pending").what : `Latest ${p.label} observation (${p.latest_date}). Select the product above to chart it.`,
        formula: !pend && p.pct_of_wti != null ? X("pct_of_wti").formula : null, params: {}, read: null,
        sections: (!pend && p.pct_of_wti != null ? [{ h: "Relative value", rows: [["% of WTI", num(p.pct_of_wti, 2) + "%"], wtiRow()] }] : []).concat([lineage(p.agent_id)]) }), "product_" + p.id);
    }
    const wtr = el("tr", {}, [el("td", { text: "WTI crude (Cushing)" }), el("td", { class: "num", text: w.value == null ? "pending" : `${num(w.value, 2)} $/bbl` }), el("td", { class: "num dim", text: "100%" })]);
    tb.append(wtr);
    if (w.value != null) D(wtr.children[1], "drv:Agent_Crude_WTI_Spot");
    T("wti", wtr, () => ({ value: w.value == null ? "pending" : `${num(w.value, 2)} USD/bbl`, badge: badgeOf(w.value == null ? "pending_collector" : "measured"), sections: [{ h: "Date", rows: [["Price date", w.date]] }, lineage("Agent_Crude_WTI_Spot")] }));
    const th = (t, cls, id) => { const h = el("th", { class: cls, text: t }); if (id) T(id, h, null, "th_" + id); return h; };
    box.append(el("table", {}, [el("thead", {}, el("tr", {}, [el("th", { text: "Product" }), th("Price", "num", "price"), th("% WTI", "num", "pct_of_wti")])), tb]));
    const pr = s.price, c = s.curves, kv = el("div", { class: "kv", style: "padding:6px 10px 6px;margin:0;border:0" });
    const add = (k, v, id, x, tid) => { const a = el("span", { text: k }), b = el("span", { text: v }); kv.append(a, b); if (id) { T(id, a, x, tid); T(id, b, x, tid); } if (KVDRILL[k]) D(b, KVDRILL[k]); };
    const chg = (v, pc) => `${signed(v, dec(pr.unit))} (${signed(pc, 2)}%)`;
    const addChg = (k, v, pc, mAbs, mPct, id, x) => {
      const a = el("span", { text: k }), b = el("span", {}, [D(el("span", { text: signed(v, dec(pr.unit)) }), mAbs), " (", D(el("span", { text: signed(pc, 2) }), mPct), "%)"]); kv.append(a, b); T(id, a, x, id + "_k");
    };
    if (pr.status === "measured") {
      addChg("1-day change", pr.change_1d, pr.change_1d_pct, "change_1d", "change_1d_pct", "change_1d", { value: chg(pr.change_1d, pr.change_1d_pct), sections: [{ h: "Inputs", rows: [["Last price", `${num(pr.value, dec(pr.unit))} ${pr.unit}`], ["Price date", pr.date]] }] });
      addChg("5-day change", pr.change_5d, pr.change_5d_pct, "change_5d", "change_5d_pct", "change_5d", { value: chg(pr.change_5d, pr.change_5d_pct), sections: [{ h: "Inputs", rows: [["Last price", `${num(pr.value, dec(pr.unit))} ${pr.unit}`], ["Price date", pr.date]] }] });
      add("Price date", pr.date, "price_date", { value: pr.date, sections: [{ h: "Timestamps", rows: [["Observation (target) date", pr.date], ["Retrieved", fts(pr.retrieved_timestamp)], ["Available (PIT)", fts(pr.available_timestamp)]] }, lineage(pr.agent_id)] });
    }
    const f = c.frac_spread, hs = c.hub_spread, fw = c.forward_curve, fl = (a) => (a && a.length ? a[a.length - 1] : null);
    add("Frac spread", f.status === "measured" ? `${signed(f.frac_spread_usd_mmbtu.at(-1), 2)} $/MMBtu · ${f.regime}` : "pending (ethane)", "frac_spread", () => (f.status === "measured"
      ? { value: `${signed(fl(f.frac_spread_usd_mmbtu), 2)} USD/MMBtu · ${f.regime}`, sections: [{ h: "Inputs (latest)", rows: [["Ethane", `${fv(fl(f.ethane_usd_mmbtu), 2)} USD/MMBtu`], ["Henry Hub", `${fv(fl(f.henry_hub_usd_mmbtu), 2)} USD/MMBtu`], ["Date", fl(f.dates)]] }] }
      : { value: "pending", badge: { text: "pending collector", cls: "is-pending" }, notes: [f.note], sections: [{ h: "Known input", rows: [["Henry Hub", f.henry_hub_latest == null ? "—" : num(f.henry_hub_latest, 3) + " USD/MMBtu"]] }, lineage((f.missing || [])[0])] }));
    add("Mont Belvieu − Conway", hs.status === "measured" ? `${signed(hs.spread_mb_minus_conway.at(-1), 2)} ¢/gal` : "pending (Conway)", "hub_spread", () => (hs.status === "measured"
      ? { value: `${signed(fl(hs.spread_mb_minus_conway), 2)} cents/gal`, sections: [{ h: "Inputs (latest)", rows: [["Mont Belvieu", fv(fl(hs.mont_belvieu), 1)], ["Conway", fv(fl(hs.conway), 1)], ["Date", fl(hs.dates)]] }] }
      : { value: "pending", badge: { text: "pending collector", cls: "is-pending" }, notes: [hs.note], sections: [{ h: "Known input", rows: [["Mont Belvieu propane", hs.mont_belvieu_latest == null ? "—" : num(hs.mont_belvieu_latest, 1) + " cents/gal"]] }, lineage((hs.missing || [])[0])] }));
    add("Forward curve", fw.status === "measured" ? `${fw.regime}${fw.stale ? " · as of " + fw.as_of_date : ""}` : "pending", "regime", () => ({ value: fw.regime, notes: [fw.shape && fw.shape.basis], sections: fw.status === "measured" ? [{ h: "Curve", rows: [["Quote date", fw.as_of_date], ["Contracts", String((fw.points || []).length)], ["Stale", fw.stale ? "yes" : "no"]] }] : [] }), "regime_row");
    box.append(kv);
  }
  function renderFib(s) {
    const box = clear($("fib")), f = s.technicals.fibonacci;
    if (!f || f.status !== "ok") return pending(box, "PENDING COLLECTOR", ["No series for the active product."]);
    const d = dec(s.price.unit), bar = el("div", { class: "fib-bar" }), pu = (v) => `${num(v, d)} ${s.price.unit}`;
    bar.append(el("div", { class: "zone", style: "left:50%;width:11.8%" }));
    for (const r of [0, 23.6, 38.2, 50, 61.8, 78.6, 100]) {
      const key = r.toFixed(1) + "%";
      bar.append(el("div", { class: "seg-line", style: `left:${r}%` }));
      const lab = el("div", { class: "lab" + ([38.2, 50, 61.8].includes(r) ? " gold" : ""), style: `left:${r}%`, text: key });
      bar.append(lab);
      D(lab, "fib:" + (r / 100).toString());
      T("fib_level", lab, () => ({ title: `Fibonacci ${key}`, value: pu(f.levels[key]), sections: [{ h: "This grid", rows: [["Swing high", `${pu(f.swing_high)} · ${f.swing_high_date}`], ["Swing low", `${pu(f.swing_low)} · ${f.swing_low_date}`], ["Leg", f.leg + "-leg"],
        ["Last price", pu(f.last)], ["Nearest level", f.nearest_level + (key === f.nearest_level ? "  ← this one" : "")]] }] }), "fib_" + key);
    }
    const pos = Math.max(0, Math.min(100, f.retracement_pct ?? 0));
    const mk = el("div", { class: "px", style: `left:${pos}%`, "data-v": num(f.last, d) });
    bar.append(mk);
    D(mk, "fib_retrace");
    T("fib_marker", mk, () => ({ value: `${num(f.retracement_pct, 1)}% retraced`, sections: [{ h: "Position", rows: [["Last price", pu(f.last)], ["Leg", f.leg + "-leg"], ["Nearest level", f.nearest_level]] }] }));
    const g1 = el("span", { class: "gold", text: `Golden ratio proximity: ${num(f.golden_ratio_distance_pct_of_range, 1)}% of range from 61.8%` });
    const g2 = el("span", { text: `${f.leg}-leg · retraced ${num(f.retracement_pct, 1)}% · nearest ${f.nearest_level}` });
    D(g1, "fib_golden"); D(g2, "fib_retrace");
    box.append(bar, el("div", { class: "fib-foot" }, [g1, g2]));
    T("golden_ratio", g1, () => ({ value: `${num(f.golden_ratio_distance_pct_of_range, 1)}% of range`, sections: [{ h: "Inputs", rows: [["Level 61.8%", pu(f.levels["61.8%"])], ["Last price", pu(f.last)]] }] }));
    T("fib_marker", g2, () => ({ value: `${num(f.retracement_pct, 1)}% retraced` }), "fib_foot");
  }
  function renderAlerts(s) {
    const box = clear($("alerts")), dv = s.derived, kv = el("div", { class: "kv" });
    const add = (k, v, id, x, tid) => { const a = el("span", { text: k }), b = el("span", { text: v }); kv.append(a, b); if (id) { T(id, a, x, tid); T(id, b, x, tid); } if (KVDRILL[k]) D(b, KVDRILL[k]); };
    const group = (g) => { const gr = s.drivers.find((x) => x.group === g); return gr ? gr.items.map((i) => [short(i.agent_id), i.value == null ? "pending" : `${num(i.value, Math.abs(i.value) >= 100 ? 0 : 2)} ${i.unit || ""}`]) : []; };
    add("Shale gas, six basins", dv.shale_production_total_bcfd.value == null ? "pending" : num(dv.shale_production_total_bcfd.value, 1) + " Bcf/d", "shale_total", () => ({ value: dv.shale_production_total_bcfd.value == null ? "pending" : num(dv.shale_production_total_bcfd.value, 1) + " Bcf/d", badge: badgeOf(dv.shale_production_total_bcfd.provenance), sections: [{ h: "The six basins", rows: group("shale") }] }));
    add("Working gas in storage", dv.storage_total_bcf.value == null ? "pending" : `${num(dv.storage_total_bcf.value, 0)} Bcf · ${dv.storage_total_bcf.date}`, "storage_total", () => ({ value: dv.storage_total_bcf.value == null ? "pending" : `${num(dv.storage_total_bcf.value, 0)} Bcf`, badge: badgeOf(dv.storage_total_bcf.provenance), sections: [{ h: `Regions, week ending ${dv.storage_total_bcf.date || "—"}`, rows: group("storage") }, lineage("Agent_Storage_East")] }));
    add("HDD vs 30-yr normal", dv.hdd_anomaly.value == null ? "pending" : `${signed(dv.hdd_anomaly.value, 1)} · ${dv.hdd_anomaly.date}`, "hdd_anomaly", () => ({ value: dv.hdd_anomaly.value == null ? "pending" : signed(dv.hdd_anomaly.value, 1) + " HDD", badge: badgeOf(dv.hdd_anomaly.provenance), sections: [{ h: "Date", rows: [["Observation date", dv.hdd_anomaly.date]] }, lineage("Agent_Weather_Actual_HDD")] }));
    const flowSrc = s.sources.filter((r) => /^Agent_(Flow_|LNG_.*_Flow$)/.test(r.agent_id));
    add("Live flow meters", `${s.geo.flow_agents_collected} of ${s.geo.flow_agents_total}`, "flow_meters", () => ({ value: `${s.geo.flow_agents_collected} of ${s.geo.flow_agents_total} meters`, badge: { text: "coverage gap", cls: "is-pending" },
      sections: [{ h: "Each meter and where it is meant to come from", rows: flowSrc.map((r) => [short(r.agent_id), r.status === "collected" ? "measured" : (r.intended_source || "no collector")]) }] }));
    const nt = s.notices || {};
    add("Critical notices, 7 days", `${nt.last_7_days || 0} · ${Object.entries(nt.by_pipeline_7d || {}).map(([k, v]) => k + " " + v).join(", ") || "—"}`, "notices", () => ({ value: `${nt.last_7_days || 0} in 7 days`, badge: { text: "source documents", cls: "measured" },
      sections: [{ h: "By pipeline", rows: Object.entries(nt.by_pipeline_7d || {}) }], notes: [nt.source, nt.note] }));
    add("Force majeure, 30 days", String((nt.force_majeure_30d || []).length), "force_majeure", () => ({ value: String((nt.force_majeure_30d || []).length), sections: [{ h: "Most recent", rows: (nt.force_majeure_30d || []).slice(0, 6).map((n) => [n.posted.slice(5, 10), n.title]) }] }));
    box.append(kv);
    for (const a of s.alerts) { const r = el("div", { class: "alert " + a.level }, [el("span", { class: "lv", text: a.level }), el("span", { text: a.text })]); box.append(r); T("alert", r, { title: `Alert · ${a.level}`, value: a.kind, notes: [a.text] }, "alert_" + a.kind + "_" + a.level + "_" + box.children.length); }
    for (const n of (nt.recent || []).slice(0, 5)) {
      const r = el("div", { class: "alert notice" }, [el("span", { class: "lv", text: n.pipeline }), el("span", { text: `${n.posted.slice(5, 16).replace("T", " ")}Z  ${n.title}` })]); box.append(r);
      T("notices", r, { title: n.title, value: n.pipeline, badge: { text: "source document", cls: "measured" }, what: "The operator's own posting, shown as published.", formula: null, params: {}, sections: [{ h: "Posting", rows: [["Pipeline", n.pipeline], ["Posted (available)", fts(n.posted)], ["Document id", n.id, "hash"]] }] }, "notice_" + n.id);
    }
  }

  /* ---------- relative-value curves ---------- */
  function renderCurves(s) {
    const c = s.curves, w = c.ngl_to_wti_pct, names = { propane: "propane", normal_butane: "n-butane", natural_gasoline: "nat. gasoline" };
    const have = Object.keys(names).filter((k) => w[k].status === "measured"), miss = Object.keys(names).filter((k) => w[k].status !== "measured");
    const pendTip = (node, id, x, tid) => { const n = node.firstChild; if (n) T(id, n, x, tid); };
    if (!have.length) { pending($("wti-chart"), "PENDING COLLECTOR", ["No NGL price series yet."]); pendTip($("wti-chart"), "pending", { title: "NGL as % of WTI" }, "pend_wti"); }
    else {
      const x = w[have[0]].dates, cls = ["bold", "dash", "dot"];
      chart($("wti-chart"), { x, xFmt: dateFmt(x.length), lines: have.map((k, i) => ({ y: w[k].pct_of_wti, cls: cls[i] })), yFmt: (v) => v + "%",
        pick: (i) => spec("pct_of_wti", { title: `NGL as % of WTI · ${x[i]}`, value: have.map((k) => `${names[k]} ${fv(w[k].pct_of_wti[i], 1)}%`).join(" · "),
          sections: [{ h: "Same date", rows: have.map((k) => [names[k] + " % of WTI", fv(w[k].pct_of_wti[i], 2) + "%"]).concat(i === x.length - 1 ? [["WTI", w.wti.value == null ? "—" : `${num(w.wti.value, 2)} USD/bbl · ${w.wti.date}`]] : []) }]
            .concat(miss.length ? [{ h: "Not shown", rows: miss.map((k) => [names[k], "pending collector", "warn"]) }] : []) }) });
      legend($("wti-chart"), have.map((k, i) => [i === 0 ? "" : cls[i], `${names[k]} ${num(w[k].latest, 1)}%`]).concat(miss.length ? [["dim", "pending: " + miss.map((k) => names[k]).join(", ")]] : []));
    }
    const h = c.hub_spread;
    if (h.status !== "measured") { pending($("hub-chart"), "PENDING COLLECTOR", [h.note, "Mont Belvieu propane: " + num(h.mont_belvieu_latest, 1) + " ¢/gal", "Missing: " + h.missing.join(", ")]);
      pendTip($("hub-chart"), "hub_spread", () => ({ value: "pending", badge: { text: "pending collector", cls: "is-pending" }, notes: [h.note], sections: [lineage((h.missing || [])[0])] }), "pend_hub"); }
    else { chart($("hub-chart"), { x: h.dates, xFmt: dateFmt(h.dates.length), lines: [{ y: h.mont_belvieu, cls: "bold" }, { y: h.conway, cls: "dash" }], bars: { y: h.spread_mb_minus_conway },
      pick: (i) => spec("hub_spread", { title: `Mont Belvieu − Conway · ${h.dates[i]}`, value: `${signed(h.spread_mb_minus_conway[i], 2)} cents/gal`, sections: [{ h: "Same date", rows: [["Mont Belvieu", fv(h.mont_belvieu[i], 1)], ["Conway", fv(h.conway[i], 1)]] }] }) });
      legend($("hub-chart"), [["", "Mont Belvieu"], ["dash", "Conway"], ["dim", "spread (bars)"]]); }
    const f = c.frac_spread;
    if (f.status !== "measured") { pending($("frac-chart"), "PENDING COLLECTOR", [f.note, "Henry Hub: " + num(f.henry_hub_latest, 3) + " $/MMBtu", "Missing: " + f.missing.join(", ")]);
      pendTip($("frac-chart"), "frac_spread", () => ({ value: "pending", badge: { text: "pending collector", cls: "is-pending" }, notes: [f.note], sections: [lineage((f.missing || [])[0])] }), "pend_frac"); }
    else { chart($("frac-chart"), { x: f.dates, xFmt: dateFmt(f.dates.length), lines: [{ y: f.ethane_usd_mmbtu, cls: "bold" }, { y: f.henry_hub_usd_mmbtu, cls: "dash" }], bars: { y: f.frac_spread_usd_mmbtu }, hlines: [{ y: 0, label: "recovery above · rejection below", cls: "gold" }],
      pick: (i) => spec("frac_spread", { title: `Frac spread · ${f.dates[i]}`, value: `${signed(f.frac_spread_usd_mmbtu[i], 2)} USD/MMBtu`, sections: [{ h: "Same date", rows: [["Ethane (fuel-equivalent)", fv(f.ethane_usd_mmbtu[i], 2) + " USD/MMBtu"], ["Henry Hub", fv(f.henry_hub_usd_mmbtu[i], 2) + " USD/MMBtu"]] }] }) });
      legend($("frac-chart"), [["", "ethane $/MMBtu"], ["dash", "Henry Hub"], ["dim", "frac spread (bars)"]]); }
    const fw = c.forward_curve, ft = clear($("fwd-tags")), pts0 = (q) => q.points || [];
    if (fw.status !== "measured") { pending($("fwd-chart"), "PENDING COLLECTOR", ["No futures contracts collected."]); pendTip($("fwd-chart"), "pending", { title: "Henry Hub forward curve" }, "pend_fwd"); }
    else {
      T("regime", D(ft.appendChild(tag(fw.regime, fw.stale ? "" : "on")), "regime"), () => ({ value: fw.regime, notes: [fw.shape && fw.shape.basis], sections: [{ h: "Curve", rows: [["Quote date", fw.as_of_date], ["Front spread", fw.shape && fw.shape.front_spread_label ? `${fw.shape.front_spread_label} ${signed(fw.shape.front_spread, 3)}` : null], ["Reversals", fw.shape ? String(fw.shape.reversals) : null]] }] }), "tag_regime");
      if (pts0(fw).some((q) => /unverified/.test(q.quality_status || ""))) T("quality", ft.appendChild(tag("delayed quotes · unverified", "gap")), { value: "delayed quote, unverified", notes: ["These are delayed, unofficial quotes, not CME settlements."] }, "tag_quality");
      if (fw.stale) T("forward_curve", ft.appendChild(tag("stale · " + fw.as_of_date, "gap")), { value: "stale", notes: [fw.note] }, "tag_stale");
      const pts = fw.points;
      chart($("fwd-chart"), { x: pts.map((q) => q.contract), xTicks: pts.map((_, i) => i), xFmt: (v) => v, lines: [{ y: pts.map((q) => q.value), cls: "bold" }],
        markers: pts.map((q, i) => ({ i, y: q.value, drill: "fwd:" + q.contract, tipId: "fwd_point", tid: "fwd_" + q.contract, tip: {
          title: `${q.contract}${q.delivery_month ? " · delivery " + q.delivery_month : ""}`, value: `${q.value.toFixed(3)} ${q.unit || ""}`, badge: { text: (q.quality_status || "").replace(/_/g, " ") || "quote", cls: /unverified/.test(q.quality_status || "") ? "is-pending" : "measured" },
          sections: [{ h: "Contract", rows: [["Symbol", q.series_id], ["Delivery month", q.delivery_month], ["Quote date", q.date]] },
            { h: "Data lineage", rows: [["Source", q.source_id], ["Published", q.published_timestamp ? fts(q.published_timestamp) : "not supplied by the source"], ["Retrieved", fts(q.retrieved_timestamp)], ["Available (PIT)", fts(q.available_timestamp)], ["Quality", (q.quality_status || "").replace(/_/g, " ")], ["Payload", q.raw_payload_hash ? q.raw_payload_hash.slice(0, 16) + "…" : null, "hash"]] }],
          notes: [X("t_published").what + " " + (q.published_timestamp ? "" : "This source did not supply one."), i > 0 ? "" : "Prompt-month contract."] } })) });
      const lr = el("span", { text: fw.note || (fw.shape && fw.shape.peak ? `${pts.length} contracts · peak ${fw.shape.peak.contract} ${fw.shape.peak.delivery_month || ""} ${fw.shape.peak.value.toFixed(3)} · trough ${fw.shape.trough.contract} ${fw.shape.trough.delivery_month || ""} ${fw.shape.trough.value.toFixed(3)} · ${fw.shape.front_spread_label} ${fw.shape.front_spread >= 0 ? "+" : ""}${fw.shape.front_spread.toFixed(3)}` : `${pts.length} contracts`) });
      below($("fwd-chart"), el("div", { class: "legend-row" }, [lr]));
      T("forward_curve", lr, () => ({ value: fw.regime, notes: [fw.shape && fw.shape.basis] }), "fwd_legend");
    }
  }

  /* ---------- LNG forward cost curve: every number below comes from the API (curves.lng_forward); nothing is computed here ---------- */
  function renderLng(s) {
    const lg = (s.curves || {}).lng_forward, box = $("lng-chart"), tg = clear($("lng-tags"));
    if (!lg || !box) return;
    if (lg.status !== "estimate") {
      pending(box, "PENDING COLLECTOR", [lg.note || "", "Missing: " + (lg.missing || []).join(", ")]);
      if (box.firstChild) T("lng_forward", box.firstChild, { value: "pending", badge: { text: "pending collector", cls: "is-pending" }, notes: [lg.note] }, "pend_lng");
      return;
    }
    const pts = lg.points, a = lg.assumptions, nb = lg.netback, f3 = (v) => fv(v, 3);
    T("lng_forward", tg.appendChild(tag("estimate", "gold")), { value: "extracted estimate", badge: badgeOf("extracted_estimate") }, "tag_lng_estimate");
    T("lng_forward", tg.appendChild(tag(`${a.feedgas_factor.value} × HH + ${fv(a.liquefaction_fee.value, 2)}`, "")), () => ({ title: "Assumptions behind this curve", value: `${a.feedgas_factor.value} × HH + ${fv(a.liquefaction_fee.value, 2)}`,
      sections: [{ h: "Set in lng_config.py: assumptions, not market data", rows: Object.values(a).map((x) => [`${x.text} (${x.kind})`, `${x.value} ${x.unit}`]) }] }), "tag_lng_assume");
    T("lng_netback", tg.appendChild(tag(nb.points_with_netback ? `TTF netback ${nb.points_with_netback}/${pts.length}` : "netback: pending JKM/TTF", nb.points_with_netback ? "on" : "gap")), () => ({
      value: nb.points_with_netback ? `${nb.points_with_netback} of ${pts.length} months` : "pending", badge: badgeOf(nb.points_with_netback ? "extracted_estimate" : "pending_collector"), notes: [nb.ttf, nb.fx, nb.jkm],
      sections: Object.keys(nb.reasons || {}).length ? [{ h: "Months without a netback", rows: Object.entries(nb.reasons) }] : [] }), "tag_lng_netback");
    const lngTip = (p) => ({ title: `${p.contract}${p.delivery_month ? " · delivery " + p.delivery_month : ""}`, value: `${f3(p.fob_cost)} USD/MMBtu FOB cost`, badge: badgeOf("extracted_estimate"),
      sections: [{ h: "Calculation", rows: [["Henry Hub futures (same month)", `${f3(p.hh_value)} USD/MMBtu`], [`× feed gas factor (${a.feedgas_factor.kind})`, String(a.feedgas_factor.value)], ["= feed gas cost", `${f3(p.feedgas_cost)} USD/MMBtu`],
        [`+ liquefaction fee (${a.liquefaction_fee.kind})`, `${f3(p.liquefaction_fee)} USD/MMBtu`], ["= FOB cost", `${f3(p.fob_cost)} USD/MMBtu`]] }]
        .concat(p.netback ? [{ h: "Netback from TTF (same month)", rows: [["TTF quote", `${fv(p.netback.ttf_eur_mwh, 2)} EUR/MWh`], ["× EUR/USD", fv(p.netback.eurusd, 4)], ["= TTF in USD/MMBtu", f3(p.netback.ttf_usd_mmbtu)],
          [`− shipping (${a.shipping.kind})`, f3(a.shipping.value)], [`− regasification (${a.regas.kind})`, f3(a.regas.value)], ["= netback", `${f3(p.netback.value)} USD/MMBtu`], ["Margin over FOB cost", `${f3(p.netback.margin_vs_fob_cost)} USD/MMBtu`],
          ["TTF last trade", fts(p.netback.ttf_published_timestamp)], ["TTF quote available (PIT)", fts(p.netback.ttf_available_timestamp)], ["EUR/USD published", fts(p.netback.fx_published_timestamp)]] }]
          : [{ h: "Netback", rows: [["Not shown", p.netback_note || "no fresh TTF quote", "warn"]] }])
        .concat([{ h: "Data lineage: the Henry Hub quote", rows: [["Contract", p.hh_series_id], ["Source", p.hh_source_id], ["Published", p.hh_published_timestamp ? fts(p.hh_published_timestamp) : "not supplied by the source"], ["Available (PIT)", fts(p.hh_available_timestamp)],
          ["Quality", (p.hh_quality_status || "").replace(/_/g, " ")], ["Payload", p.hh_raw_payload_hash ? p.hh_raw_payload_hash.slice(0, 16) + "…" : null, "hash"]] }]) });
    chart(box, { x: pts.map((p) => p.contract), xTicks: pts.map((_, i) => i), xFmt: (v) => v,
      lines: [{ y: pts.map((p) => p.hh_value), cls: "dash thin" }, { y: pts.map((p) => p.fob_cost), cls: "bold" }, { y: pts.map((p) => (p.netback ? p.netback.value : null)), cls: "gold" }],
      markers: pts.map((p, i) => ({ i, y: p.fob_cost, drill: "lng_fob:" + p.contract, tipId: "lng_fwd_point", tid: "lng_" + p.contract, tip: lngTip(p) })).concat(pts.map((p, i) => (p.netback ? { i, y: p.netback.value, cls: "gold", drill: "lng_netback:" + p.contract, tipId: "lng_netback", tid: "lngnb_" + p.contract, tip: lngTip(p) } : null)).filter(Boolean)) });
    const lr = el("span", { text: `${pts.length} months · ${lg.formula.replace("FEEDGAS_FACTOR", a.feedgas_factor.value).replace("LIQUEFACTION_FEE", fv(a.liquefaction_fee.value, 2))}` });
    const foot = el("div", { class: "lng-foot" });      // one container: below() replaces the previous caption, so every caption row must live inside this one
    foot.append(el("div", { class: "legend-row" }, [el("span", {}, [el("i", { class: "dash" }), "Henry Hub"]), el("span", {}, [el("i", {}), "FOB cost"]), el("span", {}, [el("i", { class: "gold" }), "TTF netback"]), lr]));
    T("lng_forward", lr, () => ({ value: lg.formula }), "lng_legend");
    const prm = lg.parameters || {}, plabel = { k_hh_multiplier: "k (HH multiplier)", liquefaction_usd_mmbtu: "L (liquefaction fee)" };
    for (const [key, p] of Object.entries(prm)) {
      const lib = p.source === "library";
      const row = el("div", { class: "legend-row" }, [el("span", { text: `${plabel[key] || key} = ${fv(p.value, 4)} ${p.unit || ""} · ` }), el("span", { class: lib ? "" : "dim", text: lib ? `knowledge library: “${p.quote}”` : `assumption (${p.reason || "default"})` })]);
      foot.append(row);
      T("lng_forward", row, () => ({ title: plabel[key] || key, value: `${fv(p.value, 4)} ${p.unit || ""}`, badge: badgeOf(lib ? "extracted_estimate" : "pending_collector"),
        notes: lib ? ["Taken from a verbatim quote stored in the knowledge library; the number appears in the quote and passed the sanity band."] : [`Labelled default assumption: ${p.reason || ""}`],
        sections: lib ? [{ h: "Where it came from", rows: [["Document", p.title], ["Chunk", p.chunk_id, "hash"], ["Similarity", p.similarity == null ? null : String(p.similarity)], ["Document available (PIT)", fts(p.doc_available_timestamp)], ["Prompt", p.prompt_version], ["Quote", p.quote]] }] : [] }), "lngp_" + key);
    }
    if ((lg.context || []).length) foot.append(el("div", { class: "legend-row dim" }, [el("span", { text: "Related knowledge (context only, never changes a number): " + lg.context.slice(0, 4).map((n) => n.title).join(" · ") })]));
    below(box, foot);
  }

  const LNG_GLOBAL_DOCS = {
    hh_forward: "lng_hh_forward", terminal_feedgas: "lng_terminal_feedgas", usgc_fob: "lng_usgc_fob", atlantic_fob: "lng_atlantic_fob",
    pacific_fob: "lng_pacific_fob", spark30s_atlantic_freight: "lng_spark30s_atlantic_freight", spark25s_pacific_freight: "lng_spark25s_pacific_freight",
    usgc_ttf_netback: "lng_usgc_ttf_netback", usgc_jkm_netback: "lng_usgc_jkm_netback", panama_cape_spread: "lng_panama_cape_spread",
    jkm_forward: "lng_jkm_forward", ttf_forward: "lng_ttf_forward", nwe_des: "lng_nwe_des", swe_des: "lng_swe_des", nbp_forward: "lng_nbp_forward",
    wim_forward: "lng_wim_forward", jkm_ttf_spread: "lng_jkm_ttf_spread", winter_summer_spread: "lng_winter_summer_spread",
    m1_m2_calendar_spread: "lng_m1_m2_calendar_spread", brent_linked_parity: "lng_brent_linked_parity"
  };

  function renderLngGlobal(s) {
    const root = $("lng-global"), tg = clear($("lng-global-tags")), g = (s.curves || {}).lng_global;
    if (!root || !g || !g.calculations) return;
    clear(root);
    const items = Object.entries(g.calculations), months = g.delivery_months || [];
    const d = g.diagnostics || {}, cal = g.calibration || {}, inputs = g.inputs || {}, elig = inputs.eligibility || {};
    const fmt = (v, n) => fv(v, n == null ? 2 : n);
    const statusText = { observed_quote: "observed quote", converted_observed: "converted TTF + FX", observed_proxy: "observed oil proxy", modeled: "modeled estimate" };
    const statusBadge = (v) => ({ text: statusText[v] || v || "modeled estimate", cls: v === "modeled" ? "estimate" : "measured" });
    const cellClass = (v) => v.observed_status === "observed_quote" ? "observed" : v.observed_status === "converted_observed" ? "observed converted" : v.observed_status === "observed_proxy" ? "observed proxy" : "";
    const spark = (values) => {
      const ns = "http://www.w3.org/2000/svg", svg = document.createElementNS(ns, "svg"), line = document.createElementNS(ns, "polyline");
      const ys = values.map((v) => v.base).filter((v) => Number.isFinite(v));
      const lo = Math.min.apply(null, ys), hi = Math.max.apply(null, ys), span = Math.max(hi - lo, 1e-9);
      svg.setAttribute("viewBox", "0 0 132 30"); svg.setAttribute("width", "132"); svg.setAttribute("height", "30"); svg.setAttribute("class", "lng-spark");
      line.setAttribute("points", values.map((v, i) => `${(i / Math.max(values.length - 1, 1)) * 128 + 2},${27 - ((v.base - lo) / span) * 24}`).join(" "));
      line.setAttribute("fill", "none"); line.setAttribute("stroke", "#f0c36a"); line.setAttribute("stroke-width", "1.5");
      svg.appendChild(line); return svg;
    };
    const cards = el("div", { class: "lng-card-grid" });
    for (const [key, item] of items) {
      const vals = item.values || [], first = vals[0] || {};
      const card = el("div", { class: "lng-card" }, [el("div", { class: "lng-card-h", text: item.id }),
        el("div", { class: "lng-card-v", text: `${fmt(first.base)} ${item.unit || ""}` }),
        el("div", { class: "lng-card-r", text: `M1 ${fmt(first.low)} – ${fmt(first.high)} · ${vals.length} months · ${statusText[first.observed_status] || "modeled"}` }), spark(vals)]);
      T(LNG_GLOBAL_DOCS[key] || "lng_global", card, () => ({ title: item.id, value: `${fmt(first.base)} ${item.unit || ""}`, badge: statusBadge(first.observed_status),
        sections: [{ h: "Model", rows: [["Calculation", key], ["Unit", item.unit], ["Delivery months", String(vals.length)], ["Status", item.status], ["Provenance", item.provenance], ["Model version", g.model_version]] },
          { h: "Inputs", rows: [["Observed quotes", (item.input_lineage?.observed_quotes || []).join(", ") || "none"], ["Modeled inputs", (item.input_lineage?.modeled_inputs || []).join(", ")]] },
          { h: "Method", rows: [["Marginal FOB", "facility-level cost ranking with available capacity"], ["Freight and netback", "voyage simulation with fuel, boil-off, canal, arrival timing and delivered energy"], ["Uncertainty", "low/base/high are P10/P50/P90 from correlated scenario simulation"]] }] }), "lngg_card_" + key);
      cards.appendChild(card);
    }
    root.appendChild(cards);
    const matrixWrap = el("div", { class: "lng-matrix-wrap" }), table = el("table", { class: "lng-matrix" }), thead = el("thead"), trh = el("tr");
    trh.appendChild(el("th", { class: "lng-row-h", text: "Calculation" }));
    for (const m of months) trh.appendChild(el("th", { text: m }));
    thead.appendChild(trh); table.appendChild(thead);
    const tbody = el("tbody");
    for (const [key, item] of items) {
      const row = el("tr"), label = el("th", { class: "lng-row-h", text: item.id });
      T(LNG_GLOBAL_DOCS[key] || "lng_global", label, () => ({ title: item.id, value: item.unit }), "lngg_row_" + key);
      row.appendChild(label);
      item.values.forEach((v, i) => {
        const cell = el("td", { class: cellClass(v), text: fmt(v.base) });
        const quoteRows = (v.lineage || []).flatMap((q) => [["Status", statusText[v.observed_status] || v.observed_status], ["Agent", q.agent_id], ["Series", q.series_id], ["Source", q.source_id], ["Quote value", `${fmt(q.value, 3)} ${q.native_unit || ""}`], ["Published", fts(q.published_timestamp)], ["Available (PIT)", fts(q.available_timestamp)], ["Age (days)", fmt(q.age_days, 2)], ["Freshness limit", `${q.max_age_days} days (${q.freshness_basis})`], ["Quality", (q.quality_status || "").replace(/_/g, " ")], ["Payload", q.raw_payload_hash ? String(q.raw_payload_hash).slice(0, 16) + "…" : null]]);
        T(LNG_GLOBAL_DOCS[key] || "lng_global_point", cell, () => ({ title: `${item.id} · ${v.contract}`, value: `${fmt(v.base)} ${item.unit}`, badge: statusBadge(v.observed_status),
          sections: [{ h: "Delivery", rows: [["Contract", v.contract], ["Delivery month", v.delivery_month], ["Status", statusText[v.observed_status] || v.observed_status], ["Point provenance", v.provenance], ["Observed anchor", v.observed == null ? "calibrated estimate" : fmt(v.observed, 3)], ["Native quote", v.observed_native_value == null ? null : `${fmt(v.observed_native_value, 3)} ${v.observed_native_unit || ""}`], ["Conversion", v.observed_conversion ? v.observed_conversion.formula || v.observed_conversion.note : null]] },
            ...(quoteRows.length ? [{ h: "Quote lineage and freshness", rows: quoteRows }] : []),
            { h: "Scenario distribution", rows: [["Low P10", fmt(v.low, 3)], ["P25", fmt(v.p25, 3)], ["Base P50", fmt(v.base, 3)], ["P75", fmt(v.p75, 3)], ["High P90", fmt(v.high, 3)], ["95% CI", `${fmt(v.ci_low, 3)} – ${fmt(v.ci_high, 3)}`], ["Model confidence", fmt(v.model_confidence, 3)]] },
            { h: "Diagnostics", rows: [["Atlantic marginal plant", d.atlantic_marginal_facility], ["Pacific marginal plant", d.pacific_marginal_facility], ["Pacific route", d.pacific_route], ["Scenarios", String(d.scenario_count || "")]] }] }), "lngg_" + key + "_" + i);
        row.appendChild(cell);
      });
      tbody.appendChild(row);
    }
    table.appendChild(tbody); matrixWrap.appendChild(table); root.appendChild(matrixWrap);
    const foot = el("div", { class: "lng-global-foot" }, [el("span", { text: `${items.length} calculations · ${months.length} delivery months · ${d.scenario_count || 0} scenarios · ${g.model_version}` }),
      el("span", { text: `Eligible quotes ${elig.accepted_count || 0} · rejected ${elig.rejected_count || 0} · HH anchors ${(elig.hh_anchors || []).length} · TTF anchors ${(elig.ttf_anchors || []).length}` }),
      el("span", { text: `TTF native EUR/MWh → USD/MMBtu · FX ${(inputs.ttf_conversion || {}).fx_source || "modeled"}` }),
      el("span", { text: `Marginal plants: ${d.atlantic_marginal_facility || "—"} / ${d.pacific_marginal_facility || "—"} · Pacific route: ${d.pacific_route || "—"}` }),
      el("span", { text: `Calibration: ${cal.source || "defaults"}${cal.available_timestamp ? " · " + fts(cal.available_timestamp) : ""}${cal.backtest && cal.backtest.selected ? " · backtest winner " + cal.backtest.selected : ""}` })]);
    root.appendChild(foot);
    T("lng_global", tg.appendChild(tag(g.model_version, "gold")), () => ({ title: "Global LNG model diagnostics", value: g.model_version,
      sections: [{ h: "Quote eligibility", rows: [["Accepted", String(elig.accepted_count || 0)], ["Rejected", String(elig.rejected_count || 0)], ["Freshness rules", Object.entries(elig.freshness_rules || {}).map(([k, v]) => `${k}: ${v.max_age_days}d (${v.basis})`).join(" · ")],
        ...(elig.rejected || []).slice(0, 8).map((r) => [r.quote_key, r.reason, "warn"]) ] },
        { h: "Calibration", rows: [["Source", cal.source], ["Available", fts(cal.available_timestamp)], ["Backtest winner", cal.backtest && cal.backtest.selected], ["Scenario count", String(cal.scenario_count || "")],
          ...Object.entries(inputs.parameter_provenance || {}).slice(0, 8).map(([k, v]) => [k, `${v.source}: ${v.reason || v.method || ""}`])] },
        { h: "Voyage", rows: [["Atlantic days", fmt(d.arrival_offset_days && d.arrival_offset_days.atlantic, 1)], ["Panama days", fmt(d.arrival_offset_days && d.arrival_offset_days.panama, 1)], ["Cape days", fmt(d.arrival_offset_days && d.arrival_offset_days.cape, 1)], ["Delivered fraction", fmt(d.delivered_fraction && d.delivered_fraction.panama, 3)]] }] }), "lngg_model");
    if (elig.rejected_count) T("lng_global", tg.appendChild(tag(`${elig.rejected_count} quotes rejected`, "gap")), () => ({ title: "Rejected quotes", value: `${elig.rejected_count} rejected`,
      sections: [{ h: "Rejections", rows: (elig.rejected || []).map((r) => [r.quote_key, r.reason, "warn"]) }] }), "lngg_rejected");
    const detail = el("details", { class: "under" }, [el("summary", { text: "Model assumptions and calibration diagnostics" }), el("pre", { class: "lng-assumptions", text: JSON.stringify({ assumptions: g.assumptions, calibration: g.calibration, diagnostics: g.diagnostics }, null, 2) })]);
    root.appendChild(detail);
  }

  /* ---------- the seven fundamental elements: direct inputs vs separately calculated modules ---------- */
  function renderFundamentals(s) {
    const box = clear($("fundamentals")), f = s.fundamentals;
    if (!f) return;
    box.append(el("div", { class: "fund-sub", text: "What actually sets the forward prices on this page" }));
    const pg = el("div", { class: "fund-grid" });
    for (const p of f.forward_price_inputs) {
      const card = el("div", { class: "fund-card" + (p.status === "pending_collector" ? " pend" : "") }, [
        el("div", { class: "fund-hd" }, [el("b", { text: p.id }), el("span", { text: p.label }), el("span", { class: "chip " + (p.market_derived ? "dir" : "mod"), text: p.market_derived ? "market quote" : "assumption" })]),
        el("div", { class: "fund-val", text: p.value || (p.n != null ? `${p.n} points` : p.status) }), el("div", { class: "dim", text: `sets ${p.sets}` }), el("div", { class: "dim", text: p.provenance })]);
      pg.append(card);
      T("fundamental_element", card, () => ({ title: `${p.id} · ${p.label}`, value: p.value || (p.n != null ? `${p.n} points` : p.status), badge: badgeOf(p.status === "pending_collector" ? "pending_collector" : p.market_derived ? "measured" : "extracted_estimate"),
        what: `Sets ${p.sets}.`, formula: null, params: {}, read: null, sections: [{ h: "Basis", rows: [["Provenance", p.provenance], ["Latest date", p.date], ["Market-derived?", p.market_derived ? "yes: a delayed, unofficial quote" : "no: a labelled assumption"]] }] }), "fwdin_" + p.id);
    }
    box.append(pg);
    box.append(el("div", { class: "fund-sub", text: "The seven fundamental elements: context, not price inputs" }));
    box.append(el("div", { class: "fund-note dim", text: f.price_note }));
    const grid = el("div", { class: "fund-grid" });
    for (const e of f.elements) {
      const h = e.headline, sep = e.mode === "calculated_separately";
      const val = h && h.value != null ? `${fv(h.value, Math.abs(h.value) >= 100 ? 0 : 2)} ${h.unit || ""}` : "pending";
      const sub = h ? `${h.label}${h.date ? " · " + h.date : ""}${h.p10 != null ? ` · p10 ${fv(h.p10, 1)} / p90 ${fv(h.p90, 1)}` : ""}` : e.blocked.length ? `${e.blocked.length} blocked input${e.blocked.length > 1 ? "s" : ""}` : "no data yet";
      const fvEl = el("div", { class: "fund-val", text: val }), dm = ({ M1: "shale_total", M2: "hdd_anomaly", M3: "storage_total", M4: "feedgas:p50", M6: "lng_exports_total", M7: "border_net" })[e.id];
      if (dm) D(fvEl, dm);
      const card = el("div", { class: "fund-card" + (h ? "" : " pend") }, [
        el("div", { class: "fund-hd" }, [el("b", { text: e.id }), el("span", { text: e.label }), el("span", { class: "chip " + (sep ? "mod" : "dir"), text: sep ? "separate module" : "direct input" })]),
        fvEl, el("div", { class: "dim", text: sub }), el("div", { class: "dim", text: e.role })]);
      if (e.blocked.length) card.append(el("div", { class: "warn", text: `blocked: ${e.blocked.map((b) => b.id || b.input).join(", ")}` }));
      grid.append(card);
      const prov = h && h.provenance;
      const badge = !h ? badgeOf("pending_collector") : String(prov).startsWith("bootstrapped") ? { text: "bootstrapped proxy", cls: "estimate" } : badgeOf(prov === "extracted_estimate" ? "extracted_estimate" : "measured");
      T("fundamental_element", card, () => ({ agent: (e.agents || [])[0], title: `${e.id} · ${e.label}`, value: `${val}${h && h.p10 != null ? ` (p10 ${fv(h.p10, 2)} · p90 ${fv(h.p90, 2)})` : ""}`, badge, what: e.role, formula: null, params: {}, read: null,
        sections: [{ h: "Classification", rows: [["Class", sep ? "calculated separately (orthogonal module)" : "direct ingested input"], ["Method", e.method], ["Source", e.source], ["Scope rule", e.scope_rule],
          ["Graph link", e.graph_link], ["Moves a forward price here?", "no: " + (e.price_path.reason || "").slice(0, 160), "dim"]] },
          { h: "Inputs", rows: [["Current value", val], ["Frequency", e.frequency], ["Collector", e.collector_status], ["Agents", `${e.agents_collected} of ${e.agents_total}`],
            ["Newest input (PIT)", e.age_days == null ? null : `${e.age_days} days ago`], ["Observation", h && h.date],
            ...(e.raw_payload_hashes.length ? e.raw_payload_hashes.map((x) => ["Payload hash", x.hash.slice(0, 16) + "… " + short(x.agent), "hash"]) : [["Payload hash", e.id === "M4" ? "none: computed (inputs: M6)" : null]])] },
          { h: "Calculations it feeds today", rows: [["Display / derived", e.feeds_today.length ? e.feeds_today.join("; ") : "none"], ["Forward price", "none (checklist O6)", "dim"]] },
          { h: "Blocked inputs (exact blocker · activating step)", rows: e.blocked.map((b) => [b.id ? `${b.id} ${b.input}` : b.input, `${b.reason} → ${b.activate}`, "warn"]) }] }), "fund_" + e.id);
    }
    box.append(grid);
  }
  /* ---------- drivers and sources ---------- */
  function renderDrivers(s) {
    const box = clear($("drivers"));
    const disp = Object.fromEntries(((s.fundamentals && s.fundamentals.disposition) || []).map((d) => [d.group, d]));
    for (const g of s.drivers) {
      const units = new Set(g.items.filter((i) => i.value != null).map((i) => i.unit)), max = d3.max(g.items, (i) => (i.value != null ? Math.abs(i.value) : 0)) || 1;
      const h3 = el("h3", { text: g.label });
      const gdoc = ({ lng_exports: "lng_exports", border_flows: "border_flows", lng: "flow_meters" })[g.group];
      if (gdoc) T(gdoc, h3, { title: g.label }, "grp_" + g.group);
      const card = el("div", { class: "drv" }, h3);
      if (disp[g.group]) card.append(el("div", { class: "warn", style: "font-size:11px;padding-bottom:4px", text: `not one of the 7 elements · ${disp[g.group].decision}: ${disp[g.group].reason}` }));
      for (const i of g.items) {
        const pend = i.value == null;
        const row = el("div", { class: "drv-row" + (pend ? " pend" : "") }, [
          el("span", { class: "nm", text: short(i.agent_id) }),
          el("span", { class: "bar-wrap" }, pend || units.size !== 1 ? null : el("i", { style: `width:${Math.max(2, (Math.abs(i.value) / max) * 100)}%` })),
          el("span", { class: "val", text: pend ? "pending" : `${num(i.value, Math.abs(i.value) >= 100 ? 0 : 2)}` }),
        ]);
        card.append(row);
        D(row, "drv:" + i.agent_id);
        const src = s.sources.find((r) => r.agent_id === i.agent_id);
        T(pend ? "pending" : "provenance", row, () => ({ agent: i.agent_id, title: short(i.agent_id), value: pend ? "pending collector" : `${num(i.value, Math.abs(i.value) >= 100 ? 0 : 3)} ${i.unit || ""}`,
          badge: badgeOf(pend ? "pending_collector" : i.provenance), what: (src && src.series) || (pend ? X("pending").what : "A data series collected by the platform."), formula: null, params: {}, read: null,
          sections: [{ h: g.label, rows: pend ? [] : [["Observation date", i.target_date], ["Available (PIT)", fts(i.available_timestamp)]] }, lineage(i.agent_id)] }), "driver_" + i.agent_id);
      }
      const u = [...units][0];
      if (units.size === 1) card.append(el("div", { class: "dim", style: "font-size:11px;padding-top:4px", text: u }));
      box.append(card);
    }
  }
  function renderSources(s) {
    const all = $("src-all").checked, tb = clear(document.querySelector("#sources tbody"));
    const rows = s.sources.filter((r) => all || r.contributes || !r.in_roster);
    const ts = (v) => (v ? v.replace("T", " ").replace(":00Z", "Z").slice(0, 17) : "—");
    for (const r of rows) {
      const st = r.status === "collected" ? "collected" : PENDING, pv = r.provenance || "none";
      const feed = r.feed_status || "UNREGISTERED", fst = feed === "ACTIVE" ? "collected" : PENDING, flabel = r.feed_label || "Feed Not Configured";
      const tr = el("tr", {}, [
        el("td", { text: short(r.agent_id) }), el("td", {}, el("span", { class: "st " + st, text: st.replace("_", " ") })),
        el("td", {}, el("span", { class: "st " + fst, text: flabel })),
        el("td", {}, el("span", { class: "st " + pv, text: pv === "none" ? "no data" : pv.replace(/_/g, " ") })),
        el("td", { class: "dim", text: r.source_id || "—" }), el("td", { text: r.latest_target_timestamp ? r.latest_target_timestamp.slice(0, 10) : "—" }),
        el("td", { text: ts(r.available_timestamp) }), el("td", { class: "dim", text: ts(r.retrieved_timestamp) }), el("td", { class: "dim", text: (r.quality_status || "—").replace(/_/g, " ") }),
        el("td", { class: "hash" + (r.raw_payload_archived ? " ok" : ""), text: r.raw_payload_hash ? r.raw_payload_hash.slice(0, 12) + "…" : "—" }),
      ]);
      tb.append(tr);
      T(st === "collected" ? "provenance" : "pending", tr, () => ({ title: short(r.agent_id), value: st === "collected" ? `latest ${r.latest_target_timestamp ? r.latest_target_timestamp.slice(0, 10) : "—"}` : flabel,
        badge: badgeOf(st === "collected" ? r.provenance : "pending_collector"), what: r.series || X("roster").what, formula: null, params: {}, read: null,
        sections: [{ h: "Feed", rows: [["Status", feed], ["Label", flabel], ["Age", r.feed_age_days == null ? "—" : num(r.feed_age_days, 1) + " days"]] }].concat([lineage(r.agent_id)]).concat(st === "collected" && r.intended_source ? [{ h: "Intended source (roster)", rows: [["Source", r.intended_source]] }] : []) }), "source_" + r.agent_id);
    }
    const hd = { 0: ["roster", "Agent"], 1: ["provenance", "Status"], 2: ["roster", "Feed"], 3: ["provenance", "Provenance"], 4: ["roster", "Source"], 5: ["t_target", "Latest target"], 6: ["t_available", "Available"], 7: ["t_retrieved", "Retrieved"], 8: ["quality", "Quality"], 9: ["payload_hash", "Raw payload hash"] };
    document.querySelectorAll("#sources thead th").forEach((th, k) => { if (hd[k]) T(hd[k][0], th, { title: hd[k][1] }, "th_src_" + k); });
    const p = s.platform, tg = clear($("src-tags"));
    const t1 = tag(`${p.roster_agents_collected}/${p.roster_agents} roster agents`, "on"), t2 = tag(`${num(p.pit_rows, 0)} PIT rows`), t3 = tag(`${p.raw_payloads} raw payloads`);
    tg.append(t1, t2, t3);
    T("roster", t1, { value: `${p.roster_agents_collected} of ${p.roster_agents} collected`, sections: [{ h: "Still pending", rows: s.sources.filter((r) => r.in_roster && r.status !== "collected").slice(0, 12).map((r) => [short(r.agent_id), r.intended_source || "no collector"]) }] }, "tag_roster");
    T("pit_rows", t2, { value: num(p.pit_rows, 0) }, "tag_pit"); T("payload_hash", t3, { value: String(p.raw_payloads) + " archived responses" }, "tag_payloads");
    const lg = clear($("src-legend"));
    for (const [k, v] of Object.entries(p.provenance_legend)) { const sp = el("span", {}, [el("span", { class: "st " + k, text: k.replace(/_/g, " ") })]); lg.append(sp); T("provenance", sp, { title: k.replace(/_/g, " "), badge: badgeOf(k), what: v, read: null }, "legend_" + k); }
    lg.append(el("span", { class: "hash ok", text: "payload archived" }));
  }

  /* ---------- map ---------- */
  const LABEL_POS = { MBV: [-1, -1], HHB: [1, -1], SAB: [1, 1], CAM: [1, -2.2], CCP: [-1, 1.2], FPT: [-1, 1], CRP: [-1, 0], PLQ: [1, 0], CSH: [1, 0], CNW: [-1, -1], HYN: [1, -1], PRM: [-1, -1], EGF: [-1, -1], APP: [1, 0], CVP: [1, 0], ELB: [1, 0], BKN: [1, 0], DJB: [-1, 0] };
  function initMap(s) {
    if (map || !window.maplibregl) return;
    try {
      map = new maplibregl.Map({ container: "map", attributionControl: false, dragRotate: false, pitchWithRotate: false, renderWorldCopies: false,
        style: { version: 8, sources: {}, layers: [{ id: "bg", type: "background", paint: { "background-color": "#161618" } }] },
        bounds: [[-108, 24.5], [-73, 45.5]], maxBounds: [[-180, -60], [180, 80]], minZoom: 1.5, maxZoom: 8 });
    } catch (e) { pending($("map"), "MAP UNAVAILABLE", ["WebGL is required to draw the map."]); return; }
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    mapHover = el("div", { class: "map-hover" }); mapHover.style.display = "none"; $("map").append(mapHover);
    installMapControls();
    map.on("error", (e) => { $("map-note").dataset.err = "map error: " + ((e && e.error && e.error.message) || "unknown"); });
    for (const [layer, fn] of [["lng-routes-hit", showRouteHover], ["lng-chokepoints-hit", showRiskHover]]) {
      map.on("mousemove", layer, (e) => fn(e, e.features && e.features[0]));
      map.on("mouseleave", layer, hideMapHover);
      map.on("click", layer, (e) => { const f = e.features && e.features[0]; if (!f) return; if (layer === "lng-routes-hit") selectRoute(f.properties.id); else showRiskDetail(f.properties.id); });
    }
    // The style is inline (no network), so "style.load" is the reliable ready signal; "load" also waits for a first render.
    let started = false;
    const onReady = async () => {
      if (started) return; started = true;
      mapReady = true;
      try { basemap = await (await fetch("/static/data/na_basemap.json")).json(); }
      catch (e) { $("map-note").dataset.err = "basemap failed: " + e.message; }
      drawMap(state || s);
    };
    map.once("style.load", onReady); map.once("load", onReady);
    if (map.isStyleLoaded()) onReady();
  }
  const ROUTE_LAYERS = ["lng-routes-glow", "lng-routes-line", "lng-routes-hit"];
  const RISK_LAYERS = ["lng-chokepoints-halo", "lng-chokepoints-dot", "lng-chokepoints-hit"];
  function installMapControls() {
    const box = el("div", { class: "maplibregl-ctrl maplibregl-ctrl-group map-ctrl" });
    for (const [key, label] of [["routes", "routes"], ["risk", "risk"], ["shock", "shock"], ["fit", "fit"]]) {
      const b = el("button", { type: "button", "data-layer": key, "aria-pressed": String(key === "fit" ? false : mapLayerState[key]), title: label, text: label });
      b.addEventListener("click", () => {
        if (key === "fit") { fitMapOverlays(); return; }
        mapLayerState[key] = !mapLayerState[key];
        if (key === "shock" && mapLayerState[key] && !activeScenario) activeScenario = (mapOverlays.scenarios[0] || {}).id || null;
        b.setAttribute("aria-pressed", String(mapLayerState[key]));
        renderMapInspector(state); applyMapLayers();
      });
      box.append(b);
    }
    map.addControl({ onAdd: () => box, onRemove: () => box.remove() }, "top-left");
  }
  function applyMapLayers() {
    if (!map || !mapLayersReady) return;
    const visible = (ids, on) => ids.forEach((id) => { if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", on ? "visible" : "none"); });
    visible(ROUTE_LAYERS, mapLayerState.routes);
    visible(RISK_LAYERS, mapLayerState.risk);
    visible(["lng-terminal-halos"], mapLayerState.shock && !!activeScenario);
    overlayMarkers.forEach((m) => { m.getElement().style.display = mapLayerState.routes ? "" : "none"; });
    if (map.getLayer("lng-terminal-halos")) {
      const sc = mapOverlays.scenarios.find((x) => x.id === activeScenario);
      map.setPaintProperty("lng-terminal-halos", "circle-radius", 10 + (sc ? sc.global_supply_loss_pct * 0.25 : 0));
      map.setPaintProperty("lng-terminal-halos", "circle-opacity", sc ? 0.24 : 0);
    }
  }
  function addMapLayers() {
    if (!map || mapLayersReady) return;
    const empty = () => ({ type: "FeatureCollection", features: [] });
    map.addSource("lng-routes", { type: "geojson", data: empty() });
    map.addSource("lng-chokepoints", { type: "geojson", data: empty() });
    map.addSource("lng-terminal-halos", { type: "geojson", data: empty() });
    map.addLayer({ id: "lng-routes-glow", type: "line", source: "lng-routes", paint: { "line-color": "rgba(240,195,106,.16)", "line-width": 8 } });
    map.addLayer({ id: "lng-routes-line", type: "line", source: "lng-routes", paint: { "line-color": ["case", ["==", ["get", "status"], PENDING], "#e0a86a", "#f0c36a"], "line-width": 2 } });
    map.addLayer({ id: "lng-routes-hit", type: "line", source: "lng-routes", paint: { "line-color": "#f0c36a", "line-opacity": 0, "line-width": 16 } });
    map.addLayer({ id: "lng-chokepoints-halo", type: "circle", source: "lng-chokepoints", paint: {
      "circle-radius": ["interpolate", ["linear"], ["get", "risk"], 0.2, 9, 0.9, 24],
      "circle-color": ["match", ["get", "band"], "high", "#e76f51", "elevated", "#e0a86a", "#2a9d8f"], "circle-opacity": 0.16 } });
    map.addLayer({ id: "lng-chokepoints-dot", type: "circle", source: "lng-chokepoints", paint: {
      "circle-radius": 3.5, "circle-color": ["match", ["get", "band"], "high", "#e76f51", "elevated", "#e0a86a", "#2a9d8f"],
      "circle-stroke-color": "#f7f1e8", "circle-stroke-width": 0.8 } });
    map.addLayer({ id: "lng-chokepoints-hit", type: "circle", source: "lng-chokepoints", paint: { "circle-radius": 18, "circle-color": "#2a9d8f", "circle-opacity": 0 } });
    map.addLayer({ id: "lng-terminal-halos", type: "circle", source: "lng-terminal-halos", paint: { "circle-radius": 10, "circle-color": "#f0c36a", "circle-opacity": 0, "circle-stroke-color": "#f0c36a", "circle-stroke-width": 1 } });
    mapLayersReady = true;
    applyMapLayers();
  }
  function updateMapSources(s) {
    if (!map || !mapReady) return;
    addMapLayers();
    mapOverlays = (s.geo && s.geo.overlays) || mapOverlays;
    const routeFeatures = mapOverlays.routes.filter((r) => Number.isFinite(r.from_lon) && Number.isFinite(r.to_lon)).map((r) => ({
      type: "Feature", properties: { id: r.id, label: r.label, status: r.status, netback: r.netback_value, freight: r.freight_value, unit: r.unit, basis: r.price_basis },
      geometry: { type: "LineString", coordinates: [[r.from_lon, r.from_lat], [r.to_lon, r.to_lat]] } }));
    routeFeatures.sort((a, b) => Number(a.properties.id === selectedRoute) - Number(b.properties.id === selectedRoute));
    const riskFeatures = mapOverlays.chokepoints.map((c) => ({ type: "Feature", properties: { id: c.id, label: c.label, risk: c.risk, band: c.band, note: c.note },
      geometry: { type: "Point", coordinates: [c.lon, c.lat] } }));
    const terminalFeatures = ((s.geo && s.geo.nodes) || []).filter((n) => n.kind === "lng").map((n) => ({ type: "Feature", properties: { id: n.id, label: n.label },
      geometry: { type: "Point", coordinates: [n.lon, n.lat] } }));
    map.getSource("lng-routes").setData({ type: "FeatureCollection", features: routeFeatures });
    map.getSource("lng-chokepoints").setData({ type: "FeatureCollection", features: riskFeatures });
    map.getSource("lng-terminal-halos").setData({ type: "FeatureCollection", features: terminalFeatures });
    applyMapLayers();
  }
  function scheduleMapSources(s) {
    if (!mapReady) return;
    const serial = ++mapOverlaySerial;
    idle(() => { if (serial === mapOverlaySerial && mapReady) updateMapSources(s); });
  }
  function mapHoverAt(e, text) {
    if (!mapHover) return;
    mapHover.textContent = text;
    mapHover.style.display = "block";
    const w = map.getCanvas().clientWidth;
    mapHover.style.left = Math.max(8, Math.min(e.point.x + 12, w - 280)) + "px";
    mapHover.style.top = Math.max(8, e.point.y + 12) + "px";
  }
  function showRouteHover(e, f) {
    const r = mapOverlays.routes.find((x) => x.id === f.properties.id);
    if (r) mapHoverAt(e, `${r.label}\nnetback ${num(r.netback_value, 2)} ${r.unit}\nfreight ${num(r.freight_value, 2)} · ${r.price_basis}\nmodeled context, not a traded quote`);
  }
  function showRiskHover(e, f) {
    const c = mapOverlays.chokepoints.find((x) => x.id === f.properties.id);
    if (c) mapHoverAt(e, `${c.label}\nroute risk ${num(c.risk, 2)} · ${c.band}\n${c.source}\n${c.note}`);
  }
  function hideMapHover() { if (mapHover) mapHover.style.display = "none"; }
  function selectRoute(id) {
    selectedRoute = id;
    const r = mapOverlays.routes.find((x) => x.id === id);
    if (r && map && lastRouteFit !== id) {
      map.fitBounds([[r.from_lon, r.from_lat], [r.to_lon, r.to_lat]], { padding: 90, duration: 650, maxZoom: 4 });
      lastRouteFit = id;
    }
    renderMapInspector(state); scheduleMapSources(state);
  }
  function showRiskDetail(id) {
    const row = $("map-risk-" + id);
    if (!row) return;
    row.classList.add("sel"); setTimeout(() => row.classList.remove("sel"), 2400);
  }
  function fitMapOverlays() {
    if (!map) return;
    const pts = mapOverlays.routes.flatMap((r) => [[r.from_lon, r.from_lat], [r.to_lon, r.to_lat]]).concat(mapOverlays.chokepoints.map((c) => [c.lon, c.lat]));
    if (pts.length) map.fitBounds(pts.reduce((b, p) => [[Math.min(b[0][0], p[0]), Math.min(b[0][1], p[1])], [Math.max(b[1][0], p[0]), Math.max(b[1][1], p[1])]], [[180, 90], [-180, -90]]), { padding: 60, duration: 650 });
  }
  function renderMapInspector(s) {
    if (!s || !$("map-route-list")) return;
    mapOverlays = (s.geo && s.geo.overlays) || mapOverlays;
    const routes = clear($("map-route-list"));
    routes.append(el("h4", { text: "arbitrage routes · modeled M1" }));
    for (const r of mapOverlays.routes) {
      const b = el("button", { id: "map-route-" + r.id, type: "button", class: "map-route-row" + (selectedRoute === r.id ? " sel" : "") },
        [el("b", { text: r.label }), el("span", { text: `netback ${num(r.netback_value, 2)} · freight ${num(r.freight_value, 2)} USD/MMBtu` }), el("span", { text: r.price_basis })]);
      b.addEventListener("click", () => selectRoute(r.id));
      T("lng_netback", b, () => ({ title: r.label, value: `${num(r.netback_value, 2)} ${r.unit}`, badge: badgeOf("extracted_estimate"), what: r.note,
        formula: null, params: {}, read: "Modeled context at the current cutoff; not a tradeable quote.", sections: [{ h: "Route", rows: [["Origin", r.origin], ["Destination basis", r.price_basis], ["Source", r.source]] }] }), "map_route_" + r.id);
      routes.append(b);
    }
    const risks = clear($("map-risk-list"));
    risks.append(el("h4", { text: "chokepoint risk · schematic" }));
    for (const c of mapOverlays.chokepoints) {
      const b = el("button", { id: "map-risk-" + c.id, type: "button", class: "map-risk-row", "data-band": c.band },
        [el("b", { text: `${c.label} · ${c.band}` }), el("span", { text: `route risk ${num(c.risk, 2)} · ${c.source}` })]);
      T("lng_supply_risk", b, () => ({ title: c.label, value: `route risk ${num(c.risk, 2)}`, badge: badgeOf("extracted_estimate"), what: c.note,
        formula: null, params: {}, read: "A source risk score, not a measured disruption.", sections: [{ h: "Layer", rows: [["Band", c.band], ["Source", c.source]] }] }), "map_risk_" + c.id);
      risks.append(b);
    }
    const scBox = clear($("map-scenario-list"));
    for (const [id, label, title] of [[null, "none", "No shock overlay"]].concat(mapOverlays.scenarios.map((x) => [x.id, x.label, x.description]))) {
      const b = el("button", { type: "button", title, "aria-pressed": String(id === activeScenario), text: label });
      b.addEventListener("click", () => {
        activeScenario = id;
        mapLayerState.shock = !!id;
        document.querySelectorAll(".map-ctrl button[data-layer='shock']").forEach((n) => n.setAttribute("aria-pressed", String(mapLayerState.shock)));
        renderMapInspector(state); applyMapLayers();
      });
      b.dataset.layer = "shock-option"; scBox.append(b);
    }
    const sc = mapOverlays.scenarios.find((x) => x.id === activeScenario);
    $("map-overlay-note").textContent = sc ? `${sc.label}: ${sc.global_supply_loss_pct}% global supply loss · ${sc.duration_days} days · ${sc.route_cost_shock_pct}% route cost shock. ${mapOverlays.note}` : mapOverlays.note;
  }
  const nodeVal = (n, d) => (/MMcf/.test(n.unit || "") ? num(n.value, 0) : num(n.value, n.value >= 100 ? 1 : d));
  function drawMap(s) {
    if (!map || !mapReady) return;
    markers.forEach((m) => m.remove()); overlayMarkers.forEach((m) => m.remove()); markers = []; overlayMarkers = [];
    mapOverlays = (s.geo && s.geo.overlays) || mapOverlays;
    const byId = Object.fromEntries(s.geo.nodes.map((n) => [n.id, n]));
    for (const n of s.geo.nodes) {
      const ok = n.status === "measured", pos = LABEL_POS[n.id] || [1, 0];
      const lab = el("span", { class: "node-label" }, [n.label + " ", el("em", { text: `[${n.id}]` })].concat(ok ? [" ", el("b", { text: nodeVal(n, 2) })] : []));
      lab.style.left = pos[0] > 0 ? "16px" : "auto"; if (pos[0] < 0) lab.style.right = "16px"; lab.style.top = `${-7 + pos[1] * 13}px`;
      D(lab, "geo:" + n.id);
      const dot = el("div", { class: `node-wrap ${ok ? "measured" : "pend"}` },
        [el("i", { class: `node ${n.kind === "basin" ? "basin" : n.kind === "lng" ? "lng" : ""} ${ok ? "measured" : "pend"}` }), lab]);
      T(ok ? "provenance" : "pending", dot, () => ({ title: `${n.label} [${n.id}]`, value: ok ? `${nodeVal(n, 3)} ${n.unit || ""}` : "no data", badge: badgeOf(ok ? "measured" : "pending_collector"),
        what: ({ basin: "Production basin. The value is the monthly-average gas production.", lng: "LNG export terminal. The value is the latest monthly total exports published by EIA (MMcf per month), not daily feedgas.", ngl_hub: "NGL pricing hub.", gas_hub: "Natural gas pricing hub.", crude_hub: "Crude oil pricing hub." })[n.kind] || "Location on the schematic network map.",
        formula: null, params: {}, read: ok ? "Filled marker = a measured value at this location." : "Hollow marker = no collector yet for this location.",
        sections: [{ h: "Location", rows: [["Kind", n.kind], ["Observation date", n.date]] }, lineage(n.agent_id)], notes: ["Arcs between locations are schematic links, not surveyed pipeline routes."] }), "node_" + n.id);
      markers.push(new maplibregl.Marker({ element: dot }).setLngLat([n.lon, n.lat]).addTo(map));
    }
    for (const r of mapOverlays.routes) {
      const lab = el("span", { class: "node-label overlay-label", text: `${r.to} · ${num(r.netback_value, 2)}` });
      const dot = el("div", { class: "node-wrap" }, [el("i", { class: "overlay-node" }), lab]);
      T("lng_netback", dot, () => ({ title: r.label, value: `${num(r.netback_value, 2)} ${r.unit}`, badge: badgeOf("extracted_estimate"), what: r.note,
        formula: null, params: {}, read: "Modeled destination context; the route is schematic.", sections: [{ h: "Route", rows: [["Destination basis", r.price_basis], ["Freight", `${num(r.freight_value, 2)} ${r.unit}`]] }] }), "map_dest_" + r.id);
      overlayMarkers.push(new maplibregl.Marker({ element: dot }).setLngLat([r.to_lon, r.to_lat]).addTo(map));
    }
    try {
      const data = s.geo.flows.map((f) => ({ from: [byId[f.from].lon, byId[f.from].lat], to: [byId[f.to].lon, byId[f.to].lat], f }));
      const layer = new deck.ArcLayer({ id: "flows", data, getSourcePosition: (d) => d.from, getTargetPosition: (d) => d.to, getHeight: 0.35, greatCircle: false,
        getSourceColor: [255, 255, 255, 60], getTargetColor: [255, 255, 255, 190], getWidth: 1.1 });
      // Basemap linework is drawn by deck.gl too (one renderer, no geometry worker), hairline white like the reference.
      const lines = (key, alpha, width) => new deck.PathLayer({ id: "base-" + key, data: basemap ? basemap.layers[key] : [], getPath: (d) => d,
        getColor: [255, 255, 255, alpha], getWidth: width, widthUnits: "pixels", widthMinPixels: width });
      const layers = [lines("states", 70, 0.6), lines("coast_and_borders", 200, 0.9), layer];
      if (!overlay) { overlay = new deck.MapboxOverlay({ interleaved: false, layers }); map.addControl(overlay); } else overlay.setProps({ layers });
    } catch (e) { /* the map still works without the arc layer */ }
    const mt = clear($("map-tags"));
    mt.append(tag(`${s.geo.nodes.filter((n) => n.status === "measured").length}/${s.geo.nodes.length} nodes with data`, "on"), tag(`flows ${s.geo.flow_agents_collected}/${s.geo.flow_agents_total}`, "gap"),
      tag(`${mapOverlays.routes.length} modeled routes`, "gold"), tag(`${mapOverlays.chokepoints.length} chokepoints`));
    $("map-note").textContent = s.geo.note + " Filled marker = measured value at that location; hollow = no collector. Arcs fade from origin to destination. Teal diamonds are modeled global route destinations; gold arcs and red/amber/teal rings are schematic overlays."
      + ($("map-note").dataset.err ? "  [" + $("map-note").dataset.err + "]" : "");
    scheduleMapSources(s);
  }

  /* ---------- knowledge graph ---------- */
  async function loadGraph() {
    try { graph = await (await fetch("/api/knowledge-graph?limit=300")).json(); } catch (e) { graph = null; }
    drawGraph();
  }
  function drawGraph() {
    const svg = d3.select("#kg"); svg.selectAll("*").remove();
    const tg = clear($("kg-tags"));
    if (!graph || !graph.nodes.length) { tg.append(tag("empty", "gap")); return; }
    tg.append(tag(`${graph.total_nodes} objects`, "on"), tag(`${graph.links.length} edges`));
    Object.entries(graph.domains).forEach(([k, v]) => tg.append(tag(`${k} ${v}`)));
    const lg = clear($("kg-legend"));
    Object.entries(graph.edge_legend).forEach(([k, v]) => { const sp = el("span", { text: k.replace(/_/g, " ") }); lg.append(sp); T("kg_node", sp, { title: "Link type: " + k.replace(/_/g, " "), what: v, formula: null, params: {}, read: "Semantic similarity is a retrieval aid, not evidence of a real relationship." }, "edge_" + k); });
    const w = $("kg").clientWidth || 800, h = $("kg").clientHeight || 480;
    const nodes = graph.nodes.map((n) => ({ ...n })), ids = new Set(nodes.map((n) => n.id));
    const links = graph.links.filter((l) => ids.has(l.source) && ids.has(l.target)).map((l) => ({ ...l }));
    const deg = {}; links.forEach((l) => { deg[l.source] = (deg[l.source] || 0) + 1; deg[l.target] = (deg[l.target] || 0) + 1; });
    const sim = d3.forceSimulation(nodes).force("link", d3.forceLink(links).id((d) => d.id).distance((l) => (l.type === "semantic_neighbor" ? 90 : 42)).strength((l) => (l.type === "semantic_neighbor" ? 0.05 : 0.5)))
      .force("charge", d3.forceManyBody().strength(-70)).force("x", d3.forceX(w / 2).strength(0.05)).force("y", d3.forceY(h / 2).strength(0.08)).stop();
    for (let i = 0; i < 260; i++) sim.tick();
    const cx = (d) => Math.max(8, Math.min(w - 8, d.x)), cy = (d) => Math.max(8, Math.min(h - 8, d.y));
    svg.attr("viewBox", `0 0 ${w} ${h}`);
    svg.append("g").selectAll("line").data(links).join("line").attr("class", (d) => "kg-edge " + d.type)
      .attr("x1", (d) => cx(d.source)).attr("y1", (d) => cy(d.source)).attr("x2", (d) => cx(d.target)).attr("y2", (d) => cy(d.target));
    svg.append("g").selectAll("circle").data(nodes).join("circle").attr("class", "kg-node").attr("r", (d) => 3 + Math.min(5, Math.sqrt(deg[d.id] || 0)))
      .attr("cx", cx).attr("cy", cy).on("click", (_, d) => selectNode(d.id)).on("keydown", (ev, d) => { if (ev.key === "Enter") selectNode(d.id); })
      .each(function (d) {
        T("kg_node", this, () => ({ title: d.title, value: d.domain.replace(/_/g, " "), badge: badgeOf(d.provenance), what: (d.document || "").slice(0, 260) + ((d.document || "").length > 260 ? "…" : ""), formula: null, params: {}, read: "Click to open the full object and its links.",
          sections: [{ h: "Where it came from", rows: [["Available (PIT)", fts(d.available_timestamp)], ["Published", fts(d.published_timestamp)], ["Source", d.source_id], ["Agents", (d.agent_ids || "").split(",").filter(Boolean).map(short).join(", ")], ["Raw payload", d.raw_payload_hash ? d.raw_payload_hash.slice(0, 16) + "…" : null, "hash"], ["Object id", d.id, "hash"]] }] }), "kg_" + d.id, { pin: false });
      });
    markGraph();
  }
  function markGraph() {
    d3.selectAll(".kg-node").classed("sel", (d) => d.id === kgSel).classed("hit", (d) => kgHits.has(d.id));
    d3.selectAll(".kg-edge").classed("sel", (d) => kgSel && (d.source.id === kgSel || d.target.id === kgSel));
  }
  function selectNode(id) {
    const n = graph && graph.nodes.find((x) => x.id === id); if (!n) return;
    kgSel = id; markGraph();
    const box = clear($("kg-detail"));
    box.append(el("h3", { text: n.title }), el("div", { text: n.document }));
    const dl = el("dl");
    const add = (k, v) => { dl.append(el("dt", { text: k }), el("dd", { text: v || "—" })); };
    add("id", n.id); add("domain", n.domain); add("provenance", n.provenance); add("available", n.available_timestamp); add("published", n.published_timestamp);
    add("source", n.source_id); add("agents", (n.agent_ids || "").split(",").map(short).join(", ")); add("raw payload", n.raw_payload_hash);
    box.append(dl);
    const rel = graph.links.filter((l) => l.source === id || l.target === id);
    if (rel.length) box.append(el("h3", { text: `Linked (${rel.length})` }));
    for (const l of rel) {
      const other = graph.nodes.find((x) => x.id === (l.source === id ? l.target : l.source)); if (!other) continue;
      const row = el("div", { class: "hit", text: `${l.source === id ? "→" : "←"} ${l.type.replace(/_/g, " ")}${l.weight ? " " + l.weight : ""} · ${other.title}` });
      row.addEventListener("click", () => selectNode(other.id)); box.append(row);
    }
  }
  async function search(ev) {
    ev.preventDefault();
    const q = $("kg-q").value.trim(); if (q.length < 2) return;
    const box = clear($("kg-detail")); box.append(el("div", { text: "Searching…" }));
    let r;
    try {
      const resp = await fetch("/api/knowledge-search", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query: q, limit: 10 }) });
      r = await resp.json(); if (!resp.ok) throw new Error(r.detail || "search failed");
    } catch (e) { clear(box).append(el("div", { text: "Search unavailable: " + e.message })); return; }
    kgHits = new Set(r.results.map((x) => x.id)); markGraph();
    clear(box).append(el("h3", { text: `${r.results.length} results for “${r.query}” as of ${r.as_of}` }), el("div", { class: "dim", text: r.note }));
    for (const x of r.results) {
      const row = el("div", { class: "hit" }, [el("div", { text: `${x.similarity.toFixed(3)} · ${x.domain} · ${x.title}` }), el("div", { class: "dim", text: `available ${x.available_timestamp} · ${x.provenance}` })]);
      row.addEventListener("click", () => selectNode(x.id)); box.append(row);
    }
  }

  /* ---------- controls and refresh ---------- */
  function renderControls(s) {
    const mk = (box, items, cur, key) => {
      clear(box);
      for (const it of items) {
        const b = el("button", { type: "button", "aria-pressed": String(it.id === cur), class: it.status === PENDING ? "pending" : "", text: it.code || it.label });
        b.addEventListener("click", () => { sel[key] = it.id; load(); });
        box.append(b);
        if (key === "timeframe") T("timeframe", b, { title: it.label, value: `${it.sessions} sessions`, what: it.note + "." }, "btn_tf_" + it.id);
        else T(it.status === PENDING ? "pending" : "price", b, () => ({ title: it.label, value: it.status === PENDING ? "pending collector" : `${num(it.latest, dec(it.unit))} ${it.unit}`, badge: badgeOf(it.status === PENDING ? "pending_collector" : "measured"),
          what: it.status === PENDING ? X("pending").what : "Click to chart this product.", formula: null, params: {}, read: null, sections: [lineage(it.agent_id)] }), "btn_prod_" + it.id);
      }
    };
    mk($("product-seg"), s.products, s.active_product, "product"); mk($("timeframe-seg"), s.timeframes, s.timeframe.id, "timeframe");
  }
  function render(s) {
    state = s;
    const keep = NGLTip.reset();
    $("asof").textContent = `as of ${s.as_of.replace("T", " ")} · ${s.schema}`;
    renderControls(s); renderHero(s); renderPricing(s); renderFib(s); renderAlerts(s); renderCurves(s); renderLng(s); renderLngGlobal(s); renderFundamentals(s); renderDrivers(s); renderSources(s);
    initMap(s); renderMapInspector(s); drawMap(s);
    if (graph) drawGraph();
    NGLTip.restore(keep);
    const p = s.platform, k = s.knowledge;
    $("foot-stats").textContent = `${p.agents_with_data} agents with data · ${num(p.pit_rows, 0)} point-in-time rows · ${k.nodes || 0} knowledge objects`;
  }
  async function load() {
    const u = new URLSearchParams(); if (sel.product) u.set("product", sel.product); u.set("timeframe", sel.timeframe);
    const keepTip = qs.get("tip");
    history.replaceState(null, "", "?" + u.toString() + (keepTip ? "&tip=" + encodeURIComponent(keepTip) : ""));
    try {
      const r = await fetch("/api/state.json?" + u.toString()); if (!r.ok) throw new Error("HTTP " + r.status);
      const s = await r.json(); sel.product = s.active_product; render(s);
    } catch (e) { $("asof").textContent = "state unavailable: " + e.message; }
  }
  $("host-title").textContent = (location.hostname || "ngl.joeysvault.app").toUpperCase();
  $("src-all").addEventListener("change", () => state && renderSources(state));
  $("kg-form").addEventListener("submit", search);
  let rt; window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => { if (state) { renderHero(state); renderCurves(state); renderLng(state); } drawGraph(); }, 200); });
  /* ---------- command and chat bar ---------- */
  const QUICK = ["How is the forward curve built?", "Why is Freeport flow unverified?", "How does the ethane frac spread affect Henry Hub?", "What is Corpus Christi feedgas right now?"];
  async function focusNode(id) {                                     // cite-to-highlight: select the node in the knowledge library, pulse it and bring it into view
    if (!graph || !graph.nodes.find((n) => n.id === id)) { try { graph = await (await fetch("/api/knowledge-graph?limit=600")).json(); drawGraph(); } catch (e) { return; } }
    kgHits = new Set([id]); selectNode(id); markGraph();
    const c = d3.selectAll(".kg-node").filter((d) => d.id === id).node();
    $("kg-h").scrollIntoView({ behavior: "smooth", block: "start" });
    if (c) { c.classList.add("pulse"); setTimeout(() => c.classList.remove("pulse"), 3200); }
  }
  function initChat() {
    const bar = $("chatbar"), ans = $("chat-answer"), q = $("chat-q");
    const open = (v) => { bar.dataset.open = v ? "true" : "false"; $("chat-toggle").setAttribute("aria-expanded", String(v)); $("chat-toggle").innerHTML = v ? "&#9652;" : "&#9662;"; };
    $("chat-toggle").addEventListener("click", () => open(bar.dataset.open !== "true"));
    QUICK.forEach((t) => { const b = el("button", { type: "button", text: t }); b.addEventListener("click", () => { q.value = t; ask(t); }); $("chat-chips").append(b); });
    $("chat-form").addEventListener("submit", (ev) => { ev.preventDefault(); if (q.value.trim().length > 1) ask(q.value.trim()); });
    window.addEventListener("ngl-ask", (ev) => { const d = ev.detail || {}; q.value = `Explain "${d.title}": how is it calculated, where does the data come from, and what is its collector status?`; ask(q.value, { metric: d.metric, agent: d.agent }); });
    let cites = { nodes: [], docs: [] };
    function renderAnswer(text, base) {                              // [F#] [N#] [D#] tags in the text become buttons
      clear(ans).classList.toggle("baseline", !!base);
      for (const part of text.split(/(\[[FND]\d+\])/)) {
        const m = /^\[([FND])(\d+)\]$/.exec(part);
        if (!m) { ans.append(part); continue; }
        const i = Number(m[2]) - 1, b = el("button", { type: "button", class: "cite", text: part });
        if (m[1] === "N" && cites.nodes[i]) b.addEventListener("click", () => focusNode(cites.nodes[i].id));
        else if (m[1] === "F") b.addEventListener("click", () => { const f = $("fact-" + m[2]); if (f) { f.classList.add("flash"); f.scrollIntoView({ block: "nearest" }); setTimeout(() => f.classList.remove("flash"), 1500); } });
        else if (m[1] === "D" && cites.docs[i]) b.title = `${cites.docs[i].title} · ${cites.docs[i].path || ""}`;
        ans.append(b);
      }
    }
    function renderCites(c) {
      cites = { nodes: c.cited_nodes || [], docs: c.cited_documents || [] };
      const nb = clear($("chat-nodes")), db = clear($("chat-docs"));
      cites.nodes.slice(0, 12).forEach((n, i) => { const b = el("button", { type: "button", class: "chat-node-btn" }, [el("span", { text: `N${i + 1} ${n.title.slice(0, 46)}` }), el("span", { class: "role", text: `${(n.domain_role || "").replace(/_/g, " ")}${n.hop ? " · hop " + n.hop : ""}` })]);
        b.addEventListener("click", () => focusNode(n.id)); nb.append(b); });
      if (!cites.nodes.length) nb.append(el("div", { class: "dim", text: "none retrieved at this cutoff" }));
      cites.docs.slice(0, 6).forEach((d, i) => db.append(el("div", { class: "chat-doc" }, [el("b", { text: `D${i + 1} ${d.title}` }), el("div", { text: `${d.path || ""} · ${(d.domain_role || "").replace(/_/g, " ")}${d.alignment ? " · " + d.alignment : ""} · sim ${d.similarity}` }), el("div", { text: "“" + d.snippet.slice(0, 140) + "…”" })])));
      if (!cites.docs.length) db.append(el("div", { class: "dim", text: "no document cleared the similarity threshold at this cutoff" }));
    }
    function renderFacts(facts) {
      const box = clear($("chat-facts")), det = el("details", {}, [el("summary", { text: `${facts.length} grounding facts from live telemetry` })]);
      facts.forEach((f) => det.append(el("div", { id: "fact-" + f.id.slice(1), text: `[${f.id}] ${f.text}` })));
      box.append(det);
    }
    async function ask(text, context) {
      open(true); clear(ans); clear($("chat-facts")); clear($("chat-nodes")); clear($("chat-docs"));
      $("chat-meta").textContent = "asking…"; const t0 = performance.now(); let streamed = "", baseline = "";
      let resp;
      try { resp = await fetch("/api/chat/stream", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message: text, as_of: state && state.as_of, context: context || null }) }); }
      catch (e) { ans.textContent = "chat unavailable (network)"; return; }
      if (!resp.ok) { ans.textContent = resp.status === 429 ? "Rate limit reached; try again in a minute." : `chat unavailable (${resp.status})`; return; }
      const reader = resp.body.getReader(), dec = new TextDecoder(); let buf = "";
      const handle = (raw) => {
        const ev = /^event: (\w+)/m.exec(raw), dt = /^data: (.*)$/m.exec(raw); if (!ev || !dt) return;
        const d = JSON.parse(dt[1]);
        if (ev[1] === "status") $("chat-meta").textContent = `cutoff ${d.cutoff} · retrieving…`;
        else if (ev[1] === "context") {
          if (d.facts) renderFacts(d.facts);
          if (d.baseline_answer) { baseline = d.baseline_answer; if (!streamed) renderAnswer(baseline, true); }
          if (d.cited_nodes) renderCites(d);
        } else if (ev[1] === "token") { streamed += d.t; renderAnswer(streamed, false); }
        else if (ev[1] === "final") {
          renderCites(d); renderAnswer(d.answer, d.verdict !== "model answer grounded");
          $("chat-meta").textContent = `cutoff ${d.cutoff} · ${d.intent} · ${d.verdict}${d.model ? " · " + d.model : ""} · first event ${d.first_event_ms} ms · total ${d.total_ms} ms · client ${Math.round(performance.now() - t0)} ms`;
        }
      };
      for (;;) { const { value, done } = await reader.read(); if (done) break; buf += dec.decode(value, { stream: true }); let i; while ((i = buf.indexOf("\n\n")) >= 0) { handle(buf.slice(0, i)); buf = buf.slice(i + 2); } }
    }
  }
  if (window.NGLDrill) window.NGLDrill.setContext(() => ({ product: state && state.active_product, timeframe: state && state.timeframe && state.timeframe.id, as_of: state && state.as_of }));
  initChat();
  load(); loadGraph(); setInterval(load, 60000); setInterval(loadGraph, 300000);
})();
