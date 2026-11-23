"""台灣知識庫測試：lock 與 blob 雜湊、frontmatter 與段落、雙字索引、點名與全文檢索的觸發規則、gateway 引用。
Taiwan knowledge tests: lock and blob hashes, parsing, bigram index, trigger rules, gateway grounding."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from jiezi import knowledge as K  # noqa: E402
from jiezi.errors import JieziError  # noqa: E402

ARTICLES = {
    "knowledge/Food/刈包.md": """---
title: '刈包：虎咬豬'
category: 'Food'
lastHumanReview: false
---

![圖](/x.webp)
_圖說。_

> 刈包源自福州的荷葉包，在台灣稱虎咬豬[^1]。

## 尾牙與職工
農曆十二月十六日尾牙吃刈包慰勞職工，双手捧著[^2]。

## 延伸閱讀
- [某網站](https://example.com)

[^1]: 來源一
""",
    "knowledge/Technology/台灣BIM.md": """---
title: '台灣 BIM'
lastHumanReview: true
---
營建業常用 Python 寫腳本自動排序構件與函式庫。
""",
    "knowledge/en/Food/gua-bao.md": "translation, skipped",
    "knowledge/Food/_Food Hub.md": "hub, skipped",
}
BLOBS = {p: t.encode() for p, t in ARTICLES.items()}
C = "c0ffee"
MANIFEST = f"""[source]
key = "taiwan-md"
title = "測試知識庫"
repo = "o/r"
commit = "{C}"
license = "CC BY-SA 4.0"
license_url = "https://example.invalid/l"
training_use = true
attribution = "資料來源：測試知識庫"
license_checked = "2026-11-15"
lock = "lock.json"
"""


class TestKnowledge(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.root = Path(self._t.name)
        (self.root / "knowledge").mkdir()
        (self.root / "knowledge" / "manifest.toml").write_text(MANIFEST, encoding="utf-8")
        tree = {"truncated": False, "tree": [{"type": "blob", "path": p, "sha": K.git_blob_sha(b), "size": len(b)}
                                             for p, b in BLOBS.items()]}
        files = K.make_lock("o/r", C, lambda url: tree)
        (self.root / "knowledge" / "lock.json").write_text(json.dumps({"commit": C, "files": files}))
        self.files = files

    def tearDown(self):
        self._t.cleanup()

    def get(self, url):
        return next(b for p, b in BLOBS.items() if url.endswith(K.urllib.parse.quote(p)))

    def built(self):
        K.build(self.root, get=self.get, log=lambda *_: None, workers=1)
        return K.Knowledge(K.db_path(self.root))

    def test_lock_skips_translations_and_hubs(self):
        self.assertEqual(sorted(f["path"] for f in self.files),
                         ["knowledge/Food/刈包.md", "knowledge/Technology/台灣BIM.md"])

    def test_hash_mismatch(self):
        with self.assertRaisesRegex(JieziError, "blob hash"):
            K.build(self.root, get=lambda url: b"changed", log=lambda *_: None, workers=1)
        self.assertFalse(K.db_path(self.root).exists())

    def test_parse_and_index(self):
        k = self.built()
        rows = k.con.execute("SELECT heading, text FROM sections ORDER BY id").fetchall()
        self.assertEqual([h for h, _ in rows], ["刈包：虎咬豬", "尾牙與職工", "台灣 BIM"])  # 延伸閱讀不收 / skipped
        self.assertNotIn("[^", rows[0][1])
        self.assertNotIn("x.webp", rows[0][1])
        self.assertIn("雙手", rows[1][1])                                         # 純簡體字改正體 / fixed
        self.assertEqual(k.con.execute("SELECT reviewed FROM articles WHERE name = '台灣BIM'").fetchone()[0], 1)

    def test_bigrams(self):
        self.assertEqual(K.bigrams("刈包 Python好"), ["刈包", "python"])

    def test_grounding_rules(self):
        k = self.built()
        self.assertIsNone(K.grounding(k, "早安"))
        self.assertIsNone(K.grounding(k, "寫一個 Python 排序函式"))  # 文章名稱沒有共同字詞 / no name overlap
        content, sources, trainable, appendix = K.grounding(k, "刈包是什麼？")
        self.assertEqual(sources[0], {"source": "taiwan-md", "article": "刈包", "section": "刈包：虎咬豬"})
        self.assertIn("荷葉包", content)
        self.assertIn("（未經人工審核）", appendix)
        self.assertIn("資料來源：測試知識庫", appendix)
        self.assertTrue(trainable)
        _, sources, _, _ = K.grounding(k, "尾牙為什麼要吃虎咬豬慰勞職工")  # 全文檢索 / full-text match
        self.assertEqual(sources[0]["section"], "尾牙與職工")

    def test_vector_hits_carry_scores(self):
        # tune-knowledge-relevance 2.2：向量檢索的分數帶進 sources；全文與點名沒有分數
        k = self.built()
        sid = k.con.execute("SELECT id FROM sections ORDER BY id LIMIT 1").fetchone()[0]
        _, sources, _, _ = K.grounding(k, "早安你好", hybrid=lambda text, n: [(sid, 0.712345)])
        self.assertEqual(sources[0]["score"], 0.7123)
        _, sources, _, _ = K.grounding(k, "刈包是什麼？")
        self.assertNotIn("score", sources[0])

    def test_gateway(self):
        self.built()
        import httpx
        from starlette.testclient import TestClient
        from test_runtime_gateway import KEY, local_handler, make_supervisor
        from jiezi.runtime.gateway import Gateway, create_app
        from jiezi.runtime.trajectory import TrajectoryWriter
        sup, _, patch = make_supervisor(self.root)
        lh, seen = local_handler([{"role": "assistant", "content": "刈包又叫虎咬豬。"}])
        gw = Gateway(sup.s, sup, TrajectoryWriter(self.root / "traj", log=lambda *_: None),
                     local_http=httpx.AsyncClient(transport=httpx.MockTransport(lh)), log=lambda *_: None)
        with patch, TestClient(create_app(gw)) as c:
            self.assertEqual(c.get("/health").json()["knowledge"], "on")
            r = c.post("/v1/chat/completions", headers={"Authorization": f"Bearer {KEY}"},
                       json={"messages": [{"role": "user", "content": "刈包是什麼？"}]}).json()
        self.assertEqual(r["jiezi"]["sources"][0]["article"], "刈包")
        self.assertIn("【參考資料】", r["choices"][0]["message"]["content"])
        self.assertTrue(any("荷葉包" in m["content"] for m in seen[0]["messages"] if m["role"] == "system"))


if __name__ == "__main__":
    unittest.main()
