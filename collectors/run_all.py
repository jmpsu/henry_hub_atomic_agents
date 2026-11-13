"""Run every implemented collector; one failing collector never blocks the others. Exit 1 if any failed."""
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collectors import cpc_degree_days, eia_prices, ecmwf_hdd, eia_ng_monthly, eia_petroleum_spot, rggi_auctions, steo_production, eia_storage, gfs_hdd  # noqa: E402


def main() -> int:
    db = os.environ.get("DB_PATH") or str(Path(__file__).resolve().parent.parent / "henry_hub_pit.db")
    conn = sqlite3.connect(db)
    failed = 0
    jobs = [("cpc_heating", lambda: cpc_degree_days.collect(conn, "Heating", datetime.now(timezone.utc).year)),
            ("cpc_cooling", lambda: cpc_degree_days.collect(conn, "Cooling", datetime.now(timezone.utc).year)),
            ("eia_storage", lambda: eia_storage.collect(conn)),
            ("eia_prices", lambda: eia_prices.collect(conn)),
            ("eia_ng_monthly", lambda: eia_ng_monthly.collect(conn)),
            ("rggi_auctions", lambda: rggi_auctions.collect(conn)),
            ("steo_production", lambda: steo_production.collect(conn)),
            ("eia_petroleum_spot", lambda: eia_petroleum_spot.collect(conn)),
            ("gfs_hdd", lambda: gfs_hdd.collect(conn)),
            ("ecmwf_hdd", lambda: ecmwf_hdd.collect(conn))]
    now = datetime.now(timezone.utc)
    if now.month == 1:  # year-end observations and late-December revisions live in the prior-year file
        jobs += [("cpc_heating_prev_year", lambda: cpc_degree_days.collect(conn, "Heating", now.year - 1)),
                 ("cpc_cooling_prev_year", lambda: cpc_degree_days.collect(conn, "Cooling", now.year - 1))]
    for name, job in jobs:
        try:
            print("OK  ", name, job())
        except Exception as e:  # noqa: BLE001
            failed += 1
            print("FAIL", name, repr(e))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
