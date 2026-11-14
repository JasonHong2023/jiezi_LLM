"""scripts/eval 端對端測試：假的 llama-server（真的回應 OpenAI 格式）＋暫存題庫，跑完整流程。
End-to-end test of scripts/eval with a fake llama-server (real OpenAI-format replies) and a temporary bank."""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jiezi.eval import __main__ as cli  # noqa: E402
from jiezi.eval import lock  # noqa: E402

FAKE_SERVER = f"""#!{sys.executable}
import sys, json, http.server
a = sys.argv[1:]
port = int(a[a.index("--port") + 1])
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *x): pass
    def do_GET(self):
        self.send_response(200); self.end_headers()
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        think = body.get("chat_template_kwargs", {{}}).get("enable_thinking")
        out = {{"model": body["model"], "choices": [{{"message": {{"content": "答案：B" if think is False else "?"}}}}],
               "usage": {{"completion_tokens": 3}}, "timings": {{"predicted_per_second": 50.0}}}}
        data = json.dumps(out).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers()
        self.wfile.write(data)
http.server.HTTPServer(("127.0.0.1", port), H).serve_forever()
"""


def mc(i, answer):
    return {"id": f"s/{i}", "source": "ceval-val", "task": "qa", "group": "knowledge", "scorer": "multiple_choice",
            "stratum": "s", "data": {"question": "題", "answer": answer, "choices": {"A": "a", "B": "b", "C": "c", "D": "d"}}}


class TestCli(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        r = self.root = Path(self._tmp.name)
        (r / "build-cpu" / "bin").mkdir(parents=True)
        srv = r / "build-cpu" / "bin" / "llama-server"
        srv.write_text(FAKE_SERVER)
        srv.chmod(0o755)
        (r / "models").mkdir()
        (r / "models" / "tiny.gguf").write_text("weights")
        (r / "models" / "manifest.toml").write_text(
            '[[model]]\nname = "tiny"\nfile = "tiny.gguf"\nsha256 = "' + "c" * 64 + '"\n')
        (r / "facts.json").write_text(json.dumps({"fingerprint": {"id": "f"},
                                                  "budgets": {"cpu": {"usable_threads": 2, "affinity_hint": None}}}))
        # 題庫：定義檔只需能被 load_bank 解析；題目快取與鎖定檔一致
        # Bank: the definition only needs to parse; the item cache must match the lock
        (r / "docs").mkdir()
        (r / "docs" / "licenses.md").write_text("| `lic` | x |\n")
        (r / "eval" / "banks").mkdir(parents=True)
        defs = "".join(f'[[source]]\nkey="{k}"\nlicense_key="lic"\ntask="{t}"\ngroup="knowledge"\n'
                       f'scorer="multiple_choice"\nformat="x"\ncount=50\n'
                       for k, t in (("ceval-val", "qa"), ("c", "code"), ("s", "summary"), ("t", "tool")))
        (r / "eval" / "banks" / "r0.toml").write_text('name="r0"\nversion=1\nseed=1\n' + defs)
        items = [mc(0, "B"), mc(1, "B"), mc(2, "C")]
        srcs = [{"key": "ceval-val", "items": [{"id": i["id"], "sha256": lock.item_hash(i)} for i in items]}]
        lk = {"bank": "r0", "sources": srcs, "bank_hash": lock.bank_hash(srcs)}
        (r / "eval" / "banks" / "r0.lock.json").write_text(json.dumps(lk))
        lock.write_items(items, cli.paths(r, "r0")["items"], lk)
        self.env = mock.patch.dict(os.environ, {"JIEZI_HOME": str(r), "JIEZI_PORT_BASE": "38200",
                                                "JIEZI_NIGHT_WINDOW": "", "JIEZI_CLOUD_BASE_URL": ""})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self._tmp.cleanup()

    def main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli.main(list(argv))
        return rc, out.getvalue() + err.getvalue()

    def test_local_run_end_to_end_and_resume(self):
        rc, out = self.main("run", "--now", "--model", "tiny", "--run-id", "t1")
        self.assertEqual(rc, 0, out)
        run = self.root / "var" / "eval" / "runs" / "t1"
        rep = json.loads((run / "report.json").read_text())
        k = rep["groups"]["knowledge"]["summary"]
        self.assertEqual((k["scored"], k["correct"]), (3, 2))  # 思考模式預設關閉 → 假伺服器回 B
        self.assertEqual(rep["tokens_per_second"]["mean"], 50.0)
        cond = json.loads((run / "conditions.json").read_text())["identity"]
        self.assertEqual((cond["model_file"], cond["thinking"], cond["engine"]["host"]), ("tiny.gguf", False, "127.0.0.1"))
        self.assertTrue(json.loads((run / "engine.json").read_text())["peak_rss_mib"])
        rc, out = self.main("run", "--now", "--model", "tiny", "--resume", "t1")
        self.assertEqual(rc, 0, out)
        rc, out = self.main("run", "--now", "--model", "tiny", "--resume", "t1", "--temperature", "0.5")
        self.assertEqual(rc, 2)
        self.assertIn("temperature", out)

    def test_refuses_outside_window(self):
        later = (datetime.now() + timedelta(hours=2)).strftime("%H:00")
        end = (datetime.now() + timedelta(hours=3)).strftime("%H:00")
        with mock.patch.dict(os.environ, {"JIEZI_NIGHT_WINDOW": f"{later}-{end}"}):
            rc, out = self.main("run", "--model", "tiny")
        self.assertEqual(rc, 2)
        self.assertIn("outside the night window", out)

    def test_cloud_needs_config(self):
        rc, out = self.main("run", "--now", "--backend", "cloud")
        self.assertEqual(rc, 2)
        self.assertIn("JIEZI_CLOUD_BASE_URL", out)

    def test_select_filters(self):
        items = [dict(mc(i, "B"), source=s) for i, s in enumerate(["a", "a", "b"])]
        items.append({**mc(9, "B"), "source": "c", "scorer": "pending_verifier", "group": "reasoning"})
        ns = lambda **kw: SimpleNamespace(**{"source": None, "group": None, "only_scorable": False, "limit": None, **kw})  # noqa: E731
        self.assertEqual(len(cli.select(items, ns(limit=1))), 3)
        self.assertEqual(len(cli.select(items, ns(only_scorable=True))), 3)
        self.assertEqual(len(cli.select(items, ns(group="reasoning"))), 1)


if __name__ == "__main__":
    unittest.main()
