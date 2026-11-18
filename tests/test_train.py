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
        # 2026-11-17 實測：4B 4-bit、max_len 1024 峰值 5,125 MiB；估計要在 ±15% 內，而且有算詞嵌入
        e = C.estimate_vram_mib(4, True, max_len=1024)
        self.assertGreater(e["embedding_mib"], 1100)
        self.assertLess(abs(e["total_mib"] - 5125) / 5125, 0.15)
        self.assertFalse(C.fits(9, 5117)["4bit"])

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


class TestReplay(unittest.TestCase):
    """add-sft-round2：MBPP 複習資料與混合比例。 / MBPP replay and the mix ratio."""

    def test_test_split_never_used_and_hash_pinned(self):
        from jiezi.train import replay as R
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            rows = [{"task_id": i, "text": f"t{i}", "code": "", "test_setup_code": "", "test_list": ["assert True"],
                     "challenge_test_list": []} for i in (1, 11, 300, 510, 511, 974)]
            blob = "".join(json.dumps(r) + "\n" for r in rows).encode()

            class Resp:
                def __init__(self, b):
                    self.b = b

                def read(self):
                    return self.b

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False
            with self.assertRaises(JieziError):                              # 雜湊不符就拒絕 / pinned hash
                R.fetch_mbpp(root, opener=lambda url, timeout: Resp(blob))
            p = R.mbpp_path(root)
            p.parent.mkdir(parents=True)
            p.write_bytes(blob)
            self.assertEqual([x["task_id"] for x in R.problems(p)], [1, 511, 974])

    def test_program_runs_all_tests(self):
        from jiezi.train import replay as R
        p = {"test_setup_code": "import math", "test_list": ["assert f(2) == 4"], "challenge_test_list": ["assert f(3) == 9"]}
        prog = R.program(p, "def f(x):\n    return x * x")
        self.assertIn("import math", prog)
        self.assertIn("assert f(3) == 9", prog)
        self.assertIn("問題：", R.prompt_of({"text": "x", "test_list": ["assert 1"]}))

    def test_build_keeps_only_passing_answers(self):
        from jiezi.train import replay as R
        probs = [{"task_id": 600 + i, "text": "t", "test_list": ["assert 1"]} for i in range(3)]

        class SB:
            def run_python(self, files, argv, limits):
                ok = "good" in files["main.py"]
                return type("Res", (), {"returncode": 0 if ok else 1, "limit": None})()
        answers = iter(["```python\ngood = 1\n```", "```python\nbad = 1\n```"])

        def complete(msgs, n):
            a = next(answers, None)
            if a is None:
                raise RuntimeError("engine down")
            return a
        with tempfile.TemporaryDirectory() as d, mock.patch.object(R, "fetch_mbpp", return_value=Path(d)), \
                mock.patch.object(R, "problems", return_value=probs):
            out, stats = R.build(Path(d), complete, SB(), log=lambda m: None)
            rows = [json.loads(x) for x in out.read_text().splitlines()]
        self.assertEqual((stats["passed"], stats["failed"], stats["errors"]), (1, 1, 1))
        self.assertEqual((rows[0]["source"], rows[0]["training_use"], rows[0]["task_id"]), ("mbpp-replay", True, 600))

    def test_mix_ratio(self):
        import random
        from jiezi.training_data import mix_replay
        kept = [{"id": f"n{i}"} for i in range(30)]
        rep = [{"id": f"r{i}"} for i in range(4)]
        out = mix_replay(kept, rep, 0.5, random.Random(1))
        self.assertEqual(len(out), 60)
        self.assertEqual(sum(x["id"].startswith("r") for x in out), 30)     # 不夠就重複取樣 / repeated when short
        self.assertEqual(mix_replay(kept, [], 0.5, random.Random(1)), kept)
        self.assertEqual(len(mix_replay(kept, rep, 0.0, random.Random(1))), 30)

    def test_round2_config(self):
        cfg = C.TrainConfig(**json.loads((ROOT / "src/jiezi/train/configs/qwen3.5-4b-r2.json").read_text()))
        self.assertEqual((cfg.learning_rate, cfg.max_len, cfg.extra["vram_ceiling_mib"]), (5e-05, 768, 5500))
        self.assertNotEqual(cfg.run_name, "qwen3.5-4b-r1")                    # 每輪新的 LoRA / fresh LoRA (R20.2)
