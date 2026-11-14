"""sudo 等待視窗測試（design D8）。以假 sudo 執行包裝腳本，不需要真的權限。
Tests for the sudo waiting window (design D8), running the wrapper against a fake sudo."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from jiezi_bootstrap import sudo_window as sw  # noqa: E402


def which_from(*present):
    return lambda n: f"/fake/{n}" if n in present else None


class TestPlatform(unittest.TestCase):
    def test_wsl_by_env(self):
        with tempfile.TemporaryDirectory() as d:
            pv = Path(d) / "version"
            pv.write_text("Linux version 6.0 (gcc)")
            if sys.platform.startswith("linux"):
                self.assertEqual(sw.detect_platform({"WSL_DISTRO_NAME": "X"}, pv), "wsl2")
                self.assertEqual(sw.detect_platform({}, pv), "ubuntu")
                pv.write_text("Linux version 6.0-microsoft-standard-WSL2")
                self.assertEqual(sw.detect_platform({}, pv), "wsl2")


class TestLauncher(unittest.TestCase):
    def test_wsl_prefers_wt(self):
        f = sw.choose_launcher("wsl2", {"WSL_DISTRO_NAME": "D"}, which_from("wt.exe", "cmd.exe"))
        cmd = f("/w.sh")
        self.assertEqual(cmd[0], "wt.exe")
        self.assertEqual(cmd[-6:], ["wsl.exe", "-d", "D", "--", "bash", "/w.sh"])

    def test_wsl_falls_back_to_cmd(self):
        f = sw.choose_launcher("wsl2", {"WSL_DISTRO_NAME": "D"}, which_from("cmd.exe"))
        cmd = f("/w.sh")
        self.assertEqual(cmd[:3], ["cmd.exe", "/c", "start"])
        self.assertNotIn(" ", cmd[3])

    def test_ubuntu_gui(self):
        f = sw.choose_launcher("ubuntu", {"DISPLAY": ":0"}, which_from("gnome-terminal"))
        self.assertEqual(f("/w.sh")[0], "gnome-terminal")
        f = sw.choose_launcher("ubuntu", {"WAYLAND_DISPLAY": "w"}, which_from("x-terminal-emulator", "gnome-terminal"))
        self.assertEqual(f("/w.sh")[0], "x-terminal-emulator")

    def test_headless_uses_current_terminal(self):
        self.assertIsNone(sw.choose_launcher("ubuntu", {}, which_from("gnome-terminal")))
        self.assertIsNone(sw.choose_launcher("wsl2", {}, which_from("wt.exe")))  # 無 distro 名稱 / no distro name


class TestWrapper(unittest.TestCase):
    def run_wrapper(self, step_body, fail_first_n, stdin):
        d = Path(self._tmp.name)
        bin_dir = d / "bin"
        bin_dir.mkdir()
        counter = d / "count"
        counter.write_text("0")
        # 假 sudo：前 N 次 -v 失敗 / fake sudo: the first N `-v` calls fail
        (bin_dir / "sudo").write_text(
            "#!/bin/sh\n"
            f'if [ "$1" = "-v" ]; then n=$(cat {counter}); echo $((n+1)) > {counter};'
            f' [ "$n" -lt {fail_first_n} ] && exit 1; fi\nexit 0\n')
        (bin_dir / "sudo").chmod(0o755)
        step = d / "step.sh"
        step.write_text(step_body)
        wrapper, status = sw.write_wrapper("t", step, "will do things", "T", d / "var")
        env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
        p = subprocess.run(["bash", str(wrapper)], input=stdin, capture_output=True, text=True, env=env)
        return p, status, int(counter.read_text())

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmp.cleanup()

    def test_retries_until_sudo_succeeds_then_records_exit_code(self):
        p, status, calls = self.run_wrapper("exit 0\n", fail_first_n=2, stdin="\n\n\n\n")
        self.assertEqual(status.read_text().strip(), "0")
        self.assertEqual(calls, 3)
        self.assertIn("will do things", p.stdout)

    def test_step_failure_code_is_recorded(self):
        _, status, _ = self.run_wrapper("exit 7\n", fail_first_n=0, stdin="\n\n")
        self.assertEqual(status.read_text().strip(), "7")
        self.assertEqual(sw.wait_for_status(status, sleep=lambda _: None), 7)

    def test_closed_input_aborts_cleanly(self):
        _, status, _ = self.run_wrapper("exit 0\n", fail_first_n=99, stdin="\n")
        self.assertEqual(status.read_text().strip(), "130")


class TestConsent(unittest.TestCase):
    def test_yes_and_no(self):
        quiet = lambda *_: None  # noqa: E731
        self.assertTrue(sw.ask_consent("x", inp=lambda _: "y", out=quiet))
        self.assertFalse(sw.ask_consent("x", inp=lambda _: "", out=quiet))

    def test_eof_is_no(self):
        def eof(_):
            raise EOFError
        self.assertFalse(sw.ask_consent("x", inp=eof, out=lambda *_: None))


if __name__ == "__main__":
    unittest.main()
