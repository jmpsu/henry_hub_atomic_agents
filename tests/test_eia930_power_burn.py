import os, sqlite3, sys, unittest
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import _scratch
import init_db
from collectors import eia930_power_burn as m

HEAD = '"Balancing Authority","Data Date","Hour Number","Local Time at End of Hour","UTC Time at End of Hour","Net Generation (MW) from Natural Gas","Net Generation (MW) from Natural Gas (Adjusted)"\n'


def csv_for(days, bas=("A", "B"), adj=100.0, gap=None):
    rows = [HEAD]
    for d in days:
        for h in range(1, 25):
            for b in bas:
                if gap and (d, h, b) == gap:
                    continue
                end = datetime.strptime(d, "%Y-%m-%d").replace(hour=0) + __import__("datetime").timedelta(hours=h)
                rows.append(f'{b},x,{h},x,"{end.strftime("%m/%d/%Y %I:%M:%S %p")}",1,"{adj:,}"\n')
    return "".join(rows).encode()


class T(unittest.TestCase):
    def test_daily_sum_uses_adjusted_and_drops_last_incomplete_day(self):
        p = m.parse(csv_for(["2026-11-01", "2026-11-02", "2026-11-03"]))
        self.assertEqual(p, {"2026-11-01": 4800.0})          # 24 h x 2 BAs x 100 MW; 11-02 is within a day of the newest data
    def test_incomplete_day_skipped(self):
        many = tuple(f"B{i}" for i in range(40))
        p = m.parse(csv_for(["2026-11-01", "2026-11-02", "2026-11-03", "2026-11-04"], bas=many, gap=None))
        self.assertIn("2026-11-02", p)
        short = m.parse(csv_for(["2026-11-01"], bas=("A",)))    # a single day is never a day older than the newest data
        self.assertEqual(short, {})
    def test_real_sample_and_pit(self):
        body = (ROOT / "tests" / "fixtures" / "eia930_balance_sample.csv").read_bytes()
        p = m.parse(body)
        self.assertTrue(all(v > 0 for v in p.values()))
        d = _scratch.TemporaryDirectory(); db = os.path.join(d.name, "t.db"); init_db.migrate(db); c = sqlite3.connect(db)
        f = lambda u: (200, csv_for(["2026-11-01", "2026-11-02", "2026-11-03"]), "text/csv")
        m.collect(c, f, now=datetime(2026, 11, 3, 11, tzinfo=timezone.utc), urls=["u"])     # 11-01 not public until 11-03 12:00Z
        self.assertEqual(c.execute("SELECT COUNT(*) FROM pit_market_data").fetchone()[0], 0)
        m.collect(c, f, now=datetime(2026, 11, 4, tzinfo=timezone.utc), urls=["u"])
        self.assertEqual(c.execute("SELECT value, available_timestamp FROM pit_market_data").fetchall(), [(4800.0, "2026-11-03T12:00:00Z")])
        self.assertEqual(m.collect(c, f, now=datetime(2026, 11, 5, tzinfo=timezone.utc), urls=["u"])[0]["observations_new"], 0)
        d.cleanup()
    def test_bad_header(self):
        with self.assertRaises(ValueError): m.parse(b'"x","y"\n1,2\n')


if __name__ == "__main__":
    unittest.main()


class Boundary(unittest.TestCase):
    def test_day_split_across_two_files_is_complete_when_merged(self):
        full = csv_for(["2026-06-29", "2026-06-30", "2026-07-01", "2026-07-02", "2026-07-03"]).decode().splitlines(keepends=True)
        head, rows = full[0], full[1:]
        cut = next(i for i, r in enumerate(rows) if "07/01/2026 12:00:00 AM" in r)          # the hour ending 00:00 on Jul 1 is Jun 30
        a, b = (head + "".join(rows[:cut])).encode(), (head + "".join(rows[cut:])).encode()
        self.assertNotIn("2026-06-30", m.parse(a)); self.assertNotIn("2026-06-30", m.parse(b))
        self.assertEqual(m.finalize([m.partials(a), m.partials(b)])["2026-06-30"], 4800.0)
