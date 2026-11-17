"""Literature knowledge graph (proof of concept): research papers and news PDFs as chunked, embedded, PIT-stamped source documents.

Deliberately a SEPARATE SQLite file (default runtime/literature_kb.db). It never reads or writes henry_hub_pit.db and never adds nodes to
kb_nodes, so literature cannot be mistaken for measured market data by the existing agents or the public service.

Tables
  lit_docs    one row per source PDF: sha256, kind ('paper' | 'news'), pages/words, available_timestamp (= when THIS system ingested it)
  lit_chunks  chunk text + float32 embedding; chunking is kb_ingest.chunk_text (unchanged)
  lit_edges   part_of (chunk -> doc) and next_chunk (chunk -> following chunk) are structural facts;
              semantic_neighbor (chunk -> most similar chunk of ANOTHER doc) is a retrieval aid only, NOT evidence of a relationship.
PIT: search() only returns chunks with available_epoch <= as_of. A paper's own publication date is not asserted; its availability is the
ingest time, the earliest moment this system could have used it.
Provenance of every row is 'source_document' (text as published), never 'measured'.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

import kb_ingest

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB = str(BASE_DIR / "runtime" / "literature_kb.db")
DOC_PREFIX, QUERY_PREFIX = "search_document: ", "search_query: "   # nomic-embed-text task prefixes


def ensure(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS lit_docs(doc_id TEXT PRIMARY KEY, title TEXT, kind TEXT, path TEXT, sha256 TEXT UNIQUE, pages INTEGER, words INTEGER,
        available_timestamp TEXT, available_epoch INTEGER, provenance TEXT DEFAULT 'source_document');
    CREATE TABLE IF NOT EXISTS lit_chunks(chunk_id TEXT PRIMARY KEY, doc_id TEXT, ord INTEGER, text TEXT, available_epoch INTEGER, embedding BLOB);
    CREATE TABLE IF NOT EXISTS lit_edges(src TEXT, dst TEXT, type TEXT, weight REAL, PRIMARY KEY(src, dst, type));
    CREATE INDEX IF NOT EXISTS lit_chunks_epoch ON lit_chunks(available_epoch);
    """)


def epoch(ts: str) -> int:
    return int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp())


def extract_text(path: str) -> tuple[str, int]:
    """(text, pages) via poppler's pdftotext (reading order, no layout) and pdfinfo. Raises on failure."""
    txt = subprocess.run(["pdftotext", "-enc", "UTF-8", path, "-"], capture_output=True, timeout=180, check=True).stdout.decode("utf-8", "replace")
    info = subprocess.run(["pdfinfo", path], capture_output=True, timeout=30, check=True).stdout.decode("utf-8", "replace")
    m = re.search(r"^Pages:\s+(\d+)", info, re.M)
    return txt, int(m.group(1)) if m else 0


def clean_text(raw: str) -> str:
    """Join hyphenated line breaks and wrapped lines so paragraphs (blank-line separated) are the chunking unit; drop page-number-only lines."""
    t = raw.replace("\x0c", "\n\n").replace("\r\n", "\n")
    t = re.sub(r"(\w)-\n(\w)", r"\1\2", t)
    t = "\n".join(l for l in t.split("\n") if not re.fullmatch(r"\s*\d{1,3}\s*", l))
    paras = [re.sub(r"\s*\n\s*", " ", p).strip() for p in re.split(r"\n\s*\n", t)]
    return "\n\n".join(p for p in paras if len(p) > 25)


def ingest_pdf(conn: sqlite3.Connection, path: str, kind: str, embedder, now: str | None = None) -> dict:
    """Idempotent by file sha256. Returns {'status': 'new'|'known', 'doc_id', 'chunks'}."""
    now = now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    sha = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    known = conn.execute("SELECT doc_id FROM lit_docs WHERE sha256=?", (sha,)).fetchone()
    if known:
        return {"status": "known", "doc_id": known[0], "chunks": conn.execute("SELECT COUNT(*) FROM lit_chunks WHERE doc_id=?", (known[0],)).fetchone()[0]}
    raw, pages = extract_text(path)
    text = clean_text(raw)
    chunks = kb_ingest.chunk_text(text)
    doc_id = "doc_" + sha[:10]
    ep = epoch(now)
    rows, prev = [], None
    for i, c in enumerate(chunks):
        vec = np.asarray(embedder(DOC_PREFIX + c), dtype=np.float32)       # embed everything first: a failure leaves no half-written document
        rows.append((f"{doc_id}:{i:04d}", doc_id, i, c, ep, vec.tobytes()))
    conn.execute("INSERT INTO lit_docs(doc_id,title,kind,path,sha256,pages,words,available_timestamp,available_epoch) VALUES (?,?,?,?,?,?,?,?,?)",
                 (doc_id, Path(path).stem, kind, path, sha, pages, len(text.split()), now, ep))
    conn.executemany("INSERT INTO lit_chunks VALUES (?,?,?,?,?,?)", rows)
    for r in rows:
        conn.execute("INSERT OR IGNORE INTO lit_edges VALUES (?,?,?,?)", (r[0], doc_id, "part_of", None))
        if prev:
            conn.execute("INSERT OR IGNORE INTO lit_edges VALUES (?,?,?,?)", (prev, r[0], "next_chunk", None))
        prev = r[0]
    conn.commit()
    return {"status": "new", "doc_id": doc_id, "chunks": len(rows)}


def rebuild_semantic_edges(conn: sqlite3.Connection, threshold: float = 0.72) -> int:
    """For each chunk, link to its single most similar chunk of ANOTHER document when cosine >= threshold. Similarity only."""
    conn.execute("DELETE FROM lit_edges WHERE type='semantic_neighbor'")
    rows = conn.execute("SELECT chunk_id, doc_id, embedding FROM lit_chunks WHERE embedding IS NOT NULL ORDER BY chunk_id").fetchall()
    if len(rows) < 2:
        return 0
    m = np.stack([np.frombuffer(r[2], dtype=np.float32) for r in rows])
    m = m / np.clip(np.linalg.norm(m, axis=1, keepdims=True), 1e-9, None)
    sim = m @ m.T
    docs = np.array([r[1] for r in rows])
    n = 0
    for i, r in enumerate(rows):
        s = np.where(docs != r[1], sim[i], -1.0)
        j = int(np.argmax(s))
        if s[j] >= threshold:
            conn.execute("INSERT OR IGNORE INTO lit_edges VALUES (?,?,?,?)", (r[0], rows[j][0], "semantic_neighbor", round(float(s[j]), 4)))
            n += 1
    conn.commit()
    return n


def search(conn: sqlite3.Connection, qvec, as_of_epoch: int, k: int = 5, kinds: tuple | None = None, per_doc: int | None = None) -> list[dict]:
    """Cosine top-k over chunks available at or before as_of. `per_doc` caps hits per document so one paper cannot fill the whole context."""
    sql = ("SELECT c.chunk_id,c.doc_id,c.ord,c.text,c.embedding,d.title,d.kind,d.available_timestamp FROM lit_chunks c JOIN lit_docs d USING(doc_id) "
           "WHERE c.available_epoch<=? AND c.embedding IS NOT NULL")
    args: list = [as_of_epoch]
    if kinds:
        sql += f" AND d.kind IN ({','.join('?' * len(kinds))})"
        args += list(kinds)
    rows = conn.execute(sql, args).fetchall()
    if not rows:
        return []
    q = np.asarray(qvec, dtype=np.float32)
    q = q / max(float(np.linalg.norm(q)), 1e-9)
    m = np.stack([np.frombuffer(r[4], dtype=np.float32) for r in rows])
    s = (m / np.clip(np.linalg.norm(m, axis=1, keepdims=True), 1e-9, None)) @ q
    out, per = [], {}
    for i in np.argsort(-s):
        r = rows[i]
        if per_doc and per.get(r[1], 0) >= per_doc:
            continue
        per[r[1]] = per.get(r[1], 0) + 1
        out.append({"chunk_id": r[0], "doc_id": r[1], "ord": r[2], "text": r[3], "title": r[5], "kind": r[6], "available_timestamp": r[7],
                    "similarity": round(float(s[i]), 4)})
        if len(out) >= k:
            break
    return out


def expand_adjacent(conn: sqlite3.Connection, hits: list[dict], as_of_epoch: int) -> list[dict]:
    """Add the following chunk (next_chunk edge) of each hit when it is not already present and was available at as_of. Structural, not semantic."""
    have = {h["chunk_id"] for h in hits}
    out = list(hits)
    for h in hits:
        r = conn.execute("SELECT c.chunk_id,c.doc_id,c.ord,c.text,d.title,d.kind,d.available_timestamp FROM lit_edges e JOIN lit_chunks c ON c.chunk_id=e.dst "
                         "JOIN lit_docs d ON d.doc_id=c.doc_id WHERE e.src=? AND e.type='next_chunk' AND c.available_epoch<=?", (h["chunk_id"], as_of_epoch)).fetchone()
        if r and r[0] not in have:
            have.add(r[0])
            out.append({"chunk_id": r[0], "doc_id": r[1], "ord": r[2], "text": r[3], "title": r[4], "kind": r[5], "available_timestamp": r[6],
                        "similarity": None, "via": f"next_chunk of {h['chunk_id']}"})
    return out


def stats(conn: sqlite3.Connection) -> dict:
    q = lambda s: conn.execute(s).fetchone()[0]  # noqa: E731
    return {"docs": q("SELECT COUNT(*) FROM lit_docs"), "chunks": q("SELECT COUNT(*) FROM lit_chunks"),
            "edges": dict(conn.execute("SELECT type, COUNT(*) FROM lit_edges GROUP BY type").fetchall())}


# ---- extractive evidence: verbatim, verifiable quotes with abstention (no generated prose from the literature) -----------------------------
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def split_sentences(text: str, min_chars: int = 70, max_chars: int = 420) -> list[str]:
    out = []
    pieces = [x for para in re.split(r"\n\s*\n", text) for x in _SENT.split(para)]     # never let a "sentence" span a paragraph break (title pages, affiliations)
    for s in pieces:
        s = s.strip()
        if not (min_chars <= len(s) <= max_chars) or re.match(r"(Figure|Table|Source)\b", s) or s[-1] not in ".!?":   # titles/author lines are unterminated
            continue
        if sum(ch.isalpha() for ch in s) / len(s) < 0.7:        # tables, equations and reference lists are mostly non-letters
            continue
        out.append(s)
    return out


def verify_quote(conn: sqlite3.Connection, chunk_id: str, quote: str) -> bool:
    """True only if `quote` is a verbatim substring of the stored chunk text (independent of how the quote was produced)."""
    r = conn.execute("SELECT text FROM lit_chunks WHERE chunk_id=?", (chunk_id,)).fetchone()
    return bool(r and quote in r[0])


def best_quotes(conn: sqlite3.Connection, embedder, query: str, as_of_epoch: int, kinds: tuple = ("paper",), k_chunks: int = 8, per_doc: int = 3,
                top_n: int = 2, min_chunk_sim: float = 0.70, min_sent_sim: float = 0.70) -> dict:
    """Sentence-level retrieval inside the top chunks. Returns {'quotes': [...], 'abstained': bool, 'candidates': [...]}; an empty quotes list means
    nothing in the library cleared BOTH thresholds, and the caller must show no literature rather than something loosely related."""
    qv = np.asarray(embedder(QUERY_PREFIX + query), dtype=np.float32)
    qv = qv / max(float(np.linalg.norm(qv)), 1e-9)
    hits = [h for h in search(conn, qv, as_of_epoch, k=k_chunks, kinds=kinds, per_doc=per_doc) if h["similarity"] >= min_chunk_sim]
    cands = []
    for h in hits:
        for s in split_sentences(h["text"]):
            v = np.asarray(embedder(DOC_PREFIX + s), dtype=np.float32)
            sim = float(v @ qv / max(float(np.linalg.norm(v)), 1e-9))
            cands.append({"quote": s, "similarity": round(sim, 4), "chunk_id": h["chunk_id"], "doc_id": h["doc_id"], "title": h["title"],
                          "available_timestamp": h["available_timestamp"], "chunk_similarity": h["similarity"]})
    cands.sort(key=lambda c: -c["similarity"])
    quotes, seen = [], set()
    for c in cands:
        if c["similarity"] >= min_sent_sim and c["doc_id"] not in seen and verify_quote(conn, c["chunk_id"], c["quote"]):
            seen.add(c["doc_id"])
            quotes.append(c)
        if len(quotes) >= top_n:
            break
    return {"quotes": quotes, "abstained": not quotes, "chunks_considered": len(hits), "candidates": cands[:5]}
