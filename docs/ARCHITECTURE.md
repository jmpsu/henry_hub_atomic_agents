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
