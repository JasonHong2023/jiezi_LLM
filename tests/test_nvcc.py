"""nvcc 偵測測試（規格：hwprobe / CUDA Toolkit Discovery）。
Tests for nvcc discovery (spec: hwprobe / CUDA Toolkit Discovery)."""

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("hwprobe", ROOT / "scripts" / "hwprobe.py")
hwprobe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hwprobe)


def fake_nvcc(path: Path, release: str) -> None:
    # 建立假的 nvcc，輸出指定版本 / Create a fake nvcc printing the given release
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\necho 'Cuda compilation tools, release {release}, V{release}.0'\n")
    path.chmod(0o755)


class TestFindNvcc(unittest.TestCase):
    def test_not_on_path_but_standard_location(self):
        with tempfile.TemporaryDirectory() as d:
            local = Path(d)
            fake_nvcc(local / "cuda-12.4" / "bin" / "nvcc", "12.4")
            fake_nvcc(local / "cuda-13.3" / "bin" / "nvcc", "13.3")
            info = hwprobe.find_nvcc(env={"PATH": "/nonexistent"}, local=local)
            self.assertEqual(info["found_via"], "standard_location")
            self.assertTrue(info["path"].endswith("cuda-13.3/bin/nvcc"))  # 取最高版本 / highest version wins
            self.assertEqual(info["version"], "13.3")

    def test_cuda_home_preferred_over_standard(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as h:
            fake_nvcc(Path(d) / "cuda-13.3" / "bin" / "nvcc", "13.3")
            fake_nvcc(Path(h) / "bin" / "nvcc", "12.8")
            info = hwprobe.find_nvcc(env={"PATH": "/nonexistent", "CUDA_HOME": h}, local=Path(d))
            self.assertEqual(info["found_via"], "cuda_home")

    def test_absent(self):
        with tempfile.TemporaryDirectory() as d:
            info = hwprobe.find_nvcc(env={"PATH": "/nonexistent"}, local=Path(d))
            self.assertIsNone(info["path"])
            self.assertTrue(any("cuda-*" in c for c in info["checked"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
