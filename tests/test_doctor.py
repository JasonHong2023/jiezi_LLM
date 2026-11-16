"""健康檢查測試：空目錄要列出修復方法、不當機。 / Doctor tests: an empty tree lists fixes without crashing."""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jiezi.runtime import doctor  # noqa: E402


class TestDoctor(unittest.TestCase):
    def test_empty_tree(self):
        with tempfile.TemporaryDirectory() as d:
            text, rc = doctor.report(Path(d), 1)  # port 1：不會有 gateway / nothing listens
        self.assertEqual(rc, 1)
        self.assertIn("scripts/jiezi data build", text)
        self.assertIn("scripts/bootstrap", text)
        self.assertIn("scripts/jiezi start", text)


if __name__ == "__main__":
    unittest.main()
