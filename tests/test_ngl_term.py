import importlib.util, io, os, sqlite3, sys, unittest
from datetime import date, timedelta
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import _scratch
import init_db, ingest
import markets_engine as me
from rich.console import Console

spec = importlib.util.spec_from_file_location("ngl_term", ROOT / "ngl-term.py")
nt = importlib.util.module_from_spec(spec); spec.loader.exec_module(nt)


class Braille(unittest.TestCase):
    def test_cell_bits(self):
        b = nt.Braille(1, 1)
        self.assertEqual(b.text().plain, "⠀")              # empty cell
        for x, y in ((0, 0), (1, 0), (0, 1), (1, 1), (0, 2), (1, 2), (0, 3), (1, 3)):
            b.dot(x, y)
        self.assertEqual(b.text().plain, "⣿")              # all eight dots
        c = nt.Braille(2, 1); c.dot(0, 3); c.dot(3, 0)
        self.assertEqual(c.text().plain, chr(0x2840) + chr(0x2808))
    def test_all_map_chars_are_braille_or_labels(self):
        b = nt.Braille(10, 2); b.line(0, 0, 19, 7)
        self.assertTrue(all(0x2800 <= ord(ch) <= 0x28FF for ch in b.text().plain if ch != "\n"))


class Frame(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = _scratch.TemporaryDirectory(); db = os.path.join(cls.dir.name, "t.db"); init_db.migrate(db); c = sqlite3.connect(db)
        for i in range(400):
            d = date(2025, 1, 1) + timedelta(days=i); t = d.isoformat() + "T00:00:00Z"; a = d.isoformat() + "T21:00:00Z"
            ingest.record_observation(c, agent_id="Agent_NGL_MontBelvieu_Propane", target_timestamp=t, available_timestamp=a, value=80 + (i % 40), source_id="t", unit="cents/gal")
            ingest.record_observation(c, agent_id="Agent_Crude_WTI_Spot", target_timestamp=t, available_timestamp=a, value=84.0, source_id="t", unit="USD/bbl")
            ingest.record_observation(c, agent_id="Agent_HH_Spot_EIA", target_timestamp=t, available_timestamp=a, value=3.0, source_id="t", unit="USD/MMBtu")
        c.commit(); c.close()
        cls.db = db
    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()
    def render(self, product, timeframe):
        s = me.build_state(self.db, product, timeframe, "2026-02-01T00:00:00Z")
        con = Console(file=io.StringIO(), width=180, height=56, color_system=None)
        con.print(nt.frame(s, "test://state", 180, 56, nt.load_basemap()), height=56)
        return s, con.file.getvalue()
    def test_frame_shows_the_same_numbers_as_state_json(self):
        s, out = self.render("propane", "seasonal")
        for needle in ("NORTH AMERICAN ENERGY HUB", "FIBONACCI RETRACEMENT", "SOURCE AVAILABILITY TRANSPARENCY", "PRICING OUTPUT", "REGIONAL FLOWS",
                       f"{s['price']['value']:.1f} cents/gal", f"{s['technicals']['fibonacci']['levels']['61.8%']:,.1f}", "●MBV"):
            self.assertIn(needle, out)
        self.assertTrue(any(0x2801 <= ord(ch) <= 0x28FF for ch in out))      # the map really is Braille
    def test_pending_product_is_never_given_a_value(self):
        s, out = self.render("ethane", "intraday")
        self.assertIn("PENDING COLLECTOR", out); self.assertIsNone(s["price"]["value"])
    def test_schema_mismatch_rejected(self):
        import json, http.server, threading
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                b = json.dumps({"schema": "other/9"}).encode(); self.send_response(200); self.end_headers(); self.wfile.write(b)
            def log_message(self, *a): pass
        srv = http.server.HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with self.assertRaises(ValueError): nt.fetch_state(f"http://127.0.0.1:{srv.server_port}/api/state.json", None, "seasonal")
        finally:
            srv.shutdown()


if __name__ == "__main__":
    unittest.main()
