"""CUDA toolkit 安裝決策測試（不連網、不需 sudo）。
Tests for CUDA toolkit install decisions (no network, no sudo)."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from jiezi_bootstrap import cuda_setup as cs  # noqa: E402
from jiezi_bootstrap.common import StepError  # noqa: E402

INDEX = """<a href='cuda-keyring_1.0-1_all.deb'>x</a><a href='cuda-keyring_1.1-1_all.deb'>x</a>
<a href='cuda-toolkit-12-9_12.9.1-1_amd64.deb'>x</a><a href='cuda-toolkit-13-2_13.2.2-1_amd64.deb'>x</a>
<a href='cuda-toolkit-13-3_13.3.1-1_amd64.deb'>x</a><a href='cuda-toolkit-13-5_13.5.0-1_amd64.deb'>x</a>"""

UBUNTU = {"ID": "ubuntu", "VERSION_ID": "24.04"}


class TestCeiling(unittest.TestCase):
    def test_new_and_old_headers(self):
        self.assertEqual(cs.driver_ceiling("| KMD Version: 610.91  CUDA UMD Version: 13.3 |"), (13, 3))
        self.assertEqual(cs.driver_ceiling("| Driver Version: 550.54  CUDA Version: 12.4 |"), (12, 4))
        self.assertIsNone(cs.driver_ceiling(""))


class TestRepo(unittest.TestCase):
    def test_wsl_and_ubuntu(self):
        self.assertTrue(cs.repo_url("wsl2", {}, "x86_64").endswith("/wsl-ubuntu/x86_64/"))
        self.assertTrue(cs.repo_url("ubuntu", UBUNTU, "x86_64").endswith("/ubuntu2404/x86_64/"))
        self.assertTrue(cs.repo_url("ubuntu", {"ID": "ubuntu", "VERSION_ID": "22.04"}, "aarch64")
                        .endswith("/ubuntu2204/sbsa/"))

    def test_rejections(self):
        with self.assertRaises(StepError):
            cs.repo_url("ubuntu", {"ID": "fedora", "VERSION_ID": "40"}, "x86_64")
        with self.assertRaises(StepError):
            cs.repo_url("wsl2", {}, "aarch64")


class TestPick(unittest.TestCase):
    def test_newest_not_above_ceiling(self):
        self.assertEqual(cs.pick_toolkit(INDEX, (13, 3)), "13-3")
        self.assertEqual(cs.pick_toolkit(INDEX, (13, 4)), "13-3")
        self.assertEqual(cs.pick_toolkit(INDEX, (13, 0)), "12-9")
        self.assertIsNone(cs.pick_toolkit(INDEX, (11, 8)))

    def test_keyring(self):
        self.assertEqual(cs.pick_keyring(INDEX), "cuda-keyring_1.1-1_all.deb")

    def test_prepare(self):
        c = cs.prepare("ubuntu", "CUDA Version: 13.4", UBUNTU, "x86_64", fetch=lambda _: INDEX)
        self.assertEqual((c["toolkit"], c["keyring"]), ("13-3", "cuda-keyring_1.1-1_all.deb"))

    def test_prepare_without_driver(self):
        with self.assertRaisesRegex(StepError, "driver"):
            cs.prepare("wsl2", "", {}, "x86_64", fetch=lambda _: INDEX)


class TestScript(unittest.TestCase):
    def test_no_driver_and_no_downloader(self):
        s = cs.render_script(Path("/x/cuda-keyring_1.1-1_all.deb"), "13-3")
        self.assertIn("apt-get install -y cuda-toolkit-13-3", s)
        self.assertIn("/usr/local/cuda-13.3/bin/nvcc", s)
        for banned in ("cuda-drivers", "nvidia-driver", "nvidia-open", "curl ", "wget "):
            self.assertNotIn(banned, s)
        self.assertNotIn("install -y cuda ", s)  # 元套件 cuda 會拉驅動 / the `cuda` metapackage pulls a driver


if __name__ == "__main__":
    unittest.main()
