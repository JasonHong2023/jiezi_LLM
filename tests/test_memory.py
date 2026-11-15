"""記憶 wiki 測試：主題合併、筆記、更正、手動編輯後重建、忘記、不存的問題、gateway 四種情況、聊天歷史。
Memory wiki tests: topic merging, notes, corrections, rebuild after manual edits, forgetting, unstorable questions,
the gateway paths and chat history."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from jiezi import memory as M  # noqa: E402


class TestMemoryWiki(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.m = M.Memory(Path(self._t.name) / "wiki")

    def tearDown(self):
        self._t.cleanup()

    def test_topics_merge_and_format(self):
        p1 = self.m.save_answer("用兩句話說明什麼是三值量化（ternary quantization）。", "## 定義\n權重只有 -1、0、+1。",
                                "claude", "claude-x")
        p2 = self.m.save_answer("三值量化和二值量化差在哪？", "二值只有 ±1。", "claude", "claude-x")
        self.assertEqual(p1, p2)                                   # 同一主題 / same topic page
        text = (self.m.wiki / p1).read_text(encoding="utf-8")
        self.assertIn("title: 三值量化（ternary quantization）", text)
        self.assertIn("training_use: false", text)
        self.assertIn("**定義**", text)                            # 內文標題改粗體 / heading demoted
        self.assertIn("[[三值量化（ternary quantization）]]", (self.m.wiki / "index.md").read_text(encoding="utf-8"))
        self.assertIn("| remember |", (self.m.wiki / "log.md").read_text(encoding="utf-8"))
        self.m.save_answer("三值量化和二值量化差在哪？", "新答案。", "claude", "claude-x")
        self.assertEqual([e.text for e in self.m.entries if e.question.startswith("三值量化和")], ["新答案。"])

    def test_find_and_similarity(self):
        self.m.save_answer("一句話什麼是 LoRA", "LoRA 是低秩適配。", "claude", "c")
        e, sim = self.m.find_answer("LoRA 是什麼？")
        self.assertEqual((e.title, sim), ("LoRA", 1.0))
        self.assertIsNone(self.m.find_answer("台灣最高的山"))

    def test_notes_corrections_and_manual_edit(self):
        self.m.save_note("我住新竹，回答盡量簡短")
        self.assertIn("我住新竹", M.notes_prompt(self.m))
        page = self.m.save_correction("台北101有多高？", "508 公尺。")
        content, sources, trainable, appendix = M.recall_block("台北101有多高", self.m)
        self.assertIn("正確說法：508 公尺。", content)
        self.assertTrue(trainable)                                  # 只有使用者的更正 / only the user's correction
        # 使用者在 Obsidian 改頁面後，索引自動重建 / the index follows manual edits
        f = self.m.wiki / page
        f.write_text(f.read_text(encoding="utf-8").replace("508 公尺。", "508.2 公尺。"), encoding="utf-8")
        self.assertEqual(self.m.corrections_for("台北101有多高")[0].text, "508.2 公尺。")
        self.assertTrue(self.m.forget("台北101有多高"))
        self.assertEqual(self.m.corrections_for("台北101有多高"), [])

    def test_storable(self):
        self.assertIsNone(M.storable("台積電的創辦人是誰"))
        self.assertEqual(M.storable("今天有什麼新聞"), "web_or_live")
        self.assertEqual(M.storable("你叫什麼名字"), "about_jiezi")
        self.assertEqual(M.storable("那它呢？", earlier_user_turns=1), "depends_on_context")


class TestGatewayMemory(unittest.TestCase):
    def setUp(self):
        import httpx
        from test_runtime_gateway import local_handler, make_supervisor
        from jiezi.runtime.gateway import Gateway
        from jiezi.runtime.trajectory import TrajectoryWriter
        self._t = tempfile.TemporaryDirectory()
        self.tmp = Path(self._t.name)
        self.sup, _, self.patch = make_supervisor(self.tmp)
        self.lh, self.seen = local_handler([{"role": "assistant", "content": "本機回答"}])
        self.gw = Gateway(self.sup.s, self.sup, TrajectoryWriter(self.tmp / "traj", log=lambda *_: None),
                          local_http=httpx.AsyncClient(transport=httpx.MockTransport(self.lh)), log=lambda *_: None)

    def tearDown(self):
        self._t.cleanup()

    def post(self, c, messages, model="jiezi"):
        from test_runtime_gateway import KEY
        return c.post("/v1/chat/completions", headers={"Authorization": f"Bearer {KEY}"},
                      json={"model": model, "messages": messages}).json()

    def test_remember_correct_and_serve(self):
        from starlette.testclient import TestClient
        from jiezi.runtime.gateway import create_app
        self.gw.memory.save_answer("一句話什麼是 LoRA", "LoRA 是低秩適配。", "claude", "claude-x")
        with self.patch, TestClient(create_app(self.gw)) as c:
            r = self.post(c, [{"role": "user", "content": "記住：我住新竹"}])
            self.assertIn("好，我記住了：我住新竹", r["choices"][0]["message"]["content"])
            self.assertEqual(r["jiezi"]["tier"], "memory")
            r = self.post(c, [{"role": "user", "content": "台北101有多高？"}, {"role": "assistant", "content": "500 公尺"},
                              {"role": "user", "content": "不對，是 508 公尺"}])
            self.assertIn("已記下更正", r["choices"][0]["message"]["content"])
            r = self.post(c, [{"role": "user", "content": "LoRA 是什麼？"}])           # 幾乎相同 → 直接用記憶
            self.assertTrue(r["choices"][0]["message"]["content"].startswith("LoRA 是低秩適配。"))
            self.assertEqual(r["jiezi"]["tier"], "memory")
            self.assertEqual(self.sup.status, "unloaded")                          # 不用載入模型 / no model load
            r = self.post(c, [{"role": "user", "content": "台北101有多高"}], model="jiezi-local")
            self.assertTrue(r["choices"][0]["message"]["content"].startswith("根據你"))  # 直接照更正 / correction served
            self.assertIn("508 公尺", r["choices"][0]["message"]["content"])
            r = self.post(c, [{"role": "user", "content": "台北101有多高、有幾層樓、何時完工"}], model="jiezi-local")
            sys_msgs = [m["content"] for m in self.seen[-1]["messages"] if m["role"] == "system"]
            self.assertTrue(any("我住新竹" in s for s in sys_msgs))                 # 記住的事 / notes attached
            self.assertTrue(any("508 公尺" in s for s in sys_msgs))                 # 相關更正當參考 / as reference
            self.assertIn("【記憶】", r["choices"][0]["message"]["content"])
        traj = [json.loads(x) for x in next((self.tmp / "traj").glob("*.jsonl")).read_text().splitlines()]
        self.assertIs(traj[2]["training_use"], False)                              # 記憶裡的 Claude 答案 / Claude text

    def test_consult_answer_is_saved(self):
        from starlette.testclient import TestClient
        from test_runtime_gateway import TestConsult
        from jiezi.runtime.gateway import create_app
        self.gw.consultant = TestConsult("test_safe_flags_and_prompt").consultant(self.tmp, TestConsult.OK)
        with self.patch, TestClient(create_app(self.gw)) as c:
            self.post(c, [{"role": "user", "content": "台灣最高的山是哪一座？"}], model="jiezi-ask-claude")
            self.post(c, [{"role": "user", "content": "今天有什麼新聞？"}], model="jiezi-ask-claude")
        e, sim = self.gw.memory.find_answer("台灣最高的山是哪一座")
        self.assertEqual((e.text, e.provider), ("玉山", "Claude（claude-opus-5-5）"))
        self.assertIsNone(self.gw.memory.find_answer("今天有什麼新聞"))            # 即時類不存 / live not stored


class TestChatHistory(unittest.TestCase):
    def test_resume(self):
        import anyio
        from unittest import mock
        from test_cli import CONN, fake_stream
        from jiezi.cli import chat
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "history.json"
            path.write_text(json.dumps([{"role": "user", "content": "上次的問題"},
                                        {"role": "assistant", "content": "上次的回答"}], ensure_ascii=False))
            app = chat.ChatApp(CONN, history_path=path)
            sent = {}

            def stream(conn, messages, policy, client=None):
                sent["messages"] = messages
                return fake_stream(["好"])(conn, messages, policy)

            async def go():
                with mock.patch.object(chat, "stream_chat", stream):
                    async with app.run_test(size=(60, 20)) as pilot:
                        await pilot.press(*"新問題", "enter")
                        await app.workers.wait_for_complete()
                        await pilot.pause()
            anyio.run(go)
            self.assertEqual(sent["messages"][0]["content"], "上次的問題")           # 接續上下文 / context resumed
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual([m["content"] for m in saved], ["上次的問題", "上次的回答", "新問題", "好"])


if __name__ == "__main__":
    unittest.main()
