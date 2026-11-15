"""答案查核與台灣用語測試。 / Grounded-answer check and Taiwan phrasing tests."""

import json
import random
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from jiezi.runtime import escalation as E  # noqa: E402
from jiezi.textconv import TaiwanStream, to_taiwan  # noqa: E402

SOURCE = "刈包源自福州。1955 年華西街的源芳開業，距今超過七十年。農曆十二月十六日尾牙。1927 年黃旺成日記記載「虎咬豬」。"


class TestGrounded(unittest.TestCase):
    def check(self, answer, grounding=SOURCE):
        return E.verify_grounded({"content": answer}, grounding)

    def test_not_applicable_without_data(self):
        self.assertEqual(self.check("2026 年", None)["status"], "not_applicable")

    def test_pass(self):
        self.assertEqual(self.check("刈包又叫「虎咬豬」，1955 年源芳開業，已經 70 多年；尾牙在 12 月 16 日。")["status"],
                         "pass")  # 七十、十二、十六 由中文數字換算 / from Chinese numerals

    def test_unsupported_number_and_quote(self):
        r = self.check("1. 刈包在 2026 年被選為「全球餐桌代表」。\n2. 源自福州。")
        self.assertEqual(r["status"], "fail")
        self.assertEqual(r["unsupported"], ["2026", "「全球餐桌代表」"])  # 清單編號不算 / list numbers ignored
        self.assertIn("2026", r["error"])

    def test_appendix_is_ignored(self):
        self.assertEqual(self.check("源自福州。\n\n---\n【參考資料】\n- 2026 版")["status"], "pass")

    def test_verify_combines(self):
        self.assertEqual(E.verify({}, {"content": "2026 年"}, SOURCE)["status"], "fail")
        self.assertEqual(E.verify({}, {"content": "2026 年"})["status"], "not_applicable")

    def test_gateway_retries_then_passes(self):
        import httpx
        from starlette.testclient import TestClient
        from test_knowledge import TestKnowledge
        from test_runtime_gateway import KEY, local_handler, make_supervisor
        from jiezi.runtime.gateway import Gateway, create_app
        from jiezi.runtime.trajectory import TrajectoryWriter
        t = TestKnowledge("test_gateway")
        t.setUp()
        try:
            t.built()
            sup, _, patch = make_supervisor(t.root, consult="off")
            lh, seen = local_handler([{"role": "assistant", "content": "刈包在 2026 年紅遍全球。"},
                                      {"role": "assistant", "content": "刈包源自福州的荷葉包。"}])
            gw = Gateway(sup.s, sup, TrajectoryWriter(t.root / "traj", log=lambda *_: None),
                         local_http=httpx.AsyncClient(transport=httpx.MockTransport(lh)), log=lambda *_: None)
            with patch, TestClient(create_app(gw)) as c:
                r = c.post("/v1/chat/completions", headers={"Authorization": f"Bearer {KEY}"},
                           json={"model": "jiezi-local", "messages": [{"role": "user", "content": "刈包是什麼？"}]}).json()
            self.assertEqual(r["jiezi"]["tier"], 1)                  # 本機重答一次 / one local retry
            self.assertEqual(r["jiezi"]["verification"], "pass")
            self.assertIn("2026", seen[1]["messages"][-1]["content"])  # 重答時告訴模型哪裡錯 / told what failed
        finally:
            t.tearDown()

    def test_stream_warns(self):
        import httpx
        from starlette.testclient import TestClient
        from test_knowledge import TestKnowledge
        from test_runtime_gateway import KEY, make_supervisor
        from jiezi.runtime.gateway import Gateway, create_app
        from jiezi.runtime.trajectory import TrajectoryWriter

        def handler(request):
            lines = [f'data: {json.dumps({"id": "x", "model": "core", "choices": [{"index": 0, "delta": {"content": c}}]}, ensure_ascii=False)}'
                     for c in ("刈包在 20", "26 年的默", "認做法")]
            lines.append('data: {"id": "x", "model": "core", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}')
            return httpx.Response(200, text="\n\n".join(lines + ["data: [DONE]"]) + "\n\n",
                                  headers={"content-type": "text/event-stream"})
        t = TestKnowledge("test_gateway")
        t.setUp()
        try:
            t.built()
            sup, _, patch = make_supervisor(t.root, consult="off")
            gw = Gateway(sup.s, sup, TrajectoryWriter(t.root / "traj", log=lambda *_: None),
                         local_http=httpx.AsyncClient(transport=httpx.MockTransport(handler)), log=lambda *_: None)
            text, meta = [], None
            with patch, TestClient(create_app(gw)) as c:
                with c.stream("POST", "/v1/chat/completions", headers={"Authorization": f"Bearer {KEY}"},
                              json={"model": "jiezi-local", "stream": True,
                                    "messages": [{"role": "user", "content": "刈包是什麼？"}]}) as r:
                    for line in r.iter_lines():
                        if line.startswith("data: {"):
                            d = json.loads(line[6:])
                            text += [(ch.get("delta") or {}).get("content") or "" for ch in d.get("choices") or []]
                            meta = d.get("jiezi") or meta
            out = "".join(text)
            self.assertIn("刈包在 2026 年的預設做法", out)        # 跨 chunk 的「默認」也換成台灣用語 / across chunks
            self.assertIn("［查核：2026 在附上的資料裡找不到", out)
            self.assertLess(out.index("［查核"), out.index("【參考資料】"))
            self.assertEqual(meta["verification"], "fail")
        finally:
            t.tearDown()


class TestTaiwanPhrasing(unittest.TestCase):
    def test_phrases(self):
        self.assertEqual(to_taiwan("这个视频的默认设置在软件里"), "這個影片的預設設置在軟體里")
        self.assertEqual(to_taiwan("保存參數"), "保存參數")       # 台灣也常用，不換 / common in Taiwan too
        self.assertEqual(to_taiwan("```\n# 默認\n```\n默認"), "```\n# 默認\n```\n預設")  # 程式碼不換 / code kept

    def test_stream_matches_whole(self):
        s = "这个视频的默认设置在软件里。\n```python\n# 视频\n```\n網絡很慢，以太網路由器和互聯網"
        rng = random.Random(7)
        for _ in range(100):
            st, i, out = TaiwanStream(), 0, []
            while i < len(s):
                n = rng.randint(1, 5)
                out.append(st.feed(s[i:i + n]))
                i += n
            self.assertEqual("".join(out) + st.flush(), to_taiwan(s))


if __name__ == "__main__":
    unittest.main()
