/* NGL visual intelligence front end. Renders /api/state.json (the same document ngl-term.py renders).
   Nothing here computes market numbers: it only draws what the read-only service returns. Text from the API is
   always inserted with textContent, never as HTML. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const PENDING = "pending_collector";
  const qs = new URLSearchParams(location.search);
  const sel = { product: qs.get("product"), timeframe: qs.get("timeframe") || "seasonal" };
  let state = null, map = null, mapReady = false, basemap = null, overlay = null, markers = [], graph = null, kgSel = null, kgHits = new Set();

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
      if (l.label) svg.append("text").attr("class", "hl-label " + (l.cls || "")).attr("x", m.l + 3).attr("y", ys(l.y) - 3).text(l.label);
    });
    (c.lines || []).forEach((l) => {
      const line = d3.line().defined((d) => def(d)).x((d, i) => xs(i)).y((d) => ys(d));
      svg.append("path").attr("class", "ln " + (l.cls || "")).attr("d", line(l.y));
    });
    (c.markers || []).forEach((k) => {
      if (k.i < 0 || !def(k.y)) return;
      svg.append("circle").attr("class", "mk " + (k.cls || "")).attr("cx", xs(k.i)).attr("cy", ys(k.y)).attr("r", k.r || 3.5).append("title").text(k.title || "");
    });
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
    tags.append(tag(s.timeframe.label, "on"));
    if (s.price.status !== "measured") {
      tags.append(tag("pending collector", "gap"));
      for (const id of ["price-chart", "seasonal-chart"]) pending($(id), "PENDING COLLECTOR", [s.price.note || "", "Agent: " + p.agent_id]);
      for (const id of ["rsi-chart", "macd-chart", "levels"]) clear($(id));
      return;
    }
    tags.append(tag("measured", "on"));
    const sm = t.summary;
    if (sm.bollinger_squeeze) tags.append(tag("Bollinger squeeze", "gold"));
    if (sm.triangle !== "none") tags.append(tag(sm.triangle.replace(/_/g, " "), "gold"));
    if (sm.divergence_rsi !== "none") tags.append(tag(sm.divergence_rsi + " RSI divergence", "gold"));
    if (sm.divergence_macd !== "none") tags.append(tag(sm.divergence_macd + " MACD divergence", "gold"));
    const x = s.series.dates, n = x.length, fmt = dateFmt(n);
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
      hl.push({ y: fib.levels[k], label: `${k}  ${num(fib.levels[k], d)}`, cls: ["38.2%", "50.0%", "61.8%"].includes(k) ? "gold" : "", fit: false });
    }
    const sq = t.bollinger.squeeze;
    chart($("price-chart"), {
      x, xFmt: fmt, lines, hlines: hl,
      areas: [{ y0: t.bollinger.lower, y1: t.bollinger.upper }, { y0: t.bollinger.lower.map((v, i) => (sq[i] ? v : null)), y1: t.bollinger.upper.map((v, i) => (sq[i] ? v : null)), cls: "sq" }],
      markers: t.crossovers.map((c) => ({ i: x.indexOf(c.date), y: c.price, cls: "gold", title: `${c.type.replace("_", " ")} ${c.date}` }))
        .concat([{ i: n - 1, y: s.series.values[n - 1], r: 3, title: `last ${s.price.date}` }]),
    });
    legend($("price-chart"), [["", "price"], ["dash", "50-day"], ["dot", "200-day"], ["dim", "Bollinger 20, 2σ"], ["gold dash", "triangle / Fibonacci"]]);
    chart($("rsi-chart"), { x, xFmt: () => "", lines: [{ y: t.rsi14 }], yDomain: [0, 100], yTicks: 3, hlines: [{ y: 70, label: "70" }, { y: 30, label: "30" }] });
    chart($("macd-chart"), { x, xFmt: fmt, bars: { y: t.macd.hist }, lines: [{ y: t.macd.signal, cls: "dash thin" }, { y: t.macd.line }], yTicks: 3 });
    const se = s.seasonal, g = se.day_of_year;
    $("seasonal-cap").textContent = `Seasonal overlay — ${se.history_years.length}-year band (${se.history_years[0] || "?"}–${se.history_years[se.history_years.length - 1] || "?"}) vs ${se.current_year}`;
    chart($("seasonal-chart"), {
      x: g, xTicks: [0, 13, 26, 39, g.length - 1], xFmt: (v) => MONTHS[Math.min(11, Math.floor(((v - 1) / 365) * 12))],
      areas: [{ y0: se.band_min, y1: se.band_max }],
      lines: Object.values(se.lines).map((y) => ({ y, cls: "thin" })).concat([{ y: se.band_avg, cls: "dash" }, { y: se.current, cls: "gold bold" }]),
    });
    legend($("seasonal-chart"), [["gold", String(se.current_year)], ["dash", "average"], ["dim", "prior years"]]);
    const lv = clear($("levels"));
    const cell = (k, v, gold) => lv.append(el("div", { class: gold ? "gold" : "" }, [el("span", { text: k }), v]));
    cell("Last", `${num(sm.last, d)} ${u}`); cell("50-day avg", num(sm.sma50, d)); cell("200-day avg", num(sm.sma200, d));
    cell("Trend", sm.trend.replace(/_/g, " ")); cell("50/200 regime", sm.ma_regime === "golden" ? "golden cross" : sm.ma_regime === "death" ? "death cross" : sm.ma_regime.replace(/_/g, " "));
    cell("RSI (14)", num(sm.rsi14, 1)); cell("MACD hist", signed(sm.macd_hist, 3)); cell("Bandwidth", num(sm.bandwidth_pct, 1) + "%" + (sm.bollinger_squeeze ? " squeeze" : ""), sm.bollinger_squeeze);
    cell("Triangle", sm.triangle.replace(/_/g, " "), sm.triangle !== "none");
    if (tri.pattern !== "none") { cell("Breakout above", num(tri.breakout_above, d), true); cell("Breakdown below", num(tri.breakdown_below, d), true); }
    cell("RSI divergence", sm.divergence_rsi, sm.divergence_rsi !== "none"); cell("MACD divergence", sm.divergence_macd, sm.divergence_macd !== "none");
    if (fib.status === "ok") { cell("Swing high", `${num(fib.swing_high, d)} · ${fib.swing_high_date}`); cell("Swing low", `${num(fib.swing_low, d)} · ${fib.swing_low_date}`); }
  }

  /* ---------- right-hand stack ---------- */
  function renderPricing(s) {
    const box = clear($("pricing"));
    const tb = el("tbody");
    for (const p of s.products) {
      tb.append(el("tr", { class: p.id === s.active_product ? "active" : "" }, [
        el("td", { text: `${p.label.replace("Mont Belvieu ", "")}` }),
        el("td", { class: "num" + (p.status === PENDING ? " dim" : ""), text: p.status === PENDING ? "pending" : `${num(p.latest, dec(p.unit))} ${p.unit === "cents/gal" ? "¢/gal" : "$/MMBtu"}` }),
        el("td", { class: "num dim", text: p.pct_of_wti == null ? "—" : num(p.pct_of_wti, 1) + "%" }),
      ]));
    }
    const w = s.curves.ngl_to_wti_pct.wti;
    tb.append(el("tr", {}, [el("td", { text: "WTI crude (Cushing)" }), el("td", { class: "num", text: w.value == null ? "pending" : `${num(w.value, 2)} $/bbl` }), el("td", { class: "num dim", text: "100%" })]));
    box.append(el("table", {}, [el("thead", {}, el("tr", {}, [el("th", { text: "Product" }), el("th", { class: "num", text: "Price" }), el("th", { class: "num", text: "% WTI" })])), tb]));
    const pr = s.price, c = s.curves, kv = el("div", { class: "kv", style: "padding:6px 10px 6px;margin:0;border:0" });
    const add = (k, v) => kv.append(el("span", { text: k }), el("span", { text: v }));
    if (pr.status === "measured") { add("1-day change", `${signed(pr.change_1d, dec(pr.unit))} (${signed(pr.change_1d_pct, 2)}%)`); add("5-day change", `${signed(pr.change_5d, dec(pr.unit))} (${signed(pr.change_5d_pct, 2)}%)`); add("Price date", pr.date); }
    add("Frac spread", c.frac_spread.status === "measured" ? `${signed(c.frac_spread.frac_spread_usd_mmbtu.at(-1), 2)} $/MMBtu · ${c.frac_spread.regime}` : "pending (ethane)");
    add("Mont Belvieu − Conway", c.hub_spread.status === "measured" ? `${signed(c.hub_spread.spread_mb_minus_conway.at(-1), 2)} ¢/gal` : "pending (Conway)");
    add("Forward curve", c.forward_curve.status === "measured" ? `${c.forward_curve.regime}${c.forward_curve.stale ? " · as of " + c.forward_curve.as_of_date : ""}` : "pending");
    box.append(kv);
  }
  function renderFib(s) {
    const box = clear($("fib")), f = s.technicals.fibonacci;
    if (!f || f.status !== "ok") return pending(box, "PENDING COLLECTOR", ["No series for the active product."]);
    const d = dec(s.price.unit), bar = el("div", { class: "fib-bar" });
    bar.append(el("div", { class: "zone", style: "left:50%;width:11.8%" }));
    for (const r of [0, 23.6, 38.2, 50, 61.8, 78.6, 100]) {
      bar.append(el("div", { class: "seg-line", style: `left:${r}%` }), el("div", { class: "lab" + ([38.2, 50, 61.8].includes(r) ? " gold" : ""), style: `left:${r}%`, text: r.toFixed(1) + "%" }));
    }
    const pos = Math.max(0, Math.min(100, f.retracement_pct ?? 0));
    bar.append(el("div", { class: "px", style: `left:${pos}%`, "data-v": num(f.last, d) }));
    box.append(bar, el("div", { class: "fib-foot" }, [
      el("span", { class: "gold", text: `Golden ratio proximity: ${num(f.golden_ratio_distance_pct_of_range, 1)}% of range from 61.8%` }),
      el("span", { text: `${f.leg}-leg · retraced ${num(f.retracement_pct, 1)}% · nearest ${f.nearest_level}` }),
    ]));
  }
  function renderAlerts(s) {
    const box = clear($("alerts")), dv = s.derived, kv = el("div", { class: "kv" });
    const add = (k, v) => kv.append(el("span", { text: k }), el("span", { text: v }));
    add("Shale gas, six basins", dv.shale_production_total_bcfd.value == null ? "pending" : num(dv.shale_production_total_bcfd.value, 1) + " Bcf/d");
    add("Working gas in storage", dv.storage_total_bcf.value == null ? "pending" : `${num(dv.storage_total_bcf.value, 0)} Bcf · ${dv.storage_total_bcf.date}`);
    add("HDD vs 30-yr normal", dv.hdd_anomaly.value == null ? "pending" : `${signed(dv.hdd_anomaly.value, 1)} · ${dv.hdd_anomaly.date}`);
    add("Live flow feeds", `${s.geo.flow_agents_collected} of ${s.geo.flow_agents_total}`);
    box.append(kv);
    for (const a of s.alerts) box.append(el("div", { class: "alert " + a.level }, [el("span", { class: "lv", text: a.level }), el("span", { text: a.text })]));
  }

  /* ---------- relative-value curves ---------- */
  function renderCurves(s) {
    const c = s.curves, w = c.ngl_to_wti_pct, names = { propane: "propane", normal_butane: "n-butane", natural_gasoline: "nat. gasoline" };
    const have = Object.keys(names).filter((k) => w[k].status === "measured"), miss = Object.keys(names).filter((k) => w[k].status !== "measured");
    if (!have.length) pending($("wti-chart"), "PENDING COLLECTOR", ["No NGL price series yet."]);
    else {
      const x = w[have[0]].dates, cls = ["bold", "dash", "dot"];
      chart($("wti-chart"), { x, xFmt: dateFmt(x.length), lines: have.map((k, i) => ({ y: w[k].pct_of_wti, cls: cls[i] })), yFmt: (v) => v + "%" });
      legend($("wti-chart"), have.map((k, i) => [i === 0 ? "" : cls[i], `${names[k]} ${num(w[k].latest, 1)}%`]).concat(miss.length ? [["dim", "pending: " + miss.map((k) => names[k]).join(", ")]] : []));
    }
    const h = c.hub_spread;
    if (h.status !== "measured") pending($("hub-chart"), "PENDING COLLECTOR", [h.note, "Mont Belvieu propane: " + num(h.mont_belvieu_latest, 1) + " ¢/gal", "Missing: " + h.missing.join(", ")]);
    else { chart($("hub-chart"), { x: h.dates, xFmt: dateFmt(h.dates.length), lines: [{ y: h.mont_belvieu, cls: "bold" }, { y: h.conway, cls: "dash" }], bars: { y: h.spread_mb_minus_conway } }); legend($("hub-chart"), [["", "Mont Belvieu"], ["dash", "Conway"], ["dim", "spread (bars)"]]); }
    const f = c.frac_spread;
    if (f.status !== "measured") pending($("frac-chart"), "PENDING COLLECTOR", [f.note, "Henry Hub: " + num(f.henry_hub_latest, 3) + " $/MMBtu", "Missing: " + f.missing.join(", ")]);
    else { chart($("frac-chart"), { x: f.dates, xFmt: dateFmt(f.dates.length), lines: [{ y: f.ethane_usd_mmbtu, cls: "bold" }, { y: f.henry_hub_usd_mmbtu, cls: "dash" }], bars: { y: f.frac_spread_usd_mmbtu }, hlines: [{ y: 0, label: "recovery above · rejection below", cls: "gold" }] }); legend($("frac-chart"), [["", "ethane $/MMBtu"], ["dash", "Henry Hub"], ["dim", "frac spread (bars)"]]); }
    const fw = c.forward_curve, ft = clear($("fwd-tags"));
    if (fw.status !== "measured") pending($("fwd-chart"), "PENDING COLLECTOR", ["No futures contracts collected."]);
    else {
      ft.append(tag(fw.regime, fw.stale ? "" : "on")); if (fw.stale) ft.append(tag("stale · " + fw.as_of_date, "gap"));
      const pts = fw.points;
      chart($("fwd-chart"), { x: pts.map((p) => p.contract), xTicks: pts.map((_, i) => i), xFmt: (v) => v, lines: [{ y: pts.map((p) => p.value), cls: "bold" }], markers: pts.map((p, i) => ({ i, y: p.value, title: `${p.contract} ${p.value} (${p.date})` })) });
      below($("fwd-chart"), el("div", { class: "legend-row" }, [el("span", { text: fw.note || `${pts.length} contracts` })]));
    }
  }

  /* ---------- drivers and sources ---------- */
  function renderDrivers(s) {
    const box = clear($("drivers"));
    for (const g of s.drivers) {
      const units = new Set(g.items.filter((i) => i.value != null).map((i) => i.unit)), max = d3.max(g.items, (i) => (i.value != null ? Math.abs(i.value) : 0)) || 1;
      const card = el("div", { class: "drv" }, el("h3", { text: g.label }));
      for (const i of g.items) {
        const pend = i.value == null;
        card.append(el("div", { class: "drv-row" + (pend ? " pend" : ""), title: pend ? "no collector yet" : `${i.agent_id} · target ${i.target_date} · available ${i.available_timestamp} · ${i.provenance}` }, [
          el("span", { class: "nm", text: short(i.agent_id) }),
          el("span", { class: "bar-wrap" }, pend || units.size !== 1 ? null : el("i", { style: `width:${Math.max(2, (Math.abs(i.value) / max) * 100)}%` })),
          el("span", { class: "val", text: pend ? "pending" : `${num(i.value, Math.abs(i.value) >= 100 ? 0 : 2)}` }),
        ]));
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
      tb.append(el("tr", {}, [
        el("td", { text: short(r.agent_id) }), el("td", {}, el("span", { class: "st " + st, text: st.replace("_", " ") })),
        el("td", {}, el("span", { class: "st " + pv, text: pv === "none" ? "no data" : pv.replace(/_/g, " ") })),
        el("td", { class: "dim", text: r.source_id || "—" }), el("td", { text: r.latest_target_timestamp ? r.latest_target_timestamp.slice(0, 10) : "—" }),
        el("td", { text: ts(r.available_timestamp) }), el("td", { class: "dim", text: ts(r.retrieved_timestamp) }), el("td", { class: "dim", text: (r.quality_status || "—").replace(/_/g, " ") }),
        el("td", { class: "hash" + (r.raw_payload_archived ? " ok" : ""), title: r.raw_payload_hash || "", text: r.raw_payload_hash ? r.raw_payload_hash.slice(0, 12) + "…" : "—" }),
      ]));
    }
    const p = s.platform, tg = clear($("src-tags"));
    tg.append(tag(`${p.roster_agents_collected}/${p.roster_agents} roster agents`, "on"), tag(`${num(p.pit_rows, 0)} PIT rows`), tag(`${p.raw_payloads} raw payloads`));
    const lg = clear($("src-legend"));
    for (const [k, v] of Object.entries(p.provenance_legend)) lg.append(el("span", { title: v }, [el("span", { class: "st " + k, text: k.replace(/_/g, " ") })]));
    lg.append(el("span", { class: "hash ok", text: "payload archived" }));
  }

  /* ---------- map ---------- */
  const LABEL_POS = { MBV: [-1, -1], HHB: [1, -1], SAB: [1, 1], CAM: [1, -2.2], CCP: [-1, 1.2], FPT: [-1, 1], CRP: [-1, 0], PLQ: [1, 0], CSH: [1, 0], CNW: [-1, -1], HYN: [1, -1], PRM: [-1, -1], EGF: [-1, -1], APP: [1, 0], CVP: [1, 0], ELB: [1, 0], BKN: [1, 0], DJB: [-1, 0] };
  function initMap(s) {
    if (map || !window.maplibregl) return;
    try {
      map = new maplibregl.Map({ container: "map", attributionControl: false, dragRotate: false, pitchWithRotate: false, renderWorldCopies: false,
        style: { version: 8, sources: {}, layers: [{ id: "bg", type: "background", paint: { "background-color": "#000" } }] },
        bounds: [[-108, 24.5], [-73, 45.5]], maxBounds: [[-140, 10], [-50, 62]], minZoom: 2.5, maxZoom: 8 });
    } catch (e) { pending($("map"), "MAP UNAVAILABLE", ["WebGL is required to draw the map."]); return; }
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.on("error", (e) => { $("map-note").dataset.err = "map error: " + ((e && e.error && e.error.message) || "unknown"); });
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
  function drawMap(s) {
    if (!map || !mapReady) return;
    markers.forEach((m) => m.remove()); markers = [];
    const byId = Object.fromEntries(s.geo.nodes.map((n) => [n.id, n]));
    for (const n of s.geo.nodes) {
      const ok = n.status === "measured", pos = LABEL_POS[n.id] || [1, 0];
      const lab = el("span", { class: "node-label" }, [n.label + " ", el("em", { text: `[${n.id}]` })].concat(ok ? [" ", el("b", { text: `${num(n.value, n.value >= 100 ? 1 : 2)}` })] : []));
      lab.style.left = pos[0] > 0 ? "16px" : "auto"; if (pos[0] < 0) lab.style.right = "16px"; lab.style.top = `${-7 + pos[1] * 13}px`;
      const dot = el("div", { class: `node-wrap ${ok ? "measured" : "pend"}`,
        title: ok ? `${n.label}: ${n.value} ${n.unit} (${n.date}) — ${n.agent_id}` : `${n.label}: no collector yet (${n.agent_id})` },
        [el("i", { class: `node ${n.kind === "basin" ? "basin" : n.kind === "lng" ? "lng" : ""} ${ok ? "measured" : "pend"}` }), lab]);
      markers.push(new maplibregl.Marker({ element: dot }).setLngLat([n.lon, n.lat]).addTo(map));
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
    mt.append(tag(`${s.geo.nodes.filter((n) => n.status === "measured").length}/${s.geo.nodes.length} nodes with data`, "on"), tag(`flows ${s.geo.flow_agents_collected}/${s.geo.flow_agents_total}`, "gap"));
    $("map-note").textContent = s.geo.note + " Filled marker = measured value at that location; hollow = no collector. Arcs fade from origin to destination."
      + ($("map-note").dataset.err ? "  [" + $("map-note").dataset.err + "]" : "");
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
    Object.entries(graph.edge_legend).forEach(([k, v]) => lg.append(el("span", { title: v, text: k.replace(/_/g, " ") })));
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
      .attr("cx", cx).attr("cy", cy).attr("tabindex", 0).on("click", (_, d) => selectNode(d.id)).on("keydown", (ev, d) => { if (ev.key === "Enter") selectNode(d.id); })
      .append("title").text((d) => `${d.domain} · ${d.title}`);
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
        const b = el("button", { type: "button", "aria-pressed": String(it.id === cur), class: it.status === PENDING ? "pending" : "", title: it.status === PENDING ? "no collector yet" : it.note || it.label, text: it.code || it.label });
        b.addEventListener("click", () => { sel[key] = it.id; load(); });
        box.append(b);
      }
    };
    mk($("product-seg"), s.products, s.active_product, "product"); mk($("timeframe-seg"), s.timeframes, s.timeframe.id, "timeframe");
  }
  function render(s) {
    state = s;
    $("asof").textContent = `as of ${s.as_of.replace("T", " ")} · ${s.schema}`;
    renderControls(s); renderHero(s); renderPricing(s); renderFib(s); renderAlerts(s); renderCurves(s); renderDrivers(s); renderSources(s);
    initMap(s); drawMap(s);
    const p = s.platform, k = s.knowledge;
    $("foot-stats").textContent = `${p.agents_with_data} agents with data · ${num(p.pit_rows, 0)} point-in-time rows · ${k.nodes || 0} knowledge objects`;
  }
  async function load() {
    const u = new URLSearchParams(); if (sel.product) u.set("product", sel.product); u.set("timeframe", sel.timeframe);
    history.replaceState(null, "", "?" + u.toString());
    try {
      const r = await fetch("/api/state.json?" + u.toString()); if (!r.ok) throw new Error("HTTP " + r.status);
      const s = await r.json(); sel.product = s.active_product; render(s);
    } catch (e) { $("asof").textContent = "state unavailable: " + e.message; }
  }
  $("host-title").textContent = (location.hostname || "ngl.joeysvault.app").toUpperCase();
  $("src-all").addEventListener("change", () => state && renderSources(state));
  $("kg-form").addEventListener("submit", search);
  let rt; window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => { if (state) { renderHero(state); renderCurves(state); } drawGraph(); }, 200); });
  load(); loadGraph(); setInterval(load, 60000); setInterval(loadGraph, 300000);
})();
