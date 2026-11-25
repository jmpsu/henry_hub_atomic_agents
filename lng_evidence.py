"""LNG forward-price parameters sourced from the graphical vector knowledge library via local Ollama.

The forward-price arithmetic stays deterministic (markets_engine.lng_forward_curve). This module only decides WHERE each
parameter value comes from:

  1. Retrieve candidate sentences for the parameter from the literature library (literature_kb.best_quotes: embedding
     search with nomic-embed-text, verbatim-verified sentences only, abstains below the similarity thresholds).
   2. Ask the local coder model (agents.llm, qwen2.5-coder:32b) to read ONE verified sentence and return the number it states.
  3. Accept the number only if (a) the quote is still a verbatim substring of the stored chunk, (b) the number, or for a
     percentage the number x100, literally appears in that sentence, and (c) it lies inside the parameter's sanity band.
  4. Otherwise keep the labelled default assumption. A model output is never used without a quote that contains it.

It also retrieves knowledge-graph nodes (kb_nodes: pipeline notices, weather, storage, agent findings) relevant to US LNG
feedgas. Those are context shown next to the curve; they never change a number.

Run on the host where Ollama runs:  python lng_evidence.py   ->  writes runtime/lng_params.json
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import kb_ingest
import literature_kb
from agents.llm import CODER_MODEL

BASE_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = Path(os.environ.get("QH_RUNTIME_DIR", BASE_DIR / "runtime"))
PARAMS_FILE = RUNTIME_DIR / "lng_params.json"
PROMPT_VERSION = "lng_param_extract/1"

PARAMS = {
    "k_hh_multiplier": {
        "default": 1.15, "band": (1.05, 1.30), "unit": "x Henry Hub", "pct_ok": True,
        "query": "US LNG export contracts price feedgas at 115 percent of the Henry Hub price",
        "ask": "the multiplier applied to the Henry Hub gas price in US LNG sale contracts (115% means 1.15)"},
    "liquefaction_usd_mmbtu": {
        "default": 2.50, "band": (1.50, 4.00), "unit": "USD/MMBtu", "pct_ok": False,
        "query": "US LNG liquefaction tolling fee in dollars per MMBtu",
        "ask": "the fixed liquefaction (tolling) fee in US dollars per MMBtu"},
}
CONTEXT_QUERIES = ["LNG feedgas pipeline force majeure or restriction",
                   "LNG export terminal outage or maintenance",
                   "colder than normal weather raising Henry Hub demand"]
_NUM = re.compile(r"\d+(?:\.\d+)?")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def numbers_in(text: str) -> list[float]:
    return [float(n) for n in _NUM.findall(text.replace(",", ""))]


def grounded(value: float, quote: str, pct_ok: bool) -> bool:
    """True if `value` (or value*100 for a percentage-style parameter) literally appears in the quote."""
    have = numbers_in(quote)
    want = [value] + ([value * 100] if pct_ok else [])
    return any(abs(h - w) < 1e-6 for h in have for w in want)


def accept(value, quote: str, spec: dict) -> str | None:
    """None if the extracted value is acceptable, else the reason it was rejected."""
    if value is None:
        return "model found no value in the sentence"
    if not isinstance(value, (int, float)):
        return "value is not a number"
    lo, hi = spec["band"]
    if not lo <= value <= hi:
        return f"{value} outside sanity band {lo}-{hi}"
    if not grounded(float(value), quote, spec["pct_ok"]):
        return f"{value} does not appear in the quoted sentence"
    return None


def extract_param(name: str, spec: dict, lit_conn, llm, embedder, as_of_epoch: int) -> dict:
    default = {"name": name, "value": spec["default"], "unit": spec["unit"], "source": "assumption",
               "reason": "no verified library sentence stated an acceptable value", "attempts": []}
    try:
        found = literature_kb.best_quotes(lit_conn, embedder, spec["query"], as_of_epoch, kinds=("paper", "news", "research"), top_n=3)
    except Exception as e:  # noqa: BLE001  (library DB missing or Ollama embedder down -> keep the assumption)
        return {**default, "reason": f"library/embedder unavailable: {type(e).__name__}"}
    if found["abstained"]:
        return {**default, "reason": "library abstained: no sentence cleared the similarity thresholds"}
    schema = {"type": "object", "properties": {"value": {"type": ["number", "null"]}}, "required": ["value"]}
    for q in found["quotes"]:
        if not any(spec["band"][0] <= n <= spec["band"][1] or (spec["pct_ok"] and spec["band"][0] <= n / 100 <= spec["band"][1])
                   for n in numbers_in(q["quote"])):
            default["attempts"].append({"chunk_id": q["chunk_id"], "rejected": "sentence has no number in the sanity band"})
            continue
        prompt = (f"Sentence: \"{q['quote']}\"\nReturn {spec['ask']} as stated in this sentence only. "
                  "If the sentence does not state it, return null. Do not use outside knowledge.")
        try:
            out = llm.json("extract", prompt, schema, version=PROMPT_VERSION)
        except Exception as e:  # noqa: BLE001
            default["attempts"].append({"chunk_id": q["chunk_id"], "rejected": f"model error: {type(e).__name__}"})
            continue
        why = accept(out.get("value"), q["quote"], spec)
        if why is None and not literature_kb.verify_quote(lit_conn, q["chunk_id"], q["quote"]):
            why = "quote no longer matches stored chunk"
        if why:
            default["attempts"].append({"chunk_id": q["chunk_id"], "rejected": why})
            continue
        return {"name": name, "value": float(out["value"]), "unit": spec["unit"], "source": "library",
                "quote": q["quote"], "chunk_id": q["chunk_id"], "doc_id": q["doc_id"], "title": q["title"],
                "similarity": q["similarity"], "doc_available_timestamp": q["available_timestamp"],
                "model": f"agents.llm extract ({CODER_MODEL})", "prompt_version": PROMPT_VERSION,
                "attempts": default["attempts"]}
    return default


def context_nodes(pit_conn, embedder, as_of_epoch: int, per_query: int = 4, min_sim: float = 0.55) -> list[dict]:
    seen, out = set(), []
    for q in CONTEXT_QUERIES:
        try:
            hits = kb_ingest.search(pit_conn, embedder(q), as_of_epoch, per_query)
        except Exception:  # noqa: BLE001
            continue
        for h in hits:
            if h["similarity"] >= min_sim and h["id"] not in seen:
                seen.add(h["id"])
                out.append({"query": q, "id": h["id"], "domain": h["domain"], "title": h["title"], "similarity": h["similarity"],
                            "available_timestamp": h["available_timestamp"], "source_id": h["source_id"]})
    return out


def refresh(pit_db: str, lit_db: str = literature_kb.DEFAULT_DB, out_path: Path = PARAMS_FILE, llm=None, embedder=None) -> dict:
    from agents.llm import LLM, status
    now = now_iso()
    ep = kb_ingest.epoch(now)
    embedder = embedder or kb_ingest.embed
    pit = sqlite3.connect(pit_db, timeout=30)
    lit = sqlite3.connect(lit_db, timeout=30) if os.path.isfile(lit_db) else sqlite3.connect(":memory:")
    try:
        llm = llm or LLM(pit, "Agent_LNG_Forward_Params", available=status().get("ok", False))
        params = {n: extract_param(n, s, lit, llm, embedder, ep) for n, s in PARAMS.items()}
        doc = {"generated_at": now, "available_timestamp": now, "params": params, "context": context_nodes(pit, embedder, ep)}
    finally:
        pit.close()
        lit.close()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=2))
    tmp.replace(out_path)
    return doc


def validated(doc: dict | None) -> dict | None:
    """Re-check every library-sourced parameter of a loaded params file against the O13-R rule before the engine uses it:
    value inside the sanity band AND the number (x100 for a percentage) literally present in the stored verbatim quote. A parameter that fails is
    dropped (the engine then uses the labelled default assumption and records why); nothing is repaired or guessed."""
    if not doc:
        return doc
    out, notes = {}, {}
    for name, p in (doc.get("params") or {}).items():
        spec = PARAMS.get(name)
        if not spec:
            continue
        if p.get("source") != "library":
            out[name] = p                      # a labelled default with the reason it was used
            continue
        why = accept(p.get("value"), p.get("quote") or "", spec)
        if why is None and not p.get("quote"):
            why = "no quote stored"
        if why:
            notes[name] = f"library value rejected at load: {why}"
        else:
            out[name] = p
    return {**doc, "params": out, "rejected_at_load": notes}


def load(cutoff: str, path: Path = PARAMS_FILE) -> dict | None:
    """Parameters valid at `cutoff` (point in time): None if the file is missing or was produced after the cutoff."""
    try:
        doc = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    return doc if doc.get("available_timestamp", "9999") <= cutoff else None


if __name__ == "__main__":
    import sys
    db = os.environ.get("DB_PATH") or str(BASE_DIR / "henry_hub_pit.db")
    d = refresh(db, sys.argv[1] if len(sys.argv) > 1 else literature_kb.DEFAULT_DB)
    for n, p in d["params"].items():
        print(f"{n}: {p['value']} {p['unit']}  [{p['source']}]  {p.get('quote') or p.get('reason')}")
    print(f"context nodes: {len(d['context'])}  -> {PARAMS_FILE}")
