"""本機辭典測試：清單檢查、SHA-256、建置不改內容、觸發與不觸發、最長優先、虛詞排除、gateway 引用與訓練標記。
Local dictionary tests: manifest checks, SHA-256, verbatim build, trigger rules, longest match, stop words,
gateway grounding and the training flag."""

import hashlib
import json
import lzma
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from jiezi import dictionary as D  # noqa: E402
from jiezi.errors import JieziError  # noqa: E402

ENTRIES = [
    {"title": "芥子", "heteronyms": [{"bopomofo": "ㄐㄧㄝˋ ㄗˇ", "pinyin": "jiè zǐ",
                                      "definitions": [{"def": "芥菜的種子。"}]}]},
    {"title": "樂不思蜀", "heteronyms": [{"bopomofo": "ㄌㄜˋ ㄅㄨˋ ㄙ ㄕㄨˇ", "definitions": [
        {"def": "比喻樂而忘返。", "quote": ["甲", "乙", "丙"]}]}]},
    {"title": "樂不", "heteronyms": [{"definitions": [{"def": "x"}]}]},
    {"title": "什麼", "heteronyms": [{"definitions": [{"def": "疑問代詞。"}]}]},
    {"title": "台", "heteronyms": [{"definitions": [{"def": "臺的異體。"}]}]},
]
BLOB = lzma.compress(json.dumps(ENTRIES, ensure_ascii=False).encode())
SHA = hashlib.sha256(BLOB).hexdigest()
MANIFEST = f"""
[[source]]
key = "t"
title = "測試辭典"
publisher = "測試"
format = "moedict_json_xz"
url = "https://example.invalid/t.json.xz"
sha256 = "{SHA}"
size = {len(BLOB)}
license = "CC BY-ND 3.0 TW"
license_url = "https://example.invalid/l"
training_use = false
attribution = "資料來源：測試辭典"
license_checked = "2026-11-15"
"""


class TestDictionary(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.root = Path(self._t.name)
        (self.root / "dictionaries").mkdir()
        (self.root / "dictionaries" / "manifest.toml").write_text(MANIFEST, encoding="utf-8")

    def tearDown(self):
        self._t.cleanup()

    def built(self):
        D.build(self.root, download=lambda url, dest: dest.write_bytes(BLOB), log=lambda *_: None)
        return D.Dictionary(D.db_path(self.root))

    def test_build_keeps_entries_verbatim(self):
        d = self.built()
        self.assertEqual(d.lookup("芥子")[0][1], ENTRIES[0])
        self.assertEqual(d.meta["t"]["training_use"], False)

    def test_sha_mismatch_keeps_old_db(self):
        self.built()
        with self.assertRaisesRegex(JieziError, "SHA-256"):
            for p in (self.root / "var" / "dict" / "cache").glob("*"):
                p.unlink()
            D.build(self.root, download=lambda url, dest: dest.write_bytes(b"changed"), log=lambda *_: None)
        self.assertTrue(D.Dictionary(D.db_path(self.root)).has("芥子"))

    def test_missing_license_field(self):
        (self.root / "dictionaries" / "manifest.toml").write_text(MANIFEST.replace('license = "CC BY-ND 3.0 TW"\n', ""))
        with self.assertRaisesRegex(JieziError, "license"):
            D.load_manifest(self.root)

    def test_trigger_rules(self):
        d = self.built()
        self.assertEqual(d.terms_in("「樂不思蜀」"), ["樂不思蜀"])
        self.assertEqual(d.terms_in("芥子是什麼意思"), ["芥子"])          # 虛詞排除 / stop word excluded
        self.assertEqual(d.terms_in("樂不思蜀的出處？"), ["樂不思蜀"])    # 最長優先 / longest first
        self.assertEqual(d.terms_in("早安，芥子"), [])                  # 沒有提問用語 / no word-question cue

    def test_render_limits_quotes(self):
        text = D.render(ENTRIES[1])
        self.assertIn("甲", text)
        self.assertNotIn("丙", text)

    def test_grounding_and_gateway(self):
        d = self.built()
        content, sources, trainable, appendix = D.grounding(d, "「芥子」是什麼意思？")
        self.assertIn("芥菜的種子。", content)
        self.assertIn("芥菜的種子。", appendix)
        self.assertIn("資料來源：測試辭典", appendix)
        self.assertEqual((sources, trainable), ([{"source": "t", "title": "芥子"}], False))
        self.assertIsNone(D.grounding(d, "早安"))

        import httpx
        from starlette.testclient import TestClient
        from test_runtime_gateway import KEY, local_handler, make_supervisor
        from jiezi.runtime.gateway import Gateway, create_app
        from jiezi.runtime.trajectory import TrajectoryWriter
        sup, _, patch = make_supervisor(self.root)
        lh, seen = local_handler([{"role": "assistant", "content": "芥菜的種子。"}])
        gw = Gateway(sup.s, sup, TrajectoryWriter(self.root / "traj", log=lambda *_: None),
                     local_http=httpx.AsyncClient(transport=httpx.MockTransport(lh)), log=lambda *_: None)
        with patch, TestClient(create_app(gw)) as c:
            r = c.post("/v1/chat/completions", headers={"Authorization": f"Bearer {KEY}"},
                       json={"messages": [{"role": "user", "content": "「芥子」是什麼意思？"}]}).json()
            r2 = c.post("/v1/chat/completions", headers={"Authorization": f"Bearer {KEY}"},
                        json={"messages": [{"role": "user", "content": "早安"}]}).json()
        self.assertEqual(r["jiezi"]["sources"], [{"source": "t", "title": "芥子"}])
        self.assertIn("【辭典原文】", r["choices"][0]["message"]["content"])  # 原文由 gateway 附上 / appended verbatim
        self.assertTrue(any("芥菜的種子" in m["content"] for m in seen[0]["messages"] if m["role"] == "system"))
        self.assertEqual(r2["jiezi"]["sources"], [])
        traj = [json.loads(x) for x in next((self.root / "traj").glob("*.jsonl")).read_text().splitlines()]
        self.assertIs(traj[0]["training_use"], False)
        self.assertIsNone(traj[1]["training_use"])



class TestTextConv(unittest.TestCase):
    def test_only_simplified_only_chars_change(self):
        from jiezi.textconv import to_traditional
        self.assertEqual(to_traditional("劉禅说话"), "劉禪說話")
        self.assertEqual(to_traditional("皇后在台上"), "皇后在台上")  # 也是正體字，不改 / also Traditional
        self.assertIsNone(to_traditional(None))


if __name__ == "__main__":
    unittest.main()
