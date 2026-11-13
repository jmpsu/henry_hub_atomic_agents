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


class RepairRetry(unittest.TestCase):
    def test_repeated_or_useless_proposal_triggers_grounded_retry(self):
        import selfheal
        html = '<div><span class="px">$3.42</span><span class="lbl">HH</span></div>'
        diag = selfheal.diagnose("Agent_X", html, "span.old", (1, 20))
        answers = iter([{"selector": "span.old"}, {"selector": "span.px"}])
        prompts = []
        def fake(prompt, schema):
            prompts.append(prompt); return next(answers)
        p = selfheal.propose_repair(diag, html, fake)
        self.assertEqual(p, {"selector": "span.px", "attempts": ["span.old", "span.px"]})
        self.assertTrue(prompts[1].rstrip().endswith("/no_think"))
    def test_good_first_answer_is_not_retried(self):
        import selfheal
        html = '<span class="px">$3.42</span>'
        calls = []
        p = selfheal.propose_repair(selfheal.diagnose("A", html, "b.x"), html, lambda pr, sc: calls.append(1) or {"selector": "span.px"})
        self.assertEqual((p["selector"], len(calls)), ("span.px", 1))


class RepairFallback(unittest.TestCase):
    def test_constrained_schema_and_deterministic_fallback(self):
        import selfheal
        html = '<div><span class="px">$3.42</span><span class="lbl">HH</span></div>'
        diag = selfheal.diagnose("Agent_X", html, "span.old", (1, 20))
        schemas = []
        def stubborn(prompt, schema):
            schemas.append(schema); return {"selector": "span.lbl" if len(schemas) > 1 else "span.old"}
        p = selfheal.propose_repair(diag, html, stubborn)
        self.assertEqual(set(schemas[1]["properties"]["selector"]["enum"]), {"div", "span.px", "span.lbl"} - {"div"} | set(selfheal.candidate_selectors(html)))
        self.assertEqual(p["selector"], "span.px"); self.assertEqual(p["attempts"][-1], "deterministic:span.px")
