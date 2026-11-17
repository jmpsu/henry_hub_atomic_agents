# GOAL CHECKLIST: markets.joeysvault.app LNG forward, fundamentals-behind-the-calculation, feedgas, fractionation, Ollama RAG chat

Created 2026-11-17 from the user's pasted requirement messages plus the LNG spec they reference; extended with the user's gap list (section 11, AD1-AD8), the drill-down spec (section 12), the 0001 patch overlap (section 13) and resolutions (section 14). This file TRANSLATES requirements only. It adds no requirements, removes none and changes none. Text in quotes is the user's wording. Where the user's text is ambiguous or inconsistent it is recorded in section 9 as an open item, not resolved here.

## 0. How to use this file

- A requirement is **fulfilled** only when its row shows all three gates: **I** implemented, **T** tested (tests that exercise the real behaviour, results reported honestly), **P** pushed to the final code location. The whole goal is complete only when section 10 (final gate) is fully checked.
- Marks: ☐ not done · ◐ partly done (see Notes) · ☑ done and verified. Update the marks in place; never delete a row.
- Status in the Notes column is what I verified in this session on 2026-11-17 (branch `feat/lng-forward`, nothing committed or pushed yet). "Not started" means no code exists for it.
- Standing directive from the user (twice): **"Do not stop until you have some working form of populating these elements of the final output."**
- Standing instruction in this session: the user said "stop, wait for further clarification". This checklist is the only work authorised after that; implementation resumes only on the user's instruction.
- Project rules that apply (from the user's CLAUDE.md files): never delete `pit_market_data`, snapshots or artifacts; keep `target_timestamp` vs `available_timestamp` separate; run only the targeted pytest file for an edited module and, for the final gate, the full suite; never fabricate results; state exact blockers.

## 1. Facts and claims as the user stated them (recorded, not requirements)

| # | Statement (user's text) | Source given | Notes |
|---|---|---|---|
| S1 | "No Claude task is running." | `pgrep -af "claude -p"` → `NO` | |
| S2 | "No feature branch exists, local or pushed." | `git branch --list 'feat/*'` and `git ls-remote` → (empty) | Local branch `feat/lng-forward` now exists (created by me, unpushed). Remote still has none. |
| S3 | "There's no LNG forward price on markets. or ngl." | `markets: NONE`, `ngl: NONE` | Matches my earlier check. |
| S4 | UNKNOWN: "quant.joeysvault.app. Its `/api/state.json` didn't return JSON." | `jq: parse error: Invalid numeric literal at line 1, column 10` | My check: HTTP 403, `text/html`, Cloudflare Access (cf-access headers). |
| S5 | `docs/LNG_FORWARD_SPEC.md` does not exist ("No such file or directory"); the background `claude -p` start printed "NOT STARTED". | `ls` output in the user's terminal | The spec text is in section 3 (G1-S). The file was never saved. |

## 2. Primary requirements (the headline asks)

| ID | Requirement | I | T | P | Notes |
|---|---|---|---|---|---|
| G1 | "Currently no LNG forward price on markets.joeysvault.app - that needs to be address both in the calculation pipeline and then also on the top level site." (two parts: calculation pipeline AND the top-level site) | ◐ | ◐ | ☐ | See section 3. Pipeline code written (uncommitted); site panel written, not yet browser-checked or deployed. |
| G2 | "The Production & fundamental elements behind the calculation section should be what ACTUALLY IS USED TO INFLUENCE THE FORWARD PRICE OF THE COMMODITIES BEING LOOKED AT ON THIS PAGE." | ◐ | ◐ | ☐ | Not started. See section 4. |
| G3 | "Do not stop until you have some working form of populating these elements of the final output" (the elements listed in section 4, rows E1-E8) | ◐ | ◐ | ☐ | Not started beyond the existing EIA monthly series. |
| G4 | Reconstruct missing LNG feedgas flows for 8 terminals from physical/operational/mass-balance proxies without contaminating the forward price model (section 5). | ◐ | ◐ | ☐ | Not started. Existing: EIA monthly exports only. |
| G5 | Classify and integrate the 7 fundamental elements as Direct Ingested Inputs vs Separately Calculated Orthogonal Modules, with graph nodes, tooltips and Ollama context (section 6). | ◐ | ◐ | ☐ | Not started. |
| G6 | Ollama-powered RAG and Graph-RAG chat interface on markets.joeysvault.app, in four phases (section 7). | ☐ | ☐ | ☐ | Not started. |
| G7 | Everything fulfilled, implemented, tested and pushed to the final code location so that a complete test run can be done (section 10). | ☐ | ☐ | ☐ | |

## 3. G1 detail: LNG forward price (from the user's message and the LNG spec it references)

Source of the spec: the user's earlier message that wrote `docs/LNG_FORWARD_SPEC.md` ("Work autonomously; ask nothing. Repo: ~/Projects/henry_hub_atomic_agents. Run `source .venv/bin/activate` first.").

| ID | Requirement | I | T | P | Notes |
|---|---|---|---|---|---|
| G1-S1 | **CHECK:** search tag v1.0.5 and the current branch for any LNG price, forward, JKM, TTF or netback code (`git grep`); query https://markets.joeysvault.app/api/state.json, ngl. and quant. for matching fields. If an LNG forward price already exists, report URL/field/file and STOP. | ☑ | n/a | n/a | Done: none exists. Tag `v1.0.5` does not exist locally or on origin (only v1.0.0-v1.0.2); I searched the release commit `5989f7a` instead. quant. returned 403. |
| G1-S2 | **BUILD (only if absent):** add an LNG forward price curve to `markets_hub`, **M1-M12**, derived from the existing Henry Hub forward curve. | ☑ | ☑ | ☐ | `lng_forward.py` + engine `curves.lng_forward`. Uncommitted. |
| G1-S2a | Formula: US Gulf LNG FOB cost_m = **1.15 × HH_m + L**. | ☑ | ☑ | ☐ | Tested against hand-computed values (6.09375 for HH 3.125). |
| G1-S2b | L = liquefaction fee as a **named constant in one config place**, **default 2.50 $/MMBtu, labelled assumption**. | ☑ | ☑ | ☐ | `lng_config.py` (`LIQUEFACTION_FEE_USD_MMBTU`). The 1.15 is also a named assumption there (`FEEDGAS_FACTOR`). |
| G1-S2c | If a free **JKM or TTF futures source is reachable**, add a collector and show the netback: **NB_m = JKM_m (or TTF_m) − shipping − regas**. Each assumption is a labelled constant; **never invent a quote.** | ☑ | ☑ | ☐ | TTF reachable (Yahoo `TTF<code><yy>.NYM`, EUR/MWh; stale for deferred months). JKM not reachable (`JKM=F` no data, dated contracts 404). Collector `collectors/ttf_forward_yahoo.py` written and registered; **never run against any DB**; EUR/USD collected via `EURUSD=X`. |
| G1-S2d | Otherwise show **"pending collector: JKM/TTF"**. | ☑ | ☑ | ☐ | JKM shown as pending with the evidence note; TTF netback only for months with a fresh quote. |
| G1-S3 | Add the curve to **state.json** and **the page** (a panel **next to the Henry Hub forward curve**). | ☑ | ☑ | ☐ | API block and 5-column panel written; not rendered in a browser, not deployed. |
| G1-S3a | `.explain` entries (**what / formula / read / caveat**) in the existing style. | ☑ | ☑ | ☐ | `lng_forward`, `lng_fwd_point`, `lng_netback` in `metric_docs.py`; docs test passes. |
| G1-S3b | **PIT cutoff respected.** | ☑ | ☑ | ☐ | Tested: a quote available after the cutoff is not used. |
| G1-S3c | Provenance **"extracted estimate"**. | ☑ | ☑ | ☐ | |
| G1-S4a | Test: the formula matches **hand-computed values for 3 months**. | ☑ | ☑ | ☐ | `tests/test_lng_forward.py`. |
| G1-S4b | Test: **no values when HH points are missing**. | ☑ | ☑ | ☐ | |
| G1-S4c | **The full suite passes.** | ☑ | ☑ | ☐ | 235 passed on the working tree at last run; must be re-run at the end. |
| G1-S5a | Run locally on **127.0.0.1:8095**. | ☑ | n/a | n/a | **Port 8095 is the production service** on this machine; a different port is needed (open item O1). |
| G1-S5b | Headless-Chrome **screenshot of the new panel to `docs/poc/lng_forward.png`**. | ☑ | n/a | ☐ | |
| G1-S5c | **Commit on branch `feat/lng-forward` and push.** | ☐ | n/a | ☐ | Branch exists locally only; nothing committed. |
| G1-S6 | **Report:** what existed, what was built, the formula, the constants, the test tail, the screenshot path. | ☐ | n/a | n/a | |
| G1-V | The LNG forward price actually appears on markets.joeysvault.app (the live site), not only in a local run. | ☐ | ☐ | ☐ | Implied by G1 ("on the top level site"); needs deploy. |
| G1-C | The task is runnable as the user's command did: `claude -p` in the background with a log (`lng_forward.log`), `pgrep -af "claude -p"` to confirm, `tail -f lng_forward.log` to watch; and a final `curl` of `quant /api/state.json` to confirm whether quant. has LNG data. | n/a | n/a | n/a | Spec file must exist for that command to work (S5). The quant. check is blocked by Cloudflare Access (403) unless credentials exist. |

## 4. G2 and G3 detail: the "Production & fundamental elements behind the calculation" section

User's text: the section "should be what ACTUALLY IS USED TO NIFLUENCE THE FORWARD PRICE OF THE COMMODITIES BEING LOOKED AT ON THIS PAGE". The section as it appears today lists (all must end up populated in some working form, per "Do not stop..."):

| ID | Element (user's list) | Present state | I | T | P |
|---|---|---|---|---|---|
| E1 | Shale gas production by basin ("Bcf/d (monthly average)") | populated (EIA STEO monthly) | ☑ | ☑ | ☐ |
| E2 | Weather (CONUS population-weighted HDD/CDD) | populated (NOAA CPC, GFS, ECMWF Days 1-14) | ☑ | ☑ | ☐ |
| E3 | Working gas in storage by region | populated (EIA weekly) | ◐ | ◐ | ☐ |
| E4 | LNG feedgas (daily meters, no collector yet) | **pending**, no collector | ◐ | ◐ | ☐ |
| E5 | Fractionation / rejection economics | ethane **pending**, propane and HH spot present | ◐ | ◐ | ☐ |
| E6 | LNG exports by terminal (EIA, monthly) | populated (13-series EIA collector, released 1.0.5) | ☑ | ☑ | ☐ |
| E7 | Pipeline volumes at border points (EIA, monthly) | populated (same collector) | ☑ | ☑ | ☐ |
| E8 | (For G2) a link, per element, to **what actually influences the forward price** shown on the page (which elements feed which calculation) | not started | ☑ | ☑ | ☐ |

Marks for E1-E3, E6, E7 are ◐ because data populate but the section does not yet present them as forward-price influences (G2), and E-rows need tests for that presentation.

## 5. G4 detail: reconstruct missing LNG feedgas flows (user's methodology, to be implemented)

Terminals named: Sabine Pass, Corpus Christi, Freeport, Cameron, Calcasieu Pass, Cove Point, Elba Island, Plaquemines.
Goal: reconstruct missing feedgas flows **"without contaminating your forward price model"**, using **physical, operational and mass-balance proxies**.

| ID | Requirement (user's wording preserved) | I | T | P |
|---|---|---|---|---|
| F0 | **Avoid market-derived inputs** like Henry Hub basis spreads, TTF/JKM netbacks, or broker flow estimates ("Those share variance with forward curves and introduce multicollinearity"). | ☑ | ☑ | ☐ |
| F1 | **Interstate pipeline EBBs:** scrape Operationally Available Capacity (OAC) and Scheduled Quantity postings directly from the feeding interstate pipelines (e.g., Creole Trail, Kinder Morgan Louisiana, Corpus Christi Pipeline, Transco, Elba Express, Gator Express), not third-party aggregators. Note: intrastate pipes (e.g., those feeding Freeport) do not post FERC-mandated EBB data, requiring the physical proxies below. | ☐ | ☐ | ☐ |
| F2 | **AIS maritime and draft telemetry:** track LNG carrier arrivals, berth dwell times and vessel draft changes (laden vs ballast) from raw terrestrial/satellite AIS; combine draft displacement with vessel DWT and tank capacity (typically ~170,000-174,000 m³) to compute liquefied volume lifted per cargo. | ☐ | ☐ | ☐ |
| F3 | **Grid telemetry / regional load:** for electric-drive facilities (Freeport LNG and Corpus Christi Stage 3) monitor regional load zones (ERCOT South/Coast) or behind-the-meter generation drops; electric-drive trains have a rigid, linear MW to MMcf/d ratio. | ☐ | ☐ | ☐ |
| F4 | **Remote sensing (thermal and flare):** multi-spectral passes (Sentinel-2, Landsat, VIIRS nightfire) for AGRU thermal signatures, compressor exhaust plumes and flare anomalies (a flare spike with a drop in compressor heat indicates a train trip before nominations update). | ☐ | ☐ | ☐ |
| F5 | **Ambient temperature and barometric pressure:** local airport METAR (e.g., KLCH for Lake Charles/Sabine, KCRP for Corpus Christi); turbine liquefaction efficiency drops as ambient temperature rises, giving a deterministic ceiling on daily feedgas intake. | ☑ | ☑ | ☐ |
| F6 | **Training data:** use historical verified feedgas data (or monthly EIA/DOE lagged actuals) to bootstrap daily flows with a rolling state-space or mass-balance model. (Existing: EIA monthly LNG exports, 8 terminals.) | ◐ | ◐ | ☐ |
| F7 | **Step 1, terminal mass-balance:** Feedgas_implied(t) = ((ΔInventory(t) + Cargo_Lifted(t)) / η_liq) × (1 + Fuel_Shrinkage). Cargo_Lifted from AIS draft increases × LNG density (~450 kg/m³) and regasification expansion ratio (~600:1). η_liq and Fuel_Shrinkage: "typically 8% to 10% of inbound gas is consumed as turbine fuel/shrinkage". ΔInventory bounded by each terminal's onshore full-containment tank capacity (e.g., Sabine Pass ~16.8 Bcf equivalent; Elba Island ~11.5 Bcf). | ◐ | ◐ | ☐ |
| F8 | **Step 2, ambient capacity curves:** train a regression on historical verified days mapping Ambient Temperature and Active Train Count (verified via thermal/power telemetry) to actual feedgas intake; this sets each terminal's upper physical bound per day. | ☐ | ☐ | ☐ |
| F9 | **Step 3, block-bootstrap residuals** for unobserved storage buffers (tanks buffer intake vs ship loading by 3-7 days): (1) historical buffer residuals e_t = Actual_Feedgas_t − Smoothed_Cargo_Outflow_t over periods with matching berth utilization; (2) stationary block bootstrap preserving 5-to-7-day autocorrelation blocks, conditioned on current berth dwell frequency and ambient temperature; (3) re-anchor the cumulative sum when a terminal hits tank-top (no ships loading for several days) or tank-bottom. | ◐ | ◐ | ☐ |
| F10 | **Terminal-specific mapping** (EBB visibility and independent physical proxy) — see table F10 below. | ☐ | ☐ | ☐ |
| F11 | **Strict feature exclusion:** no Henry Hub cash/futures prices, regional basis (Houston Ship Channel, Transco Zone 5), shipping charter rates or European/Asian spreads in the bootstrap feature set ("let that signal enter your forward curve once through your pricing engine—not twice via a price-adjusted flow estimate"). | ☑ | ☑ | ☐ |
| F12 | **Orthogonalize weather:** if the forward model already uses HDD/CDD for residential/commercial demand, use local coastal wet-bulb temperature **strictly to cap mechanical turbine efficiency**, not as a directional demand predictor. | ◐ | ◐ | ☐ |
| F13 | **Propagate estimation uncertainty:** pass the bootstrapped confidence interval (10th, 50th, 90th percentiles from **1,000 bootstrap iterations**) downstream; weight days backed by direct pipeline EBB scrapes higher than days inferred only from AIS and power load (like Freeport). | ◐ | ◐ | ☐ |
| F14 | Open input requested by the user's source text: "share which data feeds you currently have pipeline access to (e.g., raw AIS, ERCOT grid telemetry, or specific FERC EBB scrapers) and your target update frequency (intraday vs. gas-day)". | ☐ | n/a | n/a |

**Table F10: terminal-specific proxy mapping (as given):**

| Terminal | Primary pipeline EBB visibility | Recommended independent physical proxy |
|---|---|---|
| Sabine Pass | High (Creole Trail, NGPL, Transco) | Direct EBB sum + KOGAS/Cheniere jetty AIS draft dwell |
| Corpus Christi | High (Corpus Christi Pipeline) | EBB + ERCOT South grid load (Stage 3 electric drives) |
| Freeport | None (intrastate pipes only) | ERCOT Coast power load delta + Quintanilla jetty AIS |
| Cameron | High (Cameron Interstate, Columbia Gulf) | EBB + Calcasieu Ship Channel AIS transit timing |
| Calcasieu Pass | High (TransCameron) | EBB + power plant thermal plume (on-site CCGT) |
| Cove Point | High (Cove Point Pipeline) | EBB + Chesapeake Bay AIS draft telemetry |
| Elba Island | High (Elba Express) | EBB + Savannah River AIS berth dwell (smaller modular trains) |
| Plaquemines | Partial/Ramping (Gator Express) | AIS cargo count + VIIRS flare/thermal ramp curve |

## 6. G5 detail: element classification, separate modules, graph nodes, tooltips, Ollama context

**6.1 Element-by-element classification matrix (7 elements, as given):**

| ID | Element | Handling mode | Source and frequency | Forward-pricing role | Ollama / vector-graph role | I | T | P |
|---|---|---|---|---|---|---|---|---|
| M1 | Shale gas production by basin | Direct use (with lag interpolation) | EIA DPR / STEO (Bcf/d, monthly average) | Structural supply baseline by basin (Appalachia, Permian, Haynesville) | Links basin supply nodes to regional basis and pipeline bottlenecks | ☑ | ☑ | ☐ |
| M2 | Weather (CONUS pop-weighted HDD/CDD) | Direct use (strict scope) | NOAA/CPC (daily actuals + 15-day ensemble) | Residential/commercial demand only; **exclude from LNG liquefaction capacity equations** | Explains short-term storage draws/injections and Henry Hub prompt spikes | ☑ | ☑ | ☐ |
| M3 | Working gas in storage by region | Direct use | EIA Weekly Natural Gas Storage Report (Bcf by 5 regions) | Core inventory-to-normal deficit/surplus curve driver | Links regional storage nodes (South Central salt/nonsalt) to seasonal spreads | ◐ | ◐ | ☐ |
| M4 | LNG feedgas (daily meters, no collector yet) | Calculated separately (bootstrapped proxy) | Physical EBB scrapes + AIS draft + ERCOT power + METAR ambient temp | Demand sink input with propagated confidence intervals (10th/50th/90th pct) | Explains real-time terminal utilization while flagging pending collector status | ◐ | ◐ | ☐ |
| M5 | Fractionation / rejection economics | Calculated separately (independent spread) | Mont Belvieu purity NGL prices vs Henry Hub BTU parity (¢/gal vs $/MMBtu) | Computes ethane rejection/recovery volume (Bcf/d added/removed from dry gas) | Connects NGL visual intelligence (Mont Belvieu vs Conway, frac spread) to dry gas supply | ◐ | ◐ | ☐ |
| M6 | LNG exports by terminal (EIA, monthly) | Direct use (calibration anchor) | EIA Natural Gas Monthly (Bcf/month per terminal) | Ground-truth anchor to calibrate and re-zero the daily bootstrapped feedgas model | Historical terminal capacity utilization and verified monthly provenance | ☑ | ☑ | ☐ |
| M7 | Pipeline volumes at border points (EIA, monthly) | Direct use | EIA Monthly (Bcf/month US-Mexico and US-Canada net flows) | Net cross-border structural demand/supply offset (e.g., Permian-to-Mexico exports) | Explains regional flow balances in South Central and Midwest/Northeast hubs | ☑ | ☑ | ☐ |

Note: the existing EIA monthly series are in **MMcf/month** (as published), not Bcf/month; reconcile in open item O5.

**6.2 Module A: LNG feedgas (daily meters), bootstrapped, isolated pipeline**

| ID | Requirement | I | T | P |
|---|---|---|---|---|
| A1 | Compute in an isolated pipeline before the pricing engine ("Why separate: ... interpolating [daily meters] with price-based models would bake forward curve expectations directly into your supply/demand balance"). | ☑ | ☑ | ☐ |
| A2 | Step 1: ingest EIA LNG exports by terminal (monthly) as the historical ground-truth baseline. | ☑ | ☑ | ☐ |
| A3 | Step 2: run the orthogonal physical proxy model (interstate EBB scheduled quantities + AIS vessel draft liftings + ERCOT grid load for Freeport/Corpus Christi + coastal ambient-temperature derating) to generate **daily Bcf/d** estimates. | ◐ | ◐ | ☐ |
| A4 | Step 3: store three series in the local database: **`lng_feedgas_p50`**, **`lng_feedgas_p10`**, **`lng_feedgas_p90`**, tagged `provenance: bootstrapped_physical_proxy`. | ☑ | ☑ | ☐ |

**6.3 Module B: fractionation / rejection economics (ethane BTU parity), isolated**

| ID | Requirement | I | T | P |
|---|---|---|---|---|
| B1 | Why separate: ethane rejection alters dry natural gas supply ("+0.5 to +1.5 Bcf/d swing") based on NGL processing margins, not gas demand alone. | ☑ | ☑ | ☐ |
| B2 | Step 1: compute the Ethane Frac Spread: Mont Belvieu purity ethane ($/gal converted to $/MMBtu at **~0.0664 MMBtu/gal**) vs regional gas hub prices (**Henry Hub / Waha**) **plus T&F (transportation and fractionation) costs**. | ◐ | ◐ | ☐ |
| B3 | Step 2: when Ethane_Value < (Gas_Hub_Price + T&F_Cost), trigger the rejection curve to output estimated **Bcf/d of ethane left in the dry gas stream**. | ◐ | ◐ | ☐ |
| B4 | Step 3: feed **only the resulting net dry-gas supply delta (Bcf/d)** into the forward pricing balance; "never double-count raw NGL prices inside the gas pricing regression". | ☑ | ☑ | ☐ |
| B5 | (Existing context, not a requirement) the page's frac spread is currently pending because ethane has no collector. | ◐ | ◐ | ☐ |

**6.4 Graph node registration and tooltip / Ollama injection**

| ID | Requirement | I | T | P |
|---|---|---|---|---|
| N1 | Create explicit first-class nodes in the vector knowledge graph for all 7 elements with directed edges pointing to `Forward_Pricing_Model`. | ☑ | ☑ | ☐ |
| N1a | `Shale_Production_Basin → [feeds_supply] → Forward_Pricing_Model` | ☑ | ☑ | ☐ |
| N1b | `CONUS_Weather_HDD_CDD → [feeds_rescomm_demand] → Forward_Pricing_Model` | ☑ | ☑ | ☐ |
| N1c | `Regional_Working_Gas_Storage → [feeds_inventory_balance] → Forward_Pricing_Model` | ☑ | ☑ | ☐ |
| N1d | `LNG_Feedgas_Bootstrapped → [calibrated_by] ← EIA_Monthly_LNG_Exports` | ☑ | ☑ | ☐ |
| N1e | `Fractionation_Rejection_Econ → [modifies_dry_gas_supply] → Forward_Pricing_Model` | ☑ | ☑ | ☐ |
| N1f | `EIA_Border_Pipeline_Volumes → [feeds_net_exports] → Forward_Pricing_Model` | ☑ | ☑ | ☐ |
| N2 | Dashboard: attach the dotted-underline hover/pin metadata to **each of the 7 rows** under "Production & fundamental elements behind the calculation" showing **Current Value, Frequency, Collector Status (active vs bootstrapped proxy), Raw Payload Hash**. | ☑ | ☑ | ☐ |
| N3 | When a user asks Ollama how the forward curve is built, Ollama retrieves **all 7 graph nodes**, **cites the exact PDFs/methodologies in `/home/joey/Projects/energy_market_intelligence`** governing each formula, and explicitly distinguishes **direct EIA/NOAA actuals** from **bootstrapped LNG feedgas** and **calculated ethane rejection**. | ☐ | ☐ | ☐ |

Existing tooltips (release 1.0.5) already show source, available (PIT) time, quality and payload hash for driver rows; "frequency" and "active vs bootstrapped proxy" are not yet shown. Hence N2 ◐.

## 7. G6 detail: Ollama-powered RAG and Graph-RAG chat on markets.joeysvault.app

Goal statement: "integrate an Ollama-powered RAG & Graph-RAG chat interface into markets.joeysvault.app, utilizing the existing local database, PDFs, resources, and graphical vector knowledge library inside /home/joey/Projects/energy_market_intelligence", powering both the LNG/NGL Market Chatbot **and** the Forward Pricing Calculations **without cross-contaminating model inputs**.

**Phase 1: unified knowledge and graph-vector architecture (`/home/joey/Projects/energy_market_intelligence`)**

| ID | Requirement | I | T | P |
|---|---|---|---|---|
| R1.1 | Layer 1, PIT guardrails: enforce strict `as_of_timestamp` filtering across **all** vector and graph queries. | ☐ | ☐ | ☐ |
| R1.2 | Every PDF chunk, graph node and database metric carries an `available_at` timestamp, so neither the chatbot nor backtested forward-pricing calculations have look-ahead bias. | ☐ | ☐ | ☐ |
| R1.3 | Layer 2, document and PDF ingestion: parse **all PDFs and research resources** in `/home/joey/Projects/energy_market_intelligence` with **layout-aware chunking** (preserving tables, formulas, terminal specs). | ☐ | ☐ | ☐ |
| R1.4 | Embed chunks with a **local Ollama embedding model** (e.g., `nomic-embed-text` or `mxbai-embed-large`). | ◐ | ◐ | ☐ |
| R1.5 | Knowledge-graph edges: link extracted entities (e.g., Sabine Pass, Mont Belvieu, Henry Hub, Frac Spread, Creole Trail Pipeline) directly to the existing graphical vector nodes. | ☐ | ☐ | ☐ |
| R1.6 | Multi-hop retrieval: hybrid search returning top-k dense vector chunks **and 1-to-2 hop graph neighbours** (e.g., a terminal outage PDF note linked to its downstream pipeline node and forward-curve sensitivity). | ☐ | ☐ | ☐ |
| R1.7 | Layer 3, separation of concerns: tag every ingested knowledge object with a `domain_role` flag: `market_narrative`, `physical_fundamental` or `pricing_parameter`. | ☐ | ☐ | ☐ |
| R1.8 | Forward-pricing engine reads **only** `physical_fundamental` and `pricing_parameter` nodes (e.g., physical LNG mass-balance proxies, heat rates, storage capacities); narrative commentary never touches pricing weights. | ☐ | ☐ | ☐ |
| R1.9 | Chatbot gets **read-only** access across all three roles plus live collector status, so it can explain why a price moved and how it was calculated. | ☐ | ☐ | ☐ |

**Phase 2: backend API and Ollama orchestration (FastAPI or Node/Python service inside `/home/joey/Projects/energy_market_intelligence`)**

| ID | Requirement | I | T | P |
|---|---|---|---|---|
| R2.0 | Build a lightweight FastAPI or Node/Python service bridging the frontend chat box, the local database and Ollama. | ☐ | ☐ | ☐ |
| R2.1 | Context assembly on every prompt, step 1: **intent and entity router** extracting hubs, terminals or metrics (e.g., "Why is Sabine Pass flow unverified?", "How does ethane frac spread impact Henry Hub?"). | ☐ | ☐ | ☐ |
| R2.2 | Step 2: **live telemetry and collector-state injection**: query the local PIT database and the source-availability table for real-time status (pending collector, raw payload hash, last valid timestamp, active alerts). | ☐ | ☐ | ☐ |
| R2.3 | Step 3: **graph-vector context retrieval**: matching PDF passages, methodology definitions and connected graph-node relationships **up to the active UI cutoff time**. | ☐ | ☐ | ☐ |
| R2.4 | Grounding: system prompt (e.g., llama3.1, qwen2.5 or deepseek-r1 locally) must **never hallucinate missing collector values**; if a feed has no data, state the collector is pending and cite the last verified PIT value or the bootstrapped proxy. | ☐ | ☐ | ☐ |
| R2.5 | Return **structured JSON alongside streamed text** with `cited_nodes` and `cited_documents` so the UI can highlight them in the existing Vector knowledge library explorer. | ☐ | ☐ | ☐ |

**Phase 3: frontend (markets.joeysvault.app), preserving hover/pin tooltips and the dark terminal look**

| ID | Requirement | I | T | P |
|---|---|---|---|---|
| R3.1 | Collapsible top command and chat bar mounted directly **beneath the top navigation header** ("← joeysvault.app / MARKETS.JOEYSVAULT.APP"). | ☐ | ☐ | ☐ |
| R3.2 | Compact when idle (**1-line input + quick-prompt chips**) so charts stay above the fold; expands smoothly into a **split-pane drawer** when active. | ☐ | ☐ | ☐ |
| R3.3 | **Click-to-Ask:** add an **"Ask Ollama about this"** trigger inside the existing pin tooltip; clicking pre-loads that metric's formula, raw payload hash and lineage into the chat context. | ☐ | ☐ | ☐ |
| R3.4 | **Cite-to-Highlight:** clicking a source badge in an answer selects and centres that node in the Vector knowledge library section below. | ☐ | ☐ | ☐ |
| R3.5 | Preserve the existing interactive hover/pin architecture and dark-mode terminal aesthetic. | ☐ | ☐ | ☐ |

**Phase 4: verification checklist ("before deploying to production, audit these six critical checkpoints")**

| ID | Audit area | Verification requirement | I | T | P |
|---|---|---|---|---|---|
| V1 | Corpus completeness | 100% of PDFs, markdown notes and methodology docs in `/home/joey/Projects/energy_market_intelligence` are indexed **with hash tracking so updated files re-index automatically**. | ☐ | ☐ | ☐ |
| V2 | Forward-pricing isolation | Forward-pricing scripts read only orthogonal physical inputs and parameter nodes, **never LLM-generated text or unverified narrative summaries**. | ☐ | ☐ | ☐ |
| V3 | Cutoff synchronization | The chat API respects the exact PIT cutoff timestamp displayed on the dashboard. | ☐ | ☐ | ☐ |
| V4 | Missing-collector handling | Test queries on pending-collector / no-data feeds (e.g., Freeport, Corpus Christi) confirm Ollama cites collector status and fallback proxies rather than guessing. | ☐ | ☐ | ☐ |
| V5 | Streaming and latency | Token streaming (SSE) from Ollama so responses **begin rendering in under 500 ms** without blocking chart interactions. | ☐ | ☐ | ☐ |
| V6 | Audit logging | Log every prompt, retrieved graph node ID, PDF chunk ID and model response **locally** for provenance parity with the agent roster. | ☐ | ☐ | ☐ |

Open input requested by the user's source text: "share: your frontend and backend stack (e.g., React/Next.js, Python FastAPI/Flask, SQLite/PostgreSQL, and current vector store like Chroma, Qdrant, or pgvector)" and "which Ollama models you currently have pulled locally". (Discoverable facts from this session: frontend is plain JS + d3 + maplibre + deck.gl served by FastAPI `markets_hub`; DB is SQLite; vectors are float32 BLOBs in `kb_nodes` plus a Chroma mirror; Ollama has `qwen3:4b` and `nomic-embed-text`. Not yet provided to the user as an answer.)

## 8. Cross-cutting requirements that apply to every item above

| ID | Requirement | Status |
|---|---|---|
| X1 | PIT correctness everywhere new (target vs available timestamps; cutoff respected; no look-ahead). | ☐ |
| X2 | Provenance labelled on every new figure (measured / extracted estimate / bootstrapped physical proxy / assumption); nothing fabricated; blocked items stay "pending collector" with the exact blocker. | ☐ |
| X3 | Forward-price contamination rules (F0, F11, F12, B4, R1.8, V2) hold across LNG feedgas, fractionation, the LNG forward curve and the chatbot. | ☐ |
| X4 | Existing functionality and data preserved (no deletions; additive migrations; DB checkpoint before state-changing runs). | ☐ |
| X5 | Real tests exercising behaviour (not import tests); results reported with actual pass/fail output. | ☐ |
| X6 | Docs/explain/tooltips updated for every new figure (what / formula / read / caveat). | ☐ |

## 9. Open items, discrepancies and dependencies in the user's text (recorded, NOT resolved)

| ID | Item | Why it matters |
|---|---|---|
| O1 | The spec says run locally on **127.0.0.1:8095**, but that port is the **production** `quant_markets.service` on this machine. | Needs a decision (use another port, as I had planned) before G1-S5a. |
| O2 | "Final code location": the RAG plan names `/home/joey/Projects/energy_market_intelligence` as where the service and ingestion go, while earlier in this session the user said `henry_hub_atomic_agents` is the "true final source of truth" and is pushed with `gh`. G1 targets `markets_hub` (in henry_hub_atomic_agents) and `feat/lng-forward`. | Determines where each part is committed and pushed (section 10). |
| O3 | The user's text says graph nodes for "all 7 elements" but lists **6 edge lines** (LNG exports appears only as the calibrator in N1d). | Confirm whether LNG exports needs its own node and edge. |
| O4 | Ethane conversion: the user's text says **~0.0664 MMBtu/gal**; the existing code uses **0.0665** (`ETHANE_MMBTU_PER_GAL`). | Pick one value; B2. |
| O5 | The matrix specifies **Bcf/month** for LNG exports and border volumes; the existing data are **MMcf/month** as EIA publishes. | Unit presentation/consistency. |
| O6 | The G2 requirement says the section must show what **actually influences the forward price**. The page's Henry Hub forward curve is currently a **market quote** (NYMEX via Yahoo) and the LNG forward cost is HH × 1.15 + 2.50; no fundamentals model currently produces or adjusts a forward price. | Need to know whether G2 means (a) showing which elements feed which calculation as it is, or (b) building a fundamentals-to-price model. The matrix in section 6 (e.g., "Forward Pricing Role", "Forward_Pricing_Model") implies a forward-pricing engine that consumes these inputs; none exists in the repo today. |
| O7 | The LNG feedgas and ethane items depend on feeds that are not currently available (AIS, ERCOT telemetry, EBB scrapers, ethane price). F14 asks which feeds exist; ethane/Conway/NGL prices have no free official source (verified earlier this session). | Blockers to be stated exactly if unresolvable; "working form" is the directive (G3). |
| O8 | quant.joeysvault.app is behind Cloudflare Access (HTTP 403); its LNG content cannot be checked without access. | S4 stays UNKNOWN. |
| O9 | The LNG spec file `docs/LNG_FORWARD_SPEC.md` does not exist (S5). | Needed only if the `claude -p` background command is to be used. |
| O10 | Phase 2 says to place the service inside `/home/joey/Projects/energy_market_intelligence`; that repo currently holds a synthetic-data curriculum project (earlier assessment) and no service. | Context for O2. |
| O11 | The heading **"Frac spread: ethane vs Henry Hub"** appears alone at the top of the user's earlier message (it is the title of an existing page panel). Not stated whether it is its own ask. | AD5; B5 covers only the panel's current state (pending on ethane). |
| O12 | The patch the user calls **`0002-lng-forward-knowledge-library-ollama.patch`** was **not found** on this machine (searched the repo and `/home/joey` to depth 4). Only `~/Downloads/0001-feat-LNG-forward-price-curve-US-Gulf-FOB-cost-plus-f.patch` exists. | AD6 can only be recorded from the user's one-line description until the file is provided. |
| O13 | **Tension to resolve:** AD6 has Ollama and the knowledge library setting LNG-forward inputs (k and L, "quote-grounded"), while V2 / R1.8 / F11 say forward-pricing code must never read LLM-generated text. | Needs a rule for how a verbatim quote from the library may set a constant without LLM output entering the price. |
| O14 | `markets_complete.txt` (cited as evidence for AD1, lines 221-227 and 252-256) and "command #4 earlier" (AD8) are **not available** to me. | AD1 was re-verified from the live payload instead; AD8's exact text is unknown. |
| O15 | **Duplicate/overlapping implementation:** `~/Downloads/0001-...patch` (author jmpsu, trailer "Claude Opus 5.5", dated 2026-11-17 10:40Z) implements the same G1 curve and touches `markets_engine.py`, `web/app.js`, `web/index.html` and a **new `tests/test_lng_forward.py`**, the same files and the same test filename as my uncommitted `feat/lng-forward` work. | Choose one implementation or merge; applying both would conflict. See section 13. |
| O16 | `docs/DRILLDOWN_SPEC.md` repeats the **127.0.0.1:8095** local-run instruction (production port, see O1) and allows `--no-verify` "only if it [the hook] fails on its own syntax error". The hook's syntax error was fixed earlier in this session, so it should not be needed. | Verification items D-V5 and D-V6. |

## 10. Final gate (all must be true for the goal to be complete)

- ☐ Every row in sections 2-8 **and 11-13** is ☑ in I, T and P, or is explicitly recorded as BLOCKED with the exact blocker and the command that would activate it when the dependency exists.
- ☐ All work is committed on the agreed branch (`feat/lng-forward` for G1) and **pushed** to the agreed remote (decision O2).
- ☐ The **full test suite** passes in one complete run (count and tail reported), including the new tests for G1-G6.
- ☐ A **browser-level verification** against the running site passes (the verification script in `scripts/verify_tooltips.py`, extended for the new panels).
- ☐ The deployed site (markets.joeysvault.app) shows: the LNG forward curve beside the Henry Hub forward curve; the fundamentals section organised by what influences the forward price; the 7 element rows with value, frequency, collector status and payload hash; and, if G6 is in scope, the chat bar.
- ☐ A final report lists what existed, what was built, constants and formulas, test output and screenshot paths.

## 11. Additions requested by the user (gaps they found in the first version of this checklist)

User's message: "Missing from docs/GOAL_CHECKLIST.md" (8 items). Recorded as the user gave them; status columns follow the same I / T / P gates.

| ID | Missing item (user's words) | Evidence the user gave | What I verified | I | T | P |
|---|---|---|---|---|---|---|
| AD1 | **The Demand and Crude-and-carbon groups.** "The live section has two driver groups that aren't among the 7 elements. Nothing says whether they stay, move or go, and G2 (the section shows only what influences the forward price) depends on that." Requirement: decide and record the disposition of each group (stay / move / go) and reflect it in the section. | `markets_complete.txt` lines 221-227 (`Demand` / `Demand Industrial` / `Demand PowerBurn`) and 252-256 (`Crude and carbon` / `Crude WTI Spot` / `Power CO2 AllowancePrice`) | File not found (O14). Live payload confirms both groups: Demand = Demand_Industrial, Demand_ResComm, Demand_PowerBurn; Crude and carbon = Crude_WTI_Spot, Power_CO2_AllowancePrice. In the engine, **WTI feeds a calculation** (`ngl_to_wti_pct`); the three Demand agents and CO2 appear only in the display groups. | ☑ | ☑ | ☐ |
| AD2 | **No Waha price collector.** "B2 needs Waha, and there's no collector or open item for it." Requirement: a Waha price collector, or a recorded blocker with the exact reason. | Pasted text: `regional gas hub prices (Henry Hub / Waha)`; "the 19 uncollected sources list has no Waha agent." | Confirmed: `Waha` appears nowhere in tracked code, roster or config, and the 19 uncollected-source rows in the earlier gaps report contain no Waha agent. | ☑ | ☑ | ☐ |
| AD3 | **T&F cost has no value.** "B2 and B3 use it, but there's no named constant or open item." Requirement: a named, labelled constant for the transportation-and-fractionation cost (or a recorded open item stating the missing value). | Pasted text: `When Ethane_Value < (Gas_Hub_Price + T&F_Cost)` | Confirmed: no `T&F` / transport-and-frac constant exists in the repo. No value is given anywhere in the user's text. | ☑ | ☑ | ☐ |
| AD4 | **The cited references aren't recorded** (needed so N3 and V1 have sources to cite). | Pasted lines 95, 96, 111 | Recorded below (table AD4-refs). | ◐ | n/a | ☐ |
| AD5 | **The stray "Frac spread: ethane vs Henry Hub" heading isn't recorded.** "B5 covers the panel's state, but not whether this heading is its own ask." | Pasted line 3 | Recorded as open item O11; it is the title of the existing frac-spread panel (currently pending on ethane). | ◐ | n/a | n/a |
| AD6 | **Ollama and the knowledge library setting the LNG forward inputs** (k and L, quote-grounded). The user's patch: `0002-lng-forward-knowledge-library-ollama.patch`. | none beyond the patch name and this description | Patch file not found (O12). Conflicts in principle with V2 / R1.8 / F11 unless the quote-grounding rule is defined (O13). | ☑ | ☑ | ☐ |
| AD7 | **Drill-down calculation panel, levels L0-L4** (`docs/DRILLDOWN_SPEC.md`). | the spec file | The file exists (4,185 bytes, untracked, dated 2026-11-17 05:34). Its requirements are recorded in section 12. | ☐ | ☐ | ☐ |
| AD8 | **EMI ↔ knowledge-library alignment** ("command #4 earlier"). "Partly overlaps V1 and R1.3." | none | The text of command #4 is not available to me (O14). Overlap noted: V1 (corpus completeness, hash tracking) and R1.3 (parse all PDFs/resources in `/home/joey/Projects/energy_market_intelligence`). | ☐ | ☐ | ☐ |

**Table AD4-refs: references cited in the user's pasted text (as given):**

| Where cited | Reference |
|---|---|
| Feedgas text, pipeline EBBs bullet [1] | EIA natural gas data: https://www.eia.gov/naturalgas/data.php |
| Feedgas text, pipeline EBBs bullet [2] | FERC major pipeline projects (pending): https://www.ferc.gov/industries-data/natural-gas/major-pipeline-projects-pending |
| Feedgas text, AIS bullet [1] | Kpler, modelling and simulating vessel emissions from terrestrial AIS data: https://www.kpler.com/publications/modelling-and-simulating-vessel-emissions-in-real-time-based-on-terrestrial-ais-data |
| Feedgas text, mass-balance step 1 [1] | NGI glossary, feed gas: https://naturalgasintel.com/glossary/feed-gas/ |
| Feedgas text, mass-balance step 1 [2] | Gas Processing News, simplified simulation model for an LNG terminal (2022-06): https://www.gasprocessingnews.com/articles/2022/06/simplified-simulation-model-for-an-lng-terminal/ |
| RAG plan, phases 1-3 | Citations to fragments of markets.joeysvault.app page text (the page's own "Source availability transparency", "Vector knowledge library", hover/pin hint and frac-spread / forward-curve text); the same plan names `/home/joey/Projects/energy_market_intelligence` as the corpus location. |

Note: these references are recorded so they can be cited; they have **not** been fetched or verified by me, and I make no claim about their content beyond the user's text.

## 12. AD7 detail: multi-level price/calculation drill-down (from `docs/DRILLDOWN_SPEC.md`)

Spec heading: "TASK: Multi-level price/calculation drill-down for markets.joeysvault.app". Preamble: "Work autonomously; ask nothing. Read markets_hub.py, web/app.js, web/index.html, web/app.css, markets_engine.py and the tests first. Base all names and paths on what exists, not on guesses."

| ID | Requirement (spec wording preserved) | I | T | P |
|---|---|---|---|---|
| D1 | **Goal:** "Every number on the page is clickable. Clicking it opens a drill-down panel that walks one level at a time, from the displayed figure down to the raw stored inputs. There should be no ambiguity anywhere about how any number was computed." | ☐ | ☐ | ☐ |
| D-L0 | **L0 Displayed value:** label, value, unit, as-of cutoff. | ☐ | ☐ | ☐ |
| D-L1 | **L1 Definition in math notation** (KaTeX, **vendored locally into `web/vendor`; no CDN**), e.g. `%WTI_{C3} = \frac{(P_{C3}/100)\cdot 42}{P_{WTI}} \times 100`; each symbol gets a legend line (`P_{C3}` = Mont Belvieu propane spot, ¢/gal; 42 = gal/bbl). | ☐ | ☐ | ☐ |
| D-L2 | **L2** the same formula with the actual numbers substituted, then each arithmetic step on its own line with intermediate results, e.g. `= \frac{(106.1/100)\cdot 42}{89.62}\times 100 = \frac{44.562}{89.62}\times 100 = 49.72\%`. | ☐ | ☐ | ☐ |
| D-L3 | **L3** each operand is itself clickable. A derived operand (SMA50, EMA12, RSI, MACD, Fib level, spread, totals) opens its own L1/L2, recursively. Window-based operands (SMA, EMA, RSI, Bollinger, swing high/low) list **every input row in the window as a table**, with the sum/mean/σ shown. | ☐ | ☐ | ☐ |
| D-L4 | **L4 leaf** = raw input row from the PIT DB: `agent_id`, `series`, `value`, `unit`, `t_target`, `t_published`, `t_retrieved`, `t_available`, `provenance`, `quality_status`, `source_id`, `intended_source`, `raw_payload_hash`. If the payload is archived, add a link to view the raw bytes (**read-only endpoint**). | ☐ | ☐ | ☐ |
| D-P | **Pending or missing operand:** the leaf states `"no collector: <agent_id>"` and the parent shows `"withheld"`. "Never fill in a value." | ☐ | ☐ | ☐ |
| D-A1 | **Server-side trace:** generated by the same code path that computes the value, not reconstructed in JS. A trace object (`op`, `formula_tex`, `symbols`, `operands[]`, `value`, `unit`, `rows[]`) alongside each computed number. | ☐ | ☐ | ☐ |
| D-A2 | **New read-only endpoint**, e.g. `GET /api/derivation?metric=<id>&product=<id>&timeframe=<id>&as_of=<iso>`, returning the full tree; **lazy-load deeper levels** if a tree is large (windows of 200+ rows). | ☐ | ☐ | ☐ |
| D-A3 | **Respect the PIT cutoff:** every leaf has `t_available <= cutoff`; show the cutoff at L0. | ☐ | ☐ | ☐ |
| D-A4 | **Coverage: every number currently rendered:** prices; 1d/5d change; SMA50/200; trend; MA regime; RSI14; MACD line/signal/hist; Bollinger bandwidth/squeeze; triangle lines; divergences; swing high/low; every Fib level; retraced %; golden-ratio proximity; %WTI; frac spread; hub spread; forward-curve points and regime/M2−M1; shale total; storage total; HDD anomaly; flow-meter count; notice counts; force-majeure count; seasonal band avg/min/max; every driver row; every map node value. | ☐ | ☐ | ☐ |
| D-U1 | **UI:** dotted-underline numbers become **buttons (keyboard focusable)**. Click → side panel showing L0-L2. Click an operand → push a level. | ☐ | ☐ | ☐ |
| D-U2 | A **breadcrumb trail** (e.g. `L0 › %WTI › P_WTI › row 2026-11-11`) jumps to any level. **Back** button and **Esc** step up one level; **Esc at L0 closes** the panel. | ☐ | ☐ | ☐ |
| D-U3 | **One level per view; never dump the whole tree at once.** | ☐ | ☐ | ☐ |
| D-U4 | **Existing hover tooltips stay as they are.** | ☐ | ☐ | ☐ |
| D-V1 | **Verification 1:** unit test, for every metric: recompute the value from the L4 leaves using only the formula in the trace, and assert it equals the displayed value to its displayed precision. | ☐ | ☐ | ☐ |
| D-V2 | **Verification 2:** test that every leaf has `t_available <= cutoff`. | ☐ | ☐ | ☐ |
| D-V3 | **Verification 3:** test that pending operands produce `"withheld"`, never a number. | ☐ | ☐ | ☐ |
| D-V4 | **Verification 4:** the full existing suite passes (`source .venv/bin/activate && python -m pytest -q`). | ☐ | ☐ | ☐ |
| D-V5 | **Verification 5:** run the service locally on `127.0.0.1:8095` (see O1/O16); headless Chrome clicks the %WTI number and drills to the WTI leaf, then RSI14 down to a window row; screenshots saved to `docs/poc/drilldown_*.png`. | ☐ | ☐ | ☐ |
| D-V6 | **Verification 6:** commit on a **new branch `feat/drilldown`** (git commit; "the pre-commit hook may still be broken, so use --no-verify only if it fails on its own syntax error"), then push. | ☐ | ☐ | ☐ |
| D-V7 | **Verification 7, report:** files changed, the endpoint schema, the test results tail, screenshot paths, and "any number you could not trace to raw inputs (list it, do not hide it)". | ☐ | ☐ | ☐ |

## 13. Overlap with the `0001` patch (recorded only; nothing applied)

`/home/joey/Downloads/0001-feat-LNG-forward-price-curve-US-Gulf-FOB-cost-plus-f.patch` (9,436 bytes): author `jmpsu`, trailer `Co-Authored-By: Claude Opus 5.5`, dated 2026-11-17 10:40:10Z, subject "feat: LNG forward price curve (US Gulf FOB cost-plus from HH futures)". Body: `P_LNG,m = 1.15 * HH_m + 2.50 USD/MMBtu, M1-M12, derived from the measured Henry Hub forward points; pending when no HH futures. New panel next to the HH forward curve. JKM/TTF netback marked pending collectors.` Files: `markets_engine.py` (+30), `tests/test_lng_forward.py` (+23, new), `web/app.js` (+10), `web/index.html` (+1).

| ID | Item | Status |
|---|---|---|
| P1 | Decide which G1 implementation is kept: this branch's version (config file, pure module, TTF/EUR-USD collector, netback, `.explain`, 18+ tests) or the patch's smaller version (no collector, netback pending), or a merge. Both create `tests/test_lng_forward.py` and edit the same three source files. | ☑ resolved: this branch's implementation kept; 0002 parameter-sourcing ported (lng_evidence.py); 0001 not applied |
| P2 | Whichever is kept must still satisfy G1-S2 to G1-S6 (section 3), including `.explain` entries and the full-suite run. | ☐ |

14. Resolutions for O12, O13, O14 (updated 2026-11-17T11:53:01Z)

ID: O12-R
Resolution: ~/Downloads/0002-lng-forward-knowledge-library-ollama.patch present; sha256 23b703139c45f43b605c3217d629b835eee1ad79c3ed8301a869ebe732b1125d
  (expected 23b703139c45f43b605c3217d629b835eee1ad79c3ed8301a869ebe732b1125d). Contents: lng_evidence.py (new, +167),
  markets_engine.py (+28/-9), tests/test_lng_evidence.py (new, +57), web/app.js (+8). Applies on top of 0001.
  Test result reported in chat: 199 passed, 4 deselected (live-Ollama tests).
Status: ☑ file saved and hash verified

ID: O13-R (proposed rule; the user adopts or rejects)
Rule: A knowledge-library value may set an LNG forward constant (k = HH multiplier, L = liquefaction fee) ONLY if all hold:
  (1) the quote is a verbatim substring of a stored lit_chunks row (literature_kb.verify_quote);
  (2) the number itself, or for a percentage the number x100, literally appears in that quote;
  (3) the value is inside the sanity band (k 1.05-1.30; L 1.50-4.00 USD/MMBtu);
  (4) runtime/lng_params.json available_timestamp <= the PIT cutoff.
  The LLM only identifies which number in the quote is the parameter; the value used is the number printed in the source text.
  If any check fails, the labelled default assumption (k 1.15, L 2.50) is used. No generated text enters the price.
Effect: reconciles AD6 with V2 / R1.8 / F11.
Status: ☑ adopted by user 2026-11-17T11:56:46Z

ID: O14-R
Resolution: markets_complete.txt regenerated: markets_complete.txt generated 2026-11-17T11:53:01Z from https://markets.joeysvault.app release v1.0.5 commit 5989f7ad159bfb7352a9eb7bbfd596070b9d1a23; 1208 lines. Sections: visible page text, .explain hover text,
  sources with no raw_payload_hash, products with no price, platform counts. Path: ~/Projects/henry_hub_atomic_agents/markets_complete.txt.
  "Command #4" is the EMI alignment script in the Claude chat of 2026-11-17: it embeds every .md/.py/.ipynb/.csv/.json/.yml file in
  /home/joey/Projects/energy_market_intelligence with nomic-embed-text, scores each against kb_nodes and lit_chunks, and writes
  ~/emi_alignment.tsv (labels: overlaps / complements / new to library; cutoffs 0.75 / 0.55, uncalibrated).
Status: ☑ markets_complete.txt present  ☑ command #4 run (840 files -> ~/emi_alignment.tsv: complements library 580, overlaps library 260)

## 15. Implementation log (evidence per row; marks above are updated in place)

Written by the implementation run of docs/IMPLEMENT_GOAL_CHECKLIST.md. Each entry: row IDs, what was done, evidence, and any BLOCKED reason with the command that activates it.

### 2a/2b: P1/O15, G1 and G1-*, AD6 (implemented 2026-11-17)

- **P1/O15:** kept this branch's implementation (`lng_config.py`, `lng_forward.py`, TTF/EUR-USD collector, netback, `.explain`); 0001 not applied; the knowledge-library parameter sourcing from the 0002 patch was ported as `lng_evidence.py` plus `lng_forward.build(params_doc=...)`.
- **G1-S2/S2a/S2b:** `curves.lng_forward` = 1.15 × HH_m + L (L = 2.50 default), M1-M12 from the measured Henry Hub points; constants only in `lng_config.py`. Live check on port 8096: M1 HH 3.114 → FOB 6.0811 (hand: 1.15×3.114 = 3.5811, +2.50).
- **G1-S2c/S2d:** TTF monthly contracts and EUR/USD reachable on Yahoo and collected (`collectors/ttf_forward_yahoo.py`, run for real: 4 TTF months + EUR/USD stored; 8 months not listed by Yahoo (404)). Stale TTF months (Feb-27 last trade 2026-10-27, May-27 2026-09-08) are refused (MAX_QUOTE_AGE_DAYS=3), so netback shows for 2 of 12 months. **JKM not reachable** (`JKM=F` returns no data, dated JKM contracts 404): shown as `pending a collector`, nothing estimated.
- **G1-S3/S3a-c:** state.json block, 5-column panel beside the Henry Hub forward curve, three `.explain` entries (what/formula/read/caveat), PIT cutoff respected (test: quote available after the cutoff unused), provenance `extracted_estimate`.
- **G1-S4a-c:** `tests/test_lng_forward.py` (hand-computed 3 months, no values without HH points, staleness, PIT, JKM pending), `tests/test_ttf_forward_yahoo.py`, `tests/test_lng_evidence.py`. Full suite: 244 passed.
- **G1-S5a:** run locally on **127.0.0.1:8096** (8095 is the production port, O1). **G1-S5b:** `docs/poc/lng_forward.png` (headless Chrome, 40/40 checks in `scripts/verify_tooltips.py`). **G1-S5c/G1-V/G1-S6:** commit/push and live deploy happen in STEP 3. **G1-C:** superseded by the user's instruction not to launch `claude -p`; the work was executed directly.
- **AD6 / O13-R (adopted):** a library value sets `k` or `L` only if (1) the quote is a verbatim stored sentence, (2) the number (×100 for a percentage) literally appears in it, (3) it is inside the band (k 1.05-1.30, L 1.50-4.00), (4) `runtime/lng_params.json` was available at the cutoff; the stored file is re-validated at load time and any failure falls back to the labelled default with the reason. Live run of `python lng_evidence.py`: the library abstained for both parameters, so the defaults (k 1.15, L 2.50) are used and the reason is displayed.
- **DB checkpoint before state-changing runs:** `henry_hub_pit.db.pre-lng.20261117T121238Z` (integrity ok, 108,031 rows). Rollback: `DELETE FROM pit_market_data WHERE extraction_version='ttf_forward_yahoo_v1';`

### 2c: G5 (M1-M7, Module A, Module B, AD2, AD3) implemented 2026-11-17

- **Files:** `fundamentals.py` (M1-M7 classification, 5 direct inputs + 2 separate modules, per-element status/provenance/blockers, `price_path`), `lng_feedgas.py` (Module A), `frac_module.py` (Module B), `collectors/metar_ambient.py` (F5), engine blocks `fundamentals` and `modules`, panel + tooltips in `web/app.js`, 7 graph nodes in `kb_ingest.py`, `ingest.py` accepts provenance `bootstrapped_physical_proxy` (A4). Tests: `tests/test_g5_modules.py` (18), full suite 262 passed. Screenshot: `docs/poc/fundamentals.png`.
- **O4 resolved by the requirement's figure:** one constant `frac_module.ETHANE_MMBTU_PER_GAL = 0.0664`; the engine imports it (the page's earlier 0.0665 and its two tests were changed to 0.0664).
- **O6 stays OPEN and is stated on the page:** no fundamentals-to-price model exists, so every element carries `used_in_price: false`. The section shows the drivers as context; it does not move the Henry Hub forward curve or the LNG forward. Building such a model is a decision for the user.
- **A1/A4/F0/F11/F12:** Module A does not import the pricing engine (tested by AST) and refuses price, basis, charter and demand-weather inputs (`assert_inputs`). Output series `lng_feedgas_p10/p50/p90` stored as `Agent_LNGFeedgas_P10/P50/P90`, provenance `bootstrapped_physical_proxy`. Live run 2026-11-17: p10 16.06 / p50 18.18 / p90 20.89 Bcf/d (anchor Aug-2026 exports 16.28 Bcf/d, horizon 3.09 months, 1,000 iterations).
- **What Module A is NOT:** it is an EIA-monthly-anchored bootstrap, not the full physical proxy. EBB, AIS, ERCOT and thermal inputs are absent, so evidence class is `inferred_from_monthly_anchor`; the ambient METAR/wet-bulb values are shown but NOT applied. A3, F6, F7, F9, F12, F13 are therefore partial (◐).
- **BLOCKED F1** (EBB scheduled quantities): only Kinder Morgan critical-notice text is collected. Activate: write `collectors/ebb_<pipeline>.py` per pipeline (Creole Trail, Transco, Elba Express, ...), add agents to the roster.
- **BLOCKED F2** (AIS draft/berth): no AIS provider or key on this host. Activate: put `AISSTREAM_API_KEY` (or other provider key) in `~/.config/joey-secrets/`, add `collectors/ais_lng.py`.
- **BLOCKED F3** (ERCOT South/Coast load): not in the keyless EIA-930 files; the ERCOT public API needs registration. Activate: register, store key in the vault, add `collectors/ercot_load.py`.
- **BLOCKED F4** (Sentinel-2/Landsat/VIIRS): no remote-sensing access. Activate: `FIRMS_MAP_KEY` + `collectors/viirs_flare.py`.
- **BLOCKED F8** (ambient-capacity regression) and **F10** (terminal EBB table): need verified daily feedgas history / EBB scheduled quantities, which do not exist locally. Activate after F1 has collected >= 12 months.
- **F5 done:** `collectors/metar_ambient.py` collected 447 observations for 6 stations (KLCH, KCRP, KLBX, KMSY, KSAV, KNHK; 18 agents) from the free NOAA AWC API; registered in `run_all`; gatekeeper ranges added.
- **M5 / B2 / B3 BLOCKED on the ethane price and Waha.** Module B is built, hand-computed in tests, and returns `pending_collector` with the exact blockers: `Agent_NGL_MontBelvieu_Ethane` (EIA publishes no ethane spot; activate: licensed OPIS/Argus/CME feed + `collectors/ethane_<source>.py`) and `Agent_Gas_Waha_Spot` (AD2: no free Waha source; the hub price is Henry Hub until it exists). Nothing is estimated in their place.
- **AD3:** `TF_COST_USD_PER_GAL = 0.08` is a labelled ASSUMPTION (no value was supplied anywhere). `FULL_REJECTION_DEFICIT_USD_MMBTU = 1.00` is also an assumption; the +0.5..+1.5 Bcf/d swing is the requirement's own figure. Replace T&F with the actual contract rate.
- **M3 partial:** only 6 weekly storage values are stored, so no 5-year-normal deficit/surplus can be computed. Activate: backfill via `collectors/eia_storage.py` history.
- **M7 corrected:** headline is net imports (Canada in minus Mexico out), not a gross sum.
- **DB checkpoint:** `henry_hub_pit.db.pre-g5.20261117T122058Z` (integrity ok, 108,036 rows). Rollback of this section's data: `DELETE FROM pit_market_data WHERE extraction_version IN ('metar_ambient_v1','lng_feedgas_v1');`

### 2d: G2/E1-E8, AD1, N1, N2 implemented 2026-11-17 (N3 is delivered with the chat in 2e)

- **G2:** the section now opens with **what actually sets the forward prices** (P1 Henry Hub futures M1-M12, P2 k and L with their source, P3 TTF and EUR/USD, P4 shipping and regas), each tagged *market quote* or *assumption*; the seven elements follow, explicitly labelled *context, not price inputs*. Marked partial (◐) because of **O6**: no fundamentals-to-price model exists, so no element can honestly be shown as moving a price. Building one is a modelling decision for the user; the declared graph relations (N1) are ready for it.
- **E8:** every element lists the calculations it feeds today (`feeds_today`, e.g. M2 -> `derived.hdd_anomaly`, display and alert) and states `Forward price: none (checklist O6)`.
- **AD1 disposition (recorded in the payload and shown on the page):** **Demand** group = *move* (not one of the seven; feeds no calculation; residential/commercial demand enters through weather M2); **Crude and carbon** = *move* (WTI feeds the NGL-to-WTI relative-value ratio, not a gas forward price; CO2 allowance feeds nothing). Both are kept as underlying series inside a collapsed "Underlying series" block outside the fundamentals section.
- **N1/N1a-f:** 8 first-class graph nodes in `kb_nodes` (domain `fundamentals`: M1-M7 definitions + `Forward_Pricing_Model`), embedded with nomic-embed-text, and the six named edges (`feeds_supply`, `feeds_rescomm_demand`, `feeds_inventory_balance`, `calibrated_by` (M4 -> M6), `modifies_dry_gas_supply`, `feeds_net_exports`) stored as non-derived edge types that survive `rebuild_edges`. The edge legend and the `Forward_Pricing_Model` node text say they are **declared by the requirement, not measured causation, and no calculation consumes them yet**. Live ingest: 8 new nodes, 6 declared edges. Checkpoint `henry_hub_pit.db.pre-kbnodes.20261117T122728Z`.
- **N2:** hover/pin tooltip on each of the 7 rows shows Current value, Frequency, Collector status (active collector / bootstrapped proxy / pending collector), Raw payload hash(es), the calculations it feeds and its blockers. Verified in headless Chrome (45/45); screenshot `docs/poc/fundamentals.png`.
- **N3 not yet done:** it needs the chat/Ollama retrieval (G6, section 2e); it will retrieve all 7 nodes and cite the PDFs under `/home/joey/Projects/energy_market_intelligence`.
