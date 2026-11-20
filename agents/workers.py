"""The research agents. Each one has a narrow job, uses the local Ollama layer only where language understanding is needed
(with a deterministic fallback when the model is unavailable or its answer fails validation), talks to the others through
the message bus, and reads/writes the shared knowledge library.

  DiagnosticsAgent    collector_runs failures -> Ollama classifies the error (regex fallback) -> 'incident' message + finding
  DataQualityAgent    deterministic PIT checks (stale series, unexpected revisions, duplicate vintages) -> Ollama investigates
                      the likely cause from the collector record (rule fallback) -> 'data_quality' message + finding + owner alert
  RepairAgent         consumes 'incident' messages -> bounded self-healing assistance: selector agents get a dry-run repair
                      proposal validated on preserved fixtures (selfheal_pipeline.repair, never merged here); parser-based
                      collectors get a structured repair suggestion. Never edits code, never opens or merges a PR by itself.
  NoticeAnalystAgent  new pipeline notices (source documents) -> source-labelled event type + Ollama structured extraction
                      (severity, location, summary; rule fallback) -> notice_extractions -> 'pipeline_event' messages
  AnomalyAgent        deterministic z-scores on PIT series -> retrieves related knowledge -> Ollama interpretation ->
                      'anomaly' message + finding (all numbers from the database)
  SynthesisAgent      consumes pipeline_event / anomaly / data_quality messages and earlier findings + structured PIT
                      observations -> semantic retrieval across domains -> Ollama picks ONE relationship from a catalogue of
                      cross-domain relationships the platform can measure, with direction, horizon, rationale, contradictory
                      evidence and confidence -> deterministic checks (cited evidence exists, numbers grounded, direction agrees
                      with the observations) -> Section 5.4 hypothesis finding -> PIT walk-forward evaluation when a
                      quantitative model exists. Earlier findings are re-checked against the current rules (finding_status).

Rules: the model never produces a market number (numbers_grounded rejects any it was not given); every finding cites the
knowledge objects it used (evidence_for edges); everything is point-in-time at `as_of`.
"""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

import kb_ingest
import markets_engine as me
from agents import memory, quant_risk, retrieval_hub
from agents.llm import LLM, REASONING_MODEL, numbers_grounded, status as llm_status

ROOT = Path(__file__).resolve().parent.parent
DOMAINS = ["natural_gas", "ngl", "lng", "electricity", "weather", "pipelines", "storage", "production", "crude_oil", "coal", "carbon"]


def _has(conn, table):
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())


def _dt(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ----------------------------------------------------------------------------- diagnostics
_DIAG_RULES = [  # (regex on the error text, category, fix) - deterministic fallback and cross-check
    (r"429|rate.?limit|slowdown|too many requests", "rate_limited", "Back off and retry after the source's rate-limit window."),
    (r"timed? ?out|connecterror|connection (refused|reset)|name or service not known|temporary failure|network", "network",
     "Retry later; check connectivity to the source host."),
    (r"\b(5\d\d)\b|server error|service unavailable|bad gateway", "upstream_http_error", "Source returned a server error; retry on the next schedule."),
    (r"\b(40[034])\b|http[^\n]{0,40}(not found|forbidden)", "upstream_http_error", "Source URL or access changed; confirm the published location."),
    (r"layout|selector|column|header|table|lookuperror|no match|unexpected format|keyerror", "layout_change",
     "Source layout changed; update the parser and add the new page as a fixture."),
    (r"gatekeeper|out of range|outside expected|rejected|validation", "validation_rejected", "Value failed the validation gate; inspect the source revision."),
    (r"traceback|typeerror|attributeerror|nameerror|valueerror|indexerror", "code_error", "Collector code error; reproduce with the preserved payload and fix."),
]


def classify_error_rules(detail: str) -> dict:
    d = (detail or "").lower()
    for rx, cat, fix in _DIAG_RULES:
        if re.search(rx, d):
            return {"category": cat, "likely_fix": fix}
    return {"category": "unknown", "likely_fix": "Inspect the collector log and the preserved payload."}


class DiagnosticsAgent:
    name = "diagnostics"
    VERSION = "diag-2"
    SCHEMA = {"type": "object", "properties": {
        "category": {"type": "string", "enum": ["network", "upstream_http_error", "layout_change", "validation_rejected", "code_error", "rate_limited", "unknown"]},
        "likely_fix": {"type": "string", "maxLength": 300}}, "required": ["category", "likely_fix"]}

    def run(self, conn, llm: LLM, as_of: str, collection=None) -> dict:
        rows = conn.execute("SELECT r.id, r.name, r.started, r.detail FROM collector_runs r WHERE r.ok=0 AND r.id=(SELECT MAX(id) FROM collector_runs q "
                            "WHERE q.name=r.name AND q.started<=?) AND r.started<=?", (as_of, as_of)).fetchall() if _has(conn, "collector_runs") else []
        out = []
        for rid, name, started, detail in rows:
            if conn.execute("SELECT 1 FROM agent_messages WHERE topic='incident' AND ref=?", (f"{name}:{rid}",)).fetchone():
                continue                                           # this failed run was already diagnosed
            prompt = (f"A market-data collector named {name} failed at {started}. Error output:\n{(detail or '')[:1500]}\n"
                      "Classify the failure and give a one-sentence likely fix. Do not invent details not present in the error.")
            res = llm.json("diagnose", prompt, self.SCHEMA, fallback=lambda: classify_error_rules(detail), version=self.VERSION)
            source = llm.last_source
            body = (f"Collector {name} failed at {started}. Classified as {res['category']} ({'model' if source == 'model' else 'rule fallback'}). "
                    f"Likely fix: {res['likely_fix']} Error: {(detail or '')[:300]}")
            f = memory.add_finding(conn, llm, self.name, f"Collector {name}: {res['category']}", body, as_of, [], "extracted_estimate", "diagnosis", collection)
            memory.publish(conn, self.name, "incident", {"collector": name, "run_id": rid, "category": res["category"], "likely_fix": res["likely_fix"],
                                                         "detail": (detail or "")[:1500], "finding": f["id"], "source": source}, ref=f"{name}:{rid}")
            out.append({"collector": name, **res, "finding": f["id"], "source": source})
        return {"failing_collectors": len(rows), "diagnoses": out}


# ----------------------------------------------------------------------------- data quality
SOURCE_COLLECTOR = {  # pit_market_data.source_id -> collectors/run_all.py job that produces it
    "noaa_cpc_degree_days": "cpc_heating", "noaa_cpc_degree_days_history": "cpc_heating", "eia_wngsr": "eia_storage", "eia_dnav_ng": "eia_prices",
    "noaa_gfs_open_data": "gfs_hdd", "ecmwf_open_data": "ecmwf_hdd", "eia_ng_bulk": "eia_ng_monthly", "rggi_auction_results": "rggi_auctions",
    "eia_steo_bulk": "steo_production", "eia_dnav_pet": "eia_petroleum_spot", "eia_coal_markets": "eia_coal_spot",
    "eia_coal_transportation": "eia_coal_rail", "eia930_balance": "eia930_power_burn"}


class DataQualityAgent:
    """Deterministic detection; the model only explains the likely cause from the collector record (rule fallback)."""
    name = "data_quality"
    VERSION = "dq-1"
    CAUSES = ["source_publication_schedule", "collector_failure", "source_revision", "upstream_outage", "parser_error", "expected_behavior", "unknown"]
    ACTIONS = ["none", "monitor", "rerun_collector", "investigate_parser", "open_incident"]
    SCHEMA = {"type": "object", "properties": {"likely_cause": {"type": "string", "enum": CAUSES}, "explanation": {"type": "string", "maxLength": 400},
                                               "action": {"type": "string", "enum": ACTIONS}}, "required": ["likely_cause", "explanation", "action"]}
    SKIP_QUALITY = ("historical_only", "unverified_seed")

    ALLOWED = {  # likely causes consistent with each detected issue type; anything else is rejected and the rules decide
        "stale": {"source_publication_schedule", "collector_failure", "upstream_outage", "unknown"},
        "revision": {"source_revision", "parser_error", "unknown"},
        "duplicate": {"parser_error", "unknown"},
    }

    def __init__(self, max_investigations: int = 5, revision_pct: float = 10.0):
        self.max_investigations, self.revision_pct = max_investigations, revision_pct

    def detect(self, conn, as_of: str) -> list:
        issues = []
        cutoff = _dt(as_of)
        rows = conn.execute("SELECT agent_id, source_id, MIN(COALESCE(quality_status,'')) FROM pit_market_data WHERE available_timestamp<=? "
                            "AND COALESCE(provenance,'measured')='measured' AND source_id IS NOT NULL AND source_id<>'' GROUP BY agent_id", (as_of,)).fetchall()
        for agent, src, q in rows:
            latest_q = conn.execute("SELECT quality_status FROM pit_market_data WHERE agent_id=? AND available_timestamp<=? ORDER BY available_timestamp DESC "
                                    "LIMIT 1", (agent, as_of)).fetchone()[0] or ""
            if latest_q.startswith(self.SKIP_QUALITY):
                continue                                        # discontinued source: staleness is expected and documented
            avail = [r[0] for r in conn.execute("SELECT DISTINCT available_timestamp FROM pit_market_data WHERE agent_id=? AND available_timestamp<=? "
                                                "ORDER BY 1 DESC LIMIT 41", (agent, as_of))]
            if len(avail) >= 6:
                gaps = [(_dt(a) - _dt(b)).total_seconds() / 86400 for a, b in zip(avail, avail[1:])]
                cadence = max(statistics.median(gaps), 0.5)
                age = (cutoff - _dt(avail[0])).total_seconds() / 86400
                if age > max(3 * cadence, cadence + 4):
                    issues.append({"type": "stale", "agent": agent, "source_id": src, "ref": f"stale:{agent}:{avail[0][:10]}",
                                   "fact": f"{agent} last became available {avail[0]}, {age:.1f} days before the cutoff {as_of}; "
                                           f"its median publication interval is {cadence:.1f} days."})
        lo = _iso(cutoff - timedelta(days=14))
        scales = {}
        for agent, tgt, n, vmin, vmax, last in conn.execute(
                "SELECT agent_id, target_timestamp, COUNT(DISTINCT value), MIN(value), MAX(value), MAX(available_timestamp) FROM pit_market_data "
                "WHERE available_timestamp<=? AND COALESCE(provenance,'measured')='measured' GROUP BY agent_id, target_timestamp "
                "HAVING COUNT(DISTINCT value)>1 AND MAX(available_timestamp)>?", (as_of, lo)):
            if agent not in scales:      # typical magnitude of the series (median |value| of its last 365 observations), PIT
                vals = [abs(r[0]) for r in conn.execute("SELECT value FROM pit_market_data WHERE agent_id=? AND available_timestamp<=? "
                                                        "ORDER BY target_timestamp DESC LIMIT 365", (agent, as_of))]
                scales[agent] = max(statistics.median(vals) if vals else 0.0, 1e-6)
            pct = abs(vmax - vmin) / scales[agent] * 100
            if pct >= self.revision_pct:
                seq = [f"{v:g} (available {a})" for v, a in conn.execute(
                    "SELECT value, available_timestamp FROM pit_market_data WHERE agent_id=? AND target_timestamp=? AND available_timestamp<=? "
                    "ORDER BY available_timestamp", (agent, tgt, as_of))]
                issues.append({"type": "revision", "agent": agent, "ref": f"revision:{agent}:{tgt[:10]}:{last[:10]}",
                               "fact": f"{agent} for target {tgt[:10]} was revised across vintages: {' -> '.join(seq)}. The spread is {pct:.0f}% of the "
                                       f"series' typical magnitude ({scales[agent]:.4g}). Every vintage is preserved."})
        for agent, tgt, av, n in conn.execute("SELECT agent_id, target_timestamp, available_timestamp, COUNT(*) FROM pit_market_data WHERE available_timestamp<=? "
                                              "GROUP BY agent_id, target_timestamp, available_timestamp HAVING COUNT(*)>1 LIMIT 20", (as_of,)):
            issues.append({"type": "duplicate", "agent": agent, "ref": f"duplicate:{agent}:{tgt[:10]}:{av}",
                           "fact": f"{agent} has {n} rows for target {tgt[:10]} with the same availability time {av} (duplicate vintage)."})
        return issues

    @staticmethod
    def rules(issue: dict, last_run) -> dict:
        if issue["type"] == "stale":
            if last_run and not last_run[1]:
                return {"likely_cause": "collector_failure", "explanation": "The most recent run of the owning collector failed.", "action": "rerun_collector"}
            return {"likely_cause": "source_publication_schedule", "explanation": "The collector ran successfully; the source has not published newer data.",
                    "action": "monitor"}
        if issue["type"] == "revision":
            return {"likely_cause": "source_revision", "explanation": "The source revised a previously published value; both vintages are preserved.",
                    "action": "monitor"}
        return {"likely_cause": "parser_error", "explanation": "Duplicate rows for one vintage indicate a repeated insert.", "action": "investigate_parser"}

    def _collector_run(self, conn, issue, as_of):
        name = SOURCE_COLLECTOR.get(issue.get("source_id") or "")
        if not name or not _has(conn, "collector_runs"):
            return None
        return conn.execute("SELECT name, ok, started, detail FROM collector_runs WHERE name=? AND started<=? ORDER BY id DESC LIMIT 1",
                            (name, as_of)).fetchone()

    def recheck(self, conn, as_of: str) -> dict:
        """Earlier data-quality findings whose stated cause is impossible for their issue type are superseded (text kept)."""
        counts = {}
        for f in memory.findings(conn, as_of, 500, kinds=("data_quality",)):
            if f["status"] != "unchecked":
                continue
            t, c = re.search(r"Data-quality issue \((\w+)\)", f["document"]), re.search(r"Likely cause: (\w+)", f["document"])
            if not (t and c and t.group(1) in self.ALLOWED):
                continue
            ok = c.group(1) in self.ALLOWED[t.group(1)]
            memory.set_status(conn, f["id"], "valid" if ok else "superseded",
                              f"cause {c.group(1)} {'consistent' if ok else 'inconsistent'} with a {t.group(1)} issue ({self.VERSION} rules)", self.VERSION)
            counts["valid" if ok else "superseded"] = counts.get("valid" if ok else "superseded", 0) + 1
        return counts

    def _reported(self, conn, ref: str) -> bool:
        """True when this issue already has a live (not superseded) investigation."""
        for (payload,) in conn.execute("SELECT payload FROM agent_messages WHERE topic='data_quality' AND ref=?", (ref,)):
            fid = json.loads(payload).get("finding")
            st = conn.execute("SELECT status FROM finding_status WHERE node_id=?", (fid,)).fetchone()
            if not st or st[0] != "superseded":
                return True
        return False

    def run(self, conn, llm: LLM, as_of: str, collection=None) -> dict:
        rechecked = self.recheck(conn, as_of)
        issues = self.detect(conn, as_of)
        new = [i for i in issues if not self._reported(conn, i["ref"])]
        out = []
        for i in new[: self.max_investigations]:
            run = self._collector_run(conn, i, as_of)
            ctx = (f"Last run of collector {run[0]} at {run[2]}: {'ok' if run[1] else 'FAILED'}; detail: {str(run[3])[:600]}" if run
                   else "No collector run record matches this series.")
            prompt = (f"A deterministic data-quality check on a point-in-time market database found an issue.\nISSUE ({i['type']}): {i['fact']}\n"
                      f"COLLECTOR RECORD: {ctx}\n\nExplain the most likely cause in one sentence using only the facts above, and choose an action. "
                      f"For a {i['type']} issue the likely cause must be one of: {', '.join(sorted(self.ALLOWED[i['type']]))}. "
                      "A source that simply has not published yet is source_publication_schedule; a changed value for an already published "
                      "date is source_revision unless the collector record shows a parsing problem.")
            allowed = self.ALLOWED[i["type"]]
            res = llm.json("investigate", prompt, self.SCHEMA, fallback=lambda: self.rules(i, run), version=self.VERSION,
                           validate=lambda o: None if o["likely_cause"] in allowed else f"cause {o['likely_cause']} inconsistent with a {i['type']} issue")
            source = llm.last_source
            if source == "model" and numbers_grounded(res["explanation"], prompt):
                res, source = self.rules(i, run), "fallback"         # invented numbers -> deterministic explanation
            body = f"Data-quality issue ({i['type']}): {i['fact']} Likely cause: {res['likely_cause']}. {res['explanation']} Action: {res['action']}."
            f = memory.add_finding(conn, llm, self.name, f"Data quality: {i['type']} {i['agent']}", body, as_of, [], "extracted_estimate", "data_quality",
                                   collection, {"agent_ids": i["agent"]})
            memory.publish(conn, self.name, "data_quality", {**i, **res, "finding": f["id"], "source": source}, ref=i["ref"])
            out.append({"type": i["type"], "agent": i["agent"], **res, "source": source, "finding": f["id"]})
        if out and _notify_enabled():
            import notify
            notify.event("data-quality", f"{len(out)} data-quality issue(s) as of {as_of}",
                         "\n".join(f"- `{o['agent']}` {o['type']}: {o['likely_cause']} -> {o['action']}" for o in out))
        return {"issues_detected": len(issues), "new_issues": len(new), "investigated": out, "rechecked": rechecked}


def _notify_enabled() -> bool:
    import os
    return os.environ.get("NOTIFY", "1") != "0"


# ----------------------------------------------------------------------------- bounded self-healing assistance
COLLECTOR_MODULE = {"cpc_heating": "cpc_degree_days", "cpc_cooling": "cpc_degree_days", "cpc_heating_prev_year": "cpc_degree_days",
                    "cpc_cooling_prev_year": "cpc_degree_days"}


class RepairAgent:
    name = "repair"
    VERSION = "repair-1"
    SCHEMA = {"type": "object", "properties": {"function": {"type": "string", "maxLength": 80}, "change": {"type": "string", "maxLength": 400},
                                               "test": {"type": "string", "maxLength": 300}, "risk": {"type": "string", "enum": ["low", "medium", "high"]}},
              "required": ["function", "change", "test", "risk"]}
    REPAIRABLE = ("layout_change", "validation_rejected", "code_error")

    def __init__(self, selector_repair=None):
        self.selector_repair = selector_repair       # injectable for tests; defaults to selfheal_pipeline.repair(dry_run=True)

    def run(self, conn, llm: LLM, as_of: str, collection=None) -> dict:
        msgs = memory.consume(conn, self.name, ["incident"], 20)
        reg = json.loads((ROOT / "ingestion" / "selectors.json").read_text()) if (ROOT / "ingestion" / "selectors.json").exists() else {}
        by_collector = {cfg["collector"]: agent for agent, cfg in reg.items()}
        out = []
        for m in msgs:
            p = m["payload"]
            name, cat = p.get("collector", ""), p.get("category", "")
            if cat not in self.REPAIRABLE:
                out.append({"collector": name, "action": "none", "reason": f"category {cat} is not a parser problem"})
                continue
            if name in by_collector:
                page = p.get("page_path")
                pth = (ROOT / page).resolve() if page else None
                if not pth or ROOT.resolve() not in pth.parents or not pth.is_file():
                    out.append({"collector": name, "action": "needs_page", "reason": "no captured failing page in the incident"})
                    continue
                fn = self.selector_repair or self._dry_run_repair
                rep = fn(by_collector[name], pth.read_text(errors="replace"),
                         lambda prompt, schema: llm.json("diagnose", prompt, schema, version=self.VERSION))
                body = (f"Selector repair proposal for {by_collector[name]} (dry run, not merged): stage {rep.get('stage')}, ok {rep.get('ok')}, "
                        f"selectors {rep.get('selectors_after')}, fixture validation {json.dumps(rep.get('validation', {}))[:300]}.")
                f = memory.add_finding(conn, llm, self.name, f"Repair proposal: {by_collector[name]}", body, as_of, [p.get("finding")] if p.get("finding") else [],
                                       "model_hypothesis", "repair_proposal", collection)
                memory.publish(conn, self.name, "repair_proposal", {"collector": name, "agent": by_collector[name], "ok": rep.get("ok"),
                                                                    "stage": rep.get("stage"), "finding": f["id"]}, ref=m["ref"])
                out.append({"collector": name, "action": "selector_proposal", "ok": rep.get("ok"), "finding": f["id"]})
                continue
            mod = ROOT / "collectors" / f"{COLLECTOR_MODULE.get(name, name)}.py"
            if not mod.is_file():
                out.append({"collector": name, "action": "none", "reason": "collector source not found"})
                continue
            src = mod.read_text()[:3500]
            prompt = (f"Collector {name} failed with category {cat}. Error:\n{p.get('detail', '')[:1200]}\n\nCollector source (truncated):\n{src}\n\n"
                      "Propose the smallest code change that would fix this failure: the function to change, the change in one or two sentences, "
                      "and a unit test that would prove it using a preserved source payload. Do not invent source fields not visible above.")
            res = llm.json("diagnose", prompt, self.SCHEMA, version=self.VERSION, fallback=lambda: {
                "function": "collect", "change": f"Manual fix required: {p.get('likely_fix', 'inspect the preserved payload')}",
                "test": "Add the failing payload as a fixture and assert the parsed values.", "risk": "medium"})
            body = (f"Repair suggestion for collector {name} ({cat}); model-generated, never applied automatically. Function: {res['function']}. "
                    f"Change: {res['change']} Test: {res['test']} Risk: {res['risk']}. A human-reviewed pull request is required.")
            f = memory.add_finding(conn, llm, self.name, f"Repair suggestion: {name}", body, as_of, [p["finding"]] if p.get("finding") else [],
                                   "model_hypothesis", "repair_proposal", collection)
            memory.publish(conn, self.name, "repair_proposal", {"collector": name, "finding": f["id"], "source": llm.last_source}, ref=m["ref"])
            out.append({"collector": name, "action": "code_suggestion", "source": llm.last_source, "finding": f["id"]})
        return {"incidents_consumed": len(msgs), "proposals": out}

    @staticmethod
    def _dry_run_repair(agent_id, html, llm_callable):
        import selfheal_pipeline
        return selfheal_pipeline.repair(agent_id, html, dry_run=True, llm=llm_callable)


# ----------------------------------------------------------------------------- pipeline notices
_NOTICE_TYPES = [  # source "Type:" label -> event type (the source's own classification wins over the model)
    (r"FORCE MAJEURE", "force_majeure"), (r"OPERATIONAL FLOW|\bOFO\b", "operational_flow_order"),
    (r"CAPACITY CONSTRAINT|RESTRICTION|CURTAIL|ALLOCATION", "capacity_restriction"), (r"MAINTENANCE|OUTAGE|REPAIR", "maintenance"),
    (r"GAS QUALITY|QUALITY", "gas_quality"), (r"OVER-UNDER|IMBALANCE|PERFORMANCE", "imbalance_or_performance"),
    (r"PIPELINE CONDITION|SYSTEM CONDITION|CONDITIONS", "pipeline_conditions"),
]
_HIGH_EVIDENCE = re.compile(r"FORCE MAJEURE|UNPLANNED|EMERGENCY|CURTAIL|RUPTURE|FAILURE|\bCUT\b|CUTS\b|OUTAGE", re.I)


def notice_type(body: str) -> str | None:
    m = re.search(r"Type:\s*([^;.]+)", body or "")
    label = (m.group(1) if m else "").upper()
    for rx, et in _NOTICE_TYPES:
        if label and re.search(rx, label):
            return et
    return None


def classify_notice_rules(title: str, body: str) -> dict:
    et = notice_type(body)
    if not et:
        up = f"{title} {body}".upper()
        et = next((t for rx, t in _NOTICE_TYPES if re.search(rx, up)), "commercial_or_other")
    sev = {"force_majeure": "high", "operational_flow_order": "medium", "capacity_restriction": "medium", "maintenance": "medium"}.get(et, "low")
    if et == "maintenance" and re.search(r"UNPLANNED|EMERGENCY", body or "", re.I):
        sev = "high"
    subj = re.search(r"Subject:\s*([^.]+)", body or "")
    return {"event_type": et, "severity": sev, "location": "not stated", "summary": (subj.group(1) if subj else title)[:160]}


class NoticeAnalystAgent:
    name = "notice_analyst"
    SCHEMA = {"type": "object", "properties": {
        "event_type": {"type": "string", "enum": ["force_majeure", "maintenance", "capacity_restriction", "pipeline_conditions", "gas_quality",
                                                  "operational_flow_order", "imbalance_or_performance", "commercial_or_other"]},
        "severity": {"type": "string", "enum": ["low", "medium", "high"]},
        "location": {"type": "string", "maxLength": 120},
        "summary": {"type": "string", "maxLength": 200}}, "required": ["event_type", "severity", "location", "summary"]}

    VERSION = 3   # bump when the prompt/rubric changes: older extractions are redone

    def __init__(self, per_run: int = 25):
        self.per_run = per_run

    def run(self, conn, llm: LLM, as_of: str, collection=None) -> dict:
        conn.execute("CREATE TABLE IF NOT EXISTS notice_extractions(document_id TEXT PRIMARY KEY, pipeline TEXT, event_type TEXT, severity TEXT, "
                     "location TEXT, summary TEXT, posted TEXT, model TEXT, extracted_at TEXT, grounded INTEGER)")
        if not _has(conn, "documents"):
            return {"extracted": 0}
        cols = {r[1] for r in conn.execute("PRAGMA table_info(notice_extractions)")}
        for col, decl in (("version", "INTEGER DEFAULT 1"), ("checks", "TEXT")):
            if col not in cols:
                conn.execute(f"ALTER TABLE notice_extractions ADD COLUMN {col} {decl}")
        docs = conn.execute("SELECT id, source_id, title, body, available_timestamp FROM documents d WHERE domain='pipeline_notice' AND available_timestamp<=? "
                            "AND NOT EXISTS (SELECT 1 FROM notice_extractions e WHERE e.document_id=d.id AND COALESCE(e.version,1)>=?) "
                            "ORDER BY available_timestamp DESC LIMIT ?", (as_of, self.VERSION, self.per_run)).fetchall()
        n, events, by_source = 0, [], {"model": 0, "fallback": 0}
        for did, src, title, body, posted in docs:
            prompt = ("Extract the operational meaning of this interstate natural gas pipeline notice. Use only what the notice says; "
                      "if no location (station, segment, zone, meter or point) is named, answer 'not stated'. Keep the summary under 25 words "
                      "and do not copy timestamps into it.\n"
                      "Severity rubric (apply strictly):\n"
                      "- high: force majeure, unplanned outage, or a curtailment/cut that removes firm capacity.\n"
                      "- medium: a capacity restriction, constraint or planned maintenance that limits interruptible or secondary flows.\n"
                      "- low: routine daily pipeline-conditions postings, confirmations, imbalance or over/under-performance updates, "
                      "informational or commercial notices.\n\nNOTICE:\n" + body)
            res = llm.json("extract", prompt, self.SCHEMA, fallback=lambda: classify_notice_rules(title, body), version=f"notice-{self.VERSION}")
            source = llm.last_source
            by_source[source] = by_source.get(source, 0) + 1
            checks = []
            src_type = notice_type(body)
            if src_type and res["event_type"] != src_type:              # the source's own classification wins over the model
                checks.append(f"event_type {res['event_type']}->{src_type} (source label)")
                res["event_type"] = src_type
            if src_type == "force_majeure" and res["severity"] != "high":
                checks.append("severity->high (force majeure)")
                res["severity"] = "high"
            if res["severity"] == "high" and not _HIGH_EVIDENCE.search(body):
                checks.append("severity high->medium (no outage/curtailment/force-majeure wording)")
                res["severity"] = "medium"
            if res["location"].strip() and res["location"].lower() != "not stated" and res["location"].lower() not in body.lower():
                checks.append("location not found in notice -> not stated")
                res["location"] = "not stated"
            grounded = not numbers_grounded(res["summary"] + " " + res["location"], body)
            pipe = src.replace("kinder_morgan_notices_", "").upper()
            conn.execute("INSERT OR REPLACE INTO notice_extractions(document_id,pipeline,event_type,severity,location,summary,posted,model,extracted_at,"
                         "grounded,version,checks) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         (did, pipe, res["event_type"], res["severity"], res["location"][:120], res["summary"][:300], posted,
                          REASONING_MODEL if source == "model" else "rules_v1", memory.now(), int(grounded), self.VERSION, "; ".join(checks)))
            n += 1
            already = conn.execute("SELECT 1 FROM agent_messages WHERE topic='pipeline_event' AND ref=?", (did,)).fetchone()
            if (res["event_type"] == "force_majeure" or res["severity"] == "high") and not already:
                kb_id = kb_ingest.node_id("pipeline_notice", f"document_{src}:{did}")
                memory.publish(conn, self.name, "pipeline_event", {"document": did, "pipeline": pipe, "event_type": res["event_type"],
                                                                   "severity": res["severity"], "location": res["location"], "posted": posted,
                                                                   "summary": res["summary"], "kb_node": kb_id}, ref=did)
                events.append(did)
        conn.commit()
        return {"extracted": n, "events_published": len(events), "by_source": by_source}


# ----------------------------------------------------------------------------- anomalies
SERIES = [  # agent, label, domain, transform
    ("Agent_HH_Spot_EIA", "Henry Hub spot", "natural_gas", "diff"),
    ("Agent_NGL_MontBelvieu_Propane", "Mont Belvieu propane", "ngl", "diff"),
    ("Agent_Crude_WTI_Spot", "WTI crude", "crude_oil", "diff"),
    ("Agent_Demand_PowerBurn", "US48 gas-fired generation", "electricity", "level"),
    ("Agent_Weather_Actual_HDD", "CONUS heating degree days", "weather", "level"),
    ("Agent_Coal_CAPP_SpotPrice", "Central Appalachian coal spot", "coal", "diff"),
]


def zscore(values: list, transform: str, window: int = 250):
    """Latest observation's z-score against the trailing window (excluding itself). diff = day-over-day change."""
    x = [b - a for a, b in zip(values, values[1:])] if transform == "diff" else list(values)
    if len(x) < 60:
        return None
    hist, last = x[-window - 1:-1], x[-1]
    mu = sum(hist) / len(hist)
    sd = math.sqrt(sum((v - mu) ** 2 for v in hist) / (len(hist) - 1)) if len(hist) > 1 else 0
    return None if sd <= 0 else (last - mu) / sd, last, mu, sd


class AnomalyAgent:
    name = "anomaly"
    VERSION = "anomaly-2"
    SCHEMA = {"type": "object", "properties": {
        "interpretation": {"type": "string", "maxLength": 500},
        "related_domains": {"type": "array", "items": {"type": "string", "enum": DOMAINS}},
        "evidence_ids": {"type": "array", "items": {"type": "string"}}}, "required": ["interpretation", "related_domains", "evidence_ids"]}

    def __init__(self, threshold: float = 2.5):
        self.threshold = threshold

    def run(self, conn, llm: LLM, as_of: str, collection=None) -> dict:
        out = []
        for agent, label, domain, tr in SERIES:
            s = me.load_series(conn, agent, as_of)                     # measured, latest vintage, available <= as_of
            if len(s) < 60:
                continue
            z = zscore([v for _, v, _ in s], tr)
            if not z or abs(z[0]) < self.threshold:
                continue
            zv, last, mu, sd = z
            day = s[-1][0]
            if conn.execute("SELECT 1 FROM agent_messages WHERE topic='anomaly' AND ref=?", (f"{agent}:{day}",)).fetchone():
                continue                                               # already reported on an earlier run
            fact = (f"{label} on {day}: {'change' if tr == 'diff' else 'level'} {last:.3f} versus trailing mean {mu:.3f} "
                    f"(standard deviation {sd:.3f}), z-score {zv:.2f}.")
            hits = memory.search(conn, llm, f"{label} unusual move {domain}", as_of, 6)
            ctx = "\n".join(f"[{h['id']}] ({h['domain']}, {h['available_timestamp'][:10]}) {h['title']}: {h['document'][:300]}" for h in hits)
            prompt = (f"A deterministic check flagged an anomaly.\nFACT: {fact}\n\nRelated knowledge (ids in brackets):\n{ctx}\n\n"
                      "In two sentences, interpret what this could mean for related markets, citing only the ids you used. "
                      "Use no numbers except ones in the FACT or the knowledge.")
            res = llm.json("interpret", prompt, self.SCHEMA, version=self.VERSION,
                           fallback=lambda: {"interpretation": "", "related_domains": [], "evidence_ids": []})
            ids = [i for i in res["evidence_ids"] if i in {h["id"] for h in hits}]
            bad = numbers_grounded(res["interpretation"], fact + ctx)
            if llm.last_source != "model":
                text = "(no model interpretation: local model unavailable; deterministic fact only)"
            else:
                text = res["interpretation"] if not bad else "(model interpretation withheld: it contained numbers not present in the evidence)"
            body = f"{fact} Interpretation (model hypothesis, not an observation): {text}"
            f = memory.add_finding(conn, llm, self.name, f"Anomaly: {label} {day} (z {zv:.1f})", body, as_of, ids, "model_hypothesis", "anomaly", collection,
                                   {"agent_ids": agent})
            memory.publish(conn, self.name, "anomaly", {"agent": agent, "label": label, "domain": domain, "date": day, "z": round(zv, 2),
                                                        "related_domains": res["related_domains"], "finding": f["id"]}, ref=f"{agent}:{day}")
            out.append({"series": agent, "date": day, "z": round(zv, 2), "finding": f["id"], "grounded": not bad, "source": llm.last_source})
        return {"anomalies": out}


# ----------------------------------------------------------------------------- risk engine connection (Spec 4 integration)
class QuantRiskAgent:
    """Connects the risk engine (agents/quant_risk.py) into the agent system: VaR/ES on the Henry Hub spot
    series, with a 'risk_alert' message + finding when the expected tail loss is material (any positive tail)."""
    name = "quant_risk"

    def run(self, conn, llm: LLM, as_of: str, collection=None) -> dict:
        s = me.load_series(conn, "Agent_HH_Spot_EIA", as_of)
        returns = [s[i][1] / s[i - 1][1] - 1 for i in range(1, len(s)) if s[i - 1][1]] if s else []
        metrics = {"hh_spot": s[-1][1] if s else None, "hh_spot_available_timestamp": s[-1][2] if s else None}
        if returns:
            for k in ("var_parametric", "var_historical", "var_montecarlo", "cvar_parametric", "cvar_historical"):
                metrics[k] = round(getattr(quant_risk, k)(returns, 0.05), 4)
            metrics["liquidity_buffer"] = round(quant_risk.liquidity_buffer(metrics["var_historical"]), 4)
        alerts = [k for k in ("var_parametric", "var_historical", "var_montecarlo", "cvar_parametric", "cvar_historical")
                  if metrics.get(k) and metrics[k] > 0.05]
        out = {"alerts": alerts, "metrics": {k: v for k, v in metrics.items() if v is not None}}
        if alerts and metrics["hh_spot"]:
            body = (f"HH spot series shows tail risk at the cutoff {as_of}: {', '.join(alerts)}. "
                    f"Latest spot: {metrics['hh_spot']} (available {metrics['hh_spot_available_timestamp']}).")
            f = memory.add_finding(conn, llm, self.name, f"Risk alert: HH spot tail risk {max(metrics[k] for k in alerts):.3f}",
                                   body, as_of, [], "model_hypothesis", "risk_alert", collection)
            memory.publish(conn, self.name, "risk_alert", {"alerts": alerts, "finding": f["id"]}, ref=f"HH_Spot_EIA:{as_of[:10]}")
        return out


# ----------------------------------------------------------------------------- structured PIT observations
def _normal_hdd(conn, dates: list, as_of: str) -> dict:
    """30-year normal HDD per target date, latest vintage available at as_of (provenance extracted_estimate: derived normals)."""
    if not dates:
        return {}
    q = ("SELECT substr(target_timestamp,1,10), value FROM pit_market_data p WHERE agent_id='Agent_Weather_30YrNormal_HDD' AND available_timestamp<=? "
         "AND substr(target_timestamp,1,10) IN (%s) AND available_timestamp=(SELECT MAX(available_timestamp) FROM pit_market_data q WHERE "
         "q.agent_id=p.agent_id AND q.target_timestamp=p.target_timestamp AND q.available_timestamp<=?)") % ",".join("?" * len(dates))
    return {d: v for d, v in conn.execute(q, (as_of, *dates, as_of))}


def observations(conn, as_of: str) -> dict:
    """Deterministic, point-in-time facts the synthesis agent reasons over. Every value is read with available_timestamp <= as_of."""
    obs = {}

    def put(key, label, value, unit, date, avail, agents, extra=""):
        obs[key] = {"label": label, "value": round(value, 4), "unit": unit, "date": date, "available_timestamp": avail, "agents": agents,
                    "text": f"{label}: {value:.3f} {unit} (as of {date}, available {avail}){extra}"}

    hh = me.load_series(conn, "Agent_HH_Spot_EIA", as_of)
    if len(hh) > 21:
        put("hh", "Henry Hub spot", hh[-1][1], "USD/MMBtu", hh[-1][0], hh[-1][2], ["Agent_HH_Spot_EIA"])
        put("hh_chg20", "Henry Hub spot change over 20 trading days", hh[-1][1] - hh[-21][1], "USD/MMBtu", hh[-1][0], hh[-1][2], ["Agent_HH_Spot_EIA"])
    pr, wti = me.load_series(conn, "Agent_NGL_MontBelvieu_Propane", as_of), me.load_series(conn, "Agent_Crude_WTI_Spot", as_of)
    if len(wti) > 21:
        put("wti_chg20", "WTI crude change over 20 trading days", wti[-1][1] - wti[-21][1], "USD/bbl", wti[-1][0], wti[-1][2], ["Agent_Crude_WTI_Spot"])
    if pr and wti:
        wmap = {d: v for d, v, _ in wti}
        ratio = [(d, (v / 100 * 42) / wmap[d] * 100) for d, v, _ in pr if d in wmap and wmap[d] > 0]
        if len(ratio) > 60:
            hist = [r for _, r in ratio[-251:-1]]
            mu = sum(hist) / len(hist)
            put("propane_wti", "Mont Belvieu propane as % of WTI", ratio[-1][1], "%", ratio[-1][0], max(pr[-1][2], wti[-1][2]),
                ["Agent_NGL_MontBelvieu_Propane", "Agent_Crude_WTI_Spot"],
                f"; trailing 250-day mean {mu:.3f} %: ratio {'ABOVE' if ratio[-1][1] > mu else 'BELOW'} its mean")
            obs["propane_wti"]["mean"] = round(mu, 4)
    hdd = me.load_series(conn, "Agent_Weather_Actual_HDD", as_of)
    if len(hdd) >= 7:
        last7 = hdd[-7:]
        norm = _normal_hdd(conn, [d for d, _, _ in last7], as_of)
        if len(norm) == 7:
            act, nrm = sum(v for _, v, _ in last7), sum(norm.values())
            put("hdd_anom7", "CONUS HDD over the last 7 days minus 30-year normal", act - nrm, "degree days", last7[-1][0], last7[-1][2],
                ["Agent_Weather_Actual_HDD", "Agent_Weather_30YrNormal_HDD"],
                f" (actual {act:.1f}, normal {nrm:.1f}: {'WARMER than normal, less heating demand' if act < nrm else 'COLDER than normal, more heating demand'})")
    basins = kb_ingest.BASINS
    prod = [me.load_series(conn, b, as_of) for b in basins]
    if all(len(p) > 3 for p in prod):
        common = sorted(set.intersection(*[{d for d, _, _ in p} for p in prod]))
        if len(common) > 3:
            tot = {d: sum(v for p in prod for dd, v, _ in p if dd == d) for d in common[-4:]}
            last, prev = common[-1], common[-4]
            put("prod_chg3m", "Six-basin shale gas production change over 3 months", tot[last] - tot[prev], "Bcf/d", last,
                max(p[-1][2] for p in prod), basins, f" (latest {tot[last]:.2f} Bcf/d: production {'RISING' if tot[last] > tot[prev] else 'FALLING'})")
    pb = me.load_series(conn, "Agent_Demand_PowerBurn", as_of)
    if len(pb) >= 35:
        a, b = sum(v for _, v, _ in pb[-7:]) / 7, sum(v for _, v, _ in pb[-35:-7]) / 28
        put("power_burn_chg", "US48 gas-fired generation, 7-day mean vs prior 28 days", (a / b - 1) * 100, "%", pb[-1][0], pb[-1][2], ["Agent_Demand_PowerBurn"],
            f" (power burn {'HIGHER' if a > b else 'LOWER'} than the prior 28 days)")
    st = [me.load_series(conn, a, as_of) for a in kb_ingest.STORAGE]
    if all(len(s) >= 2 for s in st):
        chg = sum(s[-1][1] - s[-2][1] for s in st)
        put("storage_chg", "Lower-48 working gas weekly change", chg, "Bcf", st[0][-1][0], st[0][-1][2], kb_ingest.STORAGE,
            f" (total {sum(s[-1][1] for s in st):.0f} Bcf: net {'INJECTION' if chg > 0 else 'WITHDRAWAL'})")
    coal = me.load_series(conn, "Agent_Coal_CAPP_SpotPrice", as_of)
    if len(coal) > 5:
        put("coal_chg4w", "Central Appalachian coal spot change over 4 weeks", coal[-1][1] - coal[-5][1], "USD/short ton", coal[-1][0], coal[-1][2],
            ["Agent_Coal_CAPP_SpotPrice"])
    if _has(conn, "notice_extractions"):
        lo = _iso(_dt(as_of) - timedelta(days=7))
        n = conn.execute("SELECT COUNT(*) FROM notice_extractions WHERE posted<=? AND posted>? AND (severity='high' OR event_type='force_majeure')",
                         (as_of, lo)).fetchone()[0]
        m = conn.execute("SELECT COUNT(*) FROM notice_extractions WHERE posted<=? AND posted>? AND event_type='capacity_restriction'", (as_of, lo)).fetchone()[0]
        obs["pipeline_events7"] = {"label": "High-severity pipeline notices in the last 7 days", "value": n, "unit": "notices", "date": as_of[:10],
                                   "available_timestamp": as_of, "agents": [], "restrictions": m,
                                   "text": f"High-severity or force-majeure pipeline notices in the last 7 days: {n}; capacity restrictions: {m} (as of {as_of[:10]})"}
    for o in obs.values():
        assert o["available_timestamp"] <= as_of, "LOOK-AHEAD in observations"
    return obs


def _sign(v, up="up", down="down", eps=0.0):
    if v is None:
        return None
    return up if v > eps else down if v < -eps else None


# ----------------------------------------------------------------------------- cross-domain relationship catalogue
CATALOG = {
    # id: relationship, domains, target, testable model (or None), observation keys, expected direction from observations, markets, assumptions, method
    "weather_hdd_hh": {
        "relationship": "Colder-than-normal weather (positive HDD anomaly) raises residential/commercial gas demand and Henry Hub prices.",
        "domains": ["weather", "natural_gas"], "target": "henry_hub", "model": "hdd_anomaly", "obs": ["hdd_anom7", "hh", "hh_chg20"],
        "expect": lambda o: _sign(o.get("hdd_anom7", {}).get("value"), eps=5.0), "markets": ["Henry Hub", "US Lower 48"],
        "assumptions": ["Population-weighted CONUS HDD represents heating demand", "Price responds within the horizon"],
        "method": "PIT walk-forward of hdd_anomaly vs persistence on Henry Hub spot, costs and slippage included, chronological holdout."},
    "production_hh": {
        "relationship": "Rising shale gas production loosens the supply balance and pressures Henry Hub lower (and the reverse).",
        "domains": ["production", "natural_gas"], "target": "henry_hub", "model": "hh_production_momentum", "obs": ["prod_chg3m", "hh", "hh_chg20"],
        "expect": lambda o: _sign(o.get("prod_chg3m", {}).get("value"), up="down", down="up", eps=0.05), "markets": ["Henry Hub", "Permian", "Appalachia", "Haynesville"],
        "assumptions": ["EIA STEO basin estimates track realised production", "No offsetting demand shock over the horizon"],
        "method": "PIT walk-forward of hh_production_momentum vs persistence, monthly production read as published."},
    "propane_wti_revert": {
        "relationship": "Mont Belvieu propane's ratio to WTI crude reverts toward its trailing mean, driving propane relative to crude.",
        "domains": ["ngl", "crude_oil"], "target": "propane", "model": "propane_wti_revert", "obs": ["propane_wti", "wti_chg20"],
        "expect": lambda o: (_sign(o["propane_wti"]["value"] - o["propane_wti"]["mean"], up="down", down="up", eps=1.0) if "propane_wti" in o else None),
        "markets": ["Mont Belvieu", "WTI Cushing"], "assumptions": ["Export arbitrage keeps propane anchored to crude", "No fractionation outage"],
        "method": "PIT walk-forward of propane_wti_revert vs persistence on Mont Belvieu propane, costs included."},
    "propane_wti_momentum": {
        "relationship": "Mont Belvieu propane follows recent WTI crude momentum because NGL prices are set against crude oil.",
        "domains": ["ngl", "crude_oil"], "target": "propane", "model": "propane_wti_momentum", "obs": ["wti_chg20", "propane_wti"],
        "expect": lambda o: _sign(o.get("wti_chg20", {}).get("value"), eps=0.5), "markets": ["Mont Belvieu", "WTI Cushing"],
        "assumptions": ["Crude remains the marginal pricing reference for propane"],
        "method": "PIT walk-forward of propane_wti_momentum vs persistence on Mont Belvieu propane, costs included."},
    "power_burn_hh": {
        "relationship": "Higher gas-fired power generation (power burn) increases gas demand and supports Henry Hub prices.",
        "domains": ["electricity", "natural_gas"], "target": "henry_hub", "model": None, "obs": ["power_burn_chg", "hh", "hh_chg20"],
        "expect": lambda o: _sign(o.get("power_burn_chg", {}).get("value"), eps=2.0), "markets": ["Henry Hub", "US Lower 48 power"],
        "assumptions": ["EIA-930 gas-fired generation is a proxy for power-sector gas burn"],
        "method": "Needs a power-burn feature model: PIT walk-forward with EIA-930 generation lagged one day (not yet implemented)."},
    "pipeline_restriction_hh": {
        "relationship": "Pipeline capacity restrictions and force majeure events constrain delivered supply and can tighten regional and Henry Hub prices.",
        "domains": ["pipelines", "natural_gas"], "target": "henry_hub", "model": None, "obs": ["pipeline_events7", "hh", "hh_chg20"],
        "expect": lambda o: "up" if o.get("pipeline_events7", {}).get("value", 0) > 0 else None, "markets": ["Henry Hub", "Tennessee Gas", "El Paso"],
        "assumptions": ["The restricted capacity was binding for flows toward the Gulf Coast"],
        "method": "Needs a notice-count feature: PIT event study of Henry Hub returns after high-severity notices (not yet implemented)."},
    "coal_switching_hh": {
        "relationship": "Rising coal prices make gas-fired generation relatively cheaper (coal-to-gas switching), raising gas burn and Henry Hub demand.",
        "domains": ["coal", "electricity", "natural_gas"], "target": "henry_hub", "model": None, "obs": ["coal_chg4w", "power_burn_chg", "hh"],
        "expect": lambda o: _sign(o.get("coal_chg4w", {}).get("value"), eps=1.0), "markets": ["Henry Hub", "Central Appalachia coal"],
        "assumptions": ["Dispatch switching margin is close enough to bind", "CO2 allowance prices are stable"],
        "method": "Needs a coal/gas switching feature model (not yet implemented)."},
    "storage_withdrawal_hh": {
        "relationship": "Net storage withdrawals (or smaller injections) tighten the balance and support Henry Hub; larger injections loosen it.",
        "domains": ["storage", "natural_gas"], "target": "henry_hub", "model": None, "obs": ["storage_chg", "hh", "hh_chg20"],
        "expect": lambda o: _sign(o.get("storage_chg", {}).get("value"), up="down", down="up", eps=1.0), "markets": ["Henry Hub", "South Central storage"],
        "assumptions": ["The weekly change is not dominated by reclassifications"],
        "method": "Needs a storage-surprise feature (actual vs expected change); history currently too short (not yet implemented)."},
}
TARGET_PRICED_BY = {"henry_hub": {"natural_gas", "storage", "production", "lng", "pipelines", "weather", "electricity"}, "propane": {"ngl", "crude_oil"}}


class SynthesisAgent:
    name = "synthesis"
    VERSION = "synth-3"
    SCHEMA = {"type": "object", "properties": {
        "relationship_id": {"type": "string", "enum": sorted(CATALOG)},
        "direction": {"type": "string", "enum": ["up", "down", "neutral"]},
        "horizon_days": {"type": "integer", "enum": [1, 5, 10]},
        "rationale": {"type": "string", "maxLength": 600},
        "contradictory_evidence": {"type": "string", "maxLength": 300},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "evidence_ids": {"type": "array", "items": {"type": "string"}}},
        "required": ["relationship_id", "direction", "horizon_days", "rationale", "contradictory_evidence", "confidence", "evidence_ids"]}

    STANDING = ["Henry Hub natural gas price, storage and weather", "pipeline capacity restriction force majeure notice",
                "Mont Belvieu propane price relative to WTI crude oil", "shale gas production and power burn demand"]

    def __init__(self, run_backtests: bool = True, hub=None):
        self.run_backtests, self.hub = run_backtests, hub

    # -- re-check earlier findings with the current rules (the text is kept; the verdict goes to finding_status)
    def recheck(self, conn, as_of: str) -> dict:
        counts = {}
        for f in memory.findings(conn, as_of, 500, kinds=("hypothesis",)):
            if f["status"] != "unchecked":
                continue
            doc = f["document"]
            if "REJECTED" in doc:
                st, why = "rejected", "rejected by its own checks when generated"
            elif "Relationship id:" not in doc:
                tgt = re.search(r"Target (\w+)", doc)
                doms = re.search(r"Domains: ([a-z_, ]+)\.", doc)
                t = tgt.group(1) if tgt else ""
                ds = {d.strip() for d in doms.group(1).split(",")} if doms else set()
                ok = t in TARGET_PRICED_BY and bool(TARGET_PRICED_BY[t] & ds) and len(ds) >= 2
                st = "superseded"
                why = (f"free-form hypothesis from an earlier prompt version; re-checked with {self.VERSION}: "
                       + ("passes domain consistency but has no catalogued, measurable relationship" if ok
                          else f"target {t} is not priced by any cited domain {sorted(ds)}"))
            else:
                st, why = "valid", f"passes {self.VERSION} checks"
            memory.set_status(conn, f["id"], st, why, self.VERSION)
            counts[st] = counts.get(st, 0) + 1
        return counts

    def run(self, conn, llm: LLM, as_of: str, collection=None, db_path: str | None = None) -> dict:
        rechecked = self.recheck(conn, as_of)
        msgs = memory.consume(conn, self.name, ["pipeline_event", "anomaly", "data_quality"], 30)
        prior = memory.findings(conn, as_of, 6, kinds=("hypothesis", "evaluation", "anomaly"), valid_only=True)
        obs = observations(conn, as_of)
        topics = []
        for m in msgs:
            p = m["payload"]
            if m["topic"] == "pipeline_event":
                topics.append(f"{p.get('pipeline', '')} {p.get('event_type', '')} {p.get('summary', '')}".strip())
            elif m["topic"] == "anomaly":
                topics.append(f"{p.get('label')} anomaly {p.get('domain')}")
        topics = list(dict.fromkeys(topics))[:4] + self.STANDING
        hits = {}
        for t in topics:
            for h in memory.search(conn, llm, t, as_of, 3, hub=self.hub):
                hits.setdefault(h["id"], h)
        for p in prior[:4]:
            hits.setdefault(p["id"], {"id": p["id"], "domain": "agent_finding", "title": p["title"], "document": p["document"],
                                      "available_timestamp": p["available_timestamp"], "similarity": None})
        dead = {r[0] for r in conn.execute("SELECT node_id FROM finding_status WHERE status IN ('rejected','superseded')")}
        shown = [h for h in hits.values() if h["id"] not in dead][:16]
        hits = {h["id"]: h for h in shown}
        ctx = "\n".join(f"[{h['id']}] ({h['domain']}, {h['available_timestamp'][:10]}) {h['title']}: {h['document'][:280]}" for h in shown)
        obs_txt = "\n".join(f"- [{k}] {o['text']}" for k, o in obs.items()) or "- (no structured observations available)"
        schema = json.loads(json.dumps(self.SCHEMA))
        schema["properties"]["evidence_ids"]["items"] = {"type": "string", "enum": sorted(hits) or ["none"]}
        schema["properties"]["observation_ids"] = {"type": "array", "items": {"type": "string", "enum": sorted(obs) or ["none"]}}
        schema["required"] = schema["required"] + ["observation_ids"]
        events = "\n".join(f"- {m['topic']} from {m['sender']}: {json.dumps(m['payload'])[:240]}" for m in msgs[:12]) or "- (no new events)"
        def implied(v):
            if any(k not in obs for k in v["obs"]):
                return "observations unavailable"
            d = v["expect"](obs)
            return f"observations imply {d}" if d else "observations give no clear direction"
        cat = "\n".join(f"- {k}: {v['relationship']} (domains {', '.join(v['domains'])}; target {v['target']}; {implied(v)}; "
                        f"{'testable by backtest' if v['model'] else 'not yet testable'})" for k, v in CATALOG.items())
        prompt = (f"You are a cross-domain natural gas and NGL research analyst working point-in-time as of {as_of}.\n"
                  "Background (not data): Henry Hub responds to the gas balance - supply (shale production, pipeline capacity) against demand "
                  "(weather, power burn, LNG feedgas, storage injections). Propane and other NGLs are fractionated from wet gas at Mont Belvieu and "
                  "priced against crude oil and export demand; pipeline gas is not converted into propane.\n\n"
                  f"STRUCTURED OBSERVATIONS (measured, point-in-time):\n{obs_txt}\n\nNEW EVENTS FROM OTHER AGENTS:\n{events}\n\n"
                  f"KNOWLEDGE LIBRARY (ids in brackets, includes earlier agent findings):\n{ctx}\n\n"
                  f"CANDIDATE RELATIONSHIPS:\n{cat}\n\n"
                  "{CHOOSE} Give the direction the "
                  "observations imply for its target, a horizon, a rationale that cites the observations, the strongest contradictory evidence, "
                  "and your confidence (rationale at most 80 words, contradictory evidence at most 40 words). In evidence_ids cite knowledge-library ids (the ids in brackets in the KNOWLEDGE LIBRARY) that support or "
                  "contradict the relationship; in observation_ids cite the observation keys you used. Use no numbers except ones written above. "
                  "Document similarity is not evidence of causation.")
        base = dict(conn=conn, llm=llm, as_of=as_of, collection=collection, db_path=db_path, obs=obs, hits=hits, schema=schema, prompt=prompt)
        result = self._hypothesis(**base, allowed=sorted(CATALOG),
                                  choose="Choose the ONE candidate relationship best supported by the observations and events right now.")
        result.update(messages_consumed=len(msgs), retrieved=len(hits), observations=len(obs), rechecked=rechecked)
        if CATALOG[result["hypothesis"]["relationship_id"]]["model"] is None:
            # the primary relationship cannot be backtested yet: also propose the best-supported TESTABLE one, so the
            # hypothesis -> PIT walk-forward evaluation path runs on every cycle
            testable = sorted(k for k, v in CATALOG.items() if v["model"])
            try:
                result["testable"] = self._hypothesis(**base, allowed=testable, choose=(
                    "TESTABLE ONLY: choose the ONE relationship among " + ", ".join(testable) + " that the observations support best."))
            except Exception as e:  # noqa: BLE001  the primary hypothesis stands even if the secondary call fails
                result["testable"] = {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}
        return result

    def _hypothesis(self, conn, llm, as_of, collection, db_path, obs, hits, schema, prompt, allowed, choose, feedback: str | None = None) -> dict:
        args = dict(conn=conn, llm=llm, as_of=as_of, collection=collection, db_path=db_path, obs=obs, hits=hits, schema=schema, prompt=prompt,
                    allowed=allowed, choose=choose)
        schema = json.loads(json.dumps(schema))
        schema["properties"]["relationship_id"]["enum"] = allowed
        prompt = prompt.replace("{CHOOSE}", choose) + (f"\n\nREVIEW OF YOUR PREVIOUS ANSWER: {feedback}" if feedback else "")
        res = llm.json("synthesize", prompt, schema, version=self.VERSION,
                       validate=lambda o: None if o["relationship_id"] in allowed else f"relationship {o['relationship_id']} outside {allowed}")
        entry = CATALOG[res["relationship_id"]]
        ids = [i for i in res["evidence_ids"] if i in hits]
        cited_obs = [k for k in res.get("observation_ids", []) if k in obs]
        bad = numbers_grounded(res["rationale"] + " " + res["contradictory_evidence"], prompt)
        expected = entry["expect"](obs) if all(k in obs for k in entry["obs"][:1]) else None
        problems, notes = [], []
        if not ids:
            problems.append("no cited knowledge-library evidence")
        elif all(hits[i]["domain"] == memory.FINDING_DOMAIN for i in ids):
            problems.append("cites only earlier agent findings (circular): needs at least one source or data-derived knowledge object")
        if not set(cited_obs) & set(entry["obs"]):
            problems.append("cites none of the observations this relationship depends on")
        # confidence is capped deterministically: high needs a testable model and at least three cited knowledge objects
        cap = "high" if entry["model"] and len(ids) >= 3 else "medium" if len(ids) >= 2 else "low"
        order = ["low", "medium", "high"]
        if order.index(res["confidence"]) > order.index(cap):
            notes.append(f"confidence {res['confidence']}->{cap} (capped by evidence and testability)")
            res["confidence"] = cap
        if bad:
            problems.append(f"numbers not in evidence {bad}")
        if expected and res["direction"] not in (expected,):
            problems.append(f"direction {res['direction']} contradicts the observations (they imply {expected})")
        if not set(entry["domains"]) & TARGET_PRICED_BY[entry["target"]]:
            problems.append("target not priced by any domain")
        missing_obs = [k for k in entry["obs"] if k not in obs]
        if missing_obs:
            problems.append(f"required observations unavailable at the cutoff: {missing_obs}")
        valid = not problems
        fixable = [x for x in problems if not x.startswith(("required observations unavailable", "target not priced"))]
        if problems and len(fixable) == len(problems) and feedback is None:
            # bounded self-correction: one retry with the validator's findings; a second failure is rejected as usual
            r = self._hypothesis(**args, feedback=(f"you chose {res['relationship_id']} with direction {res['direction']}, but the checks found: "
                                                   f"{'; '.join(problems)}. Answer again fixing these (direction consistent with the observations, "
                                                   "cite at least one source or data knowledge object), or choose another relationship. Do not mention this review in your answer."))
            r["first_attempt"] = {"hypothesis": res, "problems": problems}
            return r
        used_obs = [obs[k]["text"] for k in dict.fromkeys(cited_obs + entry["obs"]) if k in obs]
        analogs = [f"[{h['id']}] {h['title']} ({h['available_timestamp'][:10]}; similarity {h['similarity']}, retrieval aid only)"
                   for h in hits.values() if h["id"] in ids]
        hyp = {"relationship_id": res["relationship_id"], "relationship": entry["relationship"], "domains": entry["domains"], "target": entry["target"],
               "instruments": {"henry_hub": ["Henry Hub spot (EIA)", "NYMEX NG front month"], "propane": ["Mont Belvieu propane spot (EIA)"]}[entry["target"]],
               "analogs": analogs, "observations": used_obs, "direction": res["direction"], "horizon": f"{res['horizon_days']} trading days",
               "horizon_days": res["horizon_days"], "markets": entry["markets"], "assumptions": entry["assumptions"],
               "contradictory_evidence": [res["contradictory_evidence"]] if res["contradictory_evidence"].strip() else [],
               "confidence": res["confidence"], "backtest_method": entry["method"], "vector_nodes": ids,
               "model_version": f"{REASONING_MODEL} prompt {self.VERSION}", "rationale": res["rationale"], "expected_direction_from_observations": expected,
               "magnitude": "not estimated (no evaluated quantitative model yet)", "backtest_results": {}}
        body = (f"Hypothesis (model-generated, {'validated' if valid else 'REJECTED by checks'}). Relationship id: {res['relationship_id']}. "
                f"{entry['relationship']} Target {entry['target']} {res['direction']} over {res['horizon_days']} days. Domains: {', '.join(entry['domains'])}. "
                f"Observations: {' | '.join(used_obs)}. Rationale: {res['rationale']} Contradictory evidence: {res['contradictory_evidence']} "
                f"Confidence: {res['confidence']}." + (f" Check failures: {'; '.join(problems)}." if problems else "")
                + (f" Adjustments: {'; '.join(notes)}." if notes else ""))
        obs_agents = sorted({a for k in entry["obs"] if k in obs for a in obs[k]["agents"]})
        f = memory.add_finding(conn, llm, self.name, f"Hypothesis: {res['relationship_id']} {entry['target']} {res['direction']} {res['horizon_days']}d",
                               body, as_of, ids, "model_hypothesis", "hypothesis", collection, {"agent_ids": ",".join(obs_agents)})
        memory.set_status(conn, f["id"], "valid" if valid else "rejected", "; ".join(problems) or f"passes {self.VERSION} checks", self.VERSION)
        result = {"hypothesis": res, "valid": valid, "problems": problems, "adjustments": notes, "observations_cited": cited_obs, "finding": f["id"], "evidence_linked": len(ids)}
        if valid:
            memory.publish(conn, self.name, "finding", {"finding": f["id"], "relationship_id": res["relationship_id"], "domains": entry["domains"]}, ref=f["id"])
            ev = self.evaluate(conn, llm, hyp, entry, f["id"], as_of, collection, db_path)
            result["evaluation"] = ev
            if ev.get("status") == "evaluated":
                import alerts
                hyp["backtest_results"] = ev["backtest_results"]
                hyp["magnitude"] = ev["magnitude"]
                result["memo_problems"] = alerts.validate_hypothesis(hyp)
                result["memo"] = alerts.format_memo(hyp, as_of) if not result["memo_problems"] else None
                if result["memo"]:      # the complete Section 5.4 memo is itself a persistent, linked knowledge object
                    m = memory.add_finding(conn, llm, self.name, f"Research memo: {res['relationship_id']} {entry['target']} {res['direction']} "
                                           f"{res['horizon_days']}d ({ev['outcome'].split(':')[0]})", result["memo"], as_of,
                                           [f["id"], ev["finding"]] + ids, "model_hypothesis", "memo", collection)
                    result["memo_finding"] = m["id"]
                if ev.get("promoted") and result["memo"] and _notify_enabled():
                    import notify
                    notify.event("validated-hypotheses", f"Agent hypothesis validated out of sample: {res['relationship_id']}", result["memo"][:6000])
        result["hypothesis_memo_fields"] = hyp
        return result

    def evaluate(self, conn, llm, hyp, entry, finding_id, as_of, collection, db_path):
        """Test the hypothesis with the PIT walk-forward backtester when a matching quantitative model exists. Only experiments
        recorded at or before as_of are used, so a historical run cannot see a later evaluation."""
        model, h = entry["model"], hyp["horizon_days"]
        if not model:
            return {"status": "not_testable", "reason": f"no quantitative model yet for {hyp['relationship_id']}: {entry['method']}"}
        q = ("SELECT id, reason, metrics, created, config, test_period, promoted FROM experiments WHERE config LIKE ? AND config LIKE ? "
             "AND config NOT LIKE '%\"cost_bps\": 0.0%' AND created<=? ORDER BY created DESC LIMIT 1")
        args = (f'%"model": "{model}"%', f'%"horizon_days": {h},%', as_of)
        row = conn.execute(q, args).fetchone() if _has(conn, "experiments") else None
        fresh = abs((datetime.now(timezone.utc) - _dt(as_of)).total_seconds()) < 2 * 86400
        if not row and self.run_backtests and db_path and fresh:
            import experiments
            experiments.run(db_path, 300, (h,), (10,), (model,), 5.0)
            row = conn.execute(q[:-len("AND created<=? ORDER BY created DESC LIMIT 1")] + "ORDER BY created DESC LIMIT 1", args[:2]).fetchone()
        if not row:
            return {"status": "not_run", "reason": "no cost-inclusive experiment for this model and horizon at the cutoff"}
        eid, reason, met, created, cfg, test_period, promoted = row
        m, c = json.loads(met or "{}"), json.loads(cfg or "{}")
        br = {"sample": "out_of_sample", "n": m.get("n"), "rmse": m.get("rmse"), "persistence_rmse": m.get("persistence_rmse"),
              "directional_hit_rate": m.get("directional_hit_rate"), "mean_return_after_costs": m.get("mean_return_after_costs"),
              "cost_bps": c.get("cost_bps"), "slippage_bps": c.get("slippage_bps", 0.0), "test_period": test_period, "experiment": eid}
        magnitude = (f"holdout RMSE {m.get('rmse', float('nan')):.4f} vs persistence {m.get('persistence_rmse', float('nan')):.4f}; "
                     f"mean return after costs {m.get('mean_return_after_costs', float('nan')):.4f} per decision")
        body = (f"Backtest of hypothesis {finding_id} ({hyp['relationship_id']}) with model {model} ({h}-day horizon, PIT walk-forward, "
                f"{c.get('cost_bps')} bps costs, {c.get('slippage_bps', 0.0)} bps slippage): experiment {eid}, test {test_period}, {magnitude}; outcome: {reason}.")
        # same key kb_ingest.build_objects uses for the experiment's knowledge object
        bt_node = kb_ingest.node_id("backtest", f"experiment_{c.get('model')}_{c.get('horizon_days')}d_{c.get('cost_bps')}bps_{c.get('slippage_bps', 0)}slip:{eid}")
        ev = memory.add_finding(conn, llm, self.name, f"Evaluation: {hyp['relationship_id']} {h}d - {reason.split(':')[0]}", body, as_of, [finding_id, bt_node],
                                "backtest_result", "evaluation", collection)
        memory.link(conn, finding_id, ev["id"], "evaluated_by")
        memory.set_status(conn, finding_id, "evaluated", f"experiment {eid}: {reason}", self.VERSION)
        return {"status": "evaluated", "experiment": eid, "outcome": reason, "promoted": bool(promoted), "finding": ev["id"],
                "backtest_results": br, "magnitude": magnitude}


# ----------------------------------------------------------------------------- orchestration
def run_all(db_path: str, collection=None, as_of: str | None = None, llm_factory=None, notice_limit: int = 25, run_backtests: bool = True,
            only: list | None = None) -> dict:
    as_of = me.pit_cutoff(as_of)
    conn = sqlite3.connect(db_path, timeout=60)
    memory.ensure(conn)
    st = llm_status() if llm_factory is None else {"ok": True, "injected": True}
    mk = llm_factory or (lambda name: LLM(conn, name, available=st["ok"]))
    hub = retrieval_hub.RetrievalHub(storage_dir=os.environ.get("HH_RETRIEVAL_DIR")) if llm_factory is None else None
    plan = [DiagnosticsAgent(), DataQualityAgent(), RepairAgent(), NoticeAnalystAgent(notice_limit), AnomalyAgent(), SynthesisAgent(run_backtests, hub=hub),
            QuantRiskAgent()]
    report = {"as_of": as_of, "ollama": st, "agents": {}}
    try:
        report["embeddings_backfilled"] = memory.backfill_embeddings(conn, mk("memory"), collection)
    except Exception as e:  # noqa: BLE001
        report["embeddings_backfilled"] = f"error: {e}"
    for a in plan:
        if only and a.name not in only:
            continue
        started = memory.now()
        try:
            kw = {"db_path": db_path} if isinstance(a, SynthesisAgent) else {}
            res = a.run(conn, mk(a.name), as_of, collection, **kw)
            memory.run_record(conn, a.name, started, as_of, True, res)
            report["agents"][a.name] = {"ok": True, **res}
        except Exception as e:  # noqa: BLE001  one agent failing never stops the others
            conn.rollback()
            memory.run_record(conn, a.name, started, as_of, False, {"error": f"{type(e).__name__}: {e}"})
            report["agents"][a.name] = {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}
    report["knowledge_nodes"] = conn.execute("SELECT COUNT(*) FROM kb_nodes").fetchone()[0]
    report["findings"] = conn.execute("SELECT COUNT(*) FROM kb_nodes WHERE domain=?", (memory.FINDING_DOMAIN,)).fetchone()[0]
    conn.close()
    return report


def main(argv=None) -> int:
    """CLI: run the agents without the hub (no Chroma mirror; the hub's /agents/run also mirrors into Chroma)."""
    import argparse
    import os
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--notice-limit", type=int, default=25)
    ap.add_argument("--no-backtests", action="store_true")
    a = ap.parse_args(argv)
    db = os.environ.get("DB_PATH") or str(ROOT / "henry_hub_pit.db")
    print(json.dumps(run_all(db, None, a.as_of, None, a.notice_limit, not a.no_backtests, a.only), indent=1, default=str)[:20000])
    return 0


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(ROOT))
    sys.exit(main())
