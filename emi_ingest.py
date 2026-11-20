"""R1.3 / V1: index every research document in the energy_market_intelligence tree into the local literature store, with layout-aware chunking and
content-hash tracking so an updated file is re-indexed automatically.

Corpus = *.pdf, *.md, *.txt, *.odt under EMI_ROOT, minus tooling (.git, node_modules, virtualenvs, __pycache__, browser profiles, CSV data folders) and
dependency manifests (requirements*.txt, LICENSE*). `coverage()` reports indexed / corpus and names every file that is not indexed and why (V1).

Layout-aware chunking (nothing is re-flowed that carries structure):
  markdown   split at headings; a pipe table, a fenced code block and a $$ formula block are each kept whole (never split mid-table); every chunk starts with its
             heading trail so a table row is read under its section.
  pdf        `pdftotext -layout`; blocks whose lines are column-aligned (a table) are kept verbatim, prose blocks are re-flowed.
  odt        text paragraphs and table rows from content.xml, tables kept as pipe rows.
Point in time: a document's availability is the moment THIS process indexed it (file modification times are not trustworthy), so a retrieval at an earlier
cutoff never sees it. Change: a new sha256 for a known path is ingested as a NEW document and the older one is marked `superseded_epoch`, so a cutoff before the
change still retrieves the older text. A file that disappeared is superseded the same way.

Run:  python emi_ingest.py [--root DIR] [--db runtime/literature_kb.db] [--limit N]"""
from __future__ import annotations

import hashlib
import re
import sqlite3
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import literature_kb as lk  # noqa: E402

DEFAULT_ROOT = "/home/joey/Projects/energy_market_intelligence"
EXTS = {".pdf", ".md", ".txt", ".odt"}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "chrome-profile", "data", "sqlite3", ".pytest_cache"}
SKIP_NAME = re.compile(r"^(requirements.*\.txt|license.*|.*\.lock)$", re.I)
KIND = "research"
MAX_CHARS, MIN_CHARS, HARD_MAX = 1800, 40, 7000


def corpus(root: str | Path) -> list[Path]:
    root = Path(root)
    out = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in EXTS or SKIP_NAME.match(p.name):
            continue
        if any(part in SKIP_DIRS for part in p.relative_to(root).parts[:-1]):
            continue
        out.append(p)
    return out


# ----------------------------------------------------------------------------- readers
def read_odt(path: Path) -> str:
    ns = {"t": "urn:oasis:names:tc:opendocument:xmlns:text:1.0", "tb": "urn:oasis:names:tc:opendocument:xmlns:table:1.0"}
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("content.xml"))
    txt = lambda e: "".join(e.itertext()).strip()  # noqa: E731
    lines, body = [], root.find(".//{urn:oasis:names:tc:opendocument:xmlns:office:1.0}text")
    for el in (body if body is not None else []):
        tag = el.tag.split("}")[1]
        if tag == "h":
            lines += ["", "# " + txt(el), ""]
        elif tag == "p":
            lines += [txt(el), ""]
        elif tag == "table":
            for row in el.iter("{%s}table-row" % ns["tb"]):
                lines.append("| " + " | ".join(txt(c) for c in row.findall("tb:table-cell", ns)) + " |")
            lines.append("")
        elif tag == "list":
            lines += ["- " + txt(i) for i in el.iter("{%s}list-item" % ns["t"])] + [""]
    return "\n".join(lines)


def read_pdf(path: Path) -> tuple[str, int]:
    txt = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", str(path), "-"], capture_output=True, timeout=180, check=True).stdout.decode("utf-8", "replace")
    info = subprocess.run(["pdfinfo", str(path)], capture_output=True, timeout=30, check=True).stdout.decode("utf-8", "replace")
    m = re.search(r"^Pages:\s+(\d+)", info, re.M)
    return txt.replace("\x0c", "\n\n"), int(m.group(1)) if m else 0


def read(path: Path) -> tuple[str, int]:
    s = path.suffix.lower()
    if s == ".pdf":
        return read_pdf(path)
    if s == ".odt":
        return read_odt(path), 0
    return path.read_text(encoding="utf-8", errors="replace"), 0


# ----------------------------------------------------------------------------- layout-aware chunking
_HEAD = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


def _is_table_line(l: str) -> bool:
    return l.lstrip().startswith("|") or bool(re.search(r"\S {3,}\S.*\S {3,}\S", l))      # pipe row, or column-aligned text (pdftotext -layout)


def blocks(text: str) -> list[tuple[str, str]]:
    """[(kind, text)] with kind in heading|table|code|formula|prose. Tables, fenced code and $$ formulas are single blocks."""
    out, lines, i = [], text.replace("\r\n", "\n").split("\n"), 0
    prose: list[str] = []

    def flush():
        if prose and "".join(prose).strip():
            out.append(("prose", "\n".join(prose).strip()))
        prose.clear()
    while i < len(lines):
        l = lines[i]
        if l.strip().startswith("```"):
            flush()
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith("```"):
                j += 1
            out.append(("code", "\n".join(lines[i:j + 1])))
            i = j + 1
        elif l.strip().startswith("$$"):
            flush()
            j = i if (l.strip().count("$$") >= 2) else i + 1
            while j < len(lines) and l.strip().count("$$") < 2 and "$$" not in lines[j]:
                j += 1
            out.append(("formula", "\n".join(lines[i:j + 1])))
            i = j + 1
        elif _HEAD.match(l):
            flush()
            out.append(("heading", l.strip()))
            i += 1
        elif _is_table_line(l):
            flush()
            j = i
            while j < len(lines) and (_is_table_line(lines[j]) or (not lines[j].strip() and j + 1 < len(lines) and _is_table_line(lines[j + 1]) and j - i < 1)):
                j += 1
            out.append(("table", "\n".join(lines[i:j]).rstrip()))
            i = j
        elif not l.strip():
            flush()
            i += 1
        else:
            prose.append(l)
            i += 1
    flush()
    return out


def chunk_layout(text: str, max_chars: int = MAX_CHARS) -> list[str]:
    """Pack blocks into chunks <= max_chars under their heading trail. An indivisible block (table, code, formula) bigger than max_chars is its own chunk
    (split on a line boundary only above HARD_MAX)."""
    trail: list[tuple[int, str]] = []
    chunks: list[str] = []
    cur: list[str] = []
    cur_trail = ""

    def trail_str() -> str:
        return " > ".join(t for _, t in trail)

    def emit():
        nonlocal cur
        body = "\n\n".join(cur).strip()
        if len(body) >= MIN_CHARS or "$$" in body or "```" in body or "|" in body:
            chunks.append((f"[{cur_trail}]\n" if cur_trail else "") + body)
        cur = []
    for kind, b in blocks(text):
        if kind == "heading":
            emit()
            m = _HEAD.match(b)
            lvl = len(m.group(1))
            while trail and trail[-1][0] >= lvl:
                trail.pop()
            trail.append((lvl, m.group(2)))
            cur_trail = trail_str()
            continue
        if len(b) > max_chars:                                   # too big to pack: it becomes its own chunk(s); a table/code/formula is split only above HARD_MAX, on a line boundary
            if kind == "prose":                                  # an over-long paragraph: split on sentence-ish boundaries via the shared chunker
                import kb_ingest
                parts = kb_ingest.chunk_text(b, max_chars, 150)
            elif len(b) > HARD_MAX:
                ls, parts, acc = b.split("\n"), [], []
                for l in ls:
                    if sum(len(x) + 1 for x in acc) + len(l) > MAX_CHARS * 2 and acc:
                        parts.append("\n".join(acc)); acc = []
                    acc.append(l)
                parts.append("\n".join(acc))
            else:
                parts = [b]
            emit()
            for p in parts:
                if len(p.strip()) >= MIN_CHARS or kind != "prose":
                    chunks.append((f"[{cur_trail}]\n" if cur_trail else "") + p.strip())
            continue
        # a small table, code block or formula is packed with its neighbouring text (never dropped for being short, never split)
        if sum(len(x) for x in cur) + len(b) > max_chars and cur:
            emit()
        cur.append(b)
    emit()
    return chunks


# ----------------------------------------------------------------------------- store
def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _title(rel: str, text: str) -> str:
    m = re.search(r"^#\s+(.*\S)", text, re.M)
    return (m.group(1)[:140] if m else Path(rel).stem)


def ingest_file(conn, path: Path, rel: str, embedder, now: str) -> dict:
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    known = conn.execute("SELECT doc_id, path, superseded_epoch FROM lit_docs WHERE sha256=? AND superseded_epoch IS NULL", (sha,)).fetchone()
    if known:
        return {"status": "known", "doc_id": known[0], "chunks": 0}
    text, pages = read(path)
    chunks = chunk_layout(text)
    if not chunks:
        return {"status": "empty", "doc_id": None, "chunks": 0}
    doc_id, ep = "doc_" + hashlib.sha256(f"{sha}|{now}|{rel}".encode()).hexdigest()[:10], lk.epoch(now)
    rows = [(f"{doc_id}:{i:04d}", doc_id, i, c, ep, np.asarray(embedder(lk.DOC_PREFIX + c), dtype=np.float32).tobytes()) for i, c in enumerate(chunks)]   # embed first: a failure leaves nothing half-written
    conn.execute("INSERT INTO lit_docs(doc_id,title,kind,path,sha256,pages,words,available_timestamp,available_epoch) VALUES (?,?,?,?,?,?,?,?,?)",
                 (doc_id, _title(rel, text), KIND, rel, sha, pages, len(text.split()), now, ep))
    conn.executemany("INSERT INTO lit_chunks VALUES (?,?,?,?,?,?)", rows)
    prev = None
    for r in rows:
        conn.execute("INSERT OR IGNORE INTO lit_edges VALUES (?,?,?,?)", (r[0], doc_id, "part_of", None))
        if prev:
            conn.execute("INSERT OR IGNORE INTO lit_edges VALUES (?,?,?,?)", (prev, r[0], "next_chunk", None))
        prev = r[0]
    return {"status": "new", "doc_id": doc_id, "chunks": len(rows)}


def sync(db_path: str, embedder, root: str | Path = DEFAULT_ROOT, now: str | None = None, limit: int | None = None, rebuild_edges: bool = True) -> dict:
    """Index new files, re-index changed ones (older version superseded), supersede removed ones. Idempotent."""
    now = now or _now()
    root = Path(root)
    conn = sqlite3.connect(db_path, timeout=60)
    try:
        lk.ensure(conn)
        ep = lk.epoch(now)
        active = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT path, doc_id, sha256 FROM lit_docs WHERE kind=? AND superseded_epoch IS NULL", (KIND,))}
        active = {p: (d, s) for p, (d, s) in active.items()}
        counts = {"new": 0, "changed": 0, "unchanged": 0, "removed": 0, "empty": 0, "known_elsewhere": 0, "errors": [], "chunks": 0}
        seen = set()
        for n, p in enumerate(corpus(root)):
            if limit is not None and n >= limit:
                break
            rel = str(p.relative_to(root))
            seen.add(rel)
            sha = hashlib.sha256(p.read_bytes()).hexdigest()
            if rel in active and active[rel][1] == sha:
                counts["unchanged"] += 1
                continue
            try:
                r = ingest_file(conn, p, rel, embedder, now)
            except Exception as e:  # noqa: BLE001
                counts["errors"].append({"file": rel, "error": f"{type(e).__name__}: {str(e)[:120]}"})
                continue
            if r["status"] == "new":
                counts["chunks"] += r["chunks"]
                if rel in active:
                    conn.execute("UPDATE lit_docs SET superseded_epoch=? WHERE doc_id=?", (ep, active[rel][0]))
                    counts["changed"] += 1
                else:
                    counts["new"] += 1
            elif r["status"] == "known":
                counts["known_elsewhere"] += 1                   # identical content already indexed under another path: one copy is enough
            else:
                counts["empty"] += 1
            conn.commit()
        if limit is None:
            for rel, (doc_id, _s) in active.items():
                if rel not in seen:
                    conn.execute("UPDATE lit_docs SET superseded_epoch=? WHERE doc_id=?", (ep, doc_id))
                    counts["removed"] += 1
        if rebuild_edges and (counts["new"] or counts["changed"]):
            counts["semantic_edges"] = lk.rebuild_semantic_edges(conn)
        import knowledge_roles
        counts["roles_tagged"] = knowledge_roles.tag_lit(conn, lk.BASE_DIR / "runtime" / "lng_params.json")      # R1.7
        conn.commit()
        return {**counts, **lk.stats(conn)}
    finally:
        conn.close()


def coverage(db_path: str, root: str | Path = DEFAULT_ROOT) -> dict:
    """V1: how many corpus files are represented by an active document (same content hash), and why each missing file is missing."""
    root = Path(root)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        active_sha = {r[0] for r in conn.execute("SELECT sha256 FROM lit_docs WHERE superseded_epoch IS NULL")}
        paths = {r[0]: r[1] for r in conn.execute("SELECT path, sha256 FROM lit_docs WHERE superseded_epoch IS NULL")}
    finally:
        conn.close()
    files, missing = corpus(root), []
    for p in files:
        sha = hashlib.sha256(p.read_bytes()).hexdigest()
        if sha in active_sha:
            continue
        txt = ""
        try:
            txt = read(p)[0]
        except Exception as e:  # noqa: BLE001
            missing.append({"file": str(p.relative_to(root)), "reason": f"unreadable: {type(e).__name__}"})
            continue
        why = "no chunk of at least %d characters (empty or too short)" % MIN_CHARS if not chunk_layout(txt) else \
              ("stale: file changed since the last sync" if str(p.relative_to(root)) in paths else "not indexed yet")
        missing.append({"file": str(p.relative_to(root)), "reason": why})
    n = len(files)
    return {"corpus_files": n, "indexed": n - len(missing), "coverage_pct": round(100.0 * (n - len(missing)) / n, 2) if n else 100.0, "missing": missing}


if __name__ == "__main__":
    import argparse
    import json

    import kb_ingest
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=DEFAULT_ROOT)
    ap.add_argument("--db", default=lk.DEFAULT_DB)
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    out = sync(a.db, kb_ingest.embed, a.root, limit=a.limit)
    out["coverage"] = {k: v for k, v in coverage(a.db, a.root).items() if k != "missing"}
    print(json.dumps(out, indent=2))
