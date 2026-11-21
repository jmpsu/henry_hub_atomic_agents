"""Power, Natural Gas & Cross-Commodity Modeling (QUANT_HUB_SPEC section 3).

Data-driven functions read PIT series via markets_engine.load_series (available_timestamp <= as_of everywhere).
Pure calculation functions (spark_spread, clean_spark_spread, dark_spread, basis_differential) take explicit
inputs and never invent numbers.
"""
from __future__ import annotations

import sqlite3
import statistics
from datetime import date, timedelta

import kb_ingest
import markets_engine as me

DEFAULT_HEAT_RATE = 8.5  # MMBtu per MWh of gas-fired generation (mixed-fuel rate)


def _dt(ts: str):
    from datetime import datetime
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _iso(dt) -> str:
    from datetime import datetime, timezone
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

REGIONAL_NODES = {
    "ERCOT": ("ercot", "Electric Reliability Council of Texas"),
    "PJM": ("pjm", "PJM Interconnection"),
    "MISO": ("miso", "Midcontinent Independent System Operator"),
    "CAISO": ("caiso", "California Independent System Operator"),
    "NYISO": ("nyiso", "New York Independent System Operator"),
}


# ----------------------------------------------------------------------------- pure heat-rate economics
def spark_spread(hh_price: float, electric_price_per_mwh: float, heat_rate: float = DEFAULT_HEAT_RATE) -> float:
    """Spark spread: HH natural gas price per MMBtu minus the power price expressed per MMBtu
    (electric_price_per_mwh / heat_rate). Positive = gas has the swing above the power cost."""
    return hh_price - electric_price_per_mwh / heat_rate


def clean_spark_spread(hh_price: float, electric_price_per_mwh: float, heat_rate: float = DEFAULT_HEAT_RATE,
                       fuel_adjustment_cost_per_mmbtu: float = 0.0) -> float:
    """Clean spark spread: spark spread adjusted for fuel-supply and customer charges (per MMBtu)."""
    return spark_spread(hh_price, electric_price_per_mwh, heat_rate) - fuel_adjustment_cost_per_mmbtu


def dark_spread(hh_price: float, electric_price_per_mwh: float, heat_rate: float = DEFAULT_HEAT_RATE) -> float:
    """Dark spread (power-side value): the negative of the spark spread."""
    return -spark_spread(hh_price, electric_price_per_mwh, heat_rate)


def basis_differential(hh_price: float, market_price: float) -> float:
    """HH basis against another commodity market: HH price minus the market price at the same date."""
    return hh_price - market_price


# ----------------------------------------------------------------------------- Henry Hub spot & forward curve
def hh_spot(conn, as_of: str):
    """Latest PIT-visible Henry Hub spot: (date, price, available_timestamp) or None."""
    s = me.load_series(conn, "Agent_HH_Spot_EIA", as_of)
    return s[-1] if s else None


def hh_forward_curve(conn, as_of: str, horizon_days: int = 90):
    """Forward curve: linear extrapolation of recent daily HH spot changes (slope 0 without history).
    Never extrapolates below zero: returns [(date, price), ...]."""
    s = me.load_series(conn, "Agent_HH_Spot_EIA", as_of)
    if not s:
        return []
    if len(s) == 1:
        base = s[-1]
        return [(base[0], base[1])] + [(base[0], max(base[1], 0.0)) for _ in range(horizon_days)]
    changes = [s[i][1] - s[i - 1][1] for i in range(1, len(s))][-30:]
    slope = sum(changes) / len(changes) if changes else 0.0
    if slope < -s[-1][1]:
        slope = 0.0
    price, d0 = s[-1][1], date.fromisoformat(s[-1][0])
    out = [(s[-1][0], price)]
    for d in range(1, horizon_days + 1):
        price = max(price + slope, 0.0)
        out.append(((d0 + timedelta(days=d)).isoformat(), price))
    return out


# ----------------------------------------------------------------------------- basis differentials (Waha / HSC / Transco Z6)
def hh_basis(conn, as_of: str) -> dict:
    """HH basis against each basis market proxy ingested into the PIT database.
    {name: {"hh": price, "market": proxy_price, "differential": hh - market, "market_agent": agent_id, ...}}
    A name maps to None when the database has no ingested market series for it."""
    hh = hh_spot(conn, as_of)
    if not hh:
        return {name: None for name in ("Waha", "Houston Ship Channel", "Transco Zone 6")}
    out = {}
    for name, token in (("Waha", "waha"), ("Houston Ship Channel", "hsc"), ("Transco Zone 6", "tz6")):
        rows = conn.execute("SELECT DISTINCT agent_id FROM pit_market_data WHERE agent_id LIKE ? AND available_timestamp<=? "
                            "AND COALESCE(provenance,'measured')='measured'", (f"%{token}%", as_of)).fetchall()
        entry = None
        if rows:
            s = me.load_series(conn, rows[0][0], as_of)
            entry = {"hh": hh[1], "market": s[-1][1], "differential": hh[1] - s[-1][1], "hh_available_timestamp": hh[2],
                     "market_agent": rows[0][0], "available_timestamp": s[-1][2]}
        out[name] = entry
    return out


# ----------------------------------------------------------------------------- regional ISO/RTO nodes
def regional_spot(conn, node: str, as_of: str) -> dict | None:
    """Measured spot for a regional node when the database has it; otherwise the Henry Hub proxy."""
    rows = conn.execute("SELECT DISTINCT agent_id FROM pit_market_data WHERE agent_id LIKE ? AND available_timestamp<=? "
                        "AND COALESCE(provenance,'measured')='measured'", (f"%{node.lower()}%", as_of)).fetchall()
    if rows:
        s = me.load_series(conn, rows[0][0], as_of)
        if s:
            return {"node": node, "price": s[-1][1], "available_timestamp": s[-1][2], "source": "measured", "agent_id": rows[0][0]}
    hh = hh_spot(conn, as_of)
    return {"node": node, "price": hh[1], "available_timestamp": hh[2], "source": "hh_proxy", "agent_id": "Agent_HH_Spot_EIA"} if hh else None


# ----------------------------------------------------------------------------- EIA storage cycle impacts
def storage_cycle_impact(conn, as_of: str) -> dict:
    """Weekly EIA working-gas change across Lower-48 regions; per-region when series exist."""
    per = []
    for a in kb_ingest.STORAGE:
        s = me.load_series(conn, a, as_of)
        if len(s) >= 2:
            per.append({"agent": a, "change_bcf": s[-1][1] - s[-2][1], "available_timestamp": s[-1][2]})
    total = sum(x["change_bcf"] for x in per) if per else None
    return {"total_change_bcf": total, "per_region": per, "cadence": "weekly", "as_of": as_of}


# ----------------------------------------------------------------------------- pipeline flows
def _flow_series(conn):
    """Ingested pipeline Flow series [(agent_id,)] when the database has them."""
    try:
        return [r[0] for r in conn.execute("SELECT agent_id FROM pit_market_data WHERE agent_id LIKE 'Agent_Flow_%' "
                                           "GROUP BY agent_id ORDER BY agent_id").fetchall()]
    except sqlite3.OperationalError:
        return []


def pipeline_flow_estimate(conn, as_of: str, horizon_days: int = 30) -> dict | None:
    """Constrained-flow estimate: capacity_restriction notice counts in the trailing window when the notice
    extraction table exists; otherwise the recent median of ingested Flow-series weekly deltas."""
    lo = _iso(_dt(as_of) - timedelta(days=horizon_days)) if as_of else ""
    n = 0
    try:
        n = conn.execute("SELECT COUNT(*) FROM notice_extractions WHERE posted<=? AND posted>? AND event_type='capacity_restriction'",
                         (as_of, lo)).fetchone()[0]
    except sqlite3.OperationalError:
        n = 0
    if n > 0:
        return {"basis": "capacity_restriction_notices", "count": n, "flow_reduction_estimate_mmbtu_per_day": round(0.04 * n, 4),
                "cadence_days": horizon_days, "available_timestamp": as_of}
    deltas = []
    for agent in _flow_series(conn):
        s = me.load_series(conn, agent, as_of)
        deltas.extend(s[i][1] - s[i - 1][1] for i in range(1, len(s)) if len(s) > 1)
    if not deltas:
        return None
    return {"basis": "flow_series_median_weekly_delta", "median_flow_delta": round(statistics.median(deltas[-60:]), 4),
            "series": [a for a in _flow_series(conn)], "available_timestamp": as_of}


# ----------------------------------------------------------------------------- LNG export terminal demand
def lng_export_demand_score(conn, as_of: str) -> dict | None:
    """Approximate LNG export terminal demand: net injection rate (storage change) minus estimated pipeline flow
    reduction. Positive = net terminal-side demand; None when neither is measurable."""
    sc = storage_cycle_impact(conn, as_of)
    pf = pipeline_flow_estimate(conn, as_of)
    if sc["total_change_bcf"] is None:
        return None
    red = 0.0
    if pf:
        red = pf.get("flow_reduction_estimate_mmbtu_per_day") or pf.get("median_flow_delta") or 0.0
    return {"net_demand_estimate_mmbtu_per_day": round(sc["total_change_bcf"] - red, 4),
            "injections_bcf": sc["total_change_bcf"], "flow_reduction_estimate_mmbtu_per_day": round(red, 4),
            "available_timestamp": as_of}


# ----------------------------------------------------------------------------- cross-commodity exposure
def cross_commodity_exposure(conn, as_of: str) -> dict:
    """Cross-commodity exposure to North American crude, refined-product and carbon markets (PIT vintages)."""
    def last(agent):
        s = me.load_series(conn, agent, as_of)
        return {"agent_id": agent, "price": s[-1][1], "available_timestamp": s[-1][2]} if s else None

    wti, brent = last("Agent_Crude_WTI_Spot"), last("Agent_Crude_Brent_Spot")
    ratio = round(wti["price"] / brent["price"], 4) if wti and brent and wti["price"] and brent["price"] else None
    return {"wti": wti, "brent": brent, "wti_brent_ratio": ratio,
            "refined_products": [last(a) for a in ("Agent_Gasoline_Spot", "Agent_Diesel_Spot")],
            "carbon_allowances": last("Agent_Power_CO2_AllowancePrice"), "available_timestamp": as_of}
