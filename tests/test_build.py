"""建置決策與指令測試（規格 build：Detection-Driven Backend Selection、Portable Build Flags、
Resource-Bounded Build、Build Record）。以假 facts 與假 cmake 測試，不實際編譯。
Tests for build decisions and commands using fake facts and a fake cmake; nothing is compiled."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from jiezi_bootstrap import build  # noqa: E402
from jiezi_bootstrap.common import StepError  # noqa: E402


def facts(cuda_ok=True, hint="2-13", threads=12):
    return {
        "fingerprint": {"id": "0123456789abcdef"},
        "backends": {
            "buildable": {
                "cpu": {"ok": True, "reason": None},
                "cuda": {"ok": cuda_ok, "reason": None if cuda_ok else "missing: nvidia driver"},
                "vulkan": {"ok": False, "reason": "no /dev/dri render node"},
                "openvino": {"ok": False, "reason": "libopenvino not in ldconfig"},
            },
            "toolchain": {"nvcc": {"path": "/opt/cuda/bin/nvcc", "version": "13.3"} if cuda_ok else
                          {"path": None, "version": None}},
        },
        "budgets": {"cpu": {"usable_threads": threads, "affinity_hint": hint,
                            "affinity_reason": None if hint else "core→thread topology unavailable"}},
    }


def fake_root(d: Path, cmake_exit: int = 0) -> Path:
    """建立帶假 cmake / ninja 的專案根目錄；假 cmake 在 --build 時產生 bin/llama-cli。
    A project root with fake cmake / ninja; the fake cmake creates bin/llama-cli on --build."""
    bin_dir = d / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "ninja").write_text("#!/bin/sh\nexit 0\n")
    (bin_dir / "cmake").write_text(
        "#!/bin/sh\n"
        f"[ {cmake_exit} -ne 0 ] && exit {cmake_exit}\n"
        'if [ "$1" = "--build" ]; then mkdir -p "$2/bin" && : > "$2/bin/llama-cli"; fi\n'
        "exit 0\n"
    )
    for f in bin_dir.iterdir():
        f.chmod(0o755)
    return d


class TestSelect(unittest.TestCase):
    def names(self, f):
        return [d.backend for d in build.select_backends(f) if d.build]

    def test_machine_with_cuda(self):
        self.assertEqual(self.names(facts(cuda_ok=True)), ["cpu", "cuda"])

    def test_machine_without_gpu(self):
        decisions = build.select_backends(facts(cuda_ok=False))
        self.assertEqual([d.backend for d in decisions if d.build], ["cpu"])
        skipped = {d.backend: d.reason for d in decisions if not d.build}
        self.assertEqual(set(skipped), {"cuda", "vulkan", "openvino"})
        self.assertTrue(all(skipped.values()))  # 每個略過都有原因 / every skip has a reason

    def test_empty_facts_still_builds_cpu(self):
        self.assertEqual(self.names({}), ["cpu"])


class TestPlan(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = fake_root(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_flags_are_portable_and_rpc_off(self):
        p = build.plan_build("cuda", facts(), Path("/src"), self.root)
        self.assertIn("-DGGML_RPC=OFF", p.configure)
        self.assertIn("-DGGML_NATIVE=ON", p.configure)
        self.assertIn("-DCMAKE_CUDA_ARCHITECTURES=native", p.configure)
        self.assertIn("-DCMAKE_CUDA_COMPILER=/opt/cuda/bin/nvcc", p.configure)
        self.assertFalse(any(a.startswith("-DCMAKE_CUDA_ARCHITECTURES=") and not a.endswith("=native")
                             for a in p.configure))
        self.assertFalse(any("GGML_RPC=ON" in a for a in p.configure))

    def test_budget_limits_jobs_and_pins(self):
        with mock.patch.object(build.shutil, "which", side_effect=lambda n: f"/usr/bin/{n}"):
            p = build.plan_build("cpu", facts(threads=12, hint="2-13"), Path("/src"), self.root)
        self.assertEqual(p.compile[-2:], ["-j", "12"])
        self.assertEqual(p.compile[:3], ["taskset", "-c", "2-13"])
        self.assertIn("nice", p.compile)

    def test_topology_unavailable(self):
        p = build.plan_build("cpu", facts(threads=6, hint=None), Path("/src"), self.root)
        self.assertNotIn("taskset", p.compile)
        self.assertEqual(p.compile[-2:], ["-j", "6"])
        self.assertTrue(any("pinning skipped" in n for n in p.notes))

    def test_cuda_without_nvcc_path_is_an_error(self):
        f = facts()
        f["backends"]["toolchain"]["nvcc"]["path"] = None
        with self.assertRaises(StepError):
            build.plan_build("cuda", f, Path("/src"), self.root)


class TestRunAndRecord(unittest.TestCase):
    def test_record_and_skip_on_rerun(self):
        with tempfile.TemporaryDirectory() as d:
            root = fake_root(Path(d))
            f = facts(cuda_ok=False, hint=None)
            summary = build.build_all(f, Path("/src"), "a" * 40, root, log=lambda *_: None)
            self.assertEqual([s["result"] for s in summary], ["success", "skipped", "skipped", "skipped"])
            rec = json.loads(build.record_path(root, "cpu").read_text())
            for key in ("llama_cpp_commit", "configure", "compiler", "duration_s", "result", "fingerprint_id"):
                self.assertIn(key, rec)
            self.assertEqual(rec["fingerprint_id"], "0123456789abcdef")
            again = build.build_all(f, Path("/src"), "a" * 40, root, log=lambda *_: None)
            self.assertEqual(again[0]["result"], "up-to-date")
            # commit 改變 → 重建 / a different commit forces a rebuild
            third = build.build_all(f, Path("/src"), "b" * 40, root, log=lambda *_: None)
            self.assertEqual(third[0]["result"], "success")

    def test_failure_is_recorded_and_raised(self):
        with tempfile.TemporaryDirectory() as d:
            root = fake_root(Path(d), cmake_exit=1)
            with self.assertRaisesRegex(StepError, "build-cpu failed at configure"):
                build.build_all(facts(cuda_ok=False), Path("/src"), "a" * 40, root, log=lambda *_: None)
            rec = json.loads(build.record_path(root, "cpu").read_text())
            self.assertEqual(rec["result"], "failure")


if __name__ == "__main__":
    unittest.main()
