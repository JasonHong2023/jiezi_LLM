"""視覺功能測試：核心視覺模組偵測、沒視覺時的處理、圖片原樣送入本機、上下文估算、聊天介面。 / Vision tests."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

IMG = {"type": "image_url", "image_url": {"url": "data:image/png;base64," + "A" * 200000}}


def image_msg(text="這張圖是什麼？"):
    return {"role": "user", "content": [{"type": "text", "text": text}, IMG]}


class TestVision(unittest.TestCase):
    def test_resolve_core_detects_projector(self):
        from jiezi.runtime.supervisor import resolve_core
        from test_runtime_gateway import settings
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            (tmp / "models").mkdir()
            (tmp / "core.gguf").write_bytes(b"x" * 10)
            (tmp / "models" / "manifest.toml").write_text(
                '[[model]]\nname = "core"\nfile = "core.gguf"\nsize = 10\nsha256 = "0"\nmmproj = "mm"\n'
                '[[model]]\nname = "mm"\nfile = "mm.gguf"\nsize = 3\nsha256 = "0"\n')
            s = settings(tmp, core_model="core")
            self.assertFalse(resolve_core(s)["vision"])                        # 檔案還沒下載 / not downloaded
            (tmp / "mm.gguf").write_bytes(b"abc")
            c = resolve_core(s)
            self.assertTrue(c["vision"])
            self.assertEqual(c["mmproj_path"], tmp / "mm.gguf")

    def gateway(self, tmp, vision):
        import httpx
        from test_runtime_gateway import local_handler, make_supervisor
        from jiezi.runtime.gateway import Gateway
        from jiezi.runtime.trajectory import TrajectoryWriter
        sup, _, patch = make_supervisor(tmp)
        lh, seen = local_handler([{"role": "assistant", "content": "一隻貓"}])
        gw = Gateway(sup.s, sup, TrajectoryWriter(tmp / "traj", log=lambda *_: None),
                     local_http=httpx.AsyncClient(transport=httpx.MockTransport(lh)), log=lambda *_: None)
        gw.core_vision = vision
        return gw, patch, seen

    def test_routing(self):
        from starlette.testclient import TestClient
        from test_runtime_gateway import KEY
        from jiezi.runtime.gateway import create_app
        with tempfile.TemporaryDirectory() as d:
            gw, patch, seen = self.gateway(Path(d), vision=False)
            with patch, TestClient(create_app(gw)) as c:
                r = c.post("/v1/chat/completions", headers={"Authorization": f"Bearer {KEY}"},
                           json={"model": "jiezi-local", "messages": [image_msg()]})
            self.assertEqual(r.status_code, 400)                                  # 不讓文字模型亂猜 / no guessing
            self.assertEqual(r.json()["error"]["code"], "vision_unavailable")
            self.assertEqual(seen, [])
        with tempfile.TemporaryDirectory() as d:
            gw, patch, seen = self.gateway(Path(d), vision=True)
            with patch, TestClient(create_app(gw)) as c:
                r = c.post("/v1/chat/completions", headers={"Authorization": f"Bearer {KEY}"},
                           json={"model": "jiezi-local", "messages": [image_msg("這是 2^10 的題目嗎")]}).json()
            sent = seen[0]["messages"][-1]["content"]
            self.assertEqual(sent[1], IMG)                                        # 圖片原樣送入 / image passed through
            self.assertTrue(any("1024" in m["content"] for m in seen[0]["messages"] if m["role"] == "system"))  # 文字部分查資料
            self.assertEqual(r["choices"][0]["message"]["content"].split("\n")[0], "一隻貓")

    def test_context_counts_images_not_base64(self):
        from jiezi.runtime import context as C
        self.assertLess(C.total([image_msg()]), 500)
        out, info = C.fit([image_msg()])
        self.assertEqual(info["dropped_turns"], 0)

    def test_chat_helpers(self):
        from jiezi.cli.chat import for_context, text_of
        hist = [image_msg("第一張"), {"role": "assistant", "content": "答"}, image_msg("第二張")]
        ctx = for_context(hist)
        self.assertEqual(ctx[0]["content"], "第一張 [圖片 image]")                  # 舊圖拿掉 / old image dropped
        self.assertEqual(ctx[-1]["content"][1], IMG)                                # 最新的保留 / latest kept
        self.assertEqual(json.dumps(text_of(hist[0]["content"]), ensure_ascii=False), '"第一張 [圖片 image]"')


if __name__ == "__main__":
    unittest.main()
