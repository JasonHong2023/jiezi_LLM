"""add-tts：文字處理、聲音登錄、後製、GPU 輪流與端點（假合成行程，不載入模型）。
Text prep, voice enrollment, post-processing, GPU turn-taking and endpoints with a fake worker; no model loaded."""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import anyio  # noqa: E402
import httpx  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from jiezi.runtime.gateway import Gateway, create_app  # noqa: E402
from jiezi.runtime.trajectory import TrajectoryWriter  # noqa: E402
from jiezi.tts import manager as M  # noqa: E402
from jiezi.tts import text as T  # noqa: E402
from jiezi.tts import voices as V  # noqa: E402
from test_runtime_gateway import KEY, make_supervisor  # noqa: E402

FAKE = Path(__file__).resolve().parent / "fixtures" / "fake_tts_worker.py"
HAS_FFMPEG = shutil.which("ffmpeg") is not None


def tone(path: Path, seconds: float) -> Path:
    subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i",
                    f"sine=frequency=220:duration={seconds}", str(path)], check=True)
    return path


def fake_spawn(cwd: Path):
    def spawn():
        return subprocess.Popen([sys.executable, "-I", str(FAKE)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True, bufsize=1, cwd=str(cwd))
    return spawn


class TextTests(unittest.TestCase):
    def test_clean_strips_markup_code_and_notes(self):
        ans = ("## 結論\n**光合作用**是植物把光變成養分的過程，見 [維基](https://zh.wikipedia.org/x)。\n"
               "```python\nprint(1)\n```\n- 第一點 `ls`\n\n---\n【記憶】2026-11-23 請教雲端的答案（[[光合作用]]）")
        out = T.clean_for_speech(ans)
        self.assertIn("光合作用是植物", out)
        self.assertIn(T.CODE_PLACEHOLDER, out)
        self.assertIn("維基", out)
        for bad in ("**", "##", "print(1)", "https://", "【記憶】", "[[", "請教雲端"):
            self.assertNotIn(bad, out)

    def test_split_respects_limit_and_drops_empty(self):
        text = "第一句很短。" + "這是一個沒有句號但是有逗號，" * 10 + "結束！" + "。。。"
        chunks = T.split_chunks(text, limit=30)
        self.assertTrue(all(len(c) <= 30 for c in chunks))
        self.assertEqual("".join(chunks).replace(" ", ""), text.replace("。。。", "").replace(" ", "")[:len("".join(chunks))])
        self.assertTrue(chunks[0].startswith("第一句"))
        self.assertEqual(T.split_chunks("……。！"), [])


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg not installed")
class VoiceTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.tmp = Path(self._t.name)
        self.var = self.tmp / "var"
        self.addCleanup(self._t.cleanup)

    def test_consent_required_and_duration_bounds(self):
        ok = tone(self.tmp / "me.wav", 4)
        with self.assertRaises(V.VoiceError):
            V.add(self.var, "me", ok, "")                       # 沒有同意聲明 / no consent
        self.assertFalse((V.voices_dir(self.var) / "me.wav").exists())
        with self.assertRaises(V.VoiceError):
            V.add(self.var, "short", tone(self.tmp / "s.wav", 1), "本人同意 2026-11-24")
        with self.assertRaises(V.VoiceError):
            V.add(self.var, "hung_yi_lee", ok, "本人同意")      # 不能蓋過內附語者 / no bundled names
        rec = V.add(self.var, "me", ok, "本人 2026-11-24 同意用於芥子朗讀")
        self.assertEqual(rec["id"], "me")
        self.assertEqual(len(rec["sha256"]), 64)
        voice, cloned = V.resolve(self.var, "me")
        self.assertTrue(cloned and voice["ref_wav"].endswith("me.wav"))
        self.assertEqual(V.resolve(self.var, None), ({"bundled": "female_voice"}, False))
        self.assertIn("me", [v["id"] for v in V.listing(self.var)])
        self.assertTrue(V.remove(self.var, "me"))
        with self.assertRaises(V.VoiceError):
            V.resolve(self.var, "me")

    def test_tampered_index_cannot_point_outside(self):
        V.voices_dir(self.var).mkdir(parents=True)
        (V.voices_dir(self.var) / "index.json").write_text('{"x": {"file": "../../etc/passwd"}}', encoding="utf-8")
        with self.assertRaises(V.VoiceError):
            V.resolve(self.var, "x")


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg not installed")
class PostprocessTests(unittest.TestCase):
    def test_speed_pitch_and_formats(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "a.wav"
            subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i",
                            "sine=frequency=440:duration=2:sample_rate=48000", str(src)], check=True)

            def dur(p):
                r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                    str(p)], capture_output=True, text=True)
                return float(r.stdout)
            M.postprocess(src, Path(d) / "fast.wav", "wav", speed=2.0)
            self.assertAlmostEqual(dur(Path(d) / "fast.wav"), 1.0, delta=0.1)
            M.postprocess(src, Path(d) / "high.wav", "wav", pitch=4)          # 音高變、長度不變 / same length
            self.assertAlmostEqual(dur(Path(d) / "high.wav"), 2.0, delta=0.1)
            for fmt in ("mp3", "flac", "opus"):
                M.postprocess(src, Path(d) / f"a.{fmt}", fmt)
                self.assertGreater((Path(d) / f"a.{fmt}").stat().st_size, 100)


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg not installed")
class GpuTurnTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.tmp = Path(self._t.name)
        self.addCleanup(self._t.cleanup)
        self.sup, self.engines, patch = make_supervisor(self.tmp, tts=True)
        patch.start()
        self.addCleanup(patch.stop)
        (self.tmp / "var" / "tts").mkdir(parents=True)
        self.tts = M.TTSManager(self.sup.s, self.sup, log=lambda *_: None, spawn=fake_spawn(self.tmp))
        self.addCleanup(self.tts.shutdown)
        p = mock.patch("jiezi.tts.manager.installed", return_value=None)
        p.start()
        self.addCleanup(p.stop)

    def test_tts_unloads_core_and_chat_takes_it_back(self):
        async def run():
            await self.sup.acquire()
            self.sup.release()
            self.assertEqual(self.sup.status, "loaded")
            data, mime, meta = await self.tts.speak("你好，這是測試。第二句。")
            self.assertEqual(mime, "audio/wav")
            self.assertTrue(data.startswith(b"RIFF"))
            self.assertEqual(self.sup.status, "unloaded")         # 核心讓出 GPU / core gave up the GPU
            self.assertEqual(self.sup.gpu_owner, "tts")
            self.assertTrue(self.tts.alive())
            self.assertFalse(meta["cloned"])
            await self.sup.acquire()                               # 聊天：先停 TTS 再載入 / chat: stop TTS, reload
            self.sup.release()
            self.assertFalse(self.tts.alive())
            self.assertIsNone(self.sup.gpu_owner)
            self.assertEqual(self.sup.status, "loaded")
            self.assertEqual(len(self.engines), 2)
        anyio.run(run)

    def test_busy_core_and_held_gpu_refuse(self):
        async def run():
            await self.sup.acquire()                                # 一個請求還在跑 / one request in flight
            with mock.patch.object(M, "WAIT_CORE_S", 0.6):
                with self.assertRaises(M.TTSError) as cm:
                    await self.tts.speak("忙碌中。")
            self.assertEqual(cm.exception.code, "gpu_busy")
            self.assertEqual(self.sup.status, "loaded")
            self.sup.release()
            self.sup.status = "held"
            with self.assertRaises(M.TTSError) as cm:
                await self.tts.speak("保留中。")
            self.assertEqual(cm.exception.code, "gpu_held")
        anyio.run(run)

    def test_worker_error_is_reported_and_files_logged_without_text(self):
        async def run():
            with self.assertRaises(M.TTSError) as cm:
                await self.tts.speak("FAIL 這句會失敗。")
            self.assertEqual(cm.exception.code, "tts_failed")
            await self.tts.speak("秘密內容不該進紀錄。", fmt="mp3", speed=1.2, pitch=-2)
        anyio.run(run)
        log = (self.tmp / "var" / "tts" / "log.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("秘密", log)
        self.assertIn('"format": "mp3"', log)
        self.assertEqual(list((self.tmp / "var" / "tts" / "out").glob("*.raw.wav")), [])


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg not installed")
class EndpointTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.tmp = Path(self._t.name)
        self.addCleanup(self._t.cleanup)

    def client(self, tts=True):
        sup, _, patch = make_supervisor(self.tmp, tts=tts)
        patch.start()
        self.addCleanup(patch.stop)
        (self.tmp / "var" / "tts").mkdir(parents=True, exist_ok=True)
        gw = Gateway(sup.s, sup, TrajectoryWriter(self.tmp / "traj", log=lambda *_: None),
                     local_http=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500))),
                     cloud_http=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500))),
                     log=lambda *_: None)
        if gw.tts:
            gw.tts._spawn = fake_spawn(self.tmp)
            self.addCleanup(gw.tts.shutdown)
        p = mock.patch("jiezi.tts.manager.installed", return_value=None)
        p.start()
        self.addCleanup(p.stop)
        return TestClient(create_app(gw))

    def post(self, c, body, key=KEY):
        return c.post("/v1/audio/speech", json=body, headers={"Authorization": f"Bearer {key}"})

    def test_disabled_and_unauthorized(self):
        with self.client(tts=False) as c:
            self.assertEqual(self.post(c, {"input": "你好"}).status_code, 404)
            self.assertEqual(c.get("/health").json()["tts"], "off")
        with self.client() as c:
            self.assertEqual(self.post(c, {"input": "你好"}, key="x" * 32).status_code, 401)

    def test_rejects_cloning_fields_unknown_voice_and_long_input(self):
        with self.client() as c:
            for body in ({"input": "你好", "reference_audio": "AAAA"}, {"input": "你好", "ref_wav": "/tmp/a.wav"},
                         {"input": "你好", "voice": {"file": "/tmp/a.wav"}}, {"input": "你好", "voice": "nobody"},
                         {"input": "你" * (T.MAX_INPUT_CHARS + 1)}, {"input": "你好", "response_format": "aac"},
                         {"input": "你好", "speed": 5}):
                r = self.post(c, body)
                self.assertEqual(r.status_code, 400, body)

    def test_speech_and_voices(self):
        with self.client() as c:
            r = self.post(c, {"model": "bluemagpie", "input": "你好，芥子。", "voice": "hung_yi_lee"})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.headers["content-type"], "audio/wav")
            self.assertEqual(r.headers["x-jiezi-voice"], "hung_yi_lee")
            v = c.get("/v1/audio/voices", headers={"Authorization": f"Bearer {KEY}"}).json()["data"]
            self.assertEqual([x["id"] for x in v if x["default"]], ["female_voice"])
            h = c.get("/health").json()["tts"]
            self.assertEqual((h["enabled"], h["gpu_owner"]), (True, "tts"))


class AskSpeakTests(unittest.TestCase):
    def test_speak_posts_answer_and_reports_path_on_stderr(self):
        import io
        from jiezi.cli.ask import _speak
        from jiezi.cli.client import Connection
        seen = {}

        def handler(req):
            seen["body"] = req.content.decode()
            seen["path"] = req.url.path
            return httpx.Response(200, content=b"RIFF", headers={"x-jiezi-file": "/x/var/tts/out/a.wav",
                                                                 "x-jiezi-audio-seconds": "1.5"})
        err = io.StringIO()

        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
                await _speak(Connection(url="http://gw", key=KEY), "答案。", err, c)
        anyio.run(run)
        self.assertEqual(seen["path"], "/v1/audio/speech")
        self.assertIn("答案", seen["body"])
        self.assertIn("/x/var/tts/out/a.wav", err.getvalue())


if __name__ == "__main__":
    unittest.main()
