joey@joey-dell:~/Projects/henry_hub_atomic_agents$
cd ~/Projects/henry_hub_atomic_agents || exit 1
set -u
export LC_ALL=C
REPO="jmpsu/henry_hub_atomic_agents"
ROOT="$PWD"

section() { printf '\n\n========== %s ==========\n' "$1"; }
run() { "$@" 2>&1 || true; }

section "1. GIT SOURCE AND WORKING TREE"
git branch --show-current
git log -1 --format='HEAD: %H%nCommit: %s'
git remote -v
git status --short
git branch -vv
git tag --sort=-version:refname | head -15

section "2. REPOSITORY DEPLOYMENT FILES"
find .github deploy scripts release migrations tests -maxdepth 3 -type f \
  -not -path '*/__pycache__/*' -printf '%p\n' 2>/dev/null | sort
printf '\nRoot build/config files:\n'
find . -maxdepth 1 -type f -printf '%f\n' | sort

section "3. LIVE SYSTEMD SERVICES AND TIMERS"
for UNIT in quant_hub.service markets_hub.service \
            hh-collect-cpc.service hh-collect-cpc.timer; do
  echo "--- $UNIT ---"
  systemctl cat "$UNIT" 2>&1
  systemctl show "$UNIT" \
    -p LoadState -p ActiveState -p SubState -p User \
    -p WorkingDirectory -p FragmentPath -p ExecStart \
    -p Environment -p EnvironmentFiles 2>&1
done

section "4. COMPLETE LOCAL ENVIRONMENT FILES"
for FILE in /home/joey/Projects/henry_hub_atomic_agents/.env \
            /etc/henry-hub/production.env; do
  if [[ -f "$FILE" ]]; then
    echo "--- $FILE ---"
    cat "$FILE"
  else
    echo "Not present: $FILE"
  fi
done

section "5. APPLICATION PATHS, DATA AND STORAGE"
printf 'Project: %s\n' "$ROOT"
for PATHNAME in .venv/quant_hub .venv/bin/python .venv/bin/uvicorn \
                henry_hub_pit.db chroma_pit_kb raw runtime snapshots \
                artifacts web collectors; do
  if [[ -e "$PATHNAME" ]]; then
    du -sh "$PATHNAME" 2>/dev/null || ls -ld "$PATHNAME"
  else
    echo "Missing: $PATHNAME"
  fi
done
df -h "$ROOT" /var/lib /opt 2>/dev/null

printf '\nDatabase tables and schema (read-only):\n'
if [[ -f henry_hub_pit.db ]]; then
  python - <<'PY'
import sqlite3
from pathlib import Path
echo "No files edited, no services restarted, no deployment performed."pytest|skipif' \Ref.name}' 2>&1os\.system\(' \


========== 1. GIT SOURCE AND WORKING TREE ==========
quant-hub-build
HEAD: 5e8fdfcc7702b4761ec2f3f80140fce80e9f85c3
Commit: Research agents on local Ollama, shared knowledge memory, graphical knowledge explorer
origin	https://github.com/jmpsu/henry_hub_atomic_agents.git (fetch)
origin	https://github.com/jmpsu/henry_hub_atomic_agents.git (push)
 M artifacts/Ultimate_Goal.md
 M snapshots/2026-11-14/LEADERBOARD.md
 M snapshots/2026-11-14/experiments.json
 M snapshots/2026-11-14/ingestion.json
 M snapshots/2026-11-14/manifest.json
 M snapshots/2026-11-14/sources.json
?? CLAUDE.md
?? artifacts/CHATGPT-INBOX.txt
?? artifacts/COMPLETION_ACCEPTANCE_AUDIT.md
?? "artifacts/Global Maritime Traffic Explorer.pdf"
?? "artifacts/NGL  technical audit latest version output"
?? "artifacts/NGL  technical audit latest version output v1"
?? "artifacts/NGL  technical audit latest version output v2"
?? "artifacts/NGL Henry Hub Visual Intelligence"
?? "artifacts/NGL pipeline and meter map view.png"
?? "artifacts/NGL pipeline and meter map view.webp"
?? "artifacts/NUCLEAR DEEP-DIVE AUDIT description"
?? "artifacts/Real-time global maritime traffic visualization image example.png"
?? artifacts/Ultimate_Goal.md.odt
?? "artifacts/itemized deep-dive audit overall ngl project"
?? host_executor.py
?? ngl_claude_status_b1
?? scripts/ngl_full_readonly_audit.sh
?? snapshots/2026-11-15/
  main                                                        e11a221 [origin/main] feat: deploy zero-trust quant hub
* quant-hub-build                                             5e8fdfc [origin/quant-hub-build] Research agents on local Ollama, shared knowledge memory, graphical knowledge explorer
  selfheal/selfheal_demo/agent_selfheal_demo-20261114T003340Z cc3e66d [origin/quant-hub-build: behind 10] RGGI: exclude (Future) allowance rows that share an auction date; tests never write to the real raw/ archive
  selfheal/selfheal_demo/agent_selfheal_demo-20261114T003407Z b9189e8 [origin/quant-hub-build: behind 8] selfheal: Agent_SelfHeal_Demo add selector 'span.px-now' ahead of ['span.hh-price']


========== 2. REPOSITORY DEPLOYMENT FILES ==========
deploy/add_markets_ingress.sh
deploy/hh-collect-cpc.service
deploy/markets_hub.service
deploy/timeshift_exclude_home.sh
scripts/acceptance.py
scripts/build_basemap.py
scripts/export_snapshot.py
scripts/ngl_full_readonly_audit.sh
scripts/pit_audit.sh
scripts/requirements_registry.py
scripts/run_agents.py
tests/_scratch.py
tests/e2e_worker.sh
tests/fake_gh.sh
tests/fixtures/cpc_fxus06_sample.html
tests/fixtures/eia930_balance_sample.csv
tests/fixtures/eia_coal_archive_sample.json
tests/fixtures/eia_coal_transport_table1.xlsx
tests/fixtures/km_eec_notices_sample.html
tests/seed_demo.py
tests/test_agents.py
tests/test_alerts.py
tests/test_backtest.py
tests/test_cpc_collector.py
tests/test_cpc_history.py
tests/test_ecmwf_hdd.py
tests/test_edge_ingest.py
tests/test_eia930_power_burn.py
tests/test_eia_coal_rail.py
tests/test_eia_coal_spot.py
tests/test_eia_ng_monthly.py
tests/test_eia_petroleum_spot.py
tests/test_eia_prices.py
tests/test_eia_storage.py
tests/test_export_snapshot.py
tests/test_gatekeeper.py
tests/test_gfs_hdd.py
tests/test_ingest.py
tests/test_kb_chunking.py
tests/test_km_notices.py
tests/test_knowledge_explorer.py
tests/test_markets_engine.py
tests/test_ngl_term.py
tests/test_noaa_discussion.py
tests/test_ollama_live.py
tests/test_rggi.py
tests/test_scenario.py
tests/test_selfheal.py
tests/test_selfheal_pipeline.py
tests/test_steo_production.py

Root build/config files:
.env
.gitignore
CLAUDE.md
LEADERBOARD.md
agent-fetch-prompt.odt
agents_roster.json
alerts.py
backtest.py
cloudflared-ingress-snippet.yml
command_hub.py
experiments.py
henry_hub_pit.db
host_executor.py
ingest.py
init_db.py
kb_ingest.py
markets_engine.py
markets_hub.py
ngl-term.py
ngl_claude_status_b1
notify.py
requirements.txt
runtime_paths.py
scenario.py
selfheal.py
selfheal_pipeline.py
validate_env.py
worker.js
wrangler.toml


========== 3. LIVE SYSTEMD SERVICES AND TIMERS ==========
--- quant_hub.service ---
# /etc/systemd/system/quant_hub.service
[Unit]
Description=Henry Hub Point-in-Time Quant Command Hub
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=joey
WorkingDirectory=/home/joey/Projects/henry_hub_atomic_agents
Environment=PATH=/home/joey/Projects/henry_hub_atomic_agents/.venv/bin:/usr/local/bin:/usr/bin:/bin
EnvironmentFile=/home/joey/Projects/henry_hub_atomic_agents/.env
ExecStart=/home/joey/Projects/henry_hub_atomic_agents/.venv/bin/uvicorn command_hub:app --host 127.0.0.1 --port 8090
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
ExecStart={ path=/home/joey/Projects/henry_hub_atomic_agents/.venv/bin/uvicorn ; argv[]=/home/joey/Projects/henry_hub_atomic_agents/.venv/bin/uvicorn command_hub:app --host 127.0>
Environment=PATH=/home/joey/Projects/henry_hub_atomic_agents/.venv/bin:/usr/local/bin:/usr/bin:/bin
EnvironmentFiles=/home/joey/Projects/henry_hub_atomic_agents/.env (ignore_errors=no)
WorkingDirectory=/home/joey/Projects/henry_hub_atomic_agents
User=joey
LoadState=loaded
ActiveState=active
SubState=running
FragmentPath=/etc/systemd/system/quant_hub.service
--- markets_hub.service ---
No files found for markets_hub.service.
Environment=
WorkingDirectory=
User=
LoadState=not-found
ActiveState=inactive
SubState=dead
FragmentPath=
--- hh-collect-cpc.service ---
No files found for hh-collect-cpc.service.
Environment=
WorkingDirectory=
User=
LoadState=not-found
ActiveState=inactive
SubState=dead
FragmentPath=
--- hh-collect-cpc.timer ---
No files found for hh-collect-cpc.timer.
LoadState=not-found
ActiveState=inactive
SubState=dead
FragmentPath=


========== 4. COMPLETE LOCAL ENVIRONMENT FILES ==========
--- /home/joey/Projects/henry_hub_atomic_agents/.env ---
PORT=8090
DB_PATH=/home/joey/Projects/henry_hub_atomic_agents/henry_hub_pit.db
OLLAMA_URL=http://127.0.0.1:11434
AUDIT_GIST=1
CF_ACCESS_CLIENT_ID=3bfc1245df8a8871556da3a910978a2c.access
CF_ACCESS_CLIENT_SECRET=cfast_3aBCUoVGZ5o72wNCNd234Mwowgc3zHuQHEDrMNKe597f1abe
MOBILE_COMMAND_SECRET=0P00Rrylp4wCilyFe_ZOlFXpKz2GtTvxZq2sJ5YMRSo
Not present: /etc/henry-hub/production.env


========== 5. APPLICATION PATHS, DATA AND STORAGE ==========
Project: /home/joey/Projects/henry_hub_atomic_agents
Missing: .venv/quant_hub
0	.venv/bin/python
4.0K	.venv/bin/uvicorn
62M	henry_hub_pit.db
3.4M	chroma_pit_kb
337M	raw
6.9M	runtime
588K	snapshots
12M	artifacts
2.6M	web
276K	collectors
Filesystem      Size  Used Avail Use% Mounted on
/dev/nvme0n1p2  468G  315G  130G  71% /
/dev/nvme0n1p2  468G  315G  130G  71% /
/dev/nvme0n1p2  468G  315G  130G  71% /

Database tables and schema (read-only):
Command 'python' not found, did you mean:
  command 'python3' from deb python3
  command 'python' from deb python-is-python3


========== 6. APPLICATION CONFIGURATION AND HEALTH ROUTES ==========
command_hub.py:15:DB_PATH = os.environ.get("DB_PATH", "")
command_hub.py:16:if not DB_PATH or not os.path.isabs(DB_PATH) or not os.path.isfile(DB_PATH):
command_hub.py:18:    raise RuntimeError("DB_PATH must be set to an existing absolute path (see .env)")
command_hub.py:20:_HERE = os.path.dirname(os.path.realpath(__file__))
command_hub.py:21:chroma_client = chromadb.PersistentClient(path=os.path.join(_HERE, "chroma_pit_kb"))
command_hub.py:55:    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
command_hub.py:155:    return scenario.run_sandboxed(DB_PATH, sql, as_of)
command_hub.py:180:@app.post("/ingest")
command_hub.py:187:            return subprocess.run([sys.executable, os.path.join(_HERE, "collectors", "run_all.py")],
command_hub.py:189:                                  env={**os.environ, "DB_PATH": DB_PATH})
command_hub.py:196:            kb = await asyncio.to_thread(kb_ingest.ingest, DB_PATH, kb_collection)
command_hub.py:217:    sys.path.insert(0, _HERE)
command_hub.py:234:@app.post("/ingest/edge")
command_hub.py:260:        conn = sqlite3.connect(DB_PATH, timeout=30)
command_hub.py:295:@app.post("/selfheal/rerun")
command_hub.py:302:    sys.path.insert(0, _HERE)
command_hub.py:308:    deployed = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=_HERE, capture_output=True, text=True, timeout=10).stdout.strip()
command_hub.py:315:        git = lambda *a, t=120: subprocess.run(["git", *a], cwd=_HERE, capture_output=True, text=True, timeout=t)
command_hub.py:317:        conn = sqlite3.connect(DB_PATH, timeout=30)
command_hub.py:330:                wt = os.path.join(_HERE, "runtime", "worktrees", sha[:12])
command_hub.py:337:                                       capture_output=True, text=True, timeout=600, env={**os.environ, "DB_PATH": DB_PATH, "RAW_DIR": os.path.join(_HERE, "raw")})
command_hub.py:363:        rep = await asyncio.to_thread(workers.run_all, DB_PATH, kb_collection, None, None, max(1, min(notice_limit, 200)))
command_hub.py:369:@app.post("/agents/run")
command_hub.py:393:@app.get("/agents/activity")
command_hub.py:398:        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
command_hub.py:413:@app.post("/kb/ingest")
command_hub.py:419:        return await asyncio.to_thread(kb_ingest.ingest, DB_PATH, kb_collection)
command_hub.py:432:@app.post("/experiments/run")
command_hub.py:444:        out = await asyncio.to_thread(experiments.run, DB_PATH, job.n_decisions, (job.horizon_days,), (job.cost_bps,), (job.model,), job.slippage_bps)
command_hub.py:456:@app.get("/experiments")
command_hub.py:459:        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
command_hub.py:469:@app.get("/health")
command_hub.py:470:async def health():
command_hub.py:471:    return {"ok": True, "db": os.path.basename(DB_PATH), "vector_nodes": kb_collection.count()}
command_hub.py:473:@app.post("/execute")
command_hub.py:521:        "data_quality": scenario.data_quality(DB_PATH, as_of, db_rows),
markets_hub.py:25:BASE_DIR = Path(__file__).resolve().parent
markets_hub.py:26:WEB_DIR = BASE_DIR / "web"
markets_hub.py:27:DB_PATH = os.environ.get("DB_PATH") or str(BASE_DIR / "henry_hub_pit.db")
markets_hub.py:28:if not os.path.isabs(DB_PATH) or not os.path.isfile(DB_PATH):
markets_hub.py:29:    raise RuntimeError("DB_PATH must be an existing absolute path")
markets_hub.py:54:    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
markets_hub.py:71:    return me.cached_state(DB_PATH, product, timeframe, cutoff, knowledge)
markets_hub.py:74:@app.get("/api/state.json")
markets_hub.py:80:@app.get("/api/market")
markets_hub.py:85:@app.get("/api/health")
markets_hub.py:86:def health():
markets_hub.py:96:@app.get("/api/knowledge-graph")
markets_hub.py:106:@app.get("/api/knowledge-node/{node_id}")
markets_hub.py:122:@app.get("/api/agents/activity")
markets_hub.py:132:@app.get("/knowledge")
markets_hub.py:143:@app.post("/api/knowledge-search")
markets_hub.py:174:@app.get("/")
markets_hub.py:179:@app.get("/static/{path:path}")
init_db.py:2:Usage: python init_db.py [path]   (defaults to $DB_PATH or ./henry_hub_pit.db)"""
init_db.py:52:    target = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("DB_PATH", "henry_hub_pit.db")
runtime_paths.py:8:BASE_DIR = Path(__file__).resolve().parent
runtime_paths.py:9:RUNTIME_DIR = Path(os.environ.get("QH_RUNTIME_DIR", BASE_DIR / "runtime"))


========== 7. PROJECT-PATH DEPENDENCIES AND SUBPROCESS CALLS ==========
./markets_engine.py:4:- Every number comes from henry_hub_pit.db through a point-in-time read (available_timestamp <= as_of, latest vintage).
./markets_engine.py:646:    db = os.environ.get("DB_PATH") or str(BASE_DIR / "henry_hub_pit.db")
./host_executor.py:38:        "/home/joey/Projects/henry_hub_atomic_agents/.venv/bin/python -m ingestion.orchestration.run_all",
./experiments.py:115:    db = os.environ.get("DB_PATH") or str(HERE / "henry_hub_pit.db")
./collectors/eia_ng_monthly.py:95:    db = os.environ.get("DB_PATH") or str(Path(__file__).resolve().parent.parent / "henry_hub_pit.db")
./collectors/eia_storage.py:88:    db = os.environ.get("DB_PATH") or str(Path(__file__).resolve().parent.parent / "henry_hub_pit.db")
./collectors/run_all.py:72:        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=Path(__file__).resolve().parent.parent, capture_output=True,
./collectors/run_all.py:82:    db = os.environ.get("DB_PATH") or str(Path(__file__).resolve().parent.parent / "henry_hub_pit.db")
./collectors/eia_coal_rail.py:89:    db = os.environ.get("DB_PATH") or str(Path(__file__).resolve().parent.parent / "henry_hub_pit.db")
./collectors/ecmwf_hdd.py:85:    db = os.environ.get("DB_PATH") or str(Path(__file__).resolve().parent.parent / "henry_hub_pit.db")
./collectors/eia_coal_spot.py:81:    db = os.environ.get("DB_PATH") or str(Path(__file__).resolve().parent.parent / "henry_hub_pit.db")
./collectors/steo_production.py:102:    db = os.environ.get("DB_PATH") or str(Path(__file__).resolve().parent.parent / "henry_hub_pit.db")
./collectors/rggi_auctions.py:74:    db = os.environ.get("DB_PATH") or str(Path(__file__).resolve().parent.parent / "henry_hub_pit.db")
./collectors/noaa_cpc_discussion.py:77:    db = os.environ.get("DB_PATH") or str(Path(__file__).resolve().parent.parent / "henry_hub_pit.db")
./collectors/eia_prices.py:82:    db = os.environ.get("DB_PATH") or str(Path(__file__).resolve().parent.parent / "henry_hub_pit.db")
./collectors/cpc_degree_days.py:69:    db = os.environ.get("DB_PATH") or str(Path(__file__).resolve().parent.parent / "henry_hub_pit.db")
./collectors/eia930_power_burn.py:139:    db = os.environ.get("DB_PATH") or str(Path(__file__).resolve().parent.parent / "henry_hub_pit.db")
./collectors/cpc_history.py:79:    db = os.environ.get("DB_PATH") or str(Path(__file__).resolve().parent.parent / "henry_hub_pit.db")
./collectors/eia_petroleum_spot.py:61:    db = os.environ.get("DB_PATH") or str(Path(__file__).resolve().parent.parent / "henry_hub_pit.db")
./collectors/kinder_morgan_notices.py:89:    db = os.environ.get("DB_PATH") or str(Path(__file__).resolve().parent.parent / "henry_hub_pit.db")
./collectors/gfs_hdd.py:123:    db = os.environ.get("DB_PATH") or str(Path(__file__).resolve().parent.parent / "henry_hub_pit.db")
./agents/memory.py:3:Memory = the knowledge library (kb_nodes/kb_edges in henry_hub_pit.db + the Chroma collection henry_hub_alpha_graph).
./agents/workers.py:912:    db = os.environ.get("DB_PATH") or str(ROOT / "henry_hub_pit.db")
./selfheal_pipeline.py:40:    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
./kb_ingest.py:4:Storage: tables kb_nodes / kb_edges in henry_hub_pit.db (the graph and a float32 embedding per node), and the same
./kb_ingest.py:472:    db = os.environ.get("DB_PATH") or str(BASE_DIR / "henry_hub_pit.db")
./command_hub.py:21:chroma_client = chromadb.PersistentClient(path=os.path.join(_HERE, "chroma_pit_kb"))
./command_hub.py:169:    proc = subprocess.run(
./command_hub.py:187:            return subprocess.run([sys.executable, os.path.join(_HERE, "collectors", "run_all.py")],
./command_hub.py:308:    deployed = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=_HERE, capture_output=True, text=True, timeout=10).stdout.strip()
./command_hub.py:315:        git = lambda *a, t=120: subprocess.run(["git", *a], cwd=_HERE, capture_output=True, text=True, timeout=t)
./command_hub.py:336:                    p = subprocess.run([sys.executable, os.path.join(wt, "collectors", "run_all.py"), "--only", req.collector], cwd=wt,
./scripts/acceptance.py:33:DB = os.environ.get("DB_PATH") or str(ROOT / "henry_hub_pit.db")
./scripts/acceptance.py:48:    p = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True, timeout=timeout, cwd=cwd, env={**os.environ, **(env or {})})
./scripts/acceptance.py:441:    p = subprocess.run([chrome, "--headless=new", "--no-sandbox", "--use-gl=swiftshader", "--enable-unsafe-swiftshader", f"--user-data-dir={prof}",
./scripts/acceptance.py:560:    ch = sqlite3.connect(f"file:{ROOT / 'chroma_pit_kb' / 'chroma.sqlite3'}?mode=ro", uri=True)
./scripts/acceptance.py:602:    p = subprocess.run([chrome, "--headless=new", "--no-sandbox", f"--user-data-dir={prof}", "--window-size=1600,1400", "--virtual-time-budget=15000",
./scripts/export_snapshot.py:14:Usage: scripts/export_snapshot.py [--as-of 2026-11-13T23:59:59Z] [--out snapshots] [--db henry_hub_pit.db]
./scripts/export_snapshot.py:129:    ap.add_argument("--db", default=os.environ.get("DB_PATH") or str(ROOT / "henry_hub_pit.db"))
./init_db.py:2:Usage: python init_db.py [path]   (defaults to $DB_PATH or ./henry_hub_pit.db)"""
./init_db.py:52:    target = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("DB_PATH", "henry_hub_pit.db")
./markets_hub.py:27:DB_PATH = os.environ.get("DB_PATH") or str(BASE_DIR / "henry_hub_pit.db")
./notify.py:33:    p = subprocess.run([gh, *args], input=input_text, capture_output=True, text=True, timeout=timeout)
./selfheal.py:172:    return {"dry_run": False, "output": subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout.strip()}
./deploy/markets_hub.service:10:WorkingDirectory=/home/joey/Projects/henry_hub_atomic_agents
./deploy/markets_hub.service:11:Environment=DB_PATH=/home/joey/Projects/henry_hub_atomic_agents/henry_hub_pit.db
./deploy/markets_hub.service:12:Environment=PATH=/home/joey/Projects/henry_hub_atomic_agents/.venv/bin:/usr/local/bin:/usr/bin:/bin
./deploy/markets_hub.service:13:ExecStart=/home/joey/Projects/henry_hub_atomic_agents/.venv/bin/uvicorn markets_hub:app --host 127.0.0.1 --port 8095 --no-server-header
./deploy/hh-collect-cpc.service:7:WorkingDirectory=/home/joey/Projects/henry_hub_atomic_agents
./deploy/hh-collect-cpc.service:8:Environment=DB_PATH=/home/joey/Projects/henry_hub_atomic_agents/henry_hub_pit.db
./deploy/hh-collect-cpc.service:9:ExecStart=/home/joey/Projects/henry_hub_atomic_agents/.venv/bin/python /home/joey/Projects/henry_hub_atomic_agents/collectors/run_all.py
./deploy/hh-collect-cpc.service:10:ExecStartPost=/home/joey/Projects/henry_hub_atomic_agents/.venv/bin/python /home/joey/Projects/henry_hub_atomic_agents/scripts/export_snapshot.py
./deploy/hh-collect-cpc.service:11:ExecStopPost=/home/joey/Projects/henry_hub_atomic_agents/.venv/bin/python /home/joey/Projects/henry_hub_atomic_agents/scripts/run_agents.py
./alerts.py:49:    return {"dry_run": False, "output": subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout.strip()}


========== 8. CLOUDFLARE WORKER CONFIGURATION ==========
name = "quant-gateway"
main = "worker.js"
compatibility_date = "2026-11-01"

[vars]
ORIGIN_URL = "https://quant.joeysvault.app/execute"
SELFHEAL_BASE = "quant-hub-build"   # branch the live system runs; self-heal PRs target it (switch to "main" after merging)

[triggers]
crons = ["30 13 * * *", "45 15 * * THU"]  # daily 13:30 UTC (CPC); Thursdays 15:45 UTC (EIA storage, released 15:30Z). Day NAME used: Cloudflare numbers Sunday as 1

# Backtest experiment dispatch: POST /enqueue (bearer) -> queue -> this Worker's queue() -> hub /experiments/run (local compute)
[[queues.producers]]
queue = "quant-backtest-jobs"
binding = "BACKTEST_JOBS"

[[queues.consumers]]
queue = "quant-backtest-jobs"
max_batch_size = 1
max_concurrency = 1   # the hub runs one experiment at a time; serial delivery avoids 409 retry storms
max_retries = 10
dead_letter_queue = "quant-backtest-dlq"

Wrangler version:

 ⛅️ wrangler 4.146.0 (update available 4.162.0)
───────────────────────────────────────────────

Cloudflare account authentication:

 ⛅️ wrangler 4.146.0 (update available 4.162.0)
───────────────────────────────────────────────
Getting User settings...
👋 You are logged in with an Account API Token, associated with the account Joe.metz.psu@gmail.com's Account.
ℹ️  The API Token is read from the CLOUDFLARE_API_TOKEN environment variable.
┌──────────────────────────────────┬──────────────────────────────────┐
│ Account Name                     │ Account ID                       │
├──────────────────────────────────┼──────────────────────────────────┤
│ Joe.metz.psu@gmail.com's Account │ 21fb1c8806d878917a486f564b8df305 │
└──────────────────────────────────┴──────────────────────────────────┘
🔓 To see token permissions visit https://dash.cloudflare.com/21fb1c8806d878917a486f564b8df305/api-tokens

Cloudflare Worker secret listing:
[
  {
    "name": "CF_ACCESS_CLIENT_ID",
    "type": "secret_text"
  },
  {
    "name": "CF_ACCESS_CLIENT_SECRET",
    "type": "secret_text"
  },
  {
    "name": "GITHUB_WEBHOOK_SECRET",
    "type": "secret_text"
  },
  {
    "name": "MOBILE_COMMAND_SECRET",
    "type": "secret_text"
  }
]


========== 9. GITHUB REPOSITORY AND RELEASE CONFIGURATION ==========
{
  "default_branch": "main",
  "private": true,
  "repository": "jmpsu/henry_hub_atomic_agents",
  "url": "https://github.com/jmpsu/henry_hub_atomic_agents"
}

GitHub environments:
{
  "total_count": 0,
  "environments": []
}

GitHub Actions repository secrets:
no secrets found

GitHub Actions repository variables:
no variables found

Existing self-hosted runners:
{
  "total_count": 0,
  "runners": []
}

Recent workflow runs:


========== 10. CLOUDFLARE AND LINUX NETWORK HEALTH ==========
--- http://127.0.0.1:8090/openapi.json ---
HTTP 200
--- http://127.0.0.1:8095/api/health ---
HTTP 200
--- http://127.0.0.1:8095/openapi.json ---
HTTP 404


========== 11. EXISTING TEST CONFIGURATION ==========
tests/__pycache__/__init__.cpython-312.pyc
tests/__pycache__/_scratch.cpython-312.pyc
tests/__pycache__/test_agents.cpython-312-pytest-7.4.4.pyc
tests/__pycache__/test_agents.cpython-312-pytest-9.2.0.pyc
tests/__pycache__/test_alerts.cpython-312-pytest-7.4.4.pyc
tests/__pycache__/test_alerts.cpython-312-pytest-9.2.0.pyc
tests/__pycache__/test_alerts.cpython-312.pyc
tests/__pycache__/test_backtest.cpython-312-pytest-7.4.4.pyc
tests/__pycache__/test_backtest.cpython-312-pytest-9.2.0.pyc
tests/__pycache__/test_backtest.cpython-312.pyc
tests/__pycache__/test_cpc_collector.cpython-312-pytest-7.4.4.pyc
tests/__pycache__/test_cpc_collector.cpython-312-pytest-9.2.0.pyc
tests/__pycache__/test_cpc_collector.cpython-312.pyc
tests/__pycache__/test_cpc_history.cpython-312-pytest-7.4.4.pyc
tests/__pycache__/test_cpc_history.cpython-312-pytest-9.2.0.pyc
tests/__pycache__/test_cpc_history.cpython-312.pyc
tests/__pycache__/test_ecmwf_hdd.cpython-312-pytest-7.4.4.pyc
tests/__pycache__/test_ecmwf_hdd.cpython-312-pytest-9.2.0.pyc
tests/__pycache__/test_ecmwf_hdd.cpython-312.pyc
tests/__pycache__/test_edge_ingest.cpython-312-pytest-7.4.4.pyc
tests/__pycache__/test_edge_ingest.cpython-312-pytest-9.2.0.pyc
tests/__pycache__/test_eia930_power_burn.cpython-312-pytest-7.4.4.pyc
tests/__pycache__/test_eia930_power_burn.cpython-312-pytest-9.2.0.pyc
tests/__pycache__/test_eia_coal_rail.cpython-312-pytest-7.4.4.pyc
tests/__pycache__/test_eia_coal_rail.cpython-312-pytest-9.2.0.pyc
tests/__pycache__/test_eia_coal_spot.cpython-312-pytest-7.4.4.pyc
tests/__pycache__/test_eia_coal_spot.cpython-312-pytest-9.2.0.pyc
tests/__pycache__/test_eia_ng_monthly.cpython-312-pytest-7.4.4.pyc
tests/__pycache__/test_eia_ng_monthly.cpython-312-pytest-9.2.0.pyc
tests/__pycache__/test_eia_ng_monthly.cpython-312.pyc
tests/__pycache__/test_eia_petroleum_spot.cpython-312-pytest-7.4.4.pyc
tests/__pycache__/test_eia_petroleum_spot.cpython-312-pytest-9.2.0.pyc
tests/__pycache__/test_eia_petroleum_spot.cpython-312.pyc
tests/__pycache__/test_eia_prices.cpython-312-pytest-7.4.4.pyc
tests/__pycache__/test_eia_prices.cpython-312-pytest-9.2.0.pyc
tests/__pycache__/test_eia_prices.cpython-312.pyc
tests/__pycache__/test_eia_storage.cpython-312-pytest-7.4.4.pyc
tests/__pycache__/test_eia_storage.cpython-312-pytest-9.2.0.pyc
tests/__pycache__/test_eia_storage.cpython-312.pyc
tests/__pycache__/test_export_snapshot.cpython-312-pytest-7.4.4.pyc
tests/__pycache__/test_export_snapshot.cpython-312-pytest-9.2.0.pyc
tests/__pycache__/test_gatekeeper.cpython-312-pytest-7.4.4.pyc
tests/__pycache__/test_gatekeeper.cpython-312-pytest-9.2.0.pyc
tests/__pycache__/test_gatekeeper.cpython-312.pyc
tests/__pycache__/test_gfs_hdd.cpython-312-pytest-7.4.4.pyc
tests/__pycache__/test_gfs_hdd.cpython-312-pytest-9.2.0.pyc
tests/__pycache__/test_gfs_hdd.cpython-312.pyc
tests/__pycache__/test_ingest.cpython-312-pytest-7.4.4.pyc
tests/__pycache__/test_ingest.cpython-312-pytest-9.2.0.pyc
tests/__pycache__/test_ingest.cpython-312.pyc
tests/__pycache__/test_kb_chunking.cpython-312-pytest-9.2.0.pyc
tests/__pycache__/test_km_notices.cpython-312-pytest-7.4.4.pyc
tests/__pycache__/test_km_notices.cpython-312-pytest-9.2.0.pyc
tests/__pycache__/test_knowledge_explorer.cpython-312-pytest-9.2.0.pyc
tests/__pycache__/test_markets_engine.cpython-312-pytest-7.4.4.pyc
tests/__pycache__/test_markets_engine.cpython-312-pytest-9.2.0.pyc
tests/__pycache__/test_markets_engine.cpython-312.pyc
tests/__pycache__/test_ngl_term.cpython-312-pytest-7.4.4.pyc
tests/__pycache__/test_ngl_term.cpython-312-pytest-9.2.0.pyc
tests/__pycache__/test_ngl_term.cpython-312.pyc
tests/__pycache__/test_noaa_discussion.cpython-312-pytest-7.4.4.pyc
tests/__pycache__/test_noaa_discussion.cpython-312-pytest-9.2.0.pyc
tests/__pycache__/test_ollama_live.cpython-312-pytest-9.2.0.pyc
tests/__pycache__/test_rggi.cpython-312-pytest-7.4.4.pyc
tests/__pycache__/test_rggi.cpython-312-pytest-9.2.0.pyc
tests/__pycache__/test_rggi.cpython-312.pyc
tests/__pycache__/test_scenario.cpython-312-pytest-7.4.4.pyc
tests/__pycache__/test_scenario.cpython-312-pytest-9.2.0.pyc
tests/__pycache__/test_scenario.cpython-312.pyc
tests/__pycache__/test_selfheal.cpython-312-pytest-7.4.4.pyc
tests/__pycache__/test_selfheal.cpython-312-pytest-9.2.0.pyc
tests/__pycache__/test_selfheal.cpython-312.pyc
tests/__pycache__/test_selfheal_pipeline.cpython-312-pytest-7.4.4.pyc
tests/__pycache__/test_selfheal_pipeline.cpython-312-pytest-9.2.0.pyc
tests/__pycache__/test_steo_production.cpython-312-pytest-7.4.4.pyc
tests/__pycache__/test_steo_production.cpython-312-pytest-9.2.0.pyc
tests/__pycache__/test_steo_production.cpython-312.pyc
tests/_scratch.py
tests/e2e_worker.sh
tests/fake_gh.sh
tests/fixtures/cpc_fxus06_sample.html
tests/fixtures/eia930_balance_sample.csv
tests/fixtures/eia_coal_archive_sample.json
tests/fixtures/eia_coal_transport_table1.xlsx
tests/fixtures/km_eec_notices_sample.html
tests/seed_demo.py
tests/test_agents.py
tests/test_alerts.py
tests/test_backtest.py
tests/test_cpc_collector.py
tests/test_cpc_history.py
tests/test_ecmwf_hdd.py
tests/test_edge_ingest.py
tests/test_eia930_power_burn.py
tests/test_eia_coal_rail.py
tests/test_eia_coal_spot.py
tests/test_eia_ng_monthly.py
tests/test_eia_petroleum_spot.py
tests/test_eia_prices.py
tests/test_eia_storage.py
tests/test_export_snapshot.py
tests/test_gatekeeper.py
tests/test_gfs_hdd.py
tests/test_ingest.py
tests/test_kb_chunking.py
tests/test_km_notices.py
tests/test_knowledge_explorer.py
tests/test_markets_engine.py
tests/test_ngl_term.py
tests/test_noaa_discussion.py
tests/test_ollama_live.py
tests/test_rggi.py
tests/test_scenario.py
tests/test_selfheal.py
tests/test_selfheal_pipeline.py
tests/test_steo_production.py
tests/test_selfheal_pipeline.py:11:    def test_registry_and_fixtures_consistent(self):
tests/test_ngl_term.py:66:            with self.assertRaises(ValueError): nt.fetch_state(f"http://127.0.0.1:{srv.server_port}/api/state.json", None, "seasonal")
tests/_scratch.py:49:atexit.register(_cleanup)
tests/test_agents.py:2:LLM object over a mocked HTTP transport; tests/test_ollama_live.py exercises the real local model."""
tests/e2e_worker.sh:3:# NOTE: a successful /execute call creates one private GitHub gist and one vector node.
tests/e2e_worker.sh:18:for k in ("analysis", "db_rows", "audit_gist_url", "new_vector_node_id"): assert k in d, k
tests/fake_gh.sh:2:echo "https://gist.github.com/fake/$$"


========== 12. EXISTING RELEASE DOCUMENTATION ==========
--- docs/ARCHITECTURE.md ---
# Architecture and implementation status

This is the Section 11 audit and plan for `artifacts/Ultimate_Goal.md`. The authoritative, executable status of every one of
the 422 atomic requirements is `requirements/STATUS.md`, produced by `scripts/acceptance.py` from
`requirements/registry.json`. This document explains the system the checks verify.

## Live topology (joey-dell + Cloudflare only)

```
mobile / API client
   │  Authorization: Bearer MOBILE_COMMAND_SECRET
   ▼
Cloudflare Worker  quant-gateway  (worker.js, wrangler.toml)
   │  ├─ fetch():     /            -> forwards to quant.joeysvault.app/execute
   │  │               /backtest, /enqueue -> Cloudflare Queue quant-backtest-jobs
   │  │               /edge/<key>  -> fetch one whitelisted source at the edge
   │  ├─ queue():     quant-backtest-jobs -> /experiments/run   (max_concurrency 1, DLQ quant-backtest-dlq)
   │  └─ scheduled(): crons 30 13 * * *, 45 15 * * THU -> edge fetches -> /ingest/edge, then /ingest
   │  CF-Access-Client-Id / -Secret (service token)
   ▼
Cloudflare Access ─► Cloudflare Tunnel dell-secret-tunnel ─► 127.0.0.1:8090  quant_hub.service (command_hub.py)
                                                         └─► 127.0.0.1:8095  markets_hub (markets_hub.py, read-only, public)
                                                              markets.joeysvault.app, ngl.joeysvault.app
local: Ollama 127.0.0.1:11434 (qwen3:4b, nomic-embed-text) · SQLite henry_hub_pit.db · ChromaDB chroma_pit_kb · raw/<sha256>
timers: hh-collect-cpc.timer (user) daily 09:30 local -> collectors/run_all.py, then scripts/export_snapshot.py,
        then (ExecStopPost, also after a failed collector) scripts/run_agents.py -> hub /kb/ingest + /agents/run
```

Privileged routes (`/execute`, `/ingest`, `/ingest/edge`, `/kb/ingest`, `/experiments/run`, `/agents/run`) exist only on :8090 behind
Access. The public service on :8095 opens the database read-only and has no write, LLM-generation, agent or ingestion route; it serves the
dashboard (`/`), the knowledge explorer (`/knowledge`) and read-only JSON (`/api/state.json`, `/api/knowledge-graph`,
`/api/knowledge-node/{id}`, `/api/knowledge-search`, `/api/agents/activity`).

## Data contract (Sections 3.3, 3.4, 9)

`pit_market_data` holds one row per vintage: the four canonical fields plus `source_id, source_url, retrieved_timestamp,
published_timestamp, revision_timestamp, unit, geographic_scope, series_id, raw_payload_hash, extraction_version,
quality_status, provenance`. Rows are only ever inserted; a changed value is a new vintage available at retrieval time.
`ingest.pit_snapshot` and `markets_engine.load_series` return the latest vintage with `available_timestamp <= cutoff`.
Every source payload is archived as `raw/<sha256>` and indexed in `raw_payloads`. `documents` holds unstructured source
text (pipeline notices, forecast discussions) with the source's publication time. Provenance values: `measured`,
`extracted_estimate`, `synthetic_scenario`, `model_hypothesis`, `source_document`, `backtest_result`, and
`unverified_seed` for four legacy demo rows that every calculation excludes.

## Architecture 1 — edge-to-core collection (Section 3)

| Item | State |
|---|---|
| Collectors (local) | `collectors/`: CPC degree days + history/normals, EIA storage, EIA HH spot + futures 1-4 (to 2024-04), EIA WTI + Mont Belvieu propane, EIA NG monthly demand, EIA-930 US48 gas-fired generation (power burn), EIA STEO basin production, GFS and ECMWF HDD (days 1-15 / 1-9), RGGI CO2, EIA weekly coal spot (CAPP, PRB), EIA coal rail transportation rate, Kinder Morgan critical notices (7 pipelines), NOAA CPC 6-10/8-14 discussions |
| Edge collection | Worker fetches 7 whitelisted sources from Cloudflare's network; hub `/ingest/edge` checks key+URL against its own whitelist, records status/headers/hash/time in `edge_fetches`, archives and parses with the owning collector |
| Validation | `ingestion/validation/gatekeeper.py` range/unit gate; every collector checks layout and raises on change; PIT availability rules are documented per collector |
| Coverage | 50 of 81 roster agents have real data. Missing: NGI cash (4) and CME M5-M12 (8) - paid feeds; border/Mexico flows (5) and LNG feedgas (8) - pipeline EBB logins or postback-only pages; ECMWF day 10-15 (6) - not in the deterministic open feed. |
| Schedules | Worker crons + user timer; source fetched once per run, one retry on 5xx |

## Architecture 2 — self-healing scrapers (Section 4)

`selfheal.py`: structured diagnosis, LLM (qwen3:4b via `ollama_llm`) selector proposal with a constrained, grounded retry
and a deterministic fallback, fixture validation. `selfheal_pipeline.py`: selector agents registered in
`ingestion/selectors.json` (selector lists; a repair is prepended so old layouts keep working) -> diagnose -> propose ->
validate on preserved fixtures and the failing page's value range -> isolated worktree branch `selfheal/<collector>/...` ->
full test suite -> push -> `gh pr create` (never merges; verified with PR #2). Recovery: GitHub webhook (HMAC verified by
the Worker) -> hub `/selfheal/rerun` -> fetch, verify the merge commit is on the base branch, rerun the collector from a
detached worktree of exactly that commit, record `selfheal_runs`, report on the `[selfheal]` issue stream.

## Architecture 3 — vector knowledge engine (Section 5)

`kb_ingest.py` builds knowledge objects from measured rows (weekly storage, weekly weather vs normal, monthly basin
production, monthly prices with WTI ratio, RGGI auctions), source documents (pipeline notices, CPC discussions),
experiments and `/execute` theses; embeds with nomic-embed-text; stores `kb_nodes`/`kb_edges` in SQLite and the Chroma
collection. Edge types: `previous_in_series`, `same_period` (co-occurrence, not causation), `builds_on`,
`semantic_neighbor` (similarity, not causation), `part_of` (chunk -> source document), and the agent edges `evidence_for` and
`evaluated_by`. Source documents longer than 2,700 characters are also chunked (`chunk_text`: paragraph boundaries, 1,800 characters,
overlap on hard splits) so their whole text is embedded; chunks carry the parent's PIT metadata. Search is PIT-filtered. Hypothesis memos (`alerts.py`) require every
field of 5.4 and an out-of-sample, cost-inclusive backtest. Not yet sourced: FERC (blocks automated fetches), LNG terminal
notices, NGL fractionation, cracker/refinery outages, Mont Belvieu purity products other than propane.

## Research agents and the local Ollama layer (`agents/`, CLAUDE.md capabilities 1-3)

`agents/llm.py` is the only path from agents to a model. Configuration is explicit and environment-overridable:
`HH_OLLAMA_URL` (default `http://127.0.0.1:11434`), `HH_REASONING_MODEL` (`qwen3:4b`), `HH_EMBED_MODEL` (`nomic-embed-text`), per-task token
budgets and timeouts (`HH_SYNTH_TIMEOUT` 240 s, `HH_EXTRACT_TIMEOUT` 90 s, `HH_EMBED_TIMEOUT` 30 s, ...), `HH_LLM_RETRIES` (1, for
connection errors and HTTP 5xx; timeouts are not retried). `status()` reports ok only when every configured model is installed - a
responding daemon is not enough; when it fails every agent runs on its deterministic fallback. Generations are JSON-schema constrained
(free-text fields carry `maxLength`), `think=false`, temperature 0; truncated output (`done_reason=length`) is an error. Every call -
including each fallback - is logged in `llm_calls` (agent, task, model, prompt version, prompt sha256, latency, ok, error, fallback).
`numbers_grounded()` rejects model text containing numbers that were not in the evidence (sign and rounding tolerant).

`agents/memory.py` is the shared memory and bus: PIT semantic retrieval over the knowledge library (keyword fallback when embeddings are
down), findings persisted as `agent_finding` knowledge objects (content-hash ids, `evidence_for` edges to what they cited, never available
before their evidence, mirrored into Chroma by the hub), verdicts in `finding_status` (valid / rejected / superseded / evaluated; the finding
text is never rewritten), and the `agent_messages` bus (each consumer reads a message once).

`agents/workers.py` runs six agents in order, one failure never stopping the others:

| Agent | Deterministic part | Model part (fallback) | Publishes |
|---|---|---|---|
| diagnostics | latest failed `collector_runs` | qwen3:4b classifies the error (regex rules) | `incident` |
| data_quality | stale series vs. their own cadence, revisions >= 10% of typical magnitude, duplicate vintages (all PIT) | qwen3:4b explains the cause, restricted to causes valid for the issue type (rules) | `data_quality`, owner event stream |
| repair | consumes `incident`; parser problems only | selector agents: `selfheal_pipeline.repair(dry_run=True)` on a captured page inside the project; parser collectors: structured change suggestion (manual-fix note). Never edits code, never opens or merges a PR | `repair_proposal` |
| notice_analyst | the notice's own `Type:` label sets the event type; high severity needs outage/curtailment/force-majeure wording; location must appear in the notice | qwen3:4b severity/location/summary (keyword rules) | `pipeline_event` (high severity / force majeure) |
| anomaly | z-scores on PIT series | qwen3:4b interpretation with cited ids (fact only) | `anomaly` |
| synthesis | PIT observations (with plain-language readings), retrieval excluding rejected findings, catalogue of 8 measurable cross-domain relationships with the direction the observations imply | qwen3:4b picks one relationship, direction, horizon, rationale, contradictory evidence, confidence (fails closed) | `finding` |

Synthesis checks: cited knowledge ids and observation keys are schema enums of what was shown; at least one cited object must be source
or data-derived (not only earlier hypotheses); direction must match the observations; numbers grounded; confidence capped by evidence and
testability; one bounded retry with the validator's findings, then rejection. When the chosen relationship has no quantitative model, the
best-supported testable one is also proposed. A valid testable hypothesis is evaluated with the latest cost-inclusive walk-forward
experiment recorded at or before the cutoff (run on demand only for a current cutoff); the evaluation is linked (`evaluated_by`) and a
complete Section 5.4 memo (`alerts.validate_hypothesis`) is persisted as a knowledge object. Earlier hypotheses and data-quality findings are
re-checked against the current rules on every run.

Triggers: `POST /agents/run` (hub, Access-protected, single-flight), the hub's `/ingest` (starts a background run after collection), and the
daily timer's `scripts/run_agents.py`. `GET /agents/activity` (hub) and `/api/agents/activity` (public, read-only) show runs, bus traffic,
model-call statistics and verdicts. CLI: `DB_PATH=... .venv/bin/python -m agents.workers [--as-of ISO] [--only synthesis]` (no Chroma mirror).

## Graphical knowledge explorer (`/knowledge`, CLAUDE.md capability 2, Section 12.3)

`web/knowledge.html` + `web/knowledge.js` (vendored D3, no CDN): zoomable/draggable force graph of the library at a point-in-time cutoff
(slider over the last two years or an exact UTC timestamp), domain and edge-type filters, shapes per object kind, gold for valid/evaluated
agent findings and their evidence links, PIT semantic search, and an inspector showing provenance, availability/publication timestamps,
the finding verdict, the archived source payload's metadata (URL, HTTP status, retrieval time, size - never local paths), the agent
extraction for pipeline notices, and every linked object. The page also shows recent agent runs, bus messages and Ollama call statistics.

## Architecture 4 — walk-forward backtesting (Section 6)

`backtest.py` (PIT walk-forward, look-ahead assertions, chronological train/validation/holdout, costs, slippage,
drawdown, per-decision Sharpe, heating/non-heating regime split, cross-domain feature builders that read each feature as
known at every origin), `experiments.py` (models: persistence, AR(1), mean-20, HDD anomaly, propane/WTI reversion and
momentum, HH vs shale-production momentum; per-target persistence baselines; Bonferroni divisor over every experiment
ever recorded; promotion only with lower holdout RMSE, significant direction and positive net return), `LEADERBOARD.md`
rebuilt from the `experiments` table. Dispatch: Worker → Queue → hub `/experiments/run` (local compute, single flight).
No model has met the promotion bar.

## Architecture 5 — zero-trust command and alerting (Section 7)

Worker: constant-time bearer check, 4 KiB body limit, Access headers injected, bearer dropped, upstream status preserved.
Hub `/execute`: `as_of` normalised to UTC, PIT SQL context filtered by query-implied agents, PIT vector retrieval, qwen3:4b
with strict JSON schema, `/no_think`, `num_predict` 180; model SQL runs in a sandbox (temp view with the cutoff, SQLite
authorizer, row cap, step limit) with deterministic fallback; scenario delta computed deterministically; a thesis that
contradicts the delta's sign is withheld; private audit gist piped to `gh` on stdin; new vector node linked to its
parents. Response carries all ten fields of 7.4 plus provenance labels. Owner alerts: `notify.py` opens one GitHub issue per incident (collector failure), closes it on recovery, and posts
routine events (backtests, validated hypotheses, self-heal reruns) to rolling issue streams.

## Section 12 — visual platform

`markets_engine.py` builds `/api/state.json` (schema `ngl-state/1`); `markets_hub.py` serves it, the web UI (`web/`:
D3 charts, MapLibre + deck.gl map, knowledge graph; all libraries vendored) and the PIT knowledge search. `ngl-term.py`
renders the same document in the terminal with a Braille map. Products without a collector are returned as
`pending_collector` with no value; nothing is simulated. Public hostnames have DNS records; the ingress rule needs
`sudo bash deploy/add_markets_ingress.sh`, after which `/home/joey/joeysvault-site` (commit `ab20fc0`) is deployed.

## Section 3.5 — GitHub data audit

`scripts/export_snapshot.py` writes a deterministic `snapshots/<date>/` (manifest with per-agent row digests, raw-payload
manifest, ingestion metadata, experiments, leaderboard copy); the daily timer runs it after collection. Branch protection
on `main` is not available on this repository's GitHub plan.

## Verification

- `scripts/requirements_registry.py` — registry of 422 requirements, byte-identical on re-run.
- `scripts/acceptance.py [--with-side-effects]` — runs every check, writes `requirements/status.json` and `STATUS.md`,
  and classifies every blocked check (`external_data`, `owner_action`, `platform_limit`; anything unexplained is reported
  as `unfinished_implementation`).
- `.venv/bin/python -m pytest -q` — unit suite, including `tests/test_ollama_live.py`, which calls the real local Ollama models and FAILS
  (does not skip) when a configured model is missing.
- `tests/e2e_worker.sh` — gateway end to end (creates one private gist).

Verified end to end on 2026-11-14: self-heal PR #2 opened by the pipeline, tested on the merged result and merged; the
real GitHub `pull_request closed` delivery was verified by the Worker and the hub reran `selfheal_demo` from merge commit
`f962948` (recorded in `selfheal_runs`). Research memo issue #5 documents a rejected hypothesis with its out-of-sample
evidence. Incident #3 was opened and closed by `notify.py`; backtest events stream to issue #4.

## Operations notes

- Deploying code changes: `sudo systemctl restart quant_hub.service` (hub, :8090) and `systemctl --user restart markets_hub.service`
  (public read-only, :8095); `systemctl --user daemon-reload` after editing the timer unit (a copy is kept in `deploy/hh-collect-cpc.service`).
- Run the agents now: `curl -X POST localhost:8090/agents/run` (loopback) or `.venv/bin/python scripts/run_agents.py` (knowledge refresh +
  agents, exit 1 if any agent failed).

- Public routes: DNS records for markets/ngl.joeysvault.app exist; the ingress rule is added by
  `sudo bash deploy/add_markets_ingress.sh` (validates, keeps a backup, restores on failure).
- Disk: Timeshift's config included `/home/joey` in system snapshots (`+ /home/joey/**`), filling the disk.
  `sudo bash deploy/timeshift_exclude_home.sh` removes only the two include rules (backup kept, no snapshots deleted).
- Large payloads (> 5 MB) are archived gzip-compressed; `ingest.read_payload()` returns the original bytes.
- External rate limits are respected: the ECMWF open-data bucket throttles bursts (`SlowDown`); collectors fetch once per run.
--- requirements.txt ---
aiohappyeyeballs==2.7.1
aiohttp==3.14.5
aiohttp-retry==2.9.1
aiosignal==1.4.0
annotated-doc==0.0.6
annotated-types==0.8.0
anyio==4.16.0
attrs==26.1.0
bcrypt==5.0.0
build==1.6.1
certifi==2026.10.23
charset-normalizer==3.5.2
chromadb==1.5.9
click==8.5.1
durationpy==0.11
fastapi==0.162.4
filelock==4.2.10
flatbuffers==25.12.19
frozenlist==1.8.0
fsspec==2026.9.0
googleapis-common-protos==1.76.0
grpcio==1.85.1
h11==0.16.0
hf-xet==1.8.0
httpcore==1.0.9
httpcore2==2.16.0
httptools==0.9.0
httpx==0.28.1
httpx2==2.16.0
huggingface_hub==2.4.0
idna==3.20
importlib_resources==7.1.0
jsonschema==4.26.0
jsonschema-specifications==2025.9.1
kubernetes==37.0.2
markdown-it-py==4.3.0
mdurl==0.1.2
mmh3==5.3.1
multidict==7.2.1
numpy==2.5.4
oauthlib==4.0.1
onnxruntime==1.31.1
opentelemetry-api==1.45.2
opentelemetry-exporter-otlp-common==0.66b2
opentelemetry-exporter-otlp-proto-common==1.45.2
opentelemetry-exporter-otlp-proto-grpc==1.45.2
opentelemetry-proto==1.45.2
opentelemetry-sdk==1.45.2
opentelemetry-semantic-conventions==0.66b2
orjson==3.13.0
overrides==7.7.0
packaging==26.3
propcache==0.5.4
protobuf==7.36.2
pybase64==1.5.2
pydantic==2.14.3
pydantic-settings==2.16.2
pydantic_core==2.50.4
Pygments==2.21.0
PyPika==0.51.1
pyproject_hooks==1.3.3
python-dateutil==4.0.0
python-dotenv==1.2.4
PyYAML==6.0.3
referencing==0.37.0
requests==2.34.2
requests-oauthlib==2.0.0
rich==15.0.0
rpds-py==2026.9.1
shellingham==1.5.4
starlette==1.10.0
tenacity==9.2.1
tokenizers==0.23.3
tqdm==4.70.1
truststore==0.10.5
typer==0.29.1
typing-inspection==0.4.5
typing_extensions==4.16.0
tzdata==2026.6
urllib3==2.8.0
uvicorn==0.54.0
uvloop==0.23.0
watchfiles==1.3.0
websocket-client==1.9.2
websockets==17.4
xlrd==2.0.2
yarl==1.25.1
--- .gitignore ---
.env
.venv/
audit/
artifacts/mcp_credentials.json
henry_hub_pit.db
chroma_pit_kb/
__pycache__/
*.pyc
.wrangler/
backups/
raw/
node_modules/

# Runtime data & secrets (added during consolidation)
*.db
*.db-journal
*.db-wal
.pytest_cache/

# Project-local runtime scratch (never committed)
runtime/

# Local assistant/office state (never committed)
.claude/
.~lock.*#


========== COLLECTION COMPLETE ==========
No files edited, no services restarted, no deployment performed.
