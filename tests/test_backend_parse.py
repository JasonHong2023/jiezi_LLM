import importlib.util
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

spec = importlib.util.spec_from_file_location("hwprobe", HERE.parent / "scripts" / "hwprobe.py")
hwprobe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hwprobe)


class TestDeviceLine(unittest.TestCase):
    def test_parses_accelerator_line(self):
        line = "  CUDA0: NVIDIA GeForce RTX 4050 Laptop GPU (6141 MiB, 5920 MiB free)"
        m = hwprobe.DEVICE_LINE.match(line)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "CUDA0")
        self.assertEqual(m.group(2), "NVIDIA GeForce RTX 4050 Laptop GPU")
        self.assertEqual(int(m.group(3)), 6141)
        self.assertEqual(int(m.group(4)), 5920)

    def test_parses_single_word_description(self):
        m = hwprobe.DEVICE_LINE.match("  Vulkan0: llvmpipe (4096 MiB, 4096 MiB free)")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(2), "llvmpipe")

    def test_ignores_none_marker(self):
        self.assertIsNone(hwprobe.DEVICE_LINE.match("  (none)"))

    def test_ignores_header(self):
        self.assertIsNone(hwprobe.DEVICE_LINE.match("Available devices:"))

    def test_description_with_parentheses(self):
        line = "  CUDA0: NVIDIA RTX (TM) 6000 (49152 MiB, 49000 MiB free)"
        m = hwprobe.DEVICE_LINE.match(line)
        self.assertIsNotNone(m)
        self.assertEqual(int(m.group(3)), 49152)


if __name__ == "__main__":
    unittest.main()
