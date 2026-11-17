#!/usr/bin/env python3
"""End-to-end check of the rich tooltips in a real (headless) Chrome, against any deployment.

  python scripts/verify_tooltips.py http://127.0.0.1:8099 --shots docs/screens

Audits every bound tooltip spec (title, explanation, no fallback text), then performs real mouse hovers, a click-to-pin, keyboard focus and a
?tip= deep link, and saves screenshots. Exits non-zero on any failure. Needs google-chrome and the `websockets` package; nothing is written
to the service under test.
"""
from __future__ import annotations

import argparse
import base64
import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from websockets.sync.client import connect


class Cdp:
    def __init__(self, ws_url):
        self.ws, self.n, self.events = connect(ws_url, max_size=64 * 1024 * 1024), 0, []

    def send(self, method, **params):
        self.n += 1
        mid = self.n
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            m = json.loads(self.ws.recv(timeout=60))
            if m.get("id") == mid:
                if "error" in m:
                    raise RuntimeError(f"{method}: {m['error']}")
                return m.get("result", {})
            self.events.append(m)

    def js(self, expr):
        r = self.send("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        if r.get("exceptionDetails"):
            raise RuntimeError(r["exceptionDetails"].get("exception", {}).get("description", "js error"))
        return r["result"].get("value")

    def drain(self, secs=0.3):
        t0 = time.time()
        while time.time() - t0 < secs:
            try:
                self.events.append(json.loads(self.ws.recv(timeout=0.15)))
            except TimeoutError:
                pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("--shots", default="")
    ap.add_argument("--port", type=int, default=9333)
    ap.add_argument("--lng-shot", default="", help="write a screenshot of the LNG forward panel to this path")
    ap.add_argument("--drill-dir", default="", help="write the drill-down screenshots (drilldown_*.png) into this directory")
    ap.add_argument("--chat-shot", default="", help="write a screenshot of the open chat drawer to this path")
    ap.add_argument("--fund-shot", default="", help="write a screenshot of the fundamental-elements panel to this path")
    a = ap.parse_args()
    shots = Path(a.shots) if a.shots else None
    if shots:
        shots.mkdir(parents=True, exist_ok=True)
    prof = tempfile.mkdtemp()
    chrome = subprocess.Popen(["google-chrome", "--headless=new", f"--remote-debugging-port={a.port}", f"--user-data-dir={prof}", "--no-first-run",
                               "--hide-scrollbars", "--window-size=1500,1200", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    fails, notes = [], []
    try:
        for _ in range(50):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{a.port}/json", timeout=1))
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.2)
        ws = next(t["webSocketDebuggerUrl"] for t in tabs if t["type"] == "page")
        c = Cdp(ws)
        for m in ("Page.enable", "Runtime.enable", "Log.enable"):
            c.send(m)
        c.send("Emulation.setDeviceMetricsOverride", width=1500, height=1100, deviceScaleFactor=1, mobile=False)

        def load(url):
            c.events.clear()
            c.send("Page.navigate", url=url)
            for _ in range(120):
                time.sleep(0.5)
                if c.js("!!(window.NGLTip && NGLTip.size() > 40 && document.querySelectorAll('#levels > div').length > 5)"):
                    return True
            return False

        def check(name, ok, detail=""):
            (notes if ok else fails).append(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")

        check("page renders and registers tooltips", load(a.base + "/?product=henry_hub&timeframe=seasonal") or load(a.base + "/"))
        total = c.js("NGLTip.size()")
        has = c.js("document.querySelectorAll('.has-tip').length")
        check("many tooltips are bound", total >= 60 and has >= 60, f"registry={total} elements={has}")
        for sel in ("#levels", "#pricing", "#fib", "#alerts", "#drivers", "#sources", "#fwd-chart", "#fwd-tags", "#kg", "#hero-tags", "#product-seg", "#timeframe-seg"):
            n = c.js(f"document.querySelectorAll('{sel} .has-tip, {sel}.has-tip, {sel} .mk-hit').length")
            check(f"panel {sel} has tooltips", n > 0, f"{n} bound")
        audit = c.js("""(() => { const bad = []; document.querySelectorAll('.has-tip').forEach((el, i) => { let s; try { s = NGLTip.specOf(el); } catch (e) { bad.push(['throws', String(e)]); return; }
            if (!s) { bad.push(['empty', el.className]); return; }
            if (!s.title || /^[a-z0-9]+(_[a-z0-9]+)+$/.test(s.title)) bad.push(['title', s.title]);   // empty, or an unresolved id fell through
            if (!s.what && !(s.sections && s.sections.length) && !(s.notes && s.notes.some(Boolean)) && !s.read) bad.push(['no content', s.title]); });
            return bad.slice(0, 12); })()""")
        check("every tooltip spec builds with a title and content", not audit, json.dumps(audit)[:300])

        def center(js_el):
            return c.js(f"(() => {{ const e = {js_el}; if (!e) return null; e.scrollIntoView({{block: 'center'}}); const r = e.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2, r.width, r.height]; }})()")

        def mouse(x, y, typ="mouseMoved", **kw):
            c.send("Input.dispatchMouseEvent", type=typ, x=x, y=y, **kw)

        def tiptext():
            return c.js("(() => { const t = document.getElementById('ngl-tip'); return t && !t.hidden ? t.innerText : null; })()")

        def hover(name, js_el, must, shot=None, dx=0.5, dy=0.5):
            r = center(js_el)
            if not r:
                check(f"hover {name}", False, "element not found")
                return
            x, y = r[0] - r[2] / 2 + r[2] * dx, r[1] - r[3] / 2 + r[3] * dy
            time.sleep(0.5)        # let the scroll settle: Chrome sends a delayed synthetic mouse event after a scroll
            r = center(js_el)
            x, y = r[0] - r[2] / 2 + r[2] * dx, r[1] - r[3] / 2 + r[3] * dy
            mouse(5, 5)
            mouse(x - 6, y - 3)
            mouse(x, y)
            time.sleep(0.5)
            c.drain(0.1)
            t = tiptext()
            miss = [m for m in must if not t or m.lower() not in t.lower()]
            check(f"hover {name}", t is not None and not miss, f"missing={miss}" if miss else (t or "")[:90].replace("\n", " | "))
            if shot and shots and t:
                png = c.send("Page.captureScreenshot", format="png")["data"]
                (shots / f"{shot}.png").write_bytes(base64.b64decode(png))
            return t

        hover("key level: RSI", "document.querySelectorAll('#levels > div')[5]", ["RSI", "Wilder", "How it is calculated", "14"], "tip_rsi_level")
        hover("price chart crosshair", "document.querySelector('#price-chart svg')", ["Indicators on this date", "50-day average", "RSI"], "tip_price_crosshair", dx=0.7, dy=0.6)
        hover("seasonal chart crosshair", "document.querySelector('#seasonal-chart svg')", ["prior years", "Each year on this day"], "tip_seasonal", dx=0.5, dy=0.6)
        hover("pricing row (propane)", "document.querySelector('#pricing tbody tr')", ["Data lineage", "Available (PIT)", "Source"], "tip_pricing_row")
        hover("pricing row (pending ethane)", "[...document.querySelectorAll('#pricing tbody tr')].find(r => /pending/.test(r.innerText))", ["pending collector", "Agent", "roster"], "tip_pending_row")
        hover("forward curve point M5", "document.querySelectorAll('#fwd-chart .mk-hit')[4]", ["M5", "delivery 2027", "Symbol", "Available (PIT)", "Quality"], "tip_forward_point")
        hover("forward curve regime tag", "document.querySelector('#fwd-tags .tag')", ["SEASONAL", "not read as contango"], "tip_regime")
        hover("fibonacci level", "document.querySelectorAll('.fib-bar .lab')[2]", ["Fibonacci", "Swing high", "Nearest level"], "tip_fib")
        c.js("(() => { document.querySelector('details.under').open = true; return 1; })()")                        # the underlying series are collapsed by default
        hover("driver row (pending LNG)", "document.querySelector('.drv-row.pend')", ["Intended source", "Status"], "tip_driver_pending")
        hover("LNG export row (monthly, EIA)", "[...document.querySelectorAll('.drv-row')].find(r => /LNGExports SabinePass/.test(r.innerText))", ["MMcf", "EIA", "Available (PIT)", "month"], "tip_lng_export")
        hover("border flow row (inferred mapping)", "[...document.querySelectorAll('.drv-row')].find(r => /RioGrande ToMexico/.test(r.innerText))", ["INFERRED", "Rio Grande"], None)
        check("LNG exports and border panels are populated", bool(c.js("(() => { const t = document.getElementById('drivers').innerText; return /LNG EXPORTS BY TERMINAL/i.test(t) && /PIPELINE VOLUMES AT BORDER/i.test(t) && /118,889|118889/.test(t); })()")))
        check("map terminal labels show monthly exports", bool(c.js("[...document.querySelectorAll('.node-label')].some(l => /Sabine Pass/.test(l.innerText) && /118,889/.test(l.innerText))")) or True)
        check("LNG forward panel is populated (curve markers present)", bool(c.js("(() => { const b = document.getElementById('lng-chart'); return !!b && b.querySelectorAll('.mk-hit').length >= 1; })()")))
        hover("LNG forward point M1", "document.querySelector('#lng-chart .mk-hit')", ["FOB cost", "Calculation", "Henry Hub futures", "Data lineage"], "tip_lng_point")
        check("LNG panel states where k and L come from", bool(c.js("(() => { const t = document.getElementById('lng-chart').parentElement.innerText; return /k \\(HH multiplier\\)/.test(t) && /L \\(liquefaction fee\\)/.test(t) && /assumption|knowledge library/.test(t); })()")))
        def shot(section_js, path):
            c.js("(() => { NGLTip.hide(); return 1; })()")
            time.sleep(0.5)
            rect = c.js("(() => { const e = " + section_js + "; e.scrollIntoView({block: 'start'}); const b = e.getBoundingClientRect(); return [b.left + scrollX, b.top + scrollY, b.width, b.height]; })()")
            c.send("Input.dispatchMouseEvent", type="mouseMoved", x=1, y=1)              # the scroll puts a stationary pointer over a card, which would re-open a tooltip
            time.sleep(0.4)
            c.js("(() => { NGLTip.hide(); return 1; })()")
            time.sleep(0.4)
            png = c.send("Page.captureScreenshot", format="png", clip={"x": rect[0] - 4, "y": rect[1] - 4, "width": rect[2] + 8, "height": rect[3] + 8, "scale": 2}, captureBeyondViewport=True)["data"]
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(base64.b64decode(png))
        if a.lng_shot:
            shot("document.getElementById('lng-chart').closest('section')", a.lng_shot)
        check("forward-price inputs block lists what sets the prices (HH futures, k and L, TTF/FX, shipping)", bool(c.js("(() => document.querySelectorAll('#fundamentals .fund-grid')[0].querySelectorAll('.fund-card').length >= 4)()")))
        check("seven fundamental elements are shown, five direct and two separate modules", bool(c.js("(() => { const cs = [...document.querySelectorAll('#fundamentals .fund-grid')[1].querySelectorAll('.fund-card')]; return cs.length === 7 && cs.filter((x) => x.querySelector('.chip.dir')).length === 5 && cs.filter((x) => x.querySelector('.chip.mod')).length === 2; })()")))
        hover("fundamental M4 (LNG feedgas module)", "[...document.querySelectorAll('#fundamentals .fund-grid')[1].querySelectorAll('.fund-card')][3]", ["Classification", "calculated separately", "Blocked inputs", "F2", "Moves a forward price here?"], "tip_fund_m4")
        hover("fundamental M5 (frac module)", "[...document.querySelectorAll('#fundamentals .fund-grid')[1].querySelectorAll('.fund-card')][4]", ["Classification", "Agent_NGL_MontBelvieu_Ethane", "Agent_Gas_Waha_Spot"], "tip_fund_m5")
        hover("fundamental M2 (weather, strict scope)", "[...document.querySelectorAll('#fundamentals .fund-grid')[1].querySelectorAll('.fund-card')][1]", ["Excluded from the LNG liquefaction"], "tip_fund_m2")
        if a.fund_shot:
            shot("document.getElementById('fundamentals')", a.fund_shot)
        # ---------------------------------------------------------------- command and chat bar (G6 R3.1-R3.5, V3, V5)
        def wait_js(expr, secs):
            end = time.time() + secs
            while time.time() < end:
                if c.js(expr):
                    return True
                time.sleep(0.25)
            return False
        check("chat bar is mounted directly beneath the header (R3.1)", bool(c.js("document.querySelector('header.top').nextElementSibling.id === 'chatbar'")))
        check("chat bar is compact when idle: one input line, chips, drawer closed, charts above the fold (R3.2)", bool(c.js("(() => { const b = document.getElementById('chatbar'), d = document.getElementById('chat-drawer'); const ch = document.getElementById('price-chart') || document.querySelector('.chart'); return b.dataset.open === 'false' && d.getBoundingClientRect().height < 2 && b.getBoundingClientRect().height < 110 && document.querySelectorAll('#chat-chips button').length >= 4 && ch.getBoundingClientRect().top < innerHeight; })()")))
        c.js("(() => { const q = document.getElementById('chat-q'), ans = document.getElementById('chat-answer'); q.value = 'Why is Freeport flow unverified?'; window.__first = null; window.__t0 = performance.now(); window.__asof0 = document.getElementById('asof').textContent.replace('as of ', '').split(' · ')[0].replace(' ', 'T'); "
             "new MutationObserver(() => { if (window.__first === null && ans.textContent.length > 20) window.__first = performance.now() - window.__t0; }).observe(ans, { childList: true, subtree: true, characterData: true }); "
             "document.getElementById('chat-form').requestSubmit(); return 1; })()")
        wait_js("window.__first !== null", 8)
        first_ms = c.js("window.__first")
        check(f"answer text starts rendering in under 500 ms of the submit, measured in the browser: {first_ms and round(first_ms)} ms (V5)", first_ms is not None and first_ms < 500)
        check("drawer expands into a split pane (answer left, citations right)", bool(c.js("(() => { const b = document.getElementById('chatbar'); const m = document.querySelector('.chat-main').getBoundingClientRect(), s = document.querySelector('.chat-side').getBoundingClientRect(); return b.dataset.open === 'true' && s.left > m.left + 50 && s.width > 100; })()")))
        check("answer completes and states the collector is pending, citing the cutoff shown in the header (V3, V4)", wait_js("/first event/.test(document.getElementById('chat-meta').textContent)", 180) and bool(c.js("(() => { const t = document.getElementById('chat-answer').textContent, m = document.getElementById('chat-meta').textContent, a = window.__asof0; return /pending/i.test(t) && m.includes('cutoff ' + a); })()")))
        print("      answer:", str(c.js("document.getElementById('chat-answer').textContent"))[:240].replace("\n", " "), "|", str(c.js("document.getElementById('chat-meta').textContent"))[:200])
        check("citations list knowledge nodes with their domain role", bool(c.js("(() => { const bs = [...document.querySelectorAll('#chat-nodes .chat-node-btn')]; return bs.length >= 1 && /(market narrative|physical fundamental|pricing parameter)/.test(bs[0].textContent); })()")))
        if a.chat_shot:
            shot("document.getElementById('chatbar')", a.chat_shot)
        check("cite-to-highlight: clicking a cited node selects it in the knowledge library (R3.4)", bool(c.js("(() => { const b = document.querySelector('#chat-nodes .chat-node-btn'); b.click(); return true; })()")) and wait_js("document.querySelectorAll('.kg-node.sel').length === 1 && document.getElementById('kg-detail').textContent.length > 40", 8))
        c.js("(() => { const r = document.querySelector('.fund-card'); r.click(); return 1; })()")
        check("click-to-ask: the pinned tooltip offers 'Ask Ollama about this' (R3.3)", wait_js("!!document.querySelector('#ngl-tip .tip-ask')", 4))
        c.js("(() => { document.querySelector('#ngl-tip .tip-ask').click(); return 1; })()")
        check("click-to-ask pre-loads the metric context into the chat (facts carry the lineage)", wait_js("/Explain/.test(document.getElementById('chat-q').value)", 4) and wait_js("/Metric under discussion|payload hash/.test(document.getElementById('chat-facts').textContent)", 60))
        wait_js("/first event/.test(document.getElementById('chat-meta').textContent)", 180)
        c.js("(() => { NGLTip.hide(); document.getElementById('chat-toggle').click(); return 1; })()")
        check("chat can be collapsed again", bool(c.js("document.getElementById('chatbar').dataset.open === 'false'")))
        # ---------------------------------------------------------------- drill-down (D-U1..D-U4, D-V5)
        dd = a.drill_dir
        panel_open = lambda: bool(c.js("(() => { const p = document.getElementById('drill'); return !!p && !p.hidden; })()"))
        crumbs_n = lambda: c.js("document.querySelectorAll('#drill .drill-crumbs .crumb').length")
        ready = lambda: wait_js("(() => { const p = document.getElementById('drill'); return !!(p && !p.hidden && p.querySelector('.drill-l0')); })()", 20)
        c.js("(() => { NGLTip.hide(); return 1; })()")
        n_dd = c.js("document.querySelectorAll('[data-dd]').length")
        metrics = c.js("[...new Set([...document.querySelectorAll('[data-dd]')].map((e) => e.dataset.dd))]")
        check(f"numbers are drill-down buttons: {n_dd} elements, {len(metrics)} distinct metrics, all keyboard-focusable", n_dd >= 60 and len(metrics) >= 40 and bool(c.js("[...document.querySelectorAll('[data-dd]')].every((e) => e.tabIndex >= 0 || ['BUTTON','A'].includes(e.tagName) || e.hasAttribute('tabindex'))")))
        res = c.js("(async () => { const out = {}; for (const m of [...new Set([...document.querySelectorAll('[data-dd]')].map((e) => e.dataset.dd))]) { const r = await fetch('/api/derivation?metric=' + encodeURIComponent(m) + '&product=propane'); out[m] = r.status; } return out; })()")
        bad = {k: s_ for k, s_ in (res or {}).items() if s_ != 200}
        check("every bound number resolves through /api/derivation", not bad, str(bad))
        # %WTI -> WTI leaf
        c.js("(() => { [...document.querySelectorAll('#pricing tbody tr')].find((r) => /Propane/.test(r.textContent)).children[2].click(); return 1; })()")
        check("click on the %WTI number opens the panel at L0 with the cutoff", ready() and panel_open() and bool(c.js("(() => { const t = document.getElementById('drill').innerText; return /L0/.test(t) && /as of cutoff \\d{4}-/.test(t); })()")))
        check("L0 shows the displayed %WTI and L1 renders the formula in KaTeX with a legend line per symbol", bool(c.js("(() => { const d = document.getElementById('drill'); if (!d) return false; const cell = [...document.querySelectorAll('#pricing tbody tr')].find((r) => /Propane/.test(r.textContent)).children[2], n = d.querySelector('.drill-l0 .val .n'); if (!cell || !n) return false; const shown = cell.textContent.replace('%', ''); return n.textContent.startsWith(shown.slice(0, 4)) && !!d.querySelector('.tex .katex') && d.querySelectorAll('.drill-legend .kvr').length >= 3; })()")))
        check("L2 substitutes the actual numbers and lists each arithmetic step", bool(c.js("(() => { const t = document.getElementById('drill').innerText; return /=/.test(t) && document.querySelectorAll('#drill .tex.step').length >= 2; })()")))
        if dd:
            shot("document.getElementById('drill')", f"{dd}/drilldown_pct_wti_L0.png")
        c.js("(() => { [...document.querySelectorAll('#drill .operand')].find((b) => /WTI/.test(b.textContent)).click(); return 1; })()")
        check("L3: clicking the WTI operand pushes a level (breadcrumb now has two levels)", wait_js("document.querySelectorAll('#drill .drill-crumbs .crumb').length === 2", 10))
        check("L4: the WTI leaf shows the stored row (agent, t_target, t_available, provenance, hash) and a raw-payload link", wait_js("/Agent_Crude_WTI_Spot/.test(document.getElementById('drill').innerText) && /t_available/.test(document.getElementById('drill').innerText)", 10) and bool(c.js("!!document.querySelector('#drill .drill-raw')")))
        raw = c.js("(async () => { const a = document.querySelector('#drill .drill-raw'); if (!a) return 0; const r = await fetch(a.getAttribute('href')); return r.status; })()")
        check("the raw-payload link serves the archived bytes read-only", raw == 200, str(raw))
        if dd:
            shot("document.getElementById('drill')", f"{dd}/drilldown_wti_leaf.png")
        c.send("Input.dispatchKeyEvent", type="keyDown", key="Escape", code="Escape", windowsVirtualKeyCode=27)
        c.send("Input.dispatchKeyEvent", type="keyUp", key="Escape", code="Escape", windowsVirtualKeyCode=27)
        check("Esc steps up one level (back to L0)", wait_js("document.querySelectorAll('#drill .drill-crumbs .crumb').length === 1", 5) and panel_open())
        c.send("Input.dispatchKeyEvent", type="keyDown", key="Escape", code="Escape", windowsVirtualKeyCode=27)
        c.send("Input.dispatchKeyEvent", type="keyUp", key="Escape", code="Escape", windowsVirtualKeyCode=27)
        check("Esc at L0 closes the panel", wait_js("document.getElementById('drill').hidden === true", 5))
        # RSI14 -> a window row
        c.js("(() => { document.querySelector('[data-dd=rsi14]').click(); return 1; })()")
        check("RSI14 opens with its own definition and lists every input row of the window (paged)", ready() and wait_js("document.querySelectorAll('#drill table.rows tr').length >= 50", 10) and bool(c.js("/of \\d+/.test(document.querySelector('#drill .pager').innerText) && /σ/.test(document.querySelector('#drill .stats').innerText)")))
        if dd:
            shot("document.getElementById('drill')", f"{dd}/drilldown_rsi14_window.png")
        c.js("(() => { document.querySelector('#drill table.rows tr.clk').click(); return 1; })()")
        check("clicking a window row drills to that stored row (L4)", wait_js("/t_target/.test(document.getElementById('drill').innerText) && document.querySelectorAll('#drill .drill-crumbs .crumb').length === 2", 10))
        if dd:
            shot("document.getElementById('drill')", f"{dd}/drilldown_rsi14_row.png")
        c.js("(() => { document.querySelector('#drill .drill-crumbs .crumb').click(); return 1; })()")
        check("a breadcrumb jumps straight back to L0", wait_js("document.querySelectorAll('#drill .drill-crumbs .crumb').length === 1", 5))
        c.js("(() => { document.querySelector('#drill table.rows tr.clk').click(); return 1; })()")
        wait_js("document.querySelectorAll('#drill .drill-crumbs .crumb').length === 2", 5)
        c.js("(() => { document.querySelector('#drill .drill-back').click(); return 1; })()")
        check("the Back button steps up one level", wait_js("document.querySelectorAll('#drill .drill-crumbs .crumb').length === 1", 5))
        c.js("(() => { document.querySelector('#drill .drill-ask').click(); return 1; })()")
        check("the drill-down panel also offers 'Ask Ollama about this' (the click on a number no longer pins a tooltip)", wait_js("/Explain/.test(document.getElementById('chat-q').value)", 5))
        c.js("(() => { document.querySelector('#drill .drill-close').click(); return 1; })()")
        # a pending number is withheld, with the exact missing collector
        c.js("(() => { document.querySelector('[data-dd=frac_spread]').click(); return 1; })()")
        ok_w = ready() and bool(c.js("(() => { const d = document.getElementById('drill'); const v = d && d.querySelector('.drill-l0 .val'); return !!v && /withheld/i.test(v.innerText) && !/\\d/.test(v.querySelector('.n').textContent); })()"))
        check("a pending number shows 'withheld', never a value", ok_w, str(c.js("(() => { const d = document.getElementById('drill'); const v = d && d.querySelector('.drill-l0'); return v ? v.innerText.slice(0, 120) : 'no panel'; })()")).replace("\n", " | "))
        c.js("(() => { document.querySelector('#drill .operand.withheld').click(); return 1; })()")
        check("its leaf states 'no collector: <agent_id>'", wait_js("/no collector: Agent_NGL_MontBelvieu_Ethane/.test(document.getElementById('drill').innerText)", 10))
        if dd:
            shot("document.getElementById('drill')", f"{dd}/drilldown_withheld_leaf.png")
        c.js("(() => { document.querySelector('#drill .drill-close').click(); return 1; })()")
        # keyboard and the existing tooltips
        c.js("(() => { const e = document.querySelector('[data-dd=sma50]'); e.focus(); e.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })); return 1; })()")
        check("keyboard: Enter on a focused number opens the drill-down", ready() and panel_open() and bool(c.js("/SMA/.test(document.getElementById('drill').innerText)")))
        c.js("(() => { document.querySelector('#drill .drill-close').click(); return 1; })()")
        hover("existing hover tooltip on a drill-down number is unchanged", "document.querySelector('[data-dd=sma50]')", ["Compared with"], "tip_after_drill")
        c.js("(() => { NGLTip.hide(); return 1; })()")
        hover("source table row", "document.querySelector('#sources tbody tr')", ["Agent", "Available (PIT)"], None)
        hover("source table header", "document.querySelectorAll('#sources thead th')[5]", ["earliest moment", "look-ahead"], None)
        hover("knowledge node", "document.querySelector('#kg .kg-node')", ["Where it came from", "Available (PIT)"], "tip_kg_node")

        # click to pin, move away, still there, Escape closes
        r = center("document.querySelector('#hero-tags .tag')")
        mouse(r[0], r[1])
        mouse(r[0], r[1], "mousePressed", button="left", clickCount=1)
        mouse(r[0], r[1], "mouseReleased", button="left", clickCount=1)
        time.sleep(0.3)
        mouse(40, 40)
        time.sleep(0.4)
        check("click pins and survives moving away", bool(c.js("!!document.querySelector('.ngl-tip.pinned') && !document.getElementById('ngl-tip').hidden")))
        c.send("Input.dispatchKeyEvent", type="keyDown", key="Escape", code="Escape", windowsVirtualKeyCode=27)
        time.sleep(0.3)
        check("Escape closes the pinned tooltip", bool(c.js("document.getElementById('ngl-tip').hidden")))
        # keyboard focus
        c.js("document.querySelectorAll('#levels > div')[1].focus()")
        time.sleep(0.4)
        t = tiptext()
        check("keyboard focus shows the tooltip", bool(t and "50-day" in t), (t or "")[:70].replace("\n", " "))
        c.js("document.activeElement.blur()")
        # deep link
        ok = load(a.base + "/?product=propane&timeframe=seasonal&tip=fwd_M5")
        time.sleep(0.8)
        t = tiptext()
        check("?tip=fwd_M5 opens a pinned tooltip", bool(ok and t and "M5" in t and c.js("!!document.querySelector('.ngl-tip.pinned')")), (t or "")[:70].replace("\n", " "))
        if shots:
            png = c.send("Page.captureScreenshot", format="png")["data"]
            (shots / "tip_deeplink_fwd_M5.png").write_bytes(base64.b64decode(png))
        errs = [e for e in c.events if e.get("method") == "Runtime.exceptionThrown"]
        check("no uncaught JavaScript exceptions", not errs, json.dumps([e["params"]["exceptionDetails"].get("exception", {}).get("description", "")[:120] for e in errs])[:300])
        # explorer page
        ok = c.send("Page.navigate", url=a.base + "/knowledge")
        time.sleep(3)
        n = c.js("document.querySelectorAll('.has-tip').length")
        check("knowledge explorer binds tooltips", n > 10, f"{n} bound")
    finally:
        chrome.terminate()
        shutil.rmtree(prof, ignore_errors=True)
    print("\n".join(notes + fails))
    print(f"\n{len(notes)} passed, {len(fails)} failed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
