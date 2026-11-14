import importlib.util
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

spec = importlib.util.spec_from_file_location("hwprobe", HERE.parent / "scripts" / "hwprobe.py")
hwprobe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hwprobe)


# 本機 WSL2 實測拓撲（lscpu -e）：cpu 2k 與 2k+1 同屬 core k
WSL_INTERLEAVED = [[2 * k, 2 * k + 1] for k in range(14)]
# 另一種常見拓撲：cpu k 與 k+14 為 SMT 兄弟
SPLIT_SIBLINGS = [[k, k + 14] for k in range(14)]


def facts(physical=14, available=16624, free=5920, gpu=True, core_threads=None, wsl=False):
    if core_threads is None and physical == 14:
        core_threads = WSL_INTERLEAVED
    return {
        "host": {"is_wsl": wsl},
        "cpu": {"physical_cores": physical, "core_threads": core_threads or []},
        "memory": {"total_mib": 31947, "available_mib": available},
        "gpus": {"gpus": [{"name": "RTX 4050", "vram_total_mib": 6141, "vram_free_mib": free}]}
        if gpu
        else {"gpus": []},
    }


class TestBudgets(unittest.TestCase):
    def test_this_machine(self):
        b = hwprobe.compute_budgets(facts())
        self.assertEqual(b["cpu"]["reserved_cores"], 2)
        self.assertEqual(b["cpu"]["usable_threads"], 12)
        # 舊版錯誤值 "0-11" 只涵蓋 core 0–5（6 核 × 2 SMT）
        self.assertEqual(b["cpu"]["affinity_hint"], "4,6,8,10,12,14,16,18,20,22,24,26")
        self.assertEqual(b["ram"]["usable_mib"], 11636)
        self.assertEqual(b["ram"]["binding_constraint"], "fraction")
        self.assertEqual(b["vram"]["usable_mib"], 4896)
        self.assertEqual(b["vram"]["binding_constraint"], "floor")

    def test_low_ram_never_negative(self):
        b = hwprobe.compute_budgets(facts(available=1000))
        self.assertGreaterEqual(b["ram"]["usable_mib"], 0)
        self.assertEqual(b["ram"]["usable_mib"], 0)
        self.assertEqual(b["ram"]["binding_constraint"], "floor")

    def test_ram_below_floor_yields_zero(self):
        b = hwprobe.compute_budgets(facts(available=2000))
        self.assertEqual(b["ram"]["usable_mib"], 0)
        self.assertEqual(b["ram"]["binding_constraint"], "floor")

    def test_zero_available(self):
        b = hwprobe.compute_budgets(facts(available=0, free=0))
        self.assertEqual(b["ram"]["usable_mib"], 0)
        self.assertEqual(b["vram"]["usable_mib"], 0)

    def test_single_core_still_usable(self):
        b = hwprobe.compute_budgets(facts(physical=1, gpu=False))
        self.assertEqual(b["cpu"]["usable_threads"], 1)
        self.assertEqual(b["cpu"]["reserved_cores"], 0)

    def test_four_cores(self):
        b = hwprobe.compute_budgets(facts(physical=4, gpu=False))
        self.assertEqual(b["cpu"]["usable_threads"], 2)

    def test_no_gpu(self):
        b = hwprobe.compute_budgets(facts(gpu=False))
        self.assertIsNone(b["vram"])

    def test_floor_binds_when_free_is_small(self):
        b = hwprobe.compute_budgets(facts(free=6800))
        self.assertEqual(b["vram"]["usable_mib"], 5776)
        self.assertEqual(b["vram"]["binding_constraint"], "floor")

    def test_fraction_binds_when_free_is_large(self):
        b = hwprobe.compute_budgets(facts(free=20000))
        self.assertEqual(b["vram"]["usable_mib"], 17000)
        self.assertEqual(b["vram"]["binding_constraint"], "fraction")


class TestAffinity(unittest.TestCase):
    def cpus(self, hint):
        out = set()
        for part in hint.split(","):
            a, _, b = part.partition("-")
            out.update(range(int(a), int(b or a) + 1))
        return out

    def test_one_thread_per_usable_core_interleaved(self):
        b = hwprobe.compute_budgets(facts())
        chosen = self.cpus(b["cpu"]["affinity_hint"])
        self.assertEqual(len(chosen), b["cpu"]["usable_threads"])
        cores = {c // 2 for c in chosen}
        self.assertEqual(len(cores), 12, "每個邏輯 CPU 必須落在不同實體核")
        self.assertNotIn(0, cores)
        self.assertNotIn(1, cores)

    def test_split_sibling_layout(self):
        b = hwprobe.compute_budgets(facts(core_threads=SPLIT_SIBLINGS))
        self.assertEqual(b["cpu"]["affinity_hint"], "2-13")

    def test_missing_topology_refuses_to_guess(self):
        b = hwprobe.compute_budgets(facts(physical=8, core_threads=[], gpu=False))
        self.assertIsNone(b["cpu"]["affinity_hint"])
        self.assertIn("topology unavailable", b["cpu"]["affinity_reason"])

    def test_topology_count_mismatch_refuses(self):
        b = hwprobe.compute_budgets(facts(core_threads=WSL_INTERLEAVED[:10]))
        self.assertIsNone(b["cpu"]["affinity_hint"])

    def test_single_core_keeps_it(self):
        b = hwprobe.compute_budgets(facts(physical=1, core_threads=[[0, 1]], gpu=False))
        self.assertEqual(b["cpu"]["affinity_hint"], "0")

    def test_wsl_note(self):
        self.assertIn("topology_note", hwprobe.compute_budgets(facts(wsl=True))["cpu"])
        self.assertNotIn("topology_note", hwprobe.compute_budgets(facts())["cpu"])

    def test_cpu_list_ranges(self):
        self.assertEqual(hwprobe._cpu_list([6, 0, 1, 2, 4]), "0-2,4,6")
        self.assertEqual(hwprobe._cpu_list([3]), "3")


if __name__ == "__main__":
    unittest.main(verbosity=2)
