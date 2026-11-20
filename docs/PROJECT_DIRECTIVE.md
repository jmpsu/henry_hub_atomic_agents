# AUTHORITATIVE PROJECT DIRECTIVE: HENRY HUB / NGL INTELLIGENCE PLATFORM

This project must deliver the complete originally intended, operational Henry Hub and NGL market intelligence platform. Documentation, plans, status reports, and partial implementations do not constitute completion.

## MANDATORY FIRST ACTION
Before changing code:
1. Read every project-level instruction file, specification, requirements document, acceptance criterion, architecture document, and relevant artifact.
2. Inspect the complete repository, including tracked and untracked files, existing agents, scripts, databases, tests, deployment configuration, and the artifacts directory.
3. Recover the original intended functionality from the actual project sources. Do not silently discard, simplify, replace, or redefine requirements.
4. Identify implemented, partially implemented, missing, broken, and unverified capabilities.
5. Maintain a traceable requirement-to-implementation-to-test matrix.

## REQUIRED SYSTEM CAPABILITIES

### 1. Ollama intelligence layer
Ollama must operate as an integrated local intelligence service used by the agent system, not as an isolated demonstration or optional future feature.

Inspect the actual installed models and existing configuration. Use the project's designated model where available. Do not assume a Llama model if the configured model is Qwen or another model.

Implement and test the appropriate integrations for:
- Agent reasoning and task assistance.
- Structured extraction, classification, normalization, and validation.
- Anomaly detection and data-quality investigation.
- Agent-to-agent knowledge exchange and synthesis.
- Research synthesis grounded in retrieved source data.
- Embedding generation and semantic retrieval where supported by the selected model.
- Error diagnosis and bounded self-healing assistance.

All model calls must have explicit configuration, timeouts, error handling, logging, and deterministic fallback behavior where necessary. Never report a model integration as operational merely because the Ollama daemon responds.

### 2. Graphical Vector Knowledge Library
Implement the actual graphical, persistent, searchable knowledge library intended by this project. Do not substitute a conventional SQL query or a text-only report and call it complete.

It must support:
- Ingestion of relevant research, documents, source material, agent findings, and validated market intelligence.
- Text extraction, chunking, metadata, source attribution, and provenance.
- Vector embeddings and persistent vector indexing.
- Semantic search and retrieval by agents and authorized research workflows.
- Relationships between documents, market concepts, data series, agents, findings, and derived features where required by the original specifications.
- A graphical interface for exploring, searching, inspecting, and navigating the knowledge.
- Persistent knowledge across runs, with updates, deduplication, and traceable source references.
- Ollama integration for supported embedding and synthesis operations.

Inspect existing dependencies and architecture before choosing or introducing a vector database. Do not invent a technology choice or claim an integration exists without verifying it.

### 3. Agent integration
Agents must actually use the shared intelligence and knowledge infrastructure. Implement working interfaces, shared schemas, retrieval, persistence, provenance, error handling, and collaboration. Verify actual execution rather than relying on configuration files or documentation.

### 4. Market data and quantitative integrity
Preserve and enforce point-in-time correctness. Maintain the distinction between target_timestamp and available_timestamp. Prevent look-ahead leakage in feature generation, retrieval, model inputs, training, and backtesting. Preserve source provenance and validation.

### 5. End-to-end operation
The intended pipeline must work as an integrated system:
source acquisition -> extraction -> normalization -> validation -> point-in-time database -> knowledge ingestion and vector indexing -> semantic retrieval -> agent collaboration -> Ollama-assisted synthesis -> quantitative research -> backtesting -> persistent, traceable knowledge.

## EXECUTION RULES
- Build the missing functionality. Do not spend the session merely writing plans, audits, documentation, or progress reports.
- Do not mark a requirement complete without executable evidence.
- Do not fabricate test results, runtime status, data coverage, integrations, or deployment success.
- Do not replace real integrations with mocks and report them as production-ready.
- Preserve existing working functionality and user data.
- Do not delete databases, snapshots, artifacts, backups, or project files.
- Do not perform destructive migrations or overwrite user work without explicit authorization.
- Do not expand scope beyond the original requirements.
- Run relevant tests after each material change and the complete test suite before declaring completion.
- Fix failures rather than hiding, skipping, or weakening tests.
- If an external dependency or credential blocks a requirement, implement everything possible and identify the exact blocker and evidence.

## ACCEPTANCE REQUIREMENTS
The project is complete only when:
1. Every original requirement has a traceable implementation and passing verification, or a clearly evidenced external blocker.
2. Ollama is demonstrated working through real agent workflows.
3. The Graphical Vector Knowledge Library is demonstrated ingesting, persisting, retrieving, and graphically displaying actual project knowledge.
4. Agents demonstrably share and retrieve persistent knowledge.
5. The end-to-end pipeline executes against real project data.
6. Point-in-time and no-look-ahead tests pass.
7. Relevant tests pass and deployment instructions match the actual implementation.

- Do not delete databases, snapshots, artifacts, backups, or project files.
- Do not perform destructive migrations or overwrite user work without explicit authorization.
- Do not expand scope beyond the original requirements.
- Run relevant tests after each material change and the complete test suite before declaring completion.
- Fix failures rather than hiding, skipping, or weakening tests.
- If an external dependency or credential blocks a requirement, implement everything possible and identify the exact blocker and evidence.

## ACCEPTANCE REQUIREMENTS

The project is complete only when:
1. Every original requirement has a traceable implementation and passing verification, or a clearly evidenced external blocker.
2. Ollama is demonstrated working through real agent workflows.
3. The Graphical Vector Knowledge Library demonstrably ingests, persists, retrieves, and graphically displays actual project knowledge.
4. Agents demonstrably share and retrieve persistent knowledge.
5. The end-to-end pipeline executes against real project data.
6. Point-in-time and no-look-ahead tests pass.
7. Relevant tests pass and deployment instructions match the actual implementation.

At completion, report every requirement with its source, implementation location, exact test or runtime evidence, and status. Separate VERIFIED, PARTIAL, BLOCKED, and NOT IMPLEMENTED. Never equate documentation with implementation.

Begin by inspecting the repository and original requirements, then proceed directly to implementation.
