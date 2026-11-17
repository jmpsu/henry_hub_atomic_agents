"""Deterministic pre-database sanity gate (no LLM): physical range / unit checks per agent family."""
RANGES = {  # agent_id prefix -> (min, max, unit)
    "Agent_Storage_": (0.0, 4500.0, "Bcf"),
    "Agent_HH_": (-10.0, 50.0, "USD/MMBtu"),
    "Agent_Power_CO2_": (0.0, 200.0, "USD/short ton"),
    "Agent_Coal_": (0.0, 500.0, "USD/short ton"),
    "Agent_Crude_": (-50.0, 300.0, "USD/bbl"),
    "Agent_NGL_": (0.0, 600.0, "cents/gal"),
    "Agent_Prod_": (0.0, 60.0, "Bcf/d"),
    "Agent_LNGExports_": (0.0, 300_000.0, "MMcf/month"),   # EIA monthly terminal exports (largest terminal ~120k); distinct from the daily Agent_LNG_*_Flow agents
    "Agent_BorderFlow_": (0.0, 300_000.0, "MMcf/month"),
    "Agent_TTF_": (0.0, 1000.0, "EUR/MWh"),                 # Dutch TTF monthly futures
    "Agent_FX_": (0.3, 3.0, "USD/EUR"),                     # EUR/USD spot (units of USD per EUR)   # EIA monthly border-point pipeline volumes
    "Agent_Demand_PowerBurn": (0.0, 20_000_000.0, "MWh/day"),   # checked before the Bcf/d demand family
    "Agent_Demand_": (0.0, 80.0, "Bcf/d"),
    "Agent_ECMWF_": (0.0, 80.0, "approx HDD"),
    "Agent_GFS_": (0.0, 80.0, "approx HDD"),
    "Agent_Weather_Actual_HDD": (0.0, 80.0, "population-weighted degree days"),
    "Agent_Weather_Actual_CDD": (0.0, 80.0, "population-weighted degree days"),
}


def check(agent_id: str, value: float, unit: str = ""):
    """Return (ok, reason). Unknown agents pass only if finite; known families must be in physical range."""
    if value != value or value in (float("inf"), float("-inf")):
        return False, "non-finite value"
    for prefix, (lo, hi, u) in RANGES.items():
        if agent_id.startswith(prefix):
            if not lo <= value <= hi:
                return False, f"{value} outside [{lo},{hi}] {u} (possible unit error)"
            return True, "ok"
    return True, "no range defined for this agent"
