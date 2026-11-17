"""Public READ-ONLY visual intelligence service for markets.joeysvault.app and ngl.joeysvault.app (127.0.0.1:8095).

Isolation from the privileged hub (command_hub.py on :8090):
- separate process and port; it has no /execute, /ingest, /experiments or /kb/ingest and imports none of that code;
- the database is opened read-only (mode=ro) for every request and never written;
- the only model calls are local Ollama: an embedding for knowledge search (rate-limited, cached) and the grounded chat (/api/chat), which is read-only, limited to the
  dashboard's point-in-time cutoff, rate-limited, and appends each turn to a SEPARATE local audit file (runtime/chat_log.db), never to the market database;
- every static asset (libraries, basemap, fonts) is served from web/ in this repository, nothing from a third-party CDN.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from collections import OrderedDict, deque
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

import chat_service
import kb_ingest
import literature_kb
import markets_engine as me

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"
DB_PATH = os.environ.get("DB_PATH") or str(BASE_DIR / "henry_hub_pit.db")
if not os.path.isabs(DB_PATH) or not os.path.isfile(DB_PATH):
    raise RuntimeError("DB_PATH must be an existing absolute path")

app = FastAPI(title="NGL & Henry Hub Visual Intelligence", docs_url=None, redoc_url=None, openapi_url=None)
_SEARCH_CACHE: OrderedDict = OrderedDict()
_SEARCH_TIMES: deque = deque()
SEARCH_PER_MINUTE = 30
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
                               "script-src 'self'; worker-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'",
}


@app.middleware("http")
async def headers(request: Request, call_next):
    resp = await call_next(request)
    for k, v in SECURITY_HEADERS.items():
        resp.headers.setdefault(k, v)
    if request.url.path.startswith("/api/"):
        resp.headers.setdefault("Cache-Control", "public, max-age=60")
        resp.headers.setdefault("Access-Control-Allow-Origin", "*")
    return resp


def _ro() -> sqlite3.Connection:
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


def _cutoff(as_of: str | None) -> str:
    try:
        return me.pit_cutoff(as_of)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="as_of must be an ISO-8601 timestamp")


def _state(product: str | None, timeframe: str, as_of: str | None) -> dict:
    cutoff = _cutoff(as_of) if as_of else None
    conn = _ro()
    try:
        knowledge = kb_ingest.summary(conn, kb_ingest.epoch(cutoff or me.pit_cutoff(None)))
    finally:
        conn.close()
    return me.cached_state(DB_PATH, product, timeframe, cutoff, knowledge)


@app.get("/api/state.json")
def state(product: str | None = Query(None, max_length=32), timeframe: str = Query("seasonal", max_length=16), as_of: str | None = Query(None, max_length=40)):
    """The one document the web UI and ngl-term.py both render."""
    return JSONResponse(_state(product, timeframe, as_of))


@app.get("/api/market")
def market(product: str | None = Query(None, max_length=32), timeframe: str = Query("seasonal", max_length=16), as_of: str | None = Query(None, max_length=40)):
    return JSONResponse(_state(product, timeframe, as_of))


@app.get("/api/health")
def health():
    conn = _ro()
    try:
        k = kb_ingest.summary(conn, int(time.time()))
        rows = conn.execute("SELECT COUNT(*) FROM pit_market_data").fetchone()[0]
    finally:
        conn.close()
    return {"ok": True, "service": "markets_hub", "read_only": True, "schema": me.SCHEMA_VERSION, "pit_rows": rows, "knowledge_nodes": k["nodes"]}


@app.get("/api/knowledge-graph")
def knowledge_graph(limit: int = Query(300, ge=1, le=600), as_of: str | None = Query(None, max_length=40), domain: str | None = Query(None, max_length=32)):
    cutoff = _cutoff(as_of)
    conn = _ro()
    try:
        return {"as_of": cutoff, **kb_ingest.graph(conn, kb_ingest.epoch(cutoff), limit, domain)}
    finally:
        conn.close()


@app.get("/api/knowledge-node/{node_id}")
def knowledge_node(node_id: str, as_of: str | None = Query(None, max_length=40)):
    """One knowledge object: provenance, PIT timestamps, edges, verdict, source payload metadata (never the archive path)."""
    if len(node_id) > 64 or not all(ch.isalnum() or ch == "_" for ch in node_id):
        raise HTTPException(status_code=422, detail="bad node id")
    cutoff = _cutoff(as_of)
    conn = _ro()
    try:
        n = kb_ingest.node_detail(conn, node_id, kb_ingest.epoch(cutoff))
    finally:
        conn.close()
    if not n:
        raise HTTPException(status_code=404, detail="no such knowledge object at this cutoff")
    return {"as_of": cutoff, "node": n}


@app.get("/api/agents/activity")
def agents_activity(limit: int = Query(20, ge=1, le=100)):
    """Read-only view of the research agents: runs, message bus, local model calls and finding verdicts."""
    conn = _ro()
    try:
        return kb_ingest.agent_activity(conn, limit)
    finally:
        conn.close()


@app.get("/knowledge")
def knowledge_page():
    return FileResponse(WEB_DIR / "knowledge.html", headers={"Cache-Control": "no-cache"})


class ChatReq(BaseModel):
    message: str = Field(min_length=2, max_length=800)
    as_of: str | None = Field(default=None, max_length=40)
    context: dict | None = None            # click-to-ask: {"metric": explain id, "agent": agent id}; resolved server-side, never trusted as facts


_CHAT_TIMES: deque = deque()
CHAT_PER_MINUTE = 20


def _chat_events(req: ChatReq):
    cutoff = _cutoff(req.as_of)
    now = time.time()
    while _CHAT_TIMES and now - _CHAT_TIMES[0] > 60:
        _CHAT_TIMES.popleft()
    if len(_CHAT_TIMES) >= CHAT_PER_MINUTE:
        raise HTTPException(status_code=429, detail="chat rate limit reached; try again in a minute")
    _CHAT_TIMES.append(now)
    ctx = None
    if req.context:
        ctx = {"metric": str(req.context.get("metric") or "")[:64], "agent": str(req.context.get("agent") or "")[:96]}
    kb = _ro()
    lit = None
    if os.path.isfile(literature_kb.DEFAULT_DB):
        lit = sqlite3.connect(f"file:{literature_kb.DEFAULT_DB}?mode=ro", uri=True)
    model_on = os.environ.get("HH_CHAT_MODEL", "on") != "off"

    def gen():
        try:
            for ev, pl in chat_service.respond(req.message, cutoff, lambda product=None: _state(product, "seasonal", req.as_of), kb, lit, kb_ingest.embed,
                                               chat_service.ollama_stream if model_on else None, ctx):
                yield ev, pl
        finally:
            kb.close()
            if lit is not None:
                lit.close()
    return gen()


@app.post("/api/chat/stream")
def chat_stream(req: ChatReq):
    """Server-sent events: status, context (facts, then cited nodes/documents), token*, final. The first event is sent before any retrieval or model work."""
    events = _chat_events(req)

    def sse():
        for ev, pl in events:
            yield f"event: {ev}\ndata: {json.dumps(pl, default=str)}\n\n"
    return StreamingResponse(sse(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/chat")
def chat(req: ChatReq):
    """The same pipeline without streaming: returns the final JSON (answer, cited_nodes, cited_documents, facts, verdict)."""
    final = None
    for ev, pl in _chat_events(req):
        if ev == "final":
            final = pl
    return final


class SearchReq(BaseModel):
    query: str = Field(min_length=2, max_length=200)
    as_of: str | None = Field(default=None, max_length=40)
    limit: int = Field(default=8, ge=1, le=20)


@app.post("/api/knowledge-search")
async def knowledge_search(req: SearchReq):
    """Semantic search restricted to nodes with available_epoch <= as_of. Embedding runs on local Ollama."""
    cutoff = _cutoff(req.as_of)
    q = " ".join(req.query.split())
    vec = _SEARCH_CACHE.get(q)
    if vec is None:
        now = time.time()
        while _SEARCH_TIMES and now - _SEARCH_TIMES[0] > 60:
            _SEARCH_TIMES.popleft()
        if len(_SEARCH_TIMES) >= SEARCH_PER_MINUTE:
            raise HTTPException(status_code=429, detail="search rate limit reached; try again in a minute")
        _SEARCH_TIMES.append(now)
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(kb_ingest.OLLAMA_EMB_URL, json={"model": kb_ingest.EMBED_MODEL, "prompt": q}, timeout=20.0)
                r.raise_for_status()
                vec = r.json()["embedding"]
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=503, detail="local embedding model unavailable")
        _SEARCH_CACHE[q] = vec
        if len(_SEARCH_CACHE) > 256:
            _SEARCH_CACHE.popitem(last=False)
    conn = _ro()
    try:
        return {"as_of": cutoff, "query": q, "results": kb_ingest.search(conn, vec, kb_ingest.epoch(cutoff), req.limit),
                "note": "Similarity is a retrieval aid, not evidence of causation."}
    finally:
        conn.close()


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/static/{path:path}")
def static(path: str):
    target = (WEB_DIR / path).resolve()
    if WEB_DIR.resolve() not in target.parents or not target.is_file():
        raise HTTPException(status_code=404)
    # vendored libraries and basemap are immutable for a deploy; the app's own JS/CSS must revalidate on every load
    cc = "no-cache" if target.parent == WEB_DIR.resolve() else "public, max-age=3600"
    return FileResponse(target, headers={"Cache-Control": cc})


# --- Coordinated release version reporting ---
import json as _rel_json
from fastapi import Request as _RelRequest
from fastapi.responses import JSONResponse as _RelJSONResponse
from release.version import get_release_info as _get_release_info

@app.middleware("http")
async def _inject_markets_release_version(request: _RelRequest, call_next):
    resp = await call_next(request)
    if request.url.path in ("/health", "/api/health") and resp.status_code == 200 and "application/json" in resp.headers.get("content-type", ""):
        body = b"".join([chunk async for chunk in resp.body_iterator])
        try:
            data = _rel_json.loads(body.decode("utf-8"))
            if isinstance(data, dict):
                data.update(_get_release_info())
                return _RelJSONResponse(content=data, status_code=resp.status_code)
        except Exception:
            pass
    return resp
