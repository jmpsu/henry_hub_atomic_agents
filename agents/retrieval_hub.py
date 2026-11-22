from __future__ import annotations
import os
import sys

# Configure NLTK to use a private user directory to prevent permission errors in CI
os.environ["NLTK_DATA"] = os.path.expanduser("~/nltk_data")
try:
    import nltk
    user_nltk_dir = os.path.expanduser("~/nltk_data")
    os.makedirs(user_nltk_dir, exist_ok=True)
    if user_nltk_dir not in nltk.data.path:
        nltk.data.path.insert(0, user_nltk_dir)
except Exception:
    pass

# Pre-populate LlamaIndex globals_helper stopwords
try:
    from llama_index.core.utils import globals_helper
    default_sw = {
        "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are", "aren't",
        "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but", "by",
        "can't", "cannot", "could", "couldn't", "did", "didn't", "do", "does", "doesn't", "doing", "don't",
        "down", "during", "each", "few", "for", "from", "further", "had", "hadn't", "has", "hasn't", "have",
        "haven't", "having", "he", "he'd", "he'll", "he's", "her", "here", "here's", "hers", "herself", "him",
        "himself", "his", "how", "how's", "i", "i'd", "i'll", "i'm", "i've", "if", "in", "into", "is",
        "isn't", "it", "it's", "its", "itself", "let's", "me", "more", "most", "mustn't", "my", "myself",
        "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other", "ought", "our", "ours",
        "ourselves", "out", "over", "own", "same", "shan't", "she", "she'd", "she'll", "she's", "should",
        "shouldn't", "so", "some", "such", "than", "that", "that's", "the", "their", "theirs", "them",
        "themselves", "then", "there", "there's", "these", "they", "they'd", "they'll", "they're", "they've",
        "this", "those", "through", "to", "too", "under", "until", "up", "very", "was", "wasn't", "we",
        "we'd", "we'll", "we're", "we've", "were", "weren't", "what", "what's", "when", "when's", "where",
        "where's", "which", "while", "who", "who's", "whom", "why", "why's", "with", "won't", "would",
        "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours", "yourself", "yourselves"
    }
    globals_helper._stopwords = default_sw
except Exception:
    pass

# Bypass NLTK stopwords permission and lookup errors in CI


"""LlamaIndex Multi-Engine Retrieval Hub (QUANT_HUB_SPEC section 2).

Ingests news articles, scientific journals and reports (text from URLs, files or in-memory strings) into a
LlamaIndex KnowledgeGraphIndex (entity triples via Ollama qwen2.5-coder:32b by default) and a VectorStoreIndex
(Ollama nomic-embed-text by default), and exposes a unified retrieval interface with six query-engine
modalities through the factory `get_query_engine(engine_type, **kwargs)`:

  1. "kg_vector"        (default) — KnowledgeGraphIndex.as_retriever(retriever_mode="embedding"):
                          knowledge-graph entity retrieval, vector-based
  2. "kg_keyword"                 — KnowledgeGraphIndex.as_retriever(retriever_mode="keyword"):
                          knowledge-graph entity retrieval, keyword-based
  3. "raw_vector"                 — VectorStoreIndex.as_retriever(): raw vector index retrieval
  4. "combo"                      — ComboRetriever: vector similarity + KG entity retrieval combined
  5. "kg_query_engine"            — KnowledgeGraphQueryEngine
  6. "kg_rag"                     — KnowledgeGraphRAGRetriever

`RetrievalHub.search(query, as_of, ...)` routes through one of the engines and returns PIT-filtered hits:
only nodes whose metadata `available_timestamp <= as_of` are returned (mirroring agents.memory.search).

Both indexes are held in a llama_index StorageContext pointed at `storage_dir`; `save()` persists it, and
`load(storage_dir, ...)` rebuilds the hub so persistent knowledge across runs is available to agents.
"""
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx
from llama_index.core import KnowledgeGraphIndex, VectorStoreIndex
from llama_index.core.base.base_retriever import BaseRetriever
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.core.indices.knowledge_graph.retrievers import KnowledgeGraphRAGRetriever
from llama_index.core.llms.mock import MockLLM
from llama_index.core.postprocessor import LLMRerank
from llama_index.core.query_engine.knowledge_graph_query_engine import KnowledgeGraphQueryEngine
from llama_index.core.graph_stores.simple import SimpleGraphStore
from llama_index.core.schema import Document, NodeWithScore, QueryBundle, TextNode
from llama_index.core.utils import globals_helper
from llama_index.core.storage.docstore.simple_docstore import SimpleDocumentStore
from llama_index.core.storage.index_store.simple_index_store import SimpleIndexStore
from llama_index.core.storage.storage_context import StorageContext
from llama_index.core.vector_stores.simple import SimpleVectorStore
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.llms.ollama import Ollama

from agents.llm import KG_CTX, KG_MODEL, KG_TOKENS

OLLAMA = os.environ.get("HH_OLLAMA_URL", "http://127.0.0.1:11434")
REASONING_MODEL = KG_MODEL
EMBED_MODEL = os.environ.get("HH_EMBED_MODEL", "nomic-embed-text")
RERANK_MODEL = os.environ.get("HH_RERANK_MODEL", KG_MODEL)
RERANK_BATCH_SIZE = int(os.environ.get("HH_RERANK_BATCH_SIZE", "10"))
COMBO_KG_MODES = ("embedding", "hybrid")

ENGINE_TYPES = ("kg_vector", "kg_keyword", "raw_vector", "combo", "kg_query_engine", "kg_rag")
DEFAULT_ENGINE = "kg_vector"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _epoch(ts: str) -> int:
    return int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp())


def _storage_context(storage_dir):
    """StorageContext for `storage_dir`: loads persisted stores when they exist, otherwise fresh ones."""
    if not storage_dir:
        return StorageContext.from_defaults(graph_store=LocalGraphStore())
    fresh = lambda: StorageContext.from_defaults(  # noqa: E731
        docstore=SimpleDocumentStore(), index_store=SimpleIndexStore(),
        vector_store=SimpleVectorStore(), graph_store=LocalGraphStore())
    if not Path(storage_dir).exists():
        return fresh()
    try:
        return StorageContext.from_defaults(
            docstore=SimpleDocumentStore.from_persist_dir(str(storage_dir)),
            index_store=SimpleIndexStore.from_persist_dir(str(storage_dir)),
            vector_store=SimpleVectorStore.from_persist_dir(str(storage_dir)),
            graph_store=LocalGraphStore())
    except FileNotFoundError:
        return fresh()


class LocalGraphStore(SimpleGraphStore):
    """SimpleGraphStore plus the get_schema/query surface that KnowledgeGraphQueryEngine (spec modality 5) calls.

    query() returns every stored triple as (subject, relation, object), so the query engine always has graph context."""

    def get_schema(self, refresh: bool = False) -> str:
        return "Local graph store (SimpleGraphStore): triples held as inserted; query returns all triples."

    def query(self, query: str, param_map=None):
        return [(subj, rel, obj) for subj, rels in self._data.graph_dict.items() for rel, obj in rels]


class _HashingEmbedding(BaseEmbedding):
    """Deterministic local embedding fallback when the Ollama embedding model is unavailable."""

    def _vec(self, text: str):
        import hashlib
        import numpy as np
        out = np.zeros(8, dtype=np.float32)
        for w in text.lower().split():
            h = int.from_bytes(hashlib.sha256(w.encode()).digest()[:4], "little")
            out[h % 8] += 1.0
        n = np.linalg.norm(out)
        return (out / n if n > 0 else out).tolist()

    def _get_query_embedding(self, query: str):
        return self._vec(query)

    def _get_text_embedding(self, text: str):
        return self._vec(text)


def _default_llm():
    try:
        return Ollama(model=KG_MODEL, base_url=OLLAMA, temperature=0, context_window=KG_CTX, request_timeout=300.0,
                      additional_kwargs={"num_predict": KG_TOKENS, "num_ctx": KG_CTX}, thinking=False)
    except Exception:  # noqa: BLE001
        return MockLLM(max_tokens=32)


def _default_embedder():
    try:
        return OllamaEmbedding(model_name=EMBED_MODEL, base_url=OLLAMA)
    except Exception:  # noqa: BLE001
        return _HashingEmbedding(embed_dim=8)


def _default_reranker():
    try:
        llm = Ollama(model=RERANK_MODEL, base_url=OLLAMA, temperature=0, context_window=KG_CTX, request_timeout=300.0,
                     additional_kwargs={"num_predict": KG_TOKENS, "num_ctx": KG_CTX}, thinking=False)
    except Exception:  # noqa: BLE001
        llm = MockLLM(max_tokens=32)
    return LLMRerank(llm=llm, choice_batch_size=RERANK_BATCH_SIZE, top_n=64)


def _default_triplet_fn(text: str) -> list:
    """Deterministic triplet extractor for when the LLM is unavailable (structured fallback)."""
    import re
    t = (text or "").strip()
    out = []
    for m in re.finditer(r"([A-Z][a-z0-9 ]{3,30})[:\-]?\s*(?:quoted|located|held|released|with|sells|buys|relates to)\s+([a-zA-Z0-9 ,'\-]{4,40})", t):
        out.append((m.group(1), m.group(2).strip(" .,'"), ""))
    if not out:
        for m in re.finditer(r"([A-Z][a-z0-9 ]{3,30})\s+(?:in|at|on|for)\s+([A-Za-z]{3,20}(?: [A-Za-z]{3,20})+)", t):
            out.append((m.group(1), "located", m.group(2)))
    return out[:10]


class ComboRetriever(BaseRetriever):
    """Spec modality 4: vector similarity + KG entity retrieval combined (deduplicated by node id)."""

    def __init__(self, vector_retriever: BaseRetriever, kg_retriever: BaseRetriever):
        super().__init__()
        self._vector_retriever, self._kg_retriever = vector_retriever, kg_retriever

    def _retrieve(self, query_bundle: QueryBundle):
        out, seen = [], set()
        for ns in (self._vector_retriever.retrieve(query_bundle), self._kg_retriever.retrieve(query_bundle)):
            for n in ns:
                if n.node.node_id not in seen:
                    seen.add(n.node.node_id)
                    out.append(n)
        return out


def _to_hits(nodes, limit: int = 8) -> list:
    out = []
    for n in nodes[:limit]:
        node = getattr(n, "node", n)
        meta = getattr(node, "metadata", None) or {}
        out.append({
            "id": node.node_id,
            "title": (meta.get("title") or node.get_content()[:90].replace("\n", " ").strip())[:120],
            "text": node.get_content()[:500],
            "source_kind": meta.get("source_kind", "document"),
            "available_timestamp": meta.get("available_timestamp"),
            "similarity": float(n.score) if getattr(n, "score", None) is not None else 0.0,
        })
    return out


class RetrievalHub:
    def __init__(self, storage_dir=None, llm=None, embed_model=None, kg_triplet_extract_fn=None, verbose=False,
                 combo_kg_mode=None, reranker=None):
        self.storage_dir = Path(storage_dir).resolve() if storage_dir else None
        self.storage_context = _storage_context(str(self.storage_dir) if self.storage_dir else None)
        self.llm = llm or _default_llm()
        self.embed_model = embed_model or _default_embedder()
        self._kg_triplet_extract_fn = kg_triplet_extract_fn or _default_triplet_fn
        self.combo_kg_mode = combo_kg_mode or os.environ.get("HH_COMBO_KG_MODE", COMBO_KG_MODES[0])
        if self.combo_kg_mode not in COMBO_KG_MODES:
            raise ValueError(f"unknown combo_kg_mode {self.combo_kg_mode!r}; choose from {list(COMBO_KG_MODES)}")
        self.reranker = reranker
        self.kg_index = KnowledgeGraphIndex(nodes=[], llm=self.llm, embed_model=self.embed_model,
                                            storage_context=self.storage_context, include_embeddings=True,
                                            kg_triplet_extract_fn=self._kg_triplet_extract_fn, verbose=verbose)
        self.vector_index = VectorStoreIndex(nodes=[], embed_model=self.embed_model, storage_context=self.storage_context)
        self.documents = []
        self._engines = {}

    # ---------------------------------------------------------------- ingestion
    def add_doc(self, doc: Document) -> Document:
        """Insert one document into the graph and the vector index (metadata drives PIT)."""
        self.documents.append(doc)
        self.kg_index.insert(doc)
        self.vector_index.insert(doc)
        return doc

    def ingest_texts(self, texts, source_kind: str = "article", available_timestamp: str | None = None, title_prefix: str = "") -> int:
        """Ingest news articles, scientific journals or reports given as text strings."""
        n = 0
        for t in texts or []:
            title = title_prefix + (t[:90].replace("\n", " ").strip() or source_kind)
            self.add_doc(Document(text=t, metadata={"source_kind": source_kind, "available_timestamp": available_timestamp or _now(),
                                                    "title": title[:160]}))
            n += 1
        return n

    def ingest_url(self, url: str, source_kind: str = "article", timeout: float = 30.0, available_timestamp: str | None = None) -> bool:
        """Ingest one URL (news article / journal / report) into the hub."""
        try:
            r = httpx.get(url, timeout=timeout)
            r.raise_for_status()
        except Exception:  # noqa: BLE001
            return False
        meta = {"source_kind": source_kind, "url": url, "available_timestamp": available_timestamp or _now()}
        self.documents.append(Document(text=r.text, metadata=meta))
        self.kg_index.insert(self.documents[-1])
        self.vector_index.insert(self.documents[-1])
        return True

    # ---------------------------------------------------------------- engines
    def get_query_engine(self, engine_type: str = DEFAULT_ENGINE, **kwargs):
        """Factory interface (spec). engine_type: one of ENGINE_TYPES; default "kg_vector"."""
        if engine_type not in ENGINE_TYPES:
            raise ValueError(f"unknown engine_type {engine_type!r}; choose from {list(ENGINE_TYPES)}")
        eng = self._engines.get(engine_type)
        if eng is None:
            if engine_type == "kg_vector":
                eng = self.kg_index.as_retriever(retriever_mode="embedding", **kwargs)
            elif engine_type == "kg_keyword":
                eng = self.kg_index.as_retriever(retriever_mode="keyword", **kwargs)
            elif engine_type == "raw_vector":
                eng = self.vector_index.as_retriever(**kwargs)
            elif engine_type == "combo":
                eng = ComboRetriever(self.vector_index.as_retriever(**kwargs),
                                     self.kg_index.as_retriever(retriever_mode=self.combo_kg_mode, **kwargs))
            elif engine_type == "kg_query_engine":
                eng = KnowledgeGraphQueryEngine(index=self.kg_index, storage_context=self.kg_index.storage_context, llm=self.llm, **kwargs)
            elif engine_type == "kg_rag":
                eng = KnowledgeGraphRAGRetriever(storage_context=self.kg_index.storage_context, llm=self.llm, **kwargs)
            self._engines[engine_type] = eng
        return eng

    def retrieve(self, engine_type: str, query: str, limit: int = 8) -> list:
        """Nodes for the engine, normalized (id/title/text/similarity/metadata).

        KnowledgeGraphQueryEngine (modality 5) is a query engine, not a retriever: use its query() there."""
        engine = self.get_query_engine(engine_type)
        qb = QueryBundle(query_str=query)
        try:
            nodes = engine.retrieve(qb)
        except NotImplementedError:
            resp = engine.query(qb)
            nodes = getattr(resp, "source_nodes", None) or []
        return _to_hits(nodes, limit)

    def kg_context(self, query: str, max_entities: int = 20, max_relationships: int = 30) -> str:
        """Deterministic entity/relationship context from stored triples (NexusRAG pattern)."""
        triples = list(self.storage_context.graph_store.query(query))
        if not triples:
            return ""
        stop = {str(w).lower() for w in (getattr(globals_helper, "stopwords", ()) or ())}
        terms = {t for t in re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{2,}", query or "") if t.lower() not in stop}
        def matches(value) -> bool:
            hay = str(value).lower().replace("-", " ").replace("_", " ")
            return any(t.lower() in hay for t in terms)
        rels = [(s, p, o) for s, p, o in triples if not terms or matches(s) or matches(p) or matches(o)] or triples
        entities = []
        for s, p, o in rels:
            for value in (s, p, o):
                key = str(value).strip()
                if key and key not in entities:
                    entities.append(key)
        lines = ["entities: " + ", ".join(entities[:max_entities]), "relationships:"]
        lines += [f"- {s} {p} {o}" for s, p, o in rels[:max_relationships]]
        return "\n".join(lines)

    def _rerank_hits(self, query: str, hits: list, reranker=None, prefetch: int = 20, min_score: float = 0.0) -> list:
        reranker = reranker or self.reranker or _default_reranker()
        candidates = hits[:max(prefetch, 1)]
        nodes = [NodeWithScore(node=TextNode(text=h.get("text", ""), id_=h["id"]), score=float(h.get("similarity", 0.0)))
                 for h in candidates]
        by_id = {h["id"]: h for h in candidates}
        scored, seen = [], set()
        for node in reranker.postprocess_nodes(nodes, QueryBundle(query_str=query)) or []:
            hit_id = node.node.node_id
            if hit_id in seen or hit_id not in by_id:
                continue
            hit = dict(by_id[hit_id])
            hit["rerank_score"] = float(getattr(node, "score", 0.0) or 0.0)
            seen.add(hit_id)
            if hit["rerank_score"] >= min_score:
                scored.append(hit)
        return scored or candidates[:3]

    def search(self, query: str, as_of: str | None = None, limit: int = 8, engine_type: str = DEFAULT_ENGINE,
               rerank: bool = False, prefetch: int = 20, min_score: float = 0.0, reranker=None) -> list:
        """PIT-filtered hits; optional opt-in rerank after PIT filtering (NexusRAG over-fetch/fallback pattern)."""
        hits = self.retrieve(engine_type, query, max(prefetch, limit) if rerank else limit)
        if as_of:
            as_of_epoch = _epoch(as_of)
            hits = [h for h in hits if h["available_timestamp"] and _epoch(h["available_timestamp"]) <= as_of_epoch]
        if rerank and hits:
            try:
                hits = self._rerank_hits(query, hits, reranker=reranker, prefetch=prefetch, min_score=min_score)
            except Exception:  # noqa: BLE001 - reranking is an enhancement, never a hard dependency
                pass
        return hits[:limit]

    # ---------------------------------------------------------------- persistence
    def save(self) -> bool:
        """Persist the indexes (graph triples + vector rows + documents) to storage_dir."""
        if not self.storage_dir:
            return False
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.storage_context.persist(persist_dir=str(self.storage_dir))
        return True

    @classmethod
    def load(cls, storage_dir, **kwargs) -> "RetrievalHub":
        """Rebuild a hub from a persisted storage dir (documents, graph triples, vectors)."""
        hub = cls(storage_dir=storage_dir, **kwargs)
        docs = list(hub.storage_context.docstore.docs.values())
        hub.kg_index = KnowledgeGraphIndex(nodes=docs, llm=hub.llm, embed_model=hub.embed_model, storage_context=hub.storage_context,
                                           include_embeddings=True, kg_triplet_extract_fn=hub._kg_triplet_extract_fn)
        hub.vector_index = VectorStoreIndex(nodes=docs, embed_model=hub.embed_model, storage_context=hub.storage_context)
        hub.documents = docs
        return hub
