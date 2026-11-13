#!/usr/bin/env python3
"""ngl-term: terminal dashboard for the NGL & Henry Hub visual intelligence state.

It renders exactly the document served at /api/state.json (schema ngl-state/1), the same one the web UI draws, so the two
never disagree. The map is drawn with Unicode Braille cells (U+2800-U+28FF, 2x4 sub-pixels per character) from the same
web/data/na_basemap.json linework the web map uses.

Usage:
  ngl-term.py                                   live dashboard against http://127.0.0.1:8095/api/state.json
  ngl-term.py --url https://ngl.joeysvault.app/api/state.json --product henry_hub --timeframe multi_year
  ngl-term.py --once                            print one frame and exit (also used by the tests)
Keys (live mode): p / P next / previous product, t next timeframe, r refresh now, q quit.

Runs on local infrastructure only: Python standard library plus `rich`. No AI service is called.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import select
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from rich import box
from rich.console import Console, Group
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

BASE_DIR = Path(__file__).resolve().parent
BASEMAP = BASE_DIR / "web" / "data" / "na_basemap.json"
SCHEMA = "ngl-state/1"
PRODUCTS = ["propane", "ethane", "normal_butane", "isobutane", "natural_gasoline", "henry_hub"]
TIMEFRAMES = ["intraday", "seasonal", "multi_year"]
DEFAULT_URL = os.environ.get("NGL_STATE_URL", "http://127.0.0.1:8095/api/state.json")
FG, DIM, MUTE, GOLD = "white", "grey70", "grey42", "#c8b45a"
BOX = box.SQUARE

# ----------------------------------------------------------------------------- Braille canvas
_DOT = ((0x01, 0x08), (0x02, 0x10), (0x04, 0x20), (0x40, 0x80))   # [row][col] bit for a 2x4 Braille cell


class Braille:
    """Pixel canvas of width*2 x height*4 dots rendered as width x height Braille characters."""

    def __init__(self, cols: int, rows: int):
        self.cols, self.rows = cols, rows
        self.cells = [[0] * cols for _ in range(rows)]
        self.style = [[None] * cols for _ in range(rows)]

    def dot(self, x: int, y: int, style: str | None = None) -> None:
        if 0 <= x < self.cols * 2 and 0 <= y < self.rows * 4:
            r, c = y // 4, x // 2
            self.cells[r][c] |= _DOT[y % 4][x % 2]
            if style:
                self.style[r][c] = style

    def line(self, x0: float, y0: float, x1: float, y1: float, style: str | None = None, dash: int = 0) -> None:
        n = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
        for i in range(n + 1):
            if dash and (i // dash) % 2:
                continue
            t = i / n
            self.dot(round(x0 + (x1 - x0) * t), round(y0 + (y1 - y0) * t), style)

    def text(self, overlay: dict | None = None) -> Text:
        """overlay: {(row, col): (string, style)} written over the Braille cells (labels)."""
        out = Text()
        overlay = overlay or {}
        for r in range(self.rows):
            c = 0
            while c < self.cols:
                if (r, c) in overlay:
                    s, st = overlay[(r, c)]
                    s = s[: self.cols - c]
                    out.append(s, style=st)
                    c += len(s)
                    continue
                v = self.cells[r][c]
                out.append(chr(0x2800 + v), style=self.style[r][c] or (FG if v else MUTE))
                c += 1
            if r < self.rows - 1:
                out.append("\n")
        return out


def project(lon: float, lat: float, bbox, cols: int, rows: int):
    """Equirectangular projection with cos(mid-latitude) scaling into the dot grid."""
    w, s, e, n = bbox
    k = math.cos(math.radians((s + n) / 2))
    W, H = cols * 2, rows * 4
    sx = W / ((e - w) * k)
    sy = H / (n - s)
    sc = min(sx, sy)
    ox = (W - (e - w) * k * sc) / 2
    oy = (H - (n - s) * sc) / 2
    return ox + (lon - w) * k * sc, oy + (n - lat) * sc


def render_map(state: dict, cols: int, rows: int, basemap: dict | None) -> Text:
    bbox = (-112.0, 24.0, -72.0, 50.0)
    cv = Braille(cols, rows)
    P = lambda lon, lat: project(lon, lat, bbox, cols, rows)
    if basemap:
        for key, style in (("states", "grey30"), ("coast_and_borders", "grey85")):
            for line in basemap["layers"].get(key, []):
                pts = [P(lo, la) for lo, la in line]
                for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
                    cv.line(x0, y0, x1, y1, style)
    geo = state.get("geo", {})
    nodes = {n["id"]: n for n in geo.get("nodes", [])}
    for f in geo.get("flows", []):
        a, b = nodes.get(f["from"]), nodes.get(f["to"])
        if a and b:
            x0, y0 = P(a["lon"], a["lat"])
            x1, y1 = P(b["lon"], b["lat"])
            cv.line(x0, y0, x1, y1, DIM, dash=2)               # dotted: schematic corridor, no measured flow
    overlay, taken = {}, set()
    for n in sorted(nodes.values(), key=lambda n: (n["status"] != "measured", n["kind"] == "lng")):
        x, y = P(n["lon"], n["lat"])
        r, c = int(y // 4), int(x // 2)
        if not (0 <= r < rows and 0 <= c < cols):
            continue
        ok = n["status"] == "measured"
        val = f" {n['value']:.4g}" if ok and n.get("value") is not None else ""
        label = f"{'●' if ok else '○'}{n['id']}{val}"
        start = c if c + len(label) < cols else max(0, cols - len(label))
        span = {(r, k) for k in range(start, start + len(label))}
        if span & taken:                                        # avoid overprinting a neighbour: try the row below
            r += 1
            span = {(r, k) for k in range(start, start + len(label))}
            if r >= rows or span & taken:
                continue
        taken |= span
        overlay[(r, start)] = (label, ("bold " + FG) if ok else DIM)
    return cv.text(overlay)


# ----------------------------------------------------------------------------- small helpers
def fmt(v, d: int = 2, unit: str = "") -> str:
    if v is None:
        return "—"
    return f"{v:,.{d}f}{(' ' + unit) if unit else ''}"


def signed(v, d: int = 2) -> str:
    return "—" if v is None else f"{v:+,.{d}f}"


def dec(unit: str) -> int:
    return 1 if unit == "cents/gal" else 2 if unit == "USD/bbl" else 3


def spark(values, width: int) -> str:
    vals = [v for v in values if v is not None][-width * 2:]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1.0
    cv = Braille(width, 1)
    step = (len(vals) - 1) / max(1, width * 2 - 1)
    prev = None
    for x in range(width * 2):
        v = vals[round(x * step)]
        y = 3 - round((v - lo) / rng * 3)
        if prev is not None:
            cv.line(x - 1, prev, x, y)
        prev = y
    return cv.text().plain


def short(agent: str) -> str:
    return agent.replace("Agent_", "").replace("_", " ")


def panel(body, title: str) -> Panel:
    return Panel(body, title=Text(title.upper(), style=FG), title_align="left", border_style=FG, box=BOX, padding=(0, 1))


# ----------------------------------------------------------------------------- panels
def hero_panel(s: dict, width: int = 120) -> Panel:
    p, pr, t = s["product"], s["price"], s.get("technicals", {})
    head = Text()
    head.append(f"{p['label']}  ", style="bold " + FG)
    head.append(f"[{s['timeframe']['label']}]  ", style=DIM)
    if pr["status"] != "measured":
        head.append("PENDING COLLECTOR", style=GOLD)
        return panel(Group(head, Text(pr.get("note", ""), style=DIM), Text("agent " + p["agent_id"], style=MUTE)),
                     "Seasonal patterns & key technical levels")
    d = dec(pr["unit"])
    head.append(f"{fmt(pr['value'], d)} {pr['unit']}", style="bold " + FG)
    head.append(f"  1d {signed(pr['change_1d'], d)} ({signed(pr['change_1d_pct'])}%)  5d {signed(pr['change_5d'], d)}", style=DIM)
    head.append(f"  · {pr['date']}", style=MUTE)
    sm = t["summary"]
    se = s["seasonal"]
    cur = [v for v in se["current"] if v is not None]
    avg = se["band_avg"][len(cur) - 1] if cur and len(se["band_avg"]) >= len(cur) else None
    seas = Text()
    seas.append("seasonal ", style=DIM)
    seas.append(f"{se['current_year']} vs {len(se['history_years'])}-yr band {se['history_years'][0] if se['history_years'] else '?'}–"
                f"{se['history_years'][-1] if se['history_years'] else '?'}: ", style=DIM)
    if cur and avg is not None:
        seas.append(f"now {fmt(cur[-1], d)} vs average {fmt(avg, d)} ({signed(cur[-1] - avg, d)})", style=FG)
    w = max(20, width - 6)
    line = Text(spark(s["series"]["values"], w), style=FG)
    grid = Table.grid(padding=(0, 2))
    for _ in range(4):
        grid.add_column()
    flag = lambda on, txt: Text(txt, style=GOLD if on else FG)
    grid.add_row(Text("50-day", style=DIM), Text(fmt(sm["sma50"], d)), Text("200-day", style=DIM), Text(fmt(sm["sma200"], d)))
    grid.add_row(Text("trend", style=DIM), Text(sm["trend"].replace("_", " ")), Text("50/200", style=DIM),
                 Text({"golden": "golden cross", "death": "death cross"}.get(sm["ma_regime"], sm["ma_regime"].replace("_", " "))))
    grid.add_row(Text("RSI(14)", style=DIM), Text(fmt(sm["rsi14"], 1)), Text("MACD hist", style=DIM), Text(signed(sm["macd_hist"], 3)))
    grid.add_row(Text("Bollinger", style=DIM), flag(sm["bollinger_squeeze"], f"bw {fmt(sm['bandwidth_pct'], 1)}%" + (" SQUEEZE" if sm["bollinger_squeeze"] else "")),
                 Text("triangle", style=DIM), flag(sm["triangle"] != "none", sm["triangle"].replace("_", " ")))
    grid.add_row(Text("RSI div", style=DIM), flag(sm["divergence_rsi"] != "none", sm["divergence_rsi"]),
                 Text("MACD div", style=DIM), flag(sm["divergence_macd"] != "none", sm["divergence_macd"]))
    tri = t.get("triangle", {})
    if tri.get("pattern", "none") != "none":
        grid.add_row(Text("breakout >", style=DIM), Text(fmt(tri["breakout_above"], d), style=GOLD), Text("breakdown <", style=DIM), Text(fmt(tri["breakdown_below"], d), style=GOLD))
    crosses = t.get("crossovers", [])
    if crosses:
        c = crosses[-1]
        grid.add_row(Text("last cross", style=DIM), Text(f"{c['type'].replace('_', ' ')} {c['date']}"), Text(""), Text(""))
    return panel(Group(head, line, seas, grid), "Seasonal patterns & key technical levels")


def fib_panel(s: dict) -> Panel:
    f = s.get("technicals", {}).get("fibonacci")
    if not f or f.get("status") != "ok":
        return panel(Text("pending collector — no series for the active product", style=DIM), "Fibonacci retracement")
    d = dec(s["price"]["unit"])
    width = 46
    bar = [" "] * (width + 1)
    marks = [0, 23.6, 38.2, 50, 61.8, 78.6, 100]
    for m in marks:
        bar[round(m / 100 * width)] = "│"
    for i in range(round(50 / 100 * width) + 1, round(61.8 / 100 * width)):
        bar[i] = "▒"
    pos = round(max(0.0, min(100.0, f["retracement_pct"] or 0)) / 100 * width)
    bar[pos] = "▼"
    lab = Text()
    for m in marks:
        lab.append(f"{m:g}%".ljust(7), style=GOLD if m in (38.2, 50, 61.8) else DIM)
    tb = Table(box=None, show_header=False, padding=(0, 1), expand=True)
    tb.add_column(style=DIM)
    tb.add_column(justify="right")
    for k in ("23.6%", "38.2%", "50.0%", "61.8%", "78.6%"):
        tb.add_row(Text(k, style=GOLD if k in ("38.2%", "50.0%", "61.8%") else DIM),
                   Text(fmt(f["levels"][k], d), style="bold " + GOLD if k == f["nearest_level"] else FG))
    foot = Text(f"{f['leg']}-leg · swing {fmt(f['swing_low'], d)} → {fmt(f['swing_high'], d)} · retraced {fmt(f['retracement_pct'], 1)}% · "
                f"{fmt(f['golden_ratio_distance_pct_of_range'], 1)}% of range from 61.8%", style=DIM)
    return panel(Group(lab, Text("".join(bar), style=FG), tb, foot), "Fibonacci retracement")


def pricing_panel(s: dict) -> Panel:
    tb = Table(box=None, expand=True, padding=(0, 1), header_style=DIM)
    tb.add_column("product")
    tb.add_column("price", justify="right")
    tb.add_column("% WTI", justify="right")
    for p in s["products"]:
        active = p["id"] == s["active_product"]
        name = ("▸ " if active else "  ") + p["label"].replace("Mont Belvieu ", "")
        if p["status"] == "pending_collector":
            tb.add_row(Text(name, style=MUTE), Text("pending", style=MUTE), Text("—", style=MUTE))
        else:
            tb.add_row(Text(name, style="bold " + FG if active else FG), Text(fmt(p["latest"], dec(p["unit"]), "¢/gal" if p["unit"] == "cents/gal" else "$/MMBtu")),
                       Text(fmt(p["pct_of_wti"], 1, "%") if p["pct_of_wti"] is not None else "—", style=DIM))
    c = s["curves"]
    w = c["ngl_to_wti_pct"]["wti"]
    tb.add_row(Text("  WTI crude (Cushing)"), Text(fmt(w["value"], 2, "$/bbl") if w["value"] else "pending"), Text("100%", style=DIM))
    kv = Table.grid(padding=(0, 2))
    kv.add_column(style=DIM)
    kv.add_column()
    fr, hs, fw = c["frac_spread"], c["hub_spread"], c["forward_curve"]
    kv.add_row("frac spread", f"{signed(fr['frac_spread_usd_mmbtu'][-1])} $/MMBtu {fr['regime']}" if fr["status"] == "measured" else "pending (no ethane collector)")
    kv.add_row("MB − Conway", f"{signed(hs['spread_mb_minus_conway'][-1])} ¢/gal" if hs["status"] == "measured" else "pending (no Conway collector)")
    if fw["status"] == "measured":
        pts = " ".join(f"{p['contract']} {p['value']:.3f}" for p in fw["points"])
        kv.add_row("forward curve", Text(f"{fw['regime']}" + (f" · STALE as of {fw['as_of_date']}" if fw["stale"] else ""), style=DIM if fw["stale"] else FG))
        kv.add_row("", Text(pts, style=DIM))
    else:
        kv.add_row("forward curve", "pending")
    return panel(Group(tb, Text(""), kv), "Pricing output & relative value")


def elements_panel(s: dict) -> Panel:
    dv = s["derived"]
    kv = Table.grid(padding=(0, 2), expand=True)
    kv.add_column(style=DIM)
    kv.add_column(justify="right")
    kv.add_row("shale gas, six basins", fmt(dv["shale_production_total_bcfd"]["value"], 1, "Bcf/d"))
    st = dv["storage_total_bcf"]
    kv.add_row("working gas in storage", f"{fmt(st['value'], 0, 'Bcf')} · {st['date'] or '—'}")
    hd = dv["hdd_anomaly"]
    kv.add_row("CONUS HDD vs 30-yr normal", f"{signed(hd['value'], 1)} · {hd['date'] or '—'}")
    for g in s["drivers"]:
        if g["group"] == "production":
            kv.add_row("by basin", Text("  ".join(f"{short(i['agent_id']).replace('Prod ', '')} {fmt(i['value'], 1)}" for i in g["items"] if i["value"] is not None), style=FG))
    al = Table.grid(padding=(0, 1))
    al.add_column(width=6)
    al.add_column()
    for a in s["alerts"]:
        al.add_row(Text(a["level"].upper(), style=GOLD if a["level"] == "watch" else DIM), Text(a["text"]))
    return panel(Group(kv, Text(""), al), "Production elements & active alerts")


def flows_panel(s: dict) -> Panel:
    g = s["geo"]
    tb = Table(box=None, expand=True, padding=(0, 1), header_style=DIM)
    tb.add_column("corridor / meter")
    tb.add_column("status", justify="right")
    lng = [i for grp in s["drivers"] if grp["group"] == "lng" for i in grp["items"]]
    for i in lng:
        tb.add_row(Text(short(i["agent_id"]).replace(" Flow", ""), style=MUTE if i["value"] is None else FG),
                   Text("pending" if i["value"] is None else fmt(i["value"], 0, i.get("unit", "")), style=MUTE if i["value"] is None else FG))
    for a in [x for x in s["sources"] if x["agent_id"].startswith("Agent_Flow_")]:
        tb.add_row(Text(short(a["agent_id"]).replace("Flow ", ""), style=MUTE), Text("pending" if a["status"] != "collected" else "collected", style=MUTE))
    nt = s.get("notices", {})
    note = Text(f"flow meters {g['flow_agents_collected']}/{g['flow_agents_total']} · critical notices 7d: {nt.get('last_7_days', 0)} "
                f"({', '.join(f'{k} {v}' for k, v in sorted(nt.get('by_pipeline_7d', {}).items()))}) · force majeure 30d: {len(nt.get('force_majeure_30d', []))}", style=GOLD)
    recent = Table.grid(padding=(0, 1))
    recent.add_column(style=DIM, no_wrap=True, min_width=16)
    recent.add_column(no_wrap=True, overflow="ellipsis")
    for n in nt.get("recent", [])[:5]:
        recent.add_row(f"{n['posted'][5:16].replace('T', ' ')} {n['pipeline']}", n["title"])
    return panel(Group(note, recent, tb), "Regional flows & pipeline alerts")


def sources_panel(s: dict, limit: int) -> Panel:
    tb = Table(box=None, expand=True, padding=(0, 1), header_style=DIM)
    for col, j in (("agent", "left"), ("status", "left"), ("provenance", "left"), ("available", "left"), ("age", "right"), ("quality", "left"), ("payload", "left")):
        tb.add_column(col, justify=j, no_wrap=True)
    rows = [r for r in s["sources"] if r["contributes"] or not r["in_roster"]]
    rows.sort(key=lambda r: (r["status"] != "collected", r["agent_id"]))
    for r in rows[:limit]:
        pend = r["status"] != "collected"
        st = MUTE if pend else FG
        tb.add_row(Text(short(r["agent_id"]), style=st), Text("pending" if pend else "collected", style=st),
                   Text(r["provenance"] or "no data", style=GOLD if r["provenance"] == "unverified_seed" else st),
                   Text((r["available_timestamp"] or "—").replace("T", " ")[:16], style=st),
                   Text(f"{r['age_days']:.0f}d" if r["age_days"] is not None else "—", style=DIM),
                   Text((r["quality_status"] or "—")[:28], style=DIM),
                   Text(("✓ " if r["raw_payload_archived"] else "  ") + ((r["raw_payload_hash"] or "—")[:10]), style=DIM))
    p = s["platform"]
    head = Text(f"{p['roster_agents_collected']}/{p['roster_agents']} roster agents collected · {p['pit_rows']:,} PIT rows · {p['raw_payloads']} raw payloads"
                f" · showing {min(limit, len(rows))}/{len(rows)} contributing", style=DIM)
    return panel(Group(head, tb), "Source availability transparency")


def header(s: dict, url: str) -> Text:
    t = Text()
    t.append(" NGL.JOEYSVAULT.APP ", style="reverse " + FG)
    t.append(f"  product ", style=DIM)
    for p in s["products"]:
        on = p["id"] == s["active_product"]
        t.append(f" {p['code']} ", style=("reverse " + FG) if on else (MUTE if p["status"] == "pending_collector" else FG))
    t.append("   timeframe ", style=DIM)
    for tf in s["timeframes"]:
        t.append(f" {tf['id']} ", style=("reverse " + FG) if tf["id"] == s["timeframe"]["id"] else FG)
    t.append(f"   as of {s['as_of']} · {s['schema']}", style=DIM)
    return t


def frame(s: dict, url: str, width: int, height: int, basemap: dict | None) -> Layout:
    root = Layout()
    root.split_column(Layout(name="head", size=1), Layout(name="hero", size=12), Layout(name="mid", ratio=1), Layout(name="bottom", size=max(8, height // 4)),
                      Layout(name="foot", size=1))
    root["head"].update(header(s, url))
    root["hero"].split_row(Layout(hero_panel(s, width * 3 // 5), ratio=3), Layout(fib_panel(s), ratio=2))
    left = max(40, int(width * 0.58))
    mid_h = max(10, height - 12 - max(8, height // 4) - 2)
    map_cols, map_rows = left - 4, max(6, mid_h - 2)
    geo = s["geo"]
    root["mid"].split_row(Layout(panel(render_map(s, map_cols, map_rows, basemap),
                                       f"North American energy hub · {sum(n['status'] == 'measured' for n in geo['nodes'])}/{len(geo['nodes'])} nodes with data"), size=left),
                          Layout(name="right"))
    root["mid"]["right"].split_column(Layout(pricing_panel(s), ratio=3), Layout(elements_panel(s), ratio=3))
    root["bottom"].split_row(Layout(sources_panel(s, max(3, max(8, height // 4) - 4)), ratio=3), Layout(flows_panel(s), ratio=2))
    root["foot"].update(Text(f" p/P product · t timeframe · r refresh · q quit · {url}  ·  ● measured  ○ no collector  ┄ schematic corridor", style=MUTE))
    return root


# ----------------------------------------------------------------------------- data
def fetch_state(url: str, product: str | None, timeframe: str, timeout: float = 20.0) -> dict:
    q = {"timeframe": timeframe}
    if product:
        q["product"] = product
    full = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(q)
    req = urllib.request.Request(full, headers={"User-Agent": "ngl-term/1", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        s = json.loads(r.read().decode())
    if s.get("schema") != SCHEMA:
        raise ValueError(f"unexpected schema {s.get('schema')!r}; this client renders {SCHEMA}")
    return s


def load_basemap() -> dict | None:
    try:
        return json.loads(BASEMAP.read_text())
    except Exception:  # noqa: BLE001
        return None


class Keys:
    """Single-key reads from a terminal without blocking; a no-op when stdin is not a TTY."""

    def __enter__(self):
        self.fd, self.old = None, None
        if sys.stdin.isatty():
            import termios
            import tty
            self.fd = sys.stdin.fileno()
            self.old = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)
        return self

    def read(self, timeout: float) -> str | None:
        if self.fd is None:
            time.sleep(timeout)
            return None
        r, _, _ = select.select([sys.stdin], [], [], timeout)
        return sys.stdin.read(1) if r else None

    def __exit__(self, *exc):
        if self.fd is not None:
            import termios
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--url", default=DEFAULT_URL, help="state.json URL (default %(default)s)")
    ap.add_argument("--product", choices=PRODUCTS, default=None, help="default: the product the pricing engine marks active")
    ap.add_argument("--timeframe", choices=TIMEFRAMES, default="seasonal")
    ap.add_argument("--refresh", type=float, default=60.0, help="seconds between refreshes (default %(default)s)")
    ap.add_argument("--once", action="store_true", help="render one frame and exit")
    ap.add_argument("--width", type=int, default=None)
    ap.add_argument("--height", type=int, default=None)
    a = ap.parse_args(argv)
    console = Console(width=a.width, height=a.height) if (a.width or a.height) else Console()
    basemap = load_basemap()
    product, timeframe = a.product, a.timeframe

    def draw():
        s = fetch_state(a.url, product, timeframe)
        w, h = console.size
        return s, frame(s, a.url, w, max(30, h), basemap)

    if a.once:
        try:
            _, lay = draw()
        except Exception as e:  # noqa: BLE001
            console.print(f"[{GOLD}]state unavailable:[/] {e}")
            return 2
        console.print(lay, height=max(30, console.size.height))
        return 0
    from rich.live import Live
    with Keys() as keys, Live(console=console, screen=True, auto_refresh=False) as live:
        s = None
        last = 0.0
        while True:
            if time.time() - last >= a.refresh:
                try:
                    s, lay = draw()
                    live.update(lay, refresh=True)
                except Exception as e:  # noqa: BLE001
                    live.update(Panel(Text(f"state unavailable: {e}\nretrying every {a.refresh:g}s", style=GOLD), border_style=FG, box=BOX), refresh=True)
                last = time.time()
            k = keys.read(0.25)
            if not k:
                continue
            cur = product or (s["active_product"] if s else PRODUCTS[0])
            if k in "qQ":
                return 0
            if k == "p":
                product = PRODUCTS[(PRODUCTS.index(cur) + 1) % len(PRODUCTS)]
            elif k == "P":
                product = PRODUCTS[(PRODUCTS.index(cur) - 1) % len(PRODUCTS)]
            elif k in "tT":
                timeframe = TIMEFRAMES[(TIMEFRAMES.index(timeframe) + 1) % len(TIMEFRAMES)]
            elif k not in "rR":
                continue
            last = 0.0


if __name__ == "__main__":
    sys.exit(main())
