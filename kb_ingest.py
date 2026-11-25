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
  part_of             a chunk of a long source document -> the document (parent-child; chunks carry the parent's PIT metadata)
  evidence_for        written by the research agents (agents/): knowledge an agent cited when it produced a finding
  evaluated_by        written by the synthesis agent: hypothesis -> its PIT walk-forward backtest evaluation
Long source documents are chunked (chunk_text: paragraph boundaries, overlap on hard splits) so the whole text is embedded.
"""
from __future__ import annotations

import hashlib
import re
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
EDGE_TYPES = ("previous_in_series", "same_period", "builds_on", "semantic_neighbor")   # derived here; part_of/evidence_for/evaluated_by are kept
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
    conn.execute("""CREATE TABLE IF NOT EXISTS kb_edge_versions(
        recorded_revision INTEGER PRIMARY KEY AUTOINCREMENT,
        src TEXT NOT NULL, dst TEXT NOT NULL, type TEXT NOT NULL, weight REAL,
        available_epoch INTEGER NOT NULL DEFAULT 0,
        recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        UNIQUE(src, dst, type, available_epoch, recorded_revision))""")
    conn.execute("CREATE INDEX IF NOT EXISTS kb_edge_versions_lookup ON kb_edge_versions(src, type, available_epoch, recorded_revision)")
    conn.execute("CREATE INDEX IF NOT EXISTS kb_edge_versions_reverse ON kb_edge_versions(dst, type, available_epoch, recorded_revision)")
    conn.execute("DROP TRIGGER IF EXISTS trg_kb_edges_history")
    conn.execute("""CREATE TRIGGER trg_kb_edges_history
        AFTER INSERT ON kb_edges
        BEGIN
            INSERT INTO kb_edge_versions(src, dst, type, weight, available_epoch, recorded_at)
            VALUES (NEW.src, NEW.dst, NEW.type, NEW.weight,
                    COALESCE((SELECT MAX(n.available_epoch) FROM kb_nodes n WHERE n.id=NEW.src), 0),
                    strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
        END""")
    conn.execute("CREATE INDEX IF NOT EXISTS kb_nodes_epoch ON kb_nodes(available_epoch)")
    # Superseded versions of a node (additive; kb_nodes keeps the current one). Same 16 columns so the two can be UNIONed.
    conn.execute("""CREATE TABLE IF NOT EXISTS kb_node_versions(id TEXT, domain TEXT, series_key TEXT, period TEXT, title TEXT, document TEXT,
        source_id TEXT, agent_ids TEXT, available_timestamp TEXT, available_epoch INTEGER, published_timestamp TEXT, raw_payload_hash TEXT,
        provenance TEXT, doc_hash TEXT, created TEXT, embedding BLOB, PRIMARY KEY(id, available_epoch))""")
    conn.execute("""CREATE VIEW IF NOT EXISTS kb_nodes_all AS
        SELECT id,domain,series_key,period,title,document,source_id,agent_ids,available_timestamp,available_epoch,published_timestamp,raw_payload_hash,provenance,doc_hash,created,embedding FROM kb_nodes
        UNION ALL
        SELECT id,domain,series_key,period,title,document,source_id,agent_ids,available_timestamp,available_epoch,published_timestamp,raw_payload_hash,provenance,doc_hash,created,embedding FROM kb_node_versions""")


def _archive(conn, nid: str, new_epoch: int) -> None:
    """Before kb_nodes[nid] is replaced by a later-available revision, keep the outgoing version so as_of queries between the two
    vintages still see what was known then. A rewrite at the same or an earlier availability is not a new vintage and is not archived."""
    conn.execute("INSERT OR IGNORE INTO kb_node_versions SELECT * FROM kb_nodes WHERE id=? AND available_epoch<?", (nid, new_epoch))


def _src(conn) -> str:
    """kb_nodes_all when the archive exists, else plain kb_nodes (read-only DBs written before the archive existed)."""
    return "kb_nodes_all" if conn.execute("SELECT 1 FROM sqlite_master WHERE name='kb_nodes_all'").fetchone() else "kb_nodes"


def _asof(src: str, alias: str = "n") -> str:
    """Predicate: the version of each node that was the latest available at :t (never one made available after :t)."""
    return (f"{alias}.available_epoch<=:t AND {alias}.available_epoch=(SELECT MAX(w.available_epoch) FROM {src} w "
            f"WHERE w.id={alias}.id AND w.available_epoch<=:t)")


def epoch(ts: str) -> int:
    return int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp())


def node_id(domain: str, key: str) -> str:
    return "kb_" + hashlib.sha256(f"{domain}:{key}".encode()).hexdigest()[:12]


def _obj(domain, series_key, period, title, document, agents, available, source_id, raw_hash, provenance="extracted_estimate", published=None):
    return {"id": node_id(domain, f"{series_key}:{period}"), "domain": domain, "series_key": series_key, "period": period, "title": title,
            "document": document, "agent_ids": ",".join(agents), "available_timestamp": available, "available_epoch": epoch(available),
            "published_timestamp": published or available, "source_id": source_id, "raw_payload_hash": raw_hash or "", "provenance": provenance}


DEFINED_AT = "2026-11-17T00:00:00Z"      # when the entity dictionary was adopted (availability of the entity nodes)
CHUNK_CHARS, CHUNK_OVERLAP = 1800, 200


def chunk_text(text: str, size: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP) -> list:
    """Split long source text on paragraph boundaries into pieces of at most `size` characters; a paragraph longer than
    `size` is cut with `overlap` characters repeated, so no sentence is lost at a boundary. Concatenating the pieces (minus
    overlaps) reproduces the whole text."""
    paras = [p.strip() for p in text.replace("\r\n", "\n").split("\n\n") if p.strip()]
    out, cur = [], ""
    for p in paras:
        while len(p) > size:                         # hard split of an oversized paragraph
            if cur:
                out.append(cur)
                cur = ""
            out.append(p[:size])
            p = p[size - overlap:]
        if cur and len(cur) + 2 + len(p) > size:
            out.append(cur)
            cur = ""
        cur = f"{cur}\n\n{p}" if cur else p
    if cur:
        out.append(cur)
    return out


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
    # ---- source documents (forecast discussions, pipeline notices...): the source's own text, newest first
    try:
        for did, dom, src, url, title, body, pub, av, h in conn.execute(
                "SELECT id,domain,source_id,source_url,title,body,published_timestamp,available_timestamp,raw_payload_hash FROM documents "
                "ORDER BY available_timestamp DESC LIMIT ?", (weeks * 7,)):
            text = body if len(body) <= 4000 else body[:4000] + " [...]"
            parent = _obj(dom, f"document_{src}", did, title, text, [], av, src, h, provenance="source_document", published=pub)
            out.append(parent)
            parts = chunk_text(body) if len(body) > CHUNK_CHARS * 1.5 else []
            for i, part in enumerate(parts):      # the full text, searchable piece by piece; same PIT metadata as the parent
                o = _obj(dom, f"document_{src}_chunk", f"{did}#{i + 1}", f"{title} (part {i + 1}/{len(parts)})", part, [], av, src, h,
                         provenance="source_document", published=pub)
                o["parent"] = parent["id"]
                out.append(o)
    except sqlite3.OperationalError:
        pass
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
    # ---- G5: the seven fundamental elements and how each is classified (graph nodes; the text is the definition, no market value)
    try:
        import fundamentals
        for e in fundamentals.ELEMENTS:
            kind = "calculated separately in its own isolated module" if e["mode"] == fundamentals.SEPARATE else "a direct ingested input"
            doc = (f"{e['id']} {e['label']} is {kind}. Method: {e['method']}. Source: {e['source']}. Role: {e['role']}. "
                   + (f"Scope rule: {e['scope_rule']}. " if e["scope_rule"] else "") + f"Graph link: {e['graph_link']}. It does not set the Henry Hub forward curve or the LNG forward price.")
            out.append(_obj("fundamentals", f"element_{e['id']}", "definition", f"{e['id']} {e['label']} ({'module' if e['mode'] == fundamentals.SEPARATE else 'direct input'})", doc, [],
                            fundamentals.DEFINED, "fundamentals_classification", "", provenance="source_document"))
        out.append(_obj("fundamentals", "forward_pricing_model", "definition", "Forward_Pricing_Model",
                        "The forward prices on this page: the Henry Hub forward curve is a delayed NYMEX futures quote, and the LNG forward is derived from it as k x Henry Hub + L, "
                        "with a TTF netback beside it. The relations from the seven fundamental elements into this node are DECLARED by the requirement; "
                        "no code consumes those inputs yet, so none of them changes a price today.", [], fundamentals.DEFINED, "fundamentals_classification", "", provenance="source_document"))
    except Exception:  # noqa: BLE001
        pass
    return out


# R1.5: named entities as first-class nodes, linked to every existing node whose text mentions them. (name, pattern, plain definition; no market values)
ENTITIES = [("Sabine Pass", r"sabine pass", "Sabine Pass LNG, a US Gulf Coast LNG export terminal in Louisiana."), ("Corpus Christi", r"corpus christi", "Corpus Christi LNG, a US LNG export terminal in Texas."),
            ("Freeport", r"freeport", "Freeport LNG, a US LNG export terminal in Texas (electric-drive liquefaction)."), ("Cameron", r"\bcameron\b", "Cameron LNG, a US LNG export terminal in Louisiana."),
            ("Calcasieu Pass", r"calcasieu pass", "Calcasieu Pass LNG, a US LNG export terminal in Louisiana."), ("Plaquemines", r"plaquemines", "Plaquemines LNG, a US LNG export terminal in Louisiana."),
            ("Elba Island", r"elba", "Elba Island LNG, a US LNG export terminal in Georgia."), ("Cove Point", r"cove point", "Cove Point LNG, a US LNG export terminal in Maryland."),
            ("Mont Belvieu", r"mont belvieu", "Mont Belvieu, the Texas Gulf Coast NGL trading and fractionation hub."), ("Conway", r"\bconway\b", "Conway, the Kansas Midcontinent NGL hub."),
            ("Henry Hub", r"henry hub", "Henry Hub, the Louisiana natural gas pricing point of the NYMEX futures contract."), ("Waha", r"\bwaha\b", "Waha, the West Texas natural gas hub."),
            ("Frac Spread", r"frac(?:tionation)? spread", "The frac spread, the value of ethane as fuel minus the gas price; it decides ethane recovery or rejection."),
            ("Creole Trail Pipeline", r"creole trail", "Creole Trail Pipeline, an interstate pipeline serving the Sabine Pass LNG terminal.")]
ENTITY_ROLE_DOMAIN = "entity"


def link_entities(conn) -> int:
    """Create (idempotently) one node per entity and 'mentions' edges entity -> every non-entity node whose text mentions it. Derived: recomputed on every ingest."""
    conn.execute("DELETE FROM kb_edges WHERE type='mentions'")
    n, now_ep = 0, epoch(DEFINED_AT)
    for name, pat, defn in ENTITIES:
        nid = node_id(ENTITY_ROLE_DOMAIN, f"entity_{name}:definition")
        conn.execute("INSERT OR IGNORE INTO kb_nodes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (nid, ENTITY_ROLE_DOMAIN, f"entity_{name}", "definition", name, defn, "entity_dictionary", "", DEFINED_AT, now_ep, DEFINED_AT, "", "source_document",
                      hashlib.sha256(defn.encode()).hexdigest(), DEFINED_AT, None))
        rx = re.compile(pat, re.I)
        for oid, title, doc in conn.execute("SELECT id, title, document FROM kb_nodes WHERE domain<>? AND domain<>'fundamentals'", (ENTITY_ROLE_DOMAIN,)).fetchall():
            if rx.search(title or "") or rx.search(doc or ""):
                conn.execute("INSERT OR IGNORE INTO kb_edges VALUES (?,?,?,?)", (nid, oid, "mentions", None))
                n += 1
    return n


# N1: relation names from the requirement. Stored as non-derived edge types (rebuild_edges keeps them); they are declarations, not measured causation.
DECLARED_EDGES = [("M1", "feeds_supply", None), ("M2", "feeds_rescomm_demand", None), ("M3", "feeds_inventory_balance", None), ("M4", "calibrated_by", "M6"),
                  ("M5", "modifies_dry_gas_supply", None), ("M7", "feeds_net_exports", None)]


def declare_edges(conn) -> int:
    n = 0
    fpm = node_id("fundamentals", "forward_pricing_model:definition")
    for src, typ, dst in DECLARED_EDGES:
        a, b = node_id("fundamentals", f"element_{src}:definition"), (node_id("fundamentals", f"element_{dst}:definition") if dst else fpm)
        if conn.execute("SELECT COUNT(*) FROM kb_nodes WHERE id IN (?,?)", (a, b)).fetchone()[0] == 2:
            conn.execute("INSERT OR IGNORE INTO kb_edges VALUES (?,?,?,?)", (a, b, typ, None))
            n += 1
    return n


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
            _archive(conn, o["id"], o["available_epoch"])
            conn.execute("INSERT OR REPLACE INTO kb_nodes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (o["id"], o["domain"], o["series_key"], o["period"], o["title"], o["document"], o["source_id"], o["agent_ids"], o["available_timestamp"],
                          o["available_epoch"], o["published_timestamp"], o["raw_payload_hash"], o["provenance"], dh, now, vec.tobytes()))
            if collection is not None:
                collection.upsert(ids=[o["id"]], embeddings=[vec.tolist()], documents=[o["title"] + ". " + o["document"]],
                                  metadatas=[{k: o[k] for k in ("domain", "series_key", "period", "source_id", "agent_ids", "available_timestamp", "available_epoch",
                                                                "published_timestamp", "raw_payload_hash", "provenance")} | {"linked_nodes": o.get("parent", "root")}])
            changed += o["id"] in known
            new += o["id"] not in known
        for o in objs:                               # parent-child: every chunk is part_of its source document
            if o.get("parent"):
                conn.execute("INSERT OR IGNORE INTO kb_edges VALUES (?,?,?,?)", (o["id"], o["parent"], "part_of", None))
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
                    _archive(conn, nid, int(meta.get("available_epoch") or epoch(meta["available_timestamp"])))
                    conn.execute("INSERT OR REPLACE INTO kb_nodes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                 (nid, "alpha_synthesis", "execute_thesis", meta["available_timestamp"][:10], (doc or "")[:90], doc or "", "quant_hub_execute", "",
                                  meta["available_timestamp"], int(meta.get("available_epoch") or epoch(meta["available_timestamp"])), meta["available_timestamp"], "",
                                  "model_hypothesis", dh, now, np.asarray(emb, dtype=np.float32).tobytes()))
                    mirrored += 1
                for parent in [p.strip() for p in str(meta.get("linked_nodes") or "").split(",") if p.strip() and p.strip() != "root"]:
                    conn.execute("INSERT OR IGNORE INTO kb_edges VALUES (?,?,?,?)", (parent, nid, "builds_on", None))
        edges = rebuild_edges(conn)
        edges["declared_requirement_edges"] = declare_edges(conn)
        edges["entity_mentions"] = link_entities(conn)
        import knowledge_roles
        edges["roles_tagged"] = knowledge_roles.tag_kb(conn)            # R1.7: every node carries a domain_role (market_narrative / physical_fundamental / pricing_parameter)
        conn.commit()
        total = conn.execute("SELECT COUNT(*) FROM kb_nodes").fetchone()[0]
        return {"objects_built": len(objs), "new": new, "changed": changed, "mirrored_theses": mirrored, "nodes_total": total, **edges}
    finally:
        conn.close()


def rebuild_edges(conn) -> dict:
    """Recompute the derived edge types from the current nodes (builds_on edges are kept as recorded)."""
    conn.execute("DELETE FROM kb_edges WHERE type IN ('previous_in_series','same_period','semantic_neighbor')")   # derived here; agent edges are kept
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
        if key.startswith("document_noaa_cpc_610"):           # a forecast discussion and the weekly weather summary of its issue week
            wk = next((p for k, p in idx if k == "cpc_weekly_hdd" and 0 <= (datetime.strptime(p, "%Y-%m-%d") - datetime.strptime(period[7:17], "%Y-%m-%d")).days < 7), None)
            if wk:
                conn.execute("INSERT OR IGNORE INTO kb_edges VALUES (?,?,?,?)", (idx[("cpc_weekly_hdd", wk)], nid, "same_period", None))
                counts["same_period"] += 1
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
    try:
        src = _src(conn)
        q = ("SELECT n.id,n.domain,n.series_key,n.period,n.title,n.document,n.source_id,n.agent_ids,n.available_timestamp,n.published_timestamp,n.raw_payload_hash,n.provenance "
             f"FROM {src} n WHERE {_asof(src)}")
        args: dict = {"t": as_of_epoch, "lim": limit}
        if domain:
            q += " AND n.domain=:dom"
            args["dom"] = domain
        rows = conn.execute(q + " ORDER BY n.available_epoch DESC LIMIT :lim", args).fetchall()
    except sqlite3.OperationalError:
        return {"total_nodes": 0, "nodes": [], "links": [], "domains": {}}
    keys = ("id", "domain", "series_key", "period", "title", "document", "source_id", "agent_ids", "available_timestamp", "published_timestamp",
            "raw_payload_hash", "provenance")
    nodes = [dict(zip(keys, r)) for r in rows]
    status = _finding_status(conn)
    for n in nodes:
        if n["id"] in status:
            n["status"] = status[n["id"]][0]
    ids = {n["id"] for n in nodes}
    links = [{"source": s, "target": d, "type": t, "weight": w} for s, d, t, w in conn.execute("SELECT src,dst,type,weight FROM kb_edges") if s in ids and d in ids]
    doms = dict(conn.execute(f"SELECT n.domain, COUNT(*) FROM {src} n WHERE {_asof(src)} GROUP BY n.domain", {"t": as_of_epoch}).fetchall())
    return {"total_nodes": sum(doms.values()), "nodes": nodes, "links": links, "domains": doms, "edge_legend": EDGE_LEGEND}


def _reachable_edge_source(conn, as_of_epoch: int, recorded_revision: int | None = None):
    has_history = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='kb_edge_versions'").fetchone()
    if has_history and conn.execute("SELECT 1 FROM kb_edge_versions LIMIT 1").fetchone():
        sql = "SELECT src,dst,type,weight FROM kb_edge_versions WHERE available_epoch<=:t"
        args = {"t": as_of_epoch}
        if recorded_revision is not None:
            sql += " AND recorded_revision<=:rev"
            args["rev"] = recorded_revision
        return sql, args
    return "SELECT src,dst,type,weight FROM kb_edges", {}


def graph_reachable(conn, seed_ids, as_of_epoch: int, edge_types=(), max_hops: int = 3,
                    recorded_revision: int | None = None, limit: int = 100) -> dict:
    """Bounded recursive traversal with the same PIT predicate on every node and edge (TypeGraph pattern)."""
    src = _src(conn)
    seeds = list(dict.fromkeys(s for s in (seed_ids or []) if isinstance(s, str) and s))[:50]
    max_hops = max(1, min(int(max_hops), 10))
    limit = max(1, min(int(limit), 500))
    if not seeds:
        return {"nodes": [], "links": [], "depths": {}, "max_hops": max_hops}
    edge_sql, edge_args = _reachable_edge_source(conn, as_of_epoch, recorded_revision)
    types = [t for t in (edge_types or []) if isinstance(t, str) and t]
    args = {"t": as_of_epoch, "hops": max_hops, "lim": limit, "rev": recorded_revision, **edge_args}
    args.update({f"seed{i}": seed for i, seed in enumerate(seeds)})
    seed_sql = ",".join(f":seed{i}" for i in range(len(seeds)))
    type_sql = f" AND e.type IN ({','.join(':' + f'type{i}' for i in range(len(types)))})" if types else ""
    args.update({f"type{i}": t for i, t in enumerate(types)})
    node_asof = _asof(src, "nxt")
    q = f"""
    WITH RECURSIVE walk(id, depth, path) AS (
        SELECT n.id, 0, '/' || n.id || '/'
        FROM {src} n
        WHERE n.id IN ({seed_sql}) AND {_asof(src, 'n')}
        UNION
        SELECT nxt.id, walk.depth + 1, walk.path || nxt.id || '/'
        FROM walk
        JOIN ({edge_sql}) e ON e.src = walk.id
        JOIN {src} nxt ON nxt.id = e.dst AND {node_asof}
        WHERE walk.depth < :hops
          AND INSTR(walk.path, '/' || nxt.id || '/') = 0
          {type_sql}
    )
    SELECT DISTINCT n.id, n.domain, n.title, n.available_timestamp, n.available_epoch, walk.depth
    FROM walk JOIN {src} n ON n.id = walk.id AND {_asof(src, 'n')}
    ORDER BY walk.depth, n.available_epoch DESC
    LIMIT :lim
    """
    rows = conn.execute(q, args).fetchall()
    keys = ("id", "domain", "title", "available_timestamp", "available_epoch", "depth")
    nodes = [{k: v for k, v in zip(keys, r) if k != "depth"} for r in rows]
    depths = {r[0]: r[5] for r in rows}
    ids = set(depths)
    links = [{"source": s, "target": d, "type": t, "weight": w}
             for s, d, t, w in conn.execute(edge_sql, edge_args) if s in ids and d in ids]
    return {"nodes": nodes, "links": links, "depths": depths, "max_hops": max_hops}


EDGE_LEGEND = {"previous_in_series": "prior object of the same series", "same_period": "different domains, same period (co-occurrence, not causation)",
               "builds_on": "thesis generated with the linked node in context", "semantic_neighbor": "nearest earlier object by embedding similarity (not causation)",
               "evidence_for": "knowledge an agent cited when it produced the finding", "evaluated_by": "hypothesis tested by a PIT walk-forward backtest",
               "part_of": "a chunk of a longer source document (parent-child)",
               "mentions": "a named entity (terminal, hub, pipeline, spread) appears in the text of the linked node",
               **{t: "relation declared by the requirement; no calculation consumes this input yet (not measured causation)" for _s, t, _d in DECLARED_EDGES}}


def _finding_status(conn) -> dict:
    try:
        return {r[0]: (r[1], r[2], r[3], r[4]) for r in conn.execute("SELECT node_id, status, reason, checked_at, checker FROM finding_status")}
    except sqlite3.OperationalError:
        return {}


def node_detail(conn, node_id: str, as_of_epoch: int) -> dict | None:
    """One knowledge object with its edges, verdict, source payload metadata and (for notices) the agent extraction, all PIT."""
    keys = ("id", "domain", "series_key", "period", "title", "document", "source_id", "agent_ids", "available_timestamp", "available_epoch",
            "published_timestamp", "raw_payload_hash", "provenance", "doc_hash", "created")
    src = _src(conn)
    r = conn.execute(f"SELECT {','.join('n.' + k for k in keys)} FROM {src} n WHERE n.id=:id AND {_asof(src)}", {"id": node_id, "t": as_of_epoch}).fetchone()
    if not r:
        return None
    n = dict(zip(keys, r))
    st = _finding_status(conn).get(node_id)
    n["status"] = {"status": st[0], "reason": st[1], "checked_at": st[2], "checker": st[3]} if st else None
    edges = []
    for s, d, t, w in conn.execute("SELECT src, dst, type, weight FROM kb_edges WHERE src=? OR dst=?", (node_id, node_id)):
        other = d if s == node_id else s
        o = conn.execute(f"SELECT n.title, n.domain, n.available_timestamp FROM {src} n WHERE n.id=:id AND {_asof(src)}", {"id": other, "t": as_of_epoch}).fetchone()
        if o:
            edges.append({"direction": "out" if s == node_id else "in", "type": t, "weight": w, "id": other, "title": o[0], "domain": o[1],
                          "available_timestamp": o[2]})
    n["edges"] = edges
    n["raw_payload"] = None
    if n["raw_payload_hash"]:
        try:
            p = conn.execute("SELECT source_id, source_url, http_status, retrieved_timestamp, content_type, byte_length FROM raw_payloads "
                             "WHERE raw_payload_hash=?", (n["raw_payload_hash"],)).fetchone()
        except sqlite3.OperationalError:
            p = None
        if p:
            n["raw_payload"] = dict(zip(("source_id", "source_url", "http_status", "retrieved_timestamp", "content_type", "byte_length"), p))
    n["extraction"] = None
    if n["domain"] == "pipeline_notice":
        try:
            e = conn.execute("SELECT event_type, severity, location, summary, model, extracted_at, checks FROM notice_extractions WHERE document_id=?",
                             (n["period"],)).fetchone()
        except sqlite3.OperationalError:
            e = None
        if e:
            n["extraction"] = {**dict(zip(("event_type", "severity", "location", "summary", "model", "extracted_at", "checks"), e)),
                               "provenance": "model extraction (validated against the source label)"}
    return n


def agent_activity(conn, limit: int = 20) -> dict:
    """Read-only view of the agent system: runs, bus messages, model-call statistics and finding verdicts."""
    def q(sql, args=()):
        try:
            return conn.execute(sql, args).fetchall()
        except sqlite3.OperationalError:
            return []
    cols = {r[1] for r in q("PRAGMA table_info(llm_calls)")}
    fb = "SUM(COALESCE(fallback,0))" if "fallback" in cols else "0"
    return {
        "runs": [{"agent": r[0], "started": r[1], "finished": r[2], "as_of": r[3], "ok": bool(r[4]), "summary": _short_summary(r[5])}
                 for r in q("SELECT agent, started, finished, as_of, ok, summary FROM agent_runs ORDER BY id DESC LIMIT ?", (limit,))],
        "messages": [{"id": m[0], "at": m[1], "from": m[2], "topic": m[3], "ref": m[4],
                      "consumed_by": [c[0] for c in q("SELECT consumer FROM agent_message_reads WHERE message_id=?", (m[0],))]}
                     for m in q("SELECT id, at, sender, topic, ref FROM agent_messages ORDER BY id DESC LIMIT ?", (limit,))],
        "topics": dict(q("SELECT topic, COUNT(*) FROM agent_messages GROUP BY topic")),
        "llm_calls": [{"agent": c[0], "task": c[1], "model": c[2], "calls": c[3], "ok": c[4], "fallback": c[5], "avg_ms": c[6], "last": c[7]}
                      for c in q(f"SELECT agent, task, model, COUNT(*), SUM(ok), {fb}, CAST(AVG(ms) AS INTEGER), MAX(at) FROM llm_calls GROUP BY 1,2,3 ORDER BY 8 DESC")],
        "finding_status": dict(q("SELECT status, COUNT(*) FROM finding_status GROUP BY status")),
        "findings": [{"id": r[0], "title": r[1], "available_timestamp": r[2], "provenance": r[3], "status": r[4]}
                     for r in q("SELECT n.id, n.title, n.available_timestamp, n.provenance, s.status FROM kb_nodes n LEFT JOIN finding_status s "
                                "ON s.node_id=n.id WHERE n.domain='agent_finding' ORDER BY n.created DESC LIMIT ?", (limit,))],
    }


def _short_summary(s):
    try:
        d = json.loads(s or "{}")
    except ValueError:
        return {}
    keep = ("error", "extracted", "events_published", "by_source", "anomalies", "failing_collectors", "issues_detected", "new_issues", "incidents_consumed",
            "messages_consumed", "retrieved", "observations", "valid", "problems", "finding", "evidence_linked", "rechecked")
    out = {k: d[k] for k in keep if k in d}
    if isinstance(out.get("anomalies"), list):
        out["anomalies"] = len(out["anomalies"])
    if "hypothesis" in d:
        h = d["hypothesis"]
        out["hypothesis"] = {k: h.get(k) for k in ("relationship_id", "relationship", "direction", "horizon_days", "confidence") if k in h}
    if "evaluation" in d:
        out["evaluation"] = {k: d["evaluation"].get(k) for k in ("status", "experiment", "outcome", "reason")}
    return out


def search(conn, query_vec, as_of_epoch: int, limit: int = 8) -> list:
    """Cosine similarity over nodes with available_epoch <= as_of_epoch only."""
    try:
        src = _src(conn)
        rows = conn.execute("SELECT n.id,n.domain,n.title,n.document,n.available_timestamp,n.source_id,n.raw_payload_hash,n.provenance,n.embedding "
                            f"FROM {src} n WHERE {_asof(src)} AND n.embedding IS NOT NULL", {"t": as_of_epoch}).fetchall()
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
        src = _src(conn)
        doms = dict(conn.execute(f"SELECT n.domain, COUNT(*) FROM {src} n WHERE {_asof(src)} GROUP BY n.domain", {"t": as_of_epoch}).fetchall())
        edges = conn.execute("SELECT COUNT(*) FROM kb_edges").fetchone()[0]
        latest = conn.execute(f"SELECT n.title, n.available_timestamp, n.domain FROM {src} n WHERE {_asof(src)} ORDER BY n.available_epoch DESC LIMIT 5", {"t": as_of_epoch}).fetchall()
    except sqlite3.OperationalError:
        return {"status": "empty", "nodes": 0, "edges": 0, "domains": {}, "latest": []}
    return {"status": "ok" if doms else "empty", "nodes": sum(doms.values()), "edges": edges, "domains": doms,
            "latest": [{"title": t, "available_timestamp": a, "domain": d} for t, a, d in latest]}


if __name__ == "__main__":
    db = os.environ.get("DB_PATH") or str(BASE_DIR / "henry_hub_pit.db")
    print("SQLite graph only (run POST /kb/ingest on the hub to also update the vector store):", file=sys.stderr)
    print(json.dumps(ingest(db), indent=1))
