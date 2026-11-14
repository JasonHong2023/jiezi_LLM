"""模型清單與下載驗證測試（本機假檔案，不連網）。
Tests for the model manifest and download verification (local fake files, no network)."""

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from jiezi_bootstrap import models  # noqa: E402
from jiezi_bootstrap.common import StepError, load_env  # noqa: E402

PAYLOAD = b"fake gguf weights\n" * 100
SHA = hashlib.sha256(PAYLOAD).hexdigest()


def entry(**over):
    e = {"name": "m", "file": "m.gguf", "url": "https://example.invalid/m.gguf", "sha256": SHA,
         "size": len(PAYLOAD), "license": "Apache-2.0", "license_url": "https://example.invalid/LICENSE",
         "commercial_use": False, "training_use": True, "license_checked": "2026-11-14",
         "source": "test", "smoke_test": True}
    e.update(over)
    return "[[model]]\n" + "".join(f"{k} = {v!r}\n".replace("True", "true").replace("False", "false")
                                   for k, v in e.items() if v is not None)


def fake_download(content):
    def dl(url, dest, log=print):
        dest.write_bytes(content)
    return dl


class TestManifest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, text):
        p = self.dir / "manifest.toml"
        p.write_text(text)
        return p

    def test_repo_manifest_is_valid(self):
        ms = models.load_manifest(ROOT / "models" / "manifest.toml")
        self.assertEqual(models.smoke_model(ms).file, "Qwen3-0.6B-Q8_0.gguf")

    def test_missing_license_fields(self):
        for field in ("license", "license_url", "commercial_use", "training_use", "license_checked", "source"):
            with self.subTest(field=field), self.assertRaisesRegex(StepError, f"missing {field}"):
                models.load_manifest(self.write(entry(**{field: None})))

    def test_false_flag_is_not_missing(self):
        self.assertFalse(models.load_manifest(self.write(entry()))[0].commercial_use)

    def test_flag_must_be_bool(self):
        with self.assertRaisesRegex(StepError, "true or false"):
            models.load_manifest(self.write(entry(training_use="yes")))

    def test_bad_sha_and_path(self):
        with self.assertRaisesRegex(StepError, "invalid sha256"):
            models.load_manifest(self.write(entry(sha256="abc")))
        with self.assertRaisesRegex(StepError, "plain file name"):
            models.load_manifest(self.write(entry(file="../evil.gguf")))

    def test_smallest_smoke_model(self):
        text = entry(name="big", file="b.gguf", size=999) + entry(name="small", file="s.gguf", size=5) \
            + entry(name="tiny-not-smoke", file="t.gguf", size=1, smoke_test=False)
        self.assertEqual(models.smoke_model(models.load_manifest(self.write(text))).name, "small")


class TestEnsure(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        p = self.dir / "manifest.toml"
        p.write_text(entry())
        self.model = models.load_manifest(p)[0]
        self.quiet = lambda *_: None

    def tearDown(self):
        self._tmp.cleanup()

    def test_download_then_skip(self):
        path, state = models.ensure(self.model, self.dir / "models", fake_download(PAYLOAD), self.quiet)
        self.assertEqual(state, "downloaded")
        self.assertEqual(path.read_bytes(), PAYLOAD)

        def boom(*_a, **_k):
            raise AssertionError("must not download again")
        self.assertEqual(models.ensure(self.model, self.dir / "models", boom, self.quiet)[1], "present")

    def test_sha_mismatch_deletes_download(self):
        bad = bytearray(PAYLOAD)
        bad[0] ^= 1
        with self.assertRaisesRegex(StepError, "SHA-256 mismatch"):
            models.ensure(self.model, self.dir / "models", fake_download(bytes(bad)), self.quiet)
        self.assertEqual(list((self.dir / "models").iterdir()), [])

    def test_size_mismatch(self):
        with self.assertRaisesRegex(StepError, "size"):
            models.ensure(self.model, self.dir / "models", fake_download(PAYLOAD + b"x"), self.quiet)

    def test_existing_wrong_file_is_not_overwritten(self):
        d = self.dir / "models"
        d.mkdir()
        (d / "m.gguf").write_bytes(b"something else")
        with self.assertRaisesRegex(StepError, "not overwriting"):
            models.ensure(self.model, d, fake_download(PAYLOAD), self.quiet)
        self.assertEqual((d / "m.gguf").read_bytes(), b"something else")


class TestEnv(unittest.TestCase):
    def test_env_file_and_override(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".env").write_text("# c\nJIEZI_MODELS_DIR=/data/models\nJIEZI_CLOUD_BASE_URL=\n")
            self.assertEqual(load_env(root, {}), {"JIEZI_MODELS_DIR": "/data/models"})
            self.assertEqual(load_env(root, {"JIEZI_MODELS_DIR": "/other"})["JIEZI_MODELS_DIR"], "/other")


if __name__ == "__main__":
    unittest.main()
