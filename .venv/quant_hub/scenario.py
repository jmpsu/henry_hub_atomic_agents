"""Deterministic scenario arithmetic + SQL validation for /execute. No LLM involvement in numbers or SQL safety.
scenario_delta_bcf is a USER-STATED ASSUMPTION translated to balance sign (supply minus demand, Bcf/d); it is a
synthetic_scenario, never a forecast or measured fact."""
import re
import sqlite3

_NUM = re.compile(r"(\d+(?:\.\d+)?)\s*(?:bcf\s*/?\s*d(?:ay)?|bcfd)", re.I)
_DOWN = re.compile(r"\b(drop(?:s|ping|ped)?|fall(?:s|ing)?|fell|declin\w*|cut(?:s|ting)?|reduc\w*|outage|offline|lose|loss|trip\w*|shut\w*|curtail\w*)\b", re.I)
_UP = re.compile(r"\b(rise|rises|rising|increas\w*|jump\w*|surge\w*|add(?:s|ed|ing)?|gain\w*|restart\w*|ramp\w*)\b", re.I)
_DEMAND = re.compile(r"\b(feedgas|lng|export\w*|demand|power\s*burn|burn|consumption|res(?:idential)?|industrial)\b", re.I)
_SUPPLY = re.compile(r"\b(production|supply|output|wellhead|pipeline|flow\w*|permian|freeze[- ]?off|import\w*)\b", re.I)


def estimate_delta(query: str) -> dict:
    """Return {'value': float, 'basis': str}. Positive = looser balance (more supply or less demand)."""
    m = _NUM.search(query)
    if not m:
        return {"value": 0.0, "basis": "no Bcf/d quantity in query; delta left at 0.0"}
    mag = float(m.group(1))
    down, up = bool(_DOWN.search(query)), bool(_UP.search(query))
    demand, supply = bool(_DEMAND.search(query)), bool(_SUPPLY.search(query))
    if down == up or demand == supply:
        return {"value": 0.0, "basis": f"{mag} Bcf/d found but direction or side (supply vs demand) ambiguous; delta left at 0.0"}
    direction = -1.0 if down else 1.0            # change in the flow itself
    side = -1.0 if demand else 1.0               # demand reduces balance when it rises
    return {"value": round(mag * direction * side, 3),
            "basis": f"user-stated {mag} Bcf/d {'decrease' if down else 'increase'} in {'demand' if demand else 'supply'}; "
                     "mapped to balance = supply - demand; scenario assumption, no price elasticity applied"}


_BAD = re.compile(r"(;|--|/\*|\b(pragma|attach|insert|update|delete|drop|alter|create|replace|vacuum|load_extension)\b)", re.I)


def validate_sql(sql: str, as_of: str) -> str | None:
    """Return None if acceptable, else the rejection reason. Must be one SELECT on pit_market_data/pit_snapshot-safe table
    and enforce the PIT cutoff literally."""
    s = (sql or "").strip()
    if not s.upper().startswith("SELECT"):
        return "not a SELECT"
    if _BAD.search(s):
        return "forbidden token"
    if re.search(r"\bjoin\b|\bunion\b", s, re.I):
        return "join/union not allowed"
    if not re.search(r"\bfrom\s+pit_market_data\b", s, re.I):
        return "must read pit_market_data only"
    if not re.search(r"available_timestamp\s*<=\s*'" + re.escape(as_of) + r"'", s, re.I):
        return "PIT cutoff not enforced"
    return None


def fallback_sql(as_of: str, agent_hint: str | None = None) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]", "", agent_hint or "")
    where = f"available_timestamp <= '{as_of}'" + (f" AND agent_id LIKE '%{safe}%'" if safe else "")
    return ("SELECT agent_id,target_timestamp,available_timestamp,value,provenance FROM pit_market_data "
            f"WHERE {where} ORDER BY available_timestamp DESC LIMIT 25")


def data_quality(db_path: str, as_of: str, rows: list) -> dict:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        prov = dict(conn.execute("SELECT provenance,COUNT(*) FROM pit_market_data WHERE available_timestamp<=? GROUP BY 1", (as_of,)).fetchall())
        latest = conn.execute("SELECT MAX(available_timestamp) FROM pit_market_data WHERE available_timestamp<=?", (as_of,)).fetchone()[0]
    finally:
        conn.close()
    return {"pit_rows_by_provenance": prov, "latest_available_timestamp": latest, "total_matching_rows": len(rows),
            "unverified_seed_rows_in_pit": prov.get("unverified_seed", 0),
            "note": "measured = source data; extracted_estimate/model_hypothesis/synthetic_scenario are not observed facts"}
