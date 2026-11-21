#!/usr/bin/env python3
"""Proof of concept, end to end and local: study-paper literature graph -> grounded tooltips for live pricing values.

Stages (all idempotent; nothing here writes henry_hub_pit.db, the live markets DB is opened read-only by the engine):
  ingest     PDFs in --pdf-dir -> runtime/literature_kb.db (chunk, embed with nomic-embed-text via local Ollama, edges)
  retrieval  10 concept queries with a pre-registered gold document each -> doc-level hit@1/3/5 (weak sanity check, not a benchmark)
  generate   for 5 tooltip subjects, three conditions with the same local model (qwen3:4b), temperature 0:
               A  facts only (no literature)            B  facts + top-3 paper chunks            C  facts + top-2 chunks + their next chunk (graph step)
             Every number in FACTS is computed by code from the live engine payload; the model only writes the explanation.
Checks per tooltip (recorded raw; a production path would reject on any failure):
  numbers_grounded: every number in the text must appear in FACTS (agents.llm.numbers_grounded, the project's existing guard)
  citation validity: every [doc_xxxxxxxxxx:nnnn] must be one of the chunk ids actually supplied; A must cite nothing
  gold coverage: pre-registered concept groups (defined below, before any output was seen), a crude proxy for content quality
  length <= 80 words
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import literature_kb as lk  # noqa: E402
import markets_engine as me  # noqa: E402
from agents import llm as llmmod  # noqa: E402

CITE = re.compile(r"\[(doc_[0-9a-f]{10}:\d{4})\]")

# ---- pre-registered retrieval gold (doc-title substring) ------------------------------------------------------------------------------
RETRIEVAL_GOLD = [
    ("why do prices spike when supply capacity is tight", "Supply and Demand Based Volatility"),
    ("do trading returns differ by hour of the day in oil futures", "Intra-day Seasonality"),
    ("how do producers and buyers form alliances to gain pricing power in gas", "Coalition formation"),
    ("good news versus bad news effects on price variance spillovers", "Good and bad volatility"),
    ("sizing and operating batteries when load ramps up", "Optimal dispatch"),
    ("effect of war on wheat and fuel prices", "Shocks from the Russian invasion"),
    ("diversifying across commodities reduces portfolio risk", "Understanding World Commodity Prices"),
    ("segmenting a noisy time series with network analysis", "visibility graph"),
    ("LNG imports and gas supply security in Europe", "European Natural Gas"),
    ("cross-border power market coupling and price convergence", "European electricity wholesale"),
]

# ---- pre-registered tooltip subjects: question, retrieval query (concepts only, no numbers), gold concept groups (any-of per group) -----
SUBJECTS = [
    ("curve_shape", "What does the shape of this forward curve tell a trader, and why does it look this way?",
     "natural gas forward curve contango backwardation storage seasonal demand winter supply",
     [["contango", "backwardation"], ["storage", "inventor", "carry"], ["season", "winter", "heating"]]),
    ("winter_premium", "Why is the January contract priced above the April contract?",
     "winter heating demand storage withdrawal natural gas seasonal price premium",
     [["winter", "heating", "cold"], ["demand"], ["storage", "inventor", "withdraw"]]),
    ("volatility", "Why can small supply changes cause large price moves in this market?",
     "supply curve shape convex price volatility energy market tight supply",
     [["convex", "steep", "elastic", "supply curve"], ["volatil"], ["tight", "scarc", "capacity", "margin"]]),
    ("point_lineage", "Where does the M5 price come from and how much should I trust it?",
     "data quality transparency market data source reliability",
     [["delayed"], ["unverified", "not official", "not verified"], ["yahoo"]]),
    ("propane_ratio", "What does the propane-to-WTI ratio measure and how is it computed?",
     "NGL propane crude oil price ratio relative value",
     [["crude", "wti"], ["propane"], ["ratio", "percent", "relative", "discount", "parity"]]),
]


def build_facts(state: dict) -> dict[str, str]:
    """Deterministic FACTS strings from the live engine payload. These are the only numbers a tooltip may contain."""
    fc = state["curves"]["forward_curve"]
    pts = {p["contract"]: p for p in fc["points"]}
    v = lambda m: pts[m]["value"]  # noqa: E731
    curve = "; ".join(f"{m} ({pts[m]['delivery_month']}) {pts[m]['value']:.3f}" for m in (f"M{i}" for i in range(1, 13)) if m in pts)
    hi = max(pts.values(), key=lambda p: p["value"])
    lo = min(pts.values(), key=lambda p: p["value"])
    shape = (f"Henry Hub NYMEX futures, USD/MMBtu, quote date {fc['as_of_date']}: {curve}. Engine regime label: {fc['regime']} "
             f"(last contract minus first). M2 minus M1 = {v('M2') - v('M1'):.3f}. M12 minus M1 = {v('M12') - v('M1'):.3f}. "
             f"Highest contract {hi['contract']} ({hi['delivery_month']}) {hi['value']:.3f}; lowest {lo['contract']} ({lo['delivery_month']}) {lo['value']:.3f}.")
    winter = (f"Henry Hub futures, USD/MMBtu: M2 delivering {pts['M2']['delivery_month']} = {v('M2'):.3f}; M5 delivering {pts['M5']['delivery_month']} = {v('M5'):.3f}. "
              f"M2 minus M5 = {v('M2') - v('M5'):.3f}.")
    m5 = pts["M5"]
    lineage = (f"M5 contract {m5['series_id']} delivering {m5['delivery_month']}: {m5['value']:.3f} {m5['unit']}. Source {m5['source_id']}, quality label "
               f"'{m5['quality_status']}' (a delayed quote from Yahoo Finance, not an official exchange settlement). Quote published {m5['published_timestamp']}, "
               f"retrieved and available to this system {m5['available_timestamp']}.")
    pr, wti = state["curves"]["ngl_to_wti_pct"]["propane"], state["curves"]["ngl_to_wti_pct"]["wti"]
    usd_gal = pr["latest"] / 100 * wti["value"] / 42
    ratio = (f"Propane as a percent of WTI crude on {pr['dates'][-1]}: {pr['latest']:.2f} percent. WTI crude {wti['value']:.2f} USD/bbl. Formula: "
             f"(propane cents/gal / 100 * 42) / WTI USD/bbl * 100. Implied propane price {usd_gal * 100:.1f} cents/gal ({usd_gal:.3f} USD/gal).")
    return {"curve_shape": shape, "winter_premium": winter, "volatility": shape, "point_lineage": lineage, "propane_ratio": ratio}


def prompt_for(cond: str, facts: str, question: str, chunks: list[dict]) -> str:
    base = ("You write a tooltip for a natural gas pricing dashboard, for a trader. Rules: every number you write must be copied from FACTS; "
            "write no other number. Plain text, at most 70 words.\n")
    if cond == "A":
        base += "Explain why, from general knowledge. Do not cite anything; leave citations empty.\n"
    else:
        base += ("Explain why, using ideas from SOURCES. After each sentence that relies on a source, add its id in square brackets exactly as listed, "
                 "e.g. [doc_0123456789:0007]. Use only listed ids. Do not copy any number from SOURCES.\n")
    p = base + f"\nFACTS:\n{facts}\n"
    if cond != "A":
        p += "\nSOURCES:\n" + "\n".join(f"[{c['chunk_id']}] ({c['title'][:60]}) {c['text'][:1100]}" for c in chunks) + "\n"
    return p + f"\nQUESTION: {question}"


SCHEMA = {"type": "object", "properties": {"text": {"type": "string"}, "citations": {"type": "array", "items": {"type": "string"}}},
          "required": ["text", "citations"]}


def evaluate(out: dict, facts: str, allowed: set[str], gold: list[list[str]], cond: str) -> dict:
    text = out["text"]
    cited = set(CITE.findall(text)) | set(out.get("citations") or [])
    bad_nums = llmmod.numbers_grounded(CITE.sub("", text), facts)
    bad_cites = sorted(c for c in cited if c not in allowed)
    low = text.lower()
    cov = sum(any(t in low for t in grp) for grp in gold)
    return {"words": len(text.split()), "ungrounded_numbers": bad_nums, "citations": sorted(cited), "invalid_citations": bad_cites,
            "gold_groups_hit": cov, "gold_groups": len(gold), "has_citation": bool(cited),
            "passes_guard": not bad_nums and not bad_cites and (cond == "A" or bool(cited)) and (cond != "A" or not cited)}


def stage_ingest(conn, llm, pdf_dir: Path) -> None:
    emb = lambda t: llm.embed(t)  # noqa: E731
    for p in sorted(pdf_dir.rglob("*.pdf")):
        kind = "news" if "ngl_news" in p.parts else "paper"
        t0 = time.time()
        r = lk.ingest_pdf(conn, str(p), kind, emb)
        print(f"  {r['status']:5s} {kind:5s} chunks={r['chunks']:4d} {time.time() - t0:6.1f}s  {p.name[:70]}", flush=True)
    print("semantic edges (similarity only):", lk.rebuild_semantic_edges(conn))
    print(json.dumps(lk.stats(conn)))


def stage_retrieval(conn, llm) -> dict:
    now = int(time.time())
    hits = {1: 0, 3: 0, 5: 0}
    rows = []
    for q, gold in RETRIEVAL_GOLD:
        res = lk.search(conn, llm.embed(lk.QUERY_PREFIX + q), now, k=30, kinds=("paper", "news"))
        titles = []
        for r in res:
            if r["title"] not in titles:
                titles.append(r["title"])
        rank = next((i + 1 for i, t in enumerate(titles) if gold.lower() in t.lower()), None)
        for k in hits:
            hits[k] += bool(rank and rank <= k)
        rows.append({"query": q, "gold": gold, "doc_rank": rank, "top1": titles[0][:60] if titles else None})
        print(f"  rank={rank!s:>4}  {q[:62]:62s} -> {titles[0][:48] if titles else None}")
    n = len(RETRIEVAL_GOLD)
    summ = {f"hit@{k}": f"{v}/{n}" for k, v in hits.items()}
    print("retrieval", summ)
    return {"summary": summ, "rows": rows}


def stage_generate(conn, llm, db_path: str, out_dir: Path) -> dict:
    state = me.build_state(db_path)                                   # read-only on the live PIT database
    facts_by = build_facts(state)
    now = int(time.time())
    results = []
    for sid, question, rquery, gold in SUBJECTS:
        facts = facts_by[sid]
        qv = llm.embed(lk.QUERY_PREFIX + rquery)
        hits_b = lk.search(conn, qv, now, k=3, kinds=("paper",), per_doc=2)
        hits_c = lk.expand_adjacent(conn, lk.search(conn, qv, now, k=2, kinds=("paper",), per_doc=1), now)
        for cond, chunks in (("A", []), ("B", hits_b), ("C", hits_c)):
            prompt = prompt_for(cond, facts, question, chunks)
            t0 = time.time()
            try:
                out = llm.json("interpret", prompt, SCHEMA, version=f"poc-lit-tooltip-{cond}")
                err = None
            except Exception as e:  # noqa: BLE001
                out, err = {"text": "", "citations": []}, f"{type(e).__name__}: {e}"[:200]
            ms = int((time.time() - t0) * 1000)
            ev = evaluate(out, facts, {c["chunk_id"] for c in chunks}, gold, cond) if not err else {"passes_guard": False}
            results.append({"subject": sid, "cond": cond, "question": question, "text": out["text"], "error": err, "ms": ms, "prompt_chars": len(prompt),
                            "sources": [{"chunk_id": c["chunk_id"], "title": c["title"], "similarity": c.get("similarity"), "via": c.get("via")} for c in chunks],
                            **ev})
            print(f"  {sid:15s} {cond} {ms/1000:5.1f}s guard={'PASS' if ev.get('passes_guard') else 'FAIL'} nums_bad={len(ev.get('ungrounded_numbers', []))} "
                  f"cites={len(ev.get('citations', []))} bad_cites={len(ev.get('invalid_citations', []))} gold={ev.get('gold_groups_hit')}/{ev.get('gold_groups')} "
                  f"{err or ''}", flush=True)
    agg = {}
    for c in "ABC":
        rs = [r for r in results if r["cond"] == c]
        agg[c] = {"n": len(rs), "guard_pass": sum(r.get("passes_guard", False) for r in rs), "with_ungrounded_numbers": sum(bool(r.get("ungrounded_numbers")) for r in rs),
                  "invalid_citations": sum(len(r.get("invalid_citations", [])) for r in rs), "with_citation": sum(bool(r.get("has_citation")) for r in rs),
                  "gold_hit": sum(r.get("gold_groups_hit", 0) for r in rs), "gold_total": sum(r.get("gold_groups", 0) for r in rs),
                  "errors": sum(bool(r["error"]) for r in rs), "avg_ms": int(sum(r["ms"] for r in rs) / max(1, len(rs)))}
    print(json.dumps(agg, indent=1))
    out_dir.mkdir(parents=True, exist_ok=True)
    f = out_dir / "literature_tooltips_results.json"
    f.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "model": llmmod.REASONING_MODEL,
                             "embed_model": llmmod.EMBED_MODEL, "facts": facts_by, "aggregate": agg, "results": results}, indent=1))
    print("wrote", f)
    return agg


# ---- iteration 2: extractive evidence. Hold-out subjects and expectations pre-registered BEFORE running; thresholds were informed by iteration 1 sims ----
HOLDOUT = [
    ("geo_shock", "How do geopolitical shocks like the Russian invasion of Ukraine affect gas prices?",
     "Russian invasion Ukraine shock natural gas prices energy commodities", True),
    ("asym_vol", "Why do electricity prices react more to bad news than good news?",
     "asymmetric volatility spillover bad news good news electricity prices", True),
    ("battery_arbitrage", "How do energy storage systems earn money from price differences?",
     "energy storage dispatch price arbitrage charging discharging", True),
    ("contract_expiry", "How are futures contract expiry dates determined for natural gas?",
     "natural gas futures contract expiry last trading day delivery month", False),
    ("settlement_price", "What was the official settlement price of natural gas futures last Friday?",
     "official exchange settlement price natural gas futures", False),
]


# ---- iteration 3: FRESH hold-out, pre-registered before running, threshold 0.72 (derived from iteration-2 hold-out, so it must be tested on new subjects) ----
HOLDOUT2 = [
    ("intraday_returns", "How do hourly patterns affect oil futures returns?", "intraday seasonality abnormal returns futures trading hours", True),
    ("coalition_power", "How does market power change when producers and consumers form coalitions?", "coalition formation bargaining power natural gas market", True),
    ("diversification", "Why do commodity returns help diversify a portfolio?", "commodity returns volatility diversification portfolio", True),
    ("eia_storage_now", "What is the current EIA working gas in storage in Bcf?", "current weekly EIA working natural gas storage level Bcf", False),
    ("cme_settlement", "How does the CME calculate daily settlement prices?", "exchange daily settlement price calculation methodology", False),
    ("texas_uri", "What caused the Texas winter storm Uri power outages in 2021?", "Texas winter storm Uri 2021 power outages", False),
]


# ---- iteration 4: CLEAN hold-out for the terminated-sentence fix, pre-registered before running, same 0.72 threshold ----
HOLDOUT3 = [
    ("eu_power_integration", "How does market integration affect electricity price convergence in Europe?", "European electricity market integration price convergence coupling", True),
    ("visibility_graph", "What does visibility graph clustering do for time series?", "visibility graph spectral clustering time series segmentation", True),
    ("eu_russian_gas", "How did Europe reduce its reliance on Russian gas?", "Europe reduce reliance Russian pipeline gas LNG diversification", True),
    ("brent_today", "What is the current price of Brent crude today?", "current spot price of Brent crude oil today", False),
    ("ngl_frac_spread", "How is the NGL fractionation spread calculated at Mont Belvieu?", "NGL fractionation spread Mont Belvieu calculation", False),
    ("pipeline_tariff", "What are the pipeline tariffs for Transco zone 6?", "pipeline transportation tariff rates Transco zone 6", False),
]


def stage_evidence(conn, llm, out_dir: Path, version: str = "v2") -> None:
    now = int(time.time())
    rows = []
    t_all = time.time()
    if version == "v4":
        thr, name = 0.72, "literature_evidence_v4_results.json"
        plan = [("holdout3", sid, q, rq, exp) for sid, q, rq, exp in HOLDOUT3]
    elif version == "v3":
        thr, name = 0.72, "literature_evidence_v3_results.json"
        plan = [("holdout2", sid, q, rq, exp) for sid, q, rq, exp in HOLDOUT2]
    else:
        thr, name = 0.70, "literature_evidence_results.json"
        plan = [("exploratory", sid, q, rq, None) for sid, q, rq, _ in SUBJECTS] + [("holdout", sid, q, rq, exp) for sid, q, rq, exp in HOLDOUT]
    for split, sid, q, rq, expect in plan:
        t0 = time.time()
        r = lk.best_quotes(conn, lambda t: llm.embed(t), rq, now, min_chunk_sim=thr, min_sent_sim=thr)
        ms = int((time.time() - t0) * 1000)
        ok_verbatim = all(lk.verify_quote(conn, x["chunk_id"], x["quote"]) for x in r["quotes"])
        rows.append({"split": split, "subject": sid, "question": q, "expect_support": expect, "abstained": r["abstained"], "ms": ms, "all_verbatim": ok_verbatim,
                     "quotes": r["quotes"], "top_candidates": r["candidates"], "chunks_considered": r["chunks_considered"]})
        top = r["quotes"][0] if r["quotes"] else None
        print(f"  [{split:11s}] {sid:17s} {ms/1000:5.1f}s abstained={r['abstained']!s:5} chunks_ok={r['chunks_considered']} "
              f"{'-> ' + top['title'][:34] + ' sim=' + str(top['similarity']) if top else ''}", flush=True)
        for x in r["quotes"]:
            print(f"        \"{x['quote'][:230]}\"  [{x['chunk_id']}]")
    ho = [r for r in rows if r["split"] in ("holdout", "holdout2", "holdout3")]
    tp = sum((not r["abstained"]) and r["expect_support"] for r in ho)
    tn = sum(r["abstained"] and not r["expect_support"] for r in ho)
    summ = {"threshold": thr, "holdout_n": len(ho), "supported_when_expected": f"{tp}/{sum(r['expect_support'] for r in ho)}", "abstained_when_expected": f"{tn}/{sum(not r['expect_support'] for r in ho)}",
            "all_quotes_verbatim": all(r["all_verbatim"] for r in rows), "avg_ms": int(sum(r["ms"] for r in rows) / len(rows)), "total_s": round(time.time() - t_all, 1)}
    print(json.dumps(summ))
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / name).write_text(json.dumps({"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "summary": summ, "rows": rows}, indent=1))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["ingest", "retrieval", "generate", "evidence", "evidence_v3", "evidence_v4", "all"])
    ap.add_argument("--pdf-dir", default=os.path.expanduser("~/Documents/ngl_study_journals"))
    ap.add_argument("--lit-db", default=lk.DEFAULT_DB)
    ap.add_argument("--pit-db", default=os.environ.get("DB_PATH") or str(ROOT / "henry_hub_pit.db"))
    a = ap.parse_args()
    st = llmmod.status()
    if not st["ok"]:
        print("Ollama not ready:", st)
        return 2
    Path(a.lit_db).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(a.lit_db)
    lk.ensure(conn)
    llm = llmmod.LLM(conn, "poc_literature_tooltips")                  # llm_calls are logged in the literature DB, not the PIT DB
    if a.stage in ("ingest", "all"):
        stage_ingest(conn, llm, Path(a.pdf_dir))
    if a.stage in ("retrieval", "all"):
        stage_retrieval(conn, llm)
    if a.stage in ("evidence", "all"):
        stage_evidence(conn, llm, ROOT / "docs" / "poc")
    if a.stage == "evidence_v4":
        stage_evidence(conn, llm, ROOT / "docs" / "poc", "v4")
    if a.stage == "evidence_v3":
        stage_evidence(conn, llm, ROOT / "docs" / "poc", "v3")
    if a.stage in ("generate", "all"):
        stage_generate(conn, llm, a.pit_db, ROOT / "docs" / "poc")
    return 0


if __name__ == "__main__":
    sys.exit(main())
