"""工具參數值還原與工具請求的提醒（add-strong-tool-calling）。 / Argument restoration and the tool note."""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from jiezi.runtime import toolargs  # noqa: E402


def call(args):
    return {"role": "assistant", "content": "", "tool_calls": [
        {"type": "function", "function": {"name": "f", "arguments": json.dumps(args, ensure_ascii=False)}}]}


class TestRestore(unittest.TestCase):
    def test_traditional_values_go_back_to_the_users_simplified(self):
        """2026-11-17 ACEBench：使用者寫「阅读量」，模型填「閱讀量」。 / The user's Simplified wording comes back."""
        msgs = [{"role": "user", "content": "我要分析的指标包括阅读量、点赞数和分享数，地点是纽约"}]
        m = call({"metrics": ["閱讀量", "點讚數", "分享數"], "where": {"city": "紐約"}, "n": 3})
        changed = toolargs.restore_calls(m, msgs)
        args = json.loads(m["tool_calls"][0]["function"]["arguments"])
        self.assertEqual(args, {"metrics": ["阅读量", "点赞数", "分享数"], "where": {"city": "纽约"}, "n": 3})
        self.assertEqual(len(changed), 4)

    def test_untouched_when_already_verbatim_or_absent(self):
        msgs = [{"role": "user", "content": "幫我查台北的天氣"}, {"role": "assistant", "content": "好"}]
        m = call({"city": "台北", "unit": "celsius", "x": "查"})
        self.assertEqual(toolargs.restore_calls(m, msgs), [])
        self.assertEqual(json.loads(m["tool_calls"][0]["function"]["arguments"]),
                         {"city": "台北", "unit": "celsius", "x": "查"})

    def test_assistant_text_is_not_a_source(self):
        """只從使用者與工具結果找原文。 / Only user and tool messages count as sources."""
        msgs = [{"role": "assistant", "content": "市场"}, {"role": "user", "content": "要市場報告"}]
        m = call({"t": "市場"})
        self.assertEqual(toolargs.restore_calls(m, msgs), [])

    def test_bad_arguments_and_no_calls(self):
        self.assertEqual(toolargs.restore_calls({"content": "hi"}, [{"role": "user", "content": "x"}]), [])
        m = {"tool_calls": [{"function": {"name": "f", "arguments": "{bad"}}]}
        self.assertEqual(toolargs.restore_calls(m, [{"role": "user", "content": "阅读"}]), [])


class TestToolNote(unittest.TestCase):
    def test_note_only_with_tools_and_switchable(self):
        from jiezi.runtime.gateway import TOOL_NOTE
        from jiezi.runtime.settings import load_settings
        from pathlib import Path
        import tempfile
        from test_runtime_gateway import make_supervisor
        from jiezi.runtime.gateway import Gateway
        from jiezi.runtime.trajectory import TrajectoryWriter
        with tempfile.TemporaryDirectory() as d:
            sup, _, patch = make_supervisor(Path(d))
            gw = Gateway(sup.s, sup, TrajectoryWriter(Path(d) / "t", log=lambda *_: None), log=lambda *_: None)
            body = {"messages": [{"role": "user", "content": "q"}], "tools": [{"type": "function",
                                                                                "function": {"name": "f"}}]}
            self.assertIn(TOOL_NOTE, json.dumps(gw._local_body(body), ensure_ascii=False).replace("\\n", "\n"))
            self.assertNotIn("呼叫工具的規則", json.dumps(gw._local_body({"messages": body["messages"]}),
                                                     ensure_ascii=False))
            gw.s.tool_note = False
            self.assertNotIn("呼叫工具的規則", json.dumps(gw._local_body(body), ensure_ascii=False))
        self.assertTrue(load_settings(env={"JIEZI_GATEWAY_KEY": "k" * 20}).tool_note)
        self.assertFalse(load_settings(env={"JIEZI_GATEWAY_KEY": "k" * 20, "JIEZI_TOOL_NOTE": "off"}).tool_note)


if __name__ == "__main__":
    unittest.main()
