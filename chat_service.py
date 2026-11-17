"""G6: the grounded chat behind the dashboard's command bar (R2.0-R2.5, V3-V6, N3).

Pipeline for every prompt (all of it read-only and limited to the dashboard's point-in-time cutoff):
  1 route      deterministic intent + entity extraction (terminals, hubs, metrics): no model involved.
  2 telemetry  live facts from the same state payload the page shows: collector status, last valid timestamp, raw payload hash, module outputs, alerts.
  3 retrieval  hybrid: dense vector search over the knowledge graph and the research library, plus 1-2 hop graph neighbours, all with available_at <= cutoff.
  4 answer     a deterministic answer built only from the facts (always available) and, when the local model is up, a streamed model answer that must cite the
               numbered facts. Every number the model writes must appear in the facts or the question; otherwise the model text is withheld and the deterministic
               answer is returned (R2.4: a missing feed is reported as pending, never guessed).
  5 audit      the prompt, node ids, chunk ids, fact ids, model and answer are appended to a local SQLite log (V6).
The model never sets a price and nothing it writes enters a calculation (V2)."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

import fundamentals as fu
import kb_ingest
import emi_alignment
import knowledge_roles as kr
import literature_kb as lk

BASE_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = Path(os.environ.get("QH_RUNTIME_DIR", BASE_DIR / "runtime"))
LOG_DB = RUNTIME_DIR / "chat_log.db"
EMI_ROOT = "/home/joey/Projects/energy_market_intelligence"
MAX_MESSAGE = 800
MIN_NODE_SIM, MIN_DOC_SIM = 0.50, 0.68      # measured on the live library: governing methodology chunks score >= 0.70, unrelated text about 0.62
SYNTHETIC_MARK = "SYNTHETIC HYPOTHETICAL DATA"   # exercise outputs that label themselves as made-up data are never cited as evidence
PROMPT_FACTS, PROMPT_NODES, PROMPT_DOCS = 16, 6, 3          # what the model is shown (a CPU-only 4B model: prompt length is latency); the same limits bound valid citation tags
SYSTEM = ("You are the assistant of a natural-gas and NGL markets dashboard. Answer ONLY from the numbered FACTS, NODES and DOCUMENTS you are given. "
          "If a feed has no data, say its collector is pending and quote the last verified value or the bootstrapped proxy if one is listed; never invent or estimate a number. "
          "Name whether a figure is a direct EIA/NOAA actual, a bootstrapped proxy, or a calculated module. Cite as [F1], [N1], [D1]. Never state or imply what caused a price move: report what the data shows and say it does not prove a cause. Be concise (under 120 words).")

# ----------------------------------------------------------------------------- 1. router
TERMINALS = {"sabine pass": ("SAB", "SabinePass"), "corpus christi": ("CRP", "CorpusChristi"), "freeport": ("FPT", "Freeport"), "cameron": ("CAM", "Cameron"),
             "calcasieu pass": ("CCP", "CalcasieuPass"), "plaquemines": ("PLQ", "Plaquemines"), "elba": ("ELB", "ElbaIsland"), "cove point": ("CVP", "CovePoint")}
HUBS = {"henry hub": "henry_hub", "mont belvieu": "mont_belvieu", "conway": "conway", "waha": "waha", "ttf": "ttf", "jkm": "jkm", "creole trail": "creole_trail"}
METRICS = [("frac", r"frac|ethane|rejection"), ("forward", r"forward|futures|contango|backwardation|curve"), ("lng_forward", r"lng forward|netback|fob|liquefaction"),
           ("feedgas", r"feed ?gas|feedgas"), ("storage", r"storage|inventory"), ("weather", r"weather|hdd|cdd|degree day"), ("production", r"production|shale|permian|haynesville|appalachia"),
           ("border", r"border|mexico|canada"), ("lng_exports", r"export")]
INTENTS = [("how_built", r"\b(how|explain|walk me through|what goes into)\b.*\b(forward|curve|built|constructed|calculated|computed|derived|priced)\b"),
           ("collector_status", r"pending|unverified|no data|missing|collector|not available|why is .*(flow|feed|data|empty)"),
           ("why_moved", r"\bwhy\b.*\b(move|moved|rise|rose|fall|fell|up|down|spike|jump|drop|change)\b")]


def route(message: str) -> dict:
    m = " ".join(message.lower().split())
    ents = [{"type": "terminal", "id": v[0], "name": v[1], "label": k.title()} for k, v in TERMINALS.items() if k in m]
    ents += [{"type": "hub", "id": v, "label": k.title()} for k, v in HUBS.items() if k in m]
    metrics = [k for k, pat in METRICS if re.search(pat, m)]
    intent = next((i for i, pat in INTENTS if re.search(pat, m)), "explain_metric" if (metrics or ents) else "general")
    product = "henry_hub" if any(e["id"] == "henry_hub" for e in ents) else None      # the page's default product is an NGL; a Henry Hub question needs the Henry Hub series
    return {"intent": intent, "entities": ents, "metrics": metrics, "product": product}


# ----------------------------------------------------------------------------- 2. telemetry
def _src_fact(s: dict) -> str:
    if s.get("status") == "collected":
        h = s.get("raw_payload_hash")
        return (f"{s['agent_id']} ({s.get('series') or 'series'}): collected from {s.get('source_id')}; latest observation {(s.get('latest_target_timestamp') or '')[:10]}; "
                f"available (point in time) {s.get('available_timestamp')}; age {s['age_days']:.1f} days; quality {s.get('quality_status')}; provenance {s.get('provenance')}; "
                f"payload hash {h[:16] if h else 'none'}.")
    return (f"{s['agent_id']} ({s.get('series') or 'series'}): collector pending. No collector writes this series yet (intended source: {s.get('intended_source') or 'not assigned'}); "
            "no value is shown and nothing is estimated.")


def _fmt(v, d=2):
    return "n/a" if v is None else f"{v:,.{d}f}"


def telemetry(state: dict, r: dict, context: dict | None = None) -> list[dict]:
    """Numbered facts drawn only from the payload the dashboard itself shows at this cutoff."""
    facts: list[dict] = []
    add = lambda kind, text, **kw: facts.append({"id": f"F{len(facts) + 1}", "kind": kind, "text": text, **kw})  # noqa: E731
    src = {s["agent_id"]: s for s in state.get("sources", [])}
    f, mods, curves = state.get("fundamentals") or {}, state.get("modules") or {}, state.get("curves") or {}
    els = {e["id"]: e for e in f.get("elements", [])}
    add("cutoff", f"The dashboard point-in-time cutoff is {state.get('as_of') or state.get('cutoff') or 'now'}; only data available at or before it is used.")
    for e in r["entities"]:
        if e["type"] == "terminal":
            for a in (f"Agent_LNGExports_{e['name']}", f"Agent_LNG_{e['name']}_Flow"):
                if a in src:
                    add("telemetry", _src_fact(src[a]), agent=a)
            bt = (mods.get("lng_feedgas") or {}).get("per_terminal_baseline", {}).get(e["id"])
            if bt:
                add("proxy", f"{e['label']} bootstrapped proxy baseline: {bt['feedgas_baseline_bcfd']} Bcf/d feedgas (last EIA month {bt['last_month']}, exports {bt['exports_bcfd']} Bcf/d x fuel uplift 8-10%). "
                             "It is a proxy, not a metered flow.", agent="Agent_LNGFeedgas_P50")
    want = set(r["metrics"]) | ({"forward", "lng_forward", "feedgas", "frac", "storage", "weather", "production", "lng_exports", "border"} if r["intent"] == "how_built" else set())
    mid = {"frac": "M5", "feedgas": "M4", "storage": "M3", "weather": "M2", "production": "M1", "lng_exports": "M6", "border": "M7"}
    for k in ("production", "weather", "storage", "feedgas", "frac", "lng_exports", "border"):
        if k in want and mid[k] in els:
            e = els[mid[k]]
            h = e.get("headline")
            cls = "a calculated module" if e["mode"] == fu.SEPARATE else "a direct ingested input"
            val = (f"{_fmt(h['value'])} {h.get('unit') or ''} ({h.get('label')}, {h.get('date')}; provenance {h.get('provenance')})" if h and h.get("value") is not None else "no value (collector pending)")
            add("element", f"{mid[k]} {e['label']} is {cls}; frequency {e['frequency']}; collector status: {e['collector_status']}; current: {val}.", agent=mid[k])
            for b in e.get("blocked", [])[:5]:
                add("blocked", f"{mid[k]} blocked input {b.get('id') or ''} {b.get('input')}: {b.get('reason')}. To activate: {b.get('activate')}.", agent=mid[k])
            for a in e.get("agents", [])[:1]:
                if a in src and src[a]["status"] != "collected":
                    add("telemetry", _src_fact(src[a]), agent=a)
    fg = mods.get("lng_feedgas")
    if "feedgas" in want and fg and fg.get("status") == "estimate":
        add("proxy", f"US LNG feedgas bootstrapped proxy (as of {fg['as_of'][:10]}): p10 {fg['p10']}, p50 {fg['p50']}, p90 {fg['p90']} Bcf/d from {fg['n_iterations']} bootstrap iterations, "
                     f"anchored on EIA monthly exports for {fg['anchor_month']} ({fg['anchor_exports_bcfd']} Bcf/d). Provenance {fg['provenance']}; evidence class {fg['evidence']['class']}.")
    fm = mods.get("frac")
    if "frac" in want and fm:
        if fm["status"] == "estimate":
            add("module", f"Ethane frac spread module: {fm['regime']}, margin {_fmt(fm['margin_usd_mmbtu'])} USD/MMBtu, net dry-gas delta {_fmt(fm['net_dry_gas_delta_bcfd']['central'])} Bcf/d (central).")
        else:
            add("module", "Ethane frac spread module is pending: " + "; ".join(f"{b['input']} ({b['reason']})" for b in fm.get("blocked", [])) + ". No spread or rejection volume is estimated.")
    if want & {"forward", "lng_forward"}:
        for p in f.get("forward_price_inputs", []):
            add("price_input", f"{p['id']} {p['label']} sets {p['sets']}; status {p['status']}; {p.get('value') or (str(p.get('n')) + ' points' if p.get('n') is not None else '')}; {p.get('provenance')}.")
        fw = curves.get("forward_curve") or {}
        if fw.get("status") == "measured":
            pts = fw.get("points") or []
            add("curve", f"Henry Hub forward curve: {len(pts)} monthly futures, quote date {fw.get('as_of_date')}, shape {fw.get('shape') and fw['shape'].get('regime') or fw.get('regime')}; stale={fw.get('stale')}.")
        lg = curves.get("lng_forward") or {}
        if lg.get("points"):
            p0 = lg["points"][0]
            add("curve", f"LNG FOB cost {p0['contract']}: {_fmt(p0['fob_cost'], 3)} USD/MMBtu = k {lg['parameters']['k_hh_multiplier']['value']:g} x Henry Hub {p0['hh_value']} + L "
                         f"{lg['parameters']['liquefaction_usd_mmbtu']['value']:g} (both {lg['parameters']['k_hh_multiplier']['source']}).")
    pr = state.get("price") or {}
    if any(e["id"] == "henry_hub" for e in r["entities"]) or "forward" in want:
        if state.get("active_product") == "henry_hub" and pr.get("status") == "measured":
            add("price", f"Henry Hub spot (EIA) last {_fmt(pr['value'], 3)} {pr.get('unit')} on {pr.get('date')}; 1-day change {_fmt(pr.get('change_1d'), 3)} ({_fmt(pr.get('change_1d_pct'), 2)}%); "
                         f"5-day change {_fmt(pr.get('change_5d'), 3)} ({_fmt(pr.get('change_5d_pct'), 2)}%); window high {_fmt(pr.get('window_high'), 3)}, low {_fmt(pr.get('window_low'), 3)}; "
                         f"quality {pr.get('quality_status')}; payload hash {(pr.get('raw_payload_hash') or 'none')[:16]}.")
        elif r["intent"] in ("why_moved", "explain_metric"):
            add("price", "No Henry Hub price series is available in this view; no move is described.")
    if r["intent"] == "how_built":
        add("note", f.get("price_note", ""))
    for a in state.get("alerts", [])[:3] if r["intent"] in ("why_moved", "how_built") else []:
        add("alert", f"Alert ({a.get('level')}, {a.get('kind')}): {a.get('text')}")
    if context:                                            # click-to-ask: resolved server-side from the same payload, never trusted from the client
        d = (state.get("explain") or {}).get(context.get("metric") or "", None)
        if d:
            add("context", f"Metric under discussion: {d.get('title')}. {d.get('what')} Formula: {d.get('formula') or 'n/a'}.")
        ag = context.get("agent")
        if ag and ag in src:
            add("context", _src_fact(src[ag]), agent=ag)
    return facts[:32]


CAUSAL = re.compile(r"\b(due to|because of|caused by|driven by|as a result of|owing to|thanks to|led to|resulted from|attributable to)\b", re.I)


# ----------------------------------------------------------------------------- 3. retrieval
def _neighbours(kb, node_id: str, epoch: int, limit: int) -> list[dict]:
    rows = kb.execute("SELECT e.type, CASE WHEN e.src=? THEN e.dst ELSE e.src END AS o FROM kb_edges e WHERE (e.src=? OR e.dst=?) AND e.type NOT IN ('semantic_neighbor','previous_in_series') "
                      "LIMIT 40", (node_id, node_id, node_id)).fetchall()
    out = []
    for typ, oid in rows:
        n = kb.execute("SELECT id,title,domain,series_key,available_timestamp FROM kb_nodes WHERE id=? AND available_epoch<=?", (oid, epoch)).fetchone()
        if n:
            out.append({"id": n[0], "title": n[1], "domain": n[2], "series_key": n[3], "available_timestamp": n[4], "via": typ})
        if len(out) >= limit:
            break
    return out


def retrieve(kb, lit, embedder, message: str, cutoff: str, r: dict) -> dict:
    ep = kb_ingest.epoch(cutoff)
    nodes: dict[str, dict] = {}
    try:
        qv = embedder(message)
        for h in kb_ingest.search(kb, qv, ep, 6):
            if h["similarity"] >= MIN_NODE_SIM:
                nodes[h["id"]] = {"id": h["id"], "title": h["title"], "domain": h["domain"], "similarity": h["similarity"], "available_timestamp": h["available_timestamp"], "hop": 0}
    except Exception as e:  # noqa: BLE001
        qv = None
        nodes_error = f"embedding unavailable: {type(e).__name__}"
    else:
        nodes_error = None
    if r["intent"] == "how_built":                          # N3: all seven element nodes and the pricing-model node, always
        for sk in [f"element_M{i}" for i in range(1, 8)] + ["forward_pricing_model"]:
            period = "definition"
            row = kb.execute("SELECT id,title,domain FROM kb_nodes WHERE id=? AND available_epoch<=?", (kb_ingest.node_id("fundamentals", f"{sk}:{period}"), ep)).fetchone()
            if row:
                nodes.setdefault(row[0], {"id": row[0], "title": row[1], "domain": row[2], "similarity": None, "hop": 0, "available_timestamp": None})
    for nid in list(nodes)[:4]:                             # 1-2 hop graph neighbours (R1.6)
        for n1 in _neighbours(kb, nid, ep, 3):
            nodes.setdefault(n1["id"], {**n1, "similarity": None, "hop": 1, "from": nid})
            for n2 in _neighbours(kb, n1["id"], ep, 2) if len(nodes) < 24 else []:
                nodes.setdefault(n2["id"], {**n2, "similarity": None, "hop": 2, "from": n1["id"]})
    for n in nodes.values():
        n["domain_role"] = kr.role_of_kb(kb, n["id"])
    docs: dict[str, dict] = {}
    queries = [("", message)]
    if r["intent"] == "how_built":
        queries += [("forward curve and LNG cost (P1-P4)", "forward price calculation methodology"), ("LNG feedgas and liquefaction (M4, M6)", "LNG feedgas mass balance and liquefaction"),
                    ("ethane rejection and frac spread (M5)", "ethane rejection frac spread economics"), ("storage and weather demand (M2, M3)", "natural gas storage and weather demand"),
                    ("shale production (M1)", "shale gas production by basin"), ("exports and border flows (M6, M7)", "LNG exports and cross-border pipeline flows")]
    if lit is not None:
        for topic, q in queries:
            try:
                v = np.asarray(embedder(lk.QUERY_PREFIX + q), dtype=np.float32)
                for h in lk.search(lit, v, ep, k=6, per_doc=1):
                    if SYNTHETIC_MARK in h["text"]:
                        continue
                    if h["similarity"] >= MIN_DOC_SIM and (h["doc_id"] not in docs or h["similarity"] > docs[h["doc_id"]]["similarity"]):
                        path = lit.execute("SELECT path FROM lit_docs WHERE doc_id=?", (h["doc_id"],)).fetchone()
                        docs[h["doc_id"]] = {"doc_id": h["doc_id"], "chunk_id": h["chunk_id"], "title": h["title"], "path": path[0] if path else None, "kind": h["kind"],
                                             "similarity": h["similarity"], "snippet": " ".join(h["text"].split())[:260], "query": q, "topic": topic, "domain_role": kr.role_of_lit(lit, h["doc_id"]),
                                             "alignment": (emi_alignment.alignment_of(lit, h["doc_id"]) or {}).get("label"),
                                             "available_timestamp": h["available_timestamp"]}
            except Exception:  # noqa: BLE001
                break
    return {"nodes": sorted(nodes.values(), key=lambda n: (n["hop"], -(n["similarity"] or 0)))[:24], "documents": sorted(docs.values(), key=lambda d: -d["similarity"])[:10], "node_error": nodes_error}


# ----------------------------------------------------------------------------- 4. answers
def facts_answer(r: dict, facts: list, state: dict, ret: dict) -> str:
    """The deterministic answer: built only from the facts, so it is always available and always grounded."""
    f = (state.get("fundamentals") or {})
    els = {e["id"]: e for e in f.get("elements", [])}
    if r["intent"] == "how_built":
        lines = ["How the forward prices on this page are built:"]
        for p in f.get("forward_price_inputs", []):
            lines.append(f"- {p['id']} {p['label']}: {p.get('value') or (str(p.get('n')) + ' points' if p.get('n') is not None else p['status'])} ({'market quote' if p.get('market_derived') else 'labelled assumption'}); sets {p['sets']}.")
        d = [e for e in els.values() if e["mode"] == fu.DIRECT]
        lines.append("Direct EIA/NOAA actuals (used as published, context only): " + "; ".join(
            f"{e['id']} {e['label']} {_fmt(e['headline']['value'])} {e['headline'].get('unit') or ''} ({e['headline'].get('date')})" if e.get("headline") else f"{e['id']} {e['label']} pending" for e in d) + ".")
        m4 = els.get("M4")
        if m4 and m4.get("headline"):
            h = m4["headline"]
            lines.append(f"Bootstrapped LNG feedgas (M4, a proxy, not metered): p50 {_fmt(h['value'])} Bcf/d (p10 {_fmt(h.get('p10'))}, p90 {_fmt(h.get('p90'))}) anchored on EIA monthly exports (M6); "
                         "pipeline scheduled quantities, AIS and ERCOT inputs are blocked.")
        else:
            lines.append("Bootstrapped LNG feedgas (M4): not available at this cutoff.")
        m5 = els.get("M5")
        if m5 and m5["status"] == "estimate":
            lines.append(f"Calculated ethane rejection (M5): {m5['headline']['label']} {_fmt(m5['headline']['value'])} Bcf/d.")
        else:
            lines.append("Calculated ethane rejection (M5): pending. " + "; ".join(f"{b['input']}" for b in (m5 or {}).get("blocked", [])) + " have no collector, so no spread or rejection volume is estimated.")
        lines.append(f.get("price_note", ""))
        return "\n".join(x for x in lines if x)
    body = [x["text"] for x in facts if x["kind"] not in ("cutoff", "note")][:8]
    if not body:
        return ("I have no live telemetry for that question at this cutoff. Ask about a terminal (e.g. Freeport), a hub, the forward curve, the frac spread, feedgas, "
                "storage, weather, production, exports or border flows.")
    head = {"collector_status": "Collector status at this cutoff:", "why_moved": "What the dashboard data shows (it does not prove a cause):"}.get(r["intent"], "From the dashboard data:")
    return head + "\n" + "\n".join("- " + b for b in body)


def build_prompt(message: str, facts: list, ret: dict) -> str:
    fl = "\n".join(f"[{x['id']}] {x['text']}" for x in facts[:PROMPT_FACTS])
    nl = "\n".join(f"[N{i + 1}] ({n['domain_role']}) {n['title']}" for i, n in enumerate(ret["nodes"][:PROMPT_NODES]))
    dl = "\n".join(f"[D{i + 1}] {d['title']} ({d['path']}): {d['snippet'][:170]}" for i, d in enumerate(ret["documents"][:PROMPT_DOCS]))
    return f"FACTS:\n{fl}\n\nNODES:\n{nl or 'none'}\n\nDOCUMENTS:\n{dl or 'none'}\n\nQUESTION: {message}\n/no_think"


def evidence_text(message: str, facts: list, ret: dict) -> str:
    """Exactly what the model was shown: the numbers it may repeat."""
    return (message + "\n" + "\n".join(x["text"] for x in facts[:PROMPT_FACTS]) + "\n" + "\n".join(n["title"] for n in ret["nodes"][:PROMPT_NODES]) + "\n"
            + "\n".join(d["title"] + " " + d["snippet"][:170] for d in ret["documents"][:PROMPT_DOCS]))


ANSWER_SCHEMA = {"type": "object", "properties": {"answer": {"type": "string", "maxLength": 700}, "cited": {"type": "array", "items": {"type": "string"}}}, "required": ["answer", "cited"]}
JSON_RULES = " Reply with a JSON object: answer (at most 3 sentences, starting directly with the answer, no preamble or reasoning) and cited (the ids you used)."


class AnswerExtractor:
    """Pulls the decoded text of the JSON `answer` string out of a token stream as it arrives (the schema keeps a 4B model from narrating its reasoning)."""

    def __init__(self):
        self.buf, self.pos, self.done, self.esc = "", None, False, False

    def feed(self, tok: str) -> str:
        self.buf += tok
        if self.pos is None:
            m = re.search(r'"answer"\s*:\s*"', self.buf)
            if not m:
                return ""
            self.pos = m.end()
        out, i = "", self.pos
        while i < len(self.buf) and not self.done:
            ch = self.buf[i]
            if self.esc:
                out += {"n": "\n", "t": "\t"}.get(ch, ch)
                self.esc = False
            elif ch == "\\":
                self.esc = True
            elif ch == '"':
                self.done = True
            else:
                out += ch
            i += 1
        self.pos = i
        return out


def ollama_stream(prompt: str, model: str = "qwen3:4b", url: str = "http://127.0.0.1:11434", timeout: float = 120.0):
    """Yield the answer text from the local model (Ollama /api/chat, streamed, schema-constrained). Raises on failure; the caller falls back to the deterministic answer."""
    import httpx
    body = {"model": model, "stream": True, "think": False, "keep_alive": -1, "format": ANSWER_SCHEMA, "options": {"temperature": 0, "num_predict": 320, "num_ctx": 6144},
            "messages": [{"role": "system", "content": SYSTEM + JSON_RULES}, {"role": "user", "content": prompt}]}
    ex = AnswerExtractor()
    with httpx.stream("POST", f"{url}/api/chat", json=body, timeout=timeout) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line:
                continue
            d = json.loads(line)
            tok = (d.get("message") or {}).get("content")
            if tok:
                piece = ex.feed(tok)
                if piece:
                    yield piece
            if d.get("done"):
                break


_META = re.compile(r"^\W*(we are given|let'?s|okay|hmm|first,|the user|i need to|we must|the question is|looking at)", re.I)


HOW_BUILT_TERMS = (("direct", r"direct"), ("bootstrapped proxy", r"bootstrap|proxy"), ("calculated module", r"calculated|module|rejection"))


_DEC = re.compile(r"\d+\.\d+")
_PROXY_WORDS = re.compile(r"proxy|bootstrap|baseline|estimate|modelled|modeled", re.I)


def proxy_numbers(facts: list) -> set:
    """Decimal numbers that appear in proxy facts (bootstrapped feedgas): wherever the answer repeats one it must call it a proxy, never a measured or verified value."""
    return {n for f in facts if f["kind"] == "proxy" for n in _DEC.findall(f["text"])}


def check_answer(text: str, evidence: str, n_facts: int, n_nodes: int, n_docs: int, required: tuple = (), forbid_causal: bool = False, proxy_nums: set = frozenset()) -> str | None:
    """None if the model text is acceptable, else why it is withheld: reasoning-style preamble, a citation tag that points at nothing, or a number that is not in the evidence."""
    if not text.strip():
        return "model returned nothing"
    if _META.match(text):
        return "model narrated its reasoning instead of answering"
    if forbid_causal and CAUSAL.search(text):
        return "states a cause, which the data cannot prove"
    for label, pat in required:                           # N3: the answer itself must separate actuals, the bootstrapped proxy and the calculated module
        if not re.search(pat, text, re.I):
            return f"does not distinguish the {label}"
    if proxy_nums:
        for sent in re.split(r"(?<=[.!?])\s+|[;\n]", text):
            if any(n in sent for n in proxy_nums) and not _PROXY_WORDS.search(sent):
                return "presents a bootstrapped proxy number without calling it a proxy"
    limits = {"F": n_facts, "N": n_nodes, "D": n_docs}
    for k, i in re.findall(r"\[([FND])(\d+)\]", text):
        if not 1 <= int(i) <= limits[k]:
            return f"cites [{k}{i}], which was not provided"
    bad = _ungrounded(text, evidence)
    return f"numbers not in the facts {bad}" if bad else None


# ----------------------------------------------------------------------------- 5. audit
def log_turn(path: Path, rec: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path, timeout=10)
    try:
        c.execute("""CREATE TABLE IF NOT EXISTS chat_log(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, cutoff TEXT, prompt TEXT, intent TEXT, entities TEXT, node_ids TEXT, chunk_ids TEXT,
                     fact_ids TEXT, model TEXT, verdict TEXT, answer TEXT, first_event_ms INTEGER, total_ms INTEGER)""")
        c.execute("INSERT INTO chat_log(ts,cutoff,prompt,intent,entities,node_ids,chunk_ids,fact_ids,model,verdict,answer,first_event_ms,total_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (rec["ts"], rec["cutoff"], rec["prompt"], rec["intent"], json.dumps(rec["entities"]), json.dumps(rec["node_ids"]), json.dumps(rec["chunk_ids"]), json.dumps(rec["fact_ids"]),
                   rec["model"], rec["verdict"], rec["answer"], rec["first_event_ms"], rec["total_ms"]))
        c.commit()
    finally:
        c.close()


# ----------------------------------------------------------------------------- orchestration
def respond(message: str, cutoff: str, state_fn, kb, lit, embedder, stream_fn=None, context: dict | None = None, log_path: Path | str | None = LOG_DB):
    """Generator of (event, payload): status -> context -> token* -> final. `stream_fn(prompt)` yields tokens (None disables the model)."""
    t0 = time.time()
    message = " ".join(message.split())[:MAX_MESSAGE]
    ms = lambda: int((time.time() - t0) * 1000)  # noqa: E731
    yield "status", {"stage": "routing", "cutoff": cutoff}
    first_ms = ms()
    r = route(message)
    state = state_fn(r["product"])
    facts = telemetry(state, r, context)
    base = facts_answer(r, facts, state, None)            # depends only on the facts, so it can be shown before retrieval finishes
    yield "context", {"intent": r["intent"], "entities": r["entities"], "facts": facts, "cutoff": cutoff, "baseline_answer": base}
    ret = retrieve(kb, lit, embedder, message, cutoff, r)
    yield "context", {"cited_nodes": ret["nodes"], "cited_documents": ret["documents"], "node_error": ret["node_error"]}
    text, verdict, model = "", "deterministic", None
    if stream_fn is not None:
        model = "qwen3:4b (local Ollama)"
        try:
            for tok in stream_fn(build_prompt(message, facts, ret)):
                text += tok
                yield "token", {"t": tok}
            why = check_answer(text, evidence_text(message, facts, ret), min(len(facts), PROMPT_FACTS), min(len(ret["nodes"]), PROMPT_NODES), min(len(ret["documents"]), PROMPT_DOCS),
                               HOW_BUILT_TERMS if r["intent"] == "how_built" else (), r["intent"] == "why_moved", proxy_numbers(facts[:PROMPT_FACTS]))
            verdict = "model answer grounded" if why is None else f"model text withheld: {why}"
        except Exception as e:  # noqa: BLE001
            verdict = f"model unavailable ({type(e).__name__}): deterministic answer used"
            text = ""
    answer = text.strip() if verdict == "model answer grounded" else base
    if r["intent"] == "how_built":                        # N3: name the governing methodology documents (research library paths) per topic
        gov = [f"- {d['topic']}: {d['title']} ({d['path']})" for d in ret["documents"] if d.get("topic")]
        if gov:
            answer += "\n\nGoverning documents in the research library:\n" + "\n".join(gov)
    final = {"answer": answer, "verdict": verdict, "model": model, "intent": r["intent"], "cutoff": cutoff, "cited_nodes": ret["nodes"], "cited_documents": ret["documents"],
             "facts": facts, "baseline_answer": base, "first_event_ms": first_ms, "total_ms": ms()}
    if log_path:
        try:
            log_turn(log_path, {"ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "cutoff": cutoff, "prompt": message, "intent": r["intent"], "entities": r["entities"],
                                "node_ids": [n["id"] for n in ret["nodes"]], "chunk_ids": [d["chunk_id"] for d in ret["documents"]], "fact_ids": [x["id"] for x in facts], "model": model,
                                "verdict": verdict, "answer": answer, "first_event_ms": first_ms, "total_ms": final["total_ms"]})
        except Exception as e:  # noqa: BLE001
            final["audit_error"] = f"{type(e).__name__}: {e}"[:120]
    yield "final", final


def _ungrounded(text: str, evidence: str) -> list:
    from agents.llm import numbers_grounded
    return numbers_grounded(re.sub(r"\[[FND]\d+\]", "", text), evidence)
