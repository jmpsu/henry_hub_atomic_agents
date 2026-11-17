"""AD8: the alignment table is stored next to the indexed documents, linked, checked against its own rule, and its gaps are reported."""
import csv
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import emi_alignment as al  # noqa: E402
import emi_ingest as emi  # noqa: E402
import literature_kb as lk  # noqa: E402
from test_chat_g6 import emb  # noqa: E402

HEAD = ["file", "chunks", "best_kb_sim", "best_kb_node", "best_lit_sim", "best_lit_doc", "label"]


def _tsv(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(HEAD)
        w.writerows(rows)


@pytest.fixture()
def lib(tmp_path):
    root = tmp_path / "emi"
    root.mkdir()
    (root / "a.md").write_text("# Ethane\n\nEthane rejection happens when the frac spread is negative and ethane stays in the gas stream for sale.\n")
    (root / "b.md").write_text("# Storage\n\nWorking gas in storage is reported weekly by region and compared with the five year average for the same week.\n")
    (root / "data.csv").write_text("x,y\n1,2\n")
    db = str(tmp_path / "lit.db")
    emi.sync(db, emb, root, now="2026-11-01T00:00:00Z")
    c = sqlite3.connect(db)
    c.execute("INSERT INTO lit_docs(doc_id,title,kind,path,sha256,pages,words,available_timestamp,available_epoch) VALUES ('doc_x','Natural gas liquids paper','paper','/x.pdf','h',1,1,'2026-10-01T00:00:00Z',1)")
    c.commit()
    c.close()
    return db, tmp_path


def test_labels_are_stored_linked_and_the_gaps_are_reported(lib):
    db, d = lib
    tsv = d / "al.tsv"
    _tsv(tsv, [["a.md", 3, "0.70", "agent_finding: x", "0.81", "Natural gas liquids paper", "overlaps library"], ["b.md", 2, "0.60", "storage node", "0.66", "Other", "complements library"],
               ["data.csv", 1, "0.55", "n", "0.58", "Other", "complements library"], ["gone.md", 1, "0.60", "n", "0.60", "Other", "complements library"]])
    rep = al.apply(db, str(tsv), now="2026-11-02T00:00:00Z")
    assert rep["table_rows"] == 4 and rep["matched_to_indexed_documents"] == 2 and rep["overlaps_edges"] == 1
    assert rep["table_files_not_indexed"] == 2 and rep["not_indexed_by_extension"] == {".csv": 1, ".md": 1} and rep["indexed_documents_without_a_row"] == 0
    c = sqlite3.connect(db)
    a_id = c.execute("SELECT doc_id FROM lit_docs WHERE path='a.md'").fetchone()[0]
    assert al.alignment_of(c, a_id)["label"] == "overlaps library" and al.alignment_of(c, a_id)["best_lit_doc"] == "Natural gas liquids paper"
    assert c.execute("SELECT dst FROM lit_edges WHERE src=? AND type='overlaps'", (a_id,)).fetchone()[0] == "doc_x"
    b_id = c.execute("SELECT doc_id FROM lit_docs WHERE path='b.md'").fetchone()[0]
    assert al.alignment_of(c, b_id)["label"] == "complements library" and c.execute("SELECT COUNT(*) FROM lit_edges WHERE src=? AND type='overlaps'", (b_id,)).fetchone()[0] == 0
    assert al.apply(db, str(tsv))["overlaps_edges"] == 1 and sqlite3.connect(db).execute("SELECT COUNT(*) FROM lit_edges WHERE type='overlaps'").fetchone()[0] == 1       # idempotent


def test_the_tables_own_label_rule_is_checked_and_a_document_without_a_row_is_reported(lib):
    db, d = lib
    tsv = d / "al.tsv"
    _tsv(tsv, [["a.md", 3, "0.70", "n", "0.75", "Natural gas liquids paper", "overlaps library"], ["b.md", 2, "0.74", "n", "0.70", "x", "overlaps library"]])     # b: 0.74 < 0.75, so the rule says complements
    rep = al.apply(db, str(tsv))
    assert rep["rows_that_disagree_with_the_rule"] == 1 and rep["disagreeing_examples"] == ["b.md"]
    assert al.rule_label({"best_lit_sim": "0.5", "best_kb_sim": "0.76"}) == "overlaps library" and al.rule_label({"best_lit_sim": "0.5", "best_kb_sim": "0.6"}) == "complements library"
    (d / "emi" / "c.md").write_text("# New\n\nA brand new research note about liquefaction fees that is long enough to be indexed here.\n")
    emi.sync(db, emb, d / "emi", now="2026-11-03T00:00:00Z")
    assert al.apply(db, str(tsv))["indexed_documents_without_a_row"] == 1


def test_a_malformed_table_is_refused(tmp_path):
    bad = tmp_path / "bad.tsv"
    bad.write_text("file\tlabel\nx.md\toverlaps library\n")
    with pytest.raises(ValueError):
        al.load_tsv(str(bad))
    _tsv(tmp_path / "bad2.tsv", [["a.md", 1, "0.7", "n", "0.7", "d", "maybe"]])
    with pytest.raises(ValueError):
        al.load_tsv(str(tmp_path / "bad2.tsv"))
