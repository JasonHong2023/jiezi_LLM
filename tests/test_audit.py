"""安全稽核測試：PyPI 與 git 鎖定讀取、已接受清單、未接受的漏洞讓稽核失敗。 / Audit tests."""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jiezi import audit as A  # noqa: E402

LOCK = '''[[package]]
name = "httpx"
version = "0.28.1"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "jiezi"
version = "0.1.0"
source = { editable = "." }
'''
STACK = "| 推論引擎 | llama.cpp | commit `" + "a" * 40 + "` |\n"


class TestAudit(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.root = Path(self._t.name)
        (self.root / "uv.lock").write_text(LOCK)
        (self.root / "openspec" / "specs").mkdir(parents=True)
        (self.root / "openspec" / "specs" / "stack.md").write_text(STACK, encoding="utf-8")
        (self.root / "security").mkdir()
        (self.root / "security" / "accepted.toml").write_text('[[accepted]]\nid = "GHSA-old"\nreason = "fixed before the pin"\n')

    def tearDown(self):
        self._t.cleanup()

    def test_reads_pins(self):
        self.assertEqual(A.pypi_packages(self.root), [("httpx", "0.28.1")])        # 只算 registry 套件 / registry only
        self.assertEqual(A.git_pins(self.root), {"llama.cpp": "a" * 40})

    def test_unaccepted_fails(self):
        post = lambda url, body: {"results": [{"vulns": [{"id": "PYSEC-1"}]}, {}]}  # noqa: E731
        get = lambda url: [{"ghsa_id": "GHSA-old"}, {"ghsa_id": "GHSA-new"}] if "llama" in url else []  # noqa: E731
        out, r = A.run(self.root, post=post, get=get)
        ids = sorted(i for f in r["unaccepted"] for i in f["ids"])
        self.assertEqual(ids, ["GHSA-new", "PYSEC-1"])
        self.assertIn("已接受：fixed before the pin", out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
