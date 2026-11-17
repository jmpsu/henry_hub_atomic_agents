"""NGL & Henry Hub analytics engine behind /api/state.json (web UI and ngl-term.py read the same document).

Rules this module enforces:
- Every number comes from henry_hub_pit.db through a point-in-time read (available_timestamp <= as_of, latest vintage).
- Nothing is synthesised. A product, curve or driver without a collector is returned with status "pending_collector"
  and NO series, so a placeholder can never be mistaken for a measured observation.
- All indicators are deterministic functions of the series (no LLM, no randomness).
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

BASE_DIR = Path(__file__).resolve().parent
SCHEMA_VERSION = "ngl-state/1"
GAL_PER_BBL = 42.0
ETHANE_MMBTU_PER_GAL = 0.0665
PENDING = "pending_collector"

PRODUCTS = {
    "propane": {"label": "Mont Belvieu Propane (C3)", "code": "C3", "unit": "cents/gal", "agent_id": "Agent_NGL_MontBelvieu_Propane"},
    "ethane": {"label": "Mont Belvieu Ethane (C2)", "code": "C2", "unit": "cents/gal", "agent_id": "Agent_NGL_MontBelvieu_Ethane"},
    "normal_butane": {"label": "Mont Belvieu Normal Butane (nC4)", "code": "NC4", "unit": "cents/gal", "agent_id": "Agent_NGL_MontBelvieu_NormalButane"},
    "isobutane": {"label": "Mont Belvieu Isobutane (iC4)", "code": "IC4", "unit": "cents/gal", "agent_id": "Agent_NGL_MontBelvieu_Isobutane"},
    "natural_gasoline": {"label": "Mont Belvieu Natural Gasoline (C5+)", "code": "C5+", "unit": "cents/gal", "agent_id": "Agent_NGL_MontBelvieu_NatGasoline"},
    "henry_hub": {"label": "Henry Hub Natural Gas", "code": "HH", "unit": "USD/MMBtu", "agent_id": "Agent_HH_Spot_EIA"},
}
WTI_AGENT = "Agent_Crude_WTI_Spot"
CONWAY_AGENT = "Agent_NGL_Conway_Propane"
# Sessions shown per timeframe. The database holds DAILY closes only, so "intraday" is the last 60 sessions, not tick data.
TIMEFRAMES = {
    "intraday": {"label": "Intraday / short-term", "sessions": 60, "note": "daily closes, last 60 sessions (no intraday feed)"},
    "seasonal": {"label": "Seasonal swing", "sessions": 252, "note": "daily closes, last 252 sessions"},
    "multi_year": {"label": "Multi-year hedging", "sessions": 1260, "note": "daily closes, last 1260 sessions"},
}
FIB_RATIOS = (0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0)

GEO_NODES = [  # id, label, kind, lat, lon, agent (driver shown at the node, if any)
    ("MBV", "Mont Belvieu TX", "ngl_hub", 29.85, -94.89, "Agent_NGL_MontBelvieu_Propane"),
    ("CNW", "Conway KS", "ngl_hub", 38.37, -97.64, CONWAY_AGENT),
    ("HHB", "Henry Hub LA", "gas_hub", 29.96, -92.04, "Agent_HH_Spot_EIA"),
    ("CSH", "Cushing OK", "crude_hub", 35.98, -96.77, WTI_AGENT),
    ("SAB", "Sabine Pass LNG", "lng", 29.73, -93.87, "Agent_LNG_SabinePass_Flow"),
    ("CRP", "Corpus Christi LNG", "lng", 27.88, -97.27, "Agent_LNG_CorpusChristi_Flow"),
    ("FPT", "Freeport LNG", "lng", 28.94, -95.31, "Agent_LNG_Freeport_Flow"),
    ("CAM", "Cameron LNG", "lng", 30.04, -93.33, "Agent_LNG_Cameron_Flow"),
    ("CCP", "Calcasieu Pass LNG", "lng", 29.77, -93.34, "Agent_LNG_CalcasieuPass_Flow"),
    ("PLQ", "Plaquemines LNG", "lng", 29.60, -89.90, "Agent_LNG_Plaquemines_Flow"),
    ("ELB", "Elba Island LNG", "lng", 32.09, -81.00, "Agent_LNG_ElbaIsland_Flow"),
    ("CVP", "Cove Point LNG", "lng", 38.39, -76.41, "Agent_LNG_CovePoint_Flow"),
    ("PRM", "Permian Basin", "basin", 31.80, -102.40, "Agent_Prod_Permian"),
    ("APP", "Appalachia Basin", "basin", 40.50, -79.50, "Agent_Prod_Appalachia"),
    ("HYN", "Haynesville Basin", "basin", 32.30, -93.70, "Agent_Prod_Haynesville"),
    ("EGF", "Eagle Ford", "basin", 28.60, -98.60, "Agent_Prod_EagleFord"),
    ("BKN", "Bakken", "basin", 47.90, -103.00, "Agent_Prod_Bakken"),
    ("DJB", "DJ Basin", "basin", 40.30, -104.60, "Agent_Prod_DJBasin"),
]
# Schematic corridors: straight great-circle style links between real locations. They show which hubs are connected,
# NOT surveyed pipeline routes, and carry a measured value only where a flow collector exists.
GEO_FLOWS = [
    ("PRM", "MBV", "gas_ngl"), ("PRM", "CRP", "gas"), ("EGF", "CRP", "gas"), ("HYN", "SAB", "gas"), ("HYN", "HHB", "gas"),
    ("APP", "HHB", "gas"), ("APP", "CVP", "gas"), ("CNW", "MBV", "ngl"), ("BKN", "CNW", "ngl"), ("DJB", "CNW", "ngl"),
    ("HHB", "SAB", "gas"), ("HHB", "CAM", "gas"), ("HHB", "CCP", "gas"), ("HHB", "PLQ", "gas"), ("MBV", "FPT", "gas_ngl"),
    ("APP", "ELB", "gas"),
]
DRIVER_GROUPS = [
    ("production", "Shale gas production by basin", ["Agent_Prod_Appalachia", "Agent_Prod_Permian", "Agent_Prod_Haynesville",
                                                      "Agent_Prod_EagleFord", "Agent_Prod_Bakken", "Agent_Prod_DJBasin"]),
    ("weather", "Weather (CONUS population-weighted HDD/CDD)", ["Agent_Weather_Actual_HDD", "Agent_Weather_30YrNormal_HDD", "Agent_Weather_Actual_CDD",
                                                                 "Agent_GFS_00z_HDD_Day1", "Agent_GFS_00z_HDD_Day7", "Agent_GFS_00z_HDD_Day15",
                                                                 "Agent_ECMWF_00z_HDD_Day1", "Agent_ECMWF_00z_HDD_Day7"]),
    ("storage", "Working gas in storage by region", ["Agent_Storage_East", "Agent_Storage_Midwest", "Agent_Storage_Mountain", "Agent_Storage_Pacific",
                                                     "Agent_Storage_SouthCentral_Salt", "Agent_Storage_SouthCentral_NonSalt"]),
    ("demand", "Demand", ["Agent_Demand_Industrial", "Agent_Demand_ResComm", "Agent_Demand_PowerBurn"]),
    ("lng", "LNG feedgas", ["Agent_LNG_SabinePass_Flow", "Agent_LNG_CorpusChristi_Flow", "Agent_LNG_Freeport_Flow", "Agent_LNG_Cameron_Flow",
                            "Agent_LNG_CalcasieuPass_Flow", "Agent_LNG_CovePoint_Flow", "Agent_LNG_ElbaIsland_Flow", "Agent_LNG_Plaquemines_Flow"]),
    ("fractionation", "Fractionation / rejection economics", ["Agent_NGL_MontBelvieu_Ethane", "Agent_NGL_MontBelvieu_Propane", "Agent_HH_Spot_EIA"]),
    ("crude_and_carbon", "Crude and carbon", [WTI_AGENT, "Agent_Power_CO2_AllowancePrice"]),
]


# ----------------------------------------------------------------------------- pure maths (unit-tested)
def wti_ratio(cents_per_gal: float, wti_usd_bbl: float) -> float | None:
    """NGL price as a percentage of WTI: (cents/gal / 100 * 42) / WTI * 100."""
    if not wti_usd_bbl or wti_usd_bbl <= 0:
        return None
    return cents_per_gal / 100.0 * GAL_PER_BBL / wti_usd_bbl * 100.0


def ethane_usd_mmbtu(cents_per_gal: float) -> float:
    return cents_per_gal / 100.0 / ETHANE_MMBTU_PER_GAL


def frac_spread(ethane_cents_per_gal: float, henry_hub_usd_mmbtu: float) -> float:
    """Ethane value as fuel-equivalent minus Henry Hub, USD/MMBtu. Positive favours recovery, negative rejection."""
    return ethane_usd_mmbtu(ethane_cents_per_gal) - henry_hub_usd_mmbtu


def sma(values, window: int) -> np.ndarray:
    a = np.asarray(values, dtype=float)
    out = np.full(a.shape, np.nan)
    if len(a) >= window:
        c = np.cumsum(np.insert(a, 0, 0.0))
        out[window - 1:] = (c[window:] - c[:-window]) / window
    return out


def ema(values, span: int) -> np.ndarray:
    a = np.asarray(values, dtype=float)
    out = np.empty(a.shape)
    if not len(a):
        return out
    k = 2.0 / (span + 1.0)
    out[0] = a[0]
    for i in range(1, len(a)):
        out[i] = k * a[i] + (1 - k) * out[i - 1]
    return out


def bollinger(values, window: int = 20, k: float = 2.0, squeeze_pct: float = 20.0) -> dict:
    """SMA +/- k sigma, bandwidth % of the mid, and a squeeze flag where bandwidth <= its squeeze_pct percentile."""
    a = np.asarray(values, dtype=float)
    n = len(a)
    mid, up, lo, bw = (np.full(n, np.nan) for _ in range(4))
    if n >= window:
        w = np.lib.stride_tricks.sliding_window_view(a, window)
        m, s = w.mean(axis=1), w.std(axis=1)
        mid[window - 1:], up[window - 1:], lo[window - 1:] = m, m + k * s, m - k * s
        with np.errstate(divide="ignore", invalid="ignore"):
            bw[window - 1:] = np.where(m != 0, (2 * k * s) / m * 100.0, np.nan)
    valid = bw[~np.isnan(bw)]
    thr = float(np.percentile(valid, squeeze_pct)) if len(valid) else None
    squeeze = (bw <= thr) if thr is not None else np.zeros(n, dtype=bool)
    return {"mid": mid, "upper": up, "lower": lo, "bandwidth_pct": bw, "squeeze": squeeze, "squeeze_threshold": thr}


def rsi(values, period: int = 14) -> np.ndarray:
    """Wilder RSI."""
    a = np.asarray(values, dtype=float)
    out = np.full(a.shape, np.nan)
    if len(a) <= period:
        return out
    d = np.diff(a)
    g, l = np.where(d > 0, d, 0.0), np.where(d < 0, -d, 0.0)
    ag, al = g[:period].mean(), l[:period].mean()
    for i in range(period, len(d) + 1):
        if i > period:
            ag = (ag * (period - 1) + g[i - 1]) / period
            al = (al * (period - 1) + l[i - 1]) / period
        out[i] = 100.0 if al < 1e-12 else 100.0 - 100.0 / (1.0 + ag / al)
    return out


def macd(values, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    line = ema(values, fast) - ema(values, slow)
    sig = ema(line, signal)
    return {"line": line, "signal": sig, "hist": line - sig}


def ma_crossovers(dates, values, fast: int = 50, slow: int = 200) -> list:
    f, s = sma(values, fast), sma(values, slow)
    out = []
    for i in range(1, len(values)):
        if any(math.isnan(x) for x in (f[i], s[i], f[i - 1], s[i - 1])):
            continue
        if f[i - 1] <= s[i - 1] and f[i] > s[i]:
            out.append({"date": dates[i], "type": "golden_cross", "price": float(values[i])})
        elif f[i - 1] >= s[i - 1] and f[i] < s[i]:
            out.append({"date": dates[i], "type": "death_cross", "price": float(values[i])})
    return out


def fibonacci(dates, values) -> dict:
    """Retracement grid anchored to the window's swing high and low. In an up-leg (low before high) levels are measured
    down from the high; in a down-leg they are measured up from the low."""
    a = np.asarray(values, dtype=float)
    if len(a) < 2:
        return {"status": "insufficient_data"}
    ih, il = int(a.argmax()), int(a.argmin())
    hi, lo = float(a[ih]), float(a[il])
    span = hi - lo
    up_leg = il < ih
    levels = {f"{r * 100:.1f}%": (hi - span * r) if up_leg else (lo + span * r) for r in FIB_RATIOS}
    last = float(a[-1])
    nearest = min(levels, key=lambda k: abs(levels[k] - last))
    golden = levels["61.8%"]
    return {"status": "ok", "swing_high": hi, "swing_high_date": dates[ih], "swing_low": lo, "swing_low_date": dates[il],
            "leg": "up" if up_leg else "down", "levels": levels, "last": last, "nearest_level": nearest,
            "retracement_pct": ((hi - last) if up_leg else (last - lo)) / span * 100.0 if span else None,
            "golden_ratio_distance_pct_of_range": abs(last - golden) / span * 100.0 if span else None}


def swing_points(values, window: int = 3) -> tuple[list, list]:
    """Indices of local highs and lows: the extreme of the surrounding +/- window bars. A flat top or bottom counts once,
    at its first bar (flat tops are exactly what an ascending triangle is made of)."""
    a = np.asarray(values, dtype=float)
    hi, lo = [], []
    for i in range(window, len(a) - window):
        seg = a[i - window:i + window + 1]
        if a[i] == seg.max() and a[i] > a[i - 1]:
            hi.append(i)
        if a[i] == seg.min() and a[i] < a[i - 1]:
            lo.append(i)
    return hi, lo


def triangle_detection(dates, values, lookback: int = 60, flat_pct_per_bar: float = 0.04) -> dict:
    """Fit lines through the swing highs and swing lows of the last `lookback` bars and classify the shape.
    A side is 'flat' when its slope is under flat_pct_per_bar % of the mean price per bar. The lines must converge."""
    a = np.asarray(values[-lookback:], dtype=float)
    d = list(dates[-lookback:])
    none = {"pattern": "none", "lookback": len(a)}
    if len(a) < 20:
        return none
    hi, lo = swing_points(a)
    if len(hi) < 2 or len(lo) < 2:
        return none
    mh, bh = np.polyfit(hi, a[hi], 1)
    ml, bl = np.polyfit(lo, a[lo], 1)
    n = len(a) - 1
    u0, u1, l0, l1 = bh, mh * n + bh, bl, ml * n + bl
    flat = abs(float(a.mean())) * flat_pct_per_bar / 100.0
    converging = (u1 - l1) < (u0 - l0) and (u1 - l1) > 0
    up_flat, lo_flat = abs(mh) <= flat, abs(ml) <= flat
    if not converging:
        pattern = "none"
    elif up_flat and ml > flat:
        pattern = "ascending_triangle"
    elif mh < -flat and ml > flat:
        pattern = "symmetrical_triangle"
    elif mh < -flat and lo_flat:
        pattern = "descending_triangle"
    else:
        pattern = "none"
    out = {"pattern": pattern, "lookback": len(a), "converging": bool(converging),
           "upper": {"start_date": d[0], "start": float(u0), "end_date": d[-1], "end": float(u1), "slope_per_bar": float(mh)},
           "lower": {"start_date": d[0], "start": float(l0), "end_date": d[-1], "end": float(l1), "slope_per_bar": float(ml)},
           "breakout_above": float(u1), "breakdown_below": float(l1), "swing_highs": len(hi), "swing_lows": len(lo)}
    if converging and mh != ml:
        out["bars_to_apex"] = float((bl - bh) / (mh - ml) - n)
    return out


def _divergence(price, osc, window: int = 5, lookback: int = 80) -> str:
    p = np.asarray(price[-lookback:], dtype=float)
    o = np.asarray(osc[-lookback:], dtype=float)
    if len(p) < 30:
        return "none"
    hi, lo = swing_points(p, window)
    hi, lo = [i for i in hi if not np.isnan(o[i])], [i for i in lo if not np.isnan(o[i])]   # oscillator warm-up bars don't count
    if len(hi) >= 2 and p[hi[-1]] > p[hi[-2]] and o[hi[-1]] < o[hi[-2]]:
        return "bearish"
    if len(lo) >= 2 and p[lo[-1]] < p[lo[-2]] and o[lo[-1]] > o[lo[-2]]:
        return "bullish"
    return "none"


def rsi_macd_divergence(values) -> dict:
    """Bearish: price makes a higher swing high while the oscillator makes a lower one. Bullish: the mirror on swing lows."""
    return {"rsi": _divergence(values, rsi(values)), "macd": _divergence(values, macd(values)["line"])}


def _turns(values: list, flat_band: float) -> int:
    """Number of direction reversals between consecutive contracts, ignoring moves within flat_band."""
    moves = [(1 if b - a > flat_band else -1 if b - a < -flat_band else 0) for a, b in zip(values, values[1:])]
    nz = [m for m in moves if m]
    return sum(1 for a, b in zip(nz, nz[1:]) if a != b)


def curve_regime(points: list, flat_band: float = 0.05) -> str:
    """SEASONAL when a curve of 6+ contracts reverses direction at least twice (M12 minus M1 is then not a like-for-like slope: it compares
    different calendar months, e.g. December with November). Otherwise contango when the back is above the front by more than flat_band,
    backwardation when below."""
    if len(points) < 2:
        return "UNAVAILABLE"
    if len(points) >= 6 and _turns([p["value"] for p in points], flat_band) >= 2:
        return "SEASONAL"
    slope = points[-1]["value"] - points[0]["value"]
    return "CONTANGO" if slope > flat_band else "BACKWARDATION" if slope < -flat_band else "FLAT"


def curve_shape(points: list, flat_band: float = 0.05) -> dict:
    """Deterministic structural facts behind the regime label, every number computed from the points (nothing generated)."""
    if len(points) < 2:
        return {}
    vals = [p["value"] for p in points]
    hi, lo = max(points, key=lambda p: p["value"]), min(points, key=lambda p: p["value"])
    ref = lambda p: {"contract": p["contract"], "delivery_month": p.get("delivery_month"), "value": p["value"]}  # noqa: E731
    out = {"front_spread": round(vals[1] - vals[0], 4), "front_spread_label": f'{points[1]["contract"]} minus {points[0]["contract"]}',
           "last_minus_first": round(vals[-1] - vals[0], 4), "reversals": _turns(vals, flat_band), "peak": ref(hi), "trough": ref(lo)}
    regime = curve_regime(points, flat_band)
    if regime == "SEASONAL":
        out["basis"] = (f'Seasonal: the curve reverses direction {out["reversals"]} times (peak {hi["contract"]} {hi.get("delivery_month") or ""} {hi["value"]:.3f}, '
                        f'trough {lo["contract"]} {lo.get("delivery_month") or ""} {lo["value"]:.3f}), so {points[-1]["contract"]} minus {points[0]["contract"]} '
                        f'({out["last_minus_first"]:+.3f}) compares different calendar months and is not read as contango or backwardation.')
    else:
        out["basis"] = f'{regime.title()}: {points[-1]["contract"]} minus {points[0]["contract"]} = {out["last_minus_first"]:+.3f} (band {flat_band}).'
    return out


def seasonal_overlay(dates, values, as_of_year: int, years_back: int = 5, step: int = 7) -> dict:
    """Calendar-aligned band from the previous `years_back` complete years, plus the current year's path."""
    by_year: dict[int, dict[int, float]] = {}
    for d, v in zip(dates, values):
        y, doy = int(d[:4]), datetime.strptime(d, "%Y-%m-%d").timetuple().tm_yday
        by_year.setdefault(y, {})[min(doy, 365)] = v
    hist = [y for y in range(as_of_year - years_back, as_of_year) if len(by_year.get(y, {})) >= 150]
    grid = list(range(1, 366, step))

    def at(year, doy):
        ys = by_year.get(year, {})
        near = [k for k in ys if abs(k - doy) <= 3]
        return ys[min(near, key=lambda k: abs(k - doy))] if near else None

    bmin, bmax, bavg, cur = [], [], [], []
    for g in grid:
        vals = [v for v in (at(y, g) for y in hist) if v is not None]
        bmin.append(min(vals) if vals else None)
        bmax.append(max(vals) if vals else None)
        bavg.append(sum(vals) / len(vals) if vals else None)
        cur.append(at(as_of_year, g))
    return {"day_of_year": grid, "history_years": hist, "current_year": as_of_year, "band_min": bmin, "band_max": bmax,
            "band_avg": bavg, "current": cur, "lines": {str(y): [at(y, g) for g in grid] for y in hist}}


# ----------------------------------------------------------------------------- point-in-time reads
def _conn(db_path: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def pit_cutoff(as_of: str | None) -> str:
    """Normalise the requested cutoff to the stored 'YYYY-MM-DDTHH:MM:SSZ' form; default is now. Raises ValueError."""
    if not as_of:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    dt = datetime.fromisoformat(str(as_of).strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_series(conn, agent_id: str, as_of: str) -> list[tuple]:
    """[(date, value, available_timestamp)] for MEASURED rows only: latest vintage with available_timestamp <= as_of."""
    rows = conn.execute(
        "SELECT p.target_timestamp, p.value, p.available_timestamp FROM pit_market_data p WHERE p.agent_id=? AND p.available_timestamp<=? "
        "AND COALESCE(p.provenance,'measured')='measured' AND COALESCE(p.quality_status,'')<>'unverified_seed' "
        "AND p.available_timestamp=(SELECT MAX(q.available_timestamp) FROM pit_market_data q WHERE q.agent_id=p.agent_id "
        "AND q.target_timestamp=p.target_timestamp AND q.available_timestamp<=?) ORDER BY p.target_timestamp", (agent_id, as_of, as_of)).fetchall()
    assert all(r[2] <= as_of for r in rows), "LOOK-AHEAD: row published after the cutoff"
    return [(r[0][:10], float(r[1]), r[2]) for r in rows]


def latest_rows(conn, as_of: str) -> dict:
    """Newest PIT-eligible row per agent (by target date, then vintage), with its provenance and payload reference.
    Real rows always win: an old demo seed row is only reported for an agent that has nothing else."""
    cols = ("p.agent_id,p.target_timestamp,p.available_timestamp,p.value,p.unit,p.source_id,p.retrieved_timestamp,p.quality_status,"
            "p.raw_payload_hash,p.provenance,p.geographic_scope,p.series_id,p.published_timestamp")
    seed = "(COALESCE(quality_status,'')='unverified_seed' OR source_id IS NULL OR source_id='')"
    out = {}
    for real in (False, True):  # seeds first, then real rows overwrite them
        cond = f"NOT {seed}" if real else seed
        rows = conn.execute(
            f"SELECT {cols} FROM pit_market_data p JOIN (SELECT agent_id, MAX(target_timestamp) t FROM pit_market_data "
            f"WHERE available_timestamp<=? AND {cond} GROUP BY agent_id) m ON m.agent_id=p.agent_id AND m.t=p.target_timestamp "
            f"WHERE p.available_timestamp<=? AND {cond.replace('quality_status', 'p.quality_status').replace('source_id', 'p.source_id')} "
            "ORDER BY p.agent_id, p.available_timestamp", (as_of, as_of)).fetchall()
        for r in rows:  # ordered by vintage, so the last one per agent wins
            out[r[0]] = {"agent_id": r[0], "latest_target_timestamp": r[1], "available_timestamp": r[2], "value": r[3], "unit": r[4] or "",
                         "source_id": r[5], "retrieved_timestamp": r[6], "quality_status": r[7], "raw_payload_hash": r[8] or None,
                         "provenance": (r[9] or "measured") if real else "unverified_seed", "geographic_scope": r[10] or "",
                         "series_id": r[11] or "", "published_timestamp": r[12] or ""}
    return out


def _clean(x):
    """JSON-safe: numpy scalars to Python, NaN/inf to None, floats rounded."""
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, np.ndarray):
        return [_clean(v) for v in x.tolist()]
    if isinstance(x, (np.bool_, bool)):
        return bool(x)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        f = float(x)
        return None if (math.isnan(f) or math.isinf(f)) else round(f, 4)
    return x


def _roster() -> list:
    try:
        return [a["agent_id"] for a in json.loads((BASE_DIR / "agents_roster.json").read_text())]
    except Exception:  # noqa: BLE001
        return []


def _roster_meta() -> dict:
    """agent_id -> {series, source}: what each roster agent measures and where it is meant to come from (agents_roster.json)."""
    try:
        return {a["agent_id"]: {"series": a.get("series"), "source": a.get("source")} for a in json.loads((BASE_DIR / "agents_roster.json").read_text())}
    except Exception:  # noqa: BLE001
        return {}


_EXPLAIN: dict | None = None


def explain() -> dict:
    """Definitions and formulas for every figure (metric_docs.build), built once; parameters come from this module's own signatures."""
    global _EXPLAIN
    if _EXPLAIN is None:
        import metric_docs
        _EXPLAIN = metric_docs.build(sys.modules[__name__])
    return _EXPLAIN


def active_product(default: str = "propane") -> str:
    """The product the pricing run last marked active (first line of active_product.txt), else the default."""
    try:
        p = (BASE_DIR / "active_product.txt").read_text().strip().splitlines()[0].strip()
        return p if p in PRODUCTS else default
    except Exception:  # noqa: BLE001
        return default


def _aligned(a: list, b: list) -> list:
    """[(date, va, vb)] on dates present in both series."""
    bm = {d: v for d, v, _ in b}
    return [(d, v, bm[d]) for d, v, _ in a if d in bm]


def _age_days(ts: str | None, as_of: str) -> float | None:
    if not ts:
        return None
    f = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))
    return (f(as_of) - f(ts)).total_seconds() / 86400.0


def build_state(db_path: str, product: str | None = None, timeframe: str = "seasonal", as_of: str | None = None,
                knowledge: dict | None = None) -> dict:
    cutoff = pit_cutoff(as_of)
    product = product if product in PRODUCTS else active_product()
    timeframe = timeframe if timeframe in TIMEFRAMES else "seasonal"
    meta, tf = PRODUCTS[product], TIMEFRAMES[timeframe]
    conn = _conn(db_path)
    try:
        cache: dict[str, list] = {}

        def series(agent):
            if agent not in cache:
                cache[agent] = load_series(conn, agent, cutoff)
            return cache[agent]

        latest = latest_rows(conn, cutoff)
        stats = {"pit_rows": conn.execute("SELECT COUNT(*) FROM pit_market_data WHERE available_timestamp<=?", (cutoff,)).fetchone()[0],
                 "raw_payloads": conn.execute("SELECT COUNT(*) FROM raw_payloads").fetchone()[0]}
        payload_hashes = {r[0] for r in conn.execute("SELECT raw_payload_hash FROM raw_payloads")}
        wti = series(WTI_AGENT)

        # ---- product availability
        products = []
        for key, m in PRODUCTS.items():
            s = series(m["agent_id"])
            products.append({"id": key, "label": m["label"], "code": m["code"], "unit": m["unit"], "agent_id": m["agent_id"],
                             "status": "measured" if len(s) >= 30 else PENDING, "observations": len(s),
                             "latest": s[-1][1] if s else None, "latest_date": s[-1][0] if s else None,
                             "pct_of_wti": (wti_ratio(s[-1][1], wti[-1][1]) if (s and wti and m["unit"] == "cents/gal") else None)})

        # ---- active product: price, technicals, seasonal
        full = series(meta["agent_id"])
        n = tf["sessions"]
        state: dict[str, Any] = {}
        if len(full) >= 30:
            dates, vals = [r[0] for r in full], [r[1] for r in full]
            v = slice(max(0, len(vals) - n), len(vals))
            vd, vv = dates[v], vals[v]
            bb, mc, r14 = bollinger(vals), macd(vals), rsi(vals)
            s20, s50, s200 = sma(vals, 20), sma(vals, 50), sma(vals, 200)
            crosses = [c for c in ma_crossovers(dates, vals) if c["date"] >= vd[0]]
            fib, tri, div = fibonacci(vd, vv), triangle_detection(dates, vals, lookback=min(60, n)), rsi_macd_divergence(vals)
            prev = vals[-2] if len(vals) > 1 else vals[-1]
            wk = vals[-6] if len(vals) > 5 else vals[0]
            price = {"status": "measured", "provenance": "measured", "value": vals[-1], "unit": meta["unit"], "date": dates[-1],
                     "available_timestamp": full[-1][2], "change_1d": vals[-1] - prev, "change_1d_pct": (vals[-1] / prev - 1) * 100 if prev else None,
                     "change_5d": vals[-1] - wk, "change_5d_pct": (vals[-1] / wk - 1) * 100 if wk else None,
                     "window_high": max(vv), "window_low": min(vv),
                     "agent_id": meta["agent_id"], **{k: (latest.get(meta["agent_id"]) or {}).get(k) for k in ("source_id", "retrieved_timestamp", "quality_status", "raw_payload_hash")},
                     "pct_of_wti": wti_ratio(vals[-1], wti[-1][1]) if (wti and meta["unit"] == "cents/gal") else None}
            state["series"] = {"status": "measured", "dates": vd, "values": vv}
            state["technicals"] = {
                "status": "ok", "sma20": s20[v], "sma50": s50[v], "sma200": s200[v],
                "bollinger": {"upper": bb["upper"][v], "lower": bb["lower"][v], "mid": bb["mid"][v], "bandwidth_pct": bb["bandwidth_pct"][v],
                              "squeeze": bb["squeeze"][v], "squeeze_threshold_pct": bb["squeeze_threshold"], "squeeze_active": bool(bb["squeeze"][-1])},
                "rsi14": r14[v], "macd": {"line": mc["line"][v], "signal": mc["signal"][v], "hist": mc["hist"][v]},
                "crossovers": crosses[-8:], "fibonacci": fib, "triangle": tri, "divergence": div,
                "summary": {"last": vals[-1], "sma50": s50[-1], "sma200": s200[-1],
                            "trend": ("above_200dma" if vals[-1] > s200[-1] else "below_200dma") if not math.isnan(s200[-1]) else "insufficient_history",
                            "ma_regime": ("golden" if s50[-1] > s200[-1] else "death") if not (math.isnan(s50[-1]) or math.isnan(s200[-1])) else "insufficient_history",
                            "rsi14": r14[-1], "macd_hist": mc["hist"][-1], "bollinger_squeeze": bool(bb["squeeze"][-1]),
                            "bandwidth_pct": bb["bandwidth_pct"][-1], "triangle": tri["pattern"], "divergence_rsi": div["rsi"], "divergence_macd": div["macd"]}}
            state["seasonal"] = {"status": "ok", **seasonal_overlay(dates, vals, int(cutoff[:4]))}
        else:
            price = {"status": PENDING, "provenance": None, "value": None, "unit": meta["unit"],
                     "note": f"No collector publishes {meta['label']} yet, so there is no series. Nothing is simulated."}
            state["series"] = {"status": PENDING, "dates": [], "values": []}
            state["technicals"] = {"status": PENDING}
            state["seasonal"] = {"status": PENDING}

        # ---- relative-value curves
        def pct_curve(key):
            s = series(PRODUCTS[key]["agent_id"])
            al = _aligned(s, wti)[-252:]
            if len(al) < 30:
                return {"status": PENDING, "agent_id": PRODUCTS[key]["agent_id"]}
            return {"status": "measured", "dates": [a[0] for a in al], "pct_of_wti": [wti_ratio(a[1], a[2]) for a in al],
                    "latest": wti_ratio(al[-1][1], al[-1][2])}

        mb, cw = series(PRODUCTS["propane"]["agent_id"]), series(CONWAY_AGENT)
        hub = _aligned(mb, cw)[-252:]
        eth, hh = series(PRODUCTS["ethane"]["agent_id"]), series(PRODUCTS["henry_hub"]["agent_id"])
        fr = _aligned(eth, hh)[-252:]
        fwd = []
        for m_ in range(1, 13):
            r = latest.get(f"Agent_HH_M{m_}")
            if r and r["provenance"] == "measured":
                sid = r.get("series_id") or ""
                dm = sid[sid.rfind("(") + 1:-1] if sid.endswith(")") and "(" in sid else None   # "NGZ26.NYM (2026-12)" -> "2026-12"
                fwd.append({"contract": f"M{m_}", "value": r["value"], "date": r["latest_target_timestamp"][:10], "available_timestamp": r["available_timestamp"],
                            "unit": r["unit"], "series_id": sid, "delivery_month": dm, "source_id": r["source_id"], "quality_status": r["quality_status"],
                            "published_timestamp": r.get("published_timestamp") or None, "retrieved_timestamp": r["retrieved_timestamp"],
                            "raw_payload_hash": r["raw_payload_hash"]})
        fwd_dates = {p["date"] for p in fwd}
        fwd_age = _age_days(max(p["available_timestamp"] for p in fwd), cutoff) if fwd else None
        fwd_stale = bool(fwd) and (len(fwd_dates) > 1 or (fwd_age is not None and fwd_age > 10))
        curves = {
            "ngl_to_wti_pct": {"formula": "(cents/gal / 100 * 42) / WTI_usd_bbl * 100", "wti": {"status": "measured" if wti else PENDING,
                               "value": wti[-1][1] if wti else None, "date": wti[-1][0] if wti else None, "unit": "USD/bbl"},
                               "propane": pct_curve("propane"), "normal_butane": pct_curve("normal_butane"), "natural_gasoline": pct_curve("natural_gasoline")},
            "hub_spread": ({"status": "measured", "dates": [a[0] for a in hub], "mont_belvieu": [a[1] for a in hub], "conway": [a[2] for a in hub],
                            "spread_mb_minus_conway": [a[1] - a[2] for a in hub], "unit": "cents/gal"} if len(hub) >= 30 else
                           {"status": PENDING, "missing": [CONWAY_AGENT], "unit": "cents/gal",
                            "mont_belvieu_latest": mb[-1][1] if mb else None, "note": "Conway has no collector, so no spread is shown."}),
            "frac_spread": ({"status": "measured", "dates": [a[0] for a in fr], "ethane_usd_mmbtu": [ethane_usd_mmbtu(a[1]) for a in fr],
                             "henry_hub_usd_mmbtu": [a[2] for a in fr], "frac_spread_usd_mmbtu": [frac_spread(a[1], a[2]) for a in fr],
                             "regime": "RECOVERY" if frac_spread(fr[-1][1], fr[-1][2]) > 0 else "REJECTION"} if len(fr) >= 30 else
                            {"status": PENDING, "missing": [PRODUCTS["ethane"]["agent_id"]], "formula": "(cents/gal / 100) / 0.0665 - Henry Hub",
                             "henry_hub_latest": hh[-1][1] if hh else None, "note": "Ethane has no collector, so recovery vs rejection cannot be computed."}),
            "forward_curve": {"status": "measured" if fwd else PENDING, "points": fwd, "regime": curve_regime(fwd) if fwd else "UNAVAILABLE", "shape": curve_shape(fwd) if fwd else {},
                              "stale": fwd_stale, "as_of_date": max(fwd_dates) if fwd else None, "age_days": fwd_age,
                              "missing": [f"Agent_HH_M{m_}" for m_ in range(1, 13) if f"Agent_HH_M{m_}" not in {('Agent_HH_' + p['contract']) for p in fwd}],
                              "note": "EIA stopped publishing its NYMEX contract 1-4 series on 2024-04-05; M5-M12 have no collector." if fwd_stale else ""},
        }

        # ---- drivers
        def driver(agent):
            r = latest.get(agent)
            if not r or r["provenance"] == "unverified_seed":
                return {"agent_id": agent, "status": PENDING, "value": None, "provenance": None}
            return {"agent_id": agent, "status": r["provenance"], "value": r["value"], "unit": r["unit"], "target_date": r["latest_target_timestamp"][:10],
                    "available_timestamp": r["available_timestamp"], "provenance": r["provenance"], "quality_status": r["quality_status"]}

        drivers = [{"group": g, "label": lbl, "items": [driver(a) for a in agents]} for g, lbl, agents in DRIVER_GROUPS]
        hdd, norm = latest.get("Agent_Weather_Actual_HDD"), None
        if hdd:
            nr = conn.execute("SELECT value FROM pit_market_data WHERE agent_id='Agent_Weather_30YrNormal_HDD' AND target_timestamp=? AND available_timestamp<=?",
                              (hdd["latest_target_timestamp"], cutoff)).fetchone()
            norm = nr[0] if nr else None
        st = [latest.get(a) for a in DRIVER_GROUPS[2][2]]
        st_ok = [r for r in st if r and r["provenance"] == "measured"]
        derived = {"hdd_anomaly": {"value": (hdd["value"] - norm) if (hdd and norm is not None and hdd["provenance"] == "measured") else None,
                                   "date": hdd["latest_target_timestamp"][:10] if hdd else None, "unit": "HDD vs 30-yr normal", "provenance": "extracted_estimate"},
                   "storage_total_bcf": {"value": sum(r["value"] for r in st_ok) if len(st_ok) == 6 and len({r["latest_target_timestamp"] for r in st_ok}) == 1 else None,
                                         "date": st_ok[0]["latest_target_timestamp"][:10] if st_ok else None, "unit": "Bcf", "provenance": "extracted_estimate"},
                   "shale_production_total_bcfd": {"value": (lambda p: sum(x["value"] for x in p) if len(p) == 6 else None)(
                       [latest[a] for a in DRIVER_GROUPS[0][2] if a in latest]), "unit": "Bcf/d (six roster basins)", "provenance": "extracted_estimate"}}

        # ---- source availability (every roster agent, then extras)
        roster = _roster()
        agents = roster + sorted(a for a in latest if a not in set(roster))
        needed = {meta["agent_id"], WTI_AGENT} | {a for _, _, ag in DRIVER_GROUPS for a in ag}
        sources = []
        rmeta = _roster_meta()
        for a in agents:
            r = latest.get(a)
            if r:
                sources.append({"series": (rmeta.get(a) or {}).get("series"), "intended_source": (rmeta.get(a) or {}).get("source"),
                                **{k: r[k] for k in ("agent_id", "source_id", "latest_target_timestamp", "available_timestamp", "retrieved_timestamp",
                                                     "quality_status", "raw_payload_hash", "provenance")},
                                "status": "pending_collector" if r["provenance"] == "unverified_seed" else "collected",
                                "raw_payload_archived": bool(r["raw_payload_hash"]) and r["raw_payload_hash"] in payload_hashes,
                                "age_days": _age_days(r["available_timestamp"], cutoff), "in_roster": a in set(roster), "contributes": a in needed})
            else:
                sources.append({"series": (rmeta.get(a) or {}).get("series"), "intended_source": (rmeta.get(a) or {}).get("source"),
                                "agent_id": a, "source_id": None, "latest_target_timestamp": None, "available_timestamp": None, "retrieved_timestamp": None,
                                "quality_status": None, "raw_payload_hash": None, "provenance": None, "status": "pending_collector",
                                "raw_payload_archived": False, "age_days": None, "in_roster": True, "contributes": a in needed})
        collected = [s for s in sources if s["in_roster"] and s["status"] == "collected"]

        # ---- geography
        nodes = []
        for nid, label, kind, lat, lon, agent in GEO_NODES:
            r = latest.get(agent)
            ok = bool(r) and r["provenance"] == "measured"
            nodes.append({"id": nid, "label": label, "kind": kind, "lat": lat, "lon": lon, "agent_id": agent, "status": "measured" if ok else PENDING,
                          "value": r["value"] if ok else None, "unit": r["unit"] if ok else None, "date": r["latest_target_timestamp"][:10] if ok else None})
        flow_agents = [a for a in roster if a.startswith("Agent_Flow_") or (a.startswith("Agent_LNG_") and a.endswith("_Flow"))]
        flows_ok = [a for a in flow_agents if a in latest and latest[a]["provenance"] == "measured"]
        geo = {"nodes": nodes, "flows": [{"from": a, "to": b, "kind": k, "schematic": True, "value": None, "status": PENDING} for a, b, k in GEO_FLOWS],
               "note": "Corridors are schematic links between real locations, not surveyed pipeline routes. No pipeline-flow collector exists yet.",
               "flow_agents_collected": len(flows_ok), "flow_agents_total": len(flow_agents)}

        # ---- pipeline critical notices (source documents, PIT: posted at or before the cutoff)
        try:
            nrows = conn.execute("SELECT id, source_id, title, body, available_timestamp FROM documents WHERE domain='pipeline_notice' "
                                 "AND available_timestamp<=? ORDER BY available_timestamp DESC LIMIT 400", (cutoff,)).fetchall()
        except sqlite3.OperationalError:
            nrows = []
        week = [r for r in nrows if (_age_days(r[4], cutoff) or 0) <= 7]
        fm = [r for r in nrows if "FORCE MAJEURE." in r[3] and (_age_days(r[4], cutoff) or 0) <= 30]
        per = {}
        for r in week:
            k = r[1].replace("kinder_morgan_notices_", "").upper()
            per[k] = per.get(k, 0) + 1
        notices = {"status": "measured" if nrows else PENDING, "source": "Kinder Morgan informational postings (7 interstate pipelines)",
                   "last_7_days": len(week), "by_pipeline_7d": per,
                   "force_majeure_30d": [{"id": r[0], "title": r[2], "posted": r[4]} for r in fm[:10]],
                   "recent": [{"id": r[0], "pipeline": r[1].replace("kinder_morgan_notices_", "").upper(), "title": r[2], "posted": r[4]} for r in nrows[:12]],
                   "note": "Pipeline notices are the operators' own postings (source documents), shown as published."}

        # ---- alerts (all derived from the data above)
        alerts = []
        for r in fm[:3]:
            alerts.append({"level": "watch", "kind": "pipeline", "text": f"Force majeure ({r[4][:10]}): {r[2]}"})
        t = state["technicals"]
        if t.get("status") == "ok":
            s_ = t["summary"]
            if s_["bollinger_squeeze"]:
                alerts.append({"level": "watch", "kind": "technical", "text": f"{meta['label']}: Bollinger squeeze active (bandwidth {s_['bandwidth_pct']:.1f}%)."})
            for k in ("divergence_rsi", "divergence_macd"):
                if s_[k] != "none":
                    alerts.append({"level": "watch", "kind": "technical", "text": f"{meta['label']}: {s_[k]} {k.split('_')[1].upper()} divergence."})
            if s_["triangle"] != "none":
                alerts.append({"level": "watch", "kind": "technical", "text": f"{meta['label']}: {s_['triangle'].replace('_', ' ')}; breakout above {t['triangle']['breakout_above']:.3f}, breakdown below {t['triangle']['breakdown_below']:.3f}."})
            for c in t["crossovers"][-1:]:
                if (_age_days(c["date"] + "T00:00:00Z", cutoff) or 999) <= 30:
                    alerts.append({"level": "info", "kind": "technical", "text": f"{meta['label']}: {c['type'].replace('_', ' ')} on {c['date']}."})
        if derived["hdd_anomaly"]["value"] is not None and abs(derived["hdd_anomaly"]["value"]) >= 5:
            alerts.append({"level": "info", "kind": "weather", "text": f"CONUS HDD {derived['hdd_anomaly']['value']:+.1f} vs 30-yr normal on {derived['hdd_anomaly']['date']}."})
        alerts.append({"level": "gap", "kind": "coverage", "text": f"Pipeline and LNG flow volumes: {len(flows_ok)} of {len(flow_agents)} meters collected. "
                       f"Critical notices: {notices['last_7_days']} in the last 7 days from {len(per)} pipelines."})
        def max_age(agent):  # expected cadence: daily series 10 days, monthly 75, quarterly auctions 130, static normals never
            if agent == "Agent_Weather_30YrNormal_HDD":
                return None
            if agent.startswith(("Agent_Prod_", "Agent_Demand_")):
                return 75
            return 130 if agent.startswith("Agent_Power_CO2") else 10
        stale = [s for s in sources if s["status"] == "collected" and s["contributes"] and max_age(s["agent_id"]) is not None
                 and (s["age_days"] or 0) > max_age(s["agent_id"])]
        if stale:
            alerts.append({"level": "gap", "kind": "freshness", "text": "Contributing sources older than their expected cadence: "
                           + ", ".join(f"{s['agent_id']} ({s['age_days']:.0f}d)" for s in stale[:6]) + "."})
        pend = [p["code"] for p in products if p["status"] == PENDING]
        if pend:
            alerts.append({"level": "gap", "kind": "coverage", "text": "No price collector for: " + ", ".join(pend) + ". Curves that need them are withheld, not simulated."})

        out = {"schema": SCHEMA_VERSION, "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "as_of": cutoff,
               "active_product": product, "default_product": active_product(), "product": {"id": product, **meta},
               "timeframe": {"id": timeframe, **tf}, "products": products, "timeframes": [{"id": k, **v} for k, v in TIMEFRAMES.items()],
               "price": price, **state, "curves": curves, "drivers": drivers, "derived": derived, "sources": sources, "geo": geo, "notices": notices, "alerts": alerts,
               "knowledge": knowledge or {"status": "unavailable"}, "explain": explain(),
               "platform": {"roster_agents": len(roster), "roster_agents_collected": len(collected), "agents_with_data": len(latest), **stats,
                            "provenance_legend": {"measured": "published by the source and stored unchanged", "extracted_estimate": "derived here from measured rows",
                                                  "unverified_seed": "old demo row, excluded from every calculation", PENDING: "no collector yet; no value shown"}}}
        return _clean(out)
    finally:
        conn.close()


_CACHE: dict[tuple, tuple[float, dict]] = {}


def cached_state(db_path: str, product: str | None, timeframe: str, as_of: str | None = None, knowledge: dict | None = None, ttl: float = 60.0) -> dict:
    key = (db_path, product or "", timeframe, as_of or "")
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    data = build_state(db_path, product, timeframe, as_of, knowledge)
    if len(_CACHE) > 64:
        _CACHE.clear()
    _CACHE[key] = (time.time(), data)
    return data


if __name__ == "__main__":
    import sys
    db = os.environ.get("DB_PATH") or str(BASE_DIR / "henry_hub_pit.db")
    s = build_state(db, sys.argv[1] if len(sys.argv) > 1 else None, sys.argv[2] if len(sys.argv) > 2 else "seasonal")
    print(json.dumps({k: s[k] for k in ("schema", "as_of", "active_product", "price", "alerts", "platform")}, indent=1)[:3000])
