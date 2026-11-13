import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import alerts  # noqa: E402

GOOD = {"relationship": "LNG feedgas drop interacts with salt storage draw", "instruments": ["NG M1"],
        "analogs": ["2024-02 freeze"], "observations": ["Agent_LNG_SabinePass_Flow"], "direction": "up",
        "magnitude": "+3%", "horizon": "5d", "markets": ["Henry Hub"], "assumptions": ["no pipeline reroute"],
        "contradictory_evidence": ["storage above 5y avg"], "confidence": "low", "backtest_method": "PIT walk-forward",
        "vector_nodes": ["node_x"], "model_version": "qwen3:4b",
        "backtest_results": {"sample": "out_of_sample", "n": 50, "rmse": 0.1, "directional_hit_rate": 0.55,
                             "mean_return_after_costs": 0.001, "cost_bps": 10}}


class AlertTests(unittest.TestCase):
    def test_valid_hypothesis_publishes_dry_run(self):
        r = alerts.publish_memo(GOOD)
        self.assertTrue(r["dry_run"])
        self.assertEqual(r["command"][:3], ["gh", "issue", "create"])

    def test_memo_labels_model_hypothesis_and_causation_caveat(self):
        m = alerts.format_memo(GOOD)
        self.assertIn("MODEL-GENERATED HYPOTHESIS", m)
        self.assertIn("not proof of causation", m)

    def test_missing_evidence_rejected(self):
        bad = dict(GOOD); bad["contradictory_evidence"] = []
        with self.assertRaises(ValueError):
            alerts.publish_memo(bad)

    def test_in_sample_backtest_rejected(self):
        bad = dict(GOOD); bad["backtest_results"] = dict(GOOD["backtest_results"], sample="in_sample")
        self.assertIn("backtest_results must be out-of-sample", alerts.validate_hypothesis(bad))

    def test_costless_backtest_rejected(self):
        bad = dict(GOOD); br = dict(GOOD["backtest_results"]); br.pop("cost_bps"); bad["backtest_results"] = br
        self.assertTrue(any("transaction costs" in p for p in alerts.validate_hypothesis(bad)))


if __name__ == "__main__":
    unittest.main()
