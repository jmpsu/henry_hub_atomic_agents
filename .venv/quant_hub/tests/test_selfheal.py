import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import selfheal as s  # noqa: E402

OLD = '<table><tr><td class="val">1,234.5</td></tr></table>'
NEW = '<div><span id="flow-total">1,234.5</span><span class="note">Dth/d</span></div>'  # layout changed


class SelfHealTests(unittest.TestCase):
    def test_original_selector_works(self):
        self.assertEqual(s.parse_value(OLD, "td.val"), 1234.5)

    def test_layout_change_is_detected(self):
        d = s.diagnose("Agent_Flow_Kingsgate", NEW, "td.val")
        self.assertFalse(d["ok"])
        self.assertIn("matched nothing", d["error"])

    def test_out_of_range_value_is_flagged(self):
        d = s.diagnose("Agent_Flow_Kingsgate", OLD, "td.val", expected_range=(0, 100))
        self.assertFalse(d["ok"])

    def test_good_proposal_validated_against_fixtures(self):
        diag = s.diagnose("Agent_Flow_Kingsgate", NEW, "td.val")
        prop = s.propose_repair(diag, NEW, lambda p, sc: {"selector": "#flow-total"})
        self.assertTrue(p := s.validate_proposal(prop["selector"], [{"html": NEW, "expected": 1234.5}]))
        self.assertTrue(p["passed"])

    def test_wrong_proposal_rejected(self):
        v = s.validate_proposal("span.note", [{"html": NEW, "expected": 1234.5}])
        self.assertFalse(v["passed"])

    def test_prompt_carries_no_think(self):
        seen = []
        s.propose_repair({"selector": "x", "error": "e", "agent_id": "A"}, NEW, lambda p, sc: seen.append(p) or {"selector": "#a"})
        self.assertTrue(seen[0].rstrip().endswith("/no_think"))

    def test_pr_refused_without_validation(self):
        with self.assertRaises(PermissionError):
            s.open_pull_request("fix/x", "t", "b", {"passed": False}, tests_passed=True)
        with self.assertRaises(PermissionError):
            s.open_pull_request("fix/x", "t", "b", {"passed": True}, tests_passed=False)

    def test_pr_dry_run_when_validated(self):
        r = s.open_pull_request("fix/x", "t", "b", {"passed": True}, tests_passed=True)
        self.assertTrue(r["dry_run"])
        self.assertEqual(r["command"][:3], ["gh", "pr", "create"])


if __name__ == "__main__":
    unittest.main()

class VoidTags(unittest.TestCase):
    def test_void_tag_inside_match_does_not_swallow_it(self):
        import selfheal
        self.assertEqual(selfheal.extract('<table><tr><td class="v">3.41<br>USD</td><td class="v">2.9<img src="x"></td></tr></table>', "td.v"), ["3.41USD", "2.9"])
