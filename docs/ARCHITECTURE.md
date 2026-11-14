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
timers: hh-collect-cpc.timer (user) daily 09:30 local -> collectors/run_all.py, then scripts/export_snapshot.py
```

Privileged routes (`/execute`, `/ingest`, `/ingest/edge`, `/kb/ingest`, `/experiments/run`) exist only on :8090 behind Access.
The public service on :8095 opens the database read-only and has no write, LLM-generation or ingestion route.

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
`semantic_neighbor` (similarity, not causation). Search is PIT-filtered. Hypothesis memos (`alerts.py`) require every
field of 5.4 and an out-of-sample, cost-inclusive backtest. Not yet sourced: FERC (blocks automated fetches), LNG terminal
notices, NGL fractionation, cracker/refinery outages, Mont Belvieu purity products other than propane.

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
- `.venv/bin/python -m pytest -q` — unit suite.
- `tests/e2e_worker.sh` — gateway end to end (creates one private gist).

Verified end to end on 2026-11-14: self-heal PR #2 opened by the pipeline, tested on the merged result and merged; the
real GitHub `pull_request closed` delivery was verified by the Worker and the hub reran `selfheal_demo` from merge commit
`f962948` (recorded in `selfheal_runs`). Research memo issue #5 documents a rejected hypothesis with its out-of-sample
evidence. Incident #3 was opened and closed by `notify.py`; backtest events stream to issue #4.

## Operations notes

- Public routes: DNS records for markets/ngl.joeysvault.app exist; the ingress rule is added by
  `sudo bash deploy/add_markets_ingress.sh` (validates, keeps a backup, restores on failure).
- Disk: Timeshift's config included `/home/joey` in system snapshots (`+ /home/joey/**`), filling the disk.
  `sudo bash deploy/timeshift_exclude_home.sh` removes only the two include rules (backup kept, no snapshots deleted).
- Large payloads (> 5 MB) are archived gzip-compressed; `ingest.read_payload()` returns the original bytes.
- External rate limits are respected: the ECMWF open-data bucket throttles bursts (`SlowDown`); collectors fetch once per run.
