 # ULTIMATE GOAL: NGL AND HENRY HUB MARKET ALPHA THROUGH CROSS-DOMAIN HYPER-SYNTHESIS AND POINT-IN-TIME WALK-FORWARD BACKTESTING

## 1. Governing Mission and Ultimate Objective

The ultimate goal of this project is to build a fully integrated, autonomous quantitative natural gas and Natural Gas Liquids (NGL) market intelligence platform capable of deriving actionable market alpha through **Cross-Domain Hyper-Synthesis and Point-in-Time (PIT) Walk-Forward Backtesting**.

The system must identify, extract, normalize, preserve, correlate, analyze, and backtest relationships across the North American natural gas and NGL markets. It must connect physical market fundamentals, pipeline infrastructure, weather, storage, production, LNG exports, petrochemical demand, NGL fractionation, regional price differentials, and financial market data.

The system must identify relationships that conventional single-domain analysis misses, generate quantitative trading hypotheses, test those hypotheses against historically available information, and measure whether they produce statistically and economically meaningful out-of-sample predictive advantages.

The project must integrate five complementary production-grade architectures into one connected system.

**The five architectures are:**

1. Edge-to-Core Distributed Scraping and Extraction Mesh.
2. Self-Healing Scraper and Automated Pull-Request Pipeline.
3. Cross-Domain Semantic Friction Vector Engine.
4. Serverless Walk-Forward Backtest Orchestrator.
5. Remote Zero-Trust Command and Alpha Alerting Hub.

These are not five alternative projects. They are five interconnected components of one quantitative intelligence platform.

## 2. Required Local Infrastructure and Technology Stack

The implementation must use the existing local workstation and infrastructure wherever practical.

**Local computing environment**
- Operating system: Linux Mint.
- Workstation: `joey-dell`.
- GPU: Intel Arc integrated GPU.
- Local inference: Ollama.
- Primary LLM: `qwen3:4b`.
- Embedding model: `nomic-embed-text`.
- Python-based orchestration, extraction, analysis, and backtesting.

**Remote infrastructure**
- Cloudflare Workers for edge execution, request authentication, orchestration, and job dispatch.
- Cloudflare Tunnel (`cloudflared`) for secure connectivity to the local workstation.
- Cloudflare Access service tokens for machine-to-machine authentication.
- Cloudflare Queues for asynchronous job distribution where appropriate.

**Data and knowledge infrastructure**
- SQLite `henry_hub_pit.db` for structured point-in-time market observations.
- ChromaDB or another suitable persistent vector database for semantic retrieval.
- Original HTML, CSV, JSON, XML, PDF, and other source payloads preserved for reproducibility.
- GitHub private repositories for version-controlled code, historical data snapshots, experiment records, and research artifacts.

**Development and audit infrastructure**
- GitHub CLI (`gh`) for commits, pull requests, issues, discussions, and private Gist creation.
- Python orchestrators for scraping, extraction, validation, ingestion, recovery, and backtesting.
- FastAPI for local execution services.
- `cloudflared` routing `quant.joeysvault.app` to the local Quant Hub on port `8090`.

The system must preserve existing working infrastructure and credentials. Do not replace functional components unnecessarily or introduce competing implementations without first establishing the actual live architecture.

## 3. Architecture 1: Edge-to-Core Distributed Scraping and Extraction Mesh

### Primary objective

Build a distributed collection and extraction infrastructure covering the project's 81 atomic market-data agents.

The system must collect market information from geographically and operationally diverse sources without relying exclusively on requests originating from the local workstation.

### 3.1 Edge collection

Use Cloudflare Workers to execute lightweight, scheduled source-fetching tasks.

Each collector must:
- Retrieve its assigned source data.
- Support the relevant source protocol, including HTML, CSV, JSON, XML, and downloadable documents.
- Record HTTP status, response headers, retrieval time, and source URL.
- Preserve the original response payload.
- Detect missing, malformed, stale, or unexpectedly changed source content.
- Apply source-specific request limits and retry policies.
- Avoid violating source terms, access restrictions, or published rate limits.

The intended deployment covers 81 atomic data collectors. The implementation may group collectors into shared Worker deployments where appropriate; each agent must retain an independent identity, schedule, validation contract, and execution record.

Cloudflare edge execution must not be assumed to eliminate source rate limits. Collection scheduling must respect source-specific restrictions.

### 3.2 Secure data transport

Each edge collector must transmit its retrieved payload and collection metadata to the local ingestion gateway through the Cloudflare-protected ingress architecture.

Required components:
- Cloudflare Worker.
- HTTPS transport.
- Cloudflare Access service-token authentication.
- `CF-Access-Client-Id`.
- `CF-Access-Client-Secret`.
- Cloudflare Tunnel.
- Local authenticated ingestion endpoint.

The local workstation must not expose an unauthenticated public ingestion port.

### 3.3 Local extraction

The local Python extraction orchestrator must receive the original payload and invoke Ollama when source-specific parsing requires language-model assistance.

Use `qwen3:4b` to convert irregular source material into validated structured observations.

The initial canonical observation fields must include:

- `agent_id`
- `target_timestamp`
- `available_timestamp`
- `value`

The production data contract must extend these four fields with:
- `source_id`
- `source_url`
- `retrieved_timestamp`
- `published_timestamp`
- `revision_timestamp`
- `unit`
- `geographic_scope`
- `series_id`
- `raw_payload_hash`
- `extraction_version`
- `quality_status`
- `provenance`

A four-column representation alone is insufficient for production-grade historical market analysis.

### 3.4 Historical data preservation

Preserve every source payload and every accepted observation vintage.

Never overwrite an earlier historical observation when a source revises its data.

The system must support reconstruction of exactly what the platform knew at any historical decision timestamp.

### 3.5 GitHub data audit

Use GitHub private repositories to version daily structured data snapshots, source manifests, extraction metadata, and ingestion records.

The Git history must preserve historical revisions and support reproducible retrieval. Enforce repository permissions and branch protections; do not assume ordinary Git history is intrinsically immutable.

## 4. Architecture 2: Self-Healing Scraper and Automated Pull-Request Pipeline

### Primary objective

Create an automated recovery system that detects broken source collectors, diagnoses extraction failures, proposes repairs, and submits tested code changes for review.

Pipeline Electronic Bulletin Boards (EBBs), government websites, and commercial data providers can change their layouts and delivery formats. These changes must not silently create permanent data gaps.

### 4.1 Failure detection

The Python orchestration system must monitor all 81 atomic agents.

Detect:
- HTTP 404 and other unexpected status codes.
- Connection failures and timeouts.
- Changed HTML or DOM structures.
- Missing tables and columns.
- Unexpected CSV headers.
- Invalid dates, timestamps, and numerical values.
- Unit inconsistencies.
- Duplicate observations.
- Missing expected publications.
- Failed schema validation.
- Unexpected source revisions.

Each failure must produce a structured diagnostic record.

### 4.2 Source capture and diagnosis

When an agent fails:
1. Preserve the original response or failure payload.
2. Capture the relevant HTML DOM or source document.
3. Preserve the previous working parser.
4. Capture the failed extraction output.
5. Record the expected schema and actual schema.
6. Record the failure timestamp and source identity.

### 4.3 LLM-assisted parser repair

Send the failed source material, existing parser, validation rules, and diagnostic output to local Ollama.

Use `qwen3:4b` to propose:
- Updated CSS selectors.
- Updated XPath expressions.
- Revised regular expressions.
- Modified table extraction logic.
- Revised CSV or JSON field mappings.
- Necessary parser compatibility changes.

The LLM must generate a proposed patch, not directly overwrite production code.

### 4.4 Automated testing and GitHub pull requests

The repair pipeline must:
1. Create an isolated working branch.
2. Apply the proposed patch.
3. Run unit tests against preserved source fixtures.
4. Run schema validation.
5. Compare extracted values against known expected results.
6. Check timestamp and PIT handling.
7. Generate a repair report.
8. Open a GitHub pull request using `gh pr create`.

The repository target is:

`jmpsu/henry_hub_atomic_agents`

Production deployment must require successful tests and an authorized merge. Do not allow an LLM to approve and deploy its own unverified code changes.

### 4.5 Automated recovery

After an authorized merge, a GitHub webhook can notify a Cloudflare Worker.

The Worker must authenticate the event and enqueue a deployment or execution request.

The local orchestrator must retrieve the approved change, verify its identity, and rerun the affected collector through the secure Cloudflare Tunnel architecture.

## 5. Architecture 3: Cross-Domain Semantic Friction Vector Engine

### Primary objective

Build a persistent cross-domain knowledge library that connects unstructured market events with structured market observations and financial outcomes.

The system must discover relationships between seemingly unrelated market developments that can affect NGL and Henry Hub pricing.

### 5.1 Knowledge ingestion

Ingest and index historical and current information from:

- Interstate pipeline critical notices.
- Pipeline force majeure declarations.
- Pipeline maintenance and capacity restrictions.
- FERC filings and regulatory announcements.
- EIA natural gas storage reports.
- EIA production and consumption data.
- NOAA weather forecasts and discussions.
- GFS and ECMWF weather model outputs.
- LNG terminal operational notices.
- LNG feedgas and export activity.
- NGL production and fractionation data.
- Mont Belvieu NGL pricing.
- Ethane, propane, normal butane, isobutane, and natural gasoline markets.
- Petrochemical cracker outages and operating rates.
- Refinery operating conditions.
- Natural gas power burn.
- Coal-to-gas switching.
- Regional pipeline basis and forward curves.
- Relevant financial and commodity-market publications.

Every indexed document must preserve its source, publication timestamp, availability timestamp, valid period, and historical revision information.

### 5.2 Vector embedding and retrieval

Use local Ollama embeddings through:

`/api/embeddings`

Use `nomic-embed-text` to convert documents, events, and historical research into vector representations.

Store embeddings and metadata in a persistent vector knowledge library using ChromaDB, Qdrant, or another suitable vector database.

The system must support:
- Semantic similarity retrieval.
- Historical event retrieval.
- Cross-domain event relationships.
- Time-filtered retrieval.
- Geographic filtering.
- Agent and source filtering.
- Parent-child knowledge relationships.
- Provenance tracking.
- Historical reconstruction of knowledge available at a given timestamp.

### 5.3 Cross-domain hyper-synthesis

Use `qwen3:4b` to synthesize retrieved information alongside structured numerical observations.

Examples of required analytical relationships include:

- Permian pipeline outages during high-HDD weather conditions.
- LNG feedgas disruptions interacting with South Central storage inventories.
- Ethane rejection changing the natural gas supply balance.
- Petrochemical cracker outages affecting ethane and propane demand.
- Propane export demand interacting with Gulf Coast fractionation constraints.
- Weather-driven power burn changing regional natural gas basis.
- Pipeline capacity restrictions amplifying regional supply-demand imbalances.
- NGL purity-product spreads changing alongside natural gas and crude oil benchmarks.
- Associated gas production changing as crude oil economics shift.
- Mont Belvieu NGL price movements interacting with Henry Hub forward curves.

The system must distinguish:
- Observed market facts.
- Historical analogs.
- Model-generated hypotheses.
- Scenario assumptions.
- Quantitative estimates.
- Verified statistical relationships.

Semantic similarity must never be treated as proof of causation.

### 5.4 Alpha hypothesis generation

The system must generate structured hypotheses containing:
- Market relationship.
- Relevant assets and instruments.
- Supporting historical analogs.
- Supporting structured observations.
- Expected direction of impact.
- Estimated magnitude.
- Expected time horizon.
- Relevant geographic markets.
- Assumptions.
- Contradictory evidence.
- Confidence and uncertainty.
- Proposed backtest methodology.

### 5.5 Research logging

Use `gh issue create` or GitHub Discussions to publish timestamped alpha research memos.

Each memo must reference the underlying source observations, vector nodes, model version, analytical assumptions, and backtest results.

## 6. Architecture 4: Serverless Walk-Forward Backtest Orchestrator

### Primary objective

Build an experiment orchestration system capable of evaluating thousands of quantitative model configurations without exhausting the local workstation's approximately 15 GiB RAM.

The system must determine whether cross-domain market relationships produce reproducible predictive advantages outside the training period.

### 6.1 Experiment orchestration

Use Cloudflare Workers and Cloudflare Queues to coordinate experiment dispatch.

Experiments must support parameter variations involving:
- Historical lag windows.
- Weather forecast model selection.
- GFS versus ECMWF weighting.
- HDD and CDD sensitivity.
- Production changes.
- Storage deviations.
- Pipeline flow disruptions.
- LNG feedgas changes.
- NGL production and fractionation.
- Ethane rejection.
- Propane exports.
- Petrochemical demand.
- Regional basis relationships.
- Henry Hub forward curves.
- Cross-domain vector-derived features.

The Cloudflare infrastructure coordinates jobs; local compute performs the actual quantitative simulations.

### 6.2 Local computation

A local Python worker must retrieve authenticated experiment jobs through the Cloudflare infrastructure.

The worker executes PIT simulations against the structured historical database.

Use memory-efficient batching, incremental computation, and persistent experiment results.

The system must not require thousands of simultaneous in-memory datasets.

### 6.3 PIT walk-forward methodology

Every backtest must enforce historical information availability.

The critical condition is:

`available_timestamp <= decision_timestamp`

The system must additionally distinguish:
- Observation valid time.
- Source publication time.
- System retrieval time.
- Historical revision time.
- Model decision time.
- Forecast target time.

At every historical decision point, the model may access only information available by that point.

The backtesting engine must preserve historical data vintages and prevent future revisions from leaking into earlier simulations.

Use rolling or expanding training windows with strictly separated training, validation, and test periods.

### 6.4 Performance evaluation

Evaluate models using:
- Out-of-sample RMSE.
- MAE.
- Directional accuracy.
- Directional hit rate.
- Prediction bias.
- Forecast calibration.
- Performance by market regime.
- Performance by geographic region.
- Performance by instrument.
- Trading returns where a valid execution strategy exists.
- Transaction costs.
- Slippage.
- Liquidity constraints.
- Drawdown.
- Risk-adjusted returns.

Distinguish predictive accuracy from trading profitability.

A model that predicts price direction accurately does not automatically produce a profitable trading strategy.

### 6.5 Experiment leaderboard

Record every experiment, including failed experiments.

Maintain a version-controlled `LEADERBOARD.md` containing:
- Experiment ID.
- Model configuration.
- Feature set.
- Training period.
- Validation period.
- Out-of-sample period.
- PIT data version.
- Performance metrics.
- Baseline comparison.
- Reproducibility metadata.

Only promote a model when it demonstrates a statistically defensible out-of-sample improvement over its baseline.

Use `gh` to commit validated experiment results and model artifacts.

## 7. Architecture 5: Remote Zero-Trust Command and Alpha Alerting Hub

### Primary objective

Provide secure remote control of the entire local quantitative research environment through a mobile client, external API, or authenticated trading application.

The remote interface must expose the platform's capabilities without exposing local services directly to the public internet.

### 7.1 Cloudflare Worker gateway

The existing Worker architecture must:
- Accept authenticated POST requests.
- Validate `Authorization: Bearer <MOBILE_COMMAND_SECRET>`.
- Reject unauthorized requests.
- Validate payload size and structure.
- Inject Cloudflare Access service-token headers.
- Forward requests to the protected Quant Hub endpoint.
- Preserve appropriate response status codes.
- Apply request limits and execution controls.

The gateway must use the existing Cloudflare Worker and Access infrastructure where possible.

### 7.2 Local execution server

The local FastAPI service must expose:

`POST /execute`

It must accept:
- `query`
- `as_of_timestamp`

It must provide access to:
- Structured PIT market data.
- Vector knowledge retrieval.
- Cross-domain synthesis.
- Scenario analysis.
- Historical analog retrieval.
- SQL execution.
- Backtest execution.
- Experiment status.
- Alpha research records.
- Audit history.

### 7.3 Quantitative scenario execution

Example remote command:

"Run a PIT stress test on Sabine Pass feedgas dropping 1.5 Bcf/d."

The execution pipeline must:
1. Authenticate the request.
2. Validate the requested historical cutoff.
3. Retrieve eligible market observations.
4. Retrieve relevant historical vector knowledge.
5. Identify relevant market-data agents.
6. Construct a structured analytical context.
7. Invoke local Ollama.
8. Generate validated structured output.
9. Execute only approved read-only SQL.
10. Calculate the scenario's estimated supply-demand impact.
11. Generate a concise market thesis.
12. Preserve the complete execution record.
13. Create a new vector knowledge node with appropriate provenance.
14. Return the result through the authenticated gateway.

### 7.4 Required API output

Every successful scenario response must include:

1. `sql_query`: Validated read-only SQL enforcing the PIT cutoff.
2. `scenario_delta_bcf`: Floating-point estimated supply-demand balance impact in Bcf/d.
3. `alpha_thesis`: Concise two-sentence market impact explanation.
4. `as_of_timestamp`: Historical information cutoff.
5. `db_rows`: Retrieved structured market observations.
6. `linked_parent_nodes`: Relevant previously retrieved knowledge nodes.
7. `new_vector_node_id`: Newly stored knowledge node.
8. `audit_gist_url`: Private GitHub Gist reference where successfully created.
9. `sql_source`: Whether the query came from validated model output or deterministic fallback.
10. `data_quality`: Relevant data availability and validation status.

The API must explicitly distinguish observed data from estimates and synthetic scenarios.

### 7.5 Audit and alerting

Use the local GitHub CLI to create private timestamped Gists containing:
- Original command.
- Request timestamp.
- PIT cutoff.
- Retrieved market observations.
- Retrieved vector nodes.
- Generated SQL.
- Executed results.
- Scenario estimates.
- Market thesis.
- Model identity.
- Execution status.
- Relevant provenance.

The alerting system must notify the user of material market events, failed collectors, data-quality incidents, completed backtests, and newly validated alpha hypotheses.

## 8. Cross-Architecture Integration

The five architectures must operate as a connected pipeline.

The complete operational flow is:

1. Cloudflare Workers retrieve source material through scheduled edge collectors.
2. Secure ingress delivers source payloads to the local extraction infrastructure.
3. The 81 atomic agents extract, normalize, and validate market observations.
4. The ingestion system preserves original payloads and historical vintages.
5. SQLite stores structured PIT market observations.
6. Ollama embeddings index relevant source documents and market events.
7. The vector engine retrieves historical cross-domain analogs.
8. Ollama synthesizes structured observations and unstructured market information.
9. The hypothesis engine generates testable market relationships.
10. Cloudflare Queues distribute backtesting experiments.
11. Local compute executes PIT walk-forward simulations.
12. The evaluation engine calculates out-of-sample performance.
13. GitHub preserves source code, experiment results, research memos, and approved model versions.
14. The remote Quant Hub exposes authenticated analytical capabilities.
15. The alerting system reports validated discoveries, operational failures, and material market developments.

A successful system must connect all five architectures. A functioning API, populated vector database, or successful scraper alone does not establish completion.

## 9. Non-Negotiable Data Integrity and Quantitative Research Requirements

The following requirements apply throughout the entire platform.

**Point-in-Time Integrity**
- Preserve historical publication and availability timestamps.
- Preserve revisions rather than overwriting prior vintages.
- Enforce `available_timestamp <= decision_timestamp`.
- Prevent look-ahead bias across every data source and feature.
- Apply identical PIT restrictions to SQL, vector retrieval, feature generation, and backtesting.

**Data Provenance**
- Identify every source.
- Preserve original source payloads.
- Record extraction timestamps.
- Record extraction and transformation versions.
- Preserve units and geographic scope.
- Validate observations before production ingestion.

**LLM Reliability**
- Treat LLM output as untrusted until validated.
- Never allow model-generated SQL to bypass deterministic validation.
- Never permit autonomous untested production code deployment.
- Never treat a generated scenario estimate as a measured market observation.
- Preserve model and prompt version information for reproducibility.

**Quantitative Validity**
- Separate training, validation, and out-of-sample periods.
- Account for transaction costs and execution constraints.
- Test performance across different market regimes.
- Compare against explicit baselines.
- Control for multiple testing and feature-selection bias.
- Require reproducible results before promoting an alpha hypothesis.

**Operational Security**
- Preserve Cloudflare Access authentication.
- Keep service credentials outside source control.
- Restrict local database execution to read-only operations where appropriate.
- Authenticate remote jobs and webhooks.
- Require authorization before merging and deploying repaired code.
- Preserve execution and incident audit records.

## 10. Expected Final System Capabilities

The completed platform must be able to:

1. Collect and maintain data from 81 or more specialized market-data agents.
2. Retrieve historical market observations with exact point-in-time availability.
3. Preserve original source material and every relevant data vintage.
4. Detect and recover from source and parser failures.
5. Generate tested scraper repairs and GitHub pull requests.
6. Maintain a searchable cross-domain vector knowledge library.
7. Identify historical analogs across natural gas, NGL, weather, infrastructure, and financial markets.
8. Generate structured, testable market-alpha hypotheses.
9. Execute large-scale PIT walk-forward backtesting experiments.
10. Rank competing models using out-of-sample performance.
11. Maintain reproducible experiment records and model leaderboards.
12. Accept authenticated remote natural-language commands.
13. Execute quantitative scenario analyses on the local workstation.
14. Produce auditable market research and alpha alerts.
15. Continuously improve its analytical capabilities through validated data, research, and backtesting.

## 11. Instructions to the Engineering Agent: Backward-Engineer and Complete the Entire Platform

You are the quantitative engineering agent responsible for implementing this ultimate objective.

Do not interpret this document as a request to build only a chatbot, API endpoint, vector database, or isolated scraper.

Your responsibility is to backward-engineer the complete execution path from the ultimate objective to the required production infrastructure, source code, data contracts, agents, connectors, orchestration, security, testing, and deployment.

Before modifying anything:

1. Inspect the complete project filesystem.
2. Identify the actual running FastAPI source and its process manager.
3. Inspect the existing Cloudflare Worker, Tunnel, Access configuration, and service-token integration.
4. Inspect the current SQLite schema and database contents.
5. Inspect installed Ollama models and embedding functionality.
6. Inspect the existing GitHub repository state and authentication.
7. Identify existing agents, scripts, tests, scheduled jobs, and services.
8. Distinguish implemented components from partially implemented components, placeholders, and missing components.
9. Preserve working implementations and identify conflicting or duplicated source trees.
10. Produce a complete architecture and dependency audit before making destructive changes.

Then create a comprehensive implementation plan covering all five architectures.

For every component, identify:
- Required functionality.
- Existing implementation.
- Missing functionality.
- Exact source files and directories.
- Required dependencies.
- External data sources and access requirements.
- Input and output contracts.
- Connections to other components.
- Security requirements.
- Tests and acceptance criteria.
- Deployment and monitoring requirements.

Implement the system in dependency order. Establish reliable data contracts, historical data preservation, and PIT integrity before attempting to generate or validate market alpha.

Do not declare an architecture complete because its service starts or its endpoint returns HTTP 200. Completion requires demonstrated functionality, validated data, successful integration tests, reproducible results, and evidence that the component satisfies its stated requirements.

**FINAL ENGINEERING DIRECTIVE**

Build the complete five-architecture quantitative intelligence platform to achieve its governing objective:

**Derive NGL and Henry Hub market alpha through Cross-Domain Hyper-Synthesis and Point-in-Time Walk-Forward Backtesting.**

All implementation decisions, code changes, infrastructure modifications, data contracts, agent development, and testing must directly advance this objective.

---

## 12. Visual Intelligence Web Platform, Monochrome Wireframe Design System, Geospatial Stack & Synchronized Terminal Dashboard (`markets.joeysvault.app`, `ngl.joeysvault.app`, `ngl-term.py`)

### 12.1 Mandatory Visual Design References & Aesthetic Direction

Both the web interface and the terminal dashboard must follow a **clean, sophisticated, high-contrast monochrome wireframe aesthetic** characterized by ultra-fine hairlines, crisp vector geometry, obsidian/black backgrounds, razor-sharp white/silver linework, and disciplined accent restraint—avoiding cluttered retail trading widgets.

**Before designing or implementing any UI, map, chart, or terminal layout, Claude MUST inspect and base the visual language, layout hierarchy, typography, line weights, and cartographic styling on the reference visuals in `/home/joey/Projects/henry_hub_atomic_agents/artifacts/`:**

1. `/home/joey/Projects/henry_hub_atomic_agents/artifacts/Real-time global maritime traffic visualization image example.png`
2. `/home/joey/Projects/henry_hub_atomic_agents/artifacts/NGL Henry Hub Visual Intelligence`
3. `/home/joey/Projects/henry_hub_atomic_agents/artifacts/NGL pipeline and meter map view.png`

Additionally, Claude MUST utilize geospatial tooling and visualization libraries from **`https://github.com/sshuair/awesome-gis`** (such as **MapLibre GL JS**, **deck.gl**, **D3-geo**, **TopoJSON**, **Turf.js**, **GeoPandas**, and **Shapely**) to render North American pipeline corridors, meter stations, LNG maritime export terminals/routes, producing basins, and NGL hubs with fine-line geospatial precision.

### 12.2 Cloudflare Subdomains, Tunnel Routing & Main-Site Linking

Use the local `cloudflared` CLI and paid Cloudflare account (`dell-secret-tunnel`, `e35ed333-e140-4823-954c-250f6903c335`) to provision and expose the public visual platform without exposing privileged `/execute` or `/ingest` endpoints:

1. Create and route **`markets.joeysvault.app`** as a new subdomain under `joeysvault.app`.
2. Create and route **`ngl.joeysvault.app`** (serving the NGL visual dashboard and the canonical synchronized JSON endpoint `ngl.joeysvault.app/api/state.json`, with `markets.joeysvault.app/api/state.json` serving the identical schema).
3. Link `markets.joeysvault.app` (and `ngl.joeysvault.app` where appropriate) directly from the main landing page **`https://joeysvault.app`** (`/home/joey/joeysvault-site`) and deploy via `wrangler`.
4. Keep privileged write/LLM/execution endpoints on `quant.joeysvault.app` (`127.0.0.1:8090`) protected behind Cloudflare Access; serve public read-only visualizations and `/api/state.json` from a dedicated isolated read-only service or read-only route layer.

### 12.3 Progressive Graphical Vector Knowledge Library

Extend `chroma_pit_kb` (`henry_hub_alpha_graph`) into a progressively growing, interactive **Graphical Vector Knowledge Library**:
- As atomic agents discover new market developments (pipeline critical notices, force majeure, EIA/NOAA reports, cracker outages, NGL/basis anomalies, and scenario runs), ingest them as **durable knowledge objects** embedded via `nomic-embed-text` with full PIT metadata (`available_timestamp`, `available_epoch`, `published_timestamp`, `source_id`, `raw_payload_hash`, `domain`, `provenance`) and explicit parent-child `linked_nodes` edges.
- Render an interactive monochrome fine-line **node-and-edge knowledge graph explorer** in the web UI with PIT-filtered semantic search and click-to-inspect provenance and raw payload traceability.

### 12.4 Top-Focused Hero Visual, Dynamic Product Tracking & Source Availability Transparency

1. **Top Hero Focus Panel:** The uppermost, most prominent visual on the interface MUST display **Seasonal Patterns and Key Technical Levels for the active market**.
2. **Dynamic Product & Timeframe Tracking:**
   - Dynamically detect and track whichever NGL or gas product is currently being calculated by the main pricing engine (`ethane`, `propane`, `normal_butane`, `isobutane`, `natural_gasoline`, `henry_hub`), with interactive product switching.
   - Support selectable trading timeframes: **Intraday**, **Seasonal Swing**, and **Multi-Year Hedging**.
3. **Live Pricing Decomposition & Source Availability:**
   - Visually display the **calculated price**, **historical price fluctuations**, and the **production/fundamental elements behind the calculation** (shale basin output, HDD/CDD weather drivers, storage balances, LNG feedgas, fractionation/rejection economics, power burn).
   - Display a **Source Availability Transparency panel** listing every contributing agent, `source_id`, `available_timestamp`, `retrieved_timestamp`, `quality_status`, `raw_payload_hash`, and `provenance` (`measured` vs `extracted_estimate` vs `synthetic_placeholder_pending_collector`). Never present uncollected placeholders as measured observations.

### 12.5 Required Five Commodity-Specific NGL & Relative-Value Curves

1. **NGL-to-WTI Percentage Ratio Charts:** Propane, normal butane, and natural gasoline plotted as a percentage of WTI crude oil (`(cents/gal / 100 * 42) / WTI_bbl * 100`).
2. **Mont Belvieu vs. Conway Hub Spreads:** Side-by-side hub prices and differential spread tracking Gulf Coast vs. Midcontinent pipeline bottlenecks and localized storage gluts.
3. **The "Frac Spread" Curve:** Ethane (`$/MMBtu`) vs. Henry Hub natural gas (`$/MMBtu`), visually highlighting **ethane recovery vs. ethane rejection** zones.
4. **Forward Curve Contango and Backwardation:** Futures term structure slope across delivery months with automatic regime detection (contango vs. backwardation).
5. **Multi-Year Seasonal Overlay Bands:** Calendar-aligned multi-year historical price lines and min/max/average bands revealing winter blending/heating peaks and summer troughs.

### 12.6 Required Five Classic Technical Chart Patterns & Indicators

1. **Symmetrical and Ascending Triangles:** Converging swing-high/swing-low trendlines and breakout trigger levels.
2. **Bollinger Band Squeezes:** 20-period SMA ± 2σ volatility bands with low-bandwidth squeeze detection shading.
3. **200-Day Moving Average Crossovers:** 50-day and 200-day moving average overlays with Golden/Death cross markers.
4. **RSI and MACD Divergences:** Synchronized lower momentum oscillator panes (RSI-14 and MACD 12/26/9) with automated bullish/bearish divergence detection.
5. **Fibonacci Retracement Levels:** Horizontal 23.6%, 38.2%, 50.0%, 61.8%, and 78.6% grids anchored to trailing seasonal highs/lows.

### 12.7 Complete Standalone Terminal Dashboard (`ngl-term.py`)

Build a complete, standalone terminal application **`ngl-term.py`** using Python **`rich`** that shares the exact same fine-line, high-contrast monochrome wireframe sophistication as the web UI and is **100% synchronized with the exact same JSON schema served at `ngl.joeysvault.app/api/state.json`** (and `markets.joeysvault.app/api/state.json`).

`ngl-term.py` MUST include:
1. **Sub-Pixel Unicode Braille Map (`U+2800`–`U+28FF`):** A high-contrast monochrome wireframe **North American Energy Hub & Infrastructure Map** rendered via `2x4` sub-pixel Braille dot-matrix vectors showing continental coastlines, major NGL/gas pipelines, LNG export corridors, producing basins (Permian, Appalachia, Haynesville), and hubs (Mont Belvieu, Conway, Henry Hub, Sabine Pass, Corpus Christi).
2. **Live Regional Flows & Active Pipeline Alerts:** Real-time border/LNG/interstate meter flows, capacity constraints, critical notices, and force majeure status.
3. **Top Seasonal & Technical Summary + Fibonacci Retracement Levels:** Active product (`propane`, `ethane`, `normal_butane`, `isobutane`, `natural_gasoline`, `henry_hub`), selected timeframe (`intraday`, `seasonal`, `multi_year`), 50/200-DMA, Bollinger squeeze, RSI/MACD divergence, triangle state, and Fibonacci 23.6%–78.6% price grid.
4. **Pricing & Production Elements:** Calculated spot/spread values (WTI %, Mont Belvieu–Conway, Frac Spread, Forward Curve regime) and underlying physical production/weather/storage drivers.
5. **Source Availability Transparency:** Live table of agent freshness, `available_timestamp`, `provenance`, and `quality_status`, plus keyboard/CLI flags to switch product, timeframe, and refresh interval against `ngl.joeysvault.app/api/state.json` (or local `http://127.0.0.1:8095/api/state.json`).
