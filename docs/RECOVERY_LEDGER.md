# Henry Hub Recovery Ledger

## Objective

Repair and expand the existing Henry Hub application in place. The current repository is the only product; no replacement architecture is authorized.

## Preserved inputs

- Branch `quant-hub-build`, initial HEAD `3d640f47811f34263a61d1d54eb2dfae13f7aebf`.
- Pre-existing uncommitted `requirements/STATUS.md` and `requirements/status.json` changes; acceptance later regenerated both. Originals are in `/tmp/opencode/user-changes-backup/` and pre-acceptance copies in `/tmp/opencode/STATUS.md.before-acceptance` and `/tmp/opencode/status.json.before-acceptance`.
- Pre-existing untracked `QUANT_HUB_SPEC.md`, `.venv/`, `venv/`.
- Backups of the three user files are in `/tmp/opencode/user-changes-backup/`.
- No database, snapshot, artifact, or source file was deleted or reinitialized.

## Historical investigation

- Rich tooltip implementation was introduced on `feat/lng-forward` lineage at `2e2159d` ("feat(ui): rich tooltips on every panel with API-served definitions, formulas and lineage") and expanded through `a2721cb`.
- `3d640f4` never received those commits. The absence is branch divergence, not a later deletion.
- Original functionality: `web/tooltip.js`, `metric_docs.py`, `scripts/verify_tooltips.py`, `tests/test_metric_docs.py`, `state.explain` in `/api/market`, tooltip bindings in `web/app.js` and `web/knowledge.js`, CSS in `web/app.css`, and `?tip=<id>` deep links.
- Map implementation was already present at `3d640f4` (MapLibre, deck.gl, `web/data/na_basemap.json`, `geo` payload in `markets_engine.py`). Branch commits expanded map labels, monthly EIA LNG exports, border flows, and map tooltips.
- Quant-hub files (`agents/retrieval_hub.py`, `agents/quant_commodities.py`, `agents/quant_risk.py`, `tests/test_quant_hub.py`) exist only on `quant-hub-build`; they were preserved.

## Changes applied

- Ported existing implementation from `106d00f`, `c126f31`, `2e2159d`, `376bab2a`, `5989f7a`, `10115d5c`, `82a75beb`, `a4a8d0fd`, `6b4ef034`, `b16571b6`, `132f2d97`, `262eb875`, `a2721cbf` into the working tree with `git cherry-pick -n`, then unstaged with `git restore --staged .`.
- Skipped `f6a7748` to avoid overwriting requirement status files and snapshots.
- Preserved quant-hub modules, dependencies in `requirements.txt`, acceptance checks, and all user files.
- Made `scripts/verify_tooltips.py` portable by honoring `CHROME_PATH`, adding Chromium sandbox flags, clearing stale tooltip state before each hover, and capturing diagnostic hit/target data on failures.
- Added `risk_alert` to `agents/memory.py`, corrected the risk threshold text in `agents/workers.py`, and made `QuantRiskAgent.run()` initialize `memory` on direct runs.
- Added `triage` to `agents/llm.py` CONFIG; `DataQualityAgent` now always uses qwen3 structured triage, links its finding to real KB evidence, and publishes `data_quality_triage`.
- Fixed NOAA CPC discussion parsing for current title-case 6-10/8-14 headings and `3:00 PM EST` issue stamps.
- Installed `libeccodes-dev`, `pygrib==2.1.8` and `poppler-utils`; live GFS/ECMWF GRIB collectors and EMI PDF ingestion now work.
- Made literature KB reindexing PIT-safe: partial-unique active SHA constraint, data-preserving legacy migration, and content-addressed IDs that allow superseded documents to be re-ingested.
- Added `deploy/hh-collect-cpc.timer` and made schedule/snapshot acceptance checks verify repository deployment units when `systemctl` is unavailable in the runner.
- Corrected acceptance checks for documented `bootstrapped_physical_proxy` provenance, the expanded 94-agent roster, and external-credential/deployment blockers (`alert_delivery`, `audit_gists`, `selfheal_pr_live`, `webhook_recovery`, `queue_dispatch`, `edge_collection`).
- Updated browser acceptance to discover Chromium through `CHROME_PATH` and use CDP with SwiftShader so WebGL map nodes are exercised.
- Removed the `or True` escape hatch from the tooltip verifier's map-label check and the vacuous chat-log assertion; added `tests/test_verification_integrity.py` to prevent their return.
- Replaced `--disable-gpu` with SwiftShader in `scripts/verify_tooltips.py`, then added executable checks for a real MapLibre WebGL canvas, 18 markers, no unavailable fallback, and monthly LNG export labels.
- Added acceptance check `rich_tooltips_browser` with real hover, click-to-pin, keyboard-focus, deep-link and console-exception evidence; strengthened `web_ui_browser` with canvas/WebGL/marker assertions.
- Established document focus before programmatic focus in tooltip evidence so the keyboard-focus check proves a tooltip actually renders.
- Excluded verification scripts from the production `tempfile` path check so the check tests production code rather than browser-test scaffolding.

## Test evidence

- Baseline before restoration: `.venv/bin/python -m pytest -q` -> 187 passed.
- Isolated trial worktree after port: 311 passed, 13 warnings.
- Live working tree after all repairs: `NOTIFY=0 .venv/bin/python -m pytest -q` -> 318 passed, 13 warnings, 2 subtests passed.
- Browser tooltip verifier: `CHROME_PATH=... scripts/verify_tooltips.py http://127.0.0.1:8096 --port 9454` -> 74 passed, 0 failed.
- Full acceptance with network/Chromium: `CHROME_PATH=... NOTIFY=0 .venv/bin/python scripts/acceptance.py` -> 427 requirements, 268 passed, 0 failed, 159 blocked, 0 unverified; directive 22/22 passed.
- Live agents: `scripts/run_agents.py` -> all 7 agents true, 19 findings; cross-agent evidence links, qwen3 calls and evaluation memos verified.
- Literature ingestion: 14 new / 8 unchanged / 3 known-elsewhere, 4,167 chunks, 4,165 semantic edges, 37 docs, 100% coverage.
- Graph KB: 207 nodes, 213 browser-rendered nodes, 242 edges, 20 agent findings; Chroma vector retrieval verified.
- Warnings only: pytest-asyncio fixture loop scope unset; LlamaIndex `KnowledgeGraphIndex`/`KnowledgeGraphRAGRetriever` deprecations.
- Targeted acceptance after repair: `web_ui_browser` passed with `map={'canvas': True, 'width': 1008, 'height': 640, 'gl': True, 'dw': 1008, 'markers': 18, 'unavailable': False}`; `rich_tooltips_browser` passed with `loaded=True hover=True pin=True keyboard=True deep=True errors=0`.
- Browser tooltip verifier: `CHROME_PATH=... scripts/verify_tooltips.py http://127.0.0.1:8095 --port 9471` -> 77 passed, 0 failed, including four MapLibre canvas/marker checks and real tooltip render, pin, keyboard and deep-link checks.
- Full pytest after repair: `NOTIFY=0 .venv/bin/python -m pytest -q` -> 320 passed, 13 warnings, 2 subtests passed.
- Static checks: Python compile pass over all tracked/untracked non-virtualenv sources passed; CI `py_compile` passed; `node --input-type=module --check < worker.js` passed; CI secret scan passed. No repository lint/type-check configuration exists; `bandit` is not installed in the runner.
- Full acceptance immediately before publication: 427 requirements, 268 passed, 2 failed, 157 blocked, 0 unverified; directive 22/22 passed. The only failed check was `branch_pushed` (`ahead 1`), expected while the repair commit was still local; the two failed requirements inherit that check.

## Remaining work

- Commit and push the repaired checks and ledger to `origin/quant-hub-build`, then verify local and remote commit hashes.
