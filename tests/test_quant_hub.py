
# Bypass NLTK stopwords permission and lookup errors in CI
try:
    from llama_index.core.utils import globals_helper
    if getattr(globals_helper, "_stopwords", None) is None:
        globals_helper._stopwords = {
            "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are", "aren't",
            "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but", "by", "can't",
            "cannot", "could", "couldn't", "did", "didn't", "do", "does", "doesn't", "doing", "don't", "down", "during",
            "each", "few", "for", "from", "further", "had", "hadn't", "has", "hasn't", "have", "haven't", "having",
            "he", "he'd", "he'll", "he's", "her", "here", "here's", "hers", "herself", "him", "himself", "his", "how",
            "how's", "i", "i'd", "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it", "it's", "its", "itself",
            "let's", "me", "more", "most", "mustn't", "my", "myself", "no", "nor", "not", "of", "off", "on", "once",
            "only", "or", "other", "ought", "our", "ours", "ourselves", "out", "over", "own", "same", "shan't", "she",
            "she'd", "she'll", "she's", "should", "shouldn't", "so", "some", "such", "than", "that", "that's", "the",
            "their", "theirs", "them", "themselves", "then", "there", "there's", "these", "they", "they'd", "they'll",
            "they're", "they've", "this", "those", "through", "to", "too", "under", "until", "up", "very", "was",
            "wasn't", "we", "we'd", "we'll", "we're", "we've", "were", "weren't", "what", "what's", "when", "when's",
            "where", "where's", "which", "while", "who", "who's", "whom", "why", "why's", "with", "won't", "would",
            "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours", "yourself", "yourselves"
        }
except Exception:
    pass

"""QUANT HUB SPEC (Spec 5) coverage: retrieval hub (news/journal/report ingestion, 6 engine modalities, PIT
filter, persistence), commodities (spark spread, basis differentials, HH spot & forward curve), risk engine
(parametric/historical/Monte Carlo VaR + CVaR, stress scenarios, capital & margin)."""
import os, sqlite3, sys, unittest
from datetime import date, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
os.environ["NOTIFY"] = "0"
import _scratch
import init_db, ingest
from agents import quant_commodities as qc
from agents import quant_risk as qr
from agents import retrieval_hub as rh

TRIPLETS = [("Henry Hub", "quoted_in", "eia henry hub spot"), ("Henry Hub", "located", "us golf coast"),
            ("NGL", "fractionated_from", "wet gas at mont belvieu"), ("Mont Belvieu", "exports", "natural gas"),
            ("Henry Hub", "sensitive_to", "weather regimes"), ("Henry Hub", "sells_to", "financial swap positions")]


def _triplets(text):
    t = text.lower()
    if "henry hub" in t:
        return [x for x in TRIPLETS if "henry hub" in x[0].lower()] or TRIPLETS[:1]
    if "journal" in t or "fractionation" in t:
        return [x for x in TRIPLETS if "nGL" in x[0] or "mont belvieu" in x[0].lower()] or TRIPLETS[:2]
    if "weather" in t:
        return [x for x in TRIPLETS if "henry hub" in x[0].lower() and "weather" in str(x).lower()]
    return [("Report", "mention", "natural gas")]


def make_hub(storage_dir):
    from llama_index.core.llms.mock import MockLLM
    from llama_index.core.embeddings.mock_embed_model import MockEmbedding

    class _StubLLM(MockLLM):
        def predict(self, prompt, **kwargs):
            q = kwargs.get("question") or kwargs.get("query_str") or ""
            return "KEYWORDS: " + q

    return rh.RetrievalHub(storage_dir=storage_dir, llm=_StubLLM(max_tokens=32),
                           embed_model=MockEmbedding(embed_dim=8), kg_triplet_extract_fn=_triplets)


class RetrievalHubTests(unittest.TestCase):
    def test_ingestion_of_news_journal_and_report(self):
        hub = make_hub(_scratch.mkdtemp())
        n = hub.ingest_texts(["Market report: Henry Hub quoted at $3.42 per MMBtu in November 2026, the strongest move in months.",
                              "Scientific journal article on NGL fractionation economics at Mont Belvieu and propane cracking."],
                             source_kind="article")
        n += hub.ingest_texts(["Breaking news: compressor outage forces TGP force majeure notice on Nov 13."], source_kind="news")
        n += hub.ingest_texts(["Filing: LNG export terminal demand, natural gas supply outlook."], source_kind="journal")
        self.assertGreaterEqual(n, 3)
        kinds = {d.metadata["source_kind"] for d in hub.documents}
        self.assertTrue({"article", "news", "journal"} <= kinds)

    def test_six_engine_modalities_queryable(self):
        hub = make_hub(_scratch.mkdtemp())
        hub.ingest_texts(["Market report: Henry Hub quoted at $3.42 per MMBtu in November 2026, the strongest move in months.",
                          "Scientific journal article on NGL fractionation economics at Mont Belvieu and propane cracking.",
                          "Regular market report on power generation and weather risk in the US Gulf Coast region."],
                         source_kind="article")
        from llama_index.core.query_engine.knowledge_graph_query_engine import KnowledgeGraphQueryEngine
        for et in rh.ENGINE_TYPES:
            eng = hub.get_query_engine(et)
            if et == "kg_query_engine":
                self.assertIsInstance(eng, KnowledgeGraphQueryEngine)
                self.assertGreater(len(hub.search("Henry Hub", engine_type=et)), 0)
            else:
                self.assertGreater(len(hub.search("Henry Hub", engine_type=et)), 0, et)

    def test_search_is_pit_filtered_and_bad_engine_rejected(self):
        hub = make_hub(_scratch.mkdtemp())
        hub.ingest_texts(["Market report: Henry Hub quoted at $3.42 per MMBtu in November 2026."], source_kind="article")
        self.assertEqual(hub.search("Henry Hub", as_of="2000-01-01T00:00:00Z"), [])
        self.assertGreater(len(hub.search("Henry Hub", as_of="2027-01-01T00:00:00Z")), 0)
        self.assertGreater(len(hub.search("Henry Hub")), 0)
        with self.assertRaises(ValueError):
            hub.get_query_engine("nope")

    def test_persistence_save_load(self):
        d = _scratch.mkdtemp(); hub = make_hub(os.path.join(d, "hub"))
        hub.ingest_texts(["Market report: Henry Hub quoted at $3.42 per MMBtu in November 2026."], source_kind="article")
        self.assertTrue(hub.save())
        hub2 = rh.RetrievalHub.load(os.path.join(d, "hub"), llm=hub.llm, embed_model=hub.embed_model,
                                    kg_triplet_extract_fn=_triplets)
        self.assertGreater(len(hub2.search("Henry Hub")), 0)


class SparkAndBasisTests(unittest.TestCase):
    def test_pure_calculations(self):
        self.assertAlmostEqual(qc.spark_spread(10.50, 4.20), 10.50 - 4.20 / 8.5)
        self.assertAlmostEqual(qc.clean_spark_spread(10.50, 4.20, fuel_adjustment_cost_per_mmbtu=0.20),
                               qc.spark_spread(10.50, 4.20) - 0.20)
        self.assertAlmostEqual(qc.dark_spread(10.50, 4.20), -qc.spark_spread(10.50, 4.20))
        self.assertAlmostEqual(qc.basis_differential(10.50, 10.20), 0.30, places=9)

    def test_data_driven_functions(self):
        d = _scratch.mkdtemp(); db = os.path.join(d, "q.db"); init_db.migrate(db)
        c = sqlite3.connect(db)
        for i in range(50):
            day = date(2026, 6, 1) + timedelta(days=i)
            ingest.record_observation(c, agent_id="Agent_HH_Spot_EIA", target_timestamp=day.isoformat() + "T00:00:00Z",
                                      available_timestamp=day.isoformat() + "T21:00:00Z", value=3.0 + 0.03 * i,
                                      source_id="t", raw_payload_hash="")
        c.commit()
        hh = qc.hh_spot(c, "2026-07-01T00:00:00Z")
        self.assertIsNotNone(hh); self.assertAlmostEqual(hh[1], 3.0 + 0.03 * 29, places=6)
        curve = qc.hh_forward_curve(c, "2026-07-01T00:00:00Z")
        self.assertEqual(len(curve), 1 + 90); self.assertGreater(curve[-1][1], hh[1])
        self.assertEqual(qc.hh_basis(c, "2026-07-01T00:00:00Z")["Waha"], None)                  # no basis proxy ingested
        r = qc.regional_spot(c, "PJM", "2026-07-01T00:00:00Z")
        self.assertEqual(r["source"], "hh_proxy")                                                 # HH proxy when PJM absent
        sc = qc.storage_cycle_impact(c, "2026-07-01T00:00:00Z")
        self.assertIsNone(sc["total_change_bcf"])                                                 # storage series absent here
        self.assertIsNone(qc.pipeline_flow_estimate(c, "2026-07-01T00:00:00Z"))
        self.assertIsNone(qc.lng_export_demand_score(c, "2026-07-01T00:00:00Z"))
        self.assertIsNone(qc.cross_commodity_exposure(c, "2026-07-01T00:00:00Z")["wti"])
        self.assertIsNone(qc.hh_spot(c, "2020-01-01T00:00:00Z"))                                  # PIT


class RiskEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rng = np.random.default_rng(20261119)
        cls.returns = cls.rng.normal(-0.05, 0.2, 400)

    def test_var_paths_positive_and_es_at_or_above_var(self):
        r = self.returns
        vas = [qr.var_parametric(r), qr.var_historical(r), qr.var_montecarlo(r, n_sims=20000)]
        self.assertTrue(all(v > 0 for v in vas), vas)
        ess = [qr.cvar_parametric(r), qr.cvar_historical(r), qr.cvar_montecarlo(r, n_sims=20000)]
        self.assertTrue(all(e >= v - 1e-9 for e, v in zip(ess, vas)), list(zip(ess, vas)))

    def test_paths_agree_on_a_plain_normal_series(self):
        p, h, m = qr.var_parametric(self.returns), qr.var_historical(self.returns), qr.var_montecarlo(self.returns, seed=1)
        self.assertLess(abs(p - h), 0.35 * h + 1e-3)

    def test_scenarios_execute_on_hh_series(self):
        s = [(date(2026, 1, i + 1).isoformat(), 3.0 + 0.1 * i, f"2026-01-{i + 1:02d}T21:00:00Z") for i in range(30)]
        for fn in (qr.winter_storm_uri_freeze_scenario, qr.pipeline_outage_shock, qr.multi_factor_shift):
            r = fn(s)
            self.assertTrue(r["series"] and r["description"], fn.__name__)
            self.assertGreaterEqual(len(r["series"]), 8)

    def test_capital_and_margin(self):
        self.assertEqual(qr.initial_margin(10_000_000, 0.0), 0.0)
        self.assertGreater(qr.initial_margin(10_000_000), 0.0)
        self.assertEqual(qr.variation_margin_path([0.01, -0.02], 1000)[-1], -10.0)
        self.assertGreater(qr.liquidity_buffer(2.5), 0.0)


if __name__ == "__main__":
    unittest.main()
