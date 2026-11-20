# Requirement status (2026-11-19T23:49:18Z)

Source: `artifacts/Ultimate_Goal.md` (sha256 `8eb56ffd613480c1`) · 427 atomic requirements

| Status | Count |
|---|---|
| passed | 151 |
| failed | 258 |
| blocked | 18 |
| unverified | 0 |

## Checks

| Check | Status | Evidence | Blocked by |
|---|---|---|---|
| `access_protects_hub` | passed | /execute 403, /ingest 403 |  |
| `agent_unit` | passed |   warnings.warn(PytestDeprecationWarning(_DEFAULT_FIXTURE_LOOP_SCOPE_UNSET)) |  |
| `agents_live_run` | failed | error: OperationalError: no such table: agent_runs |  |
| `agents_scheduled` | failed | timer /bin/sh: 1: systemctl: not found; ExecStopPost run_agents.py=False; /ingest trigger=True |  |
| `agents_share_knowledge` | failed | error: OperationalError: no such table: agent_message_reads |  |
| `alert_delivery` | failed | incident issues []; event streams [] |  |
| `architecture_doc` | passed | sections present=['Architecture 1', 'Architecture 2', 'Architecture 3', 'Architecture 4', 'Architecture 5']; tracked=True |  |
| `audit_gists` | failed | 0 recent hub gists |  |
| `backtest_unit` | passed |   warnings.warn(PytestDeprecationWarning(_DEFAULT_FIXTURE_LOOP_SCOPE_UNSET)) |  |
| `branch_protection` | blocked | Welcome to GitHub CLI!

To authenticate, please run `gh auth login`. | platform_limit: GitHub requires Pro or a public repository for branch protection on this private repo |
| `branch_pushed` | passed | ## quant-hub-build...origin/quant-hub-build |  |
| `collector_freshness` | passed | all daily series fresh (<=5 days) |  |
| `collector_schedule` | failed | timer /bin/sh: 1: systemctl: not found; worker crons ['crons = ["30 13 * * *", "45 15 * * THU"]  # daily 13:30 UTC (CPC); Thursdays 15:45 UTC (EIA storage, released 15:30Z). Day NA |  |
| `collectors_run` | passed (carried over) | OK   cpc_heating {'agent': 'Agent_Weather_Actual_HDD', 'obse / OK   cpc_cooling {'agent': 'Agent_Weather_Actual_CDD', 'obse / OK   eia_storage [{'agent': 'Agent_Storage_East', 'obs |  |
| `cross_domain_sources` | blocked | error: OperationalError: no such table: kb_nodes | external_data: FERC blocks automated fetches (403); LNG terminal notices, NGL fractionation, cracker/refinery outages and Mont Belvieu purity products other than propane need paid feeds |
| `db_integrity` | passed | ok |  |
| `edge_collection` | failed | edge sources with successful runs: [] |  |
| `edge_ingest_unit` | passed |   warnings.warn(PytestDeprecationWarning(_DEFAULT_FIXTURE_LOOP_SCOPE_UNSET)) |  |
| `env_locked` | passed | mode 0o600; ignored True; tracked secret files: none |  |
| `execute_sandbox_tests` | passed |   warnings.warn(PytestDeprecationWarning(_DEFAULT_FIXTURE_LOOP_SCOPE_UNSET)) |  |
| `experiment_endpoint` | passed | HTTP 200 |  |
| `experiments_recorded` | failed | error: OperationalError: no such table: experiments |  |
| `full_test_suite` | passed |   warnings.warn(PytestDeprecationWarning(_DEFAULT_FIXTURE_LOOP_SCOPE_UNSET)) |  |
| `gatekeeper` | passed |   warnings.warn(PytestDeprecationWarning(_DEFAULT_FIXTURE_LOOP_SCOPE_UNSET)) |  |
| `hub_health` | passed | {"ok":true,"db":"henry_hub_pit.db","vector_nodes":0,"version":"1.0.2","release_version":"1.0.2","release_commit":"dev"," |  |
| `hypothesis_evaluated_live` | failed | error: OperationalError: no such table: finding_status |  |
| `hypothesis_memo` | passed |   warnings.warn(PytestDeprecationWarning(_DEFAULT_FIXTURE_LOOP_SCOPE_UNSET)) |  |
| `indicators` | passed |   warnings.warn(PytestDeprecationWarning(_DEFAULT_FIXTURE_LOOP_SCOPE_UNSET)) |  |
| `kb_chunking` | failed | error: OperationalError: no such table: kb_edges |  |
| `knowledge_explorer` | failed | /knowledge 200; graph 0 nodes, edge types []; inspector 0 edges=0; tests   warnings.warn(PytestDeprecationWarning(_DEFAULT_FIXTURE_LOOP_SCOPE_UNSET)) |  |
| `knowledge_explorer_browser` | failed | google-chrome not installed |  |
| `knowledge_library` | failed | error: OperationalError: no such table: kb_nodes |  |
| `knowledge_search_pit` | failed | old cutoff -> 0 results; now -> 0 |  |
| `leaderboard_versioned` | failed | error: OperationalError: no such table: experiments |  |
| `main_site_link` | passed | HTTP 200, link present=True |  |
| `markets_local` | passed | state 200 ngl-state/1, /execute 404, / 200 |  |
| `multi_feature_experiments` | passed | feature sets: ['hdd_anomaly', 'propane_wti_revert', 'propane_wti_momentum', 'hh_production_momentum'] |  |
| `ngl_term` | passed | exit 0, 718 braille cells |  |
| `no_tmp_or_claude_paths` | passed | none |  |
| `observations_reference_payloads` | passed | 0/0 measured rows reference an archived payload |  |
| `ollama_live_integration` | passed |   warnings.warn(PytestDeprecationWarning(_DEFAULT_FIXTURE_LOOP_SCOPE_UNSET)) |  |
| `ollama_models` | passed | ['nomic-embed-text:latest', 'qwen2.5-coder:32b', 'qwen2.5:7b', 'qwen3:4b'] |  |
| `ollama_only_local` | passed | none |  |
| `pit_tests` | passed |   warnings.warn(PytestDeprecationWarning(_DEFAULT_FIXTURE_LOOP_SCOPE_UNSET)) |  |
| `promotion_gate` | passed | promotion conditions present in experiments.py |  |
| `provenance_labels` | passed | 0 unlabelled rows |  |
| `public_markets` | passed | markets.joeysvault.app 200, ngl.joeysvault.app 200 |  |
| `quant_hub_retrieval` | passed | ingested 4 documents, kg_vector: 3 hits, kg_keyword: 3 hits, raw_vector: 2 hits, combo: 5 hits, kg_query_engine: 1 hits, kg_rag: 1 hits, save/load ok |  |
| `quant_hub_spark_basis` | passed | HH spot 3.87; forward curve 91 pts |  |
| `quant_hub_stress` | passed | winter_storm_uri_freeze_scenario: 31 pts, pipeline_outage_shock: 8 pts, multi_factor_shift: 36 pts |  |
| `quant_hub_var` | passed | parametric: VaR 0.362, ES 0.473; historical: VaR 0.365, ES 0.473; montecarlo: VaR 0.366, ES 0.447 |  |
| `queue_dispatch` | failed | /bin/sh: 1: wrangler: not found
 |  |
| `raw_payloads_verified` | failed | 0/0 verified |  |
| `research_log_live` | blocked | Welcome to GitHub CLI!

To authenticate, please run `gh auth login`. | none: resolved when a memo issue exists |
| `roster_81` | passed | 81 unique |  |
| `roster_all_collected` | blocked | 0/81 with real data; missing 81: HH_Cash_Midpoint, HH_Cash_High, HH_Cash_Low, HH_Cash_Volume, HH_M1, HH_M2, HH_M3, HH_M4, HH_M5, HH_M6, HH_M7, HH_M8, HH_M9, HH_M10, HH_M11, HH_M12, | external_data: NGI cash (4) and CME M5-M12 (8) need paid subscriptions; border/Mexico flows (5) and LNG feedgas (8) need pipeline EBB logins or postback-only pages; ECMWF day 10-15 (6) is not in the deterministic open feed |
| `schema_16_columns` | passed | missing=[] |  |
| `selfheal_live_ollama` | passed | {'selector': 'span.px', 'attempts': ['span.old', 'span.px']} {'passed': True, 'n_fixtures': 1, 'results': [True]} |  |
| `selfheal_pr_live` | failed | self-heal PRs: [] |  |
| `selfheal_unit` | passed |   warnings.warn(PytestDeprecationWarning(_DEFAULT_FIXTURE_LOOP_SCOPE_UNSET)) |  |
| `snapshots_versioned` | failed | error: FileNotFoundError: [Errno 2] No such file or directory: '/root/.config/systemd/user/hh-collect-cpc.service' |  |
| `state_schema_contract` | passed |   warnings.warn(PytestDeprecationWarning(_DEFAULT_FIXTURE_LOOP_SCOPE_UNSET)) |  |
| `unstructured_sources` | failed | no such table: documents |  |
| `web_ui_browser` | failed | google-chrome not installed |  |
| `webhook_recovery` | failed | GitHub deliveries accepted after signature check: 0 of 0; reruns verified+ok=0, forged refused=0 |  |
| `worker_gateway_e2e` | passed (carried over) | PASS no bearer (401) / PASS bad bearer (401) / PASS origin without Access token (403) / PASS authenticated /execute (200) / PASS payload shape |  |

## Blocked requirements by cause

A requirement blocked by several checks is counted under each cause.

| Cause | Requirements |
|---|---|
| external_data | 17 |
| none | 1 |

## Requirements not passed

| ID | Line | Status | Requirement | Checks |
|---|---|---|---|---|
| R1-05b19d29 | 7 | failed | The system must identify, extract, normalize, preserve, correlate, analyze, and backtest relationships across  | roster_all_collected, experiments_recorded, promotion_gate, knowledge_library, worker_gateway_e2e |
| R1-b2d7a135 | 7 | failed | It must connect physical market fundamentals, pipeline infrastructure, weather, storage, production, LNG expor | roster_all_collected, experiments_recorded, promotion_gate, knowledge_library, worker_gateway_e2e |
| R1-42c22dd1 | 9 | failed | The system must identify relationships that conventional single-domain analysis misses, generate quantitative  | roster_all_collected, experiments_recorded, promotion_gate, knowledge_library, worker_gateway_e2e |
| R1-9282b34e | 11 | failed | The project must integrate five complementary production-grade architectures into one connected system. | roster_all_collected, experiments_recorded, promotion_gate, knowledge_library, worker_gateway_e2e |
| R1-0f6ca3ca | 15 | failed | Edge-to-Core Distributed Scraping and Extraction Mesh. | roster_all_collected, experiments_recorded, promotion_gate, knowledge_library, worker_gateway_e2e |
| R1-fa12c75e | 16 | failed | Self-Healing Scraper and Automated Pull-Request Pipeline. | roster_all_collected, experiments_recorded, promotion_gate, knowledge_library, worker_gateway_e2e |
| R1-b5cb2f21 | 17 | failed | Cross-Domain Semantic Friction Vector Engine. | roster_all_collected, experiments_recorded, promotion_gate, knowledge_library, worker_gateway_e2e |
| R1-ef031a2f | 18 | failed | Serverless Walk-Forward Backtest Orchestrator. | roster_all_collected, experiments_recorded, promotion_gate, knowledge_library, worker_gateway_e2e |
| R1-f49cb20e | 19 | failed | Remote Zero-Trust Command and Alpha Alerting Hub. | roster_all_collected, experiments_recorded, promotion_gate, knowledge_library, worker_gateway_e2e |
| R2-b3b3d2ca | 34 | failed | Python-based orchestration, extraction, analysis, and backtesting. | audit_gists, hub_health, full_test_suite |
| R2-568e4dd8 | 37 | failed | Cloudflare Workers for edge execution, request authentication, orchestration, and job dispatch. | access_protects_hub, queue_dispatch, hub_health |
| R2-4a0ec542 | 38 | failed | Cloudflare Tunnel (cloudflared) for secure connectivity to the local workstation. | access_protects_hub, queue_dispatch, hub_health, full_test_suite |
| R2-79b4fa66 | 39 | failed | Cloudflare Access service tokens for machine-to-machine authentication. | access_protects_hub, queue_dispatch, hub_health |
| R2-8e92a39d | 40 | failed | Cloudflare Queues for asynchronous job distribution where appropriate. | access_protects_hub, queue_dispatch, hub_health |
| R2-9b7d461a | 43 | failed | SQLite henry_hub_pit.db for structured point-in-time market observations. | db_integrity, raw_payloads_verified, knowledge_library |
| R2-4c44878c | 44 | failed | ChromaDB or another suitable persistent vector database for semantic retrieval. | db_integrity, raw_payloads_verified, knowledge_library |
| R2-aab33591 | 45 | failed | Original HTML, CSV, JSON, XML, PDF, and other source payloads preserved for reproducibility. | db_integrity, raw_payloads_verified, knowledge_library |
| R2-f82d10cb | 46 | failed | GitHub private repositories for version-controlled code, historical data snapshots, experiment records, and re | audit_gists, hub_health, full_test_suite |
| R2-643ab18c | 49 | failed | GitHub CLI (gh) for commits, pull requests, issues, discussions, and private Gist creation. | audit_gists, hub_health, full_test_suite |
| R2-2ce58f4b | 50 | failed | Python orchestrators for scraping, extraction, validation, ingestion, recovery, and backtesting. | audit_gists, hub_health, full_test_suite |
| R2-d6fb9a7f | 51 | failed | FastAPI for local execution services. | audit_gists, hub_health, full_test_suite |
| R2-42dd3747 | 52 | failed | cloudflared routing quant.joeysvault.app to the local Quant Hub on port 8090. | access_protects_hub, queue_dispatch, hub_health |
| R3-f1a3be90 | 62 | failed | The system must collect market information from geographically and operationally diverse sources without relyi | roster_all_collected, collector_schedule, edge_collection, schema_16_columns, provenance_labels |
| R3.1-8dfbddee | 68 | failed | Each collector must: | roster_all_collected, collector_schedule, edge_collection |
| R3.1-71a35591 | 69 | failed | Retrieve its assigned source data. | roster_all_collected, collector_schedule, edge_collection, edge_ingest_unit |
| R3.1-270357ba | 70 | failed | Support the relevant source protocol, including HTML, CSV, JSON, XML, and downloadable documents. | roster_all_collected, collector_schedule, edge_collection, edge_ingest_unit |
| R3.1-7f86c8bc | 71 | failed | Record HTTP status, response headers, retrieval time, and source URL. | roster_all_collected, collector_schedule, edge_collection, edge_ingest_unit, raw_payloads_verified, observations_reference_payloads |
| R3.1-55936e8e | 72 | failed | Preserve the original response payload. | roster_all_collected, collector_schedule, edge_collection, edge_ingest_unit, raw_payloads_verified, observations_reference_payloads |
| R3.1-d19b71d8 | 73 | failed | Detect missing, malformed, stale, or unexpectedly changed source content. | roster_all_collected, collector_schedule, edge_collection, gatekeeper, collector_freshness, selfheal_unit |
| R3.1-92a7a9c5 | 74 | failed | Apply source-specific request limits and retry policies. | roster_all_collected, collector_schedule, edge_collection, collectors_run |
| R3.1-7c54704e | 75 | failed | Avoid violating source terms, access restrictions, or published rate limits. | roster_all_collected, collector_schedule, edge_collection, collectors_run, access_protects_hub, worker_gateway_e2e, schema_16_columns, provenance_labels |
| R3.1-62633990 | 77 | failed | The implementation may group collectors into shared Worker deployments where appropriate; each agent must reta | roster_all_collected, collector_schedule, edge_collection, edge_ingest_unit |
| R3.1-6570b1fe | 79 | failed | Cloudflare edge execution must not be assumed to eliminate source rate limits. | roster_all_collected, collector_schedule, edge_collection, collectors_run |
| R3.2-e1da111a | 83 | failed | Each edge collector must transmit its retrieved payload and collection metadata to the local ingestion gateway | roster_all_collected, collector_schedule, edge_collection, edge_ingest_unit, schema_16_columns, provenance_labels |
| R3.2-730c15bc | 85 | failed | Required components: | edge_collection, edge_ingest_unit, access_protects_hub, worker_gateway_e2e |
| R3.2-81a4d839 | 86 | failed | Cloudflare Worker. | roster_all_collected, collector_schedule, edge_collection, edge_ingest_unit, access_protects_hub, worker_gateway_e2e |
| R3.2-2601812e | 87 | failed | HTTPS transport. | edge_collection, edge_ingest_unit, access_protects_hub, worker_gateway_e2e |
| R3.2-fa6b555a | 88 | failed | Cloudflare Access service-token authentication. | edge_collection, edge_ingest_unit, access_protects_hub, worker_gateway_e2e |
| R3.2-873b3767 | 89 | failed | CF-Access-Client-Id. | edge_collection, edge_ingest_unit, access_protects_hub, worker_gateway_e2e |
| R3.2-a95205e8 | 90 | failed | CF-Access-Client-Secret. | edge_collection, edge_ingest_unit, access_protects_hub, worker_gateway_e2e |
| R3.2-91b8b6d3 | 91 | failed | Cloudflare Tunnel. | edge_collection, edge_ingest_unit, access_protects_hub, worker_gateway_e2e |
| R3.2-7856bc0f | 92 | failed | Local authenticated ingestion endpoint. | edge_collection, edge_ingest_unit, access_protects_hub, worker_gateway_e2e |
| R3.2-d700c127 | 94 | failed | The local workstation must not expose an unauthenticated public ingestion port. | edge_collection, edge_ingest_unit, access_protects_hub, worker_gateway_e2e |
| R3.3-d8238967 | 104 | failed | agent_id | roster_all_collected, collector_schedule, edge_collection, schema_16_columns, provenance_labels |
| R3.4-42730f5e | 129 | failed | Never overwrite an earlier historical observation when a source revises its data. | pit_tests, raw_payloads_verified |
| R3.4-e684b36f | 131 | failed | The system must support reconstruction of exactly what the platform knew at any historical decision timestamp. | pit_tests, raw_payloads_verified |
| R3.5-f90f98c5 | 137 | failed | The Git history must preserve historical revisions and support reproducible retrieval. | raw_payloads_verified, observations_reference_payloads, schema_16_columns, provenance_labels, snapshots_versioned, branch_pushed, branch_protection |
| R3.5-fa8bfa50 | 137 | failed | Enforce repository permissions and branch protections; do not assume ordinary Git history is intrinsically imm | snapshots_versioned, branch_pushed, branch_protection |
| R4-e0489c13 | 145 | blocked | These changes must not silently create permanent data gaps. | collector_freshness, selfheal_unit, roster_all_collected |
| R4.1-ced2a6ba | 149 | blocked | The Python orchestration system must monitor all 81 atomic agents. | selfheal_unit, gatekeeper, collector_freshness, roster_all_collected |
| R4.2-71558763 | 169 | failed | Preserve the original response or failure payload. | selfheal_unit, raw_payloads_verified |
| R4.2-9605ad89 | 170 | failed | Capture the relevant HTML DOM or source document. | selfheal_unit, raw_payloads_verified |
| R4.2-129d5f32 | 171 | failed | Preserve the previous working parser. | selfheal_unit, raw_payloads_verified |
| R4.2-dee76e0c | 172 | failed | Capture the failed extraction output. | selfheal_unit, raw_payloads_verified |
| R4.2-4728e1aa | 173 | failed | Record the expected schema and actual schema. | selfheal_unit, raw_payloads_verified |
| R4.2-72522df4 | 174 | failed | Record the failure timestamp and source identity. | selfheal_unit, raw_payloads_verified |
| R4.4-f57940b2 | 192 | failed | The repair pipeline must: | selfheal_unit, selfheal_pr_live |
| R4.4-333bdf25 | 193 | failed | Create an isolated working branch. | selfheal_unit, selfheal_pr_live |
| R4.4-f69ec027 | 194 | failed | Apply the proposed patch. | selfheal_unit, selfheal_pr_live |
| R4.4-02d45091 | 195 | failed | Run unit tests against preserved source fixtures. | selfheal_unit, selfheal_pr_live |
| R4.4-5aedbcff | 196 | failed | Run schema validation. | selfheal_unit, selfheal_pr_live |
| R4.4-2781b5c3 | 197 | failed | Compare extracted values against known expected results. | selfheal_unit, selfheal_pr_live |
| R4.4-f06a7416 | 198 | failed | Check timestamp and PIT handling. | selfheal_unit, selfheal_pr_live |
| R4.4-44c2a840 | 199 | failed | Generate a repair report. | selfheal_unit, selfheal_pr_live |
| R4.4-a113ed48 | 200 | failed | Open a GitHub pull request using gh pr create. | selfheal_unit, selfheal_pr_live |
| R4.4-d78818ad | 206 | failed | Production deployment must require successful tests and an authorized merge. | selfheal_unit, selfheal_pr_live |
| R4.4-afc642da | 206 | failed | Do not allow an LLM to approve and deploy its own unverified code changes. | selfheal_unit, selfheal_pr_live |
| R4.5-34636c2d | 212 | failed | The Worker must authenticate the event and enqueue a deployment or execution request. | webhook_recovery |
| R4.5-81c63eb3 | 214 | failed | The local orchestrator must retrieve the approved change, verify its identity, and rerun the affected collecto | webhook_recovery |
| R5-ee5ec77f | 222 | failed | The system must discover relationships between seemingly unrelated market developments that can affect NGL and | knowledge_library, cross_domain_sources |
| R5.1-bce3a3ea | 228 | failed | Interstate pipeline critical notices. | unstructured_sources |
| R5.1-9063d06b | 229 | failed | Pipeline force majeure declarations. | unstructured_sources |
| R5.1-fb226838 | 230 | failed | Pipeline maintenance and capacity restrictions. | unstructured_sources |
| R5.1-e87f9b97 | 231 | blocked | FERC filings and regulatory announcements. | cross_domain_sources |
| R5.1-6ff76df8 | 232 | failed | EIA natural gas storage reports. | knowledge_library |
| R5.1-a8f3b9e5 | 233 | failed | EIA production and consumption data. | knowledge_library |
| R5.1-94e57388 | 234 | failed | NOAA weather forecasts and discussions. | unstructured_sources, knowledge_library |
| R5.1-cd0ea029 | 235 | failed | GFS and ECMWF weather model outputs. | knowledge_library |
| R5.1-b701c525 | 236 | blocked | LNG terminal operational notices. | cross_domain_sources |
| R5.1-8abc26bb | 237 | blocked | LNG feedgas and export activity. | cross_domain_sources |
| R5.1-6570c9d2 | 238 | failed | NGL production and fractionation data. | cross_domain_sources, knowledge_library |
| R5.1-4a9afabc | 239 | blocked | Mont Belvieu NGL pricing. | cross_domain_sources |
| R5.1-f0067ece | 240 | blocked | Ethane, propane, normal butane, isobutane, and natural gasoline markets. | cross_domain_sources |
| R5.1-1a156787 | 241 | blocked | Petrochemical cracker outages and operating rates. | cross_domain_sources |
| R5.1-a2ae8606 | 242 | blocked | Refinery operating conditions. | cross_domain_sources |
| R5.1-e103a1ec | 243 | failed | Natural gas power burn. | knowledge_library |
| R5.1-439d46f3 | 244 | failed | Coal-to-gas switching. | knowledge_library |
| R5.1-bbd46e5a | 245 | blocked | Regional pipeline basis and forward curves. | cross_domain_sources |
| R5.1-957bc21d | 246 | blocked | Relevant financial and commodity-market publications. | cross_domain_sources |
| R5.1-e950f03d | 248 | failed | Every indexed document must preserve its source, publication timestamp, availability timestamp, valid period,  | knowledge_library |
| R5.2-8039cbe9 | 260 | failed | The system must support: | ollama_models, knowledge_library, knowledge_search_pit |
| R5.2-6b5ef082 | 261 | failed | Semantic similarity retrieval. | ollama_models, knowledge_library, knowledge_search_pit |
| R5.2-5afea306 | 262 | failed | Historical event retrieval. | ollama_models, knowledge_library, knowledge_search_pit |
| R5.2-20b04406 | 263 | failed | Cross-domain event relationships. | ollama_models, knowledge_library, knowledge_search_pit |
| R5.2-1ad10fbf | 264 | failed | Time-filtered retrieval. | ollama_models, knowledge_library, knowledge_search_pit |
| R5.2-c9a8c0b7 | 265 | failed | Geographic filtering. | ollama_models, knowledge_library, knowledge_search_pit |
| R5.2-99aa362c | 266 | failed | Agent and source filtering. | ollama_models, knowledge_library, knowledge_search_pit |
| R5.2-2ae66e0f | 267 | failed | Parent-child knowledge relationships. | ollama_models, knowledge_library, knowledge_search_pit |
| R5.2-10ddaa3c | 268 | failed | Provenance tracking. | ollama_models, knowledge_library, knowledge_search_pit |
| R5.2-8d561091 | 269 | failed | Historical reconstruction of knowledge available at a given timestamp. | ollama_models, knowledge_library, knowledge_search_pit |
| R5.3-cd46a0a7 | 275 | failed | Examples of required analytical relationships include: | knowledge_library, unstructured_sources, provenance_labels, agents_live_run, hypothesis_evaluated_live |
| R5.3-b02ef1e4 | 277 | failed | Permian pipeline outages during high-HDD weather conditions. | knowledge_library, unstructured_sources, provenance_labels, agents_live_run, hypothesis_evaluated_live, cross_domain_sources |
| R5.3-160de023 | 278 | failed | LNG feedgas disruptions interacting with South Central storage inventories. | knowledge_library, unstructured_sources, provenance_labels, agents_live_run, hypothesis_evaluated_live, cross_domain_sources |
| R5.3-86b2bb28 | 279 | failed | Ethane rejection changing the natural gas supply balance. | knowledge_library, unstructured_sources, provenance_labels, agents_live_run, hypothesis_evaluated_live, cross_domain_sources |
| R5.3-fbe545d1 | 280 | failed | Petrochemical cracker outages affecting ethane and propane demand. | knowledge_library, unstructured_sources, provenance_labels, agents_live_run, hypothesis_evaluated_live, cross_domain_sources |
| R5.3-23aee387 | 281 | failed | Propane export demand interacting with Gulf Coast fractionation constraints. | knowledge_library, unstructured_sources, provenance_labels, agents_live_run, hypothesis_evaluated_live, cross_domain_sources |
| R5.3-d78a74b5 | 282 | failed | Weather-driven power burn changing regional natural gas basis. | knowledge_library, unstructured_sources, provenance_labels, agents_live_run, hypothesis_evaluated_live, cross_domain_sources |
| R5.3-7ae87737 | 283 | failed | Pipeline capacity restrictions amplifying regional supply-demand imbalances. | knowledge_library, unstructured_sources, provenance_labels, agents_live_run, hypothesis_evaluated_live |
| R5.3-76b20e87 | 284 | failed | NGL purity-product spreads changing alongside natural gas and crude oil benchmarks. | knowledge_library, unstructured_sources, provenance_labels, agents_live_run, hypothesis_evaluated_live, cross_domain_sources |
| R5.3-afcfe344 | 285 | failed | Associated gas production changing as crude oil economics shift. | knowledge_library, unstructured_sources, provenance_labels, agents_live_run, hypothesis_evaluated_live, cross_domain_sources |
| R5.3-01b98b4c | 286 | failed | Mont Belvieu NGL price movements interacting with Henry Hub forward curves. | knowledge_library, unstructured_sources, provenance_labels, agents_live_run, hypothesis_evaluated_live, cross_domain_sources |
| R5.3-c438ffef | 288 | failed | The system must distinguish: | knowledge_library, unstructured_sources, provenance_labels, agents_live_run, hypothesis_evaluated_live |
| R5.3-1907fd19 | 289 | failed | Observed market facts. | knowledge_library, unstructured_sources, provenance_labels, agents_live_run, hypothesis_evaluated_live |
| R5.3-d38ce7eb | 290 | failed | Historical analogs. | knowledge_library, unstructured_sources, provenance_labels, agents_live_run, hypothesis_evaluated_live |
| R5.3-f6f5e656 | 291 | failed | Model-generated hypotheses. | knowledge_library, unstructured_sources, provenance_labels, agents_live_run, hypothesis_evaluated_live |
| R5.3-e4ada600 | 292 | failed | Scenario assumptions. | knowledge_library, unstructured_sources, provenance_labels, agents_live_run, hypothesis_evaluated_live |
| R5.3-e41ce236 | 293 | failed | Quantitative estimates. | knowledge_library, unstructured_sources, provenance_labels, agents_live_run, hypothesis_evaluated_live |
| R5.3-222d3d02 | 294 | failed | Verified statistical relationships. | knowledge_library, unstructured_sources, provenance_labels, agents_live_run, hypothesis_evaluated_live |
| R5.3-b9a2bb3c | 296 | failed | Semantic similarity must never be treated as proof of causation. | knowledge_library, unstructured_sources, provenance_labels, agents_live_run, hypothesis_evaluated_live |
| R5.4-59b4b120 | 300 | failed | The system must generate structured hypotheses containing: | hypothesis_memo, hypothesis_evaluated_live |
| R5.4-991a8f1f | 301 | failed | Market relationship. | hypothesis_memo, hypothesis_evaluated_live |
| R5.4-18282658 | 302 | failed | Relevant assets and instruments. | hypothesis_memo, hypothesis_evaluated_live |
| R5.4-13a38a0d | 303 | failed | Supporting historical analogs. | hypothesis_memo, hypothesis_evaluated_live |
| R5.4-f0975322 | 304 | failed | Supporting structured observations. | hypothesis_memo, hypothesis_evaluated_live |
| R5.4-be2b6cda | 305 | failed | Expected direction of impact. | hypothesis_memo, hypothesis_evaluated_live |
| R5.4-86e33f3d | 306 | failed | Estimated magnitude. | hypothesis_memo, hypothesis_evaluated_live |
| R5.4-f6005fb7 | 307 | failed | Expected time horizon. | hypothesis_memo, hypothesis_evaluated_live |
| R5.4-0b624c4a | 308 | failed | Relevant geographic markets. | hypothesis_memo, hypothesis_evaluated_live |
| R5.4-7ea4c9b5 | 309 | failed | Assumptions. | hypothesis_memo, hypothesis_evaluated_live |
| R5.4-7a27c13e | 310 | failed | Contradictory evidence. | hypothesis_memo, hypothesis_evaluated_live |
| R5.4-ac03ec4a | 311 | failed | Confidence and uncertainty. | hypothesis_memo, hypothesis_evaluated_live |
| R5.4-dac6a247 | 312 | failed | Proposed backtest methodology. | hypothesis_memo, hypothesis_evaluated_live |
| R5.5-c478768c | 318 | blocked | Each memo must reference the underlying source observations, vector nodes, model version, analytical assumptio | hypothesis_memo, research_log_live |
| R6-104ed187 | 326 | failed | The system must determine whether cross-domain market relationships produce reproducible predictive advantages | backtest_unit, experiments_recorded, multi_feature_experiments |
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
| R6.5-7486d6cd | 411 | failed | Experiment ID. | leaderboard_versioned, experiments_recorded, promotion_gate |
| R6.5-e534af5f | 412 | failed | Model configuration. | leaderboard_versioned, experiments_recorded, promotion_gate |
| R6.5-9290b747 | 413 | failed | Feature set. | leaderboard_versioned, experiments_recorded, promotion_gate |
| R6.5-47917d73 | 414 | failed | Training period. | leaderboard_versioned, experiments_recorded, promotion_gate |
| R6.5-54fa2594 | 415 | failed | Validation period. | leaderboard_versioned, experiments_recorded, promotion_gate |
| R6.5-0ba87ca8 | 416 | failed | Out-of-sample period. | leaderboard_versioned, experiments_recorded, promotion_gate |
| R6.5-c56c87ac | 417 | failed | PIT data version. | leaderboard_versioned, experiments_recorded, promotion_gate |
| R6.5-6a4bc07f | 418 | failed | Performance metrics. | leaderboard_versioned, experiments_recorded, promotion_gate |
| R6.5-9ac6238e | 419 | failed | Baseline comparison. | leaderboard_versioned, experiments_recorded, promotion_gate |
| R6.5-62edc8cb | 420 | failed | Reproducibility metadata. | leaderboard_versioned, experiments_recorded, promotion_gate |
| R6.5-1327d7c4 | 422 | failed | Only promote a model when it demonstrates a statistically defensible out-of-sample improvement over its baseli | leaderboard_versioned, experiments_recorded, promotion_gate |
| R7.2-75e85344 | 450 | failed | The local FastAPI service must expose: | hub_health, execute_sandbox_tests, knowledge_search_pit, experiment_endpoint |
| R7.2-6df3dff9 | 454 | failed | It must accept: | hub_health, execute_sandbox_tests, knowledge_search_pit, experiment_endpoint |
| R7.2-29f62f6e | 455 | failed | query | hub_health, execute_sandbox_tests, knowledge_search_pit, experiment_endpoint |
| R7.2-8887b5f9 | 456 | failed | as_of_timestamp | hub_health, execute_sandbox_tests, knowledge_search_pit, experiment_endpoint |
| R7.2-63c54804 | 458 | failed | It must provide access to: | hub_health, execute_sandbox_tests, knowledge_search_pit, experiment_endpoint |
| R7.2-cc50cceb | 459 | failed | Structured PIT market data. | hub_health, execute_sandbox_tests, knowledge_search_pit, experiment_endpoint |
| R7.2-04f26655 | 460 | failed | Vector knowledge retrieval. | hub_health, execute_sandbox_tests, knowledge_search_pit, experiment_endpoint |
| R7.2-c6c83a38 | 461 | failed | Cross-domain synthesis. | hub_health, execute_sandbox_tests, knowledge_search_pit, experiment_endpoint |
| R7.2-4134c254 | 462 | failed | Scenario analysis. | hub_health, execute_sandbox_tests, knowledge_search_pit, experiment_endpoint |
| R7.2-f950bef5 | 463 | failed | Historical analog retrieval. | hub_health, execute_sandbox_tests, knowledge_search_pit, experiment_endpoint |
| R7.2-e8d5effb | 464 | failed | SQL execution. | hub_health, execute_sandbox_tests, knowledge_search_pit, experiment_endpoint |
| R7.2-b37d8292 | 465 | failed | Backtest execution. | hub_health, execute_sandbox_tests, knowledge_search_pit, experiment_endpoint |
| R7.2-2c83d004 | 466 | failed | Experiment status. | hub_health, execute_sandbox_tests, knowledge_search_pit, experiment_endpoint |
| R7.2-67c26786 | 467 | failed | Alpha research records. | hub_health, execute_sandbox_tests, knowledge_search_pit, experiment_endpoint |
| R7.2-e2bcc67c | 468 | failed | Audit history. | hub_health, execute_sandbox_tests, knowledge_search_pit, experiment_endpoint |
| R7.5-a91cd2e9 | 512 | failed | Original command. | audit_gists, worker_gateway_e2e |
| R7.5-40eaa3f5 | 513 | failed | Request timestamp. | audit_gists, worker_gateway_e2e |
| R7.5-92e67c77 | 514 | failed | PIT cutoff. | audit_gists, worker_gateway_e2e |
| R7.5-1e4e243f | 515 | failed | Retrieved market observations. | audit_gists, worker_gateway_e2e |
| R7.5-0b23f89c | 516 | failed | Retrieved vector nodes. | audit_gists, worker_gateway_e2e |
| R7.5-037320b0 | 517 | failed | Generated SQL. | audit_gists, worker_gateway_e2e |
| R7.5-559b279e | 518 | failed | Executed results. | audit_gists, worker_gateway_e2e |
| R7.5-a6215bca | 519 | failed | Scenario estimates. | audit_gists, worker_gateway_e2e |
| R7.5-0b7265d4 | 520 | failed | Market thesis. | audit_gists, worker_gateway_e2e |
| R7.5-62f4a68f | 521 | failed | Model identity. | audit_gists, worker_gateway_e2e |
| R7.5-cd216305 | 522 | failed | Execution status. | audit_gists, worker_gateway_e2e |
| R7.5-b77ca20d | 523 | failed | Relevant provenance. | audit_gists, worker_gateway_e2e |
| R7.5-205221b1 | 525 | failed | The alerting system must notify the user of material market events, failed collectors, data-quality incidents, | alert_delivery |
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
| R9-a15d2463 | 557 | failed | Preserve revisions rather than overwriting prior vintages. | pit_tests, knowledge_search_pit |
| R9-3a1be834 | 558 | failed | Enforce available_timestamp <= decision_timestamp. | pit_tests, knowledge_search_pit |
| R9-a1c2e449 | 559 | failed | Prevent look-ahead bias across every data source and feature. | pit_tests, knowledge_search_pit, raw_payloads_verified, schema_16_columns, gatekeeper |
| R9-b83173bd | 560 | failed | Apply identical PIT restrictions to SQL, vector retrieval, feature generation, and backtesting. | pit_tests, knowledge_search_pit, execute_sandbox_tests, selfheal_unit, provenance_labels |
| R9-d2990544 | 563 | failed | Identify every source. | raw_payloads_verified, schema_16_columns, gatekeeper |
| R9-2ae68d46 | 564 | failed | Preserve original source payloads. | raw_payloads_verified, schema_16_columns, gatekeeper |
| R9-cd701f5d | 565 | failed | Record extraction timestamps. | raw_payloads_verified, schema_16_columns, gatekeeper |
| R9-8f90ea08 | 566 | failed | Record extraction and transformation versions. | raw_payloads_verified, schema_16_columns, gatekeeper |
| R9-2a6392bf | 567 | failed | Preserve units and geographic scope. | raw_payloads_verified, schema_16_columns, gatekeeper |
| R9-8843da81 | 568 | failed | Validate observations before production ingestion. | raw_payloads_verified, schema_16_columns, gatekeeper |
| R9-68a73ee7 | 571 | failed | Treat LLM output as untrusted until validated. | raw_payloads_verified, schema_16_columns, gatekeeper, execute_sandbox_tests, selfheal_unit, provenance_labels |
| R9-89307192 | 578 | failed | Separate training, validation, and out-of-sample periods. | backtest_unit, promotion_gate, experiments_recorded |
| R9-466b1aff | 579 | failed | Account for transaction costs and execution constraints. | backtest_unit, promotion_gate, experiments_recorded |
| R9-75a5cec9 | 580 | failed | Test performance across different market regimes. | backtest_unit, promotion_gate, experiments_recorded |
| R9-ee48ca9a | 581 | failed | Compare against explicit baselines. | backtest_unit, promotion_gate, experiments_recorded |
| R9-ab790e63 | 582 | failed | Control for multiple testing and feature-selection bias. | backtest_unit, promotion_gate, experiments_recorded |
| R9-985a406c | 583 | failed | Require reproducible results before promoting an alpha hypothesis. | backtest_unit, promotion_gate, experiments_recorded |
| R9-8d62a603 | 586 | failed | Preserve Cloudflare Access authentication. | access_protects_hub, env_locked, execute_sandbox_tests, webhook_recovery |
| R9-319a765e | 587 | failed | Keep service credentials outside source control. | raw_payloads_verified, schema_16_columns, gatekeeper, access_protects_hub, env_locked, execute_sandbox_tests, webhook_recovery |
| R9-e22e92b1 | 588 | failed | Restrict local database execution to read-only operations where appropriate. | access_protects_hub, env_locked, execute_sandbox_tests, webhook_recovery |
| R9-6ec4b921 | 589 | failed | Authenticate remote jobs and webhooks. | access_protects_hub, env_locked, execute_sandbox_tests, webhook_recovery |
| R9-7dfd4af1 | 590 | failed | Require authorization before merging and deploying repaired code. | access_protects_hub, env_locked, execute_sandbox_tests, webhook_recovery |
| R9-a93f59cd | 591 | failed | Preserve execution and incident audit records. | access_protects_hub, env_locked, execute_sandbox_tests, webhook_recovery |
| R10-cf8a2b74 | 595 | blocked | The completed platform must be able to: | roster_all_collected, worker_gateway_e2e, backtest_unit |
| R10-d712f6b5 | 597 | blocked | Collect and maintain data from 81 or more specialized market-data agents. | roster_all_collected, worker_gateway_e2e, backtest_unit |
| R10-ba057802 | 598 | failed | Retrieve historical market observations with exact point-in-time availability. | pit_tests, raw_payloads_verified, roster_all_collected, worker_gateway_e2e, backtest_unit |
| R10-1a94b50e | 599 | failed | Preserve original source material and every relevant data vintage. | pit_tests, raw_payloads_verified, roster_all_collected, worker_gateway_e2e, backtest_unit |
| R10-13e066a4 | 600 | failed | Detect and recover from source and parser failures. | selfheal_unit, selfheal_pr_live, webhook_recovery, roster_all_collected, worker_gateway_e2e, backtest_unit |
| R10-88e4ed77 | 601 | failed | Generate tested scraper repairs and GitHub pull requests. | selfheal_unit, selfheal_pr_live, webhook_recovery, roster_all_collected, worker_gateway_e2e, backtest_unit |
| R10-4c202fb8 | 602 | failed | Maintain a searchable cross-domain vector knowledge library. | knowledge_library, cross_domain_sources, hypothesis_memo, roster_all_collected, worker_gateway_e2e, backtest_unit |
| R10-325030ce | 603 | failed | Identify historical analogs across natural gas, NGL, weather, infrastructure, and financial markets. | knowledge_library, cross_domain_sources, hypothesis_memo, roster_all_collected, worker_gateway_e2e, backtest_unit |
| R10-513986e3 | 604 | failed | Generate structured, testable market-alpha hypotheses. | knowledge_library, cross_domain_sources, hypothesis_memo, roster_all_collected, worker_gateway_e2e, backtest_unit |
| R10-973553ea | 605 | failed | Execute large-scale PIT walk-forward backtesting experiments. | backtest_unit, leaderboard_versioned, queue_dispatch, roster_all_collected, worker_gateway_e2e |
| R10-3dba0e7d | 606 | failed | Rank competing models using out-of-sample performance. | backtest_unit, leaderboard_versioned, queue_dispatch, roster_all_collected, worker_gateway_e2e |
| R10-466788d5 | 607 | failed | Maintain reproducible experiment records and model leaderboards. | backtest_unit, leaderboard_versioned, queue_dispatch, roster_all_collected, worker_gateway_e2e |
| R10-dd8d6fa7 | 608 | failed | Accept authenticated remote natural-language commands. | worker_gateway_e2e, alert_delivery, collector_schedule, roster_all_collected, backtest_unit |
| R10-0cd3fea1 | 609 | failed | Execute quantitative scenario analyses on the local workstation. | worker_gateway_e2e, alert_delivery, collector_schedule, roster_all_collected, backtest_unit |
| R10-7b0e4bd5 | 610 | failed | Produce auditable market research and alpha alerts. | worker_gateway_e2e, alert_delivery, collector_schedule, roster_all_collected, backtest_unit |
| R10-182dd91b | 611 | failed | Continuously improve its analytical capabilities through validated data, research, and backtesting. | backtest_unit, leaderboard_versioned, queue_dispatch, worker_gateway_e2e, alert_delivery, collector_schedule, roster_all_collected |
| R11-049dcf38 | 619 | blocked | Your responsibility is to backward-engineer the complete execution path from the ultimate objective to the req | full_test_suite, worker_gateway_e2e, architecture_doc, roster_all_collected |
| R11-1de351b2 | 629 | blocked | Identify existing agents, scripts, tests, scheduled jobs, and services. | full_test_suite, worker_gateway_e2e, architecture_doc, roster_all_collected |
| R11-2d6da86e | 642 | blocked | External data sources and access requirements. | full_test_suite, worker_gateway_e2e, architecture_doc, roster_all_collected |
| R12.1-f79a50dc | 667 | failed | Both the web interface and the terminal dashboard must follow a clean, sophisticated, high-contrast monochrome | web_ui_browser, ngl_term |
| R12.1-569c27e8 | 669 | failed | Before designing or implementing any UI, map, chart, or terminal layout, Claude MUST inspect and base the visu | web_ui_browser, ngl_term |
| R12.1-2a65d69c | 671 | failed | /home/joey/Projects/henry_hub_atomic_agents/artifacts/Real-time global maritime traffic visualization image ex | web_ui_browser, ngl_term |
| R12.1-9bd48e8f | 672 | failed | /home/joey/Projects/henry_hub_atomic_agents/artifacts/NGL Henry Hub Visual Intelligence | web_ui_browser, ngl_term |
| R12.1-0441f203 | 673 | failed | /home/joey/Projects/henry_hub_atomic_agents/artifacts/NGL pipeline and meter map view.png | web_ui_browser, ngl_term |
| R12.1-4388e823 | 675 | failed | Additionally, Claude MUST utilize geospatial tooling and visualization libraries from https://github.com/sshua | web_ui_browser, ngl_term |
| R12.3-b24434ad | 689 | failed | As atomic agents discover new market developments (pipeline critical notices, force majeure, EIA/NOAA reports, | knowledge_library, knowledge_search_pit, web_ui_browser, knowledge_explorer, knowledge_explorer_browser, agents_share_knowledge |
| R12.3-f23bf6e2 | 690 | failed | Render an interactive monochrome fine-line node-and-edge knowledge graph explorer in the web UI with PIT-filte | knowledge_library, knowledge_search_pit, web_ui_browser, knowledge_explorer, knowledge_explorer_browser, agents_share_knowledge |
| R12.4-cdd9c4bc | 694 | failed | Top Hero Focus Panel: The uppermost, most prominent visual on the interface MUST display Seasonal Patterns and | state_schema_contract, web_ui_browser |
| R12.4-61440bd5 | 695 | failed | Dynamic Product & Timeframe Tracking: | state_schema_contract, web_ui_browser |
| R12.4-97513311 | 696 | failed | Dynamically detect and track whichever NGL or gas product is currently being calculated by the main pricing en | state_schema_contract, web_ui_browser, roster_all_collected |
| R12.4-c6890b6e | 697 | failed | Support selectable trading timeframes: Intraday, Seasonal Swing, and Multi-Year Hedging. | state_schema_contract, web_ui_browser |
| R12.4-c53cea8c | 698 | failed | Live Pricing Decomposition & Source Availability: | state_schema_contract, web_ui_browser |
| R12.4-b78c405d | 699 | failed | Visually display the calculated price, historical price fluctuations, and the production/fundamental elements  | state_schema_contract, web_ui_browser, roster_all_collected |
| R12.4-79c1b0ff | 700 | failed | Display a Source Availability Transparency panel listing every contributing agent, source_id, available_timest | state_schema_contract, web_ui_browser |
| R12.5-0f7de509 | 704 | failed | NGL-to-WTI Percentage Ratio Charts: Propane, normal butane, and natural gasoline plotted as a percentage of WT | indicators, web_ui_browser, roster_all_collected |
| R12.5-66afc426 | 705 | failed | Mont Belvieu vs. Conway Hub Spreads: Side-by-side hub prices and differential spread tracking Gulf Coast vs. M | indicators, web_ui_browser, roster_all_collected |
| R12.5-42a3ffd8 | 706 | failed | The "Frac Spread" Curve: Ethane ($/MMBtu) vs. Henry Hub natural gas ($/MMBtu), visually highlighting ethane re | indicators, web_ui_browser, roster_all_collected |
| R12.5-f4ab8294 | 707 | failed | Forward Curve Contango and Backwardation: Futures term structure slope across delivery months with automatic r | indicators, web_ui_browser, roster_all_collected |
| R12.5-242c56a9 | 708 | failed | Multi-Year Seasonal Overlay Bands: Calendar-aligned multi-year historical price lines and min/max/average band | indicators, web_ui_browser |
| R12.6-3737fe92 | 712 | failed | Symmetrical and Ascending Triangles: Converging swing-high/swing-low trendlines and breakout trigger levels. | indicators, web_ui_browser |
| R12.6-cdf6ceaf | 713 | failed | Bollinger Band Squeezes: 20-period SMA ± 2σ volatility bands with low-bandwidth squeeze detection shading. | indicators, web_ui_browser |
| R12.6-9e40e670 | 714 | failed | 200-Day Moving Average Crossovers: 50-day and 200-day moving average overlays with Golden/Death cross markers. | indicators, web_ui_browser |
| R12.6-5c6339ea | 715 | failed | RSI and MACD Divergences: Synchronized lower momentum oscillator panes (RSI-14 and MACD 12/26/9) with automate | indicators, web_ui_browser |
| R12.6-1ec5f656 | 716 | failed | Fibonacci Retracement Levels: Horizontal 23.6%, 38.2%, 50.0%, 61.8%, and 78.6% grids anchored to trailing seas | indicators, web_ui_browser |
| R12.7-31088a85 | 724 | blocked | Live Regional Flows & Active Pipeline Alerts: Real-time border/LNG/interstate meter flows, capacity constraint | ngl_term, roster_all_collected |

## CLAUDE.md directive (requirement -> implementation -> checks)

| Requirement | CLAUDE.md line | Implementation | Checks | Status |
|---|---|---|---|---|
| Ollama: agent reasoning and task assistance | 21 | agents/workers.py SynthesisAgent, RepairAgent; agents/llm.py | agent_unit, ollama_live_integration, agents_live_run | failed |
| Ollama: structured extraction, classification, normalization, validation | 22 | agents/workers.py NoticeAnalystAgent (schema + source-label/severity/location checks), DiagnosticsAgent | agent_unit, ollama_live_integration, agents_live_run | failed |
| Ollama: anomaly detection and data-quality investigation | 23 | agents/workers.py AnomalyAgent, DataQualityAgent | agent_unit, agents_live_run | failed |
| Ollama: agent-to-agent knowledge exchange and synthesis | 24 | agents/memory.py publish/consume + findings; SynthesisAgent | agent_unit, agents_share_knowledge, agents_live_run | failed |
| Ollama: research synthesis grounded in retrieved source data | 25 | SynthesisAgent: PIT observations + semantic retrieval, numbers_grounded, evidence/observation citation checks | agent_unit, agents_live_run, hypothesis_evaluated_live | failed |
| Ollama: embedding generation and semantic retrieval | 26 | agents/llm.py embed; agents/memory.py search; kb_ingest.search | ollama_live_integration, knowledge_search_pit, agents_share_knowledge | failed |
| Ollama: error diagnosis and bounded self-healing assistance | 27 | DiagnosticsAgent -> incident -> RepairAgent (dry-run selfheal_pipeline.repair / code suggestion, never applied) | agent_unit, selfheal_unit, selfheal_live_ollama | passed |
| Model calls: explicit configuration, timeouts, error handling, logging, deterministic fallback | 29 | agents/llm.py CONFIG/status/_post/json(fallback, validate)/llm_calls | agent_unit, ollama_live_integration | passed |
| Not operational merely because the daemon responds | 29 | agents/llm.py status() requires the configured models; live tests | ollama_live_integration, agents_live_run | failed |
| Library: ingestion of documents, source material, agent findings, validated intelligence | 35 | kb_ingest.build_objects/ingest; agents/memory.add_finding | knowledge_library, agents_share_knowledge | failed |
| Library: text extraction, chunking, metadata, source attribution, provenance | 36 | kb_ingest.chunk_text + part_of edges; kb_nodes metadata | kb_chunking, knowledge_library, provenance_labels | failed |
| Library: vector embeddings and persistent vector indexing | 37 | kb_nodes.embedding + Chroma henry_hub_alpha_graph | knowledge_library, agents_share_knowledge, hub_health | failed |
| Library: semantic search and retrieval by agents and research workflows | 38 | agents/memory.search; /execute retrieve_vector_nodes; /api/knowledge-search | knowledge_search_pit, agents_live_run, worker_gateway_e2e | failed |
| Library: relationships between documents, concepts, series, agents, findings, features | 39 | kb_edges types previous_in_series, same_period, builds_on, semantic_neighbor, part_of, evidence_for, evaluated_by | knowledge_library, agents_share_knowledge, hypothesis_evaluated_live | failed |
| Library: graphical interface for exploring, searching, inspecting, navigating | 40 | web/knowledge.html + web/knowledge.js at /knowledge; /api/knowledge-graph, /api/knowledge-node, /api/agents/activity | knowledge_explorer, knowledge_explorer_browser, web_ui_browser | failed |
| Library: persistent across runs, updates, deduplication, traceable sources | 41 | doc_hash idempotent ingest; finding content-hash ids; raw_payloads | knowledge_library, agent_unit, raw_payloads_verified | failed |
| Library: Ollama for embedding and synthesis | 42 | nomic-embed-text embeddings; qwen3:4b synthesis | ollama_live_integration, agents_live_run | failed |
| Agents use shared intelligence and knowledge infrastructure (verified execution) | 47 | agents/ via /agents/run and the daily timer | agents_live_run, agents_share_knowledge, agents_scheduled | failed |
| Point-in-time correctness, no look-ahead in features, retrieval, inputs, training, backtesting | 50 | markets_engine.load_series, kb_ingest.search, memory.search assertions, observations(), evaluate(created<=as_of), backtest.py | pit_tests, knowledge_search_pit, agent_unit, backtest_unit | failed |
| End-to-end: acquisition -> ... -> agent collaboration -> Ollama synthesis -> backtesting -> persistent knowledge | 53 | collectors -> pit_market_data -> kb_ingest -> agents -> experiments -> kb findings/memos | collectors_run, knowledge_library, agents_live_run, hypothesis_evaluated_live, experiments_recorded | failed |
| Acceptance 6: point-in-time and no-look-ahead tests pass | 76 | tests/test_backtest.py, test_ingest.py, test_agents.py, ... | pit_tests, agent_unit | passed |
| Acceptance 7: relevant tests pass | 77 | pytest suite | full_test_suite | passed |
