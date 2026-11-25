<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**This project has a knowledge graph. Start with the code-review-graph
MCP tools to narrow scope, then read the source.** The graph is cheaper than scanning files and
gives you structural context (callers, dependents, test coverage) that file search cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes_tool(include_source=True, expand_neighbors=True)`
- **Understanding impact**: `get_impact_radius_tool` instead of manually tracing imports
- **Code review**: `detect_changes_tool` + `get_review_context_tool` instead of reading entire files
- **Finding relationships**: `query_graph_tool` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview_tool` + `list_communities_tool`

### Verify in the source

- Answer from `include_source=True, expand_neighbors=True`; read a file only if truncated.
- Do not change code from graph output alone: for any non-trivial change,
  read the implementation and the relevant tests before concluding.
- Verify the exact source when touching behavior, database logic, migrations, retries, fallbacks,
  recovery, or compatibility code.
- When the graph and the source disagree, the source wins. The graph may be stale.
- An empty graph result can mean "not indexed" or "not statically visible", not "does not exist".

### Key Tools

| Tool | Use when |
| ------ | ---------- |
| `detect_changes_tool` | Reviewing code changes — gives risk-scored analysis |
| `get_review_context_tool` | Need source snippets for review — token-efficient |
| `get_impact_radius_tool` | Understanding blast radius of a change |
| `get_affected_flows_tool` | Finding which execution paths are impacted |
| `query_graph_tool` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes_tool` | Finding functions/classes by name or keyword |
| `get_architecture_overview_tool` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes_tool` for code review.
3. Use `get_affected_flows_tool` to understand impact.
4. Use `query_graph_tool` pattern="tests_for" to check coverage.
<!-- /code-review-graph MCP tools -->

## Verified environment and tooling
- Always run Python with `/root/henry_hub_atomic_agents/.venv/bin/python` and tests with `/root/henry_hub_atomic_agents/.venv/bin/pytest`.
- If graph MCP tools are unavailable, use the equivalent CLI: `code-review-graph query`, `code-review-graph impact`, `code-review-graph search`, `code-review-graph detect-changes`, and `code-review-graph update --brief`.
- Persist verified schema/collector/milestone facts through `mcp-memory-libsql` when its tools are exposed (`LIBSQL_URL=file:/root/.local/share/opencode/agent-memory.db`).
- Apply domain skills only to their matching subsystems:
  - LNG/supply/geospatial/routing: `cheniere-lng-shock`, `germany-lng-model`, `lng-arbitrage`, `lng-supply-chain`, `lng-supply-risk`, `lng-geoenv`, `valhalla-web-app`.
  - Bitemporal SQLite and recursive graph traversal: `/root/agent-tools/typegraph`.
  - Hybrid retrieval and reranking patterns: `/root/agent-tools/NexusRAG`.
  - Architecture/report diagrams: `/root/diagram-design/skills/diagram-design`.
