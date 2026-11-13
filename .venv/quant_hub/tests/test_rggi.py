import os, sqlite3, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import init_db
from collectors import rggi_auctions as g
H = "".join(f"<th>{c}</th>" for c in g.EXPECTED)
HTML = f"<table><tr>{H}</tr><tr><td>Auction 73</td><td>2026-09-09</td><td>1</td><td>2</td><td>3</td><td>$37.65</td><td>$1</td></tr><tr><td>Auction 72</td><td>2026-06-03</td><td>1</td><td>0</td><td>3</td><td>$35.00</td><td>$1</td></tr></table>"
class T(unittest.TestCase):
    def test_parse_and_load(self):
        self.assertEqual(g.parse(HTML)[0], ("Auction 73", "2026-09-09", 37.65))
        f = os.path.join(tempfile.mkdtemp(), "t.db"); init_db.migrate(f); c = sqlite3.connect(f)
        self.assertEqual(g.collect(c, fetcher=lambda u: (200, HTML.encode(), "text/html"))[0]["observations_new"], 2)
        self.assertEqual(g.collect(c, fetcher=lambda u: (200, HTML.encode(), "text/html"))[0]["observations_new"], 0)
        self.assertEqual(c.execute("select available_timestamp from pit_market_data where target_timestamp like '2026-09-09%'").fetchone()[0], "2026-09-10T16:00:00Z")
    def test_layout_change_raises(self):
        with self.assertRaises(ValueError): g.parse("<table><tr><th>X</th></tr></table>")
if __name__ == "__main__": unittest.main()
