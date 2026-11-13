import asyncio, json, os, sqlite3, subprocess, sys, tempfile, hashlib, shutil
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import httpx
import chromadb
import scenario

app = FastAPI()
OLLAMA_GEN_URL = "http://127.0.0.1:11434/api/generate"
OLLAMA_EMB_URL = "http://127.0.0.1:11434/api/embeddings"
DB_PATH = os.environ.get("DB_PATH", "")
if not DB_PATH or not os.path.isabs(DB_PATH) or not os.path.isfile(DB_PATH):
    # No silent fallback to a cwd-relative or default database.
    raise RuntimeError("DB_PATH must be set to an existing absolute path (see .env)")

chroma_client = chromadb.PersistentClient(path="./chroma_pit_kb")
kb_collection = chroma_client.get_or_create_collection(name="henry_hub_alpha_graph")

class CommandRequest(BaseModel):
    query: str
    as_of_timestamp: str | None = None

async def get_embedding(text: str) -> list[float]:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            OLLAMA_EMB_URL,
            json={"model": "nomic-embed-text", "prompt": text},
            timeout=30.0
        )
        resp.raise_for_status()
        return resp.json()["embedding"]

_AGENT_HINTS = [
    (("storage", "inventory", "salt", "injection", "withdrawal"), "Agent_Storage_%"),
    (("hdd", "cdd", "weather", "cold", "freeze", "winter", "heat", "temperature"), "Agent_Weather_%"),
    (("gfs",), "Agent_GFS_%"), (("ecmwf", "euro"), "Agent_ECMWF_%"),
    (("price", "henry", "spot", "hh", "futures", "m1", "basis"), "Agent_HH_%"),
    (("lng", "feedgas", "sabine", "export"), "Agent_LNG_%"),
]


def agent_filters(query: str) -> list[str]:
    q = query.lower()
    hits = [pat for words, pat in _AGENT_HINTS if any(w in q for w in words)]
    return hits or ["%"]


def retrieve_sql_context(as_of: str, query: str = "") -> str:
    """15 most recent PIT-eligible rows matching the agent_id filter implied by the query (available_timestamp <= as_of)."""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    cursor = conn.cursor()
    pats = agent_filters(query)
    cond = " OR ".join(["agent_id LIKE ?"] * len(pats))
    cursor.execute(
        f"SELECT agent_id, target_timestamp, available_timestamp, value, provenance FROM pit_market_data "
        f"WHERE available_timestamp <= ? AND ({cond}) ORDER BY available_timestamp DESC, target_timestamp DESC LIMIT 15",
        (as_of, *pats)
    )
    rows = cursor.fetchall()
    conn.close()
    return "\n".join([f"{r[0]} | Target: {r[1]} | Avail: {r[2]} | Val: {r[3]} | {r[4]}" for r in rows])

def to_epoch(ts: str) -> int:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())

async def retrieve_vector_nodes(query: str, as_of: str) -> tuple[str, list[str]]:
    if kb_collection.count() == 0:
        return "No prior vector nodes indexed yet.", []
    q_emb = await get_embedding(query)
    results = kb_collection.query(
        query_embeddings=[q_emb],
        n_results=min(5, kb_collection.count()),
        where={"available_epoch": {"$lte": to_epoch(as_of)}}
    )
    docs = results.get("documents", [[]])[0]
    ids = results.get("ids", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    formatted = "\n".join([
        f"[Node {i} | Avail: {m.get('available_timestamp')} | Linked: {m.get('linked_nodes', 'none')}] {d}"
        for i, d, m in zip(ids, docs, metas)
    ])
    return formatted or "No PIT-eligible vector nodes found.", ids

async def store_compounding_node(query: str, as_of: str, analysis: dict, parent_ids: list[str], gist_url: str):
    node_id = "node_" + hashlib.sha256(f"{as_of}:{query}".encode()).hexdigest()[:12]
    doc_text = (
        f"Query: {query} | Thesis: {analysis['alpha_thesis']} | "
        f"Balance Delta: {analysis['scenario_delta_bcf']} Bcf/d | SQL: {analysis['sql_query']}"
    )
    emb = await get_embedding(doc_text)
    kb_collection.upsert(
        ids=[node_id],
        embeddings=[emb],
        documents=[doc_text],
        metadatas=[{
            "available_timestamp": as_of,
            "available_epoch": to_epoch(as_of),
            "scenario_delta_bcf": float(analysis["scenario_delta_bcf"]),
            "linked_nodes": ",".join(parent_ids) if parent_ids else "root",
            "gist_url": gist_url
        }]
    )
    return node_id

async def generate_pit_analysis(user_query: str, sql_ctx: str, vec_ctx: str, as_of: str, est: dict | None = None) -> dict:
    prompt = (
        f"You are a quantitative natural gas trading engine operating strictly Point-in-Time as of {as_of}.\n"
        f"User Command: {user_query}\n"
        + (f"Computed scenario balance delta (supply minus demand, positive=looser): {est['value']} Bcf/d. "
           "Your thesis MUST be consistent with this sign.\n" if est else "") + "\n"
        f"Structured PIT SQL Snapshots:\n{sql_ctx}\n\n"
        f"Retrieved Cross-Node Vector Knowledge:\n{vec_ctx}\n\n"
        "Return ONLY valid JSON with:\n"
        "- 'sql_query': A safe read-only SELECT query on 'pit_market_data' filtering available_timestamp <= as_of.\n"
        "- 'scenario_delta_bcf': Estimated daily supply/demand balance shift in Bcf/d.\n"
        "- 'alpha_thesis': Concise 2-sentence market impact summary building on linked vector nodes.\n"
        "Keep sql_query under 150 characters and alpha_thesis under 40 words; do not repeat timestamps in the thesis. "
        f"Example: {{\"sql_query\":\"SELECT agent_id,value FROM pit_market_data WHERE available_timestamp <= '{as_of}' LIMIT 20\","
        "\"scenario_delta_bcf\":-1.2,\"alpha_thesis\":\"Supply loss tightens the balance. Prompt-month should firm.\"} /no_think"
    )
    payload = {
        "model": "qwen3:4b",
        "prompt": prompt,
        "stream": False,
        "think": False,
        "keep_alive": -1,
        "format": {
            "type": "object",
            "properties": {
                "sql_query": {"type": "string"},
                "scenario_delta_bcf": {"type": "number"},
                "alpha_thesis": {"type": "string"}
            },
            "required": ["sql_query", "scenario_delta_bcf", "alpha_thesis"]
        },
        "options": {"temperature": 0.0, "num_ctx": 2048, "num_predict": 180}
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(OLLAMA_GEN_URL, json=payload, timeout=60.0)
        resp.raise_for_status()
        return json.loads(resp.json()["response"])

def execute_readonly_sql(sql: str) -> list:
    if not sql.strip().upper().startswith("SELECT"):
        raise ValueError("Blocked non-SELECT query for safety.")
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    cursor = conn.cursor()
    cursor.execute(sql)
    results = cursor.fetchall()
    conn.close()
    return results

def log_to_github_gist(command: str, as_of: str, result_payload: dict) -> str:
    timestamp_slug = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")
    markdown_body = (
        f"# Alpha Command Audit ({timestamp_slug})\n\n"
        f"**Command:** `{command}`\n**Point-in-Time Cutoff:** `{as_of}`\n"
        f"**Linked Parent Nodes:** `{result_payload.get('linked_parent_nodes', [])}`\n\n"
        f"## Synthesis & Thesis\n{result_payload['analysis']['alpha_thesis']}\n\n"
        f"**Estimated Balance Impact:** `{result_payload['analysis']['scenario_delta_bcf']} Bcf/d`\n\n"
        f"## Executed PIT Query\n```sql\n{result_payload['analysis']['sql_query']}\n```\n\n"
        f"## Database Rows Returned\n```json\n{json.dumps(result_payload['db_rows'], indent=2)}\n```\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as tmp:
        tmp.write(markdown_body)
        tmp_path = tmp.name
    proc = subprocess.run(
        [shutil.which("gh") or "/home/joey/.local/bin/gh", "gist", "create", tmp_path, "--desc", f"PIT Alpha Hub: {command[:60]}"],
        capture_output=True, text=True
    )
    return proc.stdout.strip() if proc.returncode == 0 else f"Gist Error: {proc.stderr}"

_INGEST_LOCK = asyncio.Lock()
_HERE = os.path.dirname(os.path.realpath(__file__))

@app.post("/ingest")
async def ingest_now():
    """Run every implemented collector (single-flight). Reachable only through the Access-protected tunnel."""
    if _INGEST_LOCK.locked():
        raise HTTPException(status_code=409, detail="ingestion already running")
    async with _INGEST_LOCK:
        def run():
            return subprocess.run([sys.executable, os.path.join(_HERE, "collectors", "run_all.py")],
                                  capture_output=True, text=True, timeout=240,
                                  env={**os.environ, "DB_PATH": DB_PATH})
        try:
            p = await asyncio.to_thread(run)
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=504, detail="ingestion timed out")
        lines = [l for l in p.stdout.splitlines() if l[:2] in ("OK", "FA")]
        return {"ok": p.returncode == 0, "exit": p.returncode, "results": lines[:20], "stderr": p.stderr[-300:]}

@app.get("/health")
async def health():
    return {"ok": True, "db": os.path.basename(DB_PATH), "vector_nodes": kb_collection.count()}

@app.post("/execute")
async def handle_remote_command(req: CommandRequest):
    as_of = req.as_of_timestamp or datetime.now(timezone.utc).isoformat()
    est = scenario.estimate_delta(req.query)
    sql_ctx = retrieve_sql_context(as_of, req.query)
    vec_ctx, parent_ids = await retrieve_vector_nodes(req.query, as_of)
    try:
        analysis = await generate_pit_analysis(req.query, sql_ctx, vec_ctx, as_of, est)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"model output failed: {e}")
    reason = scenario.validate_sql(analysis.get("sql_query", ""), as_of)
    if reason:
        sql_source, sql_rejected = "deterministic_fallback", reason
        analysis["sql_query"] = scenario.fallback_sql(as_of)
    else:
        sql_source, sql_rejected = "validated_model_output", None
    analysis["model_scenario_delta_bcf_ignored"] = analysis.get("scenario_delta_bcf")
    analysis["scenario_delta_bcf"] = est["value"]
    try:
        db_rows = execute_readonly_sql(analysis["sql_query"])
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    result = {
        "as_of_timestamp": as_of,
        "linked_parent_nodes": parent_ids,
        "analysis": analysis,
        "db_rows": db_rows[:25],
        "sql_source": sql_source,
        "sql_rejection_reason": sql_rejected,
        "scenario_basis": est["basis"],
        "provenance_labels": {"db_rows": "mixed; see provenance column / data_quality",
                              "scenario_delta_bcf": "synthetic_scenario",
                              "alpha_thesis": "model_hypothesis"},
        "data_quality": scenario.data_quality(DB_PATH, as_of, db_rows),
    }
    gist_url = log_to_github_gist(req.query, as_of, result)
    new_node_id = await store_compounding_node(req.query, as_of, analysis, parent_ids, gist_url)
    result["audit_gist_url"] = gist_url
    result["new_vector_node_id"] = new_node_id
    result["total_knowledge_nodes"] = kb_collection.count()
    return result
