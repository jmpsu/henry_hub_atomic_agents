# QUANT HUB ENHANCEMENT SPECIFICATION

## 1. Architectural Baseline
- Inspect existing files: kb_ingest.py, agents/memory.py, agents/llm.py, agents/workers.py, command_hub.py, scripts/acceptance.py.
- Run baseline acceptance tests: python scripts/acceptance.py and record the result.
- Maintain compatibility with existing SQLite schemas and Chroma vector storage.

## 2. LlamaIndex Multi-Engine Retrieval Hub
Implement agents/retrieval_hub.py supporting ingestion of news articles, scientific journals, and reports, exposing a unified interface with 6 query engine modalities:
1. Knowledge graph vector-based entity retrieval (DEFAULT if no query engine option is provided)
2. Knowledge graph keyword-based entity retrieval
3. Raw vector index retrieval
4. Custom combo query engine (vector similarity + KG entity retrieval)
5. KnowledgeGraphQueryEngine
6. KnowledgeGraphRAGRetriever

Provide a factory interface:
get_query_engine(engine_type="kg_vector", **kwargs)

## 3. Power, Natural Gas & Cross-Commodity Modeling
Implement agents/quant_commodities.py:
- Power & Gas Market Dynamics: Henry Hub spot & forward curve analysis, basis differentials (Waha, Houston Ship Channel, Transco Zone 6).
- Heat rate and spread economics: Spark Spread, Clean Spark Spread, Dark Spread.
- Regional ISO/RTO nodes: ERCOT, PJM, MISO, CAISO, NYISO.
- EIA storage cycle impacts, pipeline flows, LNG export terminal demand.
- Cross-commodity exposure: Crude (WTI/Brent), Refined Products, Carbon allowances.

## 4. Quantitative Risk Management Engine
Implement agents/quant_risk.py:
- Value at Risk (VaR): Parametric VaR, Historical Simulation VaR, Monte Carlo VaR, and Expected Shortfall (CVaR).
- Stress Testing & Scenario Analysis: Winter Storm Uri freeze scenarios, pipeline outage shocks, multi-factor commodity price shifts.
- Capital & Margin: Initial/variation margin modeling, liquidity buffer estimation.

## 5. Integration & Acceptance Testing
- Connect retrieval and risk engines into agents/workers.py and agents/memory.py.
- Add test coverage to scripts/acceptance.py covering:
  - Ingestion and querying across all 6 engine types.
  - Spark spread and basis differential calculations.
  - Parametric, Historical, and Monte Carlo VaR execution.
- Run python scripts/acceptance.py. Diagnose and fix any failures until all tests pass.
- Commit all changes to git on the quant-hub-build branch.
