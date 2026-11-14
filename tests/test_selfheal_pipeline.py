import json, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import selfheal_pipeline as sp

BROKEN = '<div class="quote"><span class="hub">Henry Hub</span><span class="price-now">$3.05</span></div>'


class Pipeline(unittest.TestCase):
    def test_registry_and_fixtures_consistent(self):
        reg = json.loads((ROOT / sp.REG).read_text())
        for agent, cfg in reg.items():
            fx = sp.fixtures(ROOT / cfg["fixtures"])
            self.assertGreaterEqual(len(fx), 2, agent)
            import selfheal
            self.assertTrue(sp.validate_list(cfg["selectors"], fx)["passed"], agent)    # current selectors pass their own fixtures
    def test_working_selector_needs_no_repair(self):
        ok = (ROOT / "tests/fixtures/selfheal/Agent_SelfHeal_Demo/2026-11-01.html").read_text()
        self.assertEqual(sp.repair("Agent_SelfHeal_Demo", ok, dry_run=True)["action"], "none (selector still works)")
    def test_good_proposal_reaches_dry_run_branch(self):
        r = sp.repair("Agent_SelfHeal_Demo", BROKEN, base="quant-hub-build", dry_run=True, llm=lambda p, s: {"selector": "span.price-now"})
        self.assertTrue(r["ok"]); self.assertEqual(r["stage"], "dry_run"); self.assertEqual(r["page_value"], 3.05)
        self.assertTrue(r["branch"].startswith("selfheal/selfheal_demo/agent_selfheal_demo-"))
    def test_proposal_that_breaks_a_fixture_is_rejected(self):
        # a generic selector placed first would read a DIFFERENT number from an old page -> fixture mismatch -> no PR
        orig = sp.fixtures
        sp.fixtures = lambda d: [{"html": '<div><span class="hh-price">$3.42</span><span class="x">9.99</span></div>', "expected": 3.42, "name": "f"}]
        try:
            page = '<div><span class="x">$3.05</span></div>'
            r = sp.repair("Agent_SelfHeal_Demo", page, dry_run=True, llm=lambda p, s: {"selector": "span.x"})
        finally:
            sp.fixtures = orig
        self.assertFalse(r["ok"]); self.assertEqual(r["stage"], "validate"); self.assertEqual(r["validation"]["results"], [False])
    def test_out_of_range_page_value_is_rejected(self):
        r = sp.repair("Agent_SelfHeal_Demo", '<span class="p">$300.0</span>', dry_run=True, llm=lambda p, s: {"selector": "span.p"})
        self.assertFalse(r["ok"]); self.assertFalse(r["page_value_in_range"])
    def test_unknown_agent(self):
        self.assertEqual(sp.repair("Agent_Nope", BROKEN, dry_run=True)["stage"], "lookup")


if __name__ == "__main__":
    unittest.main()
