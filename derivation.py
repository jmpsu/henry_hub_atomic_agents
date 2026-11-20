"""D-series: server-side derivation traces for every number on the page (docs/DRILLDOWN_SPEC.md, checklist D1-D-V7).

A trace is a tree of nodes built by THIS module from the same stored rows and the same engine functions that produce the displayed value
(`markets_engine`): the node's `value` is the engine's number, not a JavaScript reconstruction. Each node also carries what is needed to check it:

  op        how the value is formed from its operands or rows (leaf | constant | expr | mean | sum | std | max | min | ema | rsi | macd_signal | bw_percentile |
            polyfit | divergence | curve_regime | count)
  expr      for op=expr, a Python arithmetic expression over the operands' `var` names
  rows      for window ops, EVERY input row of the window ({d, v}); large windows are paged by the API
  operands  [{name (TeX symbol), var, id}] each of which is itself a node, down to leaves
  leaf      L4: the stored PIT row (agent_id, series, value, unit, t_target, t_published, t_retrieved, t_available, provenance, quality_status, source_id,
            intended_source, raw_payload_hash and a link to the archived payload when it exists)

`evaluate(nodes, id)` recomputes a node from its leaves using ONLY its op/expr and rows, written independently of the engine, so a test can assert that the
recomputed number equals the displayed one. A pending operand makes its parent WITHHELD (value None, never a number): the leaf says `no collector: <agent>`.
Everything is read-only and limited to the point-in-time cutoff (every leaf has t_available <= cutoff). Window ops that the engine implements with a shared
rule (curve regime, the swing/divergence scan) are recomputed with that same rule and listed in SHARED_RULE_OPS; they are the only ones not recomputed independently."""
from __future__ import annotations

import math
import re
import sqlite3
from datetime import datetime, timedelta, timezone

import numpy as np

import frac_module
import markets_engine as me

WITHHELD = "withheld"
DERIVED_OK = {"Agent_Weather_30YrNormal_HDD", "Agent_LNGFeedgas_P10", "Agent_LNGFeedgas_P50", "Agent_LNGFeedgas_P90"}      # a derived series the engine reads without the measured-only filter; its leaf shows the real provenance (extracted_estimate)
PAGE = 60
SHARED_RULE_OPS = {"curve_regime"}      # recomputed with me.curve_regime (a categorical rule over the points); every other op is recomputed independently


# ----------------------------------------------------------------------------- formatting
def num(v, d: int = 4) -> str:
    if v is None:
        return "withheld"
    if isinstance(v, str):
        return v
    if isinstance(v, bool):
        return str(v).lower()
    s = f"{v:,.{d}f}" if abs(v) < 1e15 else str(v)
    return s.rstrip("0").rstrip(".") if "." in s and d > 3 else s


def tx(template: str, **vals) -> str:
    """Fill «name» placeholders of a TeX template with numbers (so TeX braces never collide with Python formatting)."""
    out = template
    for k, v in vals.items():
        out = out.replace(f"«{k}»", num(v, 4) if not isinstance(v, tuple) else num(v[0], v[1]))
    return out


# ----------------------------------------------------------------------------- independent evaluators (pure python on the node's rows)
def _mean(v):
    return sum(v) / len(v)


def _std(v):
    m = _mean(v)
    return math.sqrt(sum((x - m) ** 2 for x in v) / len(v))


def _ema_series(v, span):
    k, out = 2.0 / (span + 1.0), [v[0]]
    for x in v[1:]:
        out.append(k * x + (1 - k) * out[-1])
    return out


def _rsi_series(v, period=14):
    out = [None] * len(v)
    if len(v) <= period:
        return out
    d = [b - a for a, b in zip(v, v[1:])]
    g, l = [max(x, 0.0) for x in d], [max(-x, 0.0) for x in d]
    ag, al = sum(g[:period]) / period, sum(l[:period]) / period
    for i in range(period, len(d) + 1):
        if i > period:
            ag = (ag * (period - 1) + g[i - 1]) / period
            al = (al * (period - 1) + l[i - 1]) / period
        out[i] = 100.0 if al < 1e-12 else 100.0 - 100.0 / (1.0 + ag / al)
    return out


def _macd_series(v, fast=12, slow=26, signal=9):
    ef, es = _ema_series(v, fast), _ema_series(v, slow)
    line = [a - b for a, b in zip(ef, es)]
    sig = _ema_series(line, signal)
    return line, sig, [a - b for a, b in zip(line, sig)]


def _bw_series(v, window=20, k=2.0):
    out = []
    for i in range(window - 1, len(v)):
        w = v[i - window + 1:i + 1]
        m, s = _mean(w), _std(w)
        out.append((2 * k * s) / m * 100.0 if m != 0 else None)
    return out


def _percentile(v, pct):
    s = sorted(x for x in v if x is not None)
    if not s:
        return None
    pos = (len(s) - 1) * pct / 100.0
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def _swings(a, window=3):
    hi, lo = [], []
    for i in range(window, len(a) - window):
        seg = a[i - window:i + window + 1]
        if a[i] == max(seg) and a[i] > a[i - 1]:
            hi.append(i)
        if a[i] == min(seg) and a[i] < a[i - 1]:
            lo.append(i)
    return hi, lo


def _divergence(price, osc, window=5, lookback=80):
    p, o = price[-lookback:], osc[-lookback:]
    if len(p) < 30:
        return "none"
    hi, lo = _swings(p, window)
    hi, lo = [i for i in hi if o[i] is not None], [i for i in lo if o[i] is not None]
    if len(hi) >= 2 and p[hi[-1]] > p[hi[-2]] and o[hi[-1]] < o[hi[-2]]:
        return "bearish"
    if len(lo) >= 2 and p[lo[-1]] < p[lo[-2]] and o[lo[-1]] > o[lo[-2]]:
        return "bullish"
    return "none"


_SAFE = {"abs": abs, "min": min, "max": max, "sum": sum, "len": len, "round": round, "math": math}


def evaluate(nodes: dict, nid: str):
    """Recompute node `nid` from its leaves using only its own op / expr / rows. Returns None when any needed operand is withheld."""
    n = nodes[nid]
    if n["status"] == WITHHELD:
        return None
    op = n["op"]
    if op == "leaf":
        return n["leaf"]["value"]
    if op == "constant":
        return n["value"]
    if op == "expr":
        env = {}
        for o in n["operands"]:
            v = evaluate(nodes, o["id"])
            if v is None:
                return None
            env[o["var"]] = v
        return eval(n["expr"], {"__builtins__": {}, **_SAFE}, env)       # noqa: S307  (expressions are written in this file, never taken from a request)
    rows, p = n["rows"], n.get("params") or {}
    v = [r["v"] for r in rows]
    if op == "mean":
        return _mean([x for x in v if x is not None])
    if op == "sum":
        return sum(x for x in v if x is not None)
    if op == "count":
        return sum(1 for x in v if x)
    if op == "std":
        return _std(v)
    if op == "max":
        return max(x for x in v if x is not None)
    if op == "min":
        return min(x for x in v if x is not None)
    if op == "ema":
        return _ema_series(v, p["span"])[-1]
    if op == "rsi":
        return _rsi_series(v, p["period"])[-1]
    if op == "macd_signal":
        return _macd_series(v, p["fast"], p["slow"], p["signal"])[1][-1]
    if op == "bw_percentile":
        return _percentile(_bw_series(v, p["window"], p["k"]), p["pct"])
    if op == "polyfit":
        pts = [(r["i"], r["v"]) for r in rows]
        m, b = np.polyfit([x for x, _ in pts], [y for _, y in pts], 1)
        return float(m * p["n"] + b) if p["want"] == "end" else float(b) if p["want"] == "start" else float(m)
    if op == "divergence":
        osc = _rsi_series(v, 14) if p["which"] == "rsi" else _macd_series(v)[0]
        return _divergence(v, osc)
    if op == "curve_regime":
        return me.curve_regime([{"contract": r["d"], "value": r["v"]} for r in rows])
    raise ValueError(f"unknown op {op}")


# ----------------------------------------------------------------------------- the trace builder
class Trace:
    def __init__(self, db_path: str, product: str | None = None, timeframe: str = "seasonal", as_of: str | None = None):
        self.db_path = db_path
        self.cutoff = me.pit_cutoff(as_of)
        self.as_of = as_of
        self.conn = me._conn(db_path)
        self.product = product if product in me.PRODUCTS else me.active_product()
        self.timeframe = timeframe if timeframe in me.TIMEFRAMES else "seasonal"
        self.meta, self.n = me.PRODUCTS[self.product], me.TIMEFRAMES[self.timeframe]["sessions"]
        self.nodes: dict[str, dict] = {}
        self._series: dict[str, list] = {}
        self.rmeta = me._roster_meta()
        self.payloads = {r[0] for r in self.conn.execute("SELECT raw_payload_hash FROM raw_payloads")}
        self._state = None

    def close(self):
        self.conn.close()

    # ---- data access
    def series(self, agent: str) -> list:
        if agent not in self._series:
            self._series[agent] = me.load_series(self.conn, agent, self.cutoff)
        return self._series[agent]

    @property
    def state(self) -> dict:
        if self._state is None:
            self._state = me.build_state(self.db_path, self.product, self.timeframe, self.as_of)
        return self._state

    # ---- node construction
    def add(self, nid, label, op, *, value=None, unit="", tex="", symbols=None, operands=None, steps=None, tex_sub="", rows=None, stats=None, params=None, decimals=3,
            status="ok", note="", expr=None, leaf=None, text="", fields=None):
        self.nodes[nid] = {"id": nid, "label": label, "op": op, "value": value, "unit": unit, "decimals": decimals, "formula_tex": tex, "symbols": symbols or [], "operands": operands or [],
                           "steps": steps or [], "tex_sub": tex_sub, "rows": rows, "stats": stats, "params": params or {}, "status": status, "note": note, "expr": expr, "leaf": leaf,
                           "text": text, "fields": fields}
        return nid

    def operand(self, name, var, nid):
        return {"name": name, "var": var, "id": nid}

    def const(self, nid, label, value, unit, meaning, kind="assumption", source=""):
        return self.add(nid, label, "constant", value=value, unit=unit, decimals=4, text=f"{kind}: {meaning}" + (f" ({source})" if source else ""), params={"kind": kind, "source": source})

    def pending_leaf(self, agent: str, date: str | None = None) -> str:
        nid = f"leaf:{agent}:{date or 'latest'}"
        rm = self.rmeta.get(agent) or {}
        return self.add(nid, f"{agent}", "leaf", status=WITHHELD, unit="", text=f"no collector: {agent}", note=f"No collector writes this series, or no measured row exists at the cutoff. Intended source: {rm.get('source') or 'not assigned'}. Nothing is filled in.",
                        leaf={"agent_id": agent, "value": None, "intended_source": rm.get("source"), "series": rm.get("series")})

    def leaf(self, agent: str, date: str | None = None) -> str:
        """The stored PIT row for `agent` on `date` (latest if None): measured rows only, vintage available at the cutoff."""
        s = self.series(agent)
        derived = agent in DERIVED_OK
        if date is None and s:
            date = s[-1][0]
        if date is None and derived:
            r0 = self.conn.execute("SELECT substr(target_timestamp,1,10) FROM pit_market_data WHERE agent_id=? AND available_timestamp<=? ORDER BY target_timestamp DESC, available_timestamp DESC LIMIT 1", (agent, self.cutoff)).fetchone()
            date = r0[0] if r0 else None
        if date is None and derived:
            return self.pending_leaf(agent, None)
        if not derived and (not s or date is None or not any(r[0] == date for r in s)):
            return self.pending_leaf(agent, date)
        nid = f"leaf:{agent}:{date}"
        if nid in self.nodes:
            return nid
        r = self.conn.execute(
            "SELECT agent_id, series_id, value, unit, target_timestamp, published_timestamp, retrieved_timestamp, available_timestamp, provenance, quality_status, source_id, raw_payload_hash, source_url "
            "FROM pit_market_data WHERE agent_id=? AND substr(target_timestamp,1,10)=? AND available_timestamp<=? AND (?=1 OR COALESCE(provenance,'measured')='measured') "
            "ORDER BY available_timestamp DESC LIMIT 1", (agent, date, self.cutoff, 1 if derived else 0)).fetchone()
        if not r:
            return self.pending_leaf(agent, date)
        rm = self.rmeta.get(agent) or {}
        h = r[11]
        leaf = {"agent_id": r[0], "series": rm.get("series") or r[1], "series_id": r[1], "value": r[2], "unit": r[3], "t_target": r[4], "t_published": r[5] or None, "t_retrieved": r[6],
                "t_available": r[7], "provenance": r[8] or "measured", "quality_status": r[9], "source_id": r[10], "intended_source": rm.get("source"), "raw_payload_hash": h or None,
                "raw_url": f"/api/raw/{h}" if h and h in self.payloads else None, "source_url": r[12]}
        note = ("A stored MODEL output (provenance bootstrapped_physical_proxy): a 1,000-iteration block bootstrap anchored on EIA monthly exports (lng_feedgas.py). It is a point-in-time row, "
                "not re-derived by this evaluator; the method and inputs are in lng_feedgas.py and runtime/lng_feedgas.json.") if agent.startswith("Agent_LNGFeedgas_") else ""
        return self.add(nid, f"{agent} {date}", "leaf", value=r[2], unit=r[3] or "", decimals=4, leaf=leaf, text=f"stored row {date}", note=note)

    def doc_leaf(self, doc_id: str) -> str:
        r = self.conn.execute("SELECT id, domain, source_id, source_url, title, published_timestamp, available_timestamp, raw_payload_hash FROM documents WHERE id=? AND available_timestamp<=?",
                              (doc_id, self.cutoff)).fetchone()
        nid = f"doc:{doc_id}"
        if not r:
            return self.add(nid, doc_id, "leaf", status=WITHHELD, text=f"no document {doc_id} available at the cutoff", leaf={"agent_id": doc_id, "value": None})
        return self.add(nid, r[4], "leaf", value=1, unit="notice", text=r[4], leaf={"agent_id": r[0], "series": r[1], "value": 1, "unit": "notice", "t_target": r[5], "t_published": r[5],
                        "t_retrieved": None, "t_available": r[6], "provenance": "source_document", "quality_status": None, "source_id": r[2], "intended_source": r[2], "raw_payload_hash": r[7] or None,
                        "raw_url": f"/api/raw/{r[7]}" if r[7] and r[7] in self.payloads else None, "source_url": r[3]})

    def window(self, agent, dates, vals):
        return [{"d": d, "v": v} for d, v in zip(dates, vals)]

    def stats(self, vals):
        v = [x for x in vals if x is not None]
        return {"n": len(v), "sum": sum(v), "mean": _mean(v), "std": _std(v), "min": min(v), "max": max(v)} if v else None

    def expr_node(self, nid, label, expr, operands, *, value, unit="", tex="", symbols=None, tex_sub="", steps=None, decimals=3, note=""):
        """An op=expr node. If any operand is withheld, the node is withheld (the engine's value is dropped, never shown)."""
        ok = all(self.nodes[o["id"]]["status"] != WITHHELD for o in operands)
        miss = [self.nodes[o["id"]]["text"] for o in operands if self.nodes[o["id"]]["status"] == WITHHELD]
        return self.add(nid, label, "expr", value=value if ok else None, unit=unit, tex=tex, symbols=symbols, operands=operands, expr=expr, tex_sub=tex_sub, steps=steps, decimals=decimals,
                        status="ok" if ok else WITHHELD, note=note if ok else "withheld because an operand has no data: " + "; ".join(miss), text="" if ok else "withheld")

    def window_node(self, nid, label, op, agent, rows, *, value, unit="", tex="", symbols=None, params=None, decimals=3, steps=None, tex_sub="", note="", all_rows=None):
        vals = [r["v"] for r in rows]
        return self.add(nid, label, op, value=value, unit=unit, tex=tex, symbols=symbols, rows=rows, stats=self.stats(vals), params={**(params or {}), "agent": agent}, decimals=decimals,
                        steps=steps, tex_sub=tex_sub, note=note)

    # ---- view (one level, paged rows)
    def view(self, nid: str, offset: int = 0, limit: int = PAGE) -> dict:
        n = self.resolve(nid)
        if n is None:
            return {"error": f"unknown node {nid}"}
        rows = n["rows"]
        out = {k: n[k] for k in ("id", "label", "op", "unit", "decimals", "formula_tex", "symbols", "steps", "tex_sub", "stats", "params", "status", "note", "text", "leaf", "expr", "fields")}
        out["cutoff"] = self.cutoff
        out["value"] = n["value"]
        out["display"] = num(n["value"], n["decimals"]) if n["status"] != WITHHELD else WITHHELD
        out["operands"] = []
        for o in n["operands"]:
            c = self.nodes[o["id"]]
            out["operands"].append({"name": o["name"], "var": o["var"], "id": o["id"], "label": c["label"], "op": c["op"], "status": c["status"], "unit": c["unit"],
                                    "display": num(c["value"], c["decimals"]) if c["status"] != WITHHELD else WITHHELD, "text": c["text"]})
        if rows is not None:
            out["rows_total"], out["rows_offset"] = len(rows), offset
            if len(rows) <= PAGE and offset == 0:
                out["rows"] = rows
            else:
                off = max(0, len(rows) - limit) if offset < 0 else offset            # offset -1 = the newest page
                out["rows_offset"], out["rows"] = off, rows[off:off + limit]
        return out

    def resolve(self, nid: str):
        if nid in self.nodes:
            return self.nodes[nid]
        if nid.startswith("leaf:"):
            _, agent, date = nid.split(":", 2)
            self.leaf(agent, None if date == "latest" else date)
        elif nid.startswith("doc:"):
            self.doc_leaf(nid[4:])
        return self.nodes.get(nid)

    def metric(self, mid: str) -> str:
        base, _, arg = mid.partition(":")
        fn = METRICS.get(base)
        if fn is None:
            raise KeyError(mid)
        return fn(self, arg)


# ----------------------------------------------------------------------------- metric builders
def _price_inputs(t: Trace):
    """(agent, dates, vals, window slice) of the active product exactly as build_state uses them, or None while pending."""
    agent = t.meta["agent_id"]
    full = t.series(agent)
    if len(full) < 30:
        return None
    dates, vals = [r[0] for r in full], [r[1] for r in full]
    return agent, dates, vals, slice(max(0, len(vals) - t.n), len(vals))


def _pending_metric(t: Trace, mid: str, label: str, agent: str, unit: str = "") -> str:
    leaf = t.pending_leaf(agent)
    return t.add(mid, label, "expr", status=WITHHELD, unit=unit, operands=[t.operand("x", "x", leaf)], expr="x", text="withheld",
                 note=f"withheld: no collector: {agent}. Nothing is estimated.")


def m_price(t: Trace, arg: str) -> str:
    p = _price_inputs(t)
    if p is None:
        return _pending_metric(t, "price", f"{t.meta['label']} price", t.meta["agent_id"], t.meta["unit"])
    agent, dates, vals, _ = p
    return t.leaf(agent, dates[-1])


def _change(t: Trace, mid: str, label: str, back: int, pct: bool) -> str:
    p = _price_inputs(t)
    if p is None:
        return _pending_metric(t, mid, label, t.meta["agent_id"], "%" if pct else t.meta["unit"])
    agent, dates, vals, _ = p
    j = len(vals) - 1 - back if len(vals) > back else 0
    last, prev = t.leaf(agent, dates[-1]), t.leaf(agent, dates[j])
    L, P = vals[-1], vals[j]
    ops = [t.operand("P_t", "p", last), t.operand(f"P_{{t-{back}}}", "q", prev)]
    sym = [{"sym": "P_t", "meaning": f"{t.meta['label']} on the latest session {dates[-1]}", "unit": t.meta["unit"]}, {"sym": f"P_{{t-{back}}}", "meaning": f"the close {back} session(s) earlier ({dates[j]})", "unit": t.meta["unit"]}]
    if pct:
        v = (L / P - 1) * 100 if P else None
        return t.expr_node(mid, label, "(p / q - 1) * 100", ops, value=v, unit="%", decimals=2, tex=rf"\Delta_{{{back}d}}\% = \left(\frac{{P_t}}{{P_{{t-{back}}}}} - 1\right) \times 100", symbols=sym,
                           tex_sub=tx(r"\left(\frac{«p»}{«q»} - 1\right) \times 100", p=L, q=P), steps=[tx(r"= \left(«r» - 1\right) \times 100", r=(L / P, 6)), tx(r"= «v»\%", v=(v, 3))])
    v = L - P
    return t.expr_node(mid, label, "p - q", ops, value=v, unit=t.meta["unit"], tex=rf"\Delta_{{{back}d}} = P_t - P_{{t-{back}}}", symbols=sym, tex_sub=tx(r"«p» - «q»", p=L, q=P), steps=[tx(r"= «v»", v=(v, 4))])


def m_change_1d(t, a): return _change(t, "change_1d", "1-day change", 1, False)
def m_change_1d_pct(t, a): return _change(t, "change_1d_pct", "1-day change %", 1, True)
def m_change_5d(t, a): return _change(t, "change_5d", "5-day change", 5, False)
def m_change_5d_pct(t, a): return _change(t, "change_5d_pct", "5-day change %", 5, True)


def _window_extreme(t: Trace, mid: str, label: str, op: str) -> str:
    p = _price_inputs(t)
    if p is None:
        return _pending_metric(t, mid, label, t.meta["agent_id"], t.meta["unit"])
    agent, dates, vals, v = p
    rows = t.window(agent, dates[v], vals[v])
    val = max(vals[v]) if op == "max" else min(vals[v])
    sym = "\\max" if op == "max" else "\\min"
    return t.window_node(mid, label, op, agent, rows, value=val, unit=t.meta["unit"], tex=rf"{sym}_{{i \in W}} P_i", symbols=[{"sym": "W", "meaning": f"the {len(rows)} sessions shown ({t.timeframe})", "unit": ""}, {"sym": "P_i", "meaning": "daily close", "unit": t.meta["unit"]}],
                         tex_sub=tx(rf"{sym}\left(«a», \ldots, «b»\right)", a=rows[0]["v"], b=rows[-1]["v"]), steps=[tx(rf"= «v»", v=(val, 4))])


def m_window_high(t, a): return _window_extreme(t, "window_high", "Window high", "max")
def m_window_low(t, a): return _window_extreme(t, "window_low", "Window low", "min")


def _sma_node(t: Trace, mid: str, label: str, w: int) -> str:
    p = _price_inputs(t)
    if p is None or len(p[2]) < w:
        return _pending_metric(t, mid, label, t.meta["agent_id"], t.meta["unit"]) if p is None else \
            t.add(mid, label, "mean", status=WITHHELD, text="withheld", note=f"withheld: only {len(p[2])} sessions stored, {w} needed. Nothing is estimated.")
    agent, dates, vals, _ = p
    rows = t.window(agent, dates[-w:], vals[-w:])
    val = float(me.sma(vals, w)[-1])
    st = t.stats(vals[-w:])
    return t.window_node(mid, label, "mean", agent, rows, value=val, unit=t.meta["unit"], tex=rf"\mathrm{{SMA}}_{{{w}}} = \frac{{1}}{{{w}}}\sum_{{i=0}}^{{{w - 1}}} P_{{t-i}}",
                         symbols=[{"sym": "P_{t-i}", "meaning": f"the last {w} daily closes ({dates[-w]} to {dates[-1]})", "unit": t.meta["unit"]}],
                         tex_sub=tx(r"\frac{«s»}{" + str(w) + "}", s=(st["sum"], 4)), steps=[tx(r"= «v»", v=(val, 4))], params={"window": w})


def m_sma20(t, a): return _sma_node(t, "sma20", "SMA 20", 20)
def m_sma50(t, a): return _sma_node(t, "sma50", "SMA 50", 50)
def m_sma200(t, a): return _sma_node(t, "sma200", "SMA 200", 200)


def _cmp_node(t: Trace, mid: str, label: str, a_id: str, b_id: str, a_name: str, b_name: str, true_label: str, false_label: str, value: str, tex_word: str) -> str:
    ops = [t.operand(a_name, "a", a_id), t.operand(b_name, "b", b_id)]
    va, vb = t.nodes[a_id]["value"], t.nodes[b_id]["value"]
    return t.expr_node(mid, label, f"'{true_label}' if a > b else '{false_label}'", ops, value=value, decimals=0, tex=rf"\text{{{tex_word}}}: \; {a_name} > {b_name} \Rightarrow \text{{{true_label}}}, \text{{ else }} \text{{{false_label}}}",
                       symbols=[{"sym": a_name, "meaning": t.nodes[a_id]["label"], "unit": t.meta["unit"]}, {"sym": b_name, "meaning": t.nodes[b_id]["label"], "unit": t.meta["unit"]}],
                       tex_sub=(num(va, 3) + " > " + num(vb, 3)) if va is not None and vb is not None else "", steps=[rf"\Rightarrow \text{{{value}}}"] if value else [])


def m_trend(t, a):
    p = _price_inputs(t)
    last = m_price(t, "")
    s200 = m_sma200(t, "")
    val = None
    if p and t.nodes[s200]["status"] != WITHHELD:
        val = "above_200dma" if p[2][-1] > float(me.sma(p[2], 200)[-1]) else "below_200dma"
    return _cmp_node(t, "trend", "Trend vs 200-day average", last, s200, "P_t", "\\mathrm{SMA}_{200}", "above_200dma", "below_200dma", val, "Trend")


def m_ma_regime(t, a):
    s50, s200 = m_sma50(t, ""), m_sma200(t, "")
    val = None
    if t.nodes[s50]["status"] != WITHHELD and t.nodes[s200]["status"] != WITHHELD:
        val = "golden" if t.nodes[s50]["value"] > t.nodes[s200]["value"] else "death"
    return _cmp_node(t, "ma_regime", "50/200 regime", s50, s200, "\\mathrm{SMA}_{50}", "\\mathrm{SMA}_{200}", "golden", "death", val, "Regime")


def _history_node(t: Trace, mid: str, label: str, op: str, value, params: dict, tex: str, symbols: list, decimals: int, unit: str = "", steps=None, tex_sub=""):
    p = _price_inputs(t)
    agent, dates, vals, _ = p
    rows = t.window(agent, dates, vals)
    return t.window_node(mid, label, op, agent, rows, value=value, unit=unit, tex=tex, symbols=symbols, params=params, decimals=decimals, steps=steps, tex_sub=tex_sub)


def m_rsi14(t, a):
    p = _price_inputs(t)
    if p is None or len(p[2]) <= 14:
        return _pending_metric(t, "rsi14", "RSI 14", t.meta["agent_id"])
    vals = p[2]
    val = float(me.rsi(vals)[-1])
    ser = _rsi_series(vals)
    return _history_node(t, "rsi14", "RSI 14", "rsi", val, {"period": 14}, r"\mathrm{RSI} = 100 - \frac{100}{1 + \overline{G}/\overline{L}}",
                         [{"sym": r"\overline{G}", "meaning": "Wilder-smoothed average gain over 14 sessions (seed: mean of the first 14 gains, then (prev x 13 + gain) / 14)", "unit": t.meta["unit"]},
                          {"sym": r"\overline{L}", "meaning": "Wilder-smoothed average loss, same smoothing", "unit": t.meta["unit"]}], 1,
                         steps=[tx(r"= 100 - \frac{100}{1 + RS} = «v»", v=(val, 3)), rf"\text{{computed over all {len(vals)} stored closes; the table lists every one}}"],
                         tex_sub=rf"\text{{Wilder smoothing over }} {len(vals)} \text{{ closes (period 14)}}")


def _ema_node(t: Trace, mid: str, span: int) -> str:
    p = _price_inputs(t)
    vals = p[2]
    val = float(me.ema(vals, span)[-1])
    return _history_node(t, mid, f"EMA {span}", "ema", val, {"span": span}, rf"\mathrm{{EMA}}_t = k P_t + (1-k)\,\mathrm{{EMA}}_{{t-1}}, \quad k = \frac{{2}}{{{span}+1}}",
                         [{"sym": "k", "meaning": f"smoothing factor 2/({span}+1)", "unit": ""}, {"sym": r"\mathrm{EMA}_0", "meaning": "the first stored close", "unit": t.meta["unit"]}], 4, t.meta["unit"],
                         steps=[tx(r"= «v»", v=(val, 5))], tex_sub=tx(r"k = «k»", k=(2 / (span + 1), 6)))


def m_macd_line(t, a):
    p = _price_inputs(t)
    if p is None:
        return _pending_metric(t, "macd_line", "MACD line", t.meta["agent_id"])
    e12, e26 = _ema_node(t, "ema12", 12), _ema_node(t, "ema26", 26)
    v = float(me.macd(p[2])["line"][-1])
    ops = [t.operand(r"\mathrm{EMA}_{12}", "f", e12), t.operand(r"\mathrm{EMA}_{26}", "s", e26)]
    return t.expr_node("macd_line", "MACD line", "f - s", ops, value=v, unit=t.meta["unit"], decimals=3, tex=r"\mathrm{MACD} = \mathrm{EMA}_{12} - \mathrm{EMA}_{26}",
                       symbols=[{"sym": r"\mathrm{EMA}_{12}", "meaning": "12-session exponential average of the close", "unit": t.meta["unit"]}, {"sym": r"\mathrm{EMA}_{26}", "meaning": "26-session exponential average", "unit": t.meta["unit"]}],
                       tex_sub=tx(r"«f» - «s»", f=(t.nodes[e12]["value"], 5), s=(t.nodes[e26]["value"], 5)), steps=[tx(r"= «v»", v=(v, 5))])


def m_macd_signal(t, a):
    p = _price_inputs(t)
    if p is None:
        return _pending_metric(t, "macd_signal", "MACD signal", t.meta["agent_id"])
    v = float(me.macd(p[2])["signal"][-1])
    return _history_node(t, "macd_signal", "MACD signal", "macd_signal", v, {"fast": 12, "slow": 26, "signal": 9}, r"\mathrm{Signal} = \mathrm{EMA}_{9}(\mathrm{MACD}_t)",
                         [{"sym": r"\mathrm{MACD}_t", "meaning": "the MACD line for every stored session (EMA12 - EMA26 of the close)", "unit": t.meta["unit"]}], 3, t.meta["unit"], steps=[tx(r"= «v»", v=(v, 5))],
                         tex_sub=rf"\mathrm{{EMA}}_9 \text{{ of the MACD line over {len(p[2])} sessions}}")


def m_macd_hist(t, a):
    p = _price_inputs(t)
    if p is None:
        return _pending_metric(t, "macd_hist", "MACD histogram", t.meta["agent_id"])
    line, sig = m_macd_line(t, ""), m_macd_signal(t, "")
    v = float(me.macd(p[2])["hist"][-1])
    ops = [t.operand(r"\mathrm{MACD}", "l", line), t.operand(r"\mathrm{Signal}", "s", sig)]
    return t.expr_node("macd_hist", "MACD histogram", "l - s", ops, value=v, unit=t.meta["unit"], decimals=3, tex=r"\mathrm{Hist} = \mathrm{MACD} - \mathrm{Signal}",
                       symbols=[{"sym": r"\mathrm{MACD}", "meaning": "MACD line", "unit": t.meta["unit"]}, {"sym": r"\mathrm{Signal}", "meaning": "9-session EMA of the MACD line", "unit": t.meta["unit"]}],
                       tex_sub=tx(r"«l» - «s»", l=(t.nodes[line]["value"], 5), s=(t.nodes[sig]["value"], 5)), steps=[tx(r"= «v»", v=(v, 5))])


def _bb(t: Trace):
    p = _price_inputs(t)
    if p is None or len(p[2]) < 20:
        return None
    agent, dates, vals, _ = p
    rows = t.window(agent, dates[-20:], vals[-20:])
    b = me.bollinger(vals)
    mid = m_sma20(t, "")
    sig = t.window_node("bb_sigma", "Bollinger sigma", "std", agent, rows, value=float(np.std(vals[-20:])), unit=t.meta["unit"], tex=r"\sigma = \sqrt{\frac{1}{20}\sum_{i=0}^{19}(P_{t-i}-\mu)^2}",
                        symbols=[{"sym": r"\mu", "meaning": "the 20-session mean (SMA 20)", "unit": t.meta["unit"]}, {"sym": "P_{t-i}", "meaning": "the last 20 daily closes", "unit": t.meta["unit"]}],
                        decimals=4, steps=[tx(r"\sigma = «v»", v=(float(np.std(vals[-20:])), 5))], params={"window": 20})
    return agent, vals, b, mid, sig


def m_bb_upper(t, a):
    r = _bb(t)
    if r is None:
        return _pending_metric(t, "bb_upper", "Bollinger upper", t.meta["agent_id"], t.meta["unit"])
    agent, vals, b, mid, sig = r
    k = t.const("bb_k", "Bollinger multiplier k", 2.0, "", "standard deviations either side of the mean", "assumption", "me.bollinger default")
    return t.expr_node("bb_upper", "Bollinger upper band", "mu + k * sd", [t.operand(r"\mu", "mu", mid), t.operand("k", "k", k), t.operand(r"\sigma", "sd", sig)], value=float(b["upper"][-1]), unit=t.meta["unit"], decimals=3,
                       tex=r"U = \mu + k\,\sigma", symbols=[{"sym": r"\mu", "meaning": "SMA 20", "unit": t.meta["unit"]}, {"sym": "k", "meaning": "2 standard deviations", "unit": ""}, {"sym": r"\sigma", "meaning": "population standard deviation of the last 20 closes", "unit": t.meta["unit"]}],
                       tex_sub=tx(r"«mu» + «k» \times «sd»", mu=(t.nodes[mid]["value"], 4), k=2, sd=(t.nodes[sig]["value"], 4)), steps=[tx(r"= «v»", v=(float(b["upper"][-1]), 4))])


def m_bb_lower(t, a):
    r = _bb(t)
    if r is None:
        return _pending_metric(t, "bb_lower", "Bollinger lower", t.meta["agent_id"], t.meta["unit"])
    agent, vals, b, mid, sig = r
    k = t.const("bb_k", "Bollinger multiplier k", 2.0, "", "standard deviations either side of the mean", "assumption", "me.bollinger default")
    return t.expr_node("bb_lower", "Bollinger lower band", "mu - k * sd", [t.operand(r"\mu", "mu", mid), t.operand("k", "k", k), t.operand(r"\sigma", "sd", sig)], value=float(b["lower"][-1]), unit=t.meta["unit"], decimals=3,
                       tex=r"L = \mu - k\,\sigma", symbols=[{"sym": r"\mu", "meaning": "SMA 20", "unit": t.meta["unit"]}, {"sym": "k", "meaning": "2 standard deviations", "unit": ""}, {"sym": r"\sigma", "meaning": "population standard deviation of the last 20 closes", "unit": t.meta["unit"]}],
                       tex_sub=tx(r"«mu» - «k» \times «sd»", mu=(t.nodes[mid]["value"], 4), k=2, sd=(t.nodes[sig]["value"], 4)), steps=[tx(r"= «v»", v=(float(b["lower"][-1]), 4))])


def m_bandwidth(t, a):
    r = _bb(t)
    if r is None:
        return _pending_metric(t, "bandwidth", "Bollinger bandwidth", t.meta["agent_id"], "%")
    agent, vals, b, mid, sig = r
    k = t.const("bb_k", "Bollinger multiplier k", 2.0, "", "standard deviations either side of the mean", "assumption", "me.bollinger default")
    return t.expr_node("bandwidth", "Bollinger bandwidth", "2 * k * sd / mu * 100", [t.operand("k", "k", k), t.operand(r"\sigma", "sd", sig), t.operand(r"\mu", "mu", mid)], value=float(b["bandwidth_pct"][-1]), unit="%", decimals=1,
                       tex=r"BW = \frac{2\,k\,\sigma}{\mu} \times 100", symbols=[{"sym": r"\mu", "meaning": "SMA 20", "unit": t.meta["unit"]}, {"sym": r"\sigma", "meaning": "std of the last 20 closes", "unit": t.meta["unit"]}, {"sym": "k", "meaning": "2", "unit": ""}],
                       tex_sub=tx(r"\frac{2 \times «k» \times «sd»}{«mu»} \times 100", k=2, sd=(t.nodes[sig]["value"], 4), mu=(t.nodes[mid]["value"], 4)), steps=[tx(r"= «v»\%", v=(float(b["bandwidth_pct"][-1]), 3))])


def m_squeeze(t, a):
    r = _bb(t)
    if r is None:
        return _pending_metric(t, "squeeze", "Bollinger squeeze", t.meta["agent_id"])
    agent, vals, b, mid, sig = r
    bw = m_bandwidth(t, "")
    p = _price_inputs(t)
    rows = t.window(agent, p[1], vals)
    thr = t.window_node("squeeze_threshold", "Squeeze threshold (20th percentile of bandwidth)", "bw_percentile", agent, rows, value=b["squeeze_threshold"], unit="%", decimals=3,
                        tex=r"T = P_{20}\left(BW_{1}, \ldots, BW_{n}\right)", symbols=[{"sym": "BW_i", "meaning": "the bandwidth at every stored session with a full 20-session window", "unit": "%"}, {"sym": "P_{20}", "meaning": "20th percentile, linear interpolation", "unit": ""}],
                        params={"window": 20, "k": 2.0, "pct": 20.0}, steps=[tx(r"T = «v»\%", v=(b["squeeze_threshold"], 4))])
    val = bool(b["squeeze"][-1])
    return t.expr_node("squeeze", "Bollinger squeeze flag", "bw <= thr", [t.operand("BW", "bw", bw), t.operand("T", "thr", thr)], value=val, decimals=0, tex=r"\text{squeeze} \iff BW \le T",
                       symbols=[{"sym": "BW", "meaning": "latest bandwidth", "unit": "%"}, {"sym": "T", "meaning": "20th percentile of the bandwidth history", "unit": "%"}],
                       tex_sub=f"{num(t.nodes[bw]['value'], 3)} \\le {num(b['squeeze_threshold'], 3)}", steps=[rf"\Rightarrow \text{{{str(val).lower()}}}"])


def _fib(t: Trace):
    p = _price_inputs(t)
    if p is None:
        return None
    agent, dates, vals, v = p
    vd, vv = dates[v], vals[v]
    if len(vv) < 2:
        return None
    f = me.fibonacci(vd, vv)
    rows = t.window(agent, vd, vv)
    hi = t.window_node("fib_high", "Swing high", "max", agent, rows, value=f["swing_high"], unit=t.meta["unit"], tex=r"H = \max_{i \in W} P_i", symbols=[{"sym": "W", "meaning": f"the {len(vv)} sessions shown", "unit": ""}],
                       decimals=4, steps=[tx(r"H = «h»\text{ on } " + f["swing_high_date"], h=(f["swing_high"], 4))], note=f"occurs on {f['swing_high_date']}")
    lo = t.window_node("fib_low", "Swing low", "min", agent, rows, value=f["swing_low"], unit=t.meta["unit"], tex=r"Lw = \min_{i \in W} P_i", symbols=[{"sym": "W", "meaning": f"the {len(vv)} sessions shown", "unit": ""}],
                       decimals=4, steps=[tx(r"Lw = «l»\text{ on } " + f["swing_low_date"], l=(f["swing_low"], 4))], note=f"occurs on {f['swing_low_date']}")
    span = t.expr_node("fib_span", "Swing range", "h - lw", [t.operand("H", "h", hi), t.operand("Lw", "lw", lo)], value=f["swing_high"] - f["swing_low"], unit=t.meta["unit"], decimals=4, tex=r"R = H - Lw",
                       symbols=[{"sym": "H", "meaning": "swing high", "unit": t.meta["unit"]}, {"sym": "Lw", "meaning": "swing low", "unit": t.meta["unit"]}], tex_sub=tx(r"«h» - «l»", h=(f["swing_high"], 4), l=(f["swing_low"], 4)))
    up = 1 if f["leg"] == "up" else 0
    leg = t.add("fib_leg", "Leg direction", "constant", value=up, decimals=0, text=("up-leg: the swing low (" + f["swing_low_date"] + ") comes before the swing high (" + f["swing_high_date"] + "), so levels are measured down from the high"
                                                                                  if up else "down-leg: the swing high comes before the swing low, so levels are measured up from the low"), params={"kind": "derived from the dates of H and Lw"})
    return agent, vd, vv, f, hi, lo, span, leg


def m_fib(t, arg):
    r = _fib(t)
    if r is None:
        return _pending_metric(t, f"fib:{arg}", f"Fibonacci {arg}", t.meta["agent_id"], t.meta["unit"])
    agent, vd, vv, f, hi, lo, span, leg = r
    key = f"{float(arg) * 100:.1f}%" if arg else "61.8%"
    ratio = float(arg) if arg else 0.618
    rn = t.const(f"fib_ratio:{ratio}", f"Fibonacci ratio {key}", ratio, "", "retracement ratio", "assumption", "standard Fibonacci ratios (me.FIB_RATIOS)")
    ops = [t.operand("H", "h", hi), t.operand("Lw", "lw", lo), t.operand("R", "r", span), t.operand("\\rho", "rho", rn), t.operand("up", "up", leg)]
    val = f["levels"][key]
    return t.expr_node(f"fib:{arg}", f"Fibonacci {key} level", "(h - r * rho) if up else (lw + r * rho)", ops, value=val, unit=t.meta["unit"], decimals=3,
                       tex=r"F_\rho = \begin{cases} H - \rho R & \text{up-leg} \\ Lw + \rho R & \text{down-leg} \end{cases}",
                       symbols=[{"sym": "H, Lw, R", "meaning": "swing high, swing low and their range", "unit": t.meta["unit"]}, {"sym": r"\rho", "meaning": f"the ratio {key}", "unit": ""}],
                       tex_sub=tx(r"«h» - «rho» \times «r»" if f["leg"] == "up" else r"«lw» + «rho» \times «r»", h=(f["swing_high"], 4), lw=(f["swing_low"], 4), rho=ratio, r=(f["swing_high"] - f["swing_low"], 4)), steps=[tx(r"= «v»", v=(val, 4))])


def m_fib_swing_high(t, a): return (_fib(t) or (None,) * 8)[4] or _pending_metric(t, "fib_high", "Swing high", t.meta["agent_id"])
def m_fib_swing_low(t, a): return (_fib(t) or (None,) * 8)[5] or _pending_metric(t, "fib_low", "Swing low", t.meta["agent_id"])


def m_fib_retrace(t, a):
    r = _fib(t)
    if r is None:
        return _pending_metric(t, "fib_retrace", "Retraced %", t.meta["agent_id"], "%")
    agent, vd, vv, f, hi, lo, span, leg = r
    last = t.leaf(agent, vd[-1])
    ops = [t.operand("H", "h", hi), t.operand("Lw", "lw", lo), t.operand("P_t", "p", last), t.operand("R", "r", span), t.operand("up", "up", leg)]
    return t.expr_node("fib_retrace", "Retraced % of the swing", "((h - p) if up else (p - lw)) / r * 100", ops, value=f["retracement_pct"], unit="%", decimals=1,
                       tex=r"\text{Retraced} = \frac{H - P_t}{R} \times 100 \;(\text{up-leg}), \quad \frac{P_t - Lw}{R} \times 100 \;(\text{down-leg})",
                       symbols=[{"sym": "P_t", "meaning": "latest close", "unit": t.meta["unit"]}, {"sym": "R", "meaning": "swing range", "unit": t.meta["unit"]}],
                       tex_sub=tx(r"\frac{«h» - «p»}{«r»} \times 100" if f["leg"] == "up" else r"\frac{«p» - «lw»}{«r»} \times 100", h=(f["swing_high"], 4), lw=(f["swing_low"], 4), p=(f["last"], 4), r=(f["swing_high"] - f["swing_low"], 4)),
                       steps=[tx(r"= «v»\%", v=(f["retracement_pct"], 3))])


def m_fib_golden(t, a):
    r = _fib(t)
    if r is None:
        return _pending_metric(t, "fib_golden", "Golden-ratio proximity", t.meta["agent_id"], "%")
    agent, vd, vv, f, hi, lo, span, leg = r
    g = m_fib(t, "0.618")
    last = t.leaf(agent, vd[-1])
    ops = [t.operand("P_t", "p", last), t.operand("F_{0.618}", "g", g), t.operand("R", "r", span)]
    return t.expr_node("fib_golden", "Golden-ratio distance (% of range)", "abs(p - g) / r * 100", ops, value=f["golden_ratio_distance_pct_of_range"], unit="% of range", decimals=1,
                       tex=r"\frac{|P_t - F_{0.618}|}{R} \times 100", symbols=[{"sym": "F_{0.618}", "meaning": "the 61.8% retracement level", "unit": t.meta["unit"]}], tex_sub=tx(r"\frac{|«p» - «g»|}{«r»} \times 100", p=(f["last"], 4), g=(f["levels"]["61.8%"], 4), r=(f["swing_high"] - f["swing_low"], 4)),
                       steps=[tx(r"= «v»\%", v=(f["golden_ratio_distance_pct_of_range"], 3))])


def _tri(t: Trace, want: str, mid: str, label: str):
    p = _price_inputs(t)
    if p is None:
        return _pending_metric(t, mid, label, t.meta["agent_id"])
    agent, dates, vals, _ = p
    lb = min(60, t.n)
    a = vals[-lb:]
    tri = me.triangle_detection(dates, vals, lookback=lb)
    hi, lo = _swings(a)
    if tri.get("pattern") is None or "upper" not in tri:
        return t.add(mid, label, "polyfit", status=WITHHELD, text="withheld", note=f"withheld: fewer than 2 swing highs and 2 swing lows in the last {lb} sessions ({len(hi)} highs, {len(lo)} lows), so no trend lines are fitted.")
    side = "upper" if want.startswith("upper") else "lower"
    idx = hi if side == "upper" else lo
    rows = [{"i": i, "d": dates[-lb:][i], "v": a[i]} for i in idx]
    which = "end" if want.endswith("end") else "start" if want.endswith("start") else "slope"
    val = tri[side][{"end": "end", "start": "start", "slope": "slope_per_bar"}[which]]
    return t.add(mid, label, "polyfit", value=val, unit=t.meta["unit"] if which != "slope" else f"{t.meta['unit']}/bar", decimals=3, rows=rows, stats=t.stats([r["v"] for r in rows]),
                 params={"n": lb - 1, "want": which, "agent": agent, "side": side}, tex=r"y = m\,i + b \quad (\text{least squares through the swing points}), \quad y_{end} = m\,(n-1) + b",
                 symbols=[{"sym": "i", "meaning": f"bar index within the last {lb} sessions", "unit": ""}, {"sym": "m, b", "meaning": "slope and intercept of the least-squares line through the listed swing " + ("highs" if side == "upper" else "lows"), "unit": ""}],
                 steps=[tx(r"= «v»", v=(val, 5))])


def m_tri_pattern(t, a):
    p = _price_inputs(t)
    if p is None:
        return _pending_metric(t, "tri_pattern", "Triangle pattern", t.meta["agent_id"])
    agent, dates, vals, _ = p
    lb = min(60, t.n)
    tri = me.triangle_detection(dates, vals, lookback=lb)
    if "upper" not in tri:
        return t.add("tri_pattern", "Triangle pattern", "constant", value="none", decimals=0, text=f"none: fewer than 2 swing highs and 2 swing lows in the last {lb} sessions, so no lines are fitted",
                     tex=r"\text{pattern} = \text{none if fewer than 2 swing highs or 2 swing lows}", symbols=[], params={"kind": "rule"})
    ids = {k: _tri(t, w, f"tri_{k}", lbl) for k, (w, lbl) in {"u1": ("upper_end", "Upper line, end"), "u0": ("upper_start", "Upper line, start"), "l1": ("lower_end", "Lower line, end"), "l0": ("lower_start", "Lower line, start"),
                                                              "mh": ("upper_slope", "Upper line slope"), "ml": ("lower_slope", "Lower line slope")}.items()}
    rows = t.window(agent, dates[-lb:], vals[-lb:])
    mu = t.window_node("tri_mean", f"Mean price, last {lb} sessions", "mean", agent, rows, value=float(np.mean(vals[-lb:])), unit=t.meta["unit"], decimals=4, tex=r"\mu = \frac{1}{n}\sum P_i",
                       symbols=[{"sym": "P_i", "meaning": f"the last {lb} daily closes", "unit": t.meta["unit"]}])
    ops = [t.operand(nm, nm, ids[nm]) for nm in ("mh", "ml", "u0", "u1", "l0", "l1")] + [t.operand(r"\mu", "mu", mu)]
    flat = "(abs(mu) * 0.04 / 100)"
    expr = (f"'none' if not ((u1 - l1) < (u0 - l0) and (u1 - l1) > 0) else 'ascending_triangle' if (abs(mh) <= {flat} and ml > {flat}) else "
            f"'symmetrical_triangle' if (mh < -{flat} and ml > {flat}) else 'descending_triangle' if (mh < -{flat} and abs(ml) <= {flat}) else 'none'")
    return t.expr_node("tri_pattern", "Triangle pattern", expr, ops, value=tri["pattern"], decimals=0,
                       tex=r"\text{lines must converge: } 0 < (U_1 - L_1) < (U_0 - L_0); \; f = 0.04\%\,\mu; \; \text{ascending: } |m_h| \le f,\, m_l > f; \; \text{symmetrical: } m_h < -f,\, m_l > f; \; \text{descending: } m_h < -f,\, |m_l| \le f",
                       symbols=[{"sym": "m_h, m_l", "meaning": "slopes of the least-squares lines through the swing highs and the swing lows", "unit": f"{t.meta['unit']}/bar"}, {"sym": "U_0, U_1, L_0, L_1", "meaning": "the upper and lower lines at the first and last bar of the window", "unit": t.meta["unit"]},
                                {"sym": "f", "meaning": "the flat-side tolerance: 0.04 % of the window's mean price per bar", "unit": t.meta["unit"]}],
                       tex_sub=(f"(U_1-L_1) = {num(tri['upper']['end'] - tri['lower']['end'], 4)}, \\; (U_0-L_0) = {num(tri['upper']['start'] - tri['lower']['start'], 4)}, \\; "
                                f"f = {num(abs(float(np.mean(vals[-lb:]))) * 0.04 / 100, 5)}"),
                       steps=[rf"\Rightarrow \text{{{tri['pattern']}}}"])


def m_tri_upper(t, a): return _tri(t, "upper_end", "tri_upper", "Triangle upper line (breakout level)")
def m_tri_lower(t, a): return _tri(t, "lower_end", "tri_lower", "Triangle lower line (breakdown level)")


def m_divergence(t, arg):
    which = arg or "rsi"
    p = _price_inputs(t)
    if p is None:
        return _pending_metric(t, f"divergence:{which}", f"{which.upper()} divergence", t.meta["agent_id"])
    agent, dates, vals, _ = p
    d = me.rsi_macd_divergence(vals)[which]
    rows = t.window(agent, dates, vals)
    return t.add(f"divergence:{which}", f"{which.upper()} divergence", "divergence", value=d, decimals=0, rows=rows, stats=None, params={"which": which, "agent": agent, "lookback": 80, "window": 5},
                 tex=r"\text{bearish: } P_{h_2} > P_{h_1} \wedge O_{h_2} < O_{h_1}; \quad \text{bullish: } P_{l_2} < P_{l_1} \wedge O_{l_2} > O_{l_1}",
                 symbols=[{"sym": "h_1, h_2", "meaning": "the last two swing highs (extreme of +/-5 bars) in the last 80 sessions", "unit": ""}, {"sym": "l_1, l_2", "meaning": "the last two swing lows", "unit": ""},
                          {"sym": "O", "meaning": ("RSI 14" if which == "rsi" else "the MACD line") + " at those bars", "unit": ""}], steps=[rf"\Rightarrow \text{{{d}}}"],
                 note="The table lists every stored close; the rule is applied to the last 80.")


def m_regime(t, a):
    """Forward-curve regime (CONTANGO / BACKWARDATION / FLAT / SEASONAL) from the Henry Hub futures points."""
    pts, leafs = _fwd_points(t)
    if not pts:
        return _pending_metric(t, "regime", "Forward curve regime", "Agent_HH_M1")
    val = me.curve_regime(pts)
    rows = [{"d": p["contract"], "v": p["value"]} for p in pts]
    return t.add("regime", "Forward curve regime", "curve_regime", value=val, decimals=0, rows=rows, stats=None, params={"flat_band": 0.05},
                 tex=r"\text{SEASONAL if } \ge 6 \text{ contracts reverse direction } \ge 2 \text{ times; else sign}(M_{12} - M_1) \text{ with a } \pm 0.05 \text{ flat band}",
                 symbols=[{"sym": "M_k", "meaning": "the k-th monthly NYMEX Henry Hub futures price", "unit": "USD/MMBtu"}], steps=[rf"\Rightarrow \text{{{val}}}"], note="Operands: the futures points listed (each a stored row).",
                 operands=[t.operand(p["contract"], p["contract"].lower(), leafs[p["contract"]]) for p in pts])


def _fwd_points(t: Trace):
    pts, leafs = [], {}
    for m_ in range(1, 13):
        agent = f"Agent_HH_M{m_}"
        s = t.series(agent)
        if s:
            leafs[f"M{m_}"] = t.leaf(agent, s[-1][0])
            pts.append({"contract": f"M{m_}", "value": s[-1][1]})
    return pts, leafs


def m_fwd(t, arg):
    m_ = arg or "M1"
    return t.leaf(f"Agent_HH_{m_}")


def m_fwd_front_spread(t, a):
    pts, leafs = _fwd_points(t)
    if "M1" not in leafs or "M2" not in leafs:
        return _pending_metric(t, "fwd_front_spread", "M2 minus M1", "Agent_HH_M1", "USD/MMBtu")
    v = pts[1]["value"] - pts[0]["value"]
    return t.expr_node("fwd_front_spread", "M2 minus M1", "m2 - m1", [t.operand("M_2", "m2", leafs["M2"]), t.operand("M_1", "m1", leafs["M1"])], value=v, unit="USD/MMBtu", decimals=4,
                       tex=r"S = M_2 - M_1", symbols=[{"sym": "M_1, M_2", "meaning": "prompt and second-month NYMEX Henry Hub futures", "unit": "USD/MMBtu"}], tex_sub=tx(r"«b» - «a»", b=pts[1]["value"], a=pts[0]["value"]), steps=[tx(r"= «v»", v=(v, 4))])


def m_fwd_span(t, a):
    pts, leafs = _fwd_points(t)
    if len(pts) < 2:
        return _pending_metric(t, "fwd_span", "Last minus first contract", "Agent_HH_M1", "USD/MMBtu")
    first, last = pts[0], pts[-1]
    v = last["value"] - first["value"]
    return t.expr_node("fwd_span", f"{last['contract']} minus {first['contract']}", "b - a", [t.operand(last["contract"], "b", leafs[last["contract"]]), t.operand(first["contract"], "a", leafs[first["contract"]])], value=v, unit="USD/MMBtu", decimals=4,
                       tex=rf"{last['contract']} - {first['contract']}", symbols=[], tex_sub=tx(r"«b» - «a»", b=last["value"], a=first["value"]), steps=[tx(r"= «v»", v=(v, 4))])


def m_pct_of_wti(t, a):
    p = _price_inputs(t)
    wti = t.series(me.WTI_AGENT)
    if p is None or t.meta["unit"] != "cents/gal":
        return _pending_metric(t, "pct_of_wti", "% of WTI", t.meta["agent_id"], "%")
    if not wti:
        return _pending_metric(t, "pct_of_wti", "% of WTI", me.WTI_AGENT, "%")
    agent, dates, vals, _ = p
    c3, w = t.leaf(agent, dates[-1]), t.leaf(me.WTI_AGENT, wti[-1][0])
    v = me.wti_ratio(vals[-1], wti[-1][1])
    code = t.meta["code"]
    return t.expr_node("pct_of_wti", f"{code} as % of WTI", "(p / 100 * 42) / w * 100", [t.operand(rf"P_{{{code}}}", "p", c3), t.operand(r"P_{WTI}", "w", w)], value=v, unit="%", decimals=2,
                       tex=rf"\%WTI_{{{code}}} = \frac{{(P_{{{code}}}/100)\cdot 42}}{{P_{{WTI}}}} \times 100",
                       symbols=[{"sym": rf"P_{{{code}}}", "meaning": f"{t.meta['label']} spot", "unit": "cents/gal"}, {"sym": "42", "meaning": "gallons per barrel", "unit": "gal/bbl"}, {"sym": "P_{WTI}", "meaning": "WTI Cushing spot", "unit": "USD/bbl"}],
                       tex_sub=tx(r"\frac{(«p»/100)\cdot 42}{«w»} \times 100", p=vals[-1], w=wti[-1][1]), steps=[tx(r"= \frac{«n»}{«w»} \times 100", n=(vals[-1] / 100 * 42, 4), w=wti[-1][1]), tx(r"= «v»\%", v=(v, 3))])


def m_frac_spread(t, a):
    eth, hh = t.series(me.PRODUCTS["ethane"]["agent_id"]), t.series(me.PRODUCTS["henry_hub"]["agent_id"])
    al = me._aligned(eth, hh)
    le = t.leaf(me.PRODUCTS["ethane"]["agent_id"], al[-1][0]) if al else t.pending_leaf(me.PRODUCTS["ethane"]["agent_id"])
    lh = t.leaf(me.PRODUCTS["henry_hub"]["agent_id"], al[-1][0]) if al else t.leaf(me.PRODUCTS["henry_hub"]["agent_id"])
    v = me.frac_spread(al[-1][1], al[-1][2]) if al else None
    return t.expr_node("frac_spread", "Frac spread", f"(c / 100) / {frac_module.ETHANE_MMBTU_PER_GAL} - hh", [t.operand("P_{C2}", "c", le), t.operand("P_{HH}", "hh", lh)], value=v, unit="USD/MMBtu", decimals=2,
                       tex=rf"S = \frac{{P_{{C2}}/100}}{{{frac_module.ETHANE_MMBTU_PER_GAL}}} - P_{{HH}}", symbols=[{"sym": "P_{C2}", "meaning": "Mont Belvieu ethane", "unit": "cents/gal"}, {"sym": str(frac_module.ETHANE_MMBTU_PER_GAL), "meaning": "MMBtu per gallon of ethane", "unit": "MMBtu/gal"},
                                                                                                                                         {"sym": "P_{HH}", "meaning": "Henry Hub spot", "unit": "USD/MMBtu"}],
                       tex_sub=tx(rf"\frac{{«c»/100}}{{{frac_module.ETHANE_MMBTU_PER_GAL}}} - «hh»", c=al[-1][1], hh=al[-1][2]) if al else "", steps=[tx(r"= «v»", v=(v, 4))] if al else [])


def m_hub_spread(t, a):
    mb, cw = t.series(me.PRODUCTS["propane"]["agent_id"]), t.series(me.CONWAY_AGENT)
    al = me._aligned(mb, cw)
    lm = t.leaf(me.PRODUCTS["propane"]["agent_id"], al[-1][0]) if al else t.leaf(me.PRODUCTS["propane"]["agent_id"])
    lc = t.leaf(me.CONWAY_AGENT, al[-1][0]) if al else t.pending_leaf(me.CONWAY_AGENT)
    v = al[-1][1] - al[-1][2] if al else None
    return t.expr_node("hub_spread", "Mont Belvieu minus Conway", "mb - cw", [t.operand("MB", "mb", lm), t.operand("CW", "cw", lc)], value=v, unit="cents/gal", decimals=2, tex=r"S = P_{MB} - P_{CW}",
                       symbols=[{"sym": "P_{MB}", "meaning": "Mont Belvieu propane", "unit": "cents/gal"}, {"sym": "P_{CW}", "meaning": "Conway propane", "unit": "cents/gal"}], tex_sub=tx(r"«a» - «b»", a=al[-1][1], b=al[-1][2]) if al else "")


def _lng_point(t: Trace, arg: str, kind: str):
    lg = t.state["curves"]["lng_forward"]
    pt = next((p for p in lg.get("points", []) if p["contract"] == (arg or "M1")), None)
    if pt is None:
        return _pending_metric(t, f"lng_{kind}:{arg}", f"LNG {kind} {arg}", f"Agent_HH_{arg or 'M1'}", "USD/MMBtu")
    hh = t.leaf(f"Agent_HH_{pt['contract']}")
    prm = lg["parameters"]
    k = t.const("lng_k", "k (feed-gas factor)", prm["k_hh_multiplier"]["value"], "x HH", f"source: {prm['k_hh_multiplier']['source']}", "assumption" if prm["k_hh_multiplier"]["source"] == "assumption" else "library quote",
                prm["k_hh_multiplier"].get("reason") or prm["k_hh_multiplier"].get("quote", ""))
    L = t.const("lng_L", "L (liquefaction fee)", prm["liquefaction_usd_mmbtu"]["value"], "USD/MMBtu", f"source: {prm['liquefaction_usd_mmbtu']['source']}", "assumption" if prm["liquefaction_usd_mmbtu"]["source"] == "assumption" else "library quote",
                prm["liquefaction_usd_mmbtu"].get("reason") or prm["liquefaction_usd_mmbtu"].get("quote", ""))
    fob = t.expr_node(f"lng_fob:{pt['contract']}", f"LNG FOB cost {pt['contract']}", "k * hh + L", [t.operand("k", "k", k), t.operand(f"HH_{{{pt['contract']}}}", "hh", hh), t.operand("L", "L", L)], value=pt["fob_cost"], unit="USD/MMBtu", decimals=3,
                      tex=r"FOB_m = k\,HH_m + L", symbols=[{"sym": "k", "meaning": "feed-gas factor (MMBtu of gas per MMBtu of LNG)", "unit": ""}, {"sym": "HH_m", "meaning": f"NYMEX Henry Hub futures {pt['contract']}", "unit": "USD/MMBtu"}, {"sym": "L", "meaning": "liquefaction fee", "unit": "USD/MMBtu"}],
                      tex_sub=tx(r"«k» \times «hh» + «L»", k=prm["k_hh_multiplier"]["value"], hh=pt["hh_value"], L=prm["liquefaction_usd_mmbtu"]["value"]), steps=[tx(r"= «v»", v=(pt["fob_cost"], 4))])
    if kind == "fob":
        return fob
    nb = pt.get("netback")
    nid = f"lng_netback:{pt['contract']}"
    if not nb or nb.get("value") is None:
        ttf_agent = f"Agent_TTF_{(pt.get('delivery_month') or '').replace('-', '_')}"
        reason = (lg.get("netback") or {}).get("reasons", {}).get(pt.get("delivery_month")) or "no fresh TTF quote for this month"
        return t.add(nid, f"TTF netback {pt['contract']}", "expr", status=WITHHELD, unit="USD/MMBtu", text="withheld", operands=[t.operand("TTF", "x", t.pending_leaf(ttf_agent))], expr="x",
                     note=f"withheld: {reason}. JKM has no free source and is never estimated.")
    ttf = t.leaf(f"Agent_TTF_{pt['delivery_month'].replace('-', '_')}")
    fx = t.leaf("Agent_FX_EURUSD")
    a = lg["assumptions"]
    sh, rg, mw = t.const("lng_ship", "shipping", a["shipping"]["value"], "USD/MMBtu", "assumption", "assumption"), t.const("lng_regas", "regasification", a["regas"]["value"], "USD/MMBtu", "assumption", "assumption"), \
        t.const("lng_mwh", "MMBtu per MWh", a["mmbtu_per_mwh"]["value"], "MMBtu/MWh", "physical conversion", "physical")
    return t.expr_node(nid, f"TTF netback {pt['contract']}", "ttf * fx / mwh - ship - regas", [t.operand("TTF", "ttf", ttf), t.operand("FX", "fx", fx), t.operand("c", "mwh", mw), t.operand("Ship", "ship", sh), t.operand("Regas", "regas", rg)],
                       value=nb["value"], unit="USD/MMBtu", decimals=3, tex=r"NB_m = \frac{TTF_m \times FX}{3.412142} - Ship - Regas",
                       symbols=[{"sym": "TTF_m", "meaning": "Dutch TTF monthly future", "unit": "EUR/MWh"}, {"sym": "FX", "meaning": "EUR/USD", "unit": "USD/EUR"}, {"sym": "3.412142", "meaning": "MMBtu per MWh", "unit": ""}],
                       tex_sub=tx(r"\frac{«t» \times «fx»}{«c»} - «s» - «r»", t=nb["ttf_eur_mwh"], fx=nb["eurusd"], c=a["mmbtu_per_mwh"]["value"], s=a["shipping"]["value"], r=a["regas"]["value"]), steps=[tx(r"= «v»", v=(nb["value"], 4))])


def m_lng_fob(t, arg): return _lng_point(t, arg, "fob")
def m_lng_netback(t, arg): return _lng_point(t, arg, "netback")


def _sum_leaves(t: Trace, mid: str, label: str, agents: list, unit: str, decimals: int, tex: str, require_all: bool = True, same_date: bool = False) -> str:
    leafs = []
    for a in agents:
        s = t.series(a)
        leafs.append(t.leaf(a, s[-1][0]) if s else t.pending_leaf(a))
    ops = [t.operand(f"x_{i + 1}", f"x{i + 1}", lid) for i, lid in enumerate(leafs)]
    vals = [t.nodes[lid]["value"] for lid in leafs]
    ok = all(v is not None for v in vals)
    return t.expr_node(mid, label, " + ".join(o["var"] for o in ops), ops, value=sum(vals) if ok else None, unit=unit, decimals=decimals, tex=tex,
                       symbols=[{"sym": f"x_{i + 1}", "meaning": a.replace("Agent_", ""), "unit": unit} for i, a in enumerate(agents)],
                       tex_sub=" + ".join(num(v, 3) for v in vals if v is not None) if ok else "", steps=[tx(r"= «v»", v=(sum(vals), 3))] if ok else [])


def m_shale_total(t, a):
    return _sum_leaves(t, "shale_total", "Shale production, six roster basins", me.DRIVER_GROUPS[0][2], "Bcf/d", 1, r"\sum_{b=1}^{6} q_b")


def m_storage_total(t, a):
    return _sum_leaves(t, "storage_total", "Working gas in storage, six regions", me.DRIVER_GROUPS[2][2], "Bcf", 0, r"\sum_{r=1}^{6} S_r")


def m_hdd_anomaly(t, a):
    act, norm = t.series("Agent_Weather_Actual_HDD"), t.series("Agent_Weather_30YrNormal_HDD")
    la = t.leaf("Agent_Weather_Actual_HDD", act[-1][0]) if act else t.pending_leaf("Agent_Weather_Actual_HDD")
    nrow = t.conn.execute("SELECT value FROM pit_market_data WHERE agent_id='Agent_Weather_30YrNormal_HDD' AND substr(target_timestamp,1,10)=? AND available_timestamp<=? ORDER BY available_timestamp DESC LIMIT 1",
                          (act[-1][0], t.cutoff)).fetchone() if act else None
    nd = {act[-1][0]: nrow[0]} if nrow else {}
    ln = t.leaf("Agent_Weather_30YrNormal_HDD", act[-1][0]) if nrow else t.pending_leaf("Agent_Weather_30YrNormal_HDD", act[-1][0] if act else None)
    v = act[-1][1] - nd[act[-1][0]] if act and nd else None
    return t.expr_node("hdd_anomaly", "HDD vs 30-year normal", "a - n", [t.operand("HDD", "a", la), t.operand("N", "n", ln)], value=v, unit="HDD", decimals=1, tex=r"\Delta HDD = HDD_{actual} - HDD_{normal}",
                       symbols=[{"sym": "HDD_{actual}", "meaning": "CONUS population-weighted heating degree days, latest day", "unit": "HDD"}, {"sym": "HDD_{normal}", "meaning": "the 30-year normal for the same calendar day", "unit": "HDD"}],
                       tex_sub=tx(r"«a» - «n»", a=act[-1][1], n=nd[act[-1][0]]) if v is not None else "", steps=[tx(r"= «v»", v=(v, 2))] if v is not None else [])


def m_flow_count(t, a):
    roster = me._roster()
    flow_agents = [x for x in roster if x.startswith("Agent_Flow_") or (x.startswith("Agent_LNG_") and x.endswith("_Flow"))]
    latest = me.latest_rows(t.conn, t.cutoff)
    rows = [{"d": x, "v": 1 if (x in latest and latest[x]["provenance"] == "measured") else 0} for x in flow_agents]
    return t.add("flow_count", "Flow meters with data", "count", value=sum(r["v"] for r in rows), unit=f"of {len(rows)}", decimals=0, rows=rows, stats=None, params={"agents": True},
                 tex=r"N = \sum_{a} \mathbf{1}[\text{a measured row exists for agent } a]", symbols=[{"sym": "a", "meaning": "each flow-meter agent in the roster", "unit": ""}], steps=[tx(r"= «n»", n=(sum(r["v"] for r in rows), 0))],
                 note="Each row is a roster agent: 1 = a measured row exists at the cutoff, 0 = no collector.")


def _notices(t: Trace, mid: str, label: str, days: int, force: bool, pipe: str | None = None):
    try:
        nrows = t.conn.execute("SELECT id, source_id, title, body, available_timestamp FROM documents WHERE domain='pipeline_notice' AND available_timestamp<=? ORDER BY available_timestamp DESC LIMIT 400", (t.cutoff,)).fetchall()
    except sqlite3.OperationalError:
        nrows = []
    sel = [r for r in nrows if (me._age_days(r[4], t.cutoff) or 0) <= days and (not force or "FORCE MAJEURE." in r[3]) and (not pipe or r[1].replace("kinder_morgan_notices_", "").upper() == pipe)]
    rows = [{"d": r[4][:10], "v": 1, "doc": r[0], "title": r[2]} for r in sel]
    return t.add(mid, label, "count", value=len(rows), unit="notices", decimals=0, rows=rows, params={"days": days, "force_majeure": force}, tex=r"N = \sum_{n} \mathbf{1}[\text{posted within the window}]",
                 symbols=[{"sym": "n", "meaning": f"pipeline notices posted in the last {days} days" + (" containing 'FORCE MAJEURE.'" if force else ""), "unit": ""}], steps=[tx(r"= «n»", n=(len(rows), 0))],
                 note="Click a row to see the notice (source document, posted time, payload hash).")


def m_notices_7d(t, arg): return _notices(t, f"notices_7d:{arg}" if arg else "notices_7d", "Pipeline notices, last 7 days" + (f" ({arg})" if arg else ""), 7, False, arg or None)
def m_fm_30d(t, a): return _notices(t, "fm_30d", "Force-majeure notices, last 30 days", 30, True)


def m_seasonal(t, arg, kind="avg"):
    p = _price_inputs(t)
    if p is None:
        return _pending_metric(t, f"seasonal_{kind}", f"Seasonal band {kind}", t.meta["agent_id"], t.meta["unit"])
    agent, dates, vals, _ = p
    ov = me.seasonal_overlay(dates, vals, int(t.cutoff[:4]))
    grid = ov["day_of_year"]
    cur_doy = datetime.strptime(dates[-1], "%Y-%m-%d").timetuple().tm_yday
    g = int(arg) if arg else min(grid, key=lambda x: abs(x - cur_doy))
    gi = grid.index(g)
    by_year: dict[int, dict[int, tuple]] = {}
    for d, v in zip(dates, vals):
        y, doy = int(d[:4]), datetime.strptime(d, "%Y-%m-%d").timetuple().tm_yday
        by_year.setdefault(y, {})[min(doy, 365)] = (v, d)
    rows = []
    for y in ov["history_years"]:
        ys = by_year.get(y, {})
        near = [k for k in ys if abs(k - g) <= 3]
        if near:
            v, d = ys[min(near, key=lambda k: abs(k - g))]
            rows.append({"d": d, "v": v})
    val = {"avg": ov["band_avg"][gi], "min": ov["band_min"][gi], "max": ov["band_max"][gi]}[kind]
    op = {"avg": "mean", "min": "min", "max": "max"}[kind]
    if val is None or not rows:
        return t.add(f"seasonal_{kind}:{g}", f"Seasonal {kind} at day {g}", op, status=WITHHELD, unit=t.meta["unit"], rows=[], text="withheld",
                     note="withheld: no previous complete year (at least 150 observations) has a value near this day of the year, so the seasonal band is not drawn. Nothing is estimated.")
    sym = {"avg": r"\bar{P}", "min": r"\min", "max": r"\max"}[kind]
    return t.window_node(f"seasonal_{kind}:{g}", f"Seasonal {kind} at day {g}", op, agent, rows, value=val, unit=t.meta["unit"], tex=rf"{sym}_{{d={g}}} = {sym}\left(P_{{y,d}}\right)_{{y \in Y}}",
                         symbols=[{"sym": "Y", "meaning": f"the previous complete years with at least 150 observations: {', '.join(map(str, ov['history_years']))}", "unit": ""}, {"sym": "P_{y,d}", "meaning": "the close in year y nearest day-of-year d (within 3 days)", "unit": t.meta["unit"]}],
                         decimals=3, steps=[tx(r"= «v»", v=(val, 4))])


def m_seasonal_avg(t, arg): return m_seasonal(t, arg, "avg")
def m_seasonal_min(t, arg): return m_seasonal(t, arg, "min")
def m_seasonal_max(t, arg): return m_seasonal(t, arg, "max")


def _scaled_sum(t: Trace, mid: str, label: str, plus: list, minus: list, unit: str, decimals: int, tex: str, scale: float = 1000.0) -> str:
    ops, vals, sym = [], [], []
    for sign, agents in (("+", plus), ("-", minus)):
        for a in agents:
            s = t.series(a)
            lid = t.leaf(a, s[-1][0]) if s else t.pending_leaf(a)
            var = f"x{len(ops) + 1}"
            ops.append(t.operand(var, var, lid))
            vals.append((sign, t.nodes[lid]["value"]))
            sym.append({"sym": var, "meaning": ("+ " if sign == "+" else "- ") + a.replace("Agent_", ""), "unit": "MMcf/month"})
    ok = all(v is not None for _, v in vals)
    expr = "(" + " ".join(("+ " if sg == "+" else "- ") + o["var"] for (sg, _), o in zip(vals, ops)).lstrip("+ ").strip() + f") / {scale:g}"
    expr = expr.replace("(- ", "(-")
    tot = (sum(v if sg == "+" else -v for sg, v in vals) / scale) if ok else None
    return t.expr_node(mid, label, expr, ops, value=tot, unit=unit, decimals=decimals, tex=tex, symbols=sym,
                       tex_sub=" ".join(("+ " if sg == "+" else "- ") + num(v, 0) for sg, v in vals).lstrip("+ ") if ok else "", steps=[tx(r"= «v»", v=(tot, 3))] if ok else [])


def m_lng_exports_total(t, a):
    return _scaled_sum(t, "lng_exports_total", "LNG exports, eight terminals (latest month)", me.DRIVER_GROUPS[7][2], [], "Bcf/month", 0, r"\frac{1}{1000}\sum_{t=1}^{8} E_t")


def m_border_net(t, a):
    ag = me.DRIVER_GROUPS[8][2]
    return _scaled_sum(t, "border_net", "Net border imports (Canada in, Mexico out)", [x for x in ag if x.endswith("_FromCanada")], [x for x in ag if x.endswith("_ToMexico")], "Bcf/month", 1,
                       r"\frac{1}{1000}\left(\sum \text{from Canada} - \sum \text{to Mexico}\right)")


def m_feedgas(t, arg):
    return t.leaf(f"Agent_LNGFeedgas_{(arg or 'p50').upper()}")


def m_driver(t, arg):
    """A driver row or a map node value: the latest stored row of the agent (or a pending leaf)."""
    return t.leaf(arg)


def m_geo(t, arg):
    node = next((n for n in me.GEO_NODES if n[0] == arg), None)
    return t.leaf(node[5]) if node else t.pending_leaf(arg)


METRICS = {
    "price": m_price, "change_1d": m_change_1d, "change_1d_pct": m_change_1d_pct, "change_5d": m_change_5d, "change_5d_pct": m_change_5d_pct, "window_high": m_window_high, "window_low": m_window_low,
    "sma20": m_sma20, "sma50": m_sma50, "sma200": m_sma200, "trend": m_trend, "ma_regime": m_ma_regime, "rsi14": m_rsi14, "macd_line": m_macd_line, "macd_signal": m_macd_signal, "macd_hist": m_macd_hist,
    "bb_upper": m_bb_upper, "bb_lower": m_bb_lower, "bandwidth": m_bandwidth, "squeeze": m_squeeze, "tri_upper": m_tri_upper, "tri_lower": m_tri_lower, "divergence": m_divergence,
    "fib": m_fib, "fib_high": m_fib_swing_high, "fib_low": m_fib_swing_low, "fib_retrace": m_fib_retrace, "fib_golden": m_fib_golden,
    "pct_of_wti": m_pct_of_wti, "frac_spread": m_frac_spread, "hub_spread": m_hub_spread,
    "fwd": m_fwd, "fwd_front_spread": m_fwd_front_spread, "fwd_span": m_fwd_span, "regime": m_regime, "lng_fob": m_lng_fob, "lng_netback": m_lng_netback,
    "shale_total": m_shale_total, "storage_total": m_storage_total, "hdd_anomaly": m_hdd_anomaly, "flow_count": m_flow_count, "notices_7d": m_notices_7d, "fm_30d": m_fm_30d,
    "tri_pattern": m_tri_pattern, "lng_exports_total": m_lng_exports_total, "border_net": m_border_net, "feedgas": m_feedgas,
    "seasonal_avg": m_seasonal_avg, "seasonal_min": m_seasonal_min, "seasonal_max": m_seasonal_max, "drv": m_driver, "geo": m_geo,
}
