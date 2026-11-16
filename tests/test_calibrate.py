"""calibrator 測試：解析 llama-bench、挑最快、失敗記錄、supervisor 只對同一檔案採用。 / Calibrator tests."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jiezi.runtime import calibrate as C  # noqa: E402

OUT = {0: [{"n_prompt": 256, "n_gen": 0, "avg_ts": 50.0}, {"n_prompt": 0, "n_gen": 64, "avg_ts": 9.0}],
       8: [{"n_prompt": 256, "n_gen": 0, "avg_ts": 120.0}, {"n_prompt": 0, "n_gen": 64, "avg_ts": 14.5}]}


class TestCalibrate(unittest.TestCase):
    def test_run_parse_and_best(self):
        def run(cmd, **kw):
            ngl = int(cmd[cmd.index("-ngl") + 1])

            class P:
                returncode = 0 if ngl in OUT else 1
                stdout = json.dumps(OUT.get(ngl, []))
                stderr = "" if ngl in OUT else "CUDA out of memory"
            return P()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            r = C.run(root, "m", root / "m.gguf", "abc", {"budgets": {}}, steps=(0, 8, 99), run_cmd=run,
                      log=lambda *_: None)
            self.assertEqual(r["results"]["8"], {"pp": 120.0, "tg": 14.5})
            self.assertIn("out of memory", r["results"]["99"]["error"])
            self.assertEqual(r["best_ngl"], 8)
            self.assertEqual(C.measured_ngl(root, "m", "abc"), 8)
            self.assertIsNone(C.measured_ngl(root, "m", "other-sha"))           # 不同檔案不用 / other file


if __name__ == "__main__":
    unittest.main()
