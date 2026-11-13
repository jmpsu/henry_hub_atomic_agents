import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collectors import cpc_history as h

class T(unittest.TestCase):
    def test_available_next_day_noon(self):
        self.assertEqual(h.avail_for("2010-01-05"), "2010-01-06T12:00:00Z")
    def test_normals_only_1991_2020_and_min_years(self):
        data = {f"{y}-01-05": 30.0 for y in range(1991, 2021)}
        data["2021-01-05"] = 999.0; data["1985-01-05"] = 999.0       # outside normals period: ignored
        data.update({f"{y}-02-01": 10.0 for y in range(1991, 2000)})  # only 9 yrs: dropped
        n = h.normals(data)
        self.assertEqual(n["01-05"], 30.0); self.assertNotIn("02-01", n)
if __name__ == "__main__":
    unittest.main()
