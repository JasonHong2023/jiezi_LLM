"""測試用假辨識行程：與 src/jiezi/asr/worker.py 同一個協定，不載入模型。 / Fake ASR worker for tests."""
import json
import sys

print(json.dumps({"ok": True, "ready": True}), flush=True)
for line in sys.stdin:
    req = json.loads(line)
    if req.get("op") == "quit":
        break
    if req.get("op") != "transcribe":
        print(json.dumps({"ok": False, "error": "bad op"}), flush=True)
        continue
    print(json.dumps({"ok": True, "text": "这个软件明天上线", "audio_s": 3.5, "gen_s": 0.1,
                      "segments": [{"start": 0.0, "end": 1.5, "text": "这个软件"},
                                   {"start": 1.5, "end": None, "text": "明天上线"}],
                      "prompt": req.get("prompt")}, ensure_ascii=False), flush=True)
