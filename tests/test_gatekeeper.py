import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ingestion.validation.gatekeeper import check

class T(unittest.TestCase):
    def test_storage_range(self):
        self.assertTrue(check("Agent_Storage_East", 926.0)[0])
        self.assertFalse(check("Agent_Storage_East", 926000.0)[0])  # MMBtu mistaken for Bcf
    def test_nan_rejected(self):
        self.assertFalse(check("Agent_X", float("nan"))[0])
if __name__ == "__main__":
    unittest.main()
