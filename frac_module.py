"""Module B: ethane frac spread and rejection, a SEPARATELY CALCULATED module (checklist B1-B4, AD2, AD3, M5).

Why separate (B1): ethane rejection changes the volume of dry natural gas (the user's source: a +0.5 to +1.5 Bcf/d swing) according to NGL processing
margins, not gas demand. B4: only the resulting NET DRY-GAS SUPPLY DELTA (Bcf/d) may leave this module for the forward pricing balance; raw NGL prices are
never an input to the gas price regression ("never double-count"). This module therefore returns the delta, and nothing price-shaped except the spread it explains.

  B2  Ethane_Value = (Mont Belvieu ethane, cents/gal / 100) / ETHANE_MMBTU_PER_GAL                        [USD/MMBtu]
      Break-even   = Gas_Hub_Price + T&F                                                                     [USD/MMBtu]
  B3  margin = Ethane_Value - break-even. margin >= 0: ethane is recovered, nothing is left in the gas stream (delta 0).
      margin <  0: rejection. fraction = min(-margin / FULL_REJECTION_DEFICIT, 1); delta_bcfd = fraction x swing, reported as low / central / high of the stated swing.

Labelled assumptions (kind `assumption`, none comes from market data; change them here only):
  TF_COST_USD_PER_GAL                 transport + fractionation, USD/gal. NO value was given in the requirement (AD3) and none exists in the repo.
  FULL_REJECTION_DEFICIT_USD_MMBTU    margin deficit at which all rejectable ethane is rejected; the user gave the swing, not the curve shape.
  RECOVERY_SWING_BCFD (0.5, 1.5)      the user's source text: "+0.5 to +1.5 Bcf/d swing".
Inputs that are NOT available (reported in `blocked`, never replaced by a guess): the ethane price (no free source: EIA publishes no ethane spot) and Waha
(no free source; the hub price is Henry Hub until a Waha agent exists)."""
from __future__ import annotations

from datetime import datetime, timezone

import series_catalog

ETHANE_MMBTU_PER_GAL = 0.0664                     # B2, the requirement's figure (the page's earlier 0.0665 was reconciled to this, O4)
TF_COST_USD_PER_GAL = 0.08                        # ASSUMPTION (AD3): transport + fractionation; replace with the actual contract rate
FULL_REJECTION_DEFICIT_USD_MMBTU = 1.00           # ASSUMPTION: deficit at which rejection is complete
RECOVERY_SWING_BCFD = (0.5, 1.5)                  # the requirement's stated swing
MAX_AGE_DAYS = 10.0
ETHANE_AGENT = "Agent_NGL_MontBelvieu_Ethane"
HH_AGENT = "Agent_HH_Spot_EIA"
WAHA_AGENT = "Agent_Gas_Waha_Spot"
LABELS = {
    "ethane_mmbtu_per_gal": {"value": ETHANE_MMBTU_PER_GAL, "unit": "MMBtu/gal", "kind": "physical", "note": "energy content of ethane used in the requirement (B2)"},
    "tf_cost": {"value": TF_COST_USD_PER_GAL, "unit": "USD/gal", "kind": "assumption", "note": "transport + fractionation; no value was supplied (AD3)"},
    "full_rejection_deficit": {"value": FULL_REJECTION_DEFICIT_USD_MMBTU, "unit": "USD/MMBtu", "kind": "assumption", "note": "margin deficit at which rejection is complete"},
    "recovery_swing": {"value": list(RECOVERY_SWING_BCFD), "unit": "Bcf/d", "kind": "stated in the requirement", "note": "+0.5 to +1.5 Bcf/d"},
}
FORMULA = "Ethane_Value = (c/gal / 100) / 0.0664;  rejection when Ethane_Value < Hub + T&F"


def ethane_usd_mmbtu(cents_per_gal: float) -> float:
    return cents_per_gal / 100.0 / ETHANE_MMBTU_PER_GAL


def tf_usd_mmbtu() -> float:
    return TF_COST_USD_PER_GAL / ETHANE_MMBTU_PER_GAL


def rejection(ethane_value: float, hub_price: float) -> dict:
    """B3, pure. margin = Ethane_Value - (hub + T&F). Returns the regime and the dry-gas delta (Bcf/d) as {low, central, high}."""
    breakeven = hub_price + tf_usd_mmbtu()
    margin = ethane_value - breakeven
    if margin >= 0:
        return {"regime": "RECOVERY", "margin_usd_mmbtu": margin, "breakeven_usd_mmbtu": breakeven, "rejection_fraction": 0.0, "net_dry_gas_delta_bcfd": {"low": 0.0, "central": 0.0, "high": 0.0}}
    frac = min(-margin / FULL_REJECTION_DEFICIT_USD_MMBTU, 1.0)
    lo, hi = RECOVERY_SWING_BCFD
    return {"regime": "REJECTION", "margin_usd_mmbtu": margin, "breakeven_usd_mmbtu": breakeven, "rejection_fraction": frac,
            "net_dry_gas_delta_bcfd": {"low": frac * lo, "central": frac * (lo + hi) / 2, "high": frac * hi}}


def _age_days(ts: str | None, cutoff: str) -> float | None:
    if not ts:
        return None
    f = "%Y-%m-%dT%H:%M:%SZ"
    return (datetime.strptime(cutoff, f).replace(tzinfo=timezone.utc) - datetime.strptime(ts, f).replace(tzinfo=timezone.utc)).total_seconds() / 86400.0


def _fresh(row: dict | None, cutoff: str) -> bool:
    return bool(row) and row.get("available_timestamp", "9999") <= cutoff and (_age_days(row.get("available_timestamp"), cutoff) or 0.0) <= MAX_AGE_DAYS \
        and row.get("provenance", "measured") == "measured"


def build(ethane: dict | None, hub: dict | None, waha: dict | None, cutoff: str, conn=None) -> dict:
    """ethane / hub / waha: latest row dicts {value, latest_target_timestamp, available_timestamp, provenance} (point in time, already <= cutoff) or None."""
    feeds = {}
    if conn is not None:
        for agent in (ETHANE_AGENT, HH_AGENT, WAHA_AGENT):
            feeds[agent] = series_catalog.feed_status(conn, agent, cutoff)
    feed_gaps = [{"agent_id": agent, "status": feed["status"], "label": feed["label"]} for agent, feed in feeds.items()
                 if feed["label"] in ("Feed Not Configured", "Feed Not Fresh")]
    blocked = []
    if not _fresh(ethane, cutoff):
        blocked.append({"input": ETHANE_AGENT, "reason": "no Mont Belvieu ethane price is collected: EIA publishes no ethane spot (collectors/eia_petroleum_spot.py), and no free feed was found",
                        "activate": "provide a licensed feed (OPIS/Argus/CME) and write collectors/ethane_<source>.py storing Agent_NGL_MontBelvieu_Ethane in cents/gal"})
    if not _fresh(hub, cutoff):
        blocked.append({"input": HH_AGENT, "reason": "no fresh Henry Hub spot at the cutoff", "activate": "python collectors/run_all.py (eia_prices)"})
    waha_note = {"input": WAHA_AGENT, "status": "BLOCKED" if not _fresh(waha, cutoff) else "available",
                 "reason": "no Waha price source is collected (AD2); the hub price used is Henry Hub only", "activate": "add a licensed Waha feed as collectors/waha_<source>.py (Agent_Gas_Waha_Spot)"}
    base = {"provenance": "extracted_estimate", "formula": FORMULA, "assumptions": LABELS, "waha": waha_note, "feed_gaps": feed_gaps, "unit": "Bcf/d",
            "output_contract": "only net_dry_gas_delta_bcfd may enter the forward pricing balance (B4); no balance model consumes it yet (O6)", "feeds_forward_balance": False}
    if blocked:
        return {**base, "status": "pending_collector", "blocked": blocked, "tf_usd_mmbtu": tf_usd_mmbtu()}
    ev, hp = ethane_usd_mmbtu(ethane["value"]), hub["value"]
    r = rejection(ev, hp)
    return {**base, "status": "estimate", "blocked": [], "ethane_value_usd_mmbtu": ev, "hub_price_usd_mmbtu": hp, "hub": "Henry Hub (Waha not available)", "tf_usd_mmbtu": tf_usd_mmbtu(),
            "ethane_date": (ethane.get("latest_target_timestamp") or "")[:10], "hub_date": (hub.get("latest_target_timestamp") or "")[:10], **r}
