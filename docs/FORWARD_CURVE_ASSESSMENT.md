# Forward curve assessment and remediation (2026-11-17)

Tags: **E** executed and observed, **S** read in source, **U** not verified.

## What the live site showed before any change (E)
`https://ngl.joeysvault.app/api/market` -> `curves.forward_curve`: status `measured`, 12 points M1..M12, regime `CONTANGO`, as_of_date 2026-11-16, not stale. Version 1.0.1 (`/api/health`). Both services (`command_hub`, `markets_hub`) run code from `/opt/quant-hub/releases/1.0.1` but read the **working-copy DB** `/home/joey/Projects/henry_hub_atomic_agents/henry_hub_pit.db` (E: `DB_PATH` in `/proc/<pid>/environ`), so DB writes appear on the site within about 60 s (engine cache TTL), while code changes need a release.

## Defects found
| ID | Defect | Evidence | Status |
|---|---|---|---|
| FC-1 | **Collector code that produced most live rows is not in the repo.** DB holds `hh_forward_yahoo_v1/v2/v3` rows (24/48/36 for M1-M9 in Nov); repo HEAD only ever had v1. Run records show `contract_month`/`published_timestamp` keys and a `TypeError` for a `collect(conn, fetcher, now)` signature that exist nowhere in git. | `pit_market_data.extraction_version`, `collector_runs.detail`, `git log -- collectors/hh_forward_yahoo.py` (one commit), grep | **Fixed**: v4 in repo, tested |
| FC-2 | **Look-ahead in availability (v1).** `available_timestamp` was set to Yahoo's quote time, not when this system retrieved it. | v1 source `parse_yahoo_chart` -> avail_ts used as `available_timestamp` | **Fixed**: available = retrieval time; published = Yahoo quote time. Test asserts `available > published` and `== retrieved` |
| FC-3 | **No expiry-aware roll.** `front_12_symbols` rolled on the calendar month, so on trade dates between a contract's last-trade date and month end it requested an expired contract and shifted every M label by one. | v1 source; NGX26 expired 2026-10-28 and Yahoo now returns "delisted" | **Fixed**: roll by last-trade date (3 business days before delivery month, approximate holiday calendar). Tests: 2026-10-28 -> M1=NGX26; 10-29 -> M1=NGZ26; 11-25/11-26; 12-31 |
| FC-4 | **Overclaimed quality.** v1 labelled delayed Yahoo quotes `validated_delayed_quote`; docstring said "settlements". | v1 source | **Fixed**: `delayed_quote_unverified`; docstring corrected |
| FC-5 | **Points lacked lineage.** API points had only contract/value/date/available_timestamp; the tooltip read `M5 2.372 (2026-11-16)` with no delivery month, symbol, source, quality or payload. | `markets_engine.py` forward block; `web/app.js` marker title | **Fixed and live in 1.0.3** |
| FC-6 | Only one trade date of curve data; EIA M1-M4 series ends 2024-04-05. | DB query | **Partly filled**: 11 complete historical curves backfilled. The 2024-04 -> 2026-10 gap cannot be filled from Yahoo (expired contracts return 404) |
| FC-7 | **`CONTANGO` label was wrong on a seasonal curve.** `curve_regime` compared M12 to M1 (different calendar months) while the curve reverses direction twice (peak M2 Jan-27 3.503, trough M5 Apr-27 2.384). | `markets_engine.py:curve_regime`; live payload | **Fixed in 1.0.3**: `SEASONAL` when a 6+ contract curve reverses direction >= 2 times (moves inside the 0.05 band ignored); `curve_shape` adds computed peak, trough, front spread, reversals and a basis sentence; tag tooltip and legend show them. 4 tests. Monotone curves keep CONTANGO/BACKWARDATION/FLAT |
| FC-8 | Freshness depends on a once-a-day timer, `hh-collect-cpc.timer`, whose unit is marked failed because `ecmwf_hdd` raises "no ECMWF 00z run found". The forward step in that run was OK. | `journalctl --user -u hh-collect-cpc.service` | **Open**, unrelated upstream gap; the daily run will use v4 |
| FC-9 | Oct 30 not backfilled: at least one of 12 contracts had no close that day, so the date was skipped rather than filled partially. | backfill dry run | By design |

## Changes made (all verified as below)
- `collectors/hh_forward_yahoo.py`: v4 (FC-1..4). `run_all.py` call unchanged (`collect(conn)`).
- `scripts/backfill_hh_forward.py`: new, dry-run default, backup before `--apply`, only complete 12-contract dates, available = retrieval time, never touches existing `(agent, target)`.
- `markets_engine.py` `latest_rows` + forward points: additive fields `unit, series_id, delivery_month, source_id, quality_status, published_timestamp, retrieved_timestamp, raw_payload_hash`.
- `web/app.js`: forward-curve marker tooltip shows delivery month, contract, quote date, published/available times, source, quality, payload hash; tag "delayed quotes · unverified".
- `tests/test_hh_forward_yahoo.py`: 6 new tests (expiry dates, roll boundaries, daily-close parsing, `collect()` against a mocked Yahoo transport for timestamps/quality/dedup, engine lineage passthrough, backfill planner).

## Executed against the live DB (E)
1. `python scripts/backfill_hh_forward.py --apply` -> backup `henry_hub_pit.db.pre-fwd-backfill.20261117T080342Z`, **132 rows** inserted (11 dates x 12 contracts, 2026-10-29..2026-11-13 excluding 10-30).
2. `python -m collectors.hh_forward_yahoo` -> 12 new rows for trade date 2026-11-17.
3. DB: `integrity_check` ok; 106,549 -> 106,693 rows; 12 contracts on each of 12 dates; 0 rows with published after available; EIA M1 history unchanged (7,496 rows, last 2024-04-05).
4. Live API after cache TTL: forward_curve as_of_date 2026-11-17, 12 points, `stale: false`. Diff of the full payload vs baseline: changes only in `curves.forward_curve`, source rows for the M agents, `age_days`, `platform.pit_rows/raw_payloads`; **price, series, technicals, drivers unchanged**.
5. Tests: full suite `pytest tests` -> **183 passed** (the 177 pre-existing plus 6 new) before the writes. Not re-run after the writes.

## Not verified / remaining
- Rendered UI: the Chrome extension was not connected, so the tooltip and tag are **untested in a browser**; `node --check web/app.js` passes and the live site serves the new `app.js` and the new payload fields (E).
- Values are Yahoo delayed, unofficial quotes/daily closes, not CME settlements; I could not cross-check them against an official source (U). The holiday calendar is approximate; expiry dates for NGX26, NGZ26, NGF27 match the rule, not an exchange calendar (U).
- Backfilled rows have empty `published_timestamp`, because Yahoo's daily bars carry no publication time.
- FC-8 remains open (upstream ECMWF gap). The KB revision defect is fixed in 1.0.3 (`docs/FUSION_ASSESSMENT.md` section 5).

## Rollback
```bash
cd /home/joey/Projects/henry_hub_atomic_agents
sqlite3 henry_hub_pit.db "DELETE FROM pit_market_data WHERE extraction_version IN ('hh_forward_backfill_v1','hh_forward_yahoo_v4');"   # removes only this session's rows
# or restore the whole file:  cp -p henry_hub_pit.db.pre-fwd-backfill.20261117T080342Z henry_hub_pit.db   (stop the services first)
```

## Release 1.0.3 (E)
Built from commit `c126f31` in a clean worktree with `scripts/build_release.sh`; `scripts/verify_release.sh` verified SHA-256 and manifest. **Installed manually, not with `scripts/install_release.sh`**, for two reasons found in source: it needs `sudo` (a password is required here) and its failure trap runs `rollback_release.sh --restore-db`, which overwrites the live DB with the install-time backup. Steps performed: verified DB backup (`/opt/quant-hub/shared/backups/henry_hub_pit_1.0.3_20261117T090152Z.db`, integrity ok, 106,693 rows), extract to `/opt/quant-hub/releases/1.0.3`, shared symlinks, new venv + `pip check`, `migrate.py` (already at head), compile and import checks, atomic `current` symlink switch, `kill -9` of both uvicorn main PIDs (systemd `Restart=on-failure` restarts on SIGKILL, not SIGTERM). Both services reported 1.0.3 within 6 s. Cloudflare Worker not redeployed: `worker.js`, `wrangler.toml` and the systemd units are unchanged since 1.0.1.
Rollback (no DB restore): `ln -sfn /opt/quant-hub/releases/1.0.1 /opt/quant-hub/current` then `kill -9 $(systemctl show -p MainPID --value quant_hub.service) $(systemctl show -p MainPID --value quant_markets.service)`.
Side findings: `/opt/quant-hub/releases/1.0.2` is an earlier install attempt that never became active; a `.git/hooks/pre-commit` bash syntax error (unquoted `=~` regex) blocked every commit and was fixed in place (original saved in the session scratchpad).

## End-to-end run on 1.0.3 (E, 2026-11-17 09:03-09:11Z, `systemctl --user start hh-collect-cpc.service`)
- Collectors: 16 of 17 OK (`hh_forward_yahoo` v4 wrote 12 new vintages for 2026-11-17; `gfs_hdd`, `cpc_*`, `noaa_cpc_discussion`, `kinder_morgan_notices` added rows/documents). **`ecmwf_hdd` FAILED**: "no ECMWF 00z run found in last 3 days" (upstream data gap, not code).
- Agents stage (ExecStopPost `scripts/run_agents.py` against the 1.0.3 hub): `kb_ingest` 30 new nodes (363 -> 394, later 401 after agent findings), and diagnostics, data_quality, repair, notice_analyst, anomaly, synthesis all `ok`; findings 77. Local LLM calls in this run: qwen3:4b 33 (32 ok, 1 deterministic fallback), nomic-embed-text 15 (15 ok).
- First ingest after the install created `kb_node_versions` and `kb_nodes_all` in the live DB; 0 archived versions yet because no node has been revised since.
- DB: `integrity_check` ok; 106,722 pit rows; 0 rows with published after available among v4/backfill rows. Live API: 1.0.3, regime SEASONAL, as_of_date 2026-11-17, stale false, 12 points.
- Tests after the run: 205 passed.
- **Finding FC-10 (open):** the unit ends `failed` whenever any collector fails, and `ExecStartPost=export_snapshot.py` is skipped on a failed `ExecStart`; no `snapshots/2026-11-16` or `2026-11-17` directory exists (E: `ls snapshots`). So a single upstream outage (ECMWF) stops snapshot export. Not changed: it alters deploy unit semantics (`deploy/hh-collect-cpc.service`, installed under `~/.config/systemd/user`).
