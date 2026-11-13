import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collectors import ecmwf_hdd as e

class T(unittest.TestCase):
    def test_index_range_inclusive_end(self):
        idx = '{"param":"msl","levtype":"sfc","_offset":0,"_length":100}\n{"param":"2t","levtype":"sfc","_offset":100,"_length":50}\n'
        self.assertEqual(e.parse_index(idx), (100, 149))
    def test_missing_param_raises(self):
        with self.assertRaises(ValueError): e.parse_index('{"param":"msl","_offset":0,"_length":1}')
    def test_day10_and_beyond_unsupported(self):
        self.assertGreater(24 * 10 + 6, e.MAX_STEP)   # Day10 needs step 246 > 240
if __name__ == "__main__":
    unittest.main()
