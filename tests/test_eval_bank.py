"""題庫定義與授權閘門測試（規格 eval：Pinned Bank Sources、License Gate、Bank Composition）。
Tests for the bank definition and license gate."""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jiezi.eval import EvalError  # noqa: E402
from jiezi.eval import bank  # noqa: E402

LICENSES = """# x
| 登記鍵 / Key | 項目 |
|---|---|
| `lic-a` | A |
| `lic-b` | B |

## 已排除 / Excluded

| 項目 | 原因 |
|---|---|
| `lic-excluded` | no |
"""

SHA = "a" * 64


def source(key, task, count, license_key="lic-a", sha=SHA, url="https://example.invalid/f"):
    return f"""
[[source]]
key = "{key}"
license_key = "{license_key}"
task = "{task}"
group = "knowledge"
scorer = "multiple_choice"
format = "x"
count = {count}

[[source.file]]
name = "f"
url = "{url}"
sha256 = "{sha}"
"""


def full(**over):
    parts = {"qa": source("q", "qa", 50), "code": source("c", "code", 50),
             "summary": source("s", "summary", 50), "tool": source("t", "tool", 50)}
    parts.update(over)
    return 'name = "t"\nversion = 1\nseed = 1\n' + "".join(parts.values())


class TestBank(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.lic = self.dir / "licenses.md"
        self.lic.write_text(LICENSES)

    def tearDown(self):
        self._tmp.cleanup()

    def load(self, text):
        p = self.dir / "b.toml"
        p.write_text(text)
        return bank.load_bank(p, self.lic)

    def test_repo_r0_is_valid(self):
        b = bank.load_bank(ROOT / "eval" / "banks" / "r0.toml", ROOT / "docs" / "licenses.md")
        self.assertEqual(b.name, "r0")
        counts = {}
        for s in b.sources:
            counts[s.task] = counts.get(s.task, 0) + s.count
        self.assertTrue(all(counts[t] >= 50 for t in bank.TASKS))
        wiki = next(s for s in b.sources if s.format == "wiki_featured")
        self.assertEqual(wiki.options["list_revid"], 95548025)

    def test_registry_ignores_excluded_table(self):
        self.assertEqual(bank.registry_keys(self.lic), {"lic-a", "lic-b"})

    def test_unregistered_license_is_refused(self):
        with self.assertRaisesRegex(EvalError, "not registered"):
            self.load(full(qa=source("q", "qa", 50, license_key="lic-excluded")))

    def test_bad_sha_and_plain_http(self):
        with self.assertRaisesRegex(EvalError, "invalid sha256"):
            self.load(full(qa=source("q", "qa", 50, sha="abc")))
        with self.assertRaisesRegex(EvalError, "https"):
            self.load(full(qa=source("q", "qa", 50, url="http://example.invalid/f")))

    def test_task_with_too_few_items(self):
        with self.assertRaisesRegex(EvalError, "short: tool=49"):
            self.load(full(tool=source("t", "tool", 49)))

    def test_invalid_task(self):
        with self.assertRaisesRegex(EvalError, "task must be one of"):
            self.load(full(tool=source("t", "chat", 50)))


if __name__ == "__main__":
    unittest.main()
