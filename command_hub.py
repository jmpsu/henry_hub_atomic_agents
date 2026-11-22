import asyncio, json, os, sqlite3, subprocess, sys, hashlib, shutil
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import httpx
import chromadb
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import scenario
import kb_ingest
import notify
from agents.llm import CODER_CTX, CODER_MODEL, CODER_TOKENS, EMBED_MODEL

app = FastAPI()
OLLAMA_GEN_URL = "http://127.0.0.1:11434/api/generate"
OLLAMA_EMB_URL = "http://127.0.0.1:11434/api/embeddings"
DB_PATH = os.environ.get("DB_PATH", "")
if not DB_PATH or not os.path.isabs(DB_PATH) or not os.path.isfile(DB_PATH):
    # No silent fallback to a cwd-relative or default database.
    raise RuntimeError("DB_PATH must be set to an existing absolute path (see .env)")

_HERE = os.path.dirname(os.path.realpath(__file__))
chroma_client = chromadb.PersistentClient(path=os.environ.get("CHROMA_PATH") or os.path.join(_HERE, "chroma_pit_kb"))
kb_collection = chroma_client.get_or_create_collection(name="henry_hub_alpha_graph")

class CommandRequest(BaseModel):
    query: str
    as_of_timestamp: str | None = None

async def get_embedding(text: str) -> list[float]:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            OLLAMA_EMB_URL,
            json={"model": EMBED_MODEL, "prompt": text},
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
           "Your thesis MUST be consistent with this sign: "
           + ("positive means the balance LOOSENS (bearish for price).\n" if est["value"] > 0 else
              "negative means the balance TIGHTENS (bullish for price).\n" if est["value"] < 0 else "zero means no stated shift.\n") if est else "") + "\n"
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
        "model": CODER_MODEL,
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
        "options": {"temperature": 0.0, "num_ctx": CODER_CTX, "num_predict": CODER_TOKENS}
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(OLLAMA_GEN_URL, json=payload, timeout=300.0)
        resp.raise_for_status()
        return json.loads(resp.json()["response"])

def execute_readonly_sql(sql: str, as_of: str) -> list:
    """Model/fallback SQL runs only inside the PIT sandbox (cutoff view + authorizer + row cap + step limit)."""
    return scenario.run_sandboxed(DB_PATH, sql, as_of)

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
    # The audit body is piped to gh on stdin; nothing is written to disk.
    proc = subprocess.run(
        [shutil.which("gh") or "/home/joey/.local/bin/gh", "gist", "create", "-", "--filename", f"audit_{timestamp_slug}.md",
         "--desc", f"PIT Alpha Hub: {command[:60]}"],
        input=markdown_body, capture_output=True, text=True, timeout=45
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip()[:300] or f"gh exit {proc.returncode}")
    return proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""

_INGEST_LOCK = asyncio.Lock()

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
        try:  # fold what was just collected into the knowledge library; a failure here never fails the ingest
            kb = await asyncio.to_thread(kb_ingest.ingest, DB_PATH, kb_collection)
        except Exception as e:  # noqa: BLE001
            kb = {"error": str(e)[:200]}
        return {"ok": p.returncode == 0, "exit": p.returncode, "results": lines[:20], "stderr": p.stderr[-300:], "knowledge": kb,
                "agents": _agents_after_ingest()}


class EdgePayload(BaseModel):
    key: str
    url: str
    status: int
    content_type: str = ""
    retrieved_timestamp: str
    headers: dict = {}
    colo: str = ""
    body_b64: str


def _edge_sources(year: int) -> dict:
    """Whitelist of sources a Worker may fetch at the edge: key -> (exact URL, how to load it). The hub only ever parses a
    payload with the collector that owns that exact URL, so a forged request cannot choose a parser or a destination."""
    sys.path.insert(0, _HERE)
    from collectors import cpc_degree_days, eia_petroleum_spot, eia_prices, eia_storage, rggi_auctions
    return {
        "cpc_heating": (cpc_degree_days.BASE.format(year=year, kind="Heating"), lambda c, f: cpc_degree_days.collect(c, "Heating", year, f)),
        "cpc_cooling": (cpc_degree_days.BASE.format(year=year, kind="Cooling"), lambda c, f: cpc_degree_days.collect(c, "Cooling", year, f)),
        "eia_storage": (eia_storage.URL, lambda c, f: eia_storage.collect(c, f)),
        "eia_hh_spot": (eia_prices.URL.format(name="RNGWHHDd"), lambda c, f: eia_prices.collect(c, f, only=["RNGWHHDd"])),
        "eia_wti": (eia_petroleum_spot.URL.format(name="RWTCd"), lambda c, f: eia_petroleum_spot.collect(c, f, only=["RWTCd"])),
        "eia_propane": (eia_petroleum_spot.URL.format(name="EER_EPLLPA_PF4_Y44MB_DPGd"),
                        lambda c, f: eia_petroleum_spot.collect(c, f, only=["EER_EPLLPA_PF4_Y44MB_DPGd"])),
        "rggi": (rggi_auctions.URL, lambda c, f: rggi_auctions.collect(c, f)),
    }


_EDGE_LOCK = asyncio.Lock()


@app.post("/ingest/edge")
async def ingest_edge(p: EdgePayload):
    """Receive a payload a Cloudflare Worker fetched at the edge (Section 3.1/3.2). Reachable only through Access.
    The fetch metadata (status, headers, edge retrieval time, colo, size, hash) is recorded in edge_fetches whether or
    not parsing succeeds; the bytes are archived and parsed by the owning collector, exactly as a local fetch would be."""
    import base64
    import ingest as _ingest
    try:
        body = base64.b64decode(p.body_b64, validate=True)
    except Exception:
        raise HTTPException(status_code=422, detail="body_b64 is not valid base64")
    if len(body) > 8_000_000:
        raise HTTPException(status_code=413, detail="payload too large")
    try:
        retrieved = _ingest.utc_iso(p.retrieved_timestamp)
    except Exception:
        raise HTTPException(status_code=422, detail="retrieved_timestamp must be an ISO-8601 UTC timestamp")
    year = int(retrieved[:4])
    sources = _edge_sources(year)
    if p.key not in sources or p.url != sources[p.key][0]:
        raise HTTPException(status_code=422, detail="unknown edge source or URL does not match the whitelist")
    url, loader = sources[p.key]
    digest = hashlib.sha256(body).hexdigest()
    headers = {k.lower(): str(v)[:300] for k, v in list(p.headers.items())[:40]}

    def run():
        conn = sqlite3.connect(DB_PATH, timeout=30)
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS edge_fetches(id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT, url TEXT, http_status INTEGER, "
                         "content_type TEXT, headers TEXT, retrieved_timestamp TEXT, received_timestamp TEXT, colo TEXT, byte_length INTEGER, "
                         "sha256 TEXT, result TEXT, ok INTEGER)")
            received = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if p.status != 200:
                result, ok = {"error": f"edge fetch returned HTTP {p.status}"}, 0
            else:
                fetcher = lambda u: (p.status, body, p.content_type) if u == url else (404, b"", "")
                try:
                    result, ok = loader(conn, fetcher), 1
                except Exception as e:  # noqa: BLE001  (layout change, gatekeeper rejection...): recorded, not raised
                    result, ok = {"error": f"{type(e).__name__}: {e}"[:300]}, 0
            conn.execute("INSERT INTO edge_fetches(key,url,http_status,content_type,headers,retrieved_timestamp,received_timestamp,colo,byte_length,sha256,result,ok) "
                         "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (p.key, url, p.status, p.content_type, json.dumps(headers, sort_keys=True), retrieved, received,
                                                             p.colo[:16], len(body), digest, json.dumps(result, default=str)[:2000], ok))
            conn.commit()
            return {"ok": bool(ok), "key": p.key, "sha256": digest, "bytes": len(body), "result": result}
        finally:
            conn.close()
    async with _EDGE_LOCK:
        return await asyncio.to_thread(run)


class RerunRequest(BaseModel):
    collector: str
    sha: str
    pr: int | None = None
    base: str = "main"


_SELFHEAL_LOCK = asyncio.Lock()


@app.post("/selfheal/rerun")
async def selfheal_rerun(req: RerunRequest):
    """Spec 4.5: after an AUTHORIZED merge (GitHub webhook -> Worker verifies the HMAC -> here, through Access) retrieve the
    approved change, verify its identity, and rerun the affected collector. Identity check: the commit must exist on
    origin/main after a fresh fetch. The collector runs from a detached worktree of exactly that commit; the service's own
    checkout is not modified. Every attempt is recorded in selfheal_runs and reported on the 'selfheal' event stream."""
    import re as _re
    sys.path.insert(0, _HERE)
    from collectors import run_all
    if req.collector not in run_all.names():
        raise HTTPException(status_code=422, detail="unknown collector")
    if not _re.fullmatch(r"[0-9a-f]{7,40}", req.sha):
        raise HTTPException(status_code=422, detail="sha must be a hex commit id")
    deployed = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=_HERE, capture_output=True, text=True, timeout=10).stdout.strip()
    if req.base not in ("main", deployed):
        raise HTTPException(status_code=422, detail=f"base must be main or the deployed branch ({deployed})")
    if _SELFHEAL_LOCK.locked():
        raise HTTPException(status_code=409, detail="a self-heal rerun is already running")

    def run():
        git = lambda *a, t=120: subprocess.run(["git", *a], cwd=_HERE, capture_output=True, text=True, timeout=t)
        started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.execute("CREATE TABLE IF NOT EXISTS selfheal_runs(id INTEGER PRIMARY KEY AUTOINCREMENT, collector TEXT, sha TEXT, pr INTEGER, started TEXT, "
                     "verified INTEGER, ok INTEGER, detail TEXT)")
        verified, ok, detail, wt = 0, 0, "", None
        try:
            f = git("fetch", "--quiet", "origin", req.base)
            full = git("rev-parse", "--verify", req.sha + "^{commit}")
            anc = git("merge-base", "--is-ancestor", req.sha, f"origin/{req.base}") if full.returncode == 0 else None
            if f.returncode != 0 or full.returncode != 0 or anc is None or anc.returncode != 0:
                detail = f"identity check failed: commit not found on origin/{req.base} after fetch"
            else:
                verified = 1
                sha = full.stdout.strip()
                wt = os.path.join(_HERE, "runtime", "worktrees", sha[:12])
                git("worktree", "remove", "--force", wt)
                w = git("worktree", "add", "--detach", wt, sha)
                if w.returncode != 0:
                    detail = "worktree failed: " + w.stderr[-300:]
                else:
                    p = subprocess.run([sys.executable, os.path.join(wt, "collectors", "run_all.py"), "--only", req.collector], cwd=wt,
                                       capture_output=True, text=True, timeout=600, env={**os.environ, "DB_PATH": DB_PATH, "RAW_DIR": os.path.join(_HERE, "raw")})
                    ok = int(p.returncode == 0)
                    detail = (p.stdout[-1200:] + p.stderr[-400:]).strip()
        except Exception as e:  # noqa: BLE001
            detail = f"{type(e).__name__}: {e}"[:500]
        finally:
            if wt:
                git("worktree", "remove", "--force", wt)
        conn.execute("INSERT INTO selfheal_runs(collector,sha,pr,started,verified,ok,detail) VALUES (?,?,?,?,?,?,?)",
                     (req.collector, req.sha, req.pr, started, verified, ok, detail))
        conn.commit()
        conn.close()
        notify.event("selfheal", f"Rerun after merge: {req.collector} @ {req.sha[:10]} -> {'ok' if ok else 'FAILED'}",
                     f"PR: {req.pr or '-'}; identity verified on origin/{req.base}: {bool(verified)}\n\n```\n{detail[-1500:]}\n```")
        return {"collector": req.collector, "sha": req.sha, "verified": bool(verified), "ok": bool(ok), "detail": detail[-600:]}
    async with _SELFHEAL_LOCK:
        return await asyncio.to_thread(run)


_AGENTS_LOCK = asyncio.Lock()
_AGENTS_LAST: dict = {}


async def _run_agents(notice_limit: int = 150, trigger: str = "api") -> dict:
    from agents import workers
    async with _AGENTS_LOCK:
        rep = await asyncio.to_thread(workers.run_all, DB_PATH, kb_collection, None, None, max(1, min(notice_limit, 200)))
        _AGENTS_LAST.update(trigger=trigger, at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                            ok={k: v.get("ok") for k, v in rep.get("agents", {}).items()})
        return rep


@app.post("/agents/run")
async def agents_run(notice_limit: int = 150):
    """Run the research agents (diagnostics, data quality, repair assistance, pipeline-notice analyst, anomaly, cross-domain
    synthesis) point-in-time now. They use local Ollama, the shared knowledge library (including this process's Chroma
    collection) and the message bus. Access-protected like every privileged route."""
    if _AGENTS_LOCK.locked():
        raise HTTPException(status_code=409, detail="agents already running")
    return await _run_agents(notice_limit, "api")


def _agents_after_ingest() -> str:
    """Start an agent run in the background after collection (the Worker's /ingest call must not wait for it)."""
    if _AGENTS_LOCK.locked():
        return "already running"

    async def bg():
        try:
            await _run_agents(25, "after_ingest")
        except Exception as e:  # noqa: BLE001
            _AGENTS_LAST.update(trigger="after_ingest", error=str(e)[:300])
    asyncio.get_running_loop().create_task(bg())
    return "started"


@app.get("/agents/activity")
async def agents_activity(limit: int = 20):
    from agents import llm as agent_llm

    def q():
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        try:
            return kb_ingest.agent_activity(conn, max(1, min(limit, 100)))
        finally:
            conn.close()
    out = await asyncio.to_thread(q)
    out["ollama"] = await asyncio.to_thread(agent_llm.status)
    out["last_trigger"] = _AGENTS_LAST
    out["running"] = _AGENTS_LOCK.locked()
    return out


_KB_LOCK = asyncio.Lock()


@app.post("/kb/ingest")
async def kb_ingest_now():
    """Rebuild the knowledge library (SQLite graph + this process's vector store) from the PIT database. Access-protected."""
    if _KB_LOCK.locked():
        raise HTTPException(status_code=409, detail="knowledge ingest already running")
    async with _KB_LOCK:
        return await asyncio.to_thread(kb_ingest.ingest, DB_PATH, kb_collection)

_EXP_LOCK = asyncio.Lock()


class ExperimentJob(BaseModel):
    model: str
    horizon_days: int = 1
    cost_bps: float = 0.0
    n_decisions: int = 250
    slippage_bps: float = 0.0


@app.post("/experiments/run")
async def run_experiment(job: ExperimentJob):
    """One walk-forward experiment on local compute (single-flight). Reached only through the Access-protected tunnel
    (Cloudflare Queue consumer -> Worker -> here). Parameters are whitelisted; nothing here executes caller-supplied code or SQL."""
    import experiments
    if job.model not in experiments.MODELS or job.model == "persistence":
        raise HTTPException(status_code=422, detail=f"model must be one of {sorted(m for m in experiments.MODELS if m != 'persistence')}")
    if job.horizon_days not in (1, 2, 3, 5, 10) or not 0 <= job.cost_bps <= 100 or not 50 <= job.n_decisions <= 1000 or not 0 <= job.slippage_bps <= 100:
        raise HTTPException(status_code=422, detail="horizon_days in {1,2,3,5,10}, cost_bps 0..100, n_decisions 50..1000")
    if _EXP_LOCK.locked():
        raise HTTPException(status_code=409, detail="an experiment is already running")
    async with _EXP_LOCK:
        out = await asyncio.to_thread(experiments.run, DB_PATH, job.n_decisions, (job.horizon_days,), (job.cost_bps,), (job.model,), job.slippage_bps)
    lines = [f"- `{r[0]}` {r[1]} h={r[2]}d cost={r[3]}bps test {r[6]}: **{r[10]}**" for r in out if r[1] != "persistence"]
    await asyncio.to_thread(notify.event, "backtests", f"Backtest completed: {job.model} {job.horizon_days}d", "\n".join(lines))
    for r in out:
        if r[9]:   # promoted: a statistically defensible out-of-sample improvement
            await asyncio.to_thread(notify.event, "validated-hypotheses", f"Model promoted: {r[1]} {r[2]}d",
                                    f"Experiment `{r[0]}` passed the promotion gate (lower holdout RMSE, Bonferroni-significant direction, "
                                    f"positive net return after costs). Metrics: {json.dumps(r[7])[:1500]}")
    return {"ok": True, "results": [{"id": r[0], "model": r[1], "horizon_days": r[2], "cost_bps": r[3], "test_period": r[6],
                                     "metrics": r[7], "baseline_metrics": r[8], "promoted": r[9], "result": r[10], "pit_data_version": r[11]} for r in out]}


@app.get("/experiments")
async def list_experiments(limit: int = 25):
    def q():
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        try:
            return conn.execute("SELECT id,created,config,promoted,reason FROM experiments ORDER BY created DESC LIMIT ?", (max(1, min(limit, 200)),)).fetchall()
        except sqlite3.OperationalError:
            return []
        finally:
            conn.close()
    return {"experiments": [{"id": r[0], "created": r[1], "config": json.loads(r[2]), "promoted": bool(r[3]), "result": r[4]} for r in await asyncio.to_thread(q)]}


@app.get("/series-catalog")
@app.get("/api/series-catalog")
async def get_series_catalog(domain: str | None = None, active_only: bool = True):
    def q():
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        try:
            from series_catalog import list_series
            rows = list_series(conn, domain=domain, active_only=active_only)
            domains = sorted({r["domain"] for r in rows})
            return {"count": len(rows), "domains": domains, "series": rows}
        finally:
            conn.close()
    return await asyncio.to_thread(q)


@app.get("/health")
async def health():
    return {"ok": True, "db": os.path.basename(DB_PATH), "vector_nodes": kb_collection.count()}

@app.post("/execute")
async def handle_remote_command(req: CommandRequest):
    try:
        as_of = scenario.norm_ts(req.as_of_timestamp or datetime.now(timezone.utc).isoformat())
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="as_of_timestamp must be an ISO-8601 timestamp")
    est = scenario.estimate_delta(req.query)
    sql_ctx = await asyncio.to_thread(retrieve_sql_context, as_of, req.query)
    vec_ctx, parent_ids = await retrieve_vector_nodes(req.query, as_of)
    try:
        analysis = await generate_pit_analysis(req.query, sql_ctx, vec_ctx, as_of, est)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"model output failed: {e}")
    consistency = scenario.thesis_consistency(analysis.get("alpha_thesis", ""), est["value"])
    if consistency == "contradicts_computed_delta":
        # Untrusted model prose that contradicts the deterministic number is withheld (and never stored in the vector KB).
        analysis["alpha_thesis_rejected"] = analysis.get("alpha_thesis", "")
        d = est["value"]
        analysis["alpha_thesis"] = (f"Computed balance shift is {d:+.2f} Bcf/d ({'looser' if d > 0 else 'tighter'}), a stated scenario assumption. "
                                    "The model thesis contradicted this sign and was withheld.")
    reason = scenario.validate_sql(analysis.get("sql_query", ""), as_of)
    if reason:
        sql_source, sql_rejected = "deterministic_fallback", reason
        analysis["sql_query"] = scenario.fallback_sql(as_of)
    else:
        sql_source, sql_rejected = "validated_model_output", None
    analysis["model_scenario_delta_bcf_ignored"] = analysis.get("scenario_delta_bcf")
    analysis["scenario_delta_bcf"] = est["value"]
    try:
        db_rows = await asyncio.to_thread(execute_readonly_sql, analysis["sql_query"], as_of)
    except Exception as e:
        if sql_source == "deterministic_fallback":
            raise HTTPException(status_code=500, detail=f"fallback SQL failed: {e}")
        sql_source, sql_rejected = "deterministic_fallback", f"model SQL failed in sandbox: {str(e)[:120]}"
        analysis["sql_query"] = scenario.fallback_sql(as_of)
        db_rows = await asyncio.to_thread(execute_readonly_sql, analysis["sql_query"], as_of)
    result = {
        "as_of_timestamp": as_of,
        "linked_parent_nodes": parent_ids,
        "analysis": analysis,
        "db_rows": db_rows[:25],
        "sql_source": sql_source,
        "sql_rejection_reason": sql_rejected,
        "scenario_basis": est["basis"],
        "thesis_consistency": consistency,
        "provenance_labels": {"db_rows": "mixed; see provenance column / data_quality",
                              "scenario_delta_bcf": "synthetic_scenario",
                              "alpha_thesis": "model_hypothesis"},
        "data_quality": scenario.data_quality(DB_PATH, as_of, db_rows),
    }
    try:
        gist_url, audit_error = await asyncio.to_thread(log_to_github_gist, req.query, as_of, result), None
    except Exception as e:  # audit failure is reported, never disguised as a URL
        gist_url, audit_error = None, str(e)[:300]
    new_node_id = await store_compounding_node(req.query, as_of, analysis, parent_ids, gist_url or "")
    result["audit_gist_url"] = gist_url
    result["audit_error"] = audit_error
    result["new_vector_node_id"] = new_node_id
    result["total_knowledge_nodes"] = kb_collection.count()
    return result


# --- Coordinated release version reporting ---
from fastapi import Request
from fastapi.responses import JSONResponse
from release.version import get_release_info as _get_release_info

@app.middleware("http")
async def _inject_release_version(request: Request, call_next):
    resp = await call_next(request)
    if request.url.path in ("/health", "/api/health") and resp.status_code == 200 and "application/json" in resp.headers.get("content-type", ""):
        body = b"".join([chunk async for chunk in resp.body_iterator])
        try:
            data = json.loads(body.decode("utf-8"))
            if isinstance(data, dict):
                data.update(_get_release_info())
                return JSONResponse(content=data, status_code=resp.status_code)
        except Exception:
            pass
    return resp
