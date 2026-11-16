# Requirement status (2026-11-15T20:16:17Z)

Source: `artifacts/Ultimate_Goal.md` (sha256 `8eb56ffd613480c1`) · 422 atomic requirements

| Status | Count |
|---|---|
| passed | 299 |
| failed | 50 |
| blocked | 73 |
| unverified | 0 |

## Checks

| Check | Status | Evidence | Blocked by |
|---|---|---|---|
| `access_protects_hub` | passed | /execute 403, /ingest 403 |  |
| `agent_unit` | passed | 31 passed in 2.39s |  |
| `agents_live_run` | passed | ok runs ['diagnostics', 'data_quality', 'repair', 'notice_analyst', 'anomaly', 'synthesis']; qwen3 ok calls {'notice_analyst': 209, 'data_quality': 4, 'synthesis': 24}; embedding o |  |
| `agents_scheduled` | passed | timer enabled; ExecStopPost run_agents.py=True; /ingest trigger=True |  |
| `agents_share_knowledge` | passed | 25 cross-agent message reads {'anomaly': 1, 'data_quality': 1, 'incident': 1, 'pipeline_event': 1}; 40 findings, 29 linked to source/data evidence, 32 finding->finding links (later |  |
| `alert_delivery` | passed | incident issues [(3, 'CLOSED')]; event streams ['[data-quality] data-quality ev', '[backtests] backtests event st', '[selfheal] selfheal event stre'] |  |
| `architecture_doc` | passed | sections present=['Architecture 1', 'Architecture 2', 'Architecture 3', 'Architecture 4', 'Architecture 5']; tracked=True |  |
| `audit_gists` | passed | 5 recent hub gists |  |
| `backtest_unit` | passed | 11 passed in 0.45s |  |
| `branch_protection` | blocked | {"message":"Branch not protected","documentation_url":"https://docs.github.com/rest/branches/branch-protection#get-branc | platform_limit: GitHub requires Pro or a public repository for branch protection on this private repo |
| `branch_pushed` | passed | ## quant-hub-build...origin/quant-hub-build |  |
| `collector_freshness` | passed | all daily series fresh (<=5 days) |  |
| `collector_schedule` | passed | timer enabled; worker crons ['crons = ["30 13 * * *", "45 15 * * THU"]  # daily 13:30 UTC (CPC); Thursdays 15:45 UTC (EIA storage, released 15:30Z). Day NAME used: Cloudflare numbe |  |
| `collectors_run` | passed (carried over) | OK   cpc_heating {'agent': 'Agent_Weather_Actual_HDD', 'obse / OK   cpc_cooling {'agent': 'Agent_Weather_Actual_CDD', 'obse / OK   eia_storage [{'agent': 'Agent_Storage_East', 'obs |  |
| `cross_domain_sources` | blocked | have ['agent_finding', 'alpha_synthesis', 'backtest', 'carbon', 'noaa_discussion', 'pipeline_notice', 'price', 'production', 'storage', 'weather']; missing ['ferc', 'lng_notice', ' | external_data: FERC blocks automated fetches (403); LNG terminal notices, NGL fractionation, cracker/refinery outages and Mont Belvieu purity products other than propane need paid feeds |
| `db_integrity` | passed | ok |  |
| `edge_collection` | passed | edge sources with successful runs: ['cpc_cooling', 'cpc_heating', 'eia_hh_spot', 'eia_propane', 'eia_storage', 'eia_wti', 'rggi'] |  |
| `edge_ingest_unit` | passed | 3 passed in 0.74s |  |
| `env_locked` | failed | mode 0o600; ignored True; tracked secret files: artifacts/NGL  technical audit latest version output
artifacts/NGL  technical audit latest version output v1
artifacts/NGL  technica |  |
| `execute_sandbox_tests` | passed | 11 passed in 0.21s |  |
| `experiment_endpoint` | passed | HTTP 200 |  |
| `experiments_recorded` | passed | 38 experiments, 0 incomplete |  |
| `full_test_suite` | passed | 175 passed in 26.33s |  |
| `gatekeeper` | passed | 3 passed in 0.11s |  |
| `hub_health` | passed | {"ok":true,"db":"henry_hub_pit.db","vector_nodes":302,"version":"1.0.1","release_version":"1.0.1","release_commit":"aa11 |  |
| `hypothesis_evaluated_live` | passed | finding verdicts {'evaluated': 6, 'rejected': 6, 'superseded': 3, 'valid': 11}; evaluated_by edges 6; memos 5 |  |
| `hypothesis_memo` | passed | 5 passed in 0.01s |  |
| `indicators` | passed | 9 passed in 0.07s |  |
| `kb_chunking` | passed | tests 2 passed in 0.20s; 26 part_of edges in the production library |  |
| `knowledge_explorer` | passed | /knowledge 200; graph 301 nodes, edge types ['builds_on', 'evaluated_by', 'evidence_for', 'part_of', 'previous_in_series', 'same_period', 'semantic_neighbor']; inspector 200 edges= |  |
| `knowledge_explorer_browser` | passed | 306 nodes, 456 edges, 41 agent findings drawn, console errors=0 |  |
| `knowledge_library` | passed | 301 nodes, 10 domains, edges {'builds_on': 74, 'evaluated_by': 6, 'evidence_for': 74, 'part_of': 26, 'previous_in_series': 234, 'same_period': 43, 'semantic_neighbor': 286}, 0 miss |  |
| `knowledge_search_pit` | passed | old cutoff -> 0 results; now -> 8 |  |
| `leaderboard_versioned` | passed | tracked=True; 38/38 experiments listed |  |
| `main_site_link` | blocked | HTTP 200, link present=False | owner_action: deployed by wrangler right after the public routes serve (depends on public_markets) |
| `markets_local` | passed | state 200 ngl-state/1, /execute 404, / 200 |  |
| `multi_feature_experiments` | passed | feature sets: ['hdd_anomaly', 'propane_wti_revert', 'propane_wti_momentum', 'hh_production_momentum'] |  |
| `ngl_term` | passed | exit 0, 794 braille cells |  |
| `no_tmp_or_claude_paths` | passed | none |  |
| `observations_reference_payloads` | passed | 92900/92900 measured rows reference an archived payload |  |
| `ollama_live_integration` | passed | 4 passed in 23.66s |  |
| `ollama_models` | passed | ['nomic-embed-text:latest', 'qwen3:4b'] |  |
| `ollama_only_local` | passed | none |  |
| `pit_tests` | passed | 23 passed in 1.04s |  |
| `promotion_gate` | passed | promotion conditions present in experiments.py |  |
| `provenance_labels` | passed | 0 unlabelled rows |  |
| `public_markets` | passed | markets.joeysvault.app 200, ngl.joeysvault.app 200 |  |
| `queue_dispatch` | failed |  this is a bug, please open an issue at: [4mhttps://github.com/cloudflare/workers-sdk/issues/new/choose[0m


🪵  Logs were written to "/home/joey/.wrangler/logs/wrangler-2026-11-1 |  |
| `raw_payloads_verified` | passed | 256/256 verified |  |
| `research_log_live` | passed | 5	OPEN	Alpha hypothesis: [REJECTED] Rising US shale gas output (3-month change, six basins) pre	alpha-hypothesis	2026-11 |  |
| `roster_81` | passed | 81 unique |  |
| `roster_all_collected` | blocked | 50/81 with real data; missing 31: HH_Cash_Midpoint, HH_Cash_High, HH_Cash_Low, HH_Cash_Volume, HH_M5, HH_M6, HH_M7, HH_M8, HH_M9, HH_M10, HH_M11, HH_M12, Flow_Kingsgate, Flow_Emers | external_data: NGI cash (4) and CME M5-M12 (8) need paid subscriptions; border/Mexico flows (5) and LNG feedgas (8) need pipeline EBB logins or postback-only pages; ECMWF day 10-15 (6) is not in the deterministic open feed |
| `schema_16_columns` | passed | missing=[] |  |
| `selfheal_live_ollama` | passed | {'selector': 'span.px', 'attempts': ['span.old', 'span.px']} {'passed': True, 'n_fixtures': 1, 'results': [True]} |  |
| `selfheal_pr_live` | passed | self-heal PRs: [(2, 'MERGED')] |  |
| `selfheal_unit` | passed | 12 passed in 0.02s |  |
| `snapshots_versioned` | passed | tracked snapshot days ['2026-11-13', '2026-11-14', '2026-11-15']; scheduled=True |  |
| `state_schema_contract` | passed | 13 passed in 0.28s |  |
| `unstructured_sources` | passed | documents {'noaa_discussion': 3, 'pipeline_notice': 409}; indexed in knowledge library {'noaa_discussion': 29, 'pipeline_notice': 117} |  |
| `web_ui_browser` | passed | 18 map nodes, panels=True, console errors=0 |  |
| `webhook_recovery` | passed | GitHub deliveries accepted after signature check: 6 of 6; reruns verified+ok=2, forged refused=1 |  |
| `worker_gateway_e2e` | passed (carried over) | PASS no bearer (401) / PASS bad bearer (401) / PASS origin without Access token (403) / PASS authenticated /execute (200) / PASS payload shape |  |

## Blocked requirements by cause

A requirement blocked by several checks is counted under each cause.

| Cause | Requirements |
|---|---|
| external_data | 67 |
| owner_action | 4 |
| platform_limit | 2 |

## Requirements not passed

| ID | Line | Status | Requirement | Checks |
|---|---|---|---|---|
| R1-05b19d29 | 7 | blocked | The system must identify, extract, normalize, preserve, correlate, analyze, and backtest relationships across  | roster_all_collected, experiments_recorded, promotion_gate, knowledge_library, worker_gateway_e2e |
| R1-b2d7a135 | 7 | blocked | It must connect physical market fundamentals, pipeline infrastructure, weather, storage, production, LNG expor | roster_all_collected, experiments_recorded, promotion_gate, knowledge_library, worker_gateway_e2e |
| R1-42c22dd1 | 9 | blocked | The system must identify relationships that conventional single-domain analysis misses, generate quantitative  | roster_all_collected, experiments_recorded, promotion_gate, knowledge_library, worker_gateway_e2e |
| R1-9282b34e | 11 | blocked | The project must integrate five complementary production-grade architectures into one connected system. | roster_all_collected, experiments_recorded, promotion_gate, knowledge_library, worker_gateway_e2e |
| R1-0f6ca3ca | 15 | blocked | Edge-to-Core Distributed Scraping and Extraction Mesh. | roster_all_collected, experiments_recorded, promotion_gate, knowledge_library, worker_gateway_e2e |
| R1-fa12c75e | 16 | blocked | Self-Healing Scraper and Automated Pull-Request Pipeline. | roster_all_collected, experiments_recorded, promotion_gate, knowledge_library, worker_gateway_e2e |
| R1-b5cb2f21 | 17 | blocked | Cross-Domain Semantic Friction Vector Engine. | roster_all_collected, experiments_recorded, promotion_gate, knowledge_library, worker_gateway_e2e |
| R1-ef031a2f | 18 | blocked | Serverless Walk-Forward Backtest Orchestrator. | roster_all_collected, experiments_recorded, promotion_gate, knowledge_library, worker_gateway_e2e |
| R1-f49cb20e | 19 | blocked | Remote Zero-Trust Command and Alpha Alerting Hub. | roster_all_collected, experiments_recorded, promotion_gate, knowledge_library, worker_gateway_e2e |
| R2-568e4dd8 | 37 | failed | Cloudflare Workers for edge execution, request authentication, orchestration, and job dispatch. | access_protects_hub, queue_dispatch, hub_health |
| R2-4a0ec542 | 38 | failed | Cloudflare Tunnel (cloudflared) for secure connectivity to the local workstation. | access_protects_hub, queue_dispatch, hub_health, full_test_suite |
| R2-79b4fa66 | 39 | failed | Cloudflare Access service tokens for machine-to-machine authentication. | access_protects_hub, queue_dispatch, hub_health |
| R2-8e92a39d | 40 | failed | Cloudflare Queues for asynchronous job distribution where appropriate. | access_protects_hub, queue_dispatch, hub_health |
| R2-42dd3747 | 52 | failed | cloudflared routing quant.joeysvault.app to the local Quant Hub on port 8090. | access_protects_hub, queue_dispatch, hub_health |
| R3-f1a3be90 | 62 | blocked | The system must collect market information from geographically and operationally diverse sources without relyi | roster_all_collected, collector_schedule, edge_collection, schema_16_columns, provenance_labels |
| R3.1-8dfbddee | 68 | blocked | Each collector must: | roster_all_collected, collector_schedule, edge_collection |
| R3.1-71a35591 | 69 | blocked | Retrieve its assigned source data. | roster_all_collected, collector_schedule, edge_collection, edge_ingest_unit |
| R3.1-270357ba | 70 | blocked | Support the relevant source protocol, including HTML, CSV, JSON, XML, and downloadable documents. | roster_all_collected, collector_schedule, edge_collection, edge_ingest_unit |
| R3.1-7f86c8bc | 71 | blocked | Record HTTP status, response headers, retrieval time, and source URL. | roster_all_collected, collector_schedule, edge_collection, edge_ingest_unit, raw_payloads_verified, observations_reference_payloads |
| R3.1-55936e8e | 72 | blocked | Preserve the original response payload. | roster_all_collected, collector_schedule, edge_collection, edge_ingest_unit, raw_payloads_verified, observations_reference_payloads |
| R3.1-d19b71d8 | 73 | blocked | Detect missing, malformed, stale, or unexpectedly changed source content. | roster_all_collected, collector_schedule, edge_collection, gatekeeper, collector_freshness, selfheal_unit |
| R3.1-92a7a9c5 | 74 | blocked | Apply source-specific request limits and retry policies. | roster_all_collected, collector_schedule, edge_collection, collectors_run |
| R3.1-7c54704e | 75 | blocked | Avoid violating source terms, access restrictions, or published rate limits. | roster_all_collected, collector_schedule, edge_collection, collectors_run, access_protects_hub, worker_gateway_e2e, schema_16_columns, provenance_labels |
| R3.1-62633990 | 77 | blocked | The implementation may group collectors into shared Worker deployments where appropriate; each agent must reta | roster_all_collected, collector_schedule, edge_collection, edge_ingest_unit |
| R3.1-6570b1fe | 79 | blocked | Cloudflare edge execution must not be assumed to eliminate source rate limits. | roster_all_collected, collector_schedule, edge_collection, collectors_run |
| R3.2-e1da111a | 83 | blocked | Each edge collector must transmit its retrieved payload and collection metadata to the local ingestion gateway | roster_all_collected, collector_schedule, edge_collection, edge_ingest_unit, schema_16_columns, provenance_labels |
| R3.2-81a4d839 | 86 | blocked | Cloudflare Worker. | roster_all_collected, collector_schedule, edge_collection, edge_ingest_unit, access_protects_hub, worker_gateway_e2e |
| R3.3-d8238967 | 104 | blocked | agent_id | roster_all_collected, collector_schedule, edge_collection, schema_16_columns, provenance_labels |
| R3.5-f90f98c5 | 137 | blocked | The Git history must preserve historical revisions and support reproducible retrieval. | raw_payloads_verified, observations_reference_payloads, schema_16_columns, provenance_labels, snapshots_versioned, branch_pushed, branch_protection |
| R3.5-fa8bfa50 | 137 | blocked | Enforce repository permissions and branch protections; do not assume ordinary Git history is intrinsically imm | snapshots_versioned, branch_pushed, branch_protection |
| R4-e0489c13 | 145 | blocked | These changes must not silently create permanent data gaps. | collector_freshness, selfheal_unit, roster_all_collected |
| R4.1-ced2a6ba | 149 | blocked | The Python orchestration system must monitor all 81 atomic agents. | selfheal_unit, gatekeeper, collector_freshness, roster_all_collected |
| R5-ee5ec77f | 222 | blocked | The system must discover relationships between seemingly unrelated market developments that can affect NGL and | knowledge_library, cross_domain_sources |
| R5.1-e87f9b97 | 231 | blocked | FERC filings and regulatory announcements. | cross_domain_sources |
| R5.1-b701c525 | 236 | blocked | LNG terminal operational notices. | cross_domain_sources |
| R5.1-8abc26bb | 237 | blocked | LNG feedgas and export activity. | cross_domain_sources |
| R5.1-6570c9d2 | 238 | blocked | NGL production and fractionation data. | cross_domain_sources, knowledge_library |
| R5.1-4a9afabc | 239 | blocked | Mont Belvieu NGL pricing. | cross_domain_sources |
| R5.1-f0067ece | 240 | blocked | Ethane, propane, normal butane, isobutane, and natural gasoline markets. | cross_domain_sources |
| R5.1-1a156787 | 241 | blocked | Petrochemical cracker outages and operating rates. | cross_domain_sources |
| R5.1-a2ae8606 | 242 | blocked | Refinery operating conditions. | cross_domain_sources |
| R5.1-bbd46e5a | 245 | blocked | Regional pipeline basis and forward curves. | cross_domain_sources |
| R5.1-957bc21d | 246 | blocked | Relevant financial and commodity-market publications. | cross_domain_sources |
| R5.3-b02ef1e4 | 277 | blocked | Permian pipeline outages during high-HDD weather conditions. | knowledge_library, unstructured_sources, provenance_labels, agents_live_run, hypothesis_evaluated_live, cross_domain_sources |
| R5.3-160de023 | 278 | blocked | LNG feedgas disruptions interacting with South Central storage inventories. | knowledge_library, unstructured_sources, provenance_labels, agents_live_run, hypothesis_evaluated_live, cross_domain_sources |
| R5.3-86b2bb28 | 279 | blocked | Ethane rejection changing the natural gas supply balance. | knowledge_library, unstructured_sources, provenance_labels, agents_live_run, hypothesis_evaluated_live, cross_domain_sources |
| R5.3-fbe545d1 | 280 | blocked | Petrochemical cracker outages affecting ethane and propane demand. | knowledge_library, unstructured_sources, provenance_labels, agents_live_run, hypothesis_evaluated_live, cross_domain_sources |
| R5.3-23aee387 | 281 | blocked | Propane export demand interacting with Gulf Coast fractionation constraints. | knowledge_library, unstructured_sources, provenance_labels, agents_live_run, hypothesis_evaluated_live, cross_domain_sources |
| R5.3-d78a74b5 | 282 | blocked | Weather-driven power burn changing regional natural gas basis. | knowledge_library, unstructured_sources, provenance_labels, agents_live_run, hypothesis_evaluated_live, cross_domain_sources |
| R5.3-76b20e87 | 284 | blocked | NGL purity-product spreads changing alongside natural gas and crude oil benchmarks. | knowledge_library, unstructured_sources, provenance_labels, agents_live_run, hypothesis_evaluated_live, cross_domain_sources |
| R5.3-afcfe344 | 285 | blocked | Associated gas production changing as crude oil economics shift. | knowledge_library, unstructured_sources, provenance_labels, agents_live_run, hypothesis_evaluated_live, cross_domain_sources |
| R5.3-01b98b4c | 286 | blocked | Mont Belvieu NGL price movements interacting with Henry Hub forward curves. | knowledge_library, unstructured_sources, provenance_labels, agents_live_run, hypothesis_evaluated_live, cross_domain_sources |
| R6.1-4385e970 | 332 | failed | Experiments must support parameter variations involving: | queue_dispatch, multi_feature_experiments, backtest_unit |
| R6.1-935d4351 | 333 | failed | Historical lag windows. | queue_dispatch, multi_feature_experiments, backtest_unit |
| R6.1-145227b9 | 334 | failed | Weather forecast model selection. | queue_dispatch, multi_feature_experiments, backtest_unit |
| R6.1-79761076 | 335 | failed | GFS versus ECMWF weighting. | queue_dispatch, multi_feature_experiments, backtest_unit |
| R6.1-6eb6b2fb | 336 | failed | HDD and CDD sensitivity. | queue_dispatch, multi_feature_experiments, backtest_unit |
| R6.1-eee2811d | 337 | failed | Production changes. | queue_dispatch, multi_feature_experiments, backtest_unit |
| R6.1-8d00578a | 338 | failed | Storage deviations. | queue_dispatch, multi_feature_experiments, backtest_unit |
| R6.1-ad5bf78c | 339 | failed | Pipeline flow disruptions. | queue_dispatch, multi_feature_experiments, backtest_unit |
| R6.1-c491e8d0 | 340 | failed | LNG feedgas changes. | queue_dispatch, multi_feature_experiments, backtest_unit |
| R6.1-9c71df28 | 341 | failed | NGL production and fractionation. | queue_dispatch, multi_feature_experiments, backtest_unit |
| R6.1-c7db39af | 342 | failed | Ethane rejection. | queue_dispatch, multi_feature_experiments, backtest_unit |
| R6.1-94f23cad | 343 | failed | Propane exports. | queue_dispatch, multi_feature_experiments, backtest_unit |
| R6.1-360db41e | 344 | failed | Petrochemical demand. | queue_dispatch, multi_feature_experiments, backtest_unit |
| R6.1-2ac160e8 | 345 | failed | Regional basis relationships. | queue_dispatch, multi_feature_experiments, backtest_unit |
| R6.1-30a88cfd | 346 | failed | Henry Hub forward curves. | queue_dispatch, multi_feature_experiments, backtest_unit |
| R6.1-95616166 | 347 | failed | Cross-domain vector-derived features. | queue_dispatch, multi_feature_experiments, backtest_unit |
| R6.2-d4023761 | 353 | failed | A local Python worker must retrieve authenticated experiment jobs through the Cloudflare infrastructure. | queue_dispatch, experiment_endpoint, experiments_recorded |
| R6.2-0a994e96 | 359 | failed | The system must not require thousands of simultaneous in-memory datasets. | queue_dispatch, experiment_endpoint, experiments_recorded, backtest_unit |
| R8-97616259 | 529 | failed | The five architectures must operate as a connected pipeline. | worker_gateway_e2e, queue_dispatch, knowledge_library, backtest_unit, roster_all_collected, edge_collection, alert_delivery |
| R8-8df61f90 | 533 | failed | Cloudflare Workers retrieve source material through scheduled edge collectors. | worker_gateway_e2e, queue_dispatch, knowledge_library, backtest_unit, roster_all_collected, edge_collection, alert_delivery |
| R8-976918fe | 534 | failed | Secure ingress delivers source payloads to the local extraction infrastructure. | worker_gateway_e2e, queue_dispatch, knowledge_library, backtest_unit, roster_all_collected, edge_collection, alert_delivery |
| R8-725b75a3 | 535 | failed | The 81 atomic agents extract, normalize, and validate market observations. | worker_gateway_e2e, queue_dispatch, knowledge_library, backtest_unit, roster_all_collected, edge_collection, alert_delivery |
| R8-414f2111 | 536 | failed | The ingestion system preserves original payloads and historical vintages. | worker_gateway_e2e, queue_dispatch, knowledge_library, backtest_unit, roster_all_collected, edge_collection, alert_delivery |
| R8-b7b57c6c | 537 | failed | SQLite stores structured PIT market observations. | worker_gateway_e2e, queue_dispatch, knowledge_library, backtest_unit, roster_all_collected, edge_collection, alert_delivery |
| R8-4268a48c | 538 | failed | Ollama embeddings index relevant source documents and market events. | worker_gateway_e2e, queue_dispatch, knowledge_library, backtest_unit, roster_all_collected, edge_collection, alert_delivery |
| R8-b6c9a07c | 539 | failed | The vector engine retrieves historical cross-domain analogs. | worker_gateway_e2e, queue_dispatch, knowledge_library, backtest_unit, roster_all_collected, edge_collection, alert_delivery |
| R8-356a1f16 | 540 | failed | Ollama synthesizes structured observations and unstructured market information. | worker_gateway_e2e, queue_dispatch, knowledge_library, backtest_unit, roster_all_collected, edge_collection, alert_delivery |
| R8-e0ad558a | 541 | failed | The hypothesis engine generates testable market relationships. | worker_gateway_e2e, queue_dispatch, knowledge_library, backtest_unit, roster_all_collected, edge_collection, alert_delivery |
| R8-88b7bc11 | 542 | failed | Cloudflare Queues distribute backtesting experiments. | worker_gateway_e2e, queue_dispatch, knowledge_library, backtest_unit, roster_all_collected, edge_collection, alert_delivery |
| R8-e43422f7 | 543 | failed | Local compute executes PIT walk-forward simulations. | worker_gateway_e2e, queue_dispatch, knowledge_library, backtest_unit, roster_all_collected, edge_collection, alert_delivery |
| R8-ed3fcfb1 | 544 | failed | The evaluation engine calculates out-of-sample performance. | worker_gateway_e2e, queue_dispatch, knowledge_library, backtest_unit, roster_all_collected, edge_collection, alert_delivery |
| R8-27bd6ebc | 545 | failed | GitHub preserves source code, experiment results, research memos, and approved model versions. | worker_gateway_e2e, queue_dispatch, knowledge_library, backtest_unit, roster_all_collected, edge_collection, alert_delivery |
| R8-20b70032 | 546 | failed | The remote Quant Hub exposes authenticated analytical capabilities. | worker_gateway_e2e, queue_dispatch, knowledge_library, backtest_unit, roster_all_collected, edge_collection, alert_delivery |
| R8-520b6109 | 547 | failed | The alerting system reports validated discoveries, operational failures, and material market developments. | worker_gateway_e2e, queue_dispatch, knowledge_library, backtest_unit, roster_all_collected, edge_collection, alert_delivery |
| R8-9adaa64a | 549 | failed | A successful system must connect all five architectures. | worker_gateway_e2e, queue_dispatch, knowledge_library, backtest_unit, roster_all_collected, edge_collection, alert_delivery |
| R9-8d62a603 | 586 | failed | Preserve Cloudflare Access authentication. | access_protects_hub, env_locked, execute_sandbox_tests, webhook_recovery |
| R9-319a765e | 587 | failed | Keep service credentials outside source control. | raw_payloads_verified, schema_16_columns, gatekeeper, access_protects_hub, env_locked, execute_sandbox_tests, webhook_recovery |
| R9-e22e92b1 | 588 | failed | Restrict local database execution to read-only operations where appropriate. | access_protects_hub, env_locked, execute_sandbox_tests, webhook_recovery |
| R9-6ec4b921 | 589 | failed | Authenticate remote jobs and webhooks. | access_protects_hub, env_locked, execute_sandbox_tests, webhook_recovery |
| R9-7dfd4af1 | 590 | failed | Require authorization before merging and deploying repaired code. | access_protects_hub, env_locked, execute_sandbox_tests, webhook_recovery |
| R9-a93f59cd | 591 | failed | Preserve execution and incident audit records. | access_protects_hub, env_locked, execute_sandbox_tests, webhook_recovery |
| R10-cf8a2b74 | 595 | blocked | The completed platform must be able to: | roster_all_collected, worker_gateway_e2e, backtest_unit |
| R10-d712f6b5 | 597 | blocked | Collect and maintain data from 81 or more specialized market-data agents. | roster_all_collected, worker_gateway_e2e, backtest_unit |
| R10-ba057802 | 598 | blocked | Retrieve historical market observations with exact point-in-time availability. | pit_tests, raw_payloads_verified, roster_all_collected, worker_gateway_e2e, backtest_unit |
| R10-1a94b50e | 599 | blocked | Preserve original source material and every relevant data vintage. | pit_tests, raw_payloads_verified, roster_all_collected, worker_gateway_e2e, backtest_unit |
| R10-13e066a4 | 600 | blocked | Detect and recover from source and parser failures. | selfheal_unit, selfheal_pr_live, webhook_recovery, roster_all_collected, worker_gateway_e2e, backtest_unit |
| R10-88e4ed77 | 601 | blocked | Generate tested scraper repairs and GitHub pull requests. | selfheal_unit, selfheal_pr_live, webhook_recovery, roster_all_collected, worker_gateway_e2e, backtest_unit |
| R10-4c202fb8 | 602 | blocked | Maintain a searchable cross-domain vector knowledge library. | knowledge_library, cross_domain_sources, hypothesis_memo, roster_all_collected, worker_gateway_e2e, backtest_unit |
| R10-325030ce | 603 | blocked | Identify historical analogs across natural gas, NGL, weather, infrastructure, and financial markets. | knowledge_library, cross_domain_sources, hypothesis_memo, roster_all_collected, worker_gateway_e2e, backtest_unit |
| R10-513986e3 | 604 | blocked | Generate structured, testable market-alpha hypotheses. | knowledge_library, cross_domain_sources, hypothesis_memo, roster_all_collected, worker_gateway_e2e, backtest_unit |
| R10-973553ea | 605 | failed | Execute large-scale PIT walk-forward backtesting experiments. | backtest_unit, leaderboard_versioned, queue_dispatch, roster_all_collected, worker_gateway_e2e |
| R10-3dba0e7d | 606 | failed | Rank competing models using out-of-sample performance. | backtest_unit, leaderboard_versioned, queue_dispatch, roster_all_collected, worker_gateway_e2e |
| R10-466788d5 | 607 | failed | Maintain reproducible experiment records and model leaderboards. | backtest_unit, leaderboard_versioned, queue_dispatch, roster_all_collected, worker_gateway_e2e |
| R10-dd8d6fa7 | 608 | blocked | Accept authenticated remote natural-language commands. | worker_gateway_e2e, alert_delivery, collector_schedule, roster_all_collected, backtest_unit |
| R10-0cd3fea1 | 609 | blocked | Execute quantitative scenario analyses on the local workstation. | worker_gateway_e2e, alert_delivery, collector_schedule, roster_all_collected, backtest_unit |
| R10-7b0e4bd5 | 610 | blocked | Produce auditable market research and alpha alerts. | worker_gateway_e2e, alert_delivery, collector_schedule, roster_all_collected, backtest_unit |
| R10-182dd91b | 611 | failed | Continuously improve its analytical capabilities through validated data, research, and backtesting. | backtest_unit, leaderboard_versioned, queue_dispatch, worker_gateway_e2e, alert_delivery, collector_schedule, roster_all_collected |
| R11-049dcf38 | 619 | blocked | Your responsibility is to backward-engineer the complete execution path from the ultimate objective to the req | full_test_suite, worker_gateway_e2e, architecture_doc, roster_all_collected |
| R11-1de351b2 | 629 | blocked | Identify existing agents, scripts, tests, scheduled jobs, and services. | full_test_suite, worker_gateway_e2e, architecture_doc, roster_all_collected |
| R11-2d6da86e | 642 | blocked | External data sources and access requirements. | full_test_suite, worker_gateway_e2e, architecture_doc, roster_all_collected |
| R12.2-f0f82166 | 681 | blocked | Create and route markets.joeysvault.app as a new subdomain under joeysvault.app. | public_markets, main_site_link, access_protects_hub, markets_local |
| R12.2-817681e4 | 682 | blocked | Create and route ngl.joeysvault.app (serving the NGL visual dashboard and the canonical synchronized JSON endp | public_markets, main_site_link, access_protects_hub, markets_local |
| R12.2-01eef309 | 683 | blocked | Link markets.joeysvault.app (and ngl.joeysvault.app where appropriate) directly from the main landing page htt | public_markets, main_site_link, access_protects_hub, markets_local |
| R12.2-e5fa8809 | 684 | blocked | Keep privileged write/LLM/execution endpoints on quant.joeysvault.app (127.0.0.1:8090) protected behind Cloudf | public_markets, main_site_link, access_protects_hub, markets_local |
| R12.4-97513311 | 696 | blocked | Dynamically detect and track whichever NGL or gas product is currently being calculated by the main pricing en | state_schema_contract, web_ui_browser, roster_all_collected |
| R12.4-b78c405d | 699 | blocked | Visually display the calculated price, historical price fluctuations, and the production/fundamental elements  | state_schema_contract, web_ui_browser, roster_all_collected |
| R12.5-0f7de509 | 704 | blocked | NGL-to-WTI Percentage Ratio Charts: Propane, normal butane, and natural gasoline plotted as a percentage of WT | indicators, web_ui_browser, roster_all_collected |
| R12.5-66afc426 | 705 | blocked | Mont Belvieu vs. Conway Hub Spreads: Side-by-side hub prices and differential spread tracking Gulf Coast vs. M | indicators, web_ui_browser, roster_all_collected |
| R12.5-42a3ffd8 | 706 | blocked | The "Frac Spread" Curve: Ethane ($/MMBtu) vs. Henry Hub natural gas ($/MMBtu), visually highlighting ethane re | indicators, web_ui_browser, roster_all_collected |
| R12.5-f4ab8294 | 707 | blocked | Forward Curve Contango and Backwardation: Futures term structure slope across delivery months with automatic r | indicators, web_ui_browser, roster_all_collected |
| R12.7-31088a85 | 724 | blocked | Live Regional Flows & Active Pipeline Alerts: Real-time border/LNG/interstate meter flows, capacity constraint | ngl_term, roster_all_collected |

## CLAUDE.md directive (requirement -> implementation -> checks)

| Requirement | CLAUDE.md line | Implementation | Checks | Status |
|---|---|---|---|---|
| Ollama: agent reasoning and task assistance | 21 | agents/workers.py SynthesisAgent, RepairAgent; agents/llm.py | agent_unit, ollama_live_integration, agents_live_run | passed |
| Ollama: structured extraction, classification, normalization, validation | 22 | agents/workers.py NoticeAnalystAgent (schema + source-label/severity/location checks), DiagnosticsAgent | agent_unit, ollama_live_integration, agents_live_run | passed |
| Ollama: anomaly detection and data-quality investigation | 23 | agents/workers.py AnomalyAgent, DataQualityAgent | agent_unit, agents_live_run | passed |
| Ollama: agent-to-agent knowledge exchange and synthesis | 24 | agents/memory.py publish/consume + findings; SynthesisAgent | agent_unit, agents_share_knowledge, agents_live_run | passed |
| Ollama: research synthesis grounded in retrieved source data | 25 | SynthesisAgent: PIT observations + semantic retrieval, numbers_grounded, evidence/observation citation checks | agent_unit, agents_live_run, hypothesis_evaluated_live | passed |
| Ollama: embedding generation and semantic retrieval | 26 | agents/llm.py embed; agents/memory.py search; kb_ingest.search | ollama_live_integration, knowledge_search_pit, agents_share_knowledge | passed |
| Ollama: error diagnosis and bounded self-healing assistance | 27 | DiagnosticsAgent -> incident -> RepairAgent (dry-run selfheal_pipeline.repair / code suggestion, never applied) | agent_unit, selfheal_unit, selfheal_live_ollama | passed |
| Model calls: explicit configuration, timeouts, error handling, logging, deterministic fallback | 29 | agents/llm.py CONFIG/status/_post/json(fallback, validate)/llm_calls | agent_unit, ollama_live_integration | passed |
| Not operational merely because the daemon responds | 29 | agents/llm.py status() requires the configured models; live tests | ollama_live_integration, agents_live_run | passed |
| Library: ingestion of documents, source material, agent findings, validated intelligence | 35 | kb_ingest.build_objects/ingest; agents/memory.add_finding | knowledge_library, agents_share_knowledge | passed |
| Library: text extraction, chunking, metadata, source attribution, provenance | 36 | kb_ingest.chunk_text + part_of edges; kb_nodes metadata | kb_chunking, knowledge_library, provenance_labels | passed |
| Library: vector embeddings and persistent vector indexing | 37 | kb_nodes.embedding + Chroma henry_hub_alpha_graph | knowledge_library, agents_share_knowledge, hub_health | passed |
| Library: semantic search and retrieval by agents and research workflows | 38 | agents/memory.search; /execute retrieve_vector_nodes; /api/knowledge-search | knowledge_search_pit, agents_live_run, worker_gateway_e2e | passed |
| Library: relationships between documents, concepts, series, agents, findings, features | 39 | kb_edges types previous_in_series, same_period, builds_on, semantic_neighbor, part_of, evidence_for, evaluated_by | knowledge_library, agents_share_knowledge, hypothesis_evaluated_live | passed |
| Library: graphical interface for exploring, searching, inspecting, navigating | 40 | web/knowledge.html + web/knowledge.js at /knowledge; /api/knowledge-graph, /api/knowledge-node, /api/agents/activity | knowledge_explorer, knowledge_explorer_browser, web_ui_browser | passed |
| Library: persistent across runs, updates, deduplication, traceable sources | 41 | doc_hash idempotent ingest; finding content-hash ids; raw_payloads | knowledge_library, agent_unit, raw_payloads_verified | passed |
| Library: Ollama for embedding and synthesis | 42 | nomic-embed-text embeddings; qwen3:4b synthesis | ollama_live_integration, agents_live_run | passed |
| Agents use shared intelligence and knowledge infrastructure (verified execution) | 47 | agents/ via /agents/run and the daily timer | agents_live_run, agents_share_knowledge, agents_scheduled | passed |
| Point-in-time correctness, no look-ahead in features, retrieval, inputs, training, backtesting | 50 | markets_engine.load_series, kb_ingest.search, memory.search assertions, observations(), evaluate(created<=as_of), backtest.py | pit_tests, knowledge_search_pit, agent_unit, backtest_unit | passed |
| End-to-end: acquisition -> ... -> agent collaboration -> Ollama synthesis -> backtesting -> persistent knowledge | 53 | collectors -> pit_market_data -> kb_ingest -> agents -> experiments -> kb findings/memos | collectors_run, knowledge_library, agents_live_run, hypothesis_evaluated_live, experiments_recorded | passed |
| Acceptance 6: point-in-time and no-look-ahead tests pass | 76 | tests/test_backtest.py, test_ingest.py, test_agents.py, ... | pit_tests, agent_unit | passed |
| Acceptance 7: relevant tests pass | 77 | pytest suite | full_test_suite | passed |
