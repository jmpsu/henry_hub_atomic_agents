import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collectors import gfs_hdd as g

IDX = "1:0:d=2026111100:HGT:500 mb:24 hour fcst:\n2:100:d=2026111100:TMP:2 m above ground:24 hour fcst:\n3:250:d=2026111100:RH:2 m above ground:24 hour fcst:\n"

class T(unittest.TestCase):
    def test_idx_range_is_start_to_next_minus_one(self):
        self.assertEqual(g.parse_idx(IDX), {24: (100, 249)})
    def test_hdd_conversion(self):
        self.assertAlmostEqual(g.hdd_f(273.15), 33.0)   # 32F -> 33 HDD
        self.assertEqual(g.hdd_f(300.0), 0.0)            # hot day -> 0
    def test_weights_sum(self):
        self.assertAlmostEqual(g.weighted_hdd([273.15] * len(g.METROS)), 33.0)
    def test_grid_index_wraps_longitude(self):
        self.assertEqual(g.grid_index(40.0, -74.0)[1], round((360 - 74) / 0.25))
        self.assertEqual(g.grid_index(90.0, 0.0), (0, 0))
if __name__ == "__main__":
    unittest.main()
