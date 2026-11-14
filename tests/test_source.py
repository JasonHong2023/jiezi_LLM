"""llama.cpp 取得原始碼測試（規格 build / Pinned Source、No Vendor Modification）。
Tests for fetching llama.cpp (spec build / Pinned Source, No Vendor Modification).

以本機暫存 git repo 當作上游，不連網路。 / Uses a local temporary repo as upstream; no network."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from jiezi_bootstrap import source  # noqa: E402
from jiezi_bootstrap.common import StepError  # noqa: E402

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def sh(args, cwd):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True,
                          env={**os.environ, **GIT_ENV}).stdout.strip()


def make_upstream(root: Path) -> tuple[Path, list[str]]:
    up = root / "upstream"
    up.mkdir()
    sh(["git", "init", "-q", "-b", "master"], up)
    commits = []
    for i in range(3):
        (up / "f.txt").write_text(f"v{i}\n")
        sh(["git", "add", "f.txt"], up)
        sh(["git", "commit", "-q", "-m", f"c{i}"], up)
        commits.append(sh(["git", "rev-parse", "HEAD"], up))
    return up, commits


class TestReadPin(unittest.TestCase):
    def test_reads_repo_stack_md(self):
        pin = source.read_pin(ROOT / "openspec" / "specs" / "stack.md")
        self.assertRegex(pin.commit, r"^[0-9a-f]{40}$")
        self.assertTrue(pin.url.startswith("https://"))

    def test_missing_row_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "stack.md"
            p.write_text("| x | y |\n")
            with self.assertRaises(StepError):
                source.read_pin(p)


class TestFetch(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.up, self.commits = make_upstream(self.tmp)
        self.dest = self.tmp / "vendor" / "llama.cpp"

    def tearDown(self):
        self._tmp.cleanup()

    def pin(self, i):
        return source.Pin(commit=self.commits[i], url=self.up.as_uri())

    def head(self):
        return sh(["git", "rev-parse", "HEAD"], self.dest)

    def test_clean_machine_fetches_pinned_commit(self):
        self.assertEqual(source.fetch(self.dest, self.pin(1), log=lambda *_: None), "fetched")
        self.assertEqual(self.head(), self.commits[1])  # 不是 master 最新 / not master's tip

    def test_rerun_skips(self):
        source.fetch(self.dest, self.pin(2), log=lambda *_: None)
        self.assertEqual(source.fetch(self.dest, self.pin(2)), "present")

    def test_wrong_commit_stops_without_overwrite(self):
        source.fetch(self.dest, self.pin(2), log=lambda *_: None)
        with self.assertRaisesRegex(StepError, "Not overwriting"):
            source.fetch(self.dest, self.pin(0))
        self.assertEqual(self.head(), self.commits[2])

    def test_modified_sources_stop_and_list_files(self):
        source.fetch(self.dest, self.pin(2), log=lambda *_: None)
        (self.dest / "f.txt").write_text("edited\n")
        with self.assertRaisesRegex(StepError, r"(?s)uncommitted.*f\.txt"):
            source.fetch(self.dest, self.pin(2))

    def test_non_git_directory_stops(self):
        self.dest.mkdir(parents=True)
        with self.assertRaisesRegex(StepError, "not a git checkout"):
            source.fetch(self.dest, self.pin(2))

    def test_fallback_to_full_fetch(self):
        # 協定 v0 不允許以非分支頂端的 hash 淺層取得 → 必須走完整 fetch
        # Protocol v0 refuses a shallow fetch of a non-tip hash → the full fetch must kick in
        env = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "protocol.version", "GIT_CONFIG_VALUE_0": "0"}
        logs = []
        with mock.patch.dict(os.environ, env):
            self.assertEqual(source.fetch(self.dest, self.pin(0), log=logs.append), "fetched")
        self.assertEqual(self.head(), self.commits[0])
        self.assertTrue(any("falling back" in m for m in logs))

    def test_unknown_commit_leaves_nothing_behind(self):
        bad = source.Pin(commit="0" * 40, url=self.up.as_uri())
        with self.assertRaises(StepError):
            source.fetch(self.dest, bad, log=lambda *_: None)
        self.assertFalse(self.dest.exists())


if __name__ == "__main__":
    unittest.main()
