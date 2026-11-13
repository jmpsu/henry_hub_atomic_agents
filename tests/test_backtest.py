import os
import sqlite3
import sys
import _scratch
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
        self.tmp = _scratch.TemporaryDirectory()
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


class WeatherModel(unittest.TestCase):
    def _db(self):
        import os, sqlite3, _scratch
        from datetime import datetime, timedelta, timezone
        import init_db, ingest
        f = os.path.join(_scratch.mkdtemp(), "t.db"); init_db.migrate(f); c = sqlite3.connect(f)
        d0, p = datetime(2025, 1, 1, tzinfo=timezone.utc), 3.0
        iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")
        for i in range(200):
            d = d0 + timedelta(days=i)
            anom = ((i * 7) % 11) - 5.0                      # deterministic anomaly known next day
            ingest.record_observation(c, agent_id="Agent_Weather_Actual_HDD", target_timestamp=iso(d), available_timestamp=iso(d + timedelta(days=1, hours=12)), value=20 + anom, source_id="t")
            ingest.record_observation(c, agent_id="Agent_Weather_30YrNormal_HDD", target_timestamp=iso(d), available_timestamp="2021-05-04T00:00:00Z", value=20.0, source_id="t", provenance="extracted_estimate")
            if i >= 2:
                p = round(p + 0.01 * ((((i - 2) * 7) % 11) - 5.0), 6)   # day i's change is driven by the anomaly of day i-2, public by day i-1 12:00Z
            ingest.record_observation(c, agent_id="Agent_HH_Spot_EIA", target_timestamp=iso(d), available_timestamp=iso(d + timedelta(hours=21)), value=p, source_id="t")
        c.commit(); return c
    def test_features_respect_cutoff_and_model_beats_persistence(self):
        import backtest as bt
        c = self._db()
        f = bt.weather_features(c, "2025-03-01T21:00:00Z", 1)
        self.assertIn("2025-02-28", f["hdd_anomaly"]); self.assertNotIn("2025-03-01", f["hdd_anomaly"])   # Mar 1 HDD not public until Mar 2 12:00Z
        times = [r[0] for r in c.execute("select distinct available_timestamp from pit_market_data where agent_id='Agent_HH_Spot_EIA' order by 1")][80:190]
        w = bt.metrics(bt.walk_forward(c, "Agent_HH_Spot_EIA", times, 1, bt.hdd_anomaly, feature_fn=bt.weather_features))
        self.assertGreater(w["n"], 50); self.assertLess(w["rmse"], 0.5 * w["persistence_rmse"])
    def test_no_features_means_no_signal(self):
        import backtest as bt
        self.assertEqual(bt.hdd_anomaly([("2025-01-01T00:00:00Z", 3.0), ("2025-01-02T00:00:00Z", 3.1)], None), 3.1)


class RiskMetrics(unittest.TestCase):
    def test_drawdown_sharpe_regime_and_slippage(self):
        import backtest as bt
        rows = [{"pred": 1, "actual": 1, "last": 1, "dir_hit": True, "ret": r, "target": t} for r, t in
                [(0.02, "2026-01-05T00:00:00Z"), (-0.05, "2026-01-06T00:00:00Z"), (0.01, "2026-07-01T00:00:00Z"), (0.04, "2026-07-02T00:00:00Z")]]
        m = bt.metrics(rows)
        self.assertAlmostEqual(m["max_drawdown"], 0.05); self.assertIsNotNone(m["sharpe_per_decision"])
        self.assertEqual(m["by_regime"]["heating_season"]["n"], 2); self.assertEqual(m["by_regime"]["non_heating_season"]["n"], 2)
        self.assertEqual(bt.regime("2026-11-30T00:00:00Z"), "heating_season"); self.assertEqual(bt.regime("2026-04-01T00:00:00Z"), "non_heating_season")


class CrossDomainModels(unittest.TestCase):
    def test_known_at_respects_availability(self):
        import backtest as bt
        k = bt.KnownAt([("2026-01-01", 10.0, "2026-02-15T00:00:00Z"), ("2026-02-01", 11.0, "2026-03-15T00:00:00Z")])
        self.assertIsNone(k.at("2026-02-14T23:59:59Z"))
        self.assertEqual(k.at("2026-02-15T00:00:00Z"), ("2026-01-01", 10.0))
        self.assertEqual(k.at("2026-03-20T00:00:00Z"), ("2026-02-01", 11.0))
        late = bt.KnownAt([("2026-02-01", 11.0, "2026-03-01T00:00:00Z"), ("2026-01-01", 10.5, "2026-03-05T00:00:00Z")])   # older month revised later
        self.assertEqual(late.at("2026-03-06T00:00:00Z"), ("2026-02-01", 11.0))                                       # still the newest target

    def test_propane_wti_revert_learns_planted_reversion(self):
        import backtest as bt
        from datetime import date as D
        days = [(D(2024, 1, 1) + timedelta(days=i)).isoformat() for i in range(500)]
        wti = bt.KnownAt([(d, 80.0, d + "T21:00:00Z") for d in days])
        fair = 0.5 * 80 / 42 * 100                                   # propane at 50% of WTI
        p, hist = fair, []
        for i, d in enumerate(days):
            shock = ((i * 37) % 11 - 5) * 0.8
            p = p + 0.3 * (fair - p) + shock                         # pulls 30% of the gap back each day
            hist.append((d + "T00:00:00Z", p))
        pred = bt.propane_wti_revert(hist, {"wti": wti, "horizon_days": 1})
        expected = hist[-1][1] + 0.3 * (fair - hist[-1][1])
        last = hist[-1][1]
        self.assertEqual((pred > last), (expected > last))                       # moves toward fair value
        self.assertLess(abs(pred - expected), 0.6 * abs(expected - last) + 1.2)   # and recovers most of the planted pull
        self.assertEqual(bt.propane_wti_revert(hist[:5], {"wti": wti, "horizon_days": 1}), hist[4][1])   # too little history: no signal

    def test_production_feature_is_pit(self):
        import backtest as bt, init_db, ingest, sqlite3
        d = _scratch.mkdtemp(); db = os.path.join(d, "t.db"); init_db.migrate(db); c = sqlite3.connect(db)
        for m in range(1, 9):
            for a in bt.PROD_BASINS:
                ingest.record_observation(c, agent_id=a, target_timestamp=f"2025-{m:02d}-01T00:00:00Z", available_timestamp=f"2025-{m + 1:02d}-15T17:00:00Z",
                                          value=10.0 + m, source_id="t")
        c.commit()
        f = bt.production_features(c, "2025-07-01T00:00:00Z", 5)
        self.assertEqual(f["prod_chg3"].at("2025-07-01T00:00:00Z"), ("2025-05-01", 18.0))   # May (pub Jun 15) minus Feb, x6 basins = 3*6
        self.assertIsNone(f["prod_chg3"].at("2025-05-14T00:00:00Z"))                         # nothing with 3 prior months yet published
