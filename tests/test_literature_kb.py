import os, sqlite3, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _scratch
import literature_kb as lk

PARA = "Natural gas prices rise in winter because heating demand draws down storage inventories across the market. "


def _fake_extract(texts):
    def f(path):
        return texts[Path(path).name], 3
    return f


def _emb(text):
    t = text.lower()                                   # 3-d toy space: [winter/storage, volatility, other]
    return [float("winter" in t or "storage" in t), float("volatil" in t), 0.1]


def _mk(tmp, name, body):
    p = Path(tmp) / name
    p.write_bytes(body.encode())
    return str(p)


def _setup(monkeypatch):
    tmp = _scratch.mkdtemp()
    a = _mk(tmp, "a.pdf", "A")
    b = _mk(tmp, "b.pdf", "B")
    texts = {"a.pdf": (PARA * 3 + "\n\n") * 4, "b.pdf": ("Volatility spikes when supply is tight and the supply curve is steep for the market. " * 3 + "\n\n") * 4}
    monkeypatch.setattr(lk, "extract_text", _fake_extract(texts))
    conn = sqlite3.connect(os.path.join(tmp, "lit.db"))
    lk.ensure(conn)
    return conn, a, b


def test_clean_text_joins_wrapped_lines_and_hyphens_and_drops_page_numbers():
    raw = "Natural gas stor-\nage rises in the\nautumn season each year.\n\n12\n\nAnother paragraph that is long enough to keep here.\x0cNext page paragraph with enough words to keep."
    out = lk.clean_text(raw)
    assert "storage rises in the autumn season" in out and "\n12\n" not in out and out.count("\n\n") == 2


def test_ingest_is_idempotent_and_builds_structural_edges(monkeypatch):
    conn, a, b = _setup(monkeypatch)
    r1 = lk.ingest_pdf(conn, a, "paper", _emb, now="2026-11-17T00:00:00Z")
    assert r1["status"] == "new" and r1["chunks"] >= 1
    assert lk.ingest_pdf(conn, a, "paper", _emb)["status"] == "known"
    s = lk.stats(conn)
    assert s["docs"] == 1 and s["edges"]["part_of"] == r1["chunks"] and s["edges"].get("next_chunk", 0) == r1["chunks"] - 1


def test_search_is_pit_filtered_and_ranks_by_similarity(monkeypatch):
    conn, a, b = _setup(monkeypatch)
    lk.ingest_pdf(conn, a, "paper", _emb, now="2026-11-17T00:00:00Z")
    lk.ingest_pdf(conn, b, "paper", _emb, now="2026-11-20T00:00:00Z")           # becomes available later
    q = _emb("volatility")
    early = lk.search(conn, q, lk.epoch("2026-11-18T00:00:00Z"), k=5)
    assert early and all(h["title"] == "a" for h in early)                      # paper b not yet available at that cutoff
    late = lk.search(conn, q, lk.epoch("2026-11-21T00:00:00Z"), k=1)
    assert late[0]["title"] == "b"
    assert lk.search(conn, q, lk.epoch("2026-11-16T00:00:00Z")) == []           # before anything was available


def test_per_doc_cap_and_kind_filter(monkeypatch):
    conn, a, b = _setup(monkeypatch)
    lk.ingest_pdf(conn, a, "paper", _emb, now="2026-11-17T00:00:00Z")
    lk.ingest_pdf(conn, b, "news", _emb, now="2026-11-17T00:00:00Z")
    t = lk.epoch("2026-11-18T00:00:00Z")
    capped = lk.search(conn, _emb("winter volatility"), t, k=10, per_doc=1)
    assert len(capped) == 2 and {h["title"] for h in capped} == {"a", "b"}
    assert {h["kind"] for h in lk.search(conn, _emb("x"), t, k=10, kinds=("news",))} == {"news"}


def test_expand_adjacent_adds_next_chunk_only_once_and_respects_pit(monkeypatch):
    conn, a, b = _setup(monkeypatch)
    lk.ingest_pdf(conn, a, "paper", _emb, now="2026-11-17T00:00:00Z")
    t = lk.epoch("2026-11-18T00:00:00Z")
    hits = lk.search(conn, _emb("winter"), t, k=1)
    ex = lk.expand_adjacent(conn, hits, t)
    assert len(ex) in (1, 2) and ex[0]["chunk_id"] == hits[0]["chunk_id"]
    if len(ex) == 2:
        assert ex[1]["ord"] == hits[0]["ord"] + 1 and ex[1]["via"].startswith("next_chunk")
    assert lk.expand_adjacent(conn, hits, lk.epoch("2026-11-16T00:00:00Z")) == hits   # nothing newly visible before availability


def test_semantic_edges_only_link_different_documents(monkeypatch):
    conn, a, b = _setup(monkeypatch)
    lk.ingest_pdf(conn, a, "paper", _emb, now="2026-11-17T00:00:00Z")
    lk.ingest_pdf(conn, b, "paper", _emb, now="2026-11-17T00:00:00Z")
    lk.rebuild_semantic_edges(conn, threshold=0.0)
    for s, d in conn.execute("SELECT src,dst FROM lit_edges WHERE type='semantic_neighbor'"):
        assert s.split(":")[0] != d.split(":")[0]


def test_does_not_touch_the_pit_database_path():
    assert lk.DEFAULT_DB.endswith(os.path.join("runtime", "literature_kb.db")) and "henry_hub_pit" not in lk.DEFAULT_DB


def test_split_sentences_filters_tables_and_short_fragments():
    t = ("Table 3. Results of the estimation for all contracts in the sample period shown here. Prices rise in winter because heating demand draws down storage across the whole market. "
         "Short one. 1.23 4.56 7.89 0.12 3.45 6.78 9.01 2.34 5.67 8.90 1.23 4.56 7.89 0.12 3.45 6.78 9.01 2.34.")
    out = lk.split_sentences(t)
    assert "Prices rise in winter because heating demand draws down storage across the whole market." in out
    assert not any("Short one" in x or "1.23 4.56" in x for x in out)        # fragments and numeric table rows are dropped (caption remnants can survive)


def test_best_quotes_are_verbatim_pit_safe_and_abstain_below_threshold(monkeypatch):
    conn, a, b = _setup(monkeypatch)
    lk.ingest_pdf(conn, a, "paper", _emb, now="2026-11-17T00:00:00Z")
    t = lk.epoch("2026-11-18T00:00:00Z")
    r = lk.best_quotes(conn, _emb, "winter storage", t, min_chunk_sim=0.5, min_sent_sim=0.5)
    assert r["quotes"] and not r["abstained"]
    for q in r["quotes"]:
        assert lk.verify_quote(conn, q["chunk_id"], q["quote"]) and q["quote"].startswith("Natural gas prices rise in winter")
    assert lk.best_quotes(conn, _emb, "volatility", t, min_chunk_sim=0.99, min_sent_sim=0.99)["abstained"]          # nothing close enough -> abstain
    assert lk.best_quotes(conn, _emb, "winter storage", lk.epoch("2026-11-16T00:00:00Z"))["abstained"]               # not yet available -> abstain
    assert not lk.verify_quote(conn, r["quotes"][0]["chunk_id"], "a sentence that is not in the chunk at all")


def test_split_sentences_drops_unterminated_titles_and_author_lines():
    t = ("Understanding World Commodity Prices Returns Volatility and Diversification of the Markets\n\n"
         "Prices rise in winter because heating demand draws down storage across the whole market.\n\nA study of the market by Some Author and Another Author, November 2024")
    assert lk.split_sentences(t) == ["Prices rise in winter because heating demand draws down storage across the whole market."]
