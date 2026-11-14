"""非 Linux 平台優雅降級測試（規格：hwprobe / Graceful Degradation Off Linux）。
Tests for graceful degradation off Linux (spec: hwprobe / Graceful Degradation Off Linux)."""

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("hwprobe", ROOT / "scripts" / "hwprobe.py")
hwprobe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hwprobe)

TOP_LEVEL = [
    "schema_version", "generated_at", "fingerprint", "host", "cpu", "memory",
    "gpus", "npus", "backends", "budgets", "verdict", "probe_failures",
]


def run_probe_without_linux_interfaces() -> tuple[int, dict]:
    # 模擬沒有 /proc 檔案、也沒有任何外部指令的平台（例如 macOS）
    # Simulate a platform with no /proc files and no external commands (e.g. macOS)
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "facts.json"
        argv = ["hwprobe.py", "--quiet", "--out", str(out)]
        with mock.patch.object(hwprobe, "read_text", return_value=None), \
             mock.patch.object(hwprobe, "run", return_value=(False, "", "not found")), \
             mock.patch.object(sys, "argv", argv), \
             redirect_stdout(io.StringIO()):
            code = hwprobe.main()
        return code, json.loads(out.read_text())


class TestGracefulDegradation(unittest.TestCase):
    def setUp(self):
        self.code, self.facts = run_probe_without_linux_interfaces()

    def test_exit_code_zero(self):
        self.assertEqual(self.code, 0)

    def test_complete_structure(self):
        for key in TOP_LEVEL:
            self.assertIn(key, self.facts)

    def test_cpu_absent_with_reason(self):
        self.assertFalse(self.facts["cpu"]["present"])
        self.assertTrue(self.facts["cpu"]["reason"])

    def test_memory_absent_with_reason(self):
        self.assertFalse(self.facts["memory"]["present"])
        self.assertTrue(self.facts["memory"]["reason"])

    def test_cpu_only_verdict_still_produced(self):
        # 沒有任何加速器時仍給出可用的 CPU 判定 / A usable CPU verdict even with no accelerators
        self.assertEqual(self.facts["verdict"]["primary_device"], "cpu")


if __name__ == "__main__":
    unittest.main(verbosity=2)
