"""課綱知識圖譜測試：清單檢查、SHA-256、代碼正規化、先修鏈與排序、觸發與不觸發、gateway 引用與訓練標記。
Curriculum graph tests: manifest checks, SHA-256, code normalization, chains and ordering, trigger rules,
gateway grounding and the training flag."""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from jiezi import curriculum as C  # noqa: E402
from jiezi.errors import JieziError  # noqa: E402


def topic(i, name, grade, codes, centrality=0.5, subject="數學"):
    return {"id": i, "type": "CONCEPTUAL", "subject": subject, "domain": "數與量", "name": name,
            "description": f"{name}的說明", "stage": (grade + 1) // 2, "gradeStart": grade, "gradeEnd": grade,
            "centrality": centrality, "elective": False, "evidence": [f"會{name}"],
            "assessmentPrompt": "請{{name}}試試看", "differentiatedTasks": {"advanced": "甲", "basic": "乙",
                                                                         "foundational": "丙"},
            "contentCodes": codes, "performanceCodes": []}


DATA = {
    "topics": {"version": "t", "topicCount": 4, "topics": [
        topic("t_c", "同分母分數的比較與加減", 3, ["math:N-3-9"]),
        topic("t_a", "單位分數的認識", 2, ["math:N-2-10"]),
        topic("t_b", "「幾分之幾」的認識", 3, ["math:N-3-9"], centrality=0.9),
        topic("t_d", "速度", 5, ["math:N-5-1"]),
    ]},
    "dependencies": {"version": "t", "note": "", "edgeCount": 2, "dependencies": [
        {"topicId": "t_b", "prerequisiteId": "t_a", "strength": "hard", "reason": "r1"},
        {"topicId": "t_c", "prerequisiteId": "t_b", "strength": "hard", "reason": "r2"},
    ]},
    "curriculum-standards": {"note": "", "curriculumVersion": "108", "subjectCount": 1, "subjects": [
        {"slug": "math", "name": "數學", "entries": [
            {"key": "math:N-3-9", "kind": "content", "code": "N-3-9", "text": "簡單同分母分數。", "category": "數與量",
             "stage": 2, "grade": 3},
            {"key": "math:N-2-10", "kind": "content", "code": "N-2-10", "text": "單位分數。", "category": "數與量",
             "stage": 1, "grade": 2},
            {"key": "math:N-5-1", "kind": "content", "code": "N-5-1", "text": "速度。", "category": "數與量",
             "stage": 3, "grade": 5},
            {"key": "math:n-II-6", "kind": "performance", "code": "n-II-6", "text": "理解同分母分數。",
             "category": "數與量", "stage": 2, "grade": None},
        ]}]},
    "clusters": {"version": "t", "clusterCount": 1, "clusters": [
        {"subject": "數學", "domain": "數與量", "stage": 2, "summary": "三四年級會學到分數。"}]},
}
BLOBS = {n: json.dumps(d, ensure_ascii=False).encode() for n, d in DATA.items()}
TEXTBOOK = """# 數學

## 數學 7上

### 翰林版
- 數與數線
  - 正數與負數
  - 正負數的加減

---

### 全華板
- 整數的运算
  - 質因數分解

## 數學 7下

### 翰林版
- 二元一次聯立方程式
"""
TB_BLOB = TEXTBOOK.encode()
FILES = "".join(f'\n[[file]]\nname = "{n}"\nurl = "https://example.invalid/{n}.json"\n'
                f'sha256 = "{hashlib.sha256(b).hexdigest()}"\n' for n, b in BLOBS.items())
MANIFEST = """[source]
key = "tw-taxonomy"
title = "測試圖譜"
publisher = "測試"
commit = "abc"
license = "CC BY 4.0"
license_url = "https://example.invalid/l"
training_use = true
attribution = "資料來源：測試圖譜"
license_checked = "2026-11-15"
""" + FILES

TEXTBOOK_MANIFEST = """
[textbooks]
key = "zetria-textbooks"
title = "測試課本"
publisher = "測試"
commit = "def"
license = "MIT"
license_url = "https://example.invalid/m"
training_use = true
attribution = "資料來源：測試課本"
license_checked = "2026-11-15"

[[textbooks.file]]
name = "國中-數學"
level = "國中"
subject = "數學"
url = "https://example.invalid/tb.md"
sha256 = "{}"
""".format(hashlib.sha256(TB_BLOB).hexdigest())


def fake_download(url, dest):
    if url.endswith(".md"):
        dest.write_bytes(TB_BLOB)
        return
    dest.write_bytes(BLOBS[url.rsplit("/", 1)[1].removesuffix(".json")])


class TestCurriculum(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.root = Path(self._t.name)
        (self.root / "curriculum").mkdir()
        (self.root / "curriculum" / "manifest.toml").write_text(MANIFEST, encoding="utf-8")

    def tearDown(self):
        self._t.cleanup()

    def built(self):
        C.build(self.root, download=fake_download, log=lambda *_: None)
        return C.Graph.load(self.root)

    def test_build_counts_and_verbatim(self):
        counts = C.build(self.root, download=fake_download, log=lambda *_: None)
        self.assertEqual(counts, {"topics": 4, "dependencies": 2, "standards": 4, "clusters": 1,
                                  "textbook_volumes": 0})
        g = C.Graph.load(self.root)
        self.assertEqual(g.standards["math:N-3-9"]["text"], "簡單同分母分數。")

    def test_sha_mismatch(self):
        with self.assertRaisesRegex(JieziError, "SHA-256"):
            C.build(self.root, download=lambda url, dest: dest.write_bytes(b"changed"), log=lambda *_: None)
        self.assertEqual(list((self.root / "var" / "curriculum").glob("*")), [])

    def test_missing_license_field(self):
        (self.root / "curriculum" / "manifest.toml").write_text(MANIFEST.replace('license = "CC BY 4.0"\n', ""))
        with self.assertRaisesRegex(JieziError, "license"):
            C.load_manifest(self.root)

    def test_not_built(self):
        with self.assertRaisesRegex(JieziError, "curriculum build"):
            C.Graph.load(self.root)

    def test_codes_and_find(self):
        g = self.built()
        self.assertEqual(g.codes("n-Ⅱ-6 和 math:N-3-9"), ["math:n-II-6", "math:N-3-9"])  # 羅馬數字正規化 / Roman numerals
        self.assertEqual(g.codes("2024-1-15"), [])
        self.assertEqual(g.find("N-3-9"), ["t_c", "t_b"])
        self.assertEqual(g.find("速度"), ["t_d"])

    def test_chain_and_plan_order(self):
        g = self.built()
        self.assertEqual(g.ancestors("t_c"), ["t_a", "t_b"])
        self.assertEqual(g.plan("數學", grade=3), ["t_b", "t_c"])     # 先修在前 / prerequisite first
        self.assertEqual(g.plan("數學", stage=1), ["t_a"])

    def test_cycle_is_rejected(self):
        DATA["dependencies"]["dependencies"].append({"topicId": "t_a", "prerequisiteId": "t_c", "strength": "soft"})
        try:
            with self.assertRaisesRegex(JieziError, "cycle"):
                C.Graph(C.load_manifest(self.root), DATA["topics"]["topics"], DATA["dependencies"]["dependencies"],
                        {}, {"math": "數學"}, [])
        finally:
            DATA["dependencies"]["dependencies"].pop()

    def test_trigger_rules(self):
        g = self.built()
        self.assertIsNone(C.grounding(g, "早安"))
        self.assertIsNone(C.grounding(g, "速度怎麼算"))                 # 沒有課綱用語 / no curriculum cue
        content, sources, trainable, appendix = C.grounding(g, "孩子學「同分母分數的比較與加減」要先學什麼？")
        self.assertEqual(sources, [{"source": "tw-taxonomy", "topic": "同分母分數的比較與加減"}])
        self.assertIn("完整先修鏈（由淺到深）：單位分數的認識、「幾分之幾」的認識", content)
        self.assertIn("請孩子試試看", content)
        self.assertTrue(trainable)
        self.assertIn("資料來源：測試圖譜", appendix)
        _, sources, _, _ = C.grounding(g, "N-3-9 是什麼？")
        self.assertEqual(sources[0], {"source": "tw-taxonomy", "code": "math:N-3-9"})
        _, sources, _, appendix = C.grounding(g, "三年級數學要學什麼？")
        self.assertEqual(sources, [{"source": "tw-taxonomy", "subject": "數學", "grade": 3, "stage": None}])
        self.assertIn("三四年級會學到分數。", appendix)

    def test_gateway_grounding(self):
        self.built()
        import httpx
        from starlette.testclient import TestClient
        from test_runtime_gateway import KEY, local_handler, make_supervisor
        from jiezi.runtime.gateway import Gateway, create_app
        from jiezi.runtime.trajectory import TrajectoryWriter
        sup, _, patch = make_supervisor(self.root)
        lh, seen = local_handler([{"role": "assistant", "content": "先學單位分數。"}])
        gw = Gateway(sup.s, sup, TrajectoryWriter(self.root / "traj", log=lambda *_: None),
                     local_http=httpx.AsyncClient(transport=httpx.MockTransport(lh)), log=lambda *_: None)
        with patch, TestClient(create_app(gw)) as c:
            self.assertEqual(c.get("/health").json()["curriculum"], "on")
            r = c.post("/v1/chat/completions", headers={"Authorization": f"Bearer {KEY}"},
                       json={"messages": [{"role": "user", "content": "國小的「幾分之幾」的認識要先學什麼？"}]}).json()
        self.assertEqual(r["jiezi"]["sources"], [{"source": "tw-taxonomy", "topic": "「幾分之幾」的認識"}])
        self.assertIn("【課綱資料原文】", r["choices"][0]["message"]["content"])
        self.assertTrue(any("單位分數的認識" in m["content"] for m in seen[0]["messages"] if m["role"] == "system"))
        traj = json.loads(next((self.root / "traj").glob("*.jsonl")).read_text().splitlines()[0])
        self.assertIsNone(traj["training_use"])  # 可訓練來源不改標記 / a trainable source leaves the flag alone



class TestTextbooks(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.root = Path(self._t.name)
        (self.root / "curriculum").mkdir()
        (self.root / "curriculum" / "manifest.toml").write_text(MANIFEST + TEXTBOOK_MANIFEST, encoding="utf-8")
        counts = C.build(self.root, download=fake_download, log=lambda *_: None)
        self.assertEqual(counts["textbook_volumes"], 3)
        self.g = C.Graph.load(self.root)

    def tearDown(self):
        self._t.cleanup()

    def test_parse(self):
        tb = self.g.textbooks
        self.assertEqual([(t["volume"], t["publisher"]) for t in tb], [("7上", "翰林版"), ("7上", "全華版"), ("7下", "翰林版")])
        self.assertEqual(tb[0]["units"], [["數與數線", ["正數與負數", "正負數的加減"]]])
        self.assertEqual(tb[1]["units"][0][0], "整數的運算")    # 純簡體字改正體 / Simplified-only char fixed

    def test_volumes(self):
        self.assertEqual(C._volumes("國一上"), ["7上"])
        self.assertEqual(C._volumes("國中一年級"), ["7上", "7下"])
        self.assertEqual(C._volumes("八年級下學期"), ["8下"])
        self.assertEqual(C._volumes("高一上"), ["高1上"])
        self.assertEqual(C._volumes("三年級"), [])

    def test_grounding(self):
        self.assertIsNone(C.grounding(self.g, "我今天學到很多"))
        content, sources, trainable, appendix = C.grounding(self.g, "國一上數學翰林版教哪些單元？")
        self.assertEqual(sources, [{"source": "zetria-textbooks", "volume": "國中數學 7上", "publisher": "翰林版"}])
        self.assertIn("1. 數與數線（正數與負數、正負數的加減）", content)
        self.assertIn("資料來源：測試課本", appendix)
        self.assertNotIn("資料來源：測試圖譜", appendix)          # 只附用到的出處 / only sources used
        self.assertTrue(trainable)
        _, sources, _, _ = C.grounding(self.g, "質因數分解在課本哪一章？")
        self.assertEqual(sources, [{"source": "zetria-textbooks", "unit": "質因數分解"}])
        self.assertIsNone(C.grounding(self.g, "國中一年級要學什麼？"))  # 不套用國小年級 / not primary grade 1


if __name__ == "__main__":
    unittest.main()
