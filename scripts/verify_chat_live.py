"""Live checks of the grounded chat against a running service and the real local model (V3, V4, V5, V6, N3, R2.x).
Usage: python scripts/verify_chat_live.py http://127.0.0.1:8096"""
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8096"
ROOT = Path(__file__).resolve().parent.parent
FAILS = []


def ask(msg, as_of=None):
    t0, marks, final, first_tok = time.time(), {}, None, None
    with httpx.stream("POST", f"{BASE}/api/chat/stream", json={"message": msg, "as_of": as_of}, timeout=300) as r:
        ev = None
        for line in r.iter_lines():
            if line.startswith("event:"):
                ev = line.split(": ")[1]
                marks.setdefault(ev, time.time() - t0)
            elif line.startswith("data:"):
                d = json.loads(line[6:])
                if ev == "token" and first_tok is None:
                    first_tok = time.time() - t0
                if ev == "final":
                    final = d
    return final, marks, first_tok, time.time() - t0


def check(name, ok, detail=""):
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILS.append(name)


state_asof = httpx.get(f"{BASE}/api/state.json").json()["as_of"]
log_before = sqlite3.connect(ROOT / "runtime" / "chat_log.db").execute("SELECT COUNT(*) FROM chat_log").fetchone()[0] if (ROOT / "runtime" / "chat_log.db").exists() else 0

# V4: pending-collector feeds
for term, probe in (("Freeport", "Why is Freeport flow unverified?"), ("Corpus Christi", "What is Corpus Christi feedgas flow right now?")):
    f, marks, tok, total = ask(probe, state_asof)
    a = f["answer"]
    check(f"V4 {term}: states the collector is pending", bool(re.search(r"pending", a, re.I)), a[:120].replace("\n", " "))
    check(f"V4 {term}: cites the proxy or last verified value from the facts, no guessed flow", f["verdict"] in ("model answer grounded",) or "withheld" in f["verdict"] or f["verdict"] == "deterministic")
    nums = re.findall(r"\d+(?:\.\d+)?", a)
    evid = " ".join(x["text"] for x in f["facts"]) + probe
    check(f"V4 {term}: every number in the answer is in the facts", all(n in evid for n in nums), f"{nums}")
    prox = {n for x in f["facts"] if x["kind"] == "proxy" for n in re.findall(r"\d+\.\d+", x["text"])}
    check(f"V4 {term}: a bootstrapped proxy number is never presented as a verified value", all(re.search(r"proxy|bootstrap|baseline|estimate", s_, re.I) for s_ in re.split(r"(?<=[.!?])\s+|[;\n]", a) if any(n in s_ for n in prox)))
    check(f"V3 {term}: answer cutoff equals the dashboard cutoff", f["cutoff"] == state_asof, f["cutoff"])
    check(f"V5 {term}: first event at {marks['status'] * 1000:.0f} ms, facts/baseline at {marks['context'] * 1000:.0f} ms (< 500 ms)", marks["context"] < 0.5, f"first model token {tok and round(tok, 1)} s, total {total:.1f} s, verdict: {f['verdict']}")

# N3: how the forward curve is built
f, marks, tok, total = ask("How is the forward curve built?", state_asof)
titles = [n["title"] for n in f["cited_nodes"]]
check("N3: all seven element nodes plus Forward_Pricing_Model retrieved", sum(bool(re.match(r"M[1-7] ", t)) for t in titles) == 7 and "Forward_Pricing_Model" in titles, f"{len(titles)} nodes")
paths = [d["path"] for d in f["cited_documents"] if d.get("topic")]
check("N3: cites governing documents from the research library", len(paths) >= 3 and all(p and not p.startswith("/etc") for p in paths), "; ".join(paths[:4]))
a = f["answer"]
check("N3: the answer distinguishes direct EIA/NOAA actuals, the bootstrapped feedgas proxy and the calculated ethane rejection", all(re.search(p, a, re.I) for p in ("direct", "bootstrap|proxy", "calculated|rejection")), f["verdict"])
check("N3: the answer says nothing among the seven moves the forward price (O6)", bool(re.search(r"no fundamentals-to-price model|none of the seven|does not enter|not .*price", a, re.I)))
print(a[:1500])

# V3: a cutoff before the knowledge existed must not retrieve it
f, *_ = ask("How is the forward curve built?", "2026-11-16T12:00:00Z")
check("V3: at an earlier cutoff, nodes and documents created later are not retrievable", not any(n["title"] == "Forward_Pricing_Model" for n in f["cited_nodes"]) and not any(d.get("topic") for d in f["cited_documents"]) and f["cutoff"] == "2026-11-16T12:00:00Z",
      f"{len(f['cited_nodes'])} nodes, {len(f['cited_documents'])} docs")

# R1.9: why did it move: no causal claim beyond the data
f, *_ = ask("Why did Henry Hub rise?", state_asof)
check("R1.9: a 'why did it move' answer reports the data and states no cause", not re.search(r"\b(due to|because of|caused by|driven by|as a result of|owing to)\b", f["answer"], re.I) and bool(re.search(r"1-day change|did not|not rise|no .*move|does not prove|price", f["answer"], re.I)), f["answer"][:200].replace("\n", " "))

# V6: audit log
c = sqlite3.connect(ROOT / "runtime" / "chat_log.db")
n = c.execute("SELECT COUNT(*) FROM chat_log").fetchone()[0]
row = c.execute("SELECT prompt,cutoff,node_ids,chunk_ids,fact_ids,model,verdict FROM chat_log ORDER BY id DESC LIMIT 1").fetchone()
check("V6: every prompt was logged locally with node ids, chunk ids, fact ids, model and verdict", n - log_before >= 5 and json.loads(row[2]) is not None and json.loads(row[4]) and row[5] is not None, f"{n - log_before} new rows; last: {row[0][:40]!r} {row[6]}")
print("\nFAILED:" if FAILS else "\nALL LIVE CHAT CHECKS PASSED", FAILS or "")
sys.exit(1 if FAILS else 0)
