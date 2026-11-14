"""機器指紋測試（規格：hwprobe / Machine Fingerprint）。
Tests for the machine fingerprint (spec: hwprobe / Machine Fingerprint)."""

import copy
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("hwprobe", ROOT / "scripts" / "hwprobe.py")
hwprobe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hwprobe)

HOST = {"is_wsl": True, "arch": "x86_64"}
CPU = {"model": "Example CPU", "physical_cores": 14, "logical_cores": 28}
MEM = {"total_mib": 31947, "available_mib": 17000}
GPUS = {"gpus": [{"name": "Example GPU", "vram_total_mib": 6141, "vram_free_mib": 5000, "driver": "610.91"}]}


def fp(host=HOST, cpu=CPU, mem=MEM, gpus=GPUS):
    return hwprobe.compute_fingerprint(host, cpu, mem, gpus)


class TestFingerprint(unittest.TestCase):
    def test_stable_when_dynamic_values_change(self):
        # 可用記憶體、可用 VRAM 改變時，id 不變 / Free memory and free VRAM changes keep the id
        mem2 = dict(MEM, available_mib=9000, total_mib=31900)  # 仍四捨五入到 31 GiB / still rounds to 31 GiB
        gpus2 = copy.deepcopy(GPUS)
        gpus2["gpus"][0]["vram_free_mib"] = 1200
        self.assertEqual(fp()["id"], fp(mem=mem2, gpus=gpus2)["id"])

    def test_changes_with_hardware(self):
        base = fp()["id"]
        self.assertNotEqual(base, fp(cpu=dict(CPU, model="Other CPU"))["id"])
        self.assertNotEqual(base, fp(mem=dict(MEM, total_mib=65536))["id"])
        self.assertNotEqual(base, fp(gpus={"gpus": []})["id"])

    def test_changes_with_driver(self):
        # 驅動升級會讓指紋改變（刻意，design D6）/ A driver upgrade changes the id (intentional, design D6)
        g = copy.deepcopy(GPUS)
        g["gpus"][0]["driver"] = "620.00"
        self.assertNotEqual(fp()["id"], fp(gpus=g)["id"])

    def test_platform_distinguishes_wsl(self):
        self.assertEqual(fp()["platform"], "wsl2")
        self.assertNotEqual(fp()["id"], fp(host=dict(HOST, is_wsl=False))["id"])

    def test_id_format(self):
        fid = fp()["id"]
        self.assertEqual(len(fid), 16)
        int(fid, 16)


if __name__ == "__main__":
    unittest.main(verbosity=2)
