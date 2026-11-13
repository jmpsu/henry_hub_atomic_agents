import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import backtest  # noqa: E402
import ingest  # noqa: E402
import init_db  # noqa: E402

A = "Agent_HH_M1"
D0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


class BacktestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db = os.path.join(self.tmp.name, "b.db")
        init_db.migrate(db)
        self.conn = sqlite3.connect(db)
        for i in range(40):  # linear series, published the evening of its own day
            ingest.record_observation(self.conn, agent_id=A, target_timestamp=iso(D0 + timedelta(days=i)),
                                      available_timestamp=iso(D0 + timedelta(days=i, hours=20)),
                                      value=3.0 + 0.01 * i, source_id="t")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def times(self):
        return [iso(D0 + timedelta(days=i, hours=23)) for i in range(5, 38)]

    def test_runs_and_scores(self):
        rows = backtest.walk_forward(self.conn, A, self.times(), 1, backtest.persistence)
        self.assertGreater(len(rows), 20)
        m = backtest.metrics(rows)
        self.assertAlmostEqual(m["rmse"], 0.01, places=6)  # persistence error = one step of drift

    def test_future_revision_cannot_leak_into_earlier_decision(self):
        t = iso(D0 + timedelta(days=10, hours=23))
        base = backtest.walk_forward(self.conn, A, [t], 1, backtest.persistence)
        # a wildly different revision of day 5, published AFTER the decision time
        ingest.record_observation(self.conn, agent_id=A, target_timestamp=iso(D0 + timedelta(days=5)),
                                  available_timestamp=iso(D0 + timedelta(days=30)), value=9.0, source_id="t")
        after = backtest.walk_forward(self.conn, A, [t], 1, backtest.persistence)
        self.assertEqual(base[0]["pred"], after[0]["pred"])

    def test_model_never_sees_later_published_rows(self):
        seen = []

        def spy(history, features):
            seen.append(len(history))
            return history[-1][1]
        t = iso(D0 + timedelta(days=10, hours=23))
        backtest.walk_forward(self.conn, A, [t], 1, spy)
        self.assertEqual(seen, [11])  # days 0..10 only

    def test_chronological_split_is_ordered_with_holdout(self):
        rows = backtest.walk_forward(self.conn, A, self.times(), 1, backtest.ar1)
        tr, va, te = backtest.split_chronological(rows)
        self.assertTrue(tr[-1]["decision"] < va[0]["decision"] < te[0]["decision"])
        self.assertEqual(len(tr) + len(va) + len(te), len(rows))

    def test_transaction_costs_reduce_returns(self):
        free = backtest.metrics(backtest.walk_forward(self.conn, A, self.times(), 1, backtest.ar1, cost_bps=0))
        costly = backtest.metrics(backtest.walk_forward(self.conn, A, self.times(), 1, backtest.ar1, cost_bps=50))
        self.assertLess(costly["mean_return_after_costs"], free["mean_return_after_costs"])


if __name__ == "__main__":
    unittest.main()
