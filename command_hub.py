"""Henry Hub zero-trust quant hub. FastAPI on 127.0.0.1:8090 (cloudflared -> quant.joeysvault.app).

POST /execute {"query": str, "as_of_timestamp": ISO-8601}
  -> {sql_query, scenario_delta_bcf, alpha_thesis, rows, rows_returned, pit_cutoff, audit}
Every read is restricted to available_timestamp <= as_of_timestamp (no look-ahead bias).
"""
import asyncio
import json
import os
import re
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

BASE = Path(__file__).resolve().parent


# ===================== STEP 2/3 support: environment loader =====================
def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "'\"":
            val = val[1:-1]
        os.environ.setdefault(key.strip(), val)


load_env(BASE / ".env")
DB_PATH = Path(os.environ.get("DB_PATH", BASE / "henry_hub_pit.db"))
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
MODEL = "qwen3:4b"
AUDIT_GIST = os.environ.get("AUDIT_GIST", "1") == "1"
AUDIT_DIR = Path(os.environ.get("AUDIT_DIR", BASE / "audit"))
GH_BIN = os.environ.get("GH_BIN", "gh")
CONTEXT_ROWS = 15  # closest chronological rows fed to the model
MAX_RESULT_ROWS = int(os.environ.get("MAX_RESULT_ROWS", "200"))
OLLAMA_OPTIONS = {"temperature": 0.0, "num_ctx": 2048, "num_predict": 180}

DEFAULT_AGENTS = ["Agent_HH_M1", "Agent_Storage_East", "Agent_Weather_Actual_HDD"]
KEYWORD_AGENTS = {
    r"freeze|pipeline|outage|production|supply": [
        "Agent_Prod_Appalachia", "Agent_Prod_Haynesville", "Agent_Prod_Permian"],
    r"lng|export|feedgas": [
        "Agent_LNG_SabinePass_Flow", "Agent_LNG_CorpusChristi_Flow", "Agent_LNG_Cameron_Flow"],
    r"winter|cold|hdd|heating|demand": [
        "Agent_Weather_Actual_HDD", "Agent_GFS_00z_HDD_Day5", "Agent_ECMWF_00z_HDD_Day5"],
    r"summer|heat|cdd|power|cooling": ["Agent_Weather_Actual_CDD", "Agent_Demand_PowerBurn"],
    r"storage|inventory|injection|withdrawal": [
        "Agent_Storage_East", "Agent_Storage_Midwest", "Agent_Storage_SouthCentral_Salt"],
    r"coal|switch": ["Agent_Coal_PRB_SpotPrice", "Agent_Coal_CAPP_SpotPrice"],
}

app = FastAPI(title="Henry Hub Quant Hub")


class ExecuteRequest(BaseModel):
    query: str
    as_of_timestamp: str


def norm_ts(value: str) -> str:
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(422, "as_of_timestamp must be ISO-8601")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ===================== STEP 3: context & retrieval =====================
def ro_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=5)
    conn.execute("PRAGMA query_only=ON")
    return conn


def select_agents(query: str) -> list:
    agents = list(DEFAULT_AGENTS)
    for pattern, ids in KEYWORD_AGENTS.items():
        if re.search(pattern, query, re.I):
            agents += ids
    seen, out = set(), []
    for a in agents:
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out[:12]


def _fetch_context(agent_ids: list, as_of: str) -> list:
    marks = ",".join("?" * len(agent_ids))
    sql = (
        "SELECT agent_id, target_timestamp, available_timestamp, value FROM pit_market_data "
        f"WHERE agent_id IN ({marks}) AND available_timestamp <= ? "
        "ORDER BY available_timestamp DESC, target_timestamp DESC LIMIT ?"
    )
    with ro_connect() as conn:
        return conn.execute(sql, (*agent_ids, as_of, CONTEXT_ROWS)).fetchall()


async def retrieve_context(agent_ids: list, as_of: str) -> list:
    return await asyncio.to_thread(_fetch_context, agent_ids, as_of)


def context_text(rows: list) -> str:
    if not rows:
        return "no data available at cutoff"
    return "\n".join(f"{a} tgt={t[:10]} avail={av[:16]} v={v:g}" for a, t, av, v in rows)


# ===================== STEP 4: Ollama structural translation =====================
LLM_SCHEMA = {
    "type": "object",
    "properties": {
        "sql_query": {"type": "string"},
        "scenario_delta_bcf": {"type": "number"},
        "alpha_thesis": {"type": "string"},
    },
    "required": ["sql_query", "scenario_delta_bcf", "alpha_thesis"],
    "additionalProperties": False,
}
LLM_LOCK = asyncio.Semaphore(1)  # one request at a time keeps the iGPU queue deterministic


def build_prompt(query: str, as_of: str, ctx: str) -> str:
    # "/no_think" is appended at the very end of the prompt.
    return (
        "You are a Henry Hub natural gas quant. Output one JSON object with exactly these keys.\n"
        "sql_query: one SQLite SELECT on pit_market_data(agent_id,target_timestamp,available_timestamp,value) "
        f"whose WHERE clause contains available_timestamp <= '{as_of}'.\n"
        "scenario_delta_bcf: your own estimate of the supply-demand balance change in Bcf/d "
        "(negative = tighter); derive it from the scenario, do not copy the example.\n"
        "alpha_thesis: exactly 2 short sentences linking the data to Henry Hub price.\n"
        'Example: {"sql_query":"SELECT agent_id,value FROM pit_market_data WHERE '
        f"available_timestamp <= '{as_of}' AND agent_id='Agent_HH_M1'\","
        '"scenario_delta_bcf":-1.2,"alpha_thesis":"Storage draws tighten the balance. '
        'Prompt-month futures should firm."}\n'
        f"Scenario: {query}\nData visible at cutoff:\n{ctx}\n/no_think"
    )


async def call_ollama(client: httpx.AsyncClient, prompt: str) -> dict:
    body = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "keep_alive": -1,
        "format": LLM_SCHEMA,
        "options": OLLAMA_OPTIONS,
    }
    async with LLM_LOCK:
        resp = await client.post(f"{OLLAMA_URL}/api/generate", json=body)
    resp.raise_for_status()
    data = json.loads(resp.json()["response"])
    if not all(k in data for k in LLM_SCHEMA["required"]):
        raise ValueError("missing keys")
    return data


async def translate(query: str, as_of: str, ctx: str) -> dict:
    prompt = build_prompt(query, as_of, ctx)
    async with httpx.AsyncClient(timeout=120) as client:
        last = None
        for _ in range(2):  # one retry on malformed/truncated JSON
            try:
                return await call_ollama(client, prompt)
            except (json.JSONDecodeError, ValueError, KeyError) as exc:
                last = exc
            except httpx.HTTPError as exc:
                raise HTTPException(502, f"ollama error: {exc}")
    raise HTTPException(502, f"model returned invalid JSON: {last}")


def two_sentences(text: str) -> str:
    parts = re.findall(r"[^.!?]+[.!?]", text.strip())
    return " ".join(p.strip() for p in parts[:2]) if parts else text.strip()


# ===================== STEP 5: read-only SQL sandbox =====================
FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|detach|pragma|replace|vacuum|reindex|"
    r"load_extension|union|with)\b|--|/\*|;",
    re.I,
)


def sql_is_safe(sql: str, as_of: str) -> bool:
    s = sql.strip()
    return (
        s[:6].upper() == "SELECT"  # must explicitly begin with SELECT
        and not FORBIDDEN.search(s)
        and len(re.findall(r"\bfrom\b", s, re.I)) == 1
        and re.search(r"\bfrom\s+pit_market_data\b", s, re.I) is not None
        and re.search(rf"available_timestamp\s*<=\s*'{re.escape(as_of)}'", s, re.I) is not None
        and len(s) <= 800
    )


def compiled_sql(agent_ids: list, as_of: str) -> str:
    ids = ",".join(f"'{a}'" for a in agent_ids if re.fullmatch(r"[A-Za-z0-9_]+", a))
    return (
        "SELECT agent_id, target_timestamp, available_timestamp, value FROM pit_market_data "
        f"WHERE available_timestamp <= '{as_of}' AND agent_id IN ({ids}) "
        f"ORDER BY available_timestamp DESC LIMIT {MAX_RESULT_ROWS}"
    )


def _run_sql(sql: str) -> list:
    with ro_connect() as conn:  # file:...?mode=ro + PRAGMA query_only
        cur = conn.execute(sql)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchmany(MAX_RESULT_ROWS)]


async def sandbox_execute(llm_sql: str, agent_ids: list, as_of: str):
    if llm_sql.strip()[:6].upper() != "SELECT":
        raise HTTPException(422, "blocked: model SQL does not begin with SELECT")
    source = "llm"
    sql = llm_sql.strip()
    if not sql_is_safe(sql, as_of):
        # Unsafe or not point-in-time bounded: never run it; use the deterministic compiled query.
        sql, source = compiled_sql(agent_ids, as_of), "compiled-fallback"
    try:
        rows = await asyncio.to_thread(_run_sql, sql)
    except sqlite3.Error as exc:
        sql, source = compiled_sql(agent_ids, as_of), "compiled-fallback"
        try:
            rows = await asyncio.to_thread(_run_sql, sql)
        except sqlite3.Error as exc2:
            raise HTTPException(422, f"sql execution failed: {exc2}")
    return sql, source, rows


# ===================== STEP 6: immutable audit log (gh gist) =====================
def write_audit(markdown: str, stamp: str) -> dict:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    path = AUDIT_DIR / f"pit_alpha_audit_{stamp}.md"
    path.write_text(markdown)
    out = {"local_path": str(path), "gist_url": None, "error": None}
    if not AUDIT_GIST:
        return out
    try:
        proc = subprocess.run(  # gh gist create is private (secret) unless --public is passed
            [GH_BIN, "gist", "create", str(path), "--desc", f"PIT Alpha Hub audit {stamp}"],
            capture_output=True, text=True, timeout=45,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            out["gist_url"] = proc.stdout.strip().splitlines()[-1]
        else:
            out["error"] = (proc.stderr or "gh returned no URL").strip()[:300]
    except (OSError, subprocess.TimeoutExpired) as exc:
        out["error"] = str(exc)
    return out


def audit_markdown(stamp, now, query, as_of, sql, source, delta, thesis, rows, ctx):
    table = "\n".join(
        f"| {r.get('agent_id','')} | {r.get('target_timestamp','')} | "
        f"{r.get('available_timestamp','')} | {r.get('value','')} |" for r in rows[:50]
    )
    return (
        f"# PIT Alpha Hub audit {stamp}\n\n"
        f"- Executed (UTC): {now.isoformat()}\n- PIT cutoff (as_of): `{as_of}`\n"
        f"- Command: {query}\n- Model: {MODEL} (num_ctx 2048, num_predict 180, /no_think)\n\n"
        f"## SQL ({source})\n```sql\n{sql}\n```\n\n"
        f"## Analytical output\n- scenario_delta_bcf: {delta}\n- alpha_thesis: {thesis}\n\n"
        f"## Rows returned: {len(rows)}\n| agent_id | target | available | value |\n|---|---|---|---|\n{table}\n\n"
        f"## Context given to model\n```\n{ctx}\n```\n"
    )


# ===================== API =====================
@app.get("/health")
async def health():
    return {"ok": True, "db_exists": DB_PATH.exists()}


@app.post("/execute")
async def execute(req: ExecuteRequest):
    as_of = norm_ts(req.as_of_timestamp)
    if not DB_PATH.exists():
        raise HTTPException(500, "database missing; run init_db.py")
    query = req.query.strip()[:500]
    if not query:
        raise HTTPException(422, "query is empty")
    agent_ids = select_agents(query)
    ctx_rows = await retrieve_context(agent_ids, as_of)
    ctx = context_text(ctx_rows)
    llm = await translate(query, as_of, ctx)
    delta = llm["scenario_delta_bcf"]
    delta = float(delta) if isinstance(delta, (int, float)) and not isinstance(delta, bool) else 0.0
    thesis = two_sentences(str(llm["alpha_thesis"]))
    sql, source, rows = await sandbox_execute(str(llm["sql_query"]), agent_ids, as_of)
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%S%fZ")
    md = audit_markdown(stamp, now, query, as_of, sql, source, delta, thesis, rows, ctx)
    audit = await asyncio.to_thread(write_audit, md, stamp)
    return {
        "sql_query": sql, "sql_source": source, "scenario_delta_bcf": delta,
        "alpha_thesis": thesis, "rows_returned": len(rows), "pit_cutoff": as_of,
        "rows": rows, "audit": audit, "gist_url": audit["gist_url"],
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8090")))
