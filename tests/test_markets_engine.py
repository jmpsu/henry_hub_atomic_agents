import math, os, sqlite3, sys, _scratch, unittest
from datetime import date, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np
import init_db, ingest
import markets_engine as me


def days(n, start=date(2024, 1, 1)):
    return [(start + timedelta(days=i)).isoformat() for i in range(n)]


class Maths(unittest.TestCase):
    def test_wti_ratio(self):
        self.assertAlmostEqual(me.wti_ratio(100.0, 84.0), 50.0)           # $1.00/gal * 42 = $42/bbl = 50% of $84
        self.assertIsNone(me.wti_ratio(100.0, 0.0))
    def test_frac_spread(self):
        self.assertAlmostEqual(me.ethane_usd_mmbtu(19.92), 3.0)           # 0.1992 $/gal / 0.0664
        self.assertAlmostEqual(me.frac_spread(19.92, 2.5), 0.5)           # recovery
        self.assertLess(me.frac_spread(13.3, 3.0), 0)                     # 2.0 - 3.0 -> rejection
    def test_bollinger(self):
        flat = me.bollinger([10.0] * 40)
        self.assertTrue(math.isnan(flat["upper"][18])); self.assertEqual(flat["upper"][19], 10.0); self.assertEqual(flat["bandwidth_pct"][-1], 0.0)
        v = [10.0] * 30 + [10 + (i % 2) * 4 for i in range(30)]
        b = me.bollinger(v)
        self.assertAlmostEqual(b["mid"][-1], 12.0); self.assertAlmostEqual(b["upper"][-1], 12.0 + 2 * 2.0)   # sigma of alternating 10/14 is 2
        self.assertTrue(b["squeeze"][25]); self.assertFalse(b["squeeze"][-1])                                 # quiet stretch is the squeeze
    def test_rsi_extremes_and_macd(self):
        self.assertEqual(me.rsi(list(range(1, 40)))[-1], 100.0)
        self.assertLess(me.rsi(list(range(40, 1, -1)))[-1], 1.0)
        m = me.macd([5.0] * 60)
        self.assertTrue(np.allclose(m["line"], 0) and np.allclose(m["hist"], 0))
    def test_rsi_macd_divergence(self):
        # higher price high on weaker momentum: sharp rally, pullback, then a slow grind to a marginal new high
        v = [100 + i * 2.0 for i in range(20)] + [138 - i * 1.5 for i in range(1, 11)] + [123 + i * 0.6 for i in range(1, 30)] + [140.4 - i for i in range(1, 8)]
        self.assertEqual(me.rsi_macd_divergence(v)["rsi"], "bearish")
        self.assertEqual(me.rsi_macd_divergence([100.0 + i for i in range(120)]), {"rsi": "none", "macd": "none"})
    def test_fibonacci(self):
        up = me.fibonacci(days(3), [10.0, 20.0, 15.0])                    # low then high: measured down from the high
        self.assertEqual(up["leg"], "up"); self.assertAlmostEqual(up["levels"]["38.2%"], 16.18); self.assertAlmostEqual(up["levels"]["61.8%"], 13.82)
        self.assertEqual(up["nearest_level"], "50.0%"); self.assertAlmostEqual(up["retracement_pct"], 50.0)
        down = me.fibonacci(days(3), [20.0, 10.0, 12.0])
        self.assertEqual(down["leg"], "down"); self.assertAlmostEqual(down["levels"]["23.6%"], 12.36)
        self.assertEqual(set(up["levels"]), {"0.0%", "23.6%", "38.2%", "50.0%", "61.8%", "78.6%", "100.0%"})
    def test_triangle_detection(self):
        def zigzag(top, bottom, n=60, period=6):                          # touches top(i) and bottom(i) alternately
            return [(top(i) if (i // (period // 2)) % 2 == 0 else bottom(i)) for i in range(n)]
        sym = me.triangle_detection(days(60), zigzag(lambda i: 120 - 0.25 * i, lambda i: 80 + 0.25 * i))
        self.assertEqual(sym["pattern"], "symmetrical_triangle"); self.assertGreater(sym["breakout_above"], sym["breakdown_below"])
        asc = me.triangle_detection(days(60), zigzag(lambda i: 120.0, lambda i: 80 + 0.5 * i))
        self.assertEqual(asc["pattern"], "ascending_triangle")
        self.assertEqual(me.triangle_detection(days(60), zigzag(lambda i: 100 + 0.5 * i, lambda i: 80 + 0.5 * i))["pattern"], "none")   # parallel channel
        self.assertEqual(me.triangle_detection(days(10), [1.0] * 10)["pattern"], "none")
    def test_crossovers_and_regime(self):
        v = [100.0] * 210 + [100 + i for i in range(1, 80)]
        c = me.ma_crossovers(days(len(v)), v)
        self.assertEqual([x["type"] for x in c], ["golden_cross"])
        self.assertEqual(me.curve_regime([{"value": 3.0}, {"value": 3.4}]), "CONTANGO")
        self.assertEqual(me.curve_regime([{"value": 3.0}, {"value": 2.6}]), "BACKWARDATION")
        self.assertEqual(me.curve_regime([{"value": 3.0}, {"value": 3.01}]), "FLAT"); self.assertEqual(me.curve_regime([]), "UNAVAILABLE")
    def test_seasonal_overlay_uses_only_prior_complete_years(self):
        d = days(366 * 3, date(2023, 1, 1)); v = [float(int(x[:4]) - 2000) for x in d]      # 23, 24, 25 by year
        s = me.seasonal_overlay(d, v, 2025)
        self.assertEqual(s["history_years"], [2023, 2024]); self.assertEqual((s["band_min"][5], s["band_max"][5], s["band_avg"][5]), (23.0, 24.0, 23.5))
        self.assertEqual(s["current"][5], 25.0)


class PitState(unittest.TestCase):
    def setUp(self):
        self.db = os.path.join(_scratch.mkdtemp(), "t.db"); init_db.migrate(self.db); c = sqlite3.connect(self.db)
        for i in range(300):
            d = date(2025, 1, 1) + timedelta(days=i); t = d.isoformat() + "T00:00:00Z"; a = d.isoformat() + "T21:00:00Z"
            ingest.record_observation(c, agent_id="Agent_NGL_MontBelvieu_Propane", target_timestamp=t, available_timestamp=a, value=80 + (i % 30), source_id="t", unit="cents/gal")
            ingest.record_observation(c, agent_id="Agent_Crude_WTI_Spot", target_timestamp=t, available_timestamp=a, value=84.0, source_id="t", unit="USD/bbl")
        # a later revision of the first day, and one demo seed row that must never be used
        ingest.record_observation(c, agent_id="Agent_NGL_MontBelvieu_Propane", target_timestamp="2025-01-01T00:00:00Z", available_timestamp="2025-12-01T00:00:00Z", value=555.0, source_id="t", unit="cents/gal")
        c.execute("INSERT INTO pit_market_data (agent_id,target_timestamp,available_timestamp,value,quality_status) VALUES ('Agent_NGL_MontBelvieu_Ethane','2025-06-01T00:00:00Z','2025-06-01T21:00:00Z',25.0,'unverified_seed')")
        c.commit(); c.close()
    def test_pit_cutoff(self):
        self.assertEqual(me.pit_cutoff("2025-03-01T19:00:00-05:00"), "2025-03-02T00:00:00Z")
        with self.assertRaises(ValueError): me.pit_cutoff("zzz")
        s = me.build_state(self.db, "propane", "intraday", "2025-03-01T20:59:59Z")
        self.assertEqual(s["series"]["dates"][-1], "2025-02-28")                   # Mar 1 close is not public until 21:00Z
        self.assertEqual(s["as_of"], "2025-03-01T20:59:59Z")
        self.assertEqual(me.build_state(self.db, "propane", "intraday", "2025-03-01T21:00:00Z")["series"]["dates"][-1], "2025-03-01")
    def test_future_revision_invisible_before_it_is_published(self):
        c = sqlite3.connect(f"file:{self.db}?mode=ro", uri=True)
        self.assertEqual(me.load_series(c, "Agent_NGL_MontBelvieu_Propane", "2025-06-01T00:00:00Z")[0][1], 80.0)
        self.assertEqual(me.load_series(c, "Agent_NGL_MontBelvieu_Propane", "2025-12-02T00:00:00Z")[0][1], 555.0)
    def test_nothing_is_simulated_for_products_without_a_collector(self):
        s = me.build_state(self.db, "ethane", "seasonal", "2025-10-01T00:00:00Z")
        self.assertEqual(s["price"]["status"], "pending_collector"); self.assertIsNone(s["price"]["value"]); self.assertEqual(s["series"]["values"], [])
        self.assertEqual(s["curves"]["frac_spread"]["status"], "pending_collector"); self.assertEqual(s["curves"]["hub_spread"]["status"], "pending_collector")
        eth = [x for x in s["sources"] if x["agent_id"] == "Agent_NGL_MontBelvieu_Ethane"][0]
        self.assertEqual((eth["provenance"], eth["status"]), ("unverified_seed", "pending_collector"))
        self.assertEqual((eth["feed_status"], eth["feed_label"]), ("INACTIVE_OR_PLANNED_GAP", "Feed Not Configured"))
        self.assertEqual([p["status"] for p in s["products"] if p["id"] == "ethane"], ["pending_collector"])
    def test_state_shape_and_ratio(self):
        s = me.build_state(self.db, "propane", "seasonal", "2025-10-01T00:00:00Z")
        for k in ("schema", "as_of", "active_product", "product", "timeframe", "products", "price", "series", "technicals", "seasonal", "curves",
                  "drivers", "derived", "sources", "geo", "alerts", "knowledge", "platform"):
            self.assertIn(k, s)
        self.assertEqual(s["schema"], "ngl-state/1"); self.assertEqual(s["price"]["provenance"], "measured")
        self.assertAlmostEqual(s["price"]["pct_of_wti"], me.wti_ratio(s["price"]["value"], 84.0), places=3)
        self.assertEqual(len(s["technicals"]["sma50"]), len(s["series"]["dates"]))
        self.assertTrue(all(f["schematic"] and f["value"] is None for f in s["geo"]["flows"]))
        ov = s["geo"]["overlays"]
        self.assertEqual(len(ov["routes"]), 3)
        self.assertEqual(len(ov["chokepoints"]), 4)
        self.assertEqual(len(ov["scenarios"]), 5)
        self.assertTrue(all(r["netback_value"] is not None and r["freight_value"] is not None for r in ov["routes"]))
        self.assertEqual({c["band"] for c in ov["chokepoints"]}, {"high", "elevated", "low"})
        import json; self.assertNotIn("NaN", json.dumps(s))


if __name__ == "__main__":
    unittest.main()


class CurveShape(unittest.TestCase):
    def pts(self, vals):
        return [{"contract": f"M{i + 1}", "value": v, "delivery_month": f"2027-{i + 1:02d}"} for i, v in enumerate(vals)]
    def test_live_style_seasonal_curve_is_not_called_contango(self):
        v = [3.125, 3.503, 3.116, 2.433, 2.384, 2.445, 2.607, 2.843, 2.925, 2.913, 2.992, 3.271]   # the 2026-11-17 curve: M12 > M1 but strongly seasonal
        self.assertEqual(me.curve_regime(self.pts(v)), "SEASONAL")
        sh = me.curve_shape(self.pts(v))
        self.assertEqual(sh["peak"]["contract"], "M2"); self.assertEqual(sh["trough"]["contract"], "M5")
        self.assertAlmostEqual(sh["front_spread"], 0.378, places=3); self.assertEqual(sh["reversals"], 2); self.assertIn("not read as contango", sh["basis"])
    def test_monotone_curves_keep_their_labels(self):
        up = [3.0, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6]; down = up[::-1]
        self.assertEqual(me.curve_regime(self.pts(up)), "CONTANGO"); self.assertEqual(me.curve_regime(self.pts(down)), "BACKWARDATION")
        self.assertEqual(me.curve_regime(self.pts([3.0] * 8)), "FLAT")
        self.assertEqual(me.curve_shape(self.pts(up))["reversals"], 0)
    def test_noise_inside_the_band_is_not_seasonality(self):
        self.assertEqual(me.curve_regime(self.pts([3.00, 3.02, 3.00, 3.02, 3.00, 3.02, 3.60])), "CONTANGO")
    def test_short_curves_unchanged(self):
        self.assertEqual(me.curve_regime(self.pts([3.0, 3.4])), "CONTANGO"); self.assertEqual(me.curve_regime([]), "UNAVAILABLE"); self.assertEqual(me.curve_shape([]), {})
