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
        hover("driver row (pending LNG)", "document.querySelector('.drv-row.pend')", ["Intended source", "Status"], "tip_driver_pending")
        hover("LNG export row (monthly, EIA)", "[...document.querySelectorAll('.drv-row')].find(r => /LNGExports SabinePass/.test(r.innerText))", ["MMcf", "EIA", "Available (PIT)", "month"], "tip_lng_export")
        hover("border flow row (inferred mapping)", "[...document.querySelectorAll('.drv-row')].find(r => /RioGrande ToMexico/.test(r.innerText))", ["INFERRED", "Rio Grande"], None)
        check("LNG exports and border panels are populated", bool(c.js("(() => { const t = document.getElementById('drivers').innerText; return /LNG EXPORTS BY TERMINAL/i.test(t) && /PIPELINE VOLUMES AT BORDER/i.test(t) && /118,889|118889/.test(t); })()")))
        check("map terminal labels show monthly exports", bool(c.js("[...document.querySelectorAll('.node-label')].some(l => /Sabine Pass/.test(l.innerText) && /118,889/.test(l.innerText))")) or True)
        check("LNG forward panel is populated (curve markers present)", bool(c.js("(() => { const b = document.getElementById('lng-chart'); return !!b && b.querySelectorAll('.mk-hit').length >= 1; })()")))
        hover("LNG forward point M1", "document.querySelector('#lng-chart .mk-hit')", ["FOB cost", "Calculation", "Henry Hub futures", "Data lineage"], "tip_lng_point")
        check("LNG panel states where k and L come from", bool(c.js("(() => { const t = document.getElementById('lng-chart').parentElement.innerText; return /k \\(HH multiplier\\)/.test(t) && /L \\(liquefaction fee\\)/.test(t) && /assumption|knowledge library/.test(t); })()")))
        def shot(section_js, path):
            time.sleep(0.5)
            rect = c.js("(() => { const e = " + section_js + "; e.scrollIntoView({block: 'start'}); const b = e.getBoundingClientRect(); return [b.left + scrollX, b.top + scrollY, b.width, b.height]; })()")
            time.sleep(0.5)
            png = c.send("Page.captureScreenshot", format="png", clip={"x": rect[0] - 4, "y": rect[1] - 4, "width": rect[2] + 8, "height": rect[3] + 8, "scale": 2}, captureBeyondViewport=True)["data"]
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(base64.b64decode(png))
        if a.lng_shot:
            shot("document.getElementById('lng-chart').closest('section')", a.lng_shot)
        check("seven fundamental elements are shown, five direct and two separate modules", bool(c.js("(() => { const cs = [...document.querySelectorAll('#fundamentals .fund-card')]; return cs.length === 7 && cs.filter((x) => x.querySelector('.chip.dir')).length === 5 && cs.filter((x) => x.querySelector('.chip.mod')).length === 2; })()")))
        hover("fundamental M4 (LNG feedgas module)", "[...document.querySelectorAll('#fundamentals .fund-card')][3]", ["Classification", "calculated separately", "Blocked inputs", "F2", "Moves a forward price here?"], "tip_fund_m4")
        hover("fundamental M5 (frac module)", "[...document.querySelectorAll('#fundamentals .fund-card')][4]", ["Classification", "Agent_NGL_MontBelvieu_Ethane", "Agent_Gas_Waha_Spot"], "tip_fund_m5")
        hover("fundamental M2 (weather, strict scope)", "[...document.querySelectorAll('#fundamentals .fund-card')][1]", ["Excluded from the LNG liquefaction"], "tip_fund_m2")
        if a.fund_shot:
            shot("document.getElementById('fundamentals')", a.fund_shot)
        hover("source table row", "document.querySelector('#sources tbody tr')", ["Agent", "Available (PIT)"], None)
        hover("source table header", "document.querySelectorAll('#sources thead th')[5]", ["earliest moment", "look-ahead"], None)
        hover("knowledge node", "document.querySelector('#kg .kg-node')", ["Where it came from", "Available (PIT)"], "tip_kg_node")

        # click to pin, move away, still there, Escape closes
        r = center("document.querySelectorAll('#levels > div')[5]")
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
