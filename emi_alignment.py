"""AD8: align the energy_market_intelligence tree with the knowledge library, using the alignment table produced earlier (`~/emi_alignment.tsv`).

The table has one row per EMI file: how close its chunks are to the closest library document and knowledge-graph node, and a label
`overlaps library` (the best similarity is about 0.75 or more: the content is already in the library) or `complements library` (it adds something new).
This module stores that verdict next to each indexed document so retrieval and the chat can say which sources duplicate the library and which extend it:

  lit_alignment(doc_id, path, label, best_kb_sim, best_kb_node, best_lit_sim, best_lit_doc, source_file, loaded_at)
  lit_edges 'overlaps'  doc -> the library document it overlaps (matched by title)

It also checks the table against itself (the label rule) and reports, never hides, what it cannot align: files in the table that are not indexed documents
(the table covers csv/yaml/py data and code files, which are not research documents) and indexed documents that the table does not mention.

Run:  python emi_alignment.py [--tsv ~/emi_alignment.tsv] [--db runtime/literature_kb.db]"""
from __future__ import annotations

import csv
import os
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import literature_kb as lk  # noqa: E402

DEFAULT_TSV = os.path.expanduser("~/emi_alignment.tsv")
THRESHOLD = 0.75
LABELS = ("overlaps library", "complements library")


def load_tsv(path: str = DEFAULT_TSV) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    need = {"file", "chunks", "best_kb_sim", "best_kb_node", "best_lit_sim", "best_lit_doc", "label"}
    if not rows or not need <= set(rows[0]):
        raise ValueError(f"unexpected alignment table columns: {list(rows[0]) if rows else 'empty'}")
    for r in rows:
        if r["label"] not in LABELS:
            raise ValueError(f"unknown label {r['label']!r} for {r['file']}")
    return rows


def rule_label(r: dict, threshold: float = THRESHOLD) -> str:
    """The label implied by the table's own numbers: overlaps when the best of the two similarities reaches the threshold."""
    return "overlaps library" if max(float(r["best_lit_sim"]), float(r["best_kb_sim"])) >= threshold else "complements library"


def ensure(conn: sqlite3.Connection) -> None:
    lk.ensure(conn)
    conn.execute("""CREATE TABLE IF NOT EXISTS lit_alignment(doc_id TEXT PRIMARY KEY, path TEXT, label TEXT NOT NULL, best_kb_sim REAL, best_kb_node TEXT, best_lit_sim REAL, best_lit_doc TEXT,
                    source_file TEXT, loaded_at TEXT)""")


def apply(db_path: str, tsv_path: str = DEFAULT_TSV, now: str | None = None) -> dict:
    now = now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = load_tsv(tsv_path)
    conn = sqlite3.connect(db_path, timeout=60)
    try:
        ensure(conn)
        docs = {r[1]: r[0] for r in conn.execute("SELECT doc_id, path FROM lit_docs WHERE kind='research' AND superseded_epoch IS NULL")}
        titles = {(r[1] or "").strip(): r[0] for r in conn.execute("SELECT doc_id, title FROM lit_docs")}
        conn.execute("DELETE FROM lit_edges WHERE type='overlaps'")
        matched, linked, unmatched = 0, 0, []
        for r in rows:
            did = docs.get(r["file"])
            if not did:
                unmatched.append(r["file"])
                continue
            conn.execute("INSERT OR REPLACE INTO lit_alignment VALUES (?,?,?,?,?,?,?,?,?)", (did, r["file"], r["label"], float(r["best_kb_sim"]), r["best_kb_node"], float(r["best_lit_sim"]), r["best_lit_doc"],
                                                                                         Path(tsv_path).name, now))
            matched += 1
            target = next((d for t, d in titles.items() if t and (t.startswith(r["best_lit_doc"].strip()) or r["best_lit_doc"].strip().startswith(t[:60]))), None)
            if r["label"] == "overlaps library" and target and target != did:
                conn.execute("INSERT OR IGNORE INTO lit_edges VALUES (?,?,?,?)", (did, target, "overlaps", float(r["best_lit_sim"])))
                linked += 1
        conn.commit()
        in_tsv = {r["file"] for r in rows}
        no_row = sorted(p for p in docs if p not in in_tsv)
        rule_miss = [r["file"] for r in rows if rule_label(r) != r["label"]]
        return {"table_rows": len(rows), "labels": dict(Counter(r["label"] for r in rows)), "matched_to_indexed_documents": matched, "overlaps_edges": linked,
                "table_files_not_indexed": len(unmatched), "not_indexed_by_extension": dict(Counter(os.path.splitext(f)[1] or "(none)" for f in unmatched)),
                "indexed_documents_without_a_row": len(no_row), "indexed_without_row_examples": no_row[:5], "label_rule_threshold": THRESHOLD, "rows_that_disagree_with_the_rule": len(rule_miss),
                "disagreeing_examples": rule_miss[:5]}
    finally:
        conn.close()


def alignment_of(conn: sqlite3.Connection, doc_id: str) -> dict | None:
    try:
        r = conn.execute("SELECT label, best_lit_sim, best_lit_doc, best_kb_sim, best_kb_node FROM lit_alignment WHERE doc_id=?", (doc_id,)).fetchone()
    except sqlite3.OperationalError:
        return None
    return {"label": r[0], "best_lit_sim": r[1], "best_lit_doc": r[2], "best_kb_sim": r[3], "best_kb_node": r[4]} if r else None


if __name__ == "__main__":
    import argparse
    import json
    ap = argparse.ArgumentParser()
    ap.add_argument("--tsv", default=DEFAULT_TSV)
    ap.add_argument("--db", default=lk.DEFAULT_DB)
    a = ap.parse_args()
    print(json.dumps(apply(a.db, a.tsv), indent=2))
