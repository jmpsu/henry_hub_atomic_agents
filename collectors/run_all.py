"""Run every implemented collector; one failing collector never blocks the others. Exit 1 if any failed.

Every run of every collector is recorded in `collector_runs` (the execution record of spec 3.1). A failure raises a
GitHub-issue incident for the owner (notify.py); the first success after a failure closes it.

Usage: collectors/run_all.py [--only NAME ...]
"""
import argparse
import os
import sqlite3
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import notify  # noqa: E402
from collectors import (cpc_degree_days, ecmwf_hdd, eia930_power_burn, eia_coal_rail, eia_coal_spot, eia_ng_monthly, eia_petroleum_spot, eia_prices, eia_storage,  # noqa: E402
                        gfs_hdd, eia_ng_flows, hh_forward_yahoo, ttf_forward_yahoo, kinder_morgan_notices, noaa_cpc_discussion, rggi_auctions, steo_production)


def selector_agents() -> dict:
    """'Collector' for HTML-selector agents (ingestion/selectors.json): every agent's selector list must still extract the
    known value from each preserved fixture. Run after a self-heal merge to confirm the repaired configuration."""
    import json
    import selfheal_pipeline as sp
    root = Path(__file__).resolve().parent.parent
    reg = json.loads((root / sp.REG).read_text())
    out = {a: sp.validate_list(cfg["selectors"], sp.fixtures(root / cfg["fixtures"])) for a, cfg in reg.items()}
    bad = [a for a, v in out.items() if not v["passed"]]
    if bad:
        raise ValueError(f"selector agents failing their fixtures: {bad}")
    return {a: f"{v['n_fixtures']} fixtures ok" for a, v in out.items()}


def jobs(conn) -> list:
    now = datetime.now(timezone.utc)
    out = [("cpc_heating", lambda: cpc_degree_days.collect(conn, "Heating", now.year)),
           ("cpc_cooling", lambda: cpc_degree_days.collect(conn, "Cooling", now.year)),
           ("eia_storage", lambda: eia_storage.collect(conn)),
           ("eia_prices", lambda: eia_prices.collect(conn)),
           ("eia_ng_monthly", lambda: eia_ng_monthly.collect(conn)),
           ("rggi_auctions", lambda: rggi_auctions.collect(conn)),
           ("steo_production", lambda: steo_production.collect(conn)),
           ("eia_petroleum_spot", lambda: eia_petroleum_spot.collect(conn)),
           ("noaa_cpc_discussion", lambda: noaa_cpc_discussion.collect(conn)),
           ("eia_coal_spot", lambda: eia_coal_spot.collect(conn)),
           ("eia_coal_rail", lambda: eia_coal_rail.collect(conn)),
           ("eia930_power_burn", lambda: eia930_power_burn.collect(conn)),
           ("kinder_morgan_notices", lambda: kinder_morgan_notices.collect(conn)),
           ("gfs_hdd", lambda: gfs_hdd.collect(conn)),
           ("ecmwf_hdd", lambda: ecmwf_hdd.collect(conn)),
           ("eia_ng_flows", lambda: eia_ng_flows.collect(conn)),
           ("hh_forward_yahoo", lambda: hh_forward_yahoo.collect(conn)),
           ("ttf_forward_yahoo", lambda: ttf_forward_yahoo.collect(conn)),
           ("selfheal_demo", selector_agents)]
    if now.month == 1:  # year-end observations and late-December revisions live in the prior-year file
        out += [("cpc_heating_prev_year", lambda: cpc_degree_days.collect(conn, "Heating", now.year - 1)),
                ("cpc_cooling_prev_year", lambda: cpc_degree_days.collect(conn, "Cooling", now.year - 1))]
    return out


def names() -> list:
    return [n for n, _ in jobs(None)]


def ensure(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS collector_runs(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, started TEXT, finished TEXT, ok INTEGER, "
                 "detail TEXT, code_version TEXT)")


def code_version() -> str:
    try:
        import subprocess
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=Path(__file__).resolve().parent.parent, capture_output=True,
                              text=True, timeout=10).stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="run only these collectors")
    a = ap.parse_args(argv)
    db = os.environ.get("DB_PATH") or str(Path(__file__).resolve().parent.parent / "henry_hub_pit.db")
    conn = sqlite3.connect(db, timeout=30)
    ensure(conn)
    ver = code_version()
    failed = 0
    selected = [(n, j) for n, j in jobs(conn) if not a.only or n in a.only]
    if a.only and len(selected) != len(set(a.only)):
        unknown = sorted(set(a.only) - {n for n, _ in selected})
        print("FAIL", "unknown collectors", unknown)
        return 2
    for name, job in selected:
        started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        prev = conn.execute("SELECT ok FROM collector_runs WHERE name=? ORDER BY id DESC LIMIT 1", (name,)).fetchone()
        try:
            res = job()
            ok, detail = 1, repr(res)[:1500]
            print("OK  ", name, res)
        except Exception as e:  # noqa: BLE001
            failed += 1
            ok, detail = 0, f"{e!r}"[:1500]
            print("FAIL", name, repr(e))
            notify.incident(f"collector:{name}", f"collector {name} failed",
                            f"Collector `{name}` failed at {started} (code {ver}).\n\n```\n{detail}\n```\n\n"
                            f"```\n{traceback.format_exc()[-2500:]}\n```\n"
                            "Self-healing diagnosis runs for HTML-selector agents; parser-based collectors need a code fix (open a PR).")
        conn.execute("INSERT INTO collector_runs(name,started,finished,ok,detail,code_version) VALUES (?,?,?,?,?,?)",
                     (name, started, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), ok, detail, ver))
        conn.commit()
        if ok and prev is not None and prev[0] == 0:
            notify.resolve(f"collector:{name}", f"Collector `{name}` succeeded again at {started} (code {ver}).")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
