"""The ONE place for every LNG-curve assumption. Nothing here is a market quote.

Each constant is labelled `assumption` (a modelling choice you should review and change) or `physical` (a unit conversion). Every number the
dashboard shows from these is traced back to them in the API (`curves.lng_forward.assumptions`) and in the tooltips, so a changed constant is visible
everywhere. Change a value here and restart the service; tests recompute expected numbers from these names, never from copies.
"""
from __future__ import annotations

# ---- US Gulf Coast LNG FOB cost:  cost_m = FEEDGAS_FACTOR * HenryHub_m + LIQUEFACTION_FEE_USD_MMBTU
FEEDGAS_FACTOR = 1.15                 # assumption: MMBtu of feed gas bought per MMBtu of LNG delivered (fuel + shrink); the 1.15 multiplier of the model
LIQUEFACTION_FEE_USD_MMBTU = 2.50     # assumption (default): tolling / liquefaction fee, USD per MMBtu

# ---- Netback to the US Gulf from a destination price:  NB_m = destination_m - SHIPPING - REGAS
SHIPPING_USD_MMBTU = 1.00             # assumption: US Gulf -> North-West Europe shipping, USD per MMBtu
REGAS_USD_MMBTU = 0.50                # assumption: regasification at the destination terminal, USD per MMBtu

# ---- TTF (EUR/MWh) -> USD/MMBtu
MMBTU_PER_MWH = 3.412142              # physical: 1 MWh = 3.412142 MMBtu
# EUR/USD is read from a collected quote (Agent_FX_EURUSD), never assumed.

# ---- freshness: a quote older than this at the PIT cutoff is NOT used (its last trade is too old to call current)
MAX_QUOTE_AGE_DAYS = 3.0              # assumption

# What each constant is, for the API and tooltips (kind is "assumption" or "physical").
LABELS = {
    "feedgas_factor": {"value": FEEDGAS_FACTOR, "unit": "MMBtu feed gas per MMBtu LNG", "kind": "assumption", "text": "feed gas bought per unit of LNG delivered (fuel and shrink)"},
    "liquefaction_fee": {"value": LIQUEFACTION_FEE_USD_MMBTU, "unit": "USD/MMBtu", "kind": "assumption", "text": "liquefaction (tolling) fee, default"},
    "shipping": {"value": SHIPPING_USD_MMBTU, "unit": "USD/MMBtu", "kind": "assumption", "text": "US Gulf to North-West Europe shipping"},
    "regas": {"value": REGAS_USD_MMBTU, "unit": "USD/MMBtu", "kind": "assumption", "text": "regasification at the destination"},
    "mmbtu_per_mwh": {"value": MMBTU_PER_MWH, "unit": "MMBtu per MWh", "kind": "physical", "text": "energy conversion for TTF"},
    "max_quote_age_days": {"value": MAX_QUOTE_AGE_DAYS, "unit": "days", "kind": "assumption", "text": "oldest last trade accepted as a current quote"},
}
