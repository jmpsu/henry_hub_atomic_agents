"""Module A: US LNG feedgas as a SEPARATELY CALCULATED, price-free series (checklist A1-A4, F0, F6, F7, F9, F11-F13).

Why separate: daily feedgas meters have no collector. Interpolating them with price-based models would bake forward-curve expectations into the
supply/demand balance, so this module is isolated from the pricing engine (it does not import markets_engine) and may read ONLY the physical inputs in
ALLOWED_PREFIXES. Henry Hub, TTF, FX, NGL prices, shipping rates, regional basis and demand-side weather are refused by `assert_inputs` (F0/F11/F12).

Method (what is implemented, and only that):
  anchor  EIA monthly LNG exports by terminal (Agent_LNGExports_*, MMcf/month -> Bcf/d), the verified ground truth (A2/F6, M6).
  step    terminal mass balance of F7 with the two terms we cannot observe set explicitly:  Feedgas = (dInventory + Cargo) / eta * (1 + Fuel)  with
          dInventory = 0 (no AIS / tank data) and the fuel-and-shrinkage uplift drawn per iteration from the 8-10 % range the user's source states (F7).
  spread  stationary block bootstrap (Politis-Romano, mean block 3 months) of the series' own historical monthly log-changes, 1,000 iterations (F9/F13),
          projected from the last published EIA month to the as-of date. p10/p50/p90 of the result are the three stored series (A4).
What it does NOT do, recorded in `not_used` and the checklist: EBB scheduled quantities (F1), AIS draft liftings (F2), ERCOT zonal load (F3), thermal/flare
(F4), the ambient-capacity regression (F8: it needs verified daily feedgas history that does not exist locally), tank-top re-anchoring (F9 step 3).
Ambient METAR is collected and reported as context; it is not applied to the estimate. Every output is tagged provenance `bootstrapped_physical_proxy`.

Run:  DB_PATH=henry_hub_pit.db python lng_feedgas.py    (writes lng_feedgas_p10/p50/p90 as Agent_LNGFeedgas_P10/P50/P90)"""
from __future__ import annotations

import calendar
import hashlib
import json
import math
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

BASE_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = Path(os.environ.get("QH_RUNTIME_DIR", BASE_DIR / "runtime"))
OUT_FILE = RUNTIME_DIR / "lng_feedgas.json"
PROVENANCE = "bootstrapped_physical_proxy"
EXTRACTION_VERSION = "lng_feedgas_v1"
SOURCE_ID = "lng_feedgas_model"
TERMINALS = {"SAB": "Agent_LNGExports_SabinePass", "CRP": "Agent_LNGExports_CorpusChristi", "FPT": "Agent_LNGExports_Freeport", "CAM": "Agent_LNGExports_Cameron",
             "CCP": "Agent_LNGExports_CalcasieuPass", "PLQ": "Agent_LNGExports_Plaquemines", "ELB": "Agent_LNGExports_ElbaIsland", "CVP": "Agent_LNGExports_CovePoint"}
SERIES = {"p10": "Agent_LNGFeedgas_P10", "p50": "Agent_LNGFeedgas_P50", "p90": "Agent_LNGFeedgas_P90"}     # series_id lng_feedgas_p10 / _p50 / _p90
ALLOWED_PREFIXES = ("Agent_LNGExports_", "Agent_AmbientTemp_", "Agent_AmbientDew_", "Agent_AmbientPress_")
FORBIDDEN_PREFIXES = ("Agent_HH_", "Agent_TTF_", "Agent_FX_", "Agent_NGL_", "Agent_Crude_", "Agent_Coal_", "Agent_Power_", "Agent_Weather_", "Agent_GFS_", "Agent_ECMWF_",
                      "Agent_Demand_", "Agent_Storage_", "Agent_Prod_", "Agent_LNG_", "Agent_Basis_", "Agent_Charter_", "Agent_JKM", "Agent_Flow_")
FUEL_SHRINK_RANGE = (0.08, 0.10)          # F7: "typically 8% to 10% of inbound gas is consumed as turbine fuel/shrinkage"
N_ITER = 1000                             # F13: 1,000 bootstrap iterations
MEAN_BLOCK_MONTHS = 3.0                   # F9 uses 5-7 day blocks for daily residuals; the anchor series is monthly, so a 3-month mean block keeps its autocorrelation
MIN_CHANGES = 12
NOT_USED = [
    {"id": "F1", "input": "interstate pipeline EBB OAC / scheduled quantities", "blocker": "only Kinder Morgan critical-notice text is collected (kinder_morgan_notices); no EBB scheduled-quantity scraper exists in the repo",
     "activate": "write collectors/ebb_<pipeline>.py per pipeline (Creole Trail, Transco, Elba Express, ...) and add the agents to the roster"},
    {"id": "F2", "input": "AIS vessel draft and berth dwell", "blocker": "no AIS provider or key is configured (no raw/terrestrial/satellite AIS feed on this host)",
     "activate": "set AISSTREAM_API_KEY (or another AIS provider key) in ~/.config/joey-secrets and add collectors/ais_lng.py"},
    {"id": "F3", "input": "ERCOT South/Coast zone load for Freeport and Corpus Christi Stage 3", "blocker": "ERCOT zonal data is not in the keyless EIA-930 files; the ERCOT public API needs registration",
     "activate": "register for the ERCOT public API, store the key in the vault, add collectors/ercot_load.py"},
    {"id": "F4", "input": "Sentinel-2 / Landsat / VIIRS thermal and flare", "blocker": "no remote-sensing access configured (VIIRS nightfire needs a NASA FIRMS key)",
     "activate": "set FIRMS_MAP_KEY and add collectors/viirs_flare.py"},
    {"id": "F8", "input": "ambient-capacity regression (temperature x active trains -> feedgas)", "blocker": "needs verified daily feedgas history, which does not exist locally (feedgas meters have no collector)",
     "activate": "after F1 collects scheduled quantities for >= 12 months, fit the regression in this module"},
]


def assert_inputs(agent_ids) -> None:
    """F0/F11/F12: refuse any market-derived or demand-side-weather input. Raises ValueError naming the offenders."""
    bad = [a for a in agent_ids if a.startswith(FORBIDDEN_PREFIXES) or not a.startswith(ALLOWED_PREFIXES)]
    if bad:
        raise ValueError(f"lng_feedgas refuses non-physical inputs (F0/F11/F12): {sorted(bad)}")


def _days(ym_ts: str) -> int:
    return calendar.monthrange(int(ym_ts[:4]), int(ym_ts[5:7]))[1]


def _series(conn, agent: str, cutoff: str) -> list:
    """[(target_ts, value)] latest vintage per target available at the cutoff, measured and non-seed rows only."""
    assert_inputs([agent])
    return conn.execute(
        "SELECT p.target_timestamp, p.value FROM pit_market_data p WHERE p.agent_id=? AND p.available_timestamp<=? AND COALESCE(p.provenance,'measured')='measured' "
        "AND COALESCE(p.quality_status,'')<>'unverified_seed' AND p.available_timestamp=(SELECT MAX(q.available_timestamp) FROM pit_market_data q "
        "WHERE q.agent_id=p.agent_id AND q.target_timestamp=p.target_timestamp AND q.available_timestamp<=?) ORDER BY p.target_timestamp", (agent, cutoff, cutoff)).fetchall()


def monthly_total_bcfd(conn, cutoff: str) -> tuple[list, dict]:
    """([(month 'YYYY-MM', total Bcf/d, frozenset(terminals present))], per-terminal {month: Bcf/d}). Total only over terminals present in that month."""
    per = {t: {r[0][:7]: r[1] / 1000.0 / _days(r[0]) for r in _series(conn, a, cutoff) if r[1] is not None} for t, a in TERMINALS.items()}
    months = sorted({m for d in per.values() for m in d})
    out = [(m, sum(d[m] for d in per.values() if m in d), frozenset(t for t, d in per.items() if m in d)) for m in months]
    return out, per


def log_changes(monthly: list) -> list:
    """Month-over-month log changes of the total, only between consecutive months with the SAME set of reporting terminals (a new terminal is not growth of the others)."""
    ch = []
    for (m0, v0, s0), (m1, v1, s1) in zip(monthly, monthly[1:]):
        y0, mo0 = int(m0[:4]), int(m0[5:])
        consecutive = (int(m1[:4]) * 12 + int(m1[5:])) - (y0 * 12 + mo0) == 1
        if consecutive and s0 == s1 and v0 > 0 and v1 > 0:
            ch.append(math.log(v1 / v0))
    return ch


def stationary_bootstrap_sums(changes: list, horizon: float, n: int, mean_block: float, rng: np.random.Generator) -> np.ndarray:
    """Cumulative log-change over `horizon` months for n resamples (stationary block bootstrap; a fractional last step is pro-rated)."""
    x = np.asarray(changes, dtype=float)
    k = len(x)
    steps = max(1, math.ceil(horizon))
    last_w = horizon - (steps - 1)                       # weight of the final (possibly partial) month
    p_new = 1.0 / mean_block
    out = np.empty(n)
    for i in range(n):
        idx = int(rng.integers(k))
        tot = 0.0
        for s in range(steps):
            if s and rng.random() < p_new:
                idx = int(rng.integers(k))
            else:
                idx = (idx + 1) % k if s else idx
            tot += x[idx] * (last_w if s == steps - 1 else 1.0)
        out[i] = tot
    return out


def wet_bulb_c(temp_c: float, dewpoint_c: float) -> float:
    """Stull (2011) wet-bulb temperature from air temperature and dew point (RH by the Magnus formula). Valid for RH 5-99 % and T -20..50 C."""
    rh = 100.0 * math.exp(17.625 * dewpoint_c / (243.04 + dewpoint_c)) / math.exp(17.625 * temp_c / (243.04 + temp_c))
    rh = min(max(rh, 5.0), 99.0)
    return (temp_c * math.atan(0.151977 * math.sqrt(rh + 8.313659)) + math.atan(temp_c + rh) - math.atan(rh - 1.676331)
            + 0.00391838 * rh ** 1.5 * math.atan(0.023101 * rh) - 4.686035)


def ambient_context(conn, cutoff: str) -> list:
    try:
        from collectors.metar_ambient import TERMINAL_STATIONS
    except Exception:  # noqa: BLE001
        return []
    out = []
    for term, icao in TERMINAL_STATIONS.items():
        t, d = _series(conn, f"Agent_AmbientTemp_{icao}", cutoff), _series(conn, f"Agent_AmbientDew_{icao}", cutoff)
        if t and d and t[-1][0] == d[-1][0]:
            out.append({"terminal": term, "station": icao, "observed": t[-1][0], "temp_c": t[-1][1], "dewpoint_c": d[-1][1], "wet_bulb_c": round(wet_bulb_c(t[-1][1], d[-1][1]), 1)})
    return out


def estimate(conn, as_of: str, n_iter: int = N_ITER) -> dict:
    """p10/p50/p90 US LNG feedgas (Bcf/d) at `as_of` (ISO timestamp), using only information available at `as_of`."""
    monthly, per = monthly_total_bcfd(conn, as_of)
    base = {"as_of": as_of, "provenance": PROVENANCE, "unit": "Bcf/d", "inputs": sorted(TERMINALS.values()), "not_used": NOT_USED,
            "evidence": {"ebb_scheduled_quantity": 0, "ais_draft": 0, "grid_load": 0, "monthly_eia_anchor": 1, "class": "inferred_from_monthly_anchor"},
            "method": "EIA monthly exports -> Bcf/d; Feedgas = Cargo x (1 + fuel/shrinkage 8-10%), dInventory = 0; stationary block bootstrap of monthly log-changes, 1000 iterations"}
    if not monthly:
        return {**base, "status": "pending_collector", "reason": "no EIA monthly LNG export rows available at the cutoff"}
    anchor_m, anchor_v, anchor_set = monthly[-1]
    changes = log_changes(monthly[-37:])
    if len(changes) < MIN_CHANGES:
        return {**base, "status": "pending_collector", "reason": f"only {len(changes)} usable month-over-month changes (need {MIN_CHANGES})", "anchor_month": anchor_m}
    anchor_mid = datetime(int(anchor_m[:4]), int(anchor_m[5:]), 15, tzinfo=timezone.utc)
    asof_dt = datetime.strptime(as_of[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    horizon = max((asof_dt - anchor_mid).days / 30.4375, 0.0)
    seed = int(hashlib.sha256(f"{anchor_m}|{as_of[:10]}|{len(changes)}".encode()).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)
    cum = stationary_bootstrap_sums(changes, horizon, n_iter, MEAN_BLOCK_MONTHS, rng) if horizon > 0 else np.zeros(n_iter)
    shrink = rng.uniform(*FUEL_SHRINK_RANGE, size=n_iter)
    feed = anchor_v * np.exp(cum) * (1.0 + shrink)
    q = np.percentile(feed, [10, 50, 90])
    terminals = {t: {"last_month": max(d), "exports_bcfd": round(d[max(d)], 4), "feedgas_baseline_bcfd": round(d[max(d)] * (1 + sum(FUEL_SHRINK_RANGE) / 2), 4)} for t, d in per.items() if d}
    return {**base, "status": "estimate", "p10": round(float(q[0]), 4), "p50": round(float(q[1]), 4), "p90": round(float(q[2]), 4),
            "anchor_month": anchor_m, "anchor_exports_bcfd": round(anchor_v, 4), "anchor_terminals": sorted(anchor_set), "horizon_months": round(horizon, 2),
            "n_iterations": n_iter, "n_changes": len(changes), "mean_block_months": MEAN_BLOCK_MONTHS, "fuel_shrink_range": FUEL_SHRINK_RANGE, "seed": seed,
            "per_terminal_baseline": terminals, "ambient_context": ambient_context(conn, as_of),
            "ambient_note": "METAR ambient and wet-bulb are collected and shown; they are NOT applied to the estimate (the ambient-capacity regression F8 needs verified daily history)."}


def store(conn, est: dict, now: str | None = None) -> int:
    """Write the three series (A4). target = the as-of date; available = now. Idempotent per (agent, target, available)."""
    import ingest
    if est.get("status") != "estimate":
        return 0
    now = now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    n = 0
    for key, agent in SERIES.items():
        n += bool(ingest.record_observation(
            conn, agent_id=agent, target_timestamp=est["as_of"][:10] + "T00:00:00Z", available_timestamp=now, value=est[key], source_id=SOURCE_ID, unit="Bcf/d",
            retrieved_timestamp=now, published_timestamp=now, geographic_scope="US LNG export terminals (8)", series_id=f"lng_feedgas_{key}", raw_payload_hash="",
            extraction_version=EXTRACTION_VERSION, quality_status="monthly_anchor_bootstrap_no_ebb_ais", provenance=PROVENANCE))
    conn.commit()
    return n


def load(cutoff: str, path: Path = OUT_FILE) -> dict | None:
    """The latest model output that was already available at `cutoff` (point in time): None if missing, produced after the cutoff, or as-of after the cutoff."""
    try:
        doc = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    return doc if doc.get("available_timestamp", "9999") <= cutoff and doc.get("as_of", "9999") <= cutoff else None


def run(db_path: str, as_of: str | None = None, out_path: Path = OUT_FILE) -> dict:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        est = estimate(conn, as_of or now)
        est["rows_written"] = store(conn, est, now)
        est["available_timestamp"] = now
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = out_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(est, indent=2))
        tmp.replace(out_path)
        return est
    finally:
        conn.close()


if __name__ == "__main__":
    out = run(os.environ.get("DB_PATH") or str(Path(__file__).resolve().parent / "henry_hub_pit.db"))
    print(json.dumps({k: v for k, v in out.items() if k not in ("not_used", "per_terminal_baseline", "inputs")}, indent=2))
