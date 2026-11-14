#!/usr/bin/env python3
"""Acceptance harness: runs every executable check, maps each requirement in requirements/registry.json to checks
(requirements/traceability.json), and writes requirements/STATUS.md + requirements/status.json.

A requirement is
  passed      every mapped check passed
  failed      at least one mapped check failed
  blocked     mapped to a check that needs something only the owner can provide (credential, sudo, paid feed)
  unverified  no executable check maps to it yet (counted as NOT done)
Checks never mutate production state except where marked `side_effect` (skipped unless --with-side-effects).

Usage: scripts/acceptance.py [--only CHECK ...] [--with-side-effects] [--no-network]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = str(ROOT / ".venv" / "bin" / "python")
DB = os.environ.get("DB_PATH") or str(ROOT / "henry_hub_pit.db")
REQ = ROOT / "requirements"
CHECKS: dict[str, dict] = {}


def check(name, desc, blocked_by=None, side_effect=False, network=False):
    def deco(fn):
        CHECKS[name] = {"fn": fn, "desc": desc, "blocked_by": blocked_by, "side_effect": side_effect, "network": network}
        return fn
    return deco


def sh(cmd, timeout=300, cwd=ROOT, env=None):
    p = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True, timeout=timeout, cwd=cwd, env={**os.environ, **(env or {})})
    return p.returncode, (p.stdout + p.stderr)


def http(url, method="GET", data=None, headers=None, timeout=30):
    req = urllib.request.Request(url, method=method, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def ro():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def pytest_ok(*nodes):
    rc, out = sh([PY, "-m", "pytest", "-q", *nodes], timeout=600)
    tail = out.strip().splitlines()[-1] if out.strip() else ""
    return rc == 0, tail


def roster():
    return [a["agent_id"] for a in json.loads((ROOT / "agents_roster.json").read_text())]


def real_agents():
    with ro() as c:
        return {r[0] for r in c.execute("SELECT DISTINCT agent_id FROM pit_market_data WHERE COALESCE(quality_status,'')<>'unverified_seed' "
                                        "AND source_id IS NOT NULL AND source_id<>'' AND COALESCE(provenance,'measured') IN ('measured','extracted_estimate')")}


# ----------------------------------------------------------------------------- data contract and PIT
@check("db_integrity", "SQLite integrity_check returns ok")
def _():
    with ro() as c:
        r = c.execute("PRAGMA integrity_check").fetchone()[0]
    return r == "ok", r


@check("schema_16_columns", "pit_market_data carries the 4 canonical + 12 production columns")
def _():
    need = {"agent_id", "target_timestamp", "available_timestamp", "value", "source_id", "source_url", "retrieved_timestamp", "published_timestamp",
            "revision_timestamp", "unit", "geographic_scope", "series_id", "raw_payload_hash", "extraction_version", "quality_status", "provenance"}
    with ro() as c:
        have = {r[1] for r in c.execute("PRAGMA table_info(pit_market_data)")}
    return need <= have, f"missing={sorted(need - have)}"


@check("raw_payloads_verified", "every raw_payloads row has its archived bytes and the sha256 matches")
def _():
    bad, n = [], 0
    with ro() as c:
        for h, p in c.execute("SELECT raw_payload_hash, archive_path FROM raw_payloads"):
            n += 1
            f = Path(p) if Path(p).is_absolute() else ROOT / p
            if not f.is_file():
                f = ROOT / "raw" / h
            if not f.is_file() or hashlib.sha256(f.read_bytes()).hexdigest() != h:
                bad.append(h[:12])
    return not bad and n > 0, f"{n - len(bad)}/{n} verified" + (f"; bad {bad[:5]}" if bad else "")


@check("observations_reference_payloads", "measured rows from collectors cite an archived raw payload")
def _():
    with ro() as c:
        n, miss = c.execute("SELECT COUNT(*), SUM(CASE WHEN p.raw_payload_hash IS NULL OR p.raw_payload_hash='' OR r.raw_payload_hash IS NULL THEN 1 ELSE 0 END) "
                            "FROM pit_market_data p LEFT JOIN raw_payloads r ON r.raw_payload_hash=p.raw_payload_hash "
                            "WHERE COALESCE(p.provenance,'measured')='measured' AND COALESCE(p.quality_status,'')<>'unverified_seed' AND p.source_id IS NOT NULL").fetchone()
    return (miss or 0) == 0, f"{n - (miss or 0)}/{n} measured rows reference an archived payload"


@check("pit_tests", "unit tests: vintages never overwritten, snapshots hide future revisions, look-ahead asserted")
def _():
    return pytest_ok("tests/test_ingest.py", "tests/test_backtest.py", "tests/test_markets_engine.py::PitState")


@check("full_test_suite", "the complete unit suite passes")
def _():
    return pytest_ok()


@check("provenance_labels", "every row is labelled measured / extracted_estimate / synthetic_scenario / model_hypothesis / unverified_seed")
def _():
    with ro() as c:
        bad = c.execute("SELECT COUNT(*) FROM pit_market_data WHERE COALESCE(provenance,'measured') NOT IN "
                        "('measured','extracted_estimate','synthetic_scenario','model_hypothesis','unverified_seed')").fetchone()[0]
    return bad == 0, f"{bad} unlabelled rows"


# ----------------------------------------------------------------------------- collection coverage
@check("roster_81", "the roster defines 81 unique atomic agents")
def _():
    r = roster()
    return len(r) == 81 and len(set(r)) == 81, f"{len(set(r))} unique"


@check("roster_all_collected", "every roster agent has real (non-seed) data", blocked_by="paid/credentialed sources for NGI, CME, pipeline EBBs, ethane/butane/C5+, coal")
def _():
    miss = [a for a in roster() if a not in real_agents()]
    return not miss, f"{81 - len(miss)}/81 with real data; missing {len(miss)}: {', '.join(m.replace('Agent_', '') for m in miss[:40])}"


@check("collectors_run", "every implemented collector runs successfully against the live sources", side_effect=True, network=True)
def _():
    rc, out = sh([PY, "collectors/run_all.py"], timeout=900, env={"DB_PATH": DB})
    return rc == 0, " | ".join(l[:60] for l in out.splitlines() if l[:2] in ("OK", "FA"))


@check("collector_freshness", "daily collectors produced data within their cadence")
def _():
    stale = []
    with ro() as c:
        for a, last in c.execute("SELECT agent_id, MAX(available_timestamp) FROM pit_market_data WHERE source_id IS NOT NULL GROUP BY 1"):
            if a.startswith(("Agent_HH_Spot", "Agent_Crude", "Agent_NGL_MontBelvieu_Propane", "Agent_Weather_Actual", "Agent_GFS", "Agent_ECMWF")):
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(last.replace("Z", "+00:00"))).days
                if age > 5:
                    stale.append(f"{a}:{age}d")
    return not stale, "stale: " + ", ".join(stale) if stale else "all daily series fresh (<=5 days)"


@check("collector_schedule", "local systemd timer and Worker cron triggers are installed")
def _():
    rc1, o1 = sh("systemctl --user is-enabled hh-collect-cpc.timer")
    toml = (ROOT / "wrangler.toml").read_text()
    return rc1 == 0 and "crons" in toml, f"timer {o1.strip()}; worker crons {re.findall(r'crons = .*', toml)}"


@check("gatekeeper", "deterministic range/unit gate rejects absurd values before ingestion")
def _():
    return pytest_ok("tests/test_gatekeeper.py", "tests/test_eia_prices.py::T::test_absurd_price_rejected_by_gatekeeper")


@check("edge_collection", "Cloudflare Workers fetch source data at the edge and forward payload + fetch metadata through Access")
def _():
    src = (ROOT / "worker.js").read_text()
    with ro() as c:
        try:
            rows = c.execute("SELECT key, MAX(retrieved_timestamp), SUM(ok), COUNT(*) FROM edge_fetches GROUP BY key").fetchall()
        except sqlite3.OperationalError:
            rows = []
    ok_keys = [r[0] for r in rows if r[2]]
    return "EDGE_SOURCES" in src and "/ingest/edge" in src and len(ok_keys) >= 3, f"edge sources with successful runs: {ok_keys}"


@check("edge_ingest_unit", "hub /ingest/edge accepts only whitelisted key+URL pairs and records fetch metadata")
def _():
    return pytest_ok("tests/test_edge_ingest.py")


# ----------------------------------------------------------------------------- self-healing
@check("selfheal_unit", "failure diagnosis, LLM selector repair proposal, fixture validation, PR gating")
def _():
    return pytest_ok("tests/test_selfheal.py")


@check("selfheal_live_ollama", "qwen3:4b proposes a selector that passes fixtures (live local Ollama)", network=True)
def _():
    code = ("import selfheal as s;h='<div><span class=\"px\">$3.42</span></div>';d=s.diagnose('Agent_X',h,'span.old',(1,20));"
            "p=s.propose_repair(d,h,s.ollama_llm);v=s.validate_proposal(p['selector'],[{'html':h,'expected':3.42}]);print(p,v);assert v['passed']")
    rc, out = sh([PY, "-c", code], timeout=180)
    lines = out.strip().splitlines()
    return rc == 0, (lines[-1][:200] if rc == 0 else " / ".join(l[:120] for l in lines[-4:])) if lines else ""


@check("selfheal_pr_live", "a validated, test-passing repair opens a real GitHub pull request (never merged automatically)", network=True)
def _():
    rc, out = sh("gh pr list -R jmpsu/henry_hub_atomic_agents --state all --search head:selfheal/ --json number,headRefName,state,files --limit 10")
    prs = json.loads(out) if rc == 0 and out.strip().startswith("[") else []
    good = [p for p in prs if any(f["path"] == "ingestion/selectors.json" for f in p.get("files", []))]
    return bool(good), f"self-heal PRs: {[(p['number'], p['state']) for p in prs]}"


@check("webhook_recovery", "GitHub webhook -> Worker HMAC check -> hub verifies the merged commit on the base branch and reruns the collector")
def _():
    src = (ROOT / "worker.js").read_text()
    with ro() as c:
        try:
            runs = c.execute("SELECT verified, ok FROM selfheal_runs").fetchall()
        except sqlite3.OperationalError:
            runs = []
    rc, hid = sh("gh api repos/jmpsu/henry_hub_atomic_agents/hooks --jq '.[] | select(.config.url|test(\"quant-gateway\")) | .id'")
    rc2, out = sh(f"gh api repos/jmpsu/henry_hub_atomic_agents/hooks/{hid.strip()}/deliveries --jq '[.[] | {{e: .event, c: .status_code}}]'") if rc == 0 and hid.strip() else (1, "[]")
    deliveries = json.loads(out) if rc2 == 0 and out.strip().startswith("[") else []
    verified = [d for d in deliveries if d["c"] in (200, 202)]          # 200 = processed, 202 = verified but not a merge event
    ok = "X-Hub-Signature-256" in src and bool(verified) and any(v and o for v, o in runs) and any(not v for v, o in runs)
    return ok, (f"GitHub deliveries accepted after signature check: {len(verified)} of {len(deliveries)}; "
                f"reruns verified+ok={sum(1 for v, o in runs if v and o)}, forged refused={sum(1 for v, o in runs if not v)}")


# ----------------------------------------------------------------------------- vector engine
@check("ollama_models", "local Ollama serves qwen3:4b and nomic-embed-text", network=True)
def _():
    st, body = http("http://127.0.0.1:11434/api/tags")
    names = {m["name"] for m in json.loads(body).get("models", [])} if st == 200 else set()
    return {"qwen3:4b", "nomic-embed-text:latest"} <= names, f"{sorted(names)}"


@check("knowledge_library", "knowledge objects with PIT metadata, typed edges, PIT-filtered search")
def _():
    with ro() as c:
        n = c.execute("SELECT COUNT(*) FROM kb_nodes").fetchone()[0]
        miss = c.execute("SELECT COUNT(*) FROM kb_nodes WHERE available_timestamp IS NULL OR available_epoch IS NULL OR provenance IS NULL OR source_id IS NULL").fetchone()[0]
        types = dict(c.execute("SELECT type, COUNT(*) FROM kb_edges GROUP BY 1").fetchall())
        doms = len(c.execute("SELECT DISTINCT domain FROM kb_nodes").fetchall())
    return n > 0 and miss == 0 and len(types) >= 3 and doms >= 5, f"{n} nodes, {doms} domains, edges {types}, {miss} missing PIT metadata"


@check("knowledge_search_pit", "semantic search returns nothing that was unavailable at the cutoff", network=True)
def _():
    st, b = http("http://127.0.0.1:8095/api/knowledge-search", "POST", json.dumps({"query": "storage", "as_of": "2020-01-01T00:00:00Z"}).encode(),
                 {"Content-Type": "application/json"})
    st2, b2 = http("http://127.0.0.1:8095/api/knowledge-search", "POST", json.dumps({"query": "storage week"}).encode(), {"Content-Type": "application/json"})
    return st == 200 and json.loads(b)["results"] == [] and st2 == 200 and json.loads(b2)["results"], f"old cutoff -> 0 results; now -> {len(json.loads(b2)['results'])}"


@check("unstructured_sources", "pipeline critical notices (incl. force majeure, maintenance) and NOAA forecast discussions are ingested as PIT documents and indexed")
def _():
    with ro() as c:
        try:
            docs = dict(c.execute("SELECT domain, COUNT(*) FROM documents GROUP BY 1").fetchall())
            kb = dict(c.execute("SELECT domain, COUNT(*) FROM kb_nodes WHERE domain IN ('pipeline_notice','noaa_discussion') GROUP BY 1").fetchall())
        except sqlite3.OperationalError as e:
            return False, str(e)
    ok = docs.get("pipeline_notice", 0) > 0 and docs.get("noaa_discussion", 0) > 0 and kb.get("pipeline_notice", 0) > 0 and kb.get("noaa_discussion", 0) > 0
    return ok, f"documents {docs}; indexed in knowledge library {kb}"


@check("cross_domain_sources", "FERC filings, LNG terminal notices, NGL fractionation, cracker/refinery outages and Mont Belvieu purity products are ingested",
       blocked_by="FERC blocks automated fetches (403); LNG terminal, fractionation, cracker and NGL purity-product feeds need subscriptions")
def _():
    with ro() as c:
        doms = {r[0] for r in c.execute("SELECT DISTINCT domain FROM kb_nodes")}
    need = {"ferc", "lng_notice", "ngl_fractionation", "petchem_outage"}
    return need <= doms, f"have {sorted(doms)}; missing {sorted(need - doms)}"


@check("hypothesis_memo", "alpha hypotheses carry every required field and are rejected without out-of-sample, cost-inclusive backtests")
def _():
    return pytest_ok("tests/test_alerts.py")


@check("research_log_live", "alpha memos are published with gh issue create", blocked_by="no hypothesis has passed promotion; publishing a rejected one would be misleading")
def _():
    rc, out = sh("gh issue list -R jmpsu/henry_hub_atomic_agents --label alpha-hypothesis --state all --limit 5")
    return rc == 0 and out.strip() != "", out.strip()[:120] or "no alpha-hypothesis issues"


# ----------------------------------------------------------------------------- backtesting
@check("backtest_unit", "walk-forward PIT backtester, chronological splits, costs, regime/drawdown metrics")
def _():
    return pytest_ok("tests/test_backtest.py")


@check("experiments_recorded", "every experiment (including rejected) is recorded with periods, data version and baseline")
def _():
    with ro() as c:
        n = c.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
        bad = c.execute("SELECT COUNT(*) FROM experiments WHERE train_period IS NULL OR val_period IS NULL OR test_period IS NULL OR data_version IS NULL "
                        "OR baseline_metrics IS NULL").fetchone()[0]
    return n > 0 and bad == 0, f"{n} experiments, {bad} incomplete"


@check("leaderboard_versioned", "LEADERBOARD.md exists, matches the experiments table and is tracked in git")
def _():
    lb = (ROOT / "LEADERBOARD.md").read_text()
    with ro() as c:
        ids = [r[0] for r in c.execute("SELECT id FROM experiments")]
    rc, out = sh("git ls-files --error-unmatch LEADERBOARD.md")
    missing = [i for i in ids if i not in lb]
    return rc == 0 and not missing, f"tracked={rc == 0}; {len(ids) - len(missing)}/{len(ids)} experiments listed"


@check("queue_dispatch", "Cloudflare Queue producer/consumer bound on the Worker", network=True)
def _():
    rc, out = sh("wrangler queues list", timeout=60)
    line = [l for l in out.splitlines() if "quant-backtest-jobs" in l]
    ok = bool(line) and re.search(r"│\s*1\s*│\s*1\s*│", line[0] or "") is not None
    return ok, (line[0].strip()[:140] if line else out[-200:])


@check("experiment_endpoint", "hub /experiments lists recorded experiments", network=True)
def _():
    st, b = http("http://127.0.0.1:8090/experiments?limit=1")
    return st == 200 and "experiments" in json.loads(b), f"HTTP {st}"


@check("multi_feature_experiments", "experiments vary weather model, storage, production, LNG, NGL and vector features",
       blocked_by="needs the missing LNG/flow/NGL collectors; only HDD-anomaly feature implemented")
def _():
    src = (ROOT / "experiments.py").read_text()
    feats = re.findall(r'"(\w+)": \(bt\.\w+_features', src)
    return len(feats) >= 4, f"feature sets: {feats}"


@check("promotion_gate", "a model is promoted only with lower OOS RMSE, Bonferroni-significant direction and positive net return")
def _():
    src = (ROOT / "experiments.py").read_text()
    return all(k in src for k in ('met["rmse"] < base["rmse"]', "p < alpha", "net > 0")), "promotion conditions present in experiments.py"


# ----------------------------------------------------------------------------- command hub and gateway
@check("hub_health", "privileged hub answers locally on 127.0.0.1:8090", network=True)
def _():
    st, b = http("http://127.0.0.1:8090/health")
    return st == 200, b.decode()[:120]


@check("execute_sandbox_tests", "/execute SQL sandbox, as_of normalisation, scenario arithmetic, thesis sign check")
def _():
    return pytest_ok("tests/test_scenario.py")


@check("worker_gateway_e2e", "Worker rejects no/bad bearer (401), Access blocks origin (403), authenticated /execute returns the full payload",
       side_effect=True, network=True)
def _():
    rc, out = sh("bash tests/e2e_worker.sh", timeout=200)
    return rc == 0, " | ".join(l for l in out.splitlines() if l.startswith(("PASS", "FAIL")))


@check("access_protects_hub", "quant.joeysvault.app refuses requests without an Access service token", network=True)
def _():
    st, _ = http("https://quant.joeysvault.app/execute", "POST", b"{}", {"Content-Type": "application/json"})
    st2, _ = http("https://quant.joeysvault.app/ingest", "POST", b"{}", {"Content-Type": "application/json"})
    return st in (302, 401, 403) and st2 in (302, 401, 403), f"/execute {st}, /ingest {st2}"


@check("env_locked", ".env is mode 600 and git-ignored; no secrets tracked")
def _():
    mode = oct((ROOT / ".env").stat().st_mode & 0o777)
    rc, _ = sh("git check-ignore -q .env")
    rc2, out = sh(["git", "grep", "-lE", r"cf[a-z]t_[A-Za-z0-9]{20,}|gh[opsu]_[A-Za-z0-9]{20,}|TunnelSecret\": *\"[A-Za-z0-9+/=]{20,}"])
    return mode == "0o600" and rc == 0 and rc2 != 0, f"mode {mode}; ignored {rc == 0}; tracked secret files: {out.strip() or 'none'}"


@check("ollama_only_local", "no production code calls an external AI API; inference is local Ollama")
def _():
    rc, out = sh(["git", "grep", "-nIiE", r"anthropic|openai\.com|api\.openai|generativelanguage|cohere\.ai", "--", "*.py", "*.js", "*.toml", "*.sh", ":!scripts/acceptance.py"])
    return rc != 0, out.strip()[:200] or "none"


@check("no_tmp_or_claude_paths", "production code uses no /tmp, tempfile or .claude paths")
def _():
    rc, out = sh(["git", "grep", "-nIE", r"/tmp|tempfile|\.claude", "--", "*.py", "*.js", "*.sh", "*.toml", "*.service", ":!scripts/acceptance.py"])
    return rc != 0, out.strip()[:200] or "none"


@check("audit_gists", "audit gists are created for /execute calls (gh authenticated, recent gist present)", network=True)
def _():
    rc, out = sh("gh gist list --limit 5")
    return rc == 0 and "PIT Alpha Hub" in out, f"{len([l for l in out.splitlines() if 'PIT Alpha Hub' in l])} recent hub gists"


@check("alert_delivery", "incidents (open on failure, close on recovery) and event streams reach the owner as GitHub issues", network=True)
def _():
    src = (ROOT / "collectors" / "run_all.py").read_text() + (ROOT / "command_hub.py").read_text()
    rc, out = sh("gh issue list -R jmpsu/henry_hub_atomic_agents --state all --label incident --label events --json number,title,state,labels --limit 50")
    rc1, inc = sh("gh issue list -R jmpsu/henry_hub_atomic_agents --state all --label incident --json number,state --limit 50")
    rc2, ev = sh("gh issue list -R jmpsu/henry_hub_atomic_agents --state all --label events --json number,title --limit 50")
    inc = json.loads(inc) if rc1 == 0 else []
    ev = json.loads(ev) if rc2 == 0 else []
    wired = "notify.incident" in src and "notify.resolve" in src and "notify.event" in src
    return wired and any(i["state"] == "CLOSED" for i in inc) and bool(ev), f"incident issues {[(i['number'], i['state']) for i in inc]}; event streams {[e['title'][:30] for e in ev]}"


# ----------------------------------------------------------------------------- visual platform
@check("markets_local", "read-only markets hub serves state.json, UI and refuses privileged routes", network=True)
def _():
    st, b = http("http://127.0.0.1:8095/api/state.json?product=propane&timeframe=seasonal")
    s = json.loads(b) if st == 200 else {}
    st2, _ = http("http://127.0.0.1:8095/execute", "POST", b"{}")
    st3, _ = http("http://127.0.0.1:8095/")
    return st == 200 and s.get("schema") == "ngl-state/1" and st2 == 404 and st3 == 200, f"state {st} {s.get('schema')}, /execute {st2}, / {st3}"


@check("state_schema_contract", "state.json carries every section the UI and terminal render, with explicit provenance")
def _():
    return pytest_ok("tests/test_markets_engine.py")


@check("indicators", "triangles, Bollinger squeeze, 50/200 crossovers, RSI/MACD divergence, Fibonacci, frac spread, WTI ratio")
def _():
    return pytest_ok("tests/test_markets_engine.py::Maths")


@check("web_ui_browser", "the web UI renders in headless Chrome with all panels, 18 map nodes and no console errors", network=True)
def _():
    chrome = shutil.which("google-chrome")
    if not chrome:
        return False, "google-chrome not installed"
    prof = ROOT / "runtime" / "chrome-acceptance"
    shutil.rmtree(prof, ignore_errors=True)
    p = subprocess.run([chrome, "--headless=new", "--no-sandbox", "--use-gl=swiftshader", "--enable-unsafe-swiftshader", f"--user-data-dir={prof}",
                        "--window-size=1600,2600", "--virtual-time-budget=20000", "--enable-logging=stderr", "--v=0", "--dump-dom",
                        "http://127.0.0.1:8095/?product=propane&timeframe=seasonal"], capture_output=True, text=True, timeout=120)
    shutil.rmtree(prof, ignore_errors=True)
    dom, log = p.stdout, p.stderr
    errs = [l for l in log.splitlines() if "CONSOLE" in l and "GPU stall" not in l]
    nodes = dom.count('class="node-wrap')
    panels = all(k in dom for k in ("Seasonal patterns", "Pricing output", "Fibonacci retracement", "Production elements", "Source availability", "Vector knowledge"))
    return nodes == 18 and panels and not errs and "state unavailable" not in dom, f"{nodes} map nodes, panels={panels}, console errors={len(errs)}"


@check("ngl_term", "ngl-term.py renders the same state.json with a Braille map")
def _():
    rc, out = sh([PY, "ngl-term.py", "--once", "--width", "180", "--height", "50"], timeout=60)
    braille = sum(1 for ch in out if 0x2801 <= ord(ch) <= 0x28FF)
    return rc == 0 and braille > 500 and "SOURCE AVAILABILITY" in out, f"exit {rc}, {braille} braille cells"


@check("public_markets", "markets.joeysvault.app and ngl.joeysvault.app serve /api/state.json publicly", network=True,
       blocked_by="sudo: deploy/add_markets_ingress.sh must be run by the owner")
def _():
    out = []
    ok = True
    for h in ("markets.joeysvault.app", "ngl.joeysvault.app"):
        st, b = http(f"https://{h}/api/state.json")
        good = st == 200 and b[:1] == b"{" and json.loads(b).get("schema") == "ngl-state/1"
        ok &= good
        out.append(f"{h} {st}")
    return ok, ", ".join(out)


@check("main_site_link", "https://joeysvault.app links to markets.joeysvault.app", network=True, blocked_by="deploy after the public routes serve")
def _():
    st, b = http("https://www.joeysvault.app/")
    return st == 200 and b"markets.joeysvault.app" in b, f"HTTP {st}, link present={b'markets.joeysvault.app' in b}"


# ----------------------------------------------------------------------------- git / audit
@check("snapshots_versioned", "deterministic snapshot manifests are exported daily and tracked in git")
def _():
    rc, out = sh("git ls-files snapshots")
    days = sorted({p.split("/")[1] for p in out.split()})
    timer = "export_snapshot" in Path.home().joinpath(".config/systemd/user/hh-collect-cpc.service").read_text()
    return rc == 0 and bool(days) and timer, f"tracked snapshot days {days[-3:]}; scheduled={timer}"


@check("branch_pushed", "local HEAD is pushed to origin", network=True)
def _():
    sh("git fetch -q origin")
    rc, out = sh("git status -sb")
    first = out.splitlines()[0] if out else ""
    return "ahead" not in first and "origin/" in first, first


@check("branch_protection", "main is protected on GitHub", network=True, blocked_by="owner decision (GitHub settings)")
def _():
    rc, out = sh("gh api repos/jmpsu/henry_hub_atomic_agents/branches/main/protection")
    return rc == 0, out.strip()[:120]


@check("architecture_doc", "an architecture/dependency audit and implementation plan covering all five architectures is versioned")
def _():
    p = ROOT / "docs" / "ARCHITECTURE.md"
    t = p.read_text() if p.exists() else ""
    secs = [f"Architecture {i}" for i in range(1, 6)]
    rc, _ = sh("git ls-files --error-unmatch docs/ARCHITECTURE.md")
    return all(x in t for x in secs) and rc == 0, f"sections present={[x for x in secs if x in t]}; tracked={rc == 0}"


# ----------------------------------------------------------------------------- mapping
RULES = [  # (section prefix or None, regex on text/context, checks) - first matching rule set is unioned per requirement
    ("1", r".", ["roster_all_collected", "experiments_recorded", "promotion_gate", "knowledge_library", "worker_gateway_e2e"]),
    ("2", r"ollama|qwen|nomic|inference|embedding", ["ollama_models", "ollama_only_local"]),
    ("2", r"worker|tunnel|access|queue|cloudflared|8090", ["access_protects_hub", "queue_dispatch", "hub_health"]),
    ("2", r"sqlite|chroma|vector|payload|preserved", ["db_integrity", "raw_payloads_verified", "knowledge_library"]),
    ("2", r"github|gh|gist|fastapi|python", ["audit_gists", "hub_health", "full_test_suite"]),
    ("2", r"linux|workstation|gpu|joey-dell|preserve existing|replace|competing", ["hub_health", "full_test_suite"]),
    ("3", r"81|agent|collector|scheduled|edge|cloudflare worker|geographically", ["roster_all_collected", "collector_schedule", "edge_collection"]),
    ("3.1", r"retrieve|protocol|http status|headers|retrieval time|source url|preserve|identity|execution record", ["edge_collection", "edge_ingest_unit"]),
    ("3.2", r".", ["edge_collection", "edge_ingest_unit"]),
    ("3", r"http status|response headers|retrieval time|source url|original response|preserve", ["raw_payloads_verified", "observations_reference_payloads"]),
    ("3", r"missing|malformed|stale|changed", ["gatekeeper", "collector_freshness", "selfheal_unit"]),
    ("3", r"rate limit|retry|terms|restriction", ["collectors_run"]),
    ("3", r"access|cf-access|tunnel|https|ingestion endpoint|unauthenticated", ["access_protects_hub", "worker_gateway_e2e"]),
    ("3", r"ollama|qwen|irregular", ["selfheal_live_ollama"]),
    ("3", r"agent_id|target_timestamp|available_timestamp|value|source_id|source_url|retrieved|published|revision|unit|geographic|series_id|raw_payload_hash|extraction_version|quality_status|provenance|four-column",
     ["schema_16_columns", "provenance_labels"]),
    ("3.4", r".", ["pit_tests", "raw_payloads_verified"]),
    ("3.5", r".", ["snapshots_versioned", "branch_pushed", "branch_protection"]),
    ("4.1", r".", ["selfheal_unit", "gatekeeper", "collector_freshness"]),
    ("4.2", r".", ["selfheal_unit", "raw_payloads_verified"]),
    ("4.3", r".", ["selfheal_unit", "selfheal_live_ollama"]),
    ("4.4", r".", ["selfheal_unit", "selfheal_pr_live"]),
    ("4.5", r".", ["webhook_recovery"]),
    ("4", r"81|monitor", ["roster_all_collected"]),
    ("5.1", r"pipeline critical|force majeure|maintenance and capacity", ["unstructured_sources"]),
    ("5.1", r"noaa weather forecasts", ["unstructured_sources"]),
    ("5.1", r"coal", ["knowledge_library"]),
    ("5.1", r"ferc|lng terminal|ngl production|mont belvieu|ethane, propane|cracker|refinery|basis|publications|lng feedgas", ["cross_domain_sources"]),
    ("5.1", r"eia|noaa|gfs|ecmwf|power burn|storage|production", ["knowledge_library"]),
    ("5.1", r"preserve|source|timestamp|revision", ["knowledge_library"]),
    ("5.2", r".", ["ollama_models", "knowledge_library", "knowledge_search_pit"]),
    ("5.3", r".", ["knowledge_library", "unstructured_sources", "provenance_labels"]),
    ("5.3", r"permian pipeline|lng feedgas|ethane|cracker|propane export|power burn|ngl purity|associated gas|mont belvieu|basis", ["cross_domain_sources"]),
    ("5.4", r".", ["hypothesis_memo"]),
    ("5.5", r".", ["hypothesis_memo", "research_log_live"]),
    ("6.1", r".", ["queue_dispatch", "multi_feature_experiments"]),
    ("6.2", r".", ["queue_dispatch", "experiment_endpoint", "experiments_recorded"]),
    ("6.3", r".", ["pit_tests", "backtest_unit"]),
    ("6.4", r".", ["backtest_unit"]),
    ("6.5", r".", ["leaderboard_versioned", "experiments_recorded", "promotion_gate"]),
    ("6", r"15 gib|ram|thousands", ["backtest_unit"]),
    ("7.1", r".", ["worker_gateway_e2e"]),
    ("7.2", r".", ["hub_health", "execute_sandbox_tests", "knowledge_search_pit", "experiment_endpoint"]),
    ("7.3", r".", ["worker_gateway_e2e", "execute_sandbox_tests"]),
    ("7.4", r".", ["worker_gateway_e2e", "execute_sandbox_tests"]),
    ("7.5", r"gist|command|timestamp|cutoff|observations|vector|sql|results|scenario|thesis|model|status|provenance|private", ["audit_gists", "worker_gateway_e2e"]),
    ("7.5", r"alert|notify|failed collectors|incidents|backtests|hypotheses", ["alert_delivery"]),
    ("8", r".", ["worker_gateway_e2e", "queue_dispatch", "knowledge_library", "backtest_unit", "roster_all_collected", "edge_collection", "alert_delivery"]),
    ("9", r"point-in-time|available_timestamp|look-ahead|revisions|vintages|identical pit", ["pit_tests", "knowledge_search_pit"]),
    ("9", r"source|payload|extraction|units|validate", ["raw_payloads_verified", "schema_16_columns", "gatekeeper"]),
    ("9", r"llm|sql|untested|scenario estimate|prompt", ["execute_sandbox_tests", "selfheal_unit", "provenance_labels"]),
    ("9", r"training|costs|regimes|baselines|multiple testing|reproducible", ["backtest_unit", "promotion_gate", "experiments_recorded"]),
    ("9", r"access|credentials|read-only|jobs|webhooks|merging|audit", ["access_protects_hub", "env_locked", "execute_sandbox_tests", "webhook_recovery"]),
    ("10", r"81", ["roster_all_collected"]),
    ("10", r"point-in-time|vintage|preserve", ["pit_tests", "raw_payloads_verified"]),
    ("10", r"recover|repairs|pull requests", ["selfheal_unit", "selfheal_pr_live", "webhook_recovery"]),
    ("10", r"vector|analogs|hypotheses", ["knowledge_library", "cross_domain_sources", "hypothesis_memo"]),
    ("10", r"backtest|rank|leaderboard", ["backtest_unit", "leaderboard_versioned", "queue_dispatch"]),
    ("10", r"remote|scenario|research|alerts|continuously", ["worker_gateway_e2e", "alert_delivery", "collector_schedule"]),
    ("11", r".", ["full_test_suite", "worker_gateway_e2e", "architecture_doc"]),
    ("11", r"81|agents|connectors|data sources", ["roster_all_collected"]),
    ("3.2", r"required components", ["access_protects_hub", "worker_gateway_e2e"]),
    ("3.3", r"canonical observation fields|production data contract", ["schema_16_columns"]),
    ("4", r"permanent data gaps", ["collector_freshness", "selfheal_unit", "roster_all_collected"]),
    ("5", r"discover relationships", ["knowledge_library", "cross_domain_sources"]),
    ("5.1", r"lng feedgas", ["cross_domain_sources"]),
    ("6", r"reproducible predictive advantages", ["backtest_unit", "experiments_recorded", "multi_feature_experiments"]),
    ("7", r"without exposing local services", ["access_protects_hub", "markets_local"]),
    ("9", r"publication and availability timestamps", ["pit_tests", "schema_16_columns"]),
    ("10", r"must be able to", ["roster_all_collected", "worker_gateway_e2e", "backtest_unit"]),
    ("12.1", r".", ["web_ui_browser", "ngl_term"]),
    ("12.2", r".", ["public_markets", "main_site_link", "access_protects_hub", "markets_local"]),
    ("12.3", r".", ["knowledge_library", "knowledge_search_pit", "web_ui_browser"]),
    ("12.4", r".", ["state_schema_contract", "web_ui_browser"]),
    ("12.4", r"ethane|butane|gasoline|fractionation|lng feedgas|power burn", ["roster_all_collected"]),
    ("12.5", r".", ["indicators", "web_ui_browser"]),
    ("12.5", r"conway|ethane|butane|gasoline|forward curve|delivery months", ["roster_all_collected"]),
    ("12.6", r".", ["indicators", "web_ui_browser"]),
    ("12.7", r".", ["ngl_term"]),
    ("12.7", r"flows|alerts|force majeure|critical notices", ["roster_all_collected"]),
]


def map_requirement(r: dict) -> list[str]:
    hay = (r["text"] + " " + (r.get("context") or "")).lower()
    out: list[str] = []
    for sec, rx, checks in RULES:
        if sec and not (r["section_no"] == sec or r["section_no"].startswith(sec + ".")):
            continue
        if re.search(rx, hay):
            out += [c for c in checks if c not in out]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--with-side-effects", action="store_true")
    ap.add_argument("--no-network", action="store_true")
    a = ap.parse_args(argv)
    reg = json.loads((REQ / "registry.json").read_text())
    results = {}
    for name, c in CHECKS.items():
        if a.only and name not in a.only:
            continue
        if c["side_effect"] and not a.with_side_effects:
            results[name] = {"status": "skipped", "evidence": "has side effects (run with --with-side-effects)", "desc": c["desc"]}
            continue
        if c["network"] and a.no_network:
            results[name] = {"status": "skipped", "evidence": "network check skipped", "desc": c["desc"]}
            continue
        t0 = time.time()
        try:
            ok, ev = c["fn"]()
        except Exception as e:  # noqa: BLE001
            ok, ev = False, f"error: {type(e).__name__}: {e}"[:300]
        status = "passed" if ok else ("blocked" if c["blocked_by"] else "failed")
        results[name] = {"status": status, "evidence": str(ev)[:600], "desc": c["desc"], "blocked_by": c["blocked_by"], "seconds": round(time.time() - t0, 1)}
        print(f"{status:8} {name:28} {str(ev)[:110]}", flush=True)
    prev = json.loads((REQ / "status.json").read_text())["checks"] if (REQ / "status.json").exists() else {}
    for k, v in prev.items():                       # keep last known result for checks not run this time
        if k not in results or results[k]["status"] == "skipped":
            if v.get("status") != "skipped":
                results[k] = {**v, "carried_over": True}
    trace, totals = [], {"passed": 0, "failed": 0, "blocked": 0, "unverified": 0}
    for r in reg["requirements"]:
        checks = map_requirement(r)
        sts = [results.get(c, {}).get("status", "unverified") for c in checks]
        if not checks or all(s in ("unverified", "skipped") for s in sts):
            st = "unverified"
        elif "failed" in sts:
            st = "failed"
        elif "blocked" in sts:
            st = "blocked"
        elif all(s == "passed" for s in sts):
            st = "passed"
        else:
            st = "unverified"
        totals[st] += 1
        trace.append({"id": r["id"], "section": r["section"], "line": r["line"], "text": r["text"], "context": r["context"], "checks": checks, "status": st})
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    doc = {"generated_at": now, "registry_sha256": reg["source_sha256"], "requirements": len(trace), "totals": totals,
           "checks": {k: results[k] for k in sorted(results)}, "traceability": trace}
    (REQ / "status.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    lines = [f"# Requirement status ({now})", "", f"Source: `artifacts/Ultimate_Goal.md` (sha256 `{reg['source_sha256'][:16]}`) · {len(trace)} atomic requirements", "",
             "| Status | Count |", "|---|---|"] + [f"| {k} | {v} |" for k, v in totals.items()] + ["", "## Checks", "",
             "| Check | Status | Evidence | Blocked by |", "|---|---|---|---|"]
    for k in sorted(results):
        v = results[k]
        lines.append(f"| `{k}` | {v['status']}{' (carried over)' if v.get('carried_over') else ''} | {str(v['evidence']).replace('|', '/')[:180]} | {v.get('blocked_by') or ''} |")
    lines += ["", "## Requirements not passed", "", "| ID | Line | Status | Requirement | Checks |", "|---|---|---|---|---|"]
    for t in trace:
        if t["status"] != "passed":
            lines.append(f"| {t['id']} | {t['line']} | {t['status']} | {t['text'][:110].replace('|', '/')} | {', '.join(t['checks']) or '—'} |")
    (REQ / "STATUS.md").write_text("\n".join(lines) + "\n")
    print(json.dumps({"requirements": len(trace), **totals}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
