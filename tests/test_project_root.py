"""專案根目錄與工作目錄無關的測試（規格：hwprobe / Path Independence）。
Tests that hwprobe does not depend on the current working directory (spec: hwprobe / Path Independence)."""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCRIPT = ROOT / "scripts" / "hwprobe.py"

spec = importlib.util.spec_from_file_location("hwprobe", SCRIPT)
hwprobe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hwprobe)


class TestProjectRoot(unittest.TestCase):
    def test_root_from_script_location(self):
        # 未設定 JIEZI_HOME 時，根目錄是 scripts/ 的上一層 / Without JIEZI_HOME the root is the parent of scripts/
        with mock.patch.dict(os.environ, {"JIEZI_HOME": ""}):
            self.assertEqual(hwprobe.project_root(), ROOT)

    def test_root_override_by_env(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"JIEZI_HOME": d}):
            self.assertEqual(hwprobe.project_root(), Path(d).resolve())

    def test_venv_tool_found_without_path(self):
        # PATH 中沒有、但專案 .venv 中有 / Absent from PATH but present in the project .venv
        with tempfile.TemporaryDirectory() as d:
            tool = Path(d) / ".venv" / "bin" / "cmake"
            tool.parent.mkdir(parents=True)
            tool.write_text("#!/bin/sh\n")
            tool.chmod(0o755)
            with mock.patch.dict(os.environ, {"JIEZI_HOME": d, "PATH": "/nonexistent"}):
                self.assertEqual(hwprobe.venv_tool("cmake"), str(tool))
                self.assertIsNone(hwprobe.venv_tool("ninja"))

    def test_run_from_other_directory(self):
        # 從專案外的目錄執行，預設輸出寫到 <JIEZI_HOME>/facts.json
        # Run from outside the project; the default output goes to <JIEZI_HOME>/facts.json
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as cwd:
            env = dict(os.environ, JIEZI_HOME=home)
            r = subprocess.run(
                [sys.executable, str(SCRIPT), "--quiet"],
                cwd=cwd, env=env, capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            out = Path(home) / "facts.json"
            self.assertTrue(out.exists())
            self.assertFalse((Path(cwd) / "facts.json").exists())
            self.assertIn("budgets", json.loads(out.read_text()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
