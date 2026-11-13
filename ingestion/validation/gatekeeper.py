"""Deterministic pre-database sanity gate (no LLM): physical range / unit checks per agent family."""
RANGES = {  # agent_id prefix -> (min, max, unit)
    "Agent_Storage_": (0.0, 4500.0, "Bcf"),
    "Agent_HH_": (-10.0, 50.0, "USD/MMBtu"),
    "Agent_Power_CO2_": (0.0, 200.0, "USD/short ton"),
    "Agent_Prod_": (0.0, 60.0, "Bcf/d"),
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
