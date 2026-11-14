# Requirement status (2026-11-14T00:38:42Z)

Source: `artifacts/Ultimate_Goal.md` (sha256 `8eb56ffd613480c1`) · 422 atomic requirements

| Status | Count |
|---|---|
| passed | 327 |
| failed | 0 |
| blocked | 95 |
| unverified | 0 |

## Checks

| Check | Status | Evidence | Blocked by |
|---|---|---|---|
| `access_protects_hub` | passed (carried over) | /execute 403, /ingest 403 |  |
| `alert_delivery` | passed (carried over) | incident issues [(3, 'CLOSED')]; event streams ['[backtests] backtests event st', '[selfheal] selfheal event stre'] |  |
| `architecture_doc` | passed (carried over) | sections present=['Architecture 1', 'Architecture 2', 'Architecture 3', 'Architecture 4', 'Architecture 5']; tracked=True |  |
| `audit_gists` | passed (carried over) | 5 recent hub gists |  |
| `backtest_unit` | passed (carried over) | 11 passed in 0.44s |  |
| `branch_protection` | blocked (carried over) | {"message":"Upgrade to GitHub Pro or make this repository public to enable this feature.","documentation_url":"https://d | owner decision (GitHub settings) |
| `branch_pushed` | passed (carried over) | ## quant-hub-build...origin/quant-hub-build |  |
| `collector_freshness` | passed (carried over) | all daily series fresh (<=5 days) |  |
| `collector_schedule` | passed (carried over) | timer enabled; worker crons ['crons = ["30 13 * * *", "45 15 * * THU"]  # daily 13:30 UTC (CPC); Thursdays 15:45 UTC (EIA storage, released 15:30Z). Day NAME used: Cloudflare numbe |  |
| `collectors_run` | passed (carried over) | OK   cpc_heating {'agent': 'Agent_Weather_Actual_HDD', 'obse / OK   cpc_cooling {'agent': 'Agent_Weather_Actual_CDD', 'obse / OK   eia_storage [{'agent': 'Agent_Storage_East', 'obs |  |
| `cross_domain_sources` | blocked (carried over) | have ['alpha_synthesis', 'backtest', 'carbon', 'noaa_discussion', 'pipeline_notice', 'price', 'production', 'storage', 'weather']; missing ['ferc', 'lng_notice', 'ngl_fractionation | FERC blocks automated fetches (403); LNG terminal, fractionation, cracker and NGL purity-product feeds need subscriptions |
| `db_integrity` | passed (carried over) | ok |  |
| `edge_collection` | passed (carried over) | edge sources with successful runs: ['cpc_heating', 'eia_hh_spot', 'eia_storage'] |  |
| `edge_ingest_unit` | passed (carried over) | 3 passed in 0.73s |  |
| `env_locked` | passed (carried over) | mode 0o600; ignored True; tracked secret files: none |  |
| `execute_sandbox_tests` | passed (carried over) | 11 passed in 0.18s |  |
| `experiment_endpoint` | passed (carried over) | HTTP 200 |  |
| `experiments_recorded` | passed (carried over) | 36 experiments, 0 incomplete |  |
| `full_test_suite` | passed (carried over) | 122 passed in 3.62s |  |
| `gatekeeper` | passed (carried over) | 3 passed in 0.10s |  |
| `hub_health` | passed (carried over) | {"ok":true,"db":"henry_hub_pit.db","vector_nodes":194} |  |
| `hypothesis_memo` | passed (carried over) | 5 passed in 0.01s |  |
| `indicators` | passed (carried over) | 9 passed in 0.07s |  |
| `knowledge_library` | passed (carried over) | 194 nodes, 9 domains, edges {'builds_on': 64, 'previous_in_series': 143, 'same_period': 24, 'semantic_neighbor': 183}, 0 missing PIT metadata |  |
| `knowledge_search_pit` | passed (carried over) | old cutoff -> 0 results; now -> 8 |  |
| `leaderboard_versioned` | passed (carried over) | tracked=True; 36/36 experiments listed |  |
| `main_site_link` | blocked (carried over) | HTTP 200, link present=False | deploy after the public routes serve |
| `markets_local` | passed (carried over) | state 200 ngl-state/1, /execute 404, / 200 |  |
| `multi_feature_experiments` | passed (carried over) | feature sets: ['hdd_anomaly', 'propane_wti_revert', 'propane_wti_momentum', 'hh_production_momentum'] | needs the missing LNG/flow/NGL collectors; only HDD-anomaly feature implemented |
| `ngl_term` | passed (carried over) | exit 0, 794 braille cells |  |
| `no_tmp_or_claude_paths` | passed (carried over) | none |  |
| `observations_reference_payloads` | passed (carried over) | 91783/91783 measured rows reference an archived payload |  |
| `ollama_models` | passed (carried over) | ['nomic-embed-text:latest', 'qwen3:4b'] |  |
| `ollama_only_local` | passed | none |  |
| `pit_tests` | passed (carried over) | 22 passed in 0.99s |  |
| `promotion_gate` | passed (carried over) | promotion conditions present in experiments.py |  |
| `provenance_labels` | passed (carried over) | 0 unlabelled rows |  |
| `public_markets` | blocked (carried over) | markets.joeysvault.app 404, ngl.joeysvault.app 404 | sudo: deploy/add_markets_ingress.sh must be run by the owner |
| `queue_dispatch` | passed (carried over) | │ d112469c13294f588a1ba71d09dcc8f0 │ quant-backtest-jobs │ 2026-11-13T13:20:59.57274Z  │ 2026-11-13T13:20:59.57274Z  │ 1         │ 1         |  |
| `raw_payloads_verified` | passed (carried over) | 163/163 verified |  |
| `research_log_live` | blocked (carried over) | no alpha-hypothesis issues | no hypothesis has passed promotion; publishing a rejected one would be misleading |
| `roster_81` | passed (carried over) | 81 unique |  |
| `roster_all_collected` | blocked (carried over) | 48/81 with real data; missing 33: HH_Cash_Midpoint, HH_Cash_High, HH_Cash_Low, HH_Cash_Volume, HH_M5, HH_M6, HH_M7, HH_M8, HH_M9, HH_M10, HH_M11, HH_M12, Flow_Kingsgate, Flow_Emers | paid/credentialed sources for NGI, CME, pipeline EBBs, ethane/butane/C5+, coal |
| `schema_16_columns` | passed (carried over) | missing=[] |  |
| `selfheal_live_ollama` | passed (carried over) | {'selector': 'span.px', 'attempts': ['span.px']} {'passed': True, 'n_fixtures': 1, 'results': [True]} |  |
| `selfheal_pr_live` | passed (carried over) | self-heal PRs: [(2, 'OPEN')] |  |
| `selfheal_unit` | passed (carried over) | 12 passed in 0.02s |  |
| `snapshots_versioned` | passed (carried over) | tracked snapshot days ['2026-11-13']; scheduled=True |  |
| `state_schema_contract` | passed (carried over) | 13 passed in 0.30s |  |
| `unstructured_sources` | passed (carried over) | documents {'noaa_discussion': 2, 'pipeline_notice': 383}; indexed in knowledge library {'noaa_discussion': 1, 'pipeline_notice': 83} |  |
| `web_ui_browser` | passed (carried over) | 18 map nodes, panels=True, console errors=0 |  |
| `webhook_recovery` | passed (carried over) | GitHub deliveries accepted after signature check: 2 of 2; reruns verified+ok=1, forged refused=1 |  |
| `worker_gateway_e2e` | passed (carried over) | PASS no bearer (401) / PASS bad bearer (401) / PASS origin without Access token (403) / PASS authenticated /execute (200) / PASS payload shape |  |

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
| R5.3-b02ef1e4 | 277 | blocked | Permian pipeline outages during high-HDD weather conditions. | knowledge_library, unstructured_sources, provenance_labels, cross_domain_sources |
| R5.3-160de023 | 278 | blocked | LNG feedgas disruptions interacting with South Central storage inventories. | knowledge_library, unstructured_sources, provenance_labels, cross_domain_sources |
| R5.3-86b2bb28 | 279 | blocked | Ethane rejection changing the natural gas supply balance. | knowledge_library, unstructured_sources, provenance_labels, cross_domain_sources |
| R5.3-fbe545d1 | 280 | blocked | Petrochemical cracker outages affecting ethane and propane demand. | knowledge_library, unstructured_sources, provenance_labels, cross_domain_sources |
| R5.3-23aee387 | 281 | blocked | Propane export demand interacting with Gulf Coast fractionation constraints. | knowledge_library, unstructured_sources, provenance_labels, cross_domain_sources |
| R5.3-d78a74b5 | 282 | blocked | Weather-driven power burn changing regional natural gas basis. | knowledge_library, unstructured_sources, provenance_labels, cross_domain_sources |
| R5.3-76b20e87 | 284 | blocked | NGL purity-product spreads changing alongside natural gas and crude oil benchmarks. | knowledge_library, unstructured_sources, provenance_labels, cross_domain_sources |
| R5.3-afcfe344 | 285 | blocked | Associated gas production changing as crude oil economics shift. | knowledge_library, unstructured_sources, provenance_labels, cross_domain_sources |
| R5.3-01b98b4c | 286 | blocked | Mont Belvieu NGL price movements interacting with Henry Hub forward curves. | knowledge_library, unstructured_sources, provenance_labels, cross_domain_sources |
| R5.5-c478768c | 318 | blocked | Each memo must reference the underlying source observations, vector nodes, model version, analytical assumptio | hypothesis_memo, research_log_live |
| R8-97616259 | 529 | blocked | The five architectures must operate as a connected pipeline. | worker_gateway_e2e, queue_dispatch, knowledge_library, backtest_unit, roster_all_collected, edge_collection, alert_delivery |
| R8-8df61f90 | 533 | blocked | Cloudflare Workers retrieve source material through scheduled edge collectors. | worker_gateway_e2e, queue_dispatch, knowledge_library, backtest_unit, roster_all_collected, edge_collection, alert_delivery |
| R8-976918fe | 534 | blocked | Secure ingress delivers source payloads to the local extraction infrastructure. | worker_gateway_e2e, queue_dispatch, knowledge_library, backtest_unit, roster_all_collected, edge_collection, alert_delivery |
| R8-725b75a3 | 535 | blocked | The 81 atomic agents extract, normalize, and validate market observations. | worker_gateway_e2e, queue_dispatch, knowledge_library, backtest_unit, roster_all_collected, edge_collection, alert_delivery |
| R8-414f2111 | 536 | blocked | The ingestion system preserves original payloads and historical vintages. | worker_gateway_e2e, queue_dispatch, knowledge_library, backtest_unit, roster_all_collected, edge_collection, alert_delivery |
| R8-b7b57c6c | 537 | blocked | SQLite stores structured PIT market observations. | worker_gateway_e2e, queue_dispatch, knowledge_library, backtest_unit, roster_all_collected, edge_collection, alert_delivery |
| R8-4268a48c | 538 | blocked | Ollama embeddings index relevant source documents and market events. | worker_gateway_e2e, queue_dispatch, knowledge_library, backtest_unit, roster_all_collected, edge_collection, alert_delivery |
| R8-b6c9a07c | 539 | blocked | The vector engine retrieves historical cross-domain analogs. | worker_gateway_e2e, queue_dispatch, knowledge_library, backtest_unit, roster_all_collected, edge_collection, alert_delivery |
| R8-356a1f16 | 540 | blocked | Ollama synthesizes structured observations and unstructured market information. | worker_gateway_e2e, queue_dispatch, knowledge_library, backtest_unit, roster_all_collected, edge_collection, alert_delivery |
| R8-e0ad558a | 541 | blocked | The hypothesis engine generates testable market relationships. | worker_gateway_e2e, queue_dispatch, knowledge_library, backtest_unit, roster_all_collected, edge_collection, alert_delivery |
| R8-88b7bc11 | 542 | blocked | Cloudflare Queues distribute backtesting experiments. | worker_gateway_e2e, queue_dispatch, knowledge_library, backtest_unit, roster_all_collected, edge_collection, alert_delivery |
| R8-e43422f7 | 543 | blocked | Local compute executes PIT walk-forward simulations. | worker_gateway_e2e, queue_dispatch, knowledge_library, backtest_unit, roster_all_collected, edge_collection, alert_delivery |
| R8-ed3fcfb1 | 544 | blocked | The evaluation engine calculates out-of-sample performance. | worker_gateway_e2e, queue_dispatch, knowledge_library, backtest_unit, roster_all_collected, edge_collection, alert_delivery |
| R8-27bd6ebc | 545 | blocked | GitHub preserves source code, experiment results, research memos, and approved model versions. | worker_gateway_e2e, queue_dispatch, knowledge_library, backtest_unit, roster_all_collected, edge_collection, alert_delivery |
| R8-20b70032 | 546 | blocked | The remote Quant Hub exposes authenticated analytical capabilities. | worker_gateway_e2e, queue_dispatch, knowledge_library, backtest_unit, roster_all_collected, edge_collection, alert_delivery |
| R8-520b6109 | 547 | blocked | The alerting system reports validated discoveries, operational failures, and material market developments. | worker_gateway_e2e, queue_dispatch, knowledge_library, backtest_unit, roster_all_collected, edge_collection, alert_delivery |
| R8-9adaa64a | 549 | blocked | A successful system must connect all five architectures. | worker_gateway_e2e, queue_dispatch, knowledge_library, backtest_unit, roster_all_collected, edge_collection, alert_delivery |
| R10-cf8a2b74 | 595 | blocked | The completed platform must be able to: | roster_all_collected, worker_gateway_e2e, backtest_unit |
| R10-d712f6b5 | 597 | blocked | Collect and maintain data from 81 or more specialized market-data agents. | roster_all_collected, worker_gateway_e2e, backtest_unit |
| R10-ba057802 | 598 | blocked | Retrieve historical market observations with exact point-in-time availability. | pit_tests, raw_payloads_verified, roster_all_collected, worker_gateway_e2e, backtest_unit |
| R10-1a94b50e | 599 | blocked | Preserve original source material and every relevant data vintage. | pit_tests, raw_payloads_verified, roster_all_collected, worker_gateway_e2e, backtest_unit |
| R10-13e066a4 | 600 | blocked | Detect and recover from source and parser failures. | selfheal_unit, selfheal_pr_live, webhook_recovery, roster_all_collected, worker_gateway_e2e, backtest_unit |
| R10-88e4ed77 | 601 | blocked | Generate tested scraper repairs and GitHub pull requests. | selfheal_unit, selfheal_pr_live, webhook_recovery, roster_all_collected, worker_gateway_e2e, backtest_unit |
| R10-4c202fb8 | 602 | blocked | Maintain a searchable cross-domain vector knowledge library. | knowledge_library, cross_domain_sources, hypothesis_memo, roster_all_collected, worker_gateway_e2e, backtest_unit |
| R10-325030ce | 603 | blocked | Identify historical analogs across natural gas, NGL, weather, infrastructure, and financial markets. | knowledge_library, cross_domain_sources, hypothesis_memo, roster_all_collected, worker_gateway_e2e, backtest_unit |
| R10-513986e3 | 604 | blocked | Generate structured, testable market-alpha hypotheses. | knowledge_library, cross_domain_sources, hypothesis_memo, roster_all_collected, worker_gateway_e2e, backtest_unit |
| R10-973553ea | 605 | blocked | Execute large-scale PIT walk-forward backtesting experiments. | backtest_unit, leaderboard_versioned, queue_dispatch, roster_all_collected, worker_gateway_e2e |
| R10-3dba0e7d | 606 | blocked | Rank competing models using out-of-sample performance. | backtest_unit, leaderboard_versioned, queue_dispatch, roster_all_collected, worker_gateway_e2e |
| R10-466788d5 | 607 | blocked | Maintain reproducible experiment records and model leaderboards. | backtest_unit, leaderboard_versioned, queue_dispatch, roster_all_collected, worker_gateway_e2e |
| R10-dd8d6fa7 | 608 | blocked | Accept authenticated remote natural-language commands. | worker_gateway_e2e, alert_delivery, collector_schedule, roster_all_collected, backtest_unit |
| R10-0cd3fea1 | 609 | blocked | Execute quantitative scenario analyses on the local workstation. | worker_gateway_e2e, alert_delivery, collector_schedule, roster_all_collected, backtest_unit |
| R10-7b0e4bd5 | 610 | blocked | Produce auditable market research and alpha alerts. | worker_gateway_e2e, alert_delivery, collector_schedule, roster_all_collected, backtest_unit |
| R10-182dd91b | 611 | blocked | Continuously improve its analytical capabilities through validated data, research, and backtesting. | backtest_unit, leaderboard_versioned, queue_dispatch, worker_gateway_e2e, alert_delivery, collector_schedule, roster_all_collected |
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
