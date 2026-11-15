"""程式驗證器測試（實際使用 bubblewrap 沙盒；沒有建置時略過）：擷取程式碼、base / plus 分開、逾時、浮點容差、
MBPP 特殊判定與輸入轉換。
Code verifier tests (real bubblewrap; skipped when not built): extraction, base / plus split, timeouts,
float tolerance, MBPP special oracles and input conversion."""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jiezi.verify import code as cv  # noqa: E402
from jiezi.verify.sandbox import Sandbox  # noqa: E402

BWRAP = ROOT / "var" / "tools" / "bubblewrap" / "bin" / "bwrap"

HE = {"data": {
    "task_id": "HumanEval/900", "entry_point": "add_half",
    "prompt": "from typing import List\n\n\ndef add_half(xs: List[float]) -> List[float]:\n    \"\"\"加 0.5\"\"\"\n",
    "canonical_solution": "    return [x + 0.5 for x in xs]\n",
    "base_input": [[[1.0, 2.0]]], "plus_input": [[[0.1, 0.2]], [[-3.0]]], "atol": 0}}

MBPP = {"data": {
    "task_id": "Mbpp/2", "entry_point": "similar_elements",
    "prompt": "\"\"\"\nWrite a function to find the shared elements.\n\"\"\"\n",
    "canonical_solution": "\ndef similar_elements(a, b):\n    assert isinstance(a, tuple)\n"
                          "    return tuple(set(a) & set(b))\n",
    "base_input": [[[3, 4, 5, 6], [5, 7, 4, 10]]], "plus_input": [[[1, 2, 3], [3, 2]]], "atol": 0}}


def fenced(code):
    return f"這是答案：\n```python\n{code}```\n"


@unittest.skipUnless(BWRAP.is_file(), "bubblewrap not built (scripts/bootstrap)")
class TestCodeVerifier(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.v = cv.CodeVerifier(Sandbox(ROOT), Path(cls._tmp.name))

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_correct_with_float_tolerance_and_prompt_imports(self):
        r = self.v.verify(HE, fenced("def add_half(xs: List[float]) -> List[float]:\n"
                                     "    return [x + 0.5000000001 for x in xs]\n"))
        self.assertEqual((r["status"], r["score"]), ("correct", 1), r)
        self.assertIn("prepended prompt imports", r["details"]["notes"])

    def test_base_pass_plus_fail(self):
        code = "def add_half(xs):\n    return [x + 0.5 for x in xs] if xs and xs[0] >= 1 else []\n"
        r = self.v.verify(HE, fenced(code))
        self.assertEqual((r["details"]["base_pass"], r["details"]["plus_pass"], r["score"]), (True, False, 0))

    def test_timeout_and_crash(self):
        r = self.v.verify(HE, fenced("def add_half(xs):\n    while True: pass\n"))
        self.assertEqual((r["score"], r["details"]["base"]["status"]), (0, "timeout"))
        r = self.v.verify(HE, fenced("def add_half(xs):\n    raise ValueError\n"))
        self.assertEqual((r["status"], r["details"]["base_pass"]), ("wrong", False))

    def test_completion_without_def(self):
        r = self.v.verify(HE, "    return [x + 0.5 for x in xs]\n")
        self.assertEqual(r["score"], 1, r)

    def test_mbpp_tuple_inputs_and_set_oracle(self):
        # 輸入轉為 tuple（mbpp_deserialize_inputs）、輸出以集合比較 / tuple inputs and set comparison
        r = self.v.verify(MBPP, fenced("def similar_elements(a, b):\n    assert isinstance(a, tuple)\n"
                                       "    return tuple(sorted(set(b) & set(a), reverse=True))\n"))
        self.assertEqual(r["score"], 1, r)

    def test_expected_outputs_cached(self):
        self.v.expected(HE)
        self.assertEqual(len(list(Path(self._tmp.name).glob("*.pkl"))) >= 1, True)


class TestExtraction(unittest.TestCase):
    def test_prefers_block_with_entry_point(self):
        text = "```python\nimport os\n```\n說明\n```python\ndef f(x):\n    return x\n```"
        self.assertEqual(cv.extract_code(text, "f")[0], "def f(x):\n    return x\n")

    def test_unavailable_sandbox_is_pending(self):
        with tempfile.TemporaryDirectory() as d:
            v = cv.CodeVerifier(Sandbox(Path(d)), Path(d) / "c")
            r = v.verify(HE, fenced("def add_half(xs):\n    return xs\n"))
            self.assertEqual((r["status"], r["score"]), ("pending_verifier", None))


if __name__ == "__main__":
    unittest.main()
