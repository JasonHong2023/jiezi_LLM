"""訓練工具測試（不需要 PyTorch）：估算、回歸關卡、資料把關、答案遮罩、GGUF 流程。 / Training tool tests."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jiezi.errors import JieziError  # noqa: E402
from jiezi.train import config as C, export as X, gate as G, sft as S  # noqa: E402


class TestGate(unittest.TestCase):
    def snap(self, tool=34, code=22, qa=22, length=70, latency=6.0, esc=0.0):
        return G.Snapshot({"tool": tool, "code": code, "qa": qa}, length, latency, esc)

    def test_pass(self):
        r = G.check(self.snap(), self.snap(tool=40, code=21.5), ["tool"])
        self.assertTrue(r["pass"], r["reasons"])
        self.assertEqual(r["deltas"]["tool"], 6)

    def test_failures(self):
        b = self.snap()
        self.assertFalse(G.check(b, self.snap(tool=34), ["tool"])["pass"])                 # 沒提升 / no gain
        self.assertFalse(G.check(b, self.snap(tool=40, code=20), ["tool"])["pass"])        # 退步 2 分 / dropped
        self.assertFalse(G.check(b, self.snap(tool=40, length=90), ["tool"])["pass"])      # 變長 / longer
        self.assertFalse(G.check(b, self.snap(tool=40, latency=7), ["tool"])["pass"])      # 變慢 / slower
        self.assertFalse(G.check(b, self.snap(tool=40, esc=0.1), ["tool"])["pass"])        # R20.6 轉交增加


class TestTraining(unittest.TestCase):
    def test_vram_estimate(self):
        f = C.fits(0.8, 4900)
        self.assertTrue(f["bf16"])
        self.assertFalse(C.fits(4, 4900)["bf16"])
        self.assertTrue(C.fits(4, 4900)["4bit"])

    def test_dataset_must_be_trainable(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.jsonl"
            p.write_text(json.dumps({"messages": [], "training_use": None, "sha256": "a"}) + "\n")
            with self.assertRaisesRegex(JieziError, "not marked trainable"):
                S.load_examples(p)

    def test_missing_stack_message(self):
        with mock.patch("builtins.__import__", side_effect=ImportError):
            with self.assertRaisesRegex(JieziError, "install after the user approves"):
                S.require_stack()

    def test_answer_only_labels(self):
        class Tok:
            def apply_chat_template(self, msgs, tokenize, add_generation_prompt, enable_thinking):
                ids = []  # 每則訊息後接分隔符 0，生成提示也是 0（像真的模板）/ separator after each message
                for m in msgs:
                    ids += [ord(c) for c in m["content"]] + [0]
                return ids
        ex = {"messages": [{"role": "user", "content": "ab"}, {"role": "assistant", "content": "cd"}]}
        e = S.encode(ex, Tok(), 100)
        self.assertEqual(e["labels"][:3], [S.IGNORE] * 3)                                   # 提問不算 / prompt masked
        self.assertIsNone(S.encode(ex, Tok(), 3))                                           # 太長略過 / too long

    def test_gguf_pipeline_commands(self):
        calls = []

        def run(cmd, **kw):
            calls.append(cmd)
            if "llama-quantize" in cmd[0]:
                Path(cmd[2]).write_bytes(b"gguf")

            class P:
                returncode, stderr = 0, ""
            return P()
        with tempfile.TemporaryDirectory() as d:
            root, run_dir = Path(d), Path(d) / "var" / "train" / "r1"
            (run_dir / "merged").mkdir(parents=True)
            (root / "build-cpu" / "bin").mkdir(parents=True)
            (root / "build-cpu" / "bin" / "llama-quantize").write_text("")
            res = X.to_gguf(root, run_dir, "Q8_0", log=lambda *_: None, run=run)
        self.assertIn("convert_hf_to_gguf.py", calls[0][1])
        self.assertEqual(calls[1][-1], "Q8_0")
        self.assertTrue(res["path"].endswith("r1-Q8_0.gguf"))


if __name__ == "__main__":
    unittest.main()
