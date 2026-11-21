"""Integrated 20-calculation Global LNG Forward Pricing Model.

All delivery months M1-M24 are produced. Observed point-in-time quotes anchor the curve where available; every missing input is estimated from
calibrated fundamentals, engineering cost stacks, comparable-market relationships, route simulation and correlated scenario simulation. The older
``lng_forward`` module is preserved unchanged; this module is additive and exposes one coherent payload through ``curves.lng_global``.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

import lng_config as cfg

BASE_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = Path(os.environ.get("QH_RUNTIME_DIR", BASE_DIR / "runtime"))
CALIBRATION_FILE = RUNTIME_DIR / "lng_global_calibration.json"
MODEL_VERSION = "lng_global_v2"
PROVENANCE = "modeled_estimate"
DELIVERY_COUNT = 24
MMBTU_PER_MWH = cfg.MMBTU_PER_MWH
FRESHNESS_RULES = {
    "hh_forward": {"max_age_days": 10.0, "basis": "existing forward_curve staleness threshold"},
    "ttf_forward": {"max_age_days": float(cfg.MAX_QUOTE_AGE_DAYS), "basis": "lng_config.MAX_QUOTE_AGE_DAYS"},
    "fx_eurusd": {"max_age_days": float(cfg.MAX_QUOTE_AGE_DAYS), "basis": "lng_config.MAX_QUOTE_AGE_DAYS"},
    "oil": {"max_age_days": 10.0, "basis": "existing forward_curve staleness threshold applied to slow daily crude closes"},
}

PARAM_DEFAULTS = {
    "hh_base": 3.35, "hh_season_amp": 0.62, "hh_phase": 0.35, "hh_mean_reversion": 0.10, "hh_vol": 0.16,
    "ttf_base_eur_mwh": 42.0, "ttf_season_amp_eur_mwh": 6.5, "ttf_phase": 0.30, "ttf_mean_reversion": 0.12, "ttf_vol": 0.14,
    "fx_base": 1.09, "fx_vol": 0.015,
    "jkm_basis": 1.45, "jkm_asia_season": 0.85, "jkm_basis_vol": 0.42,
    "nbp_basis": 0.24, "wim_discount": 0.72, "nwe_regas_fee": 0.42, "swe_basis": 0.18,
    "terminal_basis_median": 0.09, "terminal_tariff_median": 0.14, "fuel_share": 0.09,
    "liquefaction_fee": 2.50, "loading_cost": 0.12, "regas_cost": 0.38, "feed_factor": 1.09,
    "oil_base": 76.0, "oil_season_amp": 2.4, "oil_vol": 0.18, "brent_slope": 0.125, "brent_constant": 1.15,
    "wti_brent_premium": 3.6, "charter_base": 62000.0, "charter_vol": 0.22, "fuel_price_base": 610.0, "fuel_vol": 0.18,
    "boil_off_rate": 0.00085, "boil_vol": 0.18, "demand_disruption_vol": 0.08,
    "regional_demand_atlantic": 7.2, "regional_demand_pacific": 10.5,
}

CALCULATION_LINEAGE = {
    "hh_forward": {"observed_quotes": ["hh_forward"], "modeled_inputs": ["hh_season_amp", "hh_phase", "hh_mean_reversion", "hh_vol"]},
    "terminal_feedgas": {"observed_quotes": ["hh_forward"], "modeled_inputs": ["terminal_basis_median", "terminal_tariff_median", "fuel_share"]},
    "usgc_fob": {"observed_quotes": ["hh_forward"], "modeled_inputs": ["feed_factor", "liquefaction_fee", "loading_cost"]},
    "atlantic_fob": {"observed_quotes": ["hh_forward"], "modeled_inputs": ["atlantic_facility_costs", "regional_demand_atlantic", "demand_disruption_vol"]},
    "pacific_fob": {"observed_quotes": ["hh_forward"], "modeled_inputs": ["pacific_facility_costs", "regional_demand_pacific", "demand_disruption_vol"]},
    "spark30s_atlantic_freight": {"observed_quotes": [], "modeled_inputs": ["charter_base", "charter_vol", "fuel_price_base", "fuel_vol", "boil_off_rate", "atlantic_route"]},
    "spark25s_pacific_freight": {"observed_quotes": [], "modeled_inputs": ["charter_base", "charter_vol", "fuel_price_base", "fuel_vol", "boil_off_rate", "pacific_route"]},
    "usgc_ttf_netback": {"observed_quotes": ["ttf_forward", "fx_eurusd"], "modeled_inputs": ["charter_base", "fuel_price_base", "boil_off_rate", "regas_cost", "loading_cost"]},
    "usgc_jkm_netback": {"observed_quotes": ["jkm_forward"], "modeled_inputs": ["jkm_basis", "pacific_route", "charter_base", "regas_cost", "loading_cost"]},
    "panama_cape_spread": {"observed_quotes": [], "modeled_inputs": ["panama_route", "cape_route", "charter_base", "fuel_price_base"]},
    "jkm_forward": {"observed_quotes": ["ttf_forward", "fx_eurusd"], "modeled_inputs": ["jkm_basis", "jkm_asia_season", "jkm_basis_vol"]},
    "ttf_forward": {"observed_quotes": ["ttf_forward", "fx_eurusd"], "modeled_inputs": ["ttf_season_amp_eur_mwh", "ttf_phase", "ttf_mean_reversion", "ttf_vol", "fx_vol"]},
    "nwe_des": {"observed_quotes": ["ttf_forward", "fx_eurusd"], "modeled_inputs": ["nwe_regas_fee"]},
    "swe_des": {"observed_quotes": ["ttf_forward", "fx_eurusd"], "modeled_inputs": ["swe_basis"]},
    "nbp_forward": {"observed_quotes": ["ttf_forward", "fx_eurusd"], "modeled_inputs": ["nbp_basis"]},
    "wim_forward": {"observed_quotes": ["ttf_forward", "fx_eurusd"], "modeled_inputs": ["jkm_basis", "wim_discount"]},
    "jkm_ttf_spread": {"observed_quotes": ["ttf_forward", "fx_eurusd"], "modeled_inputs": ["jkm_basis", "pacific_freight", "basis_shock"]},
    "winter_summer_spread": {"observed_quotes": ["hh_forward", "ttf_forward", "fx_eurusd"], "modeled_inputs": ["seasonal_amplitudes", "basis_shock"]},
    "m1_m2_calendar_spread": {"observed_quotes": ["hh_forward", "ttf_forward", "fx_eurusd"], "modeled_inputs": ["curve_mean_reversion", "basis_shock"]},
    "brent_linked_parity": {"observed_quotes": ["oil"], "modeled_inputs": ["wti_brent_premium", "brent_slope", "brent_constant", "oil_season_amp", "oil_vol"]},
}

CALCULATIONS = [
    ("hh_forward", "Henry Hub forward curve", "USD/MMBtu"),
    ("terminal_feedgas", "Terminal-delivered feedgas", "USD/MMBtu"),
    ("usgc_fob", "US Gulf Coast FOB", "USD/MMBtu"),
    ("atlantic_fob", "Atlantic Basin marginal FOB", "USD/MMBtu"),
    ("pacific_fob", "Pacific Basin marginal FOB", "USD/MMBtu"),
    ("spark30s_atlantic_freight", "Spark30S Atlantic freight", "USD/MMBtu"),
    ("spark25s_pacific_freight", "Spark25S Pacific freight", "USD/MMBtu"),
    ("usgc_ttf_netback", "USGC-to-TTF netback", "USD/MMBtu"),
    ("usgc_jkm_netback", "USGC-to-JKM netback", "USD/MMBtu"),
    ("panama_cape_spread", "Panama vs Cape diversion spread", "USD/MMBtu"),
    ("jkm_forward", "JKM forward curve", "USD/MMBtu"),
    ("ttf_forward", "TTF forward curve", "USD/MMBtu"),
    ("nwe_des", "Northwest Europe DES", "USD/MMBtu"),
    ("swe_des", "Southwest Europe DES", "USD/MMBtu"),
    ("nbp_forward", "NBP forward curve", "USD/MMBtu"),
    ("wim_forward", "West India Marker", "USD/MMBtu"),
    ("jkm_ttf_spread", "JKM-TTF spread", "USD/MMBtu"),
    ("winter_summer_spread", "Winter-summer spread", "USD/MMBtu"),
    ("m1_m2_calendar_spread", "M1-M2 calendar spread", "USD/MMBtu"),
    ("brent_linked_parity", "Brent-linked LNG parity", "USD/MMBtu"),
]

TERMINALS = [
    ("Sabine Pass", 0.06, 0.13, 4.8), ("Corpus Christi", 0.05, 0.12, 5.4), ("Freeport", 0.08, 0.16, 3.8),
    ("Cameron", 0.07, 0.14, 3.2), ("Calcasieu Pass", 0.06, 0.15, 2.4), ("Plaquemines", 0.09, 0.18, 3.6),
    ("Elba Island", 0.14, 0.22, 1.4), ("Cove Point", 0.19, 0.27, 1.1),
]

ATLANTIC_FACILITIES = [
    ("USGC-Sabine", 6.05, 0.92, 3.2, 0.72, 0.08), ("USGC-Corpus", 6.14, 0.92, 3.6, 0.70, 0.09),
    ("USGC-Plaquemines", 6.32, 0.92, 2.4, 0.68, 0.11), ("Trinidad-Atlantic", 6.88, 0.34, 2.1, 0.74, 0.14),
    ("Egypt-Idku", 7.34, 0.28, 1.5, 0.80, 0.18), ("Nigeria-Bonny", 7.82, 0.22, 1.2, 0.77, 0.20),
    ("Angola-Soyo", 8.10, 0.20, 0.9, 0.78, 0.16), ("Norway-Melkoya", 8.72, 0.12, 0.8, 0.70, 0.10),
]

PACIFIC_FACILITIES = [
    ("Australia-QCLNG", 6.62, 0.38, 2.8, 0.76, 0.10), ("Australia-GLNG", 6.78, 0.36, 2.3, 0.75, 0.11),
    ("Australia-Wheatstone", 6.94, 0.34, 2.1, 0.74, 0.12), ("Australia-Gorgon", 7.08, 0.32, 3.0, 0.73, 0.09),
    ("Malaysia-Bintulu", 7.44, 0.26, 2.2, 0.78, 0.13), ("Indonesia-Bontang", 7.72, 0.24, 1.5, 0.79, 0.15),
    ("Papua NG", 8.04, 0.21, 1.2, 0.77, 0.17), ("Qatar-RasLaffan", 6.36, 0.18, 3.4, 0.72, 0.07),
]

ROUTES = {
    "atlantic": {"distance_nm": 5050.0, "speed_kn": 17.5, "port_days": 2.5, "canal_days": 0.0, "canal_toll": 0.0,
                 "port_charge": 0.22, "cargo_mmbtu": 3600000.0, "fuel_tons_day": 118.0, "mmbtu_ton": 52.0},
    "panama": {"distance_nm": 11350.0, "speed_kn": 17.0, "port_days": 3.0, "canal_days": 2.0, "canal_toll": 620000.0,
               "port_charge": 0.34, "cargo_mmbtu": 3600000.0, "fuel_tons_day": 132.0, "mmbtu_ton": 52.0},
    "cape": {"distance_nm": 15400.0, "speed_kn": 17.5, "port_days": 2.5, "canal_days": 0.0, "canal_toll": 0.0,
             "port_charge": 0.28, "cargo_mmbtu": 3600000.0, "fuel_tons_day": 126.0, "mmbtu_ton": 52.0},
}


def _month_sequence(cutoff: str | None, count: int = DELIVERY_COUNT) -> list[str]:
    if cutoff:
        y, m = int(cutoff[:4]), int(cutoff[5:7])
    else:
        y, m = 2026, 11
    out = []
    for _ in range(count):
        m += 1
        if m == 13:
            y, m = y + 1, 1
        out.append(f"{y:04d}-{m:02d}")
    return out


def _month_index(month: str) -> int:
    return int(month[5:7]) - 1


def _season(month: str, amp: float, phase: float) -> float:
    return amp * math.cos(2 * math.pi * (_month_index(month) - 1) / 12.0 + phase)


def _observed_map(points: list[dict]) -> dict[str, float]:
    return {p["delivery_month"]: float(p["value"]) for p in points or [] if p.get("delivery_month") and p.get("value") is not None}


def _quote_value(row: dict | None) -> float | None:
    if not row or row.get("value") is None:
        return None
    try:
        return float(row["value"])
    except (TypeError, ValueError):
        return None


def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _default_param_provenance(params: dict) -> dict:
    return {key: {"value": value, "source": "labelled_assumption", "reason": "no calibrated observation supplied for this parameter"}
            for key, value in params.items()}


def _load_params(cutoff: str | None) -> tuple[dict, dict]:
    params = dict(PARAM_DEFAULTS)
    default_meta = {"source": "defaults", "available_timestamp": None, "backtest": {}, "scenario_count": 0, "benchmark": {},
                    "parameter_provenance": _default_param_provenance(params)}
    if not CALIBRATION_FILE.exists():
        return params, default_meta
    try:
        doc = json.loads(CALIBRATION_FILE.read_text())
    except (OSError, ValueError):
        return params, default_meta
    available = doc.get("available_timestamp")
    if available and cutoff and available > cutoff:
        default_meta["source"] = "calibration after cutoff; defaults used"
        return params, default_meta
    params.update({k: float(v) for k, v in (doc.get("params") or {}).items() if k in params})
    provenance = doc.get("parameter_provenance") or {}
    detail = {key: provenance.get(key, {"value": value, "source": "calibration_artifact_unclassified",
                                        "reason": "calibration artifact has no per-parameter provenance for this value"})
              for key, value in params.items()}
    meta = {"source": "calibration", "available_timestamp": available, "backtest": doc.get("backtest", {}),
            "scenario_count": doc.get("scenario_count", 0), "benchmark": doc.get("benchmark", {}), "model_version": doc.get("model_version"),
            "parameter_provenance": detail}
    return params, meta


def _quote_eligibility(row: dict | None, role: str, cutoff: str | None) -> dict:
    rule = FRESHNESS_RULES[role]
    record = {"quote_key": None, "role": role, "agent_id": None, "delivery_month": None, "value": None, "native_unit": None,
              "available_timestamp": None, "published_timestamp": None, "latest_target_timestamp": None, "target_timestamp": None,
              "retrieved_timestamp": None, "source_id": None, "series_id": None, "quality_status": None, "provenance": None,
              "raw_payload_hash": None, "age_days": None, "max_age_days": rule["max_age_days"], "freshness_basis": rule["basis"],
              "eligible": False, "reason": "no quote collected"}
    if not row:
        return record
    for key in ("agent_id", "delivery_month", "available_timestamp", "published_timestamp", "latest_target_timestamp", "target_timestamp",
                "retrieved_timestamp", "source_id", "series_id", "quality_status", "provenance", "raw_payload_hash", "quote_role"):
        record[key] = row.get(key)
    record["native_unit"] = row.get("unit") or row.get("native_unit")
    record["value"] = _quote_value(row)
    if record["value"] is None:
        record["reason"] = "quote has no value"
        return record
    available = _parse_ts(record["available_timestamp"])
    cutoff_dt = _parse_ts(cutoff)
    if available is None:
        record["reason"] = "quote has no usable available_timestamp"
        return record
    if cutoff_dt is None:
        record["reason"] = "cutoff is not a usable timestamp"
        return record
    if available > cutoff_dt:
        record["reason"] = "quote was not available at the cutoff"
        return record
    age_source = None
    for key in ("published_timestamp", "latest_target_timestamp", "target_timestamp", "date"):
        candidate = _parse_ts(row.get(key))
        if candidate is not None:
            age_source, stamp = key, candidate
            break
    if age_source is None:
        record["reason"] = "quote has no published, latest_target, target or date timestamp for freshness"
        return record
    age = (cutoff_dt - stamp).total_seconds() / 86400.0
    record["age_days"] = round(age, 4)
    record["freshness_timestamp_source"] = age_source
    if age < 0:
        record["reason"] = "quote timestamp is after the cutoff"
        return record
    if age > float(rule["max_age_days"]):
        record["reason"] = f"last trade {age:.1f} days before the cutoff (limit {rule['max_age_days']:g})"
        return record
    record["eligible"] = True
    record["reason"] = ""
    return record


def _input_eligibility(hh_points, ttf_by_month, fx_row, oil_row, cutoff, months) -> dict:
    records, hh_obs, ttf_obs = [], {}, {}
    fx, oil = None, None
    for point in hh_points or []:
        month = point.get("delivery_month")
        record = _quote_eligibility(point, "hh_forward", cutoff)
        record["quote_key"] = f"hh_forward:{month}" if month else "hh_forward:unknown"
        if month not in months:
            record["eligible"] = False
            record["reason"] = "delivery month outside the 24-month forecast window"
        records.append(record)
        if record["eligible"]:
            hh_obs[month] = record["value"]
    for month, row in (ttf_by_month or {}).items():
        record = _quote_eligibility(row, "ttf_forward", cutoff)
        record["quote_key"] = f"ttf_forward:{month}"
        record["delivery_month"] = month
        if month not in months:
            record["eligible"] = False
            record["reason"] = "delivery month outside the 24-month forecast window"
        records.append(record)
        if record["eligible"]:
            ttf_obs[month] = record["value"]
    fx_record = _quote_eligibility(fx_row, "fx_eurusd", cutoff)
    fx_record["quote_key"] = "fx_eurusd"
    records.append(fx_record)
    if fx_record["eligible"]:
        fx = fx_record["value"]
    oil_record = _quote_eligibility(oil_row, "oil", cutoff)
    oil_record["quote_key"] = "oil"
    records.append(oil_record)
    if oil_record["eligible"]:
        oil = oil_record["value"]
    accepted = [r["quote_key"] for r in records if r["eligible"]]
    rejected = [{"quote_key": r["quote_key"], "agent_id": r["agent_id"], "reason": r["reason"],
                 "available_timestamp": r["available_timestamp"], "published_timestamp": r["published_timestamp"]}
                for r in records if not r["eligible"]]
    return {"hh_observed": hh_obs, "ttf_observed": ttf_obs, "fx": fx, "oil": oil, "records": records,
            "eligibility": {"freshness_rules": FRESHNESS_RULES, "quotes": records, "accepted": accepted, "rejected": rejected,
                            "accepted_count": len(accepted), "rejected_count": len(rejected),
                            "hh_anchors": sorted(hh_obs), "ttf_anchors": sorted(ttf_obs),
                            "fx_eligible": fx is not None, "oil_eligible": oil is not None}}


def _extend_curve(months: list[str], observed: dict[str, float], base: float, amp: float, phase: float, reversion: float) -> np.ndarray:
    out = np.empty(len(months), dtype=float)
    previous = None
    for i, month in enumerate(months):
        anchor = observed.get(month)
        if anchor is not None:
            value = anchor
        else:
            target = base + _season(month, amp, phase)
            value = target if previous is None else previous + reversion * (target - previous)
            if i > 11 and anchor is None:
                value = 0.65 * target + 0.35 * value
        out[i] = value
        previous = value
    return out


def _marginal_stack(hh: np.ndarray, params: dict, facilities: list[tuple], demand: float, outage: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    names = [f[0] for f in facilities]
    cost0 = np.array([f[1] for f in facilities], dtype=float)
    sensitivity = np.array([f[2] for f in facilities], dtype=float)
    capacity = np.array([f[3] for f in facilities], dtype=float)
    utilization = np.array([f[4] for f in facilities], dtype=float)
    outage_sens = np.array([f[5] for f in facilities], dtype=float)
    costs = cost0[None, None, :] + sensitivity[None, None, :] * (hh[:, :, None] - params["hh_base"])
    costs = costs + outage[:, :, None] * outage_sens[None, None, :]
    available = capacity[None, None, :] * (1.0 - utilization[None, None, :]) * np.clip(1.0 - outage[:, :, None] * outage_sens[None, None, :], 0.05, 1.0)
    order = np.argsort(costs, axis=2)
    sorted_cost = np.take_along_axis(costs, order, axis=2)
    sorted_cap = np.take_along_axis(available, order, axis=2)
    cumulative = np.cumsum(sorted_cap, axis=2)
    demand_arr = np.full(hh.shape, demand, dtype=float)
    pos = np.clip((demand_arr[:, :, None] > cumulative).sum(axis=2), 0, len(names) - 1)
    idx = np.take_along_axis(order, pos[:, :, None], axis=2)[:, :, 0]
    marginal = np.take_along_axis(costs, idx[:, :, None], axis=2)[:, :, 0]
    return marginal, idx


def _voyage(route: dict, charter: np.ndarray, fuel_price: np.ndarray, boil: np.ndarray, dest_curve: np.ndarray, params: dict, offset_months: int = 0) -> dict:
    cfg = ROUTES[route] if isinstance(route, str) else route
    days = cfg["distance_nm"] / (cfg["speed_kn"] * 24.0) + cfg["port_days"] + cfg["canal_days"]
    boil_fraction = 1.0 - np.power(1.0 - boil, days)
    fuel_energy = cfg["fuel_tons_day"] * days * cfg["mmbtu_ton"]
    delivered = np.clip(cfg["cargo_mmbtu"] * (1.0 - boil_fraction) - fuel_energy, 1.0, None)
    charter_cost = charter * days
    fuel_cost = cfg["fuel_tons_day"] * days * fuel_price
    total_cost = charter_cost + fuel_cost + cfg["canal_toll"] + cfg["port_charge"] * cfg["cargo_mmbtu"]
    freight = total_cost / delivered
    arrival = np.clip(np.arange(dest_curve.shape[1])[None, :] + int(math.ceil(days / 30.0)) + offset_months, 0, dest_curve.shape[1] - 1)
    dest_price = np.take_along_axis(dest_curve, np.broadcast_to(arrival, dest_curve.shape), axis=1)
    netback = (dest_price * delivered - total_cost - params["regas_cost"] * delivered - params["loading_cost"] * cfg["cargo_mmbtu"]) / cfg["cargo_mmbtu"]
    return {"freight": freight, "netback": netback, "days": float(days), "delivered_fraction": float(np.mean(delivered / cfg["cargo_mmbtu"])),
            "arrival_offset": int(math.ceil(days / 30.0)), "total_cost": float(np.mean(total_cost))}


def simulate(params: dict, months: list[str], hh_observed: dict[str, float], ttf_observed: dict[str, float], fx_value: float | None,
             oil_value: float | None, n: int, seed: int = 20261120, backend: str = "cpu", input_context: dict | None = None) -> dict:
    if backend == "gpu":
        return _simulate_gpu(params, months, hh_observed, ttf_observed, fx_value, oil_value, n, seed, input_context)
    context = input_context or {}
    rng = np.random.default_rng(seed)
    n = max(1, int(n))
    shape = (n, len(months))
    common = rng.normal(size=shape)
    hh_shock = 0.65 * common + 0.76 * rng.normal(size=shape)
    ttf_shock = 0.70 * common + 0.71 * rng.normal(size=shape)
    basis_shock = rng.normal(size=shape)
    freight_shock = rng.normal(size=shape)
    fx_shock = rng.normal(size=shape)
    outage = np.abs(rng.normal(size=shape)) * params["demand_disruption_vol"]

    hh = _extend_curve(months, hh_observed, params["hh_base"], params["hh_season_amp"], params["hh_phase"], params["hh_mean_reversion"])
    ttf_eur = _extend_curve(months, ttf_observed, params["ttf_base_eur_mwh"], params["ttf_season_amp_eur_mwh"], params["ttf_phase"], params["ttf_mean_reversion"])
    fx = params["fx_base"] if fx_value is None else fx_value
    oil_base = params["oil_base"] if oil_value is None else oil_value
    oil = _extend_curve(months, {}, oil_base, params["oil_season_amp"], 0.18, 0.08)

    hh_scen = hh[None, :] * np.exp(params["hh_vol"] * hh_shock)
    ttf_eur_scen = ttf_eur[None, :] * np.exp(params["ttf_vol"] * ttf_shock)
    fx_scen = fx * np.exp(params["fx_vol"] * fx_shock)
    ttf = ttf_eur_scen * fx_scen / MMBTU_PER_MWH
    for i, month in enumerate(months):
        if month in hh_observed:
            hh_scen[:, i] = hh_observed[month]
        if month in ttf_observed:
            ttf_eur_scen[:, i] = ttf_observed[month]
            ttf[:, i] = ttf_observed[month] * fx_scen[:, i] / MMBTU_PER_MWH

    jkm = ttf + params["jkm_basis"] + params["jkm_asia_season"] * np.array([1.0 if _winter_month(m) else 0.0 for m in months])[None, :] + params["jkm_basis_vol"] * basis_shock
    nbp = ttf + params["nbp_basis"] + 0.08 * basis_shock
    wim = jkm - params["wim_discount"] - 0.18 * basis_shock
    nwe = ttf + params["nwe_regas_fee"] + 0.05 * basis_shock
    swe = ttf + params["swe_basis"] - 0.11 * basis_shock

    terminal_cost = hh_scen + params["terminal_basis_median"] + params["terminal_tariff_median"] + params["fuel_share"] * hh_scen
    usgc_fob = terminal_cost * params["feed_factor"] + params["liquefaction_fee"] + params["loading_cost"]
    atlantic_fob, atlantic_idx = _marginal_stack(hh_scen, params, ATLANTIC_FACILITIES, params["regional_demand_atlantic"], outage)
    pacific_fob, pacific_idx = _marginal_stack(hh_scen, params, PACIFIC_FACILITIES, params["regional_demand_pacific"], outage)

    charter = params["charter_base"] * np.exp(params["charter_vol"] * freight_shock)
    fuel_price = params["fuel_price_base"] * np.exp(params["fuel_vol"] * freight_shock)
    boil = params["boil_off_rate"] * np.exp(params["boil_vol"] * freight_shock)
    atlantic = _voyage("atlantic", charter, fuel_price, boil, ttf, params)
    panama = _voyage("panama", charter, fuel_price, boil, jkm, params)
    cape = _voyage("cape", charter, fuel_price, boil, jkm, params)
    pacific = panama if np.mean(panama["netback"]) >= np.mean(cape["netback"]) else cape
    diversion = panama["netback"] - cape["netback"]
    ttf_netback = atlantic["netback"]
    jkm_netback = pacific["netback"]
    jkm_ttf = jkm - ttf - 0.55 * pacific["freight"] - 0.18 * np.abs(basis_shock)

    oil_scen = oil[None, :] * np.exp(params["oil_vol"] * common)
    for i, month in enumerate(months):
        if oil_value is not None and i == 0:
            oil_scen[:, i] = oil_value
    brent = oil_scen + params["wti_brent_premium"]
    brent_parity = brent * params["brent_slope"] + params["brent_constant"]

    curves = {"hh_forward": hh_scen, "ttf_forward": ttf, "jkm_forward": jkm, "nbp_forward": nbp, "wim_forward": wim,
              "nwe_des": nwe, "swe_des": swe, "brent_linked_parity": brent_parity}
    winter_summer = _winter_summer(curves, months)
    calendar = _calendar_spread(curves)
    all_arrays = {
        "hh_forward": hh_scen, "terminal_feedgas": terminal_cost, "usgc_fob": usgc_fob, "atlantic_fob": atlantic_fob, "pacific_fob": pacific_fob,
        "spark30s_atlantic_freight": atlantic["freight"], "spark25s_pacific_freight": pacific["freight"],
        "usgc_ttf_netback": ttf_netback, "usgc_jkm_netback": jkm_netback, "panama_cape_spread": diversion,
        "jkm_forward": jkm, "ttf_forward": ttf, "nwe_des": nwe, "swe_des": swe, "nbp_forward": nbp, "wim_forward": wim,
        "jkm_ttf_spread": jkm_ttf, "winter_summer_spread": winter_summer, "m1_m2_calendar_spread": calendar,
        "brent_linked_parity": brent_parity,
    }
    diagnostics = {
        "atlantic_marginal_facility": _mode_name([f[0] for f in ATLANTIC_FACILITIES], atlantic_idx),
        "pacific_marginal_facility": _mode_name([f[0] for f in PACIFIC_FACILITIES], pacific_idx),
        "pacific_route": "Panama" if pacific is panama else "Cape",
        "arrival_offset_days": {"atlantic": atlantic["days"], "panama": panama["days"], "cape": cape["days"]},
        "arrival_offset_months": {"atlantic": atlantic["arrival_offset"], "panama": panama["arrival_offset"], "cape": cape["arrival_offset"]},
        "delivered_fraction": {"atlantic": atlantic["delivered_fraction"], "panama": panama["delivered_fraction"], "cape": cape["delivered_fraction"]},
        "voyage_cost_usd": {"atlantic": atlantic["total_cost"], "panama": panama["total_cost"], "cape": cape["total_cost"]},
        "scenario_count": n, "backend": "cpu", "seed": int(seed),
        "ttf_conversion": {"formula": "TTF(EUR/MWh) * EURUSD / MMBTU_PER_MWH", "native_unit": "EUR/MWh",
                           "mmbtu_per_mwh": MMBTU_PER_MWH, "fx_source": context.get("fx_source", "calibrated_assumption"),
                           "ttf_anchor_source": context.get("ttf_anchor_source", "calibrated_assumption")},
        "oil_source": context.get("oil_source", "calibrated_assumption"),
    }
    return {"arrays": all_arrays, "curves": curves, "diagnostics": diagnostics}


def _mode_name(names: list[str], idx: np.ndarray) -> str:
    vals, counts = np.unique(idx, return_counts=True)
    return names[int(vals[int(np.argmax(counts))])]


def _winter_month(month: str) -> bool:
    return int(month[5:7]) in (11, 12, 1, 2, 3)


def _rolling_seasonal_spread(curve: np.ndarray, months: list[str]) -> np.ndarray:
    out = np.zeros_like(curve, dtype=float)
    for i in range(curve.shape[1]):
        winter, summer = [], []
        for j in range(i, min(curve.shape[1], i + 12)):
            (winter if _winter_month(months[j]) else summer).append(curve[:, j])
        if winter and summer:
            out[:, i] = np.mean(winter, axis=0) - np.mean(summer, axis=0)
    return out


def _winter_summer(curves: dict, months: list[str]) -> np.ndarray:
    parts = [_rolling_seasonal_spread(curves[k], months) for k in ("hh_forward", "ttf_forward", "jkm_forward", "nbp_forward")]
    return np.mean(np.stack(parts, axis=0), axis=0)


def _calendar_spread(curves: dict) -> np.ndarray:
    parts = []
    for key in ("hh_forward", "ttf_forward", "jkm_forward", "nbp_forward"):
        c = curves[key]
        spread = c[:, :-1] - c[:, 1:]
        parts.append(np.concatenate([spread, spread[:, -1:]], axis=1))
    return np.mean(np.stack(parts, axis=0), axis=0)


def _torch_curve(months: list[str], observed: dict[str, float], base: float, amp: float, phase: float, reversion: float, device) -> "object":
    import torch
    return torch.as_tensor(_extend_curve(months, observed, base, amp, phase, reversion), dtype=torch.float32, device=device)


def _torch_marginal_stack(hh: "object", params: dict, facilities: list[tuple], demand: float, outage: "object", device) -> tuple["object", "object"]:
    import torch
    names = [f[0] for f in facilities]
    cost0 = torch.tensor([f[1] for f in facilities], dtype=torch.float32, device=device)
    sensitivity = torch.tensor([f[2] for f in facilities], dtype=torch.float32, device=device)
    capacity = torch.tensor([f[3] for f in facilities], dtype=torch.float32, device=device)
    utilization = torch.tensor([f[4] for f in facilities], dtype=torch.float32, device=device)
    outage_sens = torch.tensor([f[5] for f in facilities], dtype=torch.float32, device=device)
    costs = cost0 + sensitivity * (hh[:, :, None] - float(params["hh_base"]))
    costs = costs + outage[:, :, None] * outage_sens
    available = capacity * (1.0 - utilization) * torch.clamp(1.0 - outage[:, :, None] * outage_sens, min=0.05)
    order = torch.argsort(costs, dim=2)
    sorted_cap = torch.gather(available, 2, order)
    cumulative = torch.cumsum(sorted_cap, dim=2)
    pos = torch.clamp((float(demand) > cumulative).sum(dim=2).long(), max=len(names) - 1)
    idx = torch.gather(order, 2, pos[:, :, None])[:, :, 0]
    marginal = torch.gather(costs, 2, idx[:, :, None])[:, :, 0]
    return marginal, idx


def _torch_voyage(route: dict, charter: "object", fuel_price: "object", boil: "object", dest_curve: "object", params: dict, device, offset_months: int = 0) -> dict:
    import torch
    cfg = ROUTES[route] if isinstance(route, str) else route
    days = cfg["distance_nm"] / (cfg["speed_kn"] * 24.0) + cfg["port_days"] + cfg["canal_days"]
    boil_fraction = 1.0 - torch.pow(1.0 - boil, days)
    fuel_energy = cfg["fuel_tons_day"] * days * cfg["mmbtu_ton"]
    delivered = torch.clamp(cfg["cargo_mmbtu"] * (1.0 - boil_fraction) - fuel_energy, min=1.0)
    charter_cost = charter * days
    fuel_cost = cfg["fuel_tons_day"] * days * fuel_price
    total_cost = charter_cost + fuel_cost + cfg["canal_toll"] + cfg["port_charge"] * cfg["cargo_mmbtu"]
    freight = total_cost / delivered
    arrival = torch.arange(dest_curve.shape[1], device=device)[None, :] + int(math.ceil(days / 30.0)) + offset_months
    arrival = arrival.clamp(max=dest_curve.shape[1] - 1).expand(charter.shape[0], -1)
    dest_price = torch.gather(dest_curve, 1, arrival)
    netback = (dest_price * delivered - total_cost - float(params["regas_cost"]) * delivered - float(params["loading_cost"]) * cfg["cargo_mmbtu"]) / cfg["cargo_mmbtu"]
    return {"freight": freight, "netback": netback, "days": float(days), "delivered_fraction": float(torch.mean(delivered / cfg["cargo_mmbtu"]).item()),
            "arrival_offset": int(math.ceil(days / 30.0)), "total_cost": float(torch.mean(total_cost).item())}


def _simulate_gpu(params: dict, months: list[str], hh_observed: dict[str, float], ttf_observed: dict[str, float], fx_value: float | None,
                  oil_value: float | None, n: int, seed: int, input_context: dict | None = None) -> dict:
    context = input_context or {}
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("GPU backend requires the precompiled PyTorch wheel") from exc
    if not torch.cuda.is_available():
        raise RuntimeError("GPU backend requested but CUDA is unavailable")
    device = torch.device("cuda:0")
    generator = torch.Generator(device=device).manual_seed(int(seed))
    n = max(1, int(n))
    shape = (n, len(months))
    common = torch.randn(shape, device=device, generator=generator, dtype=torch.float32)
    hh_shock = 0.65 * common + 0.76 * torch.randn(shape, device=device, generator=generator, dtype=torch.float32)
    ttf_shock = 0.70 * common + 0.71 * torch.randn(shape, device=device, generator=generator, dtype=torch.float32)
    basis_shock = torch.randn(shape, device=device, generator=generator, dtype=torch.float32)
    freight_shock = torch.randn(shape, device=device, generator=generator, dtype=torch.float32)
    fx_shock = torch.randn(shape, device=device, generator=generator, dtype=torch.float32)
    outage = torch.abs(torch.randn(shape, device=device, generator=generator, dtype=torch.float32)) * float(params["demand_disruption_vol"])

    hh = _torch_curve(months, hh_observed, params["hh_base"], params["hh_season_amp"], params["hh_phase"], params["hh_mean_reversion"], device)
    ttf_eur = _torch_curve(months, ttf_observed, params["ttf_base_eur_mwh"], params["ttf_season_amp_eur_mwh"], params["ttf_phase"], params["ttf_mean_reversion"], device)
    fx = float(params["fx_base"] if fx_value is None else fx_value)
    oil_base = float(params["oil_base"] if oil_value is None else oil_value)
    oil = _torch_curve(months, {}, oil_base, params["oil_season_amp"], 0.18, 0.08, device)

    hh_scen = hh[None, :] * torch.exp(float(params["hh_vol"]) * hh_shock)
    ttf_eur_scen = ttf_eur[None, :] * torch.exp(float(params["ttf_vol"]) * ttf_shock)
    fx_scen = fx * torch.exp(float(params["fx_vol"]) * fx_shock)
    ttf = ttf_eur_scen * fx_scen / MMBTU_PER_MWH
    for i, month in enumerate(months):
        if month in hh_observed:
            hh_scen[:, i] = float(hh_observed[month])
        if month in ttf_observed:
            ttf_eur_scen[:, i] = float(ttf_observed[month])
            ttf[:, i] = float(ttf_observed[month]) * fx_scen[:, i] / MMBTU_PER_MWH

    winter = torch.tensor([1.0 if _winter_month(m) else 0.0 for m in months], dtype=torch.float32, device=device)[None, :]
    jkm = ttf + float(params["jkm_basis"]) + float(params["jkm_asia_season"]) * winter + float(params["jkm_basis_vol"]) * basis_shock
    nbp = ttf + float(params["nbp_basis"]) + 0.08 * basis_shock
    wim = jkm - float(params["wim_discount"]) - 0.18 * basis_shock
    nwe = ttf + float(params["nwe_regas_fee"]) + 0.05 * basis_shock
    swe = ttf + float(params["swe_basis"]) - 0.11 * basis_shock

    terminal_cost = hh_scen + float(params["terminal_basis_median"]) + float(params["terminal_tariff_median"]) + float(params["fuel_share"]) * hh_scen
    usgc_fob = terminal_cost * float(params["feed_factor"]) + float(params["liquefaction_fee"]) + float(params["loading_cost"])
    atlantic_fob, atlantic_idx = _torch_marginal_stack(hh_scen, params, ATLANTIC_FACILITIES, float(params["regional_demand_atlantic"]), outage, device)
    pacific_fob, pacific_idx = _torch_marginal_stack(hh_scen, params, PACIFIC_FACILITIES, float(params["regional_demand_pacific"]), outage, device)

    charter = float(params["charter_base"]) * torch.exp(float(params["charter_vol"]) * freight_shock)
    fuel_price = float(params["fuel_price_base"]) * torch.exp(float(params["fuel_vol"]) * freight_shock)
    boil = float(params["boil_off_rate"]) * torch.exp(float(params["boil_vol"]) * freight_shock)
    atlantic = _torch_voyage("atlantic", charter, fuel_price, boil, ttf, params, device)
    panama = _torch_voyage("panama", charter, fuel_price, boil, jkm, params, device)
    cape = _torch_voyage("cape", charter, fuel_price, boil, jkm, params, device)
    pacific = panama if float(torch.mean(panama["netback"]).item()) >= float(torch.mean(cape["netback"]).item()) else cape
    diversion = panama["netback"] - cape["netback"]
    ttf_netback = atlantic["netback"]
    jkm_netback = pacific["netback"]
    jkm_ttf = jkm - ttf - 0.55 * pacific["freight"] - 0.18 * torch.abs(basis_shock)

    oil_scen = oil[None, :] * torch.exp(float(params["oil_vol"]) * common)
    for i, month in enumerate(months):
        if oil_value is not None and i == 0:
            oil_scen[:, i] = float(oil_value)
    brent = oil_scen + float(params["wti_brent_premium"])
    brent_parity = brent * float(params["brent_slope"]) + float(params["brent_constant"])

    curves_t = {"hh_forward": hh_scen, "ttf_forward": ttf, "jkm_forward": jkm, "nbp_forward": nbp, "wim_forward": wim,
                "nwe_des": nwe, "swe_des": swe, "brent_linked_parity": brent_parity}
    curves = {k: v.detach().cpu().numpy().astype(float) for k, v in curves_t.items()}
    winter_summer = _winter_summer(curves, months)
    calendar = _calendar_spread(curves)
    arrays_t = {
        "hh_forward": hh_scen, "terminal_feedgas": terminal_cost, "usgc_fob": usgc_fob, "atlantic_fob": atlantic_fob, "pacific_fob": pacific_fob,
        "spark30s_atlantic_freight": atlantic["freight"], "spark25s_pacific_freight": pacific["freight"],
        "usgc_ttf_netback": ttf_netback, "usgc_jkm_netback": jkm_netback, "panama_cape_spread": diversion,
        "jkm_forward": jkm, "ttf_forward": ttf, "nwe_des": nwe, "swe_des": swe, "nbp_forward": nbp, "wim_forward": wim,
        "jkm_ttf_spread": jkm_ttf, "winter_summer_spread": torch.as_tensor(winter_summer, device=device), "m1_m2_calendar_spread": torch.as_tensor(calendar, device=device),
        "brent_linked_parity": brent_parity,
    }
    all_arrays = {k: v.detach().cpu().numpy().astype(float) for k, v in arrays_t.items()}
    diagnostics = {
        "atlantic_marginal_facility": _mode_name([f[0] for f in ATLANTIC_FACILITIES], atlantic_idx.detach().cpu().numpy()),
        "pacific_marginal_facility": _mode_name([f[0] for f in PACIFIC_FACILITIES], pacific_idx.detach().cpu().numpy()),
        "pacific_route": "Panama" if pacific is panama else "Cape",
        "arrival_offset_days": {"atlantic": atlantic["days"], "panama": panama["days"], "cape": cape["days"]},
        "arrival_offset_months": {"atlantic": atlantic["arrival_offset"], "panama": panama["arrival_offset"], "cape": cape["arrival_offset"]},
        "delivered_fraction": {"atlantic": atlantic["delivered_fraction"], "panama": panama["delivered_fraction"], "cape": cape["delivered_fraction"]},
        "voyage_cost_usd": {"atlantic": atlantic["total_cost"], "panama": panama["total_cost"], "cape": cape["total_cost"]},
        "scenario_count": n, "backend": "cuda:0", "device_name": torch.cuda.get_device_name(0), "seed": int(seed),
        "ttf_conversion": {"formula": "TTF(EUR/MWh) * EURUSD / MMBTU_PER_MWH", "native_unit": "EUR/MWh",
                           "mmbtu_per_mwh": MMBTU_PER_MWH, "fx_source": context.get("fx_source", "calibrated_assumption"),
                           "ttf_anchor_source": context.get("ttf_anchor_source", "calibrated_assumption")},
        "oil_source": context.get("oil_source", "calibrated_assumption"),
    }
    return {"arrays": all_arrays, "curves": curves, "diagnostics": diagnostics}


POINT_PROVENANCE = {
    "modeled": PROVENANCE,
    "observed_quote": "measured_quote_anchor_with_scenario_band",
    "converted_observed": "converted_observed_quote_with_modeled_fx_and_scenario_band",
    "observed_proxy": "observed_quote_with_labelled_conversion_and_scenario_band",
}


def _summarize(array: np.ndarray, months: list[str], label: str, unit: str, observed: dict[str, float] | None = None,
               observed_statuses: dict[str, str] | None = None, native_values: dict[str, float] | None = None,
               native_units: dict[str, str] | None = None, conversion: dict | None = None, lineage: dict | None = None,
               item_status: str = "modeled", item_provenance: str = PROVENANCE) -> dict:
    low, p25, base, p75, high, ci_low, ci_high = np.quantile(array, [0.10, 0.25, 0.50, 0.75, 0.90, 0.025, 0.975], axis=0)
    mean = np.mean(array, axis=0)
    std = np.std(array, axis=0)
    observed, observed_statuses = observed or {}, observed_statuses or {}
    native_values, native_units, lineage = native_values or {}, native_units or {}, lineage or {}
    values = []
    for i, month in enumerate(months):
        status = observed_statuses.get(month, "modeled")
        values.append({
            "contract": f"M{i + 1}", "delivery_month": month, "base": round(float(base[i]), 6), "low": round(float(low[i]), 6),
            "high": round(float(high[i]), 6), "p25": round(float(p25[i]), 6), "p75": round(float(p75[i]), 6),
            "ci_low": round(float(ci_low[i]), 6), "ci_high": round(float(ci_high[i]), 6), "mean": round(float(mean[i]), 6),
            "std": round(float(std[i]), 6), "observed": observed.get(month), "observed_status": status,
            "observed_native_value": native_values.get(month), "observed_native_unit": native_units.get(month),
            "observed_conversion": conversion if status != "modeled" else None, "provenance": POINT_PROVENANCE[status],
            "lineage": lineage.get(month, []), "model_confidence": round(float(1.0 / (1.0 + std[i])), 4),
        })
    return {"id": label, "unit": unit, "status": item_status, "provenance": item_provenance, "values": values}


def build(hh_points: list[dict] | None = None, ttf_by_month: dict | None = None, fx_row: dict | None = None, oil_row: dict | None = None,
          cutoff: str | None = None, params_doc: dict | None = None, scenarios: int | None = None, seed: int = 20261120,
          backend: str = "cpu") -> dict:
    months = _month_sequence(cutoff)
    params, calibration = _load_params(cutoff)
    if params_doc and isinstance(params_doc.get("params"), dict):
        doc_params = params_doc["params"]
        for key, aliases in (("feed_factor", ("feed_factor", "k_hh_multiplier")), ("liquefaction_fee", ("liquefaction_fee", "liquefaction_usd_mmbtu")),
                             ("regas_cost", ("regas_cost",))):
            for alias in aliases:
                candidate = doc_params.get(alias)
                if isinstance(candidate, dict) and candidate.get("value") is not None:
                    params[key] = float(candidate["value"])
                    calibration.setdefault("parameter_provenance", {})[key] = {
                        "value": params[key], "source": "knowledge_library_parameter_doc", "reason": "validated parameter document override"}
                    break
    eligible = _input_eligibility(hh_points, ttf_by_month, fx_row, oil_row, cutoff, months)
    hh_obs, ttf_obs = eligible["hh_observed"], eligible["ttf_observed"]
    fx, oil = eligible["fx"], eligible["oil"]
    fx_record = next((r for r in eligible["records"] if r["role"] == "fx_eurusd"), None)
    oil_record = next((r for r in eligible["records"] if r["role"] == "oil"), None)
    fx_source = "measured_quote" if fx is not None else "calibrated_assumption"
    ttf_source = "measured_eur_mwh_quote" if ttf_obs else "calibrated_assumption"
    oil_role = (oil_record or {}).get("quote_role") or ("brent" if (oil_record or {}).get("agent_id") == "Agent_Crude_Brent_Spot" else "wti_proxy")
    oil_source = "calibrated_assumption"
    if oil is not None:
        oil_source = "measured_brent_quote" if oil_role == "brent" else "measured_wti_quote_with_labelled_brent_premium"
    input_context = {"fx_source": fx_source, "ttf_anchor_source": ttf_source, "oil_source": oil_source}
    scenario_count = int(scenarios or os.environ.get("LNG_GLOBAL_SCENARIOS", 8192))
    result = simulate(params, months, hh_obs, ttf_obs, fx, oil, scenario_count, seed, backend, input_context)
    hh_lineage = {r["delivery_month"]: [r] for r in eligible["records"] if r["role"] == "hh_forward" and r["eligible"]}
    ttf_lineage = {r["delivery_month"]: [r] for r in eligible["records"] if r["role"] == "ttf_forward" and r["eligible"]}
    ttf_converted = {}
    for month, value in ttf_obs.items():
        if month in months:
            idx = months.index(month)
            ttf_converted[month] = round(float(np.median(result["arrays"]["ttf_forward"][:, idx])), 6)
    ttf_conversion = {"formula": "TTF(EUR/MWh) * EURUSD / MMBTU_PER_MWH", "native_unit": "EUR/MWh", "output_unit": "USD/MMBtu",
                      "mmbtu_per_mwh": MMBTU_PER_MWH, "ttf_quote_source": ttf_source, "fx_source": fx_source,
                      "fx_available_at_cutoff": fx is not None, "fx_native_value": fx,
                      "fx_lineage": fx_record if fx is not None else None,
                      "note": "Observed TTF months are anchored in EUR/MWh; the USD/MMBtu anchor includes simulated EUR/USD dispersion unless an observed FX quote was eligible."}
    oil_conversion = {"native_unit": "USD/bbl", "output_unit": "USD/MMBtu", "source": oil_source, "quote_role": oil_role,
                      "wti_brent_premium": params["wti_brent_premium"], "brent_slope": params["brent_slope"], "brent_constant": params["brent_constant"],
                      "note": "This is a labelled parity estimate, not an observed LNG price."}
    calculations = {}
    for key, label, unit in CALCULATIONS:
        observed, statuses, native_values, native_units, lineage, conversion = {}, {}, {}, {}, {}, None
        item_status, item_provenance = "modeled", PROVENANCE
        if key == "hh_forward":
            observed = dict(hh_obs)
            statuses = {month: "observed_quote" for month in hh_obs if month in months}
            native_values = dict(hh_obs)
            native_units = {month: "USD/MMBtu" for month in hh_obs}
            lineage = hh_lineage
            if statuses:
                item_status, item_provenance = "observed_anchored_and_modeled", "measured_quote_anchor_with_modeled_scenarios"
        elif key == "ttf_forward":
            observed = dict(ttf_converted)
            statuses = {month: "converted_observed" for month in ttf_obs if month in months}
            native_values = dict(ttf_obs)
            native_units = {month: "EUR/MWh" for month in ttf_obs}
            lineage = ttf_lineage
            conversion = ttf_conversion
            if statuses:
                item_status, item_provenance = "observed_converted_and_modeled", "converted_observed_quote_with_modeled_fx_and_scenarios"
        elif key == "brent_linked_parity" and oil is not None and months:
            statuses = {months[0]: "observed_proxy" if oil_role != "brent" else "observed_quote"}
            native_values = {months[0]: oil}
            native_units = {months[0]: "USD/bbl"}
            lineage = {months[0]: [oil_record]}
            conversion = oil_conversion
            item_status = "observed_proxy_and_modeled" if oil_role != "brent" else "observed_anchored_and_modeled"
            item_provenance = oil_source
        calculations[key] = _summarize(result["arrays"][key], months, label, unit, observed, statuses, native_values, native_units,
                                       conversion, lineage, item_status, item_provenance)
        calculations[key]["input_lineage"] = CALCULATION_LINEAGE[key]
    anchored = any(item["status"] != "modeled" for item in calculations.values())
    return {
        "model_version": MODEL_VERSION, "status": "observed_anchored_and_modeled" if anchored else "modeled",
        "provenance": "mixed_measured_and_modeled" if anchored else PROVENANCE, "unit": "USD/MMBtu",
        "generated_at": cutoff, "cutoff": cutoff, "delivery_months": months, "calculations": calculations,
        "assumptions": params, "calibration": calibration, "diagnostics": result["diagnostics"],
        "inputs": {"eligibility": eligible["eligibility"], "ttf_conversion": ttf_conversion, "oil_conversion": oil_conversion,
                   "parameter_provenance": calibration.get("parameter_provenance", {})},
        "note": "All 20 calculations are produced for M1-M24. Only quotes with an available timestamp at or before the cutoff and a series-specific freshness check can anchor a month; every other value is a labeled model estimate.",
    }
