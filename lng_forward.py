"""LNG forward cost curve derived from the Henry Hub futures curve, plus a TTF-based netback where a fresh quote exists. Pure functions, no I/O.

  FOB cost_m   = FEEDGAS_FACTOR * HH_m + LIQUEFACTION_FEE            (USD/MMBtu; HH_m is the Henry Hub futures price for delivery month m)
  TTF_usd_m    = TTF_m(EUR/MWh) * EURUSD / MMBTU_PER_MWH
  Netback_m    = TTF_usd_m - SHIPPING - REGAS                        (only when BOTH the TTF month and EURUSD quotes are fresh at the cutoff)
  Margin_m     = Netback_m - FOB cost_m

Nothing is invented: a month with no HH point has no value; a month with no fresh TTF or EUR/USD quote has no netback; JKM has no free futures source and is
reported as pending. Provenance is `extracted_estimate` (derived here from measured quotes plus the labelled assumptions in lng_config).
"""
from __future__ import annotations

from datetime import datetime

import lng_config as cfg

PROVENANCE = "extracted_estimate"
FORMULA = "FOB cost = FEEDGAS_FACTOR * Henry Hub futures + LIQUEFACTION_FEE"
NETBACK_FORMULA = "Netback = TTF(EUR/MWh) * EURUSD / MMBTU_PER_MWH - SHIPPING - REGAS"
JKM_NOTE = ("No free JKM futures source is reachable (checked 2026-11-17: Yahoo JKM=F returns no data, dated JKM contracts return 404), "
            "so JKM netback is pending a collector. Nothing is estimated in its place.")


def fob_cost(hh_usd_mmbtu: float) -> float:
    return cfg.FEEDGAS_FACTOR * hh_usd_mmbtu + cfg.LIQUEFACTION_FEE_USD_MMBTU


def ttf_usd_mmbtu(ttf_eur_mwh: float, eurusd: float) -> float:
    return ttf_eur_mwh * eurusd / cfg.MMBTU_PER_MWH


def netback(ttf_eur_mwh: float, eurusd: float) -> float:
    return ttf_usd_mmbtu(ttf_eur_mwh, eurusd) - cfg.SHIPPING_USD_MMBTU - cfg.REGAS_USD_MMBTU


def _age_days(ts: str | None, cutoff: str) -> float | None:
    if not ts:
        return None
    f = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))  # noqa: E731
    return (f(cutoff) - f(ts)).total_seconds() / 86400.0


def _fresh(row: dict | None, cutoff: str):
    """(usable, age_days, reason). A quote is usable only if it was available at the cutoff and its last trade is within MAX_QUOTE_AGE_DAYS."""
    if not row:
        return False, None, "no quote collected"
    if row.get("available_timestamp") and row["available_timestamp"] > cutoff:
        return False, None, "quote not yet available at the cutoff"
    age = _age_days(row.get("published_timestamp") or row.get("latest_target_timestamp"), cutoff)
    if age is None:
        return False, None, "quote has no timestamp"
    if age > cfg.MAX_QUOTE_AGE_DAYS:
        return False, age, f"last trade {age:.1f} days before the cutoff (limit {cfg.MAX_QUOTE_AGE_DAYS:g})"
    return True, age, ""


def _params(params_doc: dict | None) -> tuple[float, float, dict]:
    """Effective k (feed-gas factor) and L (liquefaction fee) plus a record of where each came from. A value from the knowledge library is used only if it is
    present in the (already validated, PIT-gated) params doc; otherwise the labelled default assumption in lng_config applies, with the reason."""
    pd = (params_doc or {}).get("params", {}) if params_doc else {}
    rej = (params_doc or {}).get("rejected_at_load", {}) if params_doc else {}
    why_missing = "lng_params.json not available at the cutoff" if not params_doc else "no verified library sentence stated an acceptable value"
    spec = {"k_hh_multiplier": (cfg.FEEDGAS_FACTOR, "x Henry Hub"), "liquefaction_usd_mmbtu": (cfg.LIQUEFACTION_FEE_USD_MMBTU, "USD/MMBtu")}
    out = {}
    for name, (default, unit) in spec.items():
        p = pd.get(name)
        if p and p.get("source") == "library":
            out[name] = dict(p)
        else:
            out[name] = {"value": default, "unit": unit, "source": "assumption", "reason": rej.get(name) or (p or {}).get("reason") or why_missing}
    return float(out["k_hh_multiplier"]["value"]), float(out["liquefaction_usd_mmbtu"]["value"]), out


def build(hh_points: list, ttf_by_month: dict, fx_row: dict | None, cutoff: str, params_doc: dict | None = None) -> dict:
    """hh_points: [{contract, delivery_month 'YYYY-MM', value, ...lineage}] (already PIT-eligible). ttf_by_month: {'YYYY-MM': latest-row dict with value/published/available}.
    Returns the payload block; `points` is empty and status `pending_collector` when there is no Henry Hub curve."""
    k_eff, l_eff, parameters = _params(params_doc)
    assumptions = {k: dict(v) for k, v in cfg.LABELS.items()}
    assumptions["feedgas_factor"].update(value=k_eff, source=parameters["k_hh_multiplier"]["source"])
    assumptions["liquefaction_fee"].update(value=l_eff, source=parameters["liquefaction_usd_mmbtu"]["source"])
    context = (params_doc or {}).get("context", []) if params_doc else []
    base = {"provenance": PROVENANCE, "unit": "USD/MMBtu", "formula": FORMULA, "netback_formula": NETBACK_FORMULA, "assumptions": assumptions,
            "parameters": parameters, "parameters_generated_at": (params_doc or {}).get("generated_at") if params_doc else None, "context": context}
    pts = [p for p in hh_points if p.get("value") is not None]
    if not pts:
        return {**base, "status": "pending_collector", "points": [], "missing": ["Henry Hub futures curve (Agent_HH_M1..M12)"], "as_of_date": None,
                "note": "No Henry Hub futures points are available at this cutoff, so no LNG cost is computed.",
                "netback": {"status": "pending_collector", "ttf": "no Henry Hub months to align to", "jkm": JKM_NOTE, "points_with_netback": 0}}
    fx_ok, fx_age, fx_why = _fresh(fx_row, cutoff)
    out, with_nb, reasons = [], 0, {}
    for p in pts:
        hh = float(p["value"])
        feed = k_eff * hh
        pt = {"contract": p["contract"], "delivery_month": p.get("delivery_month"), "hh_value": hh, "feedgas_cost": round(feed, 6),
              "liquefaction_fee": l_eff, "fob_cost": round(feed + l_eff, 6),
              "hh_series_id": p.get("series_id"), "hh_source_id": p.get("source_id"), "hh_quality_status": p.get("quality_status"),
              "hh_published_timestamp": p.get("published_timestamp"), "hh_available_timestamp": p.get("available_timestamp"), "hh_quote_date": p.get("date"),
              "hh_raw_payload_hash": p.get("raw_payload_hash"), "netback": None, "netback_note": None}
        ttf = ttf_by_month.get(p.get("delivery_month"))
        t_ok, t_age, t_why = _fresh(ttf, cutoff)
        if t_ok and fx_ok:
            usd = ttf_usd_mmbtu(float(ttf["value"]), float(fx_row["value"]))
            nb = usd - cfg.SHIPPING_USD_MMBTU - cfg.REGAS_USD_MMBTU
            pt["netback"] = {"value": round(nb, 6), "ttf_eur_mwh": float(ttf["value"]), "eurusd": float(fx_row["value"]), "ttf_usd_mmbtu": round(usd, 6),
                             "margin_vs_fob_cost": round(nb - pt["fob_cost"], 6), "ttf_series_id": ttf.get("series_id"), "ttf_published_timestamp": ttf.get("published_timestamp"),
                             "ttf_available_timestamp": ttf.get("available_timestamp"), "ttf_quality_status": ttf.get("quality_status"), "ttf_raw_payload_hash": ttf.get("raw_payload_hash"),
                             "fx_published_timestamp": fx_row.get("published_timestamp"), "fx_available_timestamp": fx_row.get("available_timestamp"),
                             "ttf_age_days": round(t_age, 2), "fx_age_days": round(fx_age, 2)}
            with_nb += 1
        else:
            pt["netback_note"] = "TTF: " + (t_why or "ok") + "; EUR/USD: " + (fx_why or "ok")
            reasons[pt["delivery_month"]] = pt["netback_note"]
        out.append(pt)
    dates = [p.get("date") for p in pts if p.get("date")]
    return {**base, "status": "estimate", "points": out, "missing": [], "as_of_date": max(dates) if dates else None,
            "note": "",
            "netback": {"status": "estimate" if with_nb else "pending_collector", "points_with_netback": with_nb, "of": len(out),
                        "ttf": (f"{with_nb} of {len(out)} months have a fresh TTF quote" if with_nb else "no fresh TTF quote at this cutoff"),
                        "fx": ("EUR/USD fresh" if fx_ok else "EUR/USD: " + fx_why), "jkm": JKM_NOTE, "formula": NETBACK_FORMULA, "reasons": reasons}}
