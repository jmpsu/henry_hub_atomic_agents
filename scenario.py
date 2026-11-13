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


_TIGHT = re.compile(r"\b(tighten\w*|tighter|deficit|shortage|undersuppl\w*|bullish|firm\w*|(prices?|basis)\s+(likely\s+to\s+)?(rise|rises|rising|increase\w*|spike\w*|higher))\b", re.I)
_LOOSE = re.compile(r"\b(loosen\w*|looser|surplus|oversuppl\w*|glut|bearish|soften\w*|weaken\w*|(prices?|basis)\s+(likely\s+to\s+)?(fall|falls|falling|decline\w*|drop\w*|lower))\b", re.I)


def thesis_consistency(thesis: str, delta: float) -> str:
    """Deterministic sign check of the model's prose against the computed balance delta (positive = looser).
    Returns 'consistent', 'contradicts_computed_delta', or 'not_checked' (zero delta or no directional wording)."""
    if not delta:
        return "not_checked"
    tight, loose = bool(_TIGHT.search(thesis or "")), bool(_LOOSE.search(thesis or ""))
    if tight == loose:
        return "not_checked"
    return "consistent" if (loose if delta > 0 else tight) else "contradicts_computed_delta"


_BAD = re.compile(r"(;|--|/\*|\b(pragma|attach|insert|update|delete|drop|alter|create|replace|vacuum|load_extension|with|main|temp|sqlite_\w*)\b)", re.I)
_TS = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_FUNCS = {"count", "sum", "avg", "min", "max", "round", "abs", "substr", "lower", "upper", "coalesce", "like", "date", "strftime", "total", "length"}
MAX_ROWS = 200


def norm_ts(ts: str) -> str:
    """Parse any ISO-8601 timestamp, convert to UTC and return the stored 'YYYY-MM-DDTHH:MM:SSZ' form. Raises ValueError."""
    from datetime import datetime, timezone
    dt = datetime.fromisoformat(str(ts).strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_sql(sql: str, as_of: str) -> str | None:
    """Textual pre-check (None = acceptable). The hard guarantee is run_sandboxed(), which enforces the cutoff and table
    restriction regardless of the SQL text."""
    s = (sql or "").strip()
    if len(s) > 800:
        return "too long"
    if not s.upper().startswith("SELECT"):
        return "not a SELECT"
    if _BAD.search(s):
        return "forbidden token"
    if len(re.findall(r"\bselect\b", s, re.I)) != 1:
        return "subqueries not allowed"
    if re.search(r"\bjoin\b|\bunion\b|\bintersect\b|\bexcept\b", s, re.I):
        return "join/union not allowed"
    if len(re.findall(r"\bfrom\b", s, re.I)) != 1 or not re.search(r"\bfrom\s+pit_market_data\b(?!\s*,)", s, re.I):
        return "must read pit_market_data only"
    if re.search(r"\bor\b", s, re.I):
        return "OR not allowed"
    if not re.search(r"available_timestamp\s*<=\s*'" + re.escape(as_of) + r"'", s, re.I):
        return "PIT cutoff not enforced"
    return None


def run_sandboxed(db_path: str, sql: str, as_of: str, max_rows: int = MAX_ROWS, max_steps: int = 20_000_000) -> list:
    """Execute a SELECT so that it can only see pit_market_data rows with available_timestamp <= as_of, whatever the SQL says:
    read-only connection + TEMP VIEW shadowing the table with the cutoff + authorizer denying every other table/function."""
    if not _TS.fullmatch(as_of):
        raise ValueError("as_of must be normalised with norm_ts first")
    if not sql.strip().upper().startswith("SELECT"):
        raise ValueError("Blocked non-SELECT query for safety.")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        conn.execute(f"CREATE TEMP VIEW pit_market_data AS SELECT * FROM main.pit_market_data WHERE available_timestamp <= '{as_of}'")

        def auth(action, a1, a2, db, src):
            if action == sqlite3.SQLITE_SELECT:
                return sqlite3.SQLITE_OK
            if action == sqlite3.SQLITE_READ and a1 == "pit_market_data" and (db == "temp" or src == "pit_market_data"):
                return sqlite3.SQLITE_OK
            if action == sqlite3.SQLITE_FUNCTION and (a2 or "").lower() in _FUNCS:
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY
        conn.set_authorizer(auth)
        steps = [0]

        def tick():
            steps[0] += 100_000
            return 1 if steps[0] > max_steps else 0
        conn.set_progress_handler(tick, 100_000)
        return conn.execute(sql).fetchmany(max_rows)
    finally:
        conn.close()


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
    return {"pit_rows_by_provenance": prov, "latest_available_timestamp": latest, "returned_rows": len(rows), "row_cap": MAX_ROWS,
            "unverified_seed_rows_in_pit": prov.get("unverified_seed", 0),
            "note": "measured = source data; extracted_estimate/model_hypothesis/synthetic_scenario are not observed facts"}
