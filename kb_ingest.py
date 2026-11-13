"""Progressive knowledge library: turns what the collectors and the hub have recorded into durable, PIT-stamped
knowledge objects with typed edges.

Storage: tables kb_nodes / kb_edges in henry_hub_pit.db (the graph and a float32 embedding per node), and the same
documents in the Chroma collection henry_hub_alpha_graph when a collection handle is passed (the hub process does that).
The public markets service only ever reads the SQLite tables, read-only.

Every object is a deterministic summary of rows already in pit_market_data, so its provenance is 'extracted_estimate'
(or 'model_hypothesis' for /execute theses and 'backtest_result' for experiments), never 'measured'.

Edge types and what they do and do not claim:
  previous_in_series  the prior object of the same series (chronology only)
  same_period         objects from different domains covering the same period (co-occurrence, NOT causation)
  builds_on           an /execute thesis that was generated with the linked node in its context
  semantic_neighbor   nearest EARLIER object by embedding similarity (retrieval aid, NOT proof of an analog or of causation)
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import numpy as np

BASE_DIR = Path(__file__).resolve().parent
OLLAMA_EMB_URL = os.environ.get("OLLAMA_EMB_URL", "http://127.0.0.1:11434/api/embeddings")
EMBED_MODEL = "nomic-embed-text"
EDGE_TYPES = ("previous_in_series", "same_period", "builds_on", "semantic_neighbor")
STORAGE = ["Agent_Storage_East", "Agent_Storage_Midwest", "Agent_Storage_Mountain", "Agent_Storage_Pacific",
           "Agent_Storage_SouthCentral_Salt", "Agent_Storage_SouthCentral_NonSalt"]
BASINS = ["Agent_Prod_Appalachia", "Agent_Prod_Permian", "Agent_Prod_Haynesville", "Agent_Prod_EagleFord", "Agent_Prod_Bakken", "Agent_Prod_DJBasin"]
PRICES = [("Agent_HH_Spot_EIA", "Henry Hub spot", "USD/MMBtu"), ("Agent_NGL_MontBelvieu_Propane", "Mont Belvieu propane", "cents/gal"),
          ("Agent_Crude_WTI_Spot", "WTI crude", "USD/bbl")]
REAL = "COALESCE(provenance,'measured')='measured' AND COALESCE(quality_status,'')<>'unverified_seed' AND source_id IS NOT NULL AND source_id<>''"


def ensure(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS kb_nodes(id TEXT PRIMARY KEY, domain TEXT, series_key TEXT, period TEXT, title TEXT, document TEXT,
        source_id TEXT, agent_ids TEXT, available_timestamp TEXT, available_epoch INTEGER, published_timestamp TEXT, raw_payload_hash TEXT,
        provenance TEXT, doc_hash TEXT, created TEXT, embedding BLOB)""")
    conn.execute("CREATE TABLE IF NOT EXISTS kb_edges(src TEXT, dst TEXT, type TEXT, weight REAL, PRIMARY KEY(src, dst, type))")
    conn.execute("CREATE INDEX IF NOT EXISTS kb_nodes_epoch ON kb_nodes(available_epoch)")


def epoch(ts: str) -> int:
    return int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp())


def node_id(domain: str, key: str) -> str:
    return "kb_" + hashlib.sha256(f"{domain}:{key}".encode()).hexdigest()[:12]


def _obj(domain, series_key, period, title, document, agents, available, source_id, raw_hash, provenance="extracted_estimate", published=None):
    return {"id": node_id(domain, f"{series_key}:{period}"), "domain": domain, "series_key": series_key, "period": period, "title": title,
            "document": document, "agent_ids": ",".join(agents), "available_timestamp": available, "available_epoch": epoch(available),
            "published_timestamp": published or available, "source_id": source_id, "raw_payload_hash": raw_hash or "", "provenance": provenance}


def _latest(conn, agent, target_like=None, limit=None):
    """Latest vintage per target for real measured rows: [(target, value, available, source_id, raw_hash)] ascending by target."""
    q = (f"SELECT p.target_timestamp,p.value,p.available_timestamp,p.source_id,p.raw_payload_hash FROM pit_market_data p WHERE p.agent_id=? AND {REAL} "
         "AND p.available_timestamp=(SELECT MAX(q.available_timestamp) FROM pit_market_data q WHERE q.agent_id=p.agent_id AND q.target_timestamp=p.target_timestamp)")
    args = [agent]
    if target_like:
        q += " AND p.target_timestamp LIKE ?"
        args.append(target_like)
    rows = conn.execute(q + " ORDER BY p.target_timestamp DESC" + (f" LIMIT {int(limit)}" if limit else ""), args).fetchall()
    return rows[::-1]


def build_objects(conn, weeks: int = 12, months: int = 12) -> list:
    out = []
    # ---- EIA weekly storage reports
    by_week: dict[str, dict] = {}
    for a in STORAGE:
        for t, v, av, src, h in _latest(conn, a, limit=weeks + 1):
            by_week.setdefault(t, {})[a] = (v, av, src, h)
    full = sorted(t for t, d in by_week.items() if len(d) == len(STORAGE))
    for i, t in enumerate(full):
        d = by_week[t]
        total = sum(x[0] for x in d.values())
        prev = sum(x[0] for x in by_week[full[i - 1]].values()) if i else None
        chg = f"; change versus the prior report {total - prev:+.0f} Bcf" if prev is not None else ""
        parts = ", ".join(f"{a.replace('Agent_Storage_', '').replace('_', ' ')} {d[a][0]:.0f}" for a in STORAGE)
        av = max(x[1] for x in d.values())
        out.append(_obj("storage", "eia_weekly_storage", t[:10], f"EIA storage, week ending {t[:10]}: {total:.0f} Bcf",
                        f"EIA weekly natural gas storage report for the week ending {t[:10]}. Working gas in Lower 48 storage was {total:.0f} Bcf{chg}. "
                        f"By region (Bcf): {parts}.", STORAGE, av, d[STORAGE[0]][2], d[STORAGE[0]][3]))
    # ---- weekly weather versus normal
    hdd = {t[:10]: (v, av, src, h) for t, v, av, src, h in _latest(conn, "Agent_Weather_Actual_HDD", limit=weeks * 7 + 7)}
    norm = dict(conn.execute("SELECT substr(target_timestamp,1,10), value FROM pit_market_data WHERE agent_id='Agent_Weather_30YrNormal_HDD'").fetchall())
    if hdd:
        last = datetime.strptime(max(hdd), "%Y-%m-%d")
        end = last - timedelta(days=(last.weekday() - 4) % 7)          # most recent Friday, to line up with storage weeks
        for w in range(weeks):
            e = end - timedelta(days=7 * w)
            ds = [(e - timedelta(days=k)).strftime("%Y-%m-%d") for k in range(7)]
            if not all(d in hdd and d in norm for d in ds):
                continue
            act, nrm = sum(hdd[d][0] for d in ds), sum(norm[d] for d in ds)
            tone = "colder than normal" if act > nrm else "warmer than normal"
            av = max(hdd[d][1] for d in ds)
            out.append(_obj("weather", "cpc_weekly_hdd", ds[0], f"Weather, week ending {ds[0]}: {act - nrm:+.0f} HDD versus normal",
                            f"Population-weighted CONUS heating degree days for the week ending {ds[0]} totalled {act:.0f} against a 1991-2020 normal of {nrm:.0f} "
                            f"({act - nrm:+.0f} HDD, {tone}). Source: NOAA CPC daily degree days; the normal is derived here from CPC history.",
                            ["Agent_Weather_Actual_HDD", "Agent_Weather_30YrNormal_HDD"], av, hdd[ds[0]][2], hdd[ds[0]][3]))
    # ---- monthly shale production by basin
    by_m: dict[str, dict] = {}
    for a in BASINS:
        for t, v, av, src, h in _latest(conn, a, limit=months + 1):
            by_m.setdefault(t, {})[a] = (v, av, src, h)
    fullm = sorted(t for t, d in by_m.items() if len(d) == len(BASINS))
    for i, t in enumerate(fullm):
        d = by_m[t]
        total = sum(x[0] for x in d.values())
        prev = sum(x[0] for x in by_m[fullm[i - 1]].values()) if i else None
        chg = f", {total - prev:+.2f} Bcf/d versus the prior month" if prev is not None else ""
        parts = ", ".join(f"{a.replace('Agent_Prod_', '')} {d[a][0]:.2f}" for a in BASINS)
        out.append(_obj("production", "steo_shale_production", t[:7], f"Shale gas production, {t[:7]}: {total:.1f} Bcf/d",
                        f"EIA estimate of shale natural gas production for {t[:7]} across six plays: {total:.2f} Bcf/d{chg}. By play (Bcf/d): {parts}. "
                        "These are EIA estimates and are revised in later releases.", BASINS, max(x[1] for x in d.values()), d[BASINS[0]][2], d[BASINS[0]][3]))
    # ---- monthly price summaries
    wti_m: dict[str, float] = {}
    for agent, label, unit in PRICES[::-1]:
        rows = _latest(conn, agent, limit=months * 23)
        bym: dict[str, list] = {}
        for r in rows:
            bym.setdefault(r[0][:7], []).append(r)
        ms = sorted(bym)[1:]                                            # the first month is usually partial
        for i, m in enumerate(ms):
            rs = bym[m]
            vals = [r[1] for r in rs]
            close, avg = vals[-1], sum(vals) / len(vals)
            if agent == "Agent_Crude_WTI_Spot":
                wti_m[m] = avg
            prev = bym[ms[i - 1]][-1][1] if i else None
            chg = f", {(close / prev - 1) * 100:+.1f}% on the month" if prev else ""
            extra = (f" The monthly average was {avg / 100 * 42 / wti_m[m] * 100:.0f}% of WTI on a per-barrel basis." if (unit == "cents/gal" and m in wti_m) else "")
            out.append(_obj("price", f"monthly_{agent}", m, f"{label}, {m}: closed {close:g} {unit}",
                            f"{label} in {m}: last close {close:g} {unit}{chg}; monthly range {min(vals):g} to {max(vals):g}, average {avg:.3g}.{extra} "
                            f"Source: EIA daily spot series ({len(vals)} sessions).", [agent], rs[-1][2], rs[-1][3], rs[-1][4]))
    # ---- RGGI auctions
    for t, v, av, src, h in _latest(conn, "Agent_Power_CO2_AllowancePrice", limit=6):
        out.append(_obj("carbon", "rggi_auction", t[:10], f"RGGI auction {t[:10]}: cleared ${v:.2f}/short ton",
                        f"The RGGI quarterly CO2 allowance auction held on {t[:10]} cleared at ${v:.2f} per short ton.", ["Agent_Power_CO2_AllowancePrice"], av, src, h))
    # ---- backtest experiments (results, not observations)
    try:
        for eid, created, cfg, tp, met, reason in conn.execute("SELECT id,created,config,test_period,metrics,reason FROM experiments WHERE config NOT LIKE '%\"persistence\"%'"):
            c, m = json.loads(cfg), json.loads(met or "{}")
            feats = (" using " + ", ".join(c["features"])) if c.get("features") else ""
            out.append(_obj("backtest", f"experiment_{c.get('model')}_{c.get('horizon_days')}d_{c.get('cost_bps')}bps_{c.get('slippage_bps', 0)}slip", eid,
                            f"Backtest {c.get('model')} {c.get('horizon_days')}d: {reason.split(':')[0]}",
                            f"Point-in-time walk-forward backtest of model '{c.get('model')}'{feats} on {c.get('agent')}, horizon {c.get('horizon_days')} day(s), "
                            f"cost {c.get('cost_bps')} bps. Out-of-sample period {tp}, n={m.get('n')}, RMSE {m.get('rmse', float('nan')):.4f}. Outcome: {reason}. "
                            "A rejected model is not evidence of a tradable edge.", [c.get("agent", "")], created, "experiments", "", provenance="backtest_result"))
    except sqlite3.OperationalError:
        pass
    return out


def embed(text: str, client: httpx.Client | None = None) -> list:
    r = (client or httpx).post(OLLAMA_EMB_URL, json={"model": EMBED_MODEL, "prompt": text}, timeout=30.0)
    r.raise_for_status()
    return r.json()["embedding"]


def _vec(blob) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def ingest(db_path: str, collection=None, embedder=embed, now: str | None = None, weeks: int = 12, months: int = 12) -> dict:
    """Build objects, embed the new or changed ones, store nodes and edges. Idempotent. `collection` is an optional Chroma handle."""
    now = now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        ensure(conn)
        objs = build_objects(conn, weeks, months)
        known = dict(conn.execute("SELECT id, doc_hash FROM kb_nodes").fetchall())
        new = changed = 0
        for o in objs:
            dh = hashlib.sha256(o["document"].encode()).hexdigest()
            if known.get(o["id"]) == dh:
                continue
            vec = np.asarray(embedder(o["title"] + ". " + o["document"]), dtype=np.float32)
            conn.execute("INSERT OR REPLACE INTO kb_nodes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (o["id"], o["domain"], o["series_key"], o["period"], o["title"], o["document"], o["source_id"], o["agent_ids"], o["available_timestamp"],
                          o["available_epoch"], o["published_timestamp"], o["raw_payload_hash"], o["provenance"], dh, now, vec.tobytes()))
            if collection is not None:
                collection.upsert(ids=[o["id"]], embeddings=[vec.tolist()], documents=[o["title"] + ". " + o["document"]],
                                  metadatas=[{k: o[k] for k in ("domain", "series_key", "period", "source_id", "agent_ids", "available_timestamp", "available_epoch",
                                                                "published_timestamp", "raw_payload_hash", "provenance")} | {"linked_nodes": "root"}])
            changed += o["id"] in known
            new += o["id"] not in known
        # mirror /execute theses already in the vector store so they appear in the graph
        mirrored = 0
        if collection is not None:
            got = collection.get(include=["documents", "metadatas", "embeddings"])
            for nid, doc, meta, emb in zip(got.get("ids", []), got.get("documents", []), got.get("metadatas", []), got.get("embeddings", [])):
                meta = meta or {}
                if nid.startswith("kb_") or not meta.get("available_timestamp"):
                    continue
                dh = hashlib.sha256((doc or "").encode()).hexdigest()
                if known.get(nid) != dh:
                    conn.execute("INSERT OR REPLACE INTO kb_nodes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                 (nid, "alpha_synthesis", "execute_thesis", meta["available_timestamp"][:10], (doc or "")[:90], doc or "", "quant_hub_execute", "",
                                  meta["available_timestamp"], int(meta.get("available_epoch") or epoch(meta["available_timestamp"])), meta["available_timestamp"], "",
                                  "model_hypothesis", dh, now, np.asarray(emb, dtype=np.float32).tobytes()))
                    mirrored += 1
                for parent in [p.strip() for p in str(meta.get("linked_nodes") or "").split(",") if p.strip() and p.strip() != "root"]:
                    conn.execute("INSERT OR IGNORE INTO kb_edges VALUES (?,?,?,?)", (parent, nid, "builds_on", None))
        edges = rebuild_edges(conn)
        conn.commit()
        total = conn.execute("SELECT COUNT(*) FROM kb_nodes").fetchone()[0]
        return {"objects_built": len(objs), "new": new, "changed": changed, "mirrored_theses": mirrored, "nodes_total": total, **edges}
    finally:
        conn.close()


def rebuild_edges(conn) -> dict:
    """Recompute the derived edge types from the current nodes (builds_on edges are kept as recorded)."""
    conn.execute("DELETE FROM kb_edges WHERE type<>'builds_on'")
    rows = conn.execute("SELECT id,domain,series_key,period,available_epoch,embedding FROM kb_nodes ORDER BY series_key, period").fetchall()
    counts = dict.fromkeys(EDGE_TYPES, 0)
    by_series: dict[str, list] = {}
    for r in rows:
        by_series.setdefault(r[2], []).append(r)
    for key, rs in by_series.items():
        if key == "execute_thesis" or key.startswith("experiment_"):
            continue
        for a, b in zip(rs, rs[1:]):
            conn.execute("INSERT OR IGNORE INTO kb_edges VALUES (?,?,?,?)", (a[0], b[0], "previous_in_series", None))
            counts["previous_in_series"] += 1
    # same period: weekly storage <-> weekly weather (same week ending); monthly price <-> monthly production
    idx = {(r[2], r[3]): r[0] for r in rows}
    for (key, period), nid in idx.items():
        if key == "eia_weekly_storage" and ("cpc_weekly_hdd", period) in idx:
            conn.execute("INSERT OR IGNORE INTO kb_edges VALUES (?,?,?,?)", (idx[("cpc_weekly_hdd", period)], nid, "same_period", None))
            counts["same_period"] += 1
        if key == "steo_shale_production":
            for k2 in ("monthly_Agent_HH_Spot_EIA", "monthly_Agent_NGL_MontBelvieu_Propane"):
                if (k2, period) in idx:
                    conn.execute("INSERT OR IGNORE INTO kb_edges VALUES (?,?,?,?)", (nid, idx[(k2, period)], "same_period", None))
                    counts["same_period"] += 1
    # nearest EARLIER neighbour from a different series (similarity only)
    vecs = [(r[0], r[2], r[4], _vec(r[5])) for r in rows if r[5]]
    if len(vecs) > 1:
        m = np.stack([v[3] for v in vecs])
        m = m / np.clip(np.linalg.norm(m, axis=1, keepdims=True), 1e-9, None)
        sim = m @ m.T
        for i, (nid, key, ep, _) in enumerate(vecs):
            best, bj = 0.0, None
            for j, (oid, okey, oep, _) in enumerate(vecs):
                if j != i and okey != key and oep < ep and sim[i, j] > best:
                    best, bj = float(sim[i, j]), j
            if bj is not None and best >= 0.6:
                conn.execute("INSERT OR IGNORE INTO kb_edges VALUES (?,?,?,?)", (vecs[bj][0], nid, "semantic_neighbor", round(best, 4)))
                counts["semantic_neighbor"] += 1
    counts["builds_on"] = conn.execute("SELECT COUNT(*) FROM kb_edges WHERE type='builds_on'").fetchone()[0]
    return {"edges": counts}


# ----------------------------------------------------------------------------- read side (used by the public service, read-only)
def graph(conn, as_of_epoch: int, limit: int = 300, domain: str | None = None) -> dict:
    q = ("SELECT id,domain,series_key,period,title,document,source_id,agent_ids,available_timestamp,published_timestamp,raw_payload_hash,provenance "
         "FROM kb_nodes WHERE available_epoch<=?")
    args: list = [as_of_epoch]
    if domain:
        q += " AND domain=?"
        args.append(domain)
    try:
        rows = conn.execute(q + " ORDER BY available_epoch DESC LIMIT ?", args + [limit]).fetchall()
    except sqlite3.OperationalError:
        return {"total_nodes": 0, "nodes": [], "links": [], "domains": {}}
    keys = ("id", "domain", "series_key", "period", "title", "document", "source_id", "agent_ids", "available_timestamp", "published_timestamp",
            "raw_payload_hash", "provenance")
    nodes = [dict(zip(keys, r)) for r in rows]
    ids = {n["id"] for n in nodes}
    links = [{"source": s, "target": d, "type": t, "weight": w} for s, d, t, w in conn.execute("SELECT src,dst,type,weight FROM kb_edges") if s in ids and d in ids]
    doms = dict(conn.execute("SELECT domain, COUNT(*) FROM kb_nodes WHERE available_epoch<=? GROUP BY domain", (as_of_epoch,)).fetchall())
    return {"total_nodes": sum(doms.values()), "nodes": nodes, "links": links, "domains": doms,
            "edge_legend": {"previous_in_series": "prior object of the same series", "same_period": "different domains, same period (co-occurrence, not causation)",
                            "builds_on": "thesis generated with the linked node in context", "semantic_neighbor": "nearest earlier object by embedding similarity (not causation)"}}


def search(conn, query_vec, as_of_epoch: int, limit: int = 8) -> list:
    """Cosine similarity over nodes with available_epoch <= as_of_epoch only."""
    try:
        rows = conn.execute("SELECT id,domain,title,document,available_timestamp,source_id,raw_payload_hash,provenance,embedding FROM kb_nodes "
                            "WHERE available_epoch<=? AND embedding IS NOT NULL", (as_of_epoch,)).fetchall()
    except sqlite3.OperationalError:
        return []
    if not rows:
        return []
    q = np.asarray(query_vec, dtype=np.float32)
    q = q / max(float(np.linalg.norm(q)), 1e-9)
    m = np.stack([_vec(r[8]) for r in rows])
    m = m / np.clip(np.linalg.norm(m, axis=1, keepdims=True), 1e-9, None)
    s = m @ q
    order = np.argsort(-s)[:limit]
    return [{"id": rows[i][0], "domain": rows[i][1], "title": rows[i][2], "document": rows[i][3], "available_timestamp": rows[i][4], "source_id": rows[i][5],
             "raw_payload_hash": rows[i][6], "provenance": rows[i][7], "similarity": round(float(s[i]), 4)} for i in order]


def summary(conn, as_of_epoch: int) -> dict:
    try:
        doms = dict(conn.execute("SELECT domain, COUNT(*) FROM kb_nodes WHERE available_epoch<=? GROUP BY domain", (as_of_epoch,)).fetchall())
        edges = conn.execute("SELECT COUNT(*) FROM kb_edges").fetchone()[0]
        latest = conn.execute("SELECT title, available_timestamp, domain FROM kb_nodes WHERE available_epoch<=? ORDER BY available_epoch DESC LIMIT 5", (as_of_epoch,)).fetchall()
    except sqlite3.OperationalError:
        return {"status": "empty", "nodes": 0, "edges": 0, "domains": {}, "latest": []}
    return {"status": "ok" if doms else "empty", "nodes": sum(doms.values()), "edges": edges, "domains": doms,
            "latest": [{"title": t, "available_timestamp": a, "domain": d} for t, a, d in latest]}


if __name__ == "__main__":
    db = os.environ.get("DB_PATH") or str(BASE_DIR / "henry_hub_pit.db")
    print("SQLite graph only (run POST /kb/ingest on the hub to also update the vector store):", file=sys.stderr)
    print(json.dumps(ingest(db), indent=1))
