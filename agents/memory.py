"""Shared research memory and agent message bus.

Memory = the knowledge library (kb_nodes/kb_edges in henry_hub_pit.db + the Chroma collection henry_hub_alpha_graph).
  search()          PIT-filtered semantic retrieval for any agent (embedding via the local Ollama model); when the embedding
                    model is unavailable it falls back to deterministic PIT keyword retrieval and says so (`retrieval`)
  add_finding()     persists a finding as a knowledge object with typed edges to the evidence it used (`evidence_for`),
                    deduplicated by content hash, embedded, mirrored into Chroma when a collection is given. If embedding
                    fails the node is stored without a vector and `backfill_embeddings()` completes it on a later run.
  findings()        earlier findings, so later runs build on what previous runs concluded
  set_status()      the current verdict on a finding (valid / rejected / superseded) after re-checking it with newer rules;
                    the finding text itself is never rewritten, so the history stays auditable
Bus = `agent_messages`: agents publish typed messages (pipeline_event, anomaly, incident, data_quality, finding,
repair_proposal) that other agents consume exactly once per consumer. This is how agents hand work to each other.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone

import numpy as np

import kb_ingest

FINDING_DOMAIN = "agent_finding"
FINDING_PROVENANCE = ("model_hypothesis", "extracted_estimate", "backtest_result")
KINDS = ("repair_proposal", "data_quality", "hypothesis", "evaluation", "memo", "anomaly", "diagnosis", "finding")   # series_key = agent_<agent>_<kind>


def ensure(conn: sqlite3.Connection) -> None:
    kb_ingest.ensure(conn)
    conn.execute("CREATE TABLE IF NOT EXISTS agent_messages(id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, sender TEXT, topic TEXT, "
                 "payload TEXT, ref TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS agent_message_reads(message_id INTEGER, consumer TEXT, at TEXT, PRIMARY KEY(message_id, consumer))")
    conn.execute("CREATE TABLE IF NOT EXISTS agent_runs(id INTEGER PRIMARY KEY AUTOINCREMENT, agent TEXT, started TEXT, finished TEXT, as_of TEXT, "
                 "ok INTEGER, summary TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS finding_status(node_id TEXT PRIMARY KEY, status TEXT, reason TEXT, checked_at TEXT, checker TEXT)")


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ----------------------------------------------------------------------------- bus
def publish(conn, sender: str, topic: str, payload: dict, ref: str = "") -> int:
    cur = conn.execute("INSERT INTO agent_messages(at,sender,topic,payload,ref) VALUES (?,?,?,?,?)",
                       (now(), sender, topic, json.dumps(payload, sort_keys=True, default=str), ref))
    conn.commit()
    return cur.lastrowid


def consume(conn, consumer: str, topics: list, limit: int = 50) -> list:
    """Unread messages on these topics for this consumer, oldest first; marks them read."""
    q = ("SELECT id, at, sender, topic, payload, ref FROM agent_messages m WHERE topic IN (%s) AND NOT EXISTS "
         "(SELECT 1 FROM agent_message_reads r WHERE r.message_id=m.id AND r.consumer=?) ORDER BY id LIMIT ?") % ",".join("?" * len(topics))
    rows = conn.execute(q, (*topics, consumer, limit)).fetchall()
    for r in rows:
        conn.execute("INSERT OR IGNORE INTO agent_message_reads VALUES (?,?,?)", (r[0], consumer, now()))
    conn.commit()
    return [{"id": r[0], "at": r[1], "sender": r[2], "topic": r[3], "payload": json.loads(r[4]), "ref": r[5]} for r in rows]


# ----------------------------------------------------------------------------- memory
_WORD = re.compile(r"[a-z][a-z0-9_]{2,}")
_STOP = {"the", "and", "for", "with", "from", "that", "this", "are", "was", "were", "not", "but", "has", "have", "into", "over", "per"}


def keyword_search(conn, query: str, as_of: str, limit: int = 8) -> list:
    """Deterministic PIT fallback retrieval: term overlap between the query and title+document (available_epoch <= as_of)."""
    terms = {w for w in _WORD.findall(query.lower()) if w not in _STOP}
    if not terms:
        return []
    rows = conn.execute("SELECT id,domain,title,document,available_timestamp,source_id,raw_payload_hash,provenance FROM kb_nodes "
                        "WHERE available_epoch<=?", (kb_ingest.epoch(as_of),)).fetchall()
    scored = []
    for r in rows:
        words = set(_WORD.findall(f"{r[2]} {r[3]}".lower()))
        s = len(terms & words) / len(terms)
        if s > 0:
            scored.append((s, r))
    scored.sort(key=lambda x: x[1][4], reverse=True)        # newest first among equal scores
    scored.sort(key=lambda x: -x[0])
    return [{"id": r[0], "domain": r[1], "title": r[2], "document": r[3], "available_timestamp": r[4], "source_id": r[5],
             "raw_payload_hash": r[6], "provenance": r[7], "similarity": round(s, 4), "retrieval": "keyword_fallback"} for s, r in scored[:limit]]


def search(conn, llm, query: str, as_of: str, limit: int = 8, domains: list | None = None) -> list:
    """PIT semantic retrieval; deterministic keyword retrieval if the embedding model is unavailable."""
    try:
        vec = llm.embed(query)
        hits = kb_ingest.search(conn, vec, kb_ingest.epoch(as_of), limit * 4 if domains else limit)
        for h in hits:
            h["retrieval"] = "semantic"
    except Exception:  # noqa: BLE001
        hits = keyword_search(conn, query, as_of, limit * 4 if domains else limit)
    if domains:
        hits = [h for h in hits if h["domain"] in domains][:limit]
    assert all(kb_ingest.epoch(h["available_timestamp"]) <= kb_ingest.epoch(as_of) for h in hits), "LOOK-AHEAD in knowledge retrieval"
    return hits


def findings(conn, as_of: str, limit: int = 20, kinds: tuple | None = None, valid_only: bool = False) -> list:
    """Earlier findings available at as_of, newest first. valid_only drops findings whose latest status is rejected/superseded."""
    q = ("SELECT n.id, n.title, n.document, n.available_timestamp, n.provenance, n.series_key, s.status FROM kb_nodes n "
         "LEFT JOIN finding_status s ON s.node_id=n.id WHERE n.domain=? AND n.available_epoch<=?")
    args: list = [FINDING_DOMAIN, kb_ingest.epoch(as_of)]
    if valid_only:
        q += " AND COALESCE(s.status,'valid') NOT IN ('rejected','superseded')"
    rows = conn.execute(q + " ORDER BY n.available_epoch DESC, n.created DESC", args).fetchall()
    out = [{"id": r[0], "title": r[1], "document": r[2], "available_timestamp": r[3], "provenance": r[4], "series_key": r[5],
            "kind": next((k for k in KINDS if r[5].endswith("_" + k)), r[5].rsplit("_", 1)[-1]), "status": r[6] or "unchecked"} for r in rows]
    if kinds:
        out = [f for f in out if any(f["series_key"].endswith("_" + k) for k in kinds)]
    return out[:limit]


def _evidence_time(conn, ids) -> str | None:
    if not ids:
        return None
    r = conn.execute("SELECT MAX(available_timestamp) FROM kb_nodes WHERE id IN (%s)" % ",".join("?" * len(ids)), list(ids)).fetchone()
    return r[0] if r else None


def add_finding(conn, llm, agent: str, title: str, body: str, as_of: str, evidence_ids: list, provenance: str = "model_hypothesis",
                kind: str = "finding", collection=None, meta: dict | None = None) -> dict:
    """Persist a finding. available_timestamp = as_of, and never earlier than the newest evidence it cites (a finding cannot be
    known before the evidence it is built on). Returns {"id", "new", "evidence_linked", "embedded"}; an identical finding
    (same agent+kind+body) is not stored twice."""
    if provenance not in FINDING_PROVENANCE:
        raise ValueError("bad provenance for a finding")
    key = hashlib.sha256(f"{agent}|{kind}|{body}".encode()).hexdigest()
    nid = "kb_finding_" + key[:12]
    if conn.execute("SELECT 1 FROM kb_nodes WHERE id=?", (nid,)).fetchone():
        return {"id": nid, "new": False, "evidence_linked": 0, "embedded": True}
    known = sorted({r[0] for r in conn.execute("SELECT id FROM kb_nodes WHERE id IN (%s)" % ",".join("?" * len(evidence_ids)), list(evidence_ids))}
                   if evidence_ids else set())
    ev_t = _evidence_time(conn, known)
    avail = max(as_of, ev_t) if ev_t else as_of
    try:
        vec = np.asarray(llm.embed(f"{title}. {body}"), dtype=np.float32)
    except Exception:  # noqa: BLE001  stored without a vector; backfill_embeddings() completes it later
        vec = None
    conn.execute("INSERT INTO kb_nodes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (nid, FINDING_DOMAIN, f"agent_{agent}_{kind}", avail[:10], title[:200], body, f"agent:{agent}", (meta or {}).get("agent_ids", ""),
                  avail, kb_ingest.epoch(avail), avail, (meta or {}).get("raw_payload_hash", ""), provenance, key, now(),
                  None if vec is None else vec.tobytes()))
    for e in known:
        conn.execute("INSERT OR IGNORE INTO kb_edges VALUES (?,?,?,?)", (e, nid, "evidence_for", None))
    conn.commit()
    if collection is not None and vec is not None:
        _mirror(collection, nid, vec, f"{title}. {body}", agent, kind, avail, provenance, known)
    return {"id": nid, "new": True, "evidence_linked": len(known), "embedded": vec is not None}


def _mirror(collection, nid, vec, doc, agent, kind, avail, provenance, linked):
    collection.upsert(ids=[nid], embeddings=[np.asarray(vec, dtype=np.float32).tolist()], documents=[doc],
                      metadatas=[{"domain": FINDING_DOMAIN, "agent": agent, "kind": kind, "available_timestamp": avail,
                                  "available_epoch": kb_ingest.epoch(avail), "provenance": provenance,
                                  "linked_nodes": ",".join(sorted(linked)) or "root"}])


def backfill_embeddings(conn, llm, collection=None, limit: int = 50) -> int:
    """Embed findings that were stored while the embedding model was unavailable."""
    rows = conn.execute("SELECT id, title, document, series_key, available_timestamp, provenance FROM kb_nodes WHERE domain=? AND embedding IS NULL LIMIT ?",
                        (FINDING_DOMAIN, limit)).fetchall()
    done = 0
    for nid, title, doc, sk, avail, prov in rows:
        try:
            vec = np.asarray(llm.embed(f"{title}. {doc}"), dtype=np.float32)
        except Exception:  # noqa: BLE001
            break
        conn.execute("UPDATE kb_nodes SET embedding=? WHERE id=?", (vec.tobytes(), nid))
        if collection is not None:
            linked = [r[0] for r in conn.execute("SELECT src FROM kb_edges WHERE dst=? AND type='evidence_for'", (nid,))]
            agent, kind = sk[len("agent_"):].rsplit("_", 1) if sk.startswith("agent_") else (sk, "finding")
            _mirror(collection, nid, vec, f"{title}. {doc}", agent, kind, avail, prov, linked)
        done += 1
    conn.commit()
    return done


def link(conn, src: str, dst: str, edge_type: str) -> None:
    conn.execute("INSERT OR IGNORE INTO kb_edges VALUES (?,?,?,?)", (src, dst, edge_type, None))
    conn.commit()


def set_status(conn, node_id: str, status: str, reason: str, checker: str) -> None:
    if status not in ("valid", "rejected", "superseded", "evaluated"):
        raise ValueError(status)
    conn.execute("INSERT OR REPLACE INTO finding_status VALUES (?,?,?,?,?)", (node_id, status, reason[:500], now(), checker))
    conn.commit()


def run_record(conn, agent: str, started: str, as_of: str, ok: bool, summary: dict) -> None:
    conn.execute("INSERT INTO agent_runs(agent,started,finished,as_of,ok,summary) VALUES (?,?,?,?,?,?)",
                 (agent, started, now(), as_of, int(ok), json.dumps(summary, default=str)[:4000]))
    conn.commit()
