"""add-asr：字幕格式、台灣用字、GPU 三方輪流與端點（假辨識行程，不載入模型）。
Subtitle formats, Taiwan output, three-way GPU turn-taking and the endpoint with a fake worker."""

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

from jiezi.asr import manager as A  # noqa: E402
from jiezi.runtime.gateway import Gateway, create_app  # noqa: E402
from jiezi.runtime.trajectory import TrajectoryWriter  # noqa: E402
from jiezi.tts import manager as M  # noqa: E402
from test_runtime_gateway import KEY, make_supervisor  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"
HAS_FFMPEG = shutil.which("ffmpeg") is not None


def spawn(script: str, cwd: Path):
    def go():
        return subprocess.Popen([sys.executable, "-I", str(FIX / script)], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1, cwd=str(cwd))
    return go


def wav_bytes(tmp: Path, seconds: float = 1.0) -> bytes:
    p = tmp / "in.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i",
                    f"sine=frequency=300:duration={seconds}", str(p)], check=True)
    return p.read_bytes()


class FormatTests(unittest.TestCase):
    RES = {"text": "你好世界", "audio_s": 65.5, "segments": [{"start": 0.0, "end": 1.25, "text": "你好"},
                                                            {"start": 61.0, "end": 65.5, "text": "世界"}]}

    def test_srt_vtt_text_json(self):
        srt, mime = A.render(self.RES, "srt")
        self.assertIn("1\n00:00:00,000 --> 00:00:01,250\n你好", srt)
        self.assertIn("2\n00:01:01,000 --> 00:01:05,500\n世界", srt)
        self.assertTrue(mime.startswith("application/x-subrip"))
        vtt, _ = A.render(self.RES, "vtt")
        self.assertTrue(vtt.startswith("WEBVTT\n\n00:00:00.000 --> 00:00:01.250"))
        self.assertEqual(A.render(self.RES, "text")[0], "你好世界\n")
        self.assertIn('"duration": 65.5', A.render(self.RES, "verbose_json")[0])

    def test_missing_end_filled(self):
        segs = A.segments_fixed([{"start": 0, "end": None, "text": "a"}, {"start": 2.0, "end": None, "text": "b"},
                                 {"start": 3, "end": 4, "text": ""}], 5.0)
        self.assertEqual([(s["start"], s["end"]) for s in segs], [(0, 2.0), (2.0, 3)])   # 下一段（空白）從 3 秒開始 / the next (empty) chunk starts at 3 s

    def test_taiwan_conversion(self):
        self.assertEqual(A.taiwan("这个软件"), "這個軟體")


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg not installed")
class ThreeWayTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.tmp = Path(self._t.name)
        self.addCleanup(self._t.cleanup)
        self.sup, self.engines, patch = make_supervisor(self.tmp, tts=True, asr=True)
        patch.start()
        self.addCleanup(patch.stop)
        (self.tmp / "var" / "tts").mkdir(parents=True)
        self.tts = M.TTSManager(self.sup.s, self.sup, log=lambda *_: None, spawn=spawn("fake_tts_worker.py", self.tmp))
        self.asr = A.ASRManager(self.sup.s, self.sup, log=lambda *_: None, spawn=spawn("fake_asr_worker.py", self.tmp))
        self.addCleanup(self.tts.shutdown)
        self.addCleanup(self.asr.shutdown)
        for target in ("jiezi.tts.manager.installed", "jiezi.asr.manager.installed"):
            p = mock.patch(target, return_value=None)
            p.start()
            self.addCleanup(p.stop)

    def test_voice_chat_turn(self):
        audio = wav_bytes(self.tmp)

        async def run():
            await self.sup.acquire()
            self.sup.release()
            res = await self.asr.transcribe(audio, "q.wav")          # 聽 / listen
            self.assertEqual(res["text"], "這個軟體明天上線")
            self.assertEqual(res["segments"][-1]["end"], 3.5)
            self.assertEqual((self.sup.gpu_owner, self.sup.status), ("asr", "unloaded"))
            await self.tts.speak("好的。")                             # 說：先停 ASR / speak: ASR is stopped first
            self.assertEqual(self.sup.gpu_owner, "tts")
            self.assertFalse(self.asr.alive())
            self.assertTrue(self.tts.alive())
            await self.sup.acquire()                                    # 想：停 TTS、載入核心 / think
            self.sup.release()
            self.assertIsNone(self.sup.gpu_owner)
            self.assertFalse(self.tts.alive())
            self.assertEqual(self.sup.status, "loaded")
        anyio.run(run)
        self.assertEqual(list((self.tmp / "var" / "asr" / "tmp").iterdir()), [])   # 上傳檔已刪 / upload deleted
        self.assertNotIn("軟體", (self.tmp / "var" / "asr" / "log.jsonl").read_text(encoding="utf-8"))

    def test_busy_and_bad_audio(self):
        async def run():
            with self.assertRaises(A.ASRError) as cm:
                await self.asr.transcribe(b"not audio at all", "x.wav")
            self.assertEqual(cm.exception.code, "invalid_audio")
            await self.sup.acquire()
            with mock.patch("jiezi.media.WAIT_CORE_S", 0.6):
                with self.assertRaises(A.ASRError) as cm:
                    await self.asr.transcribe(wav_bytes(self.tmp), "q.wav")
            self.assertEqual(cm.exception.code, "gpu_busy")
            self.sup.release()
        anyio.run(run)


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg not installed")
class EndpointTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.tmp = Path(self._t.name)
        self.addCleanup(self._t.cleanup)

    def client(self, asr=True):
        sup, _, patch = make_supervisor(self.tmp, asr=asr)
        patch.start()
        self.addCleanup(patch.stop)
        gw = Gateway(sup.s, sup, TrajectoryWriter(self.tmp / "traj", log=lambda *_: None),
                     local_http=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500))),
                     cloud_http=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500))),
                     log=lambda *_: None)
        if gw.asr:
            gw.asr._spawn = spawn("fake_asr_worker.py", self.tmp)
            self.addCleanup(gw.asr.shutdown)
        p = mock.patch("jiezi.asr.manager.installed", return_value=None)
        p.start()
        self.addCleanup(p.stop)
        return TestClient(create_app(gw))

    H = {"Authorization": f"Bearer {KEY}"}

    def test_multipart_and_raw(self):
        audio = wav_bytes(self.tmp)
        with self.client() as c:
            r = c.post("/v1/audio/transcriptions", headers=self.H, data={"model": "whisper-1", "response_format": "srt"},
                       files={"file": ("q.wav", audio, "audio/wav")})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertIn("00:00:00,000 --> 00:00:01,500\n這個軟體", r.text)
            r = c.post("/v1/audio/transcriptions?name=q.webm", headers={**self.H, "Content-Type": "audio/webm"},
                       content=audio)
            self.assertEqual(r.json(), {"text": "這個軟體明天上線"})
            self.assertEqual(c.get("/health").json()["asr"]["gpu_owner"], "asr")

    def test_disabled_unauthorized_bad_format_and_too_large(self):
        with self.client(asr=False) as c:
            self.assertEqual(c.post("/v1/audio/transcriptions", headers=self.H, content=b"x").status_code, 404)
        with self.client() as c:
            self.assertEqual(c.post("/v1/audio/transcriptions", content=b"x").status_code, 401)
            r = c.post("/v1/audio/transcriptions", headers=self.H, data={"response_format": "doc"},
                       files={"file": ("q.wav", b"x", "audio/wav")})
            self.assertEqual(r.status_code, 400)
            self.assertEqual(c.post("/v1/audio/transcriptions", headers=self.H, content=b"").status_code, 400)
            with mock.patch("jiezi.asr.manager.MAX_BYTES", 10):
                r = c.post("/v1/audio/transcriptions", headers={**self.H, "Content-Length": str(10 ** 9)},
                           content=b"x" * 20)
            self.assertEqual(r.status_code, 413)


if __name__ == "__main__":
    unittest.main()
