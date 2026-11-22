from __future__ import annotations
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
os.environ["NOTIFY"] = "0"

from llama_index.core.embeddings.mock_embed_model import MockEmbedding
from llama_index.core.llms.mock import MockLLM
from llama_index.core.schema import NodeWithScore

from agents import retrieval_hub as rh

TRIPLETS = [("Henry Hub", "quoted_in", "eia henry hub spot"),
            ("Henry Hub", "located", "us golf coast"),
            ("Henry Hub", "sensitive_to", "weather regimes"),
            ("Mont Belvieu", "exports", "natural gas")]


def _triplets(text):
    low = text.lower()
    if "henry hub" in low:
        return [t for t in TRIPLETS if "henry hub" in t[0].lower()]
    return [TRIPLETS[-1]]


def make_hub(storage_dir, **kwargs):
    class StubLLM(MockLLM):
        def predict(self, prompt, **kwargs):
            return "KEYWORDS: " + str(kwargs.get("question") or kwargs.get("query_str") or "")

    base = dict(storage_dir=storage_dir, llm=StubLLM(max_tokens=32), embed_model=MockEmbedding(embed_dim=8),
                kg_triplet_extract_fn=_triplets)
    base.update(kwargs)
    return rh.RetrievalHub(**base)


class ReverseReranker:
    def postprocess_nodes(self, nodes, query_bundle):
        ranked = list(reversed(nodes))
        return [NodeWithScore(node=n.node, score=float(len(ranked) - i)) for i, n in enumerate(ranked)]


class EmptyReranker:
    def postprocess_nodes(self, nodes, query_bundle):
        return []


def _ingest(hub):
    hub.ingest_texts(["Henry Hub cash price strengthened on Gulf Coast demand.",
                      "Henry Hub weather risk and power burn support winter prices.",
                      "Mont Belvieu NGL fractionation economics and propane exports."],
                     source_kind="article")


def test_default_search_path_is_unchanged(tmp_path):
    hub = make_hub(tmp_path / "hub")
    _ingest(hub)
    hits = hub.search("Henry Hub", limit=3)
    assert len(hits) > 1
    assert all("rerank_score" not in h for h in hits)


def test_opt_in_rerank_reorders_and_scores(tmp_path):
    hub = make_hub(tmp_path / "hub")
    _ingest(hub)
    candidates = [h["id"] for h in hub.search("Henry Hub", limit=20) if h["available_timestamp"]]
    reranked = hub.search("Henry Hub", limit=3, rerank=True, reranker=ReverseReranker())
    reranked_stable = [h["id"] for h in reranked if h["available_timestamp"]]
    expected = list(reversed(candidates))
    positions = [expected.index(hit_id) for hit_id in reranked_stable]
    assert positions == sorted(positions)
    assert [h["rerank_score"] for h in reranked] == sorted((h["rerank_score"] for h in reranked), reverse=True)
    assert all(isinstance(h["rerank_score"], float) for h in reranked)


def test_empty_rerank_falls_back_to_pit_hits(tmp_path):
    hub = make_hub(tmp_path / "hub")
    _ingest(hub)
    original = [h["id"] for h in hub.search("Henry Hub", limit=3)]
    fallback = hub.search("Henry Hub", limit=3, rerank=True, reranker=EmptyReranker())
    assert [h["id"] for h in fallback] == original


def test_pit_filter_runs_before_rerank(tmp_path):
    hub = make_hub(tmp_path / "hub")
    hub.ingest_texts(["Future Henry Hub report."], source_kind="article", available_timestamp="2030-01-01T00:00:00Z")
    hub.ingest_texts(["Current Henry Hub report."], source_kind="article", available_timestamp="2026-01-01T00:00:00Z")
    all_hits = hub.search("Henry Hub", limit=8)
    future_ids = {h["id"] for h in all_hits if str(h["available_timestamp"]).startswith("2030")}
    assert future_ids
    reranked = hub.search("Henry Hub", as_of="2027-01-01T00:00:00Z", limit=2, rerank=True, reranker=ReverseReranker())
    assert not future_ids.intersection({h["id"] for h in reranked})


def test_kg_context_and_hybrid_combo_mode(tmp_path):
    hub = make_hub(tmp_path / "hub", combo_kg_mode="hybrid")
    _ingest(hub)
    ctx = hub.kg_context("Henry Hub weather")
    assert "entities:" in ctx and "Henry Hub" in ctx and "relationships:" in ctx
    assert hub.search("Henry Hub", engine_type="combo", limit=3)
    try:
        make_hub(tmp_path / "bad", combo_kg_mode="nope")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid combo_kg_mode accepted")
