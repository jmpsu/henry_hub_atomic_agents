"""G5: the seven fundamental elements, classified as DIRECT INGESTED INPUTS or SEPARATELY CALCULATED ORTHOGONAL MODULES (checklist M1-M7).

Pure: takes the engine's point-in-time `latest` rows (already <= the cutoff) and the two module outputs; reads nothing itself and prices nothing.
`price_path` states plainly whether the element influences any forward price shown on the page. Today none does (checklist O6: there is no fundamentals-to-price
model); the block says so instead of implying it. Module outputs are shown with their own provenance and their blockers."""
from __future__ import annotations

from datetime import datetime, timezone

DIRECT, SEPARATE = "direct_ingested_input", "calculated_separately"
DEFINED = "2026-11-17T00:00:00Z"        # when the classification below was adopted (used as the knowledge-graph node availability)
ELEMENTS = [
    {"id": "M1", "key": "production", "label": "Shale gas production by basin", "mode": DIRECT, "method": "Direct use (with lag: the latest published month is held, not extrapolated)",
     "source": "EIA DPR / STEO (Bcf/d, monthly average)", "role": "Structural supply baseline by basin (Appalachia, Permian, Haynesville)",
     "scope_rule": "", "graph_link": "Links basin supply nodes to regional basis and pipeline bottlenecks"},
    {"id": "M2", "key": "weather", "label": "Weather (CONUS population-weighted HDD/CDD)", "mode": DIRECT, "method": "Direct use (strict scope)",
     "source": "NOAA/CPC (daily actuals + 15-day ensemble)", "role": "Residential/commercial demand only",
     "scope_rule": "Excluded from the LNG liquefaction capacity equations (enforced in lng_feedgas.assert_inputs)", "graph_link": "Explains short-term storage draws/injections and Henry Hub prompt spikes"},
    {"id": "M3", "key": "storage", "label": "Working gas in storage by region", "mode": DIRECT, "method": "Direct use",
     "source": "EIA Weekly Natural Gas Storage Report (Bcf by 5 regions)", "role": "Core inventory-to-normal deficit/surplus curve driver",
     "scope_rule": "", "graph_link": "Links regional storage nodes (South Central salt/nonsalt) to seasonal spreads"},
    {"id": "M4", "key": "lng", "label": "LNG feedgas (daily meters, no collector yet)", "mode": SEPARATE, "method": "Calculated separately (bootstrapped proxy), module lng_feedgas.py",
     "source": "Physical EBB scrapes + AIS draft + ERCOT power + METAR ambient temp (only EIA monthly exports and METAR are available)",
     "role": "Demand sink input with propagated confidence intervals (10th/50th/90th pct)", "scope_rule": "No price, basis, charter-rate or demand-weather input (F0/F11/F12)",
     "graph_link": "Explains real-time terminal utilization while flagging pending collector status"},
    {"id": "M5", "key": "fractionation", "label": "Fractionation / rejection economics", "mode": SEPARATE, "method": "Calculated separately (independent spread), module frac_module.py",
     "source": "Mont Belvieu purity NGL prices vs Henry Hub BTU parity (cents/gal vs $/MMBtu)", "role": "Computes ethane rejection/recovery volume (Bcf/d added/removed from dry gas)",
     "scope_rule": "Only the net dry-gas delta (Bcf/d) may leave the module (B4)", "graph_link": "Connects NGL visual intelligence (Mont Belvieu vs Conway, frac spread) to dry gas supply"},
    {"id": "M6", "key": "lng_exports", "label": "LNG exports by terminal (EIA, monthly)", "mode": DIRECT, "method": "Direct use (calibration anchor)",
     "source": "EIA Natural Gas Monthly (Bcf/month per terminal)", "role": "Ground-truth anchor to calibrate and re-zero the daily bootstrapped feedgas model",
     "scope_rule": "", "graph_link": "Historical terminal capacity utilization and verified monthly provenance"},
    {"id": "M7", "key": "border_flows", "label": "Pipeline volumes at border points (EIA, monthly)", "mode": DIRECT, "method": "Direct use",
     "source": "EIA Monthly (Bcf/month US-Mexico and US-Canada net flows)", "role": "Net cross-border structural demand/supply offset (e.g., Permian-to-Mexico exports)",
     "scope_rule": "", "graph_link": "Explains regional flow balances in South Central and Midwest/Northeast hubs"},
]
GROUP_AGENTS = {}      # filled by the engine's DRIVER_GROUPS (kept in one place there)


def _age(ts: str | None, cutoff: str) -> float | None:
    if not ts:
        return None
    f = "%Y-%m-%dT%H:%M:%SZ"
    return round((datetime.strptime(cutoff, f).replace(tzinfo=timezone.utc) - datetime.strptime(ts, f).replace(tzinfo=timezone.utc)).total_seconds() / 86400.0, 1)


def value_at(points: list, as_of_date: str) -> dict | None:
    """Monthly series [(YYYY-MM-DD month start, value)] -> value on `as_of_date`. A month's value sits at its mid-month; between two published
    months it is linearly interpolated; after the last published month it is HELD (extrapolation is refused) and flagged."""
    pts = sorted((datetime.strptime(d[:7] + "-15", "%Y-%m-%d"), v) for d, v in points if v is not None)
    if not pts:
        return None
    t = datetime.strptime(as_of_date[:10], "%Y-%m-%d")
    if t >= pts[-1][0]:
        return {"value": pts[-1][1], "mode": "held", "reference_month": pts[-1][0].strftime("%Y-%m"), "lag_days": (t - pts[-1][0]).days}
    if t <= pts[0][0]:
        return {"value": pts[0][1], "mode": "before_range", "reference_month": pts[0][0].strftime("%Y-%m"), "lag_days": 0}
    for (t0, v0), (t1, v1) in zip(pts, pts[1:]):
        if t0 <= t <= t1:
            w = (t - t0).days / max((t1 - t0).days, 1)
            return {"value": v0 + w * (v1 - v0), "mode": "interpolated", "between": [t0.strftime("%Y-%m"), t1.strftime("%Y-%m")], "lag_days": 0}
    return None


def _sum_group(latest: dict, agents: list) -> tuple[float | None, str | None, int]:
    rows = [latest[a] for a in agents if a in latest and latest[a]["provenance"] == "measured"]
    if not rows:
        return None, None, 0
    return sum(r["value"] for r in rows), max(r["latest_target_timestamp"] for r in rows)[:10], len(rows)


def build(latest: dict, group_agents: dict, derived: dict, feedgas: dict | None, frac: dict, cutoff: str, price_path_note: str = "") -> dict:
    """latest: engine rows keyed by agent; group_agents: {group key: [agent ids]}; derived: engine `derived`; feedgas: lng_feedgas.estimate-like dict or None; frac: frac_module.build()."""
    items = []
    for e in ELEMENTS:
        agents = group_agents.get(e["key"], [])
        have = [a for a in agents if a in latest and latest[a]["provenance"] == "measured"]
        it = {**e, "agents": agents, "agents_collected": len(have), "agents_total": len(agents), "blocked": [], "status": "measured" if have else "pending_collector"}
        newest = max((latest[a]["available_timestamp"] for a in have), default=None)
        if e["id"] == "M1":
            v, d, n = _sum_group(latest, agents)
            it["headline"] = {"label": "Six roster basins, latest month", "value": v, "unit": "Bcf/d", "date": d, "n": n, "provenance": "measured"} if v is not None else None
            if d:
                it["headline"]["lag_days"] = (datetime.strptime(cutoff[:10], "%Y-%m-%d") - datetime.strptime(d[:7] + "-15", "%Y-%m-%d")).days
        elif e["id"] == "M2":
            a = derived.get("hdd_anomaly") or {}
            it["headline"] = {"label": "CONUS HDD vs 30-year normal", "value": a.get("value"), "unit": a.get("unit"), "date": a.get("date"), "provenance": a.get("provenance")} if a.get("value") is not None else None
            it["scope_verified"] = True
        elif e["id"] == "M3":
            a = derived.get("storage_total_bcf") or {}
            it["headline"] = {"label": "Working gas, regions reported", "value": a.get("value"), "unit": "Bcf", "date": a.get("date"), "provenance": a.get("provenance")} if a.get("value") is not None else None
            if have and len(have) < 6:
                it["blocked"].append({"input": "storage history", "reason": f"{len(have)} of 6 regions have a stored weekly value; a 5-year-normal deficit/surplus needs more history than is stored",
                                      "activate": "python collectors/eia_storage.py (weekly) and a history backfill"})
        elif e["id"] == "M4":
            it["status"] = (feedgas or {}).get("status", "pending_collector")
            if feedgas and feedgas.get("status") == "estimate":
                it["headline"] = {"label": "US LNG feedgas p10 / p50 / p90", "value": feedgas["p50"], "p10": feedgas["p10"], "p90": feedgas["p90"], "unit": "Bcf/d",
                                  "date": (feedgas.get("as_of") or "")[:10], "provenance": feedgas.get("provenance"), "anchor_month": feedgas.get("anchor_month")}
            it["blocked"] = [{"input": b["input"], "reason": b["blocker"], "activate": b["activate"], "id": b["id"]} for b in (feedgas or {}).get("not_used", [])]
        elif e["id"] == "M5":
            it["status"] = frac.get("status", "pending_collector")
            it["blocked"] = list(frac.get("blocked", [])) + ([frac["waha"]] if frac.get("waha", {}).get("status") == "BLOCKED" else [])
            if frac.get("status") == "estimate":
                it["headline"] = {"label": f"Ethane {frac['regime'].lower()}; net dry-gas delta (central)", "value": frac["net_dry_gas_delta_bcfd"]["central"], "unit": "Bcf/d",
                                  "date": frac.get("ethane_date"), "provenance": frac.get("provenance")}
        elif e["id"] == "M6":
            v, d, n = _sum_group(latest, agents)
            it["headline"] = {"label": "Sum of terminals, latest month", "value": v / 1000.0, "unit": "Bcf/month", "date": d, "n": n, "provenance": "measured"} if v is not None else None
        elif e["id"] == "M7":      # net cross-border flow: imports from Canada minus exports to Mexico (both EIA monthly, MMcf)
            inn, d1, n1 = _sum_group(latest, [a for a in agents if a.endswith("_FromCanada")])
            out, d2, n2 = _sum_group(latest, [a for a in agents if a.endswith("_ToMexico")])
            if n1 and n2 and d1 == d2:
                it["headline"] = {"label": "Net imports (Canada in, Mexico out), latest month", "value": (inn - out) / 1000.0, "unit": "Bcf/month", "date": d1, "n": n1 + n2,
                                  "imports_canada_bcf": inn / 1000.0, "exports_mexico_bcf": out / 1000.0, "provenance": "measured"}
        it.setdefault("headline", None)
        it["age_days"] = _age(newest, cutoff)
        it["price_path"] = {"used_in_price": False, "reason": price_path_note}
        items.append(it)
    return {"elements": items, "direct": [i["id"] for i in items if i["mode"] == DIRECT], "separate": [i["id"] for i in items if i["mode"] == SEPARATE],
            "price_note": price_path_note,
            "legend": {DIRECT: "ingested as published, only aligned to the point-in-time cutoff", SEPARATE: "computed in its own isolated module before the pricing engine; only its output crosses over"}}
