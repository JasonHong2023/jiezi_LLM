"""測試用假合成行程：與 src/jiezi/tts/worker.py 同一個協定，不載入模型。 / Fake TTS worker for tests."""
import json
import sys
import wave

print(json.dumps({"ok": True, "ready": True, "voices": ["female_voice", "hung_yi_lee"], "sample_rate": 48000}),
      flush=True)
for line in sys.stdin:
    req = json.loads(line)
    if req.get("op") == "quit":
        break
    if req.get("op") != "synth":
        print(json.dumps({"ok": False, "error": "bad op"}), flush=True)
        continue
    if any("FAIL" in c for c in req["chunks"]):
        print(json.dumps({"ok": False, "error": "boom"}), flush=True)
        continue
    n = 4800 * len(req["chunks"])
    with wave.open(req["out"], "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(b"\x00\x10" * n)
    print(json.dumps({"ok": True, "audio_s": n / 48000, "gen_s": 0.01, "chunks": len(req["chunks"]),
                      "voice": req["voice"]}), flush=True)
