# OPENCODE DIRECTIVE: DATA GAP AUDIT & RESOLUTION

## 1. MANDATORY PRE-FLIGHT GUARDRAILS (EXECUTE BEFORE WRITING ANY CODE)
Before creating any file, migration, collector, or SQL query, run these read-only discovery checks and adhere strictly to the rules below:

1. **Identify the True Superset Branch & Working Baseline:**
   Run:
   ```bash
   git fetch origin --prune --tags && \
   for b in \$(git for-each-ref --format='%(refname:short)' refs/heads/ refs/remotes/origin/); do
     echo "\$b: (git rev-list --left-right --count HEAD...b)"
   done
   ```
   * Always work from the active superset branch (`quant-hub-build`), never an outdated branch.
   * **NEVER commit or push directly to `main`.** All changes must be committed to a feature branch off `quant-hub-build` and merged via Pull Request (`gh pr create`).

2. **Verify Existing Code, Catalogs & Database Schema First:**
   Run:
   ```bash
   grep -rn "series_catalog\|PLANNED_GAP\|is_active" --exclude-dir=.git --exclude-dir=__pycache__ . && \
   sqlite3 "file:\$(grep -h '^DB_PATH=' /opt/quant-hub/shared/.env .env 2>/dev/null | head -n1 | cut -d= -f2)?mode=ro" \
     ".schema" "SELECT agent_id, series_id, source_id, domain, frequency, unit, is_active, observation_count FROM series_catalog ORDER BY is_active ASC, domain, agent_id;"
   ```
   * **NEVER duplicate existing infrastructure.** `series_catalog`, its auto-sync SQLite triggers (`migrations/0003_series_catalog_sync.sql`), `series_catalog.py`, and `/api/series-catalog` already exist. Reuse them.
   * **NEVER guess column names or `DB_PATH`.** Resolve `DB_PATH` from `/opt/quant-hub/shared/.env` (or environment) and verify exact column names (`agent_id`, `target_timestamp`, `available_timestamp`, `unit`) against `.schema` first.
   * **NEVER modify production databases during testing.** Copy `DB_PATH` to a temporary path (`/tmp/test_gap_audit.db`) for all migration and collector tests, then delete the temporary file.

3. **Keep Mutations Small, Atomic & Verifiable:**
   * Do not chain unverified writes, commits, and pushes into a single shell command. Make one focused change at a time, run `.venv/bin/pytest` on the affected test suite, and verify `git diff` before committing.

---

## 2. TARGET DATA GAPS TO RESOLVE

Inspect `series_catalog` (`is_active = 0` or missing expected domain feeds) and `docs/MISSING_DATA_REVIEW.md` / `agents_roster.json`, then resolve each confirmed gap in priority order:

1. **Year-Round Prior-Year NOAA CPC Revision Capture (`collectors/run_all.py`):**
   * Remove any `if now.month == 1:` restriction gating `cpc_heating_prev_year` and `cpc_cooling_prev_year` so NOAA CPC historical HDD/CDD revisions are ingested year-round into `pit_market_data` as new PIT vintages.
   * Verify with `.venv/bin/pytest -q tests/test_cpc_collector.py`.

2. **Explicitly Register Unconfigured / Missing Feeds in `series_catalog` (`is_active = 0`):**
   * Ensure all known downstream data gaps (e.g., Conway propane, Mont Belvieu ethane / normal butane / isobutane / natural gasoline, JKM forward, AECO basis, Waha basis) are explicitly registered in `series_catalog` with `is_active = 0` and a clear `source_id` marker (e.g., `planned_gap`) so downstream modules (`markets_engine.py`, `frac_module.py`, `lng_feedgas.py`) distinguish unconfigured feeds from silent zero-row failures.
   * Add a helper in `series_catalog.py` (e.g., `feed_status(conn, agent_id)`) returning structured status (`ACTIVE`, `INACTIVE_OR_PLANNED_GAP`, `UNREGISTERED`, `STALE`) based on `FREQUENCY_EXPECTED_DAYS`.

3. **Implement Free/Public Collectors for Remaining Retrievable Series:**
   * Check `docs/MISSING_DATA_REVIEW.md` and `agents_roster.json` for any roster agents with `observation_count = 0` that have an available free public endpoint (EIA API v2, NOAA, CME delayed, or public EBB).
   * Implement each collector using `ingest.py` (`gatekeeper` validation, raw payload archiving via `ingest.archive_payload()`, explicit `target_timestamp` and `available_timestamp`), register it in `collectors/run_all.py`, and add unit tests with fixture payloads under `tests/`.

4. **Clean Up Legacy `unit=NONE` Seed Rows in Queries:**
   * Ensure downstream queries and `series_catalog` sync logic ignore or mark legacy `unit IS NULL` / `unit = 'NONE'` seed entries (`is_active = 0`) so they never pollute live calculations.

---

## 3. ACCEPTANCE & DELIVERY CRITERIA
Before finishing, verify all items below on your feature branch:
1. Run full relevant test suite: `.venv/bin/pytest -q tests/test_series_catalog.py tests/test_cpc_collector.py tests/test_markets_engine.py tests/test_quant_hub.py`.
2. Verify `git status -s` shows only intentional, clean changes and `release/version.py` is only bumped if requested.
3. Push the feature branch to `origin` and open a Pull Request targeting `quant-hub-build` (or `main` via PR) summarizing every closed data gap and its verification output.
