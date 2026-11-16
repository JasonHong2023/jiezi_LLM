"""JSON 格式輸出測試（add-json-output）：response_format 解析、抽取、schema 檢查、gateway 分層、請教提示、CLI。
Structured-output tests: response_format parsing, extraction, schema checks, gateway tiers, consult prompt, CLI."""

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

import anyio

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from jiezi.runtime import escalation, jsonout as J  # noqa: E402

SCHEMA = {"type": "object", "required": ["city", "days"], "additionalProperties": False,
          "properties": {"city": {"type": "string", "minLength": 1}, "days": {"type": "integer", "minimum": 1, "maximum": 7},
                         "unit": {"enum": ["C", "F"]}, "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 2}}}
RF = {"type": "json_schema", "json_schema": {"name": "x", "schema": SCHEMA}}


class TestSpec(unittest.TestCase):
    def test_modes(self):
        self.assertIsNone(J.spec({}))
        self.assertIsNone(J.spec({"response_format": {"type": "text"}}))
        self.assertEqual(J.spec({"response_format": {"type": "json_object"}}), {"schema": None})
        self.assertEqual(J.spec({"response_format": RF}), {"schema": SCHEMA})
        self.assertEqual(J.spec({"response_format": {"type": "json_object", "schema": SCHEMA}}), {"schema": SCHEMA})

    def test_malformed(self):
        big = {"type": "object", "description": "x" * (J.MAX_SCHEMA_BYTES + 1)}
        for rf in ("json", {"type": "xml"}, {"type": "json_schema"}, {"type": "json_schema", "json_schema": {"schema": []}},
                   {}, {"type": "json_schema", "json_schema": {"schema": big}}):
            with self.assertRaises(J.BadFormat, msg=rf):
                J.spec({"response_format": rf})


class TestExtractAndValidate(unittest.TestCase):
    def test_extract(self):
        self.assertEqual(J.extract('{"a": 1}'), {"a": 1})
        self.assertEqual(J.extract('好的，結果如下：\n```json\n{"a": [1, 2]}\n```\n希望有幫助'), {"a": [1, 2]})
        self.assertEqual(J.extract('答案是 {"a": {"b": "}"}} 以上'), {"a": {"b": "}"}})
        self.assertEqual(J.extract("[1, 2]"), [1, 2])
        for bad in ("", "沒有 JSON", '{"a": '):
            with self.assertRaises(ValueError):
                J.extract(bad)

    def test_validate(self):
        ok = {"city": "台北", "days": 3, "unit": "C", "tags": ["a"]}
        self.assertEqual(J.validate(ok, SCHEMA), [])
        cases = [({"city": "台北"}, "missing required property 'days'"),
                 ({"city": "台北", "days": "3"}, "$.days: expected integer"),
                 ({"city": "台北", "days": True}, "$.days: expected integer"),
                 ({"city": "台北", "days": 9}, "maximum 7"),
                 ({"city": "", "days": 1}, "shorter than 1"),
                 ({"city": "台北", "days": 1, "unit": "K"}, "must be one of"),
                 ({"city": "台北", "days": 1, "x": 1}, "unexpected property 'x'"),
                 ({"city": "台北", "days": 1, "tags": ["a", 2]}, "$.tags[1]: expected string"),
                 ({"city": "台北", "days": 1, "tags": ["a", "b", "c"]}, "at most 2 items"),
                 ([], "expected object")]
        for value, msg in cases:
            self.assertIn(msg, "; ".join(J.validate(value, SCHEMA)), value)
        self.assertEqual(J.validate(3.0, {"type": "integer"}), [])
        self.assertEqual(J.validate("x", {"anyOf": [{"type": "string"}, {"type": "null"}]}), [])
        self.assertTrue(J.validate(1, {"anyOf": [{"type": "string"}, {"type": "null"}]}))
        self.assertTrue(J.validate(1, {"oneOf": [{"type": "integer"}, {"type": "number"}]}))
        self.assertEqual(J.validate({"a": 1}, {"pattern": "x", "$ref": "#/y", "format": "date"}), [])  # 不認得的不擋

    def test_check_and_verify(self):
        good = {"content": '```json\n{"city": "台北", "days": 2}\n```'}
        self.assertEqual(J.check({"schema": SCHEMA}, good)["status"], "pass")
        self.assertEqual(J.check({"schema": None}, {"content": "[1]"})["status"], "fail")
        self.assertEqual(J.check({"schema": None}, {"content": "不是"})["status"], "fail")
        v = escalation.verify({"response_format": RF}, {"content": '{"city": "台北"}'})
        self.assertEqual(v["status"], "fail")
        self.assertIn("days", v["error"])
        self.assertEqual(escalation.verify({"response_format": RF}, good)["status"], "pass")
        self.assertEqual(escalation.verify({}, {"content": "一般文字"})["status"], "not_applicable")

    def test_normalize_key_and_convert(self):
        m = {"content": '說明\n```json\n{"b": 1, "a": "台北"}\n```'}
        self.assertTrue(J.normalize(m))
        self.assertEqual(m["content"], '{"b": 1, "a": "台北"}')
        self.assertFalse(J.normalize({"content": "沒有"}))
        self.assertEqual(J.key({"content": '{"b":1,"a":2}'}), J.key({"content": '{ "a": 2, "b": 1 }'}))
        self.assertEqual(J.key({"content": "x"}), "invalid")
        out = json.loads(J.convert_values('{"软件": "软件", "n": [1, "软件"]}', lambda s: s.replace("软件", "軟體")))
        self.assertEqual(out, {"软件": "軟體", "n": [1, "軟體"]})          # 鍵不動 / keys untouched
        self.assertEqual(J.convert_values("软件", lambda s: "軟體"), "軟體")


class TestGateway(unittest.TestCase):
    def post(self, body, answers, cloud=None, consultant=None, **kw):
        import httpx
        from starlette.testclient import TestClient
        from test_runtime_gateway import KEY, local_handler, make_supervisor
        from jiezi.runtime.gateway import Gateway, create_app
        from jiezi.runtime.trajectory import TrajectoryWriter
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            sup, _, patch = make_supervisor(tmp, **{"samples": 1, **kw})
            lh, seen = local_handler([{"role": "assistant", "content": a} for a in answers])
            gw = Gateway(sup.s, sup, TrajectoryWriter(tmp / "traj", log=lambda *_: None),
                         local_http=httpx.AsyncClient(transport=httpx.MockTransport(lh)),
                         cloud_http=httpx.AsyncClient(transport=httpx.MockTransport(cloud)) if cloud else None,
                         consultant=consultant, log=lambda *_: None)
            with patch, TestClient(create_app(gw)) as c:
                r = c.post("/v1/chat/completions", headers={"Authorization": f"Bearer {KEY}"}, json=body)
            recs = [json.loads(x) for f in (tmp / "traj").glob("*.jsonl") for x in f.read_text(encoding="utf-8").splitlines()]
        return r, seen, recs

    def body(self, q="台北三天的天氣查詢參數", **kw):
        return {"model": "jiezi-local", "messages": [{"role": "user", "content": q}], "response_format": RF, **kw}

    def test_valid_answer_is_bare_json(self):
        r, seen, recs = self.post(self.body(), ['```json\n{"city": "台北", "days": 3}\n```'])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(json.loads(r.json()["choices"][0]["message"]["content"]), {"city": "台北", "days": 3})
        self.assertEqual(r.json()["jiezi"]["verification"], "pass")
        self.assertEqual(seen[0]["response_format"], RF)                   # 文法限制交給引擎 / the engine gets the format
        self.assertTrue(recs[0]["json_mode"])

    def test_retry_then_pass(self):
        r, seen, _ = self.post(self.body(), ['{"city": "台北"}', '{"city": "台北", "days": 3}'])
        self.assertEqual((r.json()["jiezi"]["tier"], r.json()["jiezi"]["verification"]), (1, "pass"))
        self.assertIn("days", seen[1]["messages"][-1]["content"])         # 重試時告知錯在哪 / the retry names the error

    def test_local_only_reports_failure(self):
        r, _, _ = self.post(self.body(), ["我不會輸出 JSON"])
        meta = r.json()["jiezi"]
        self.assertEqual((meta["verification"], meta["escalation"]), ("fail", "local_only_policy"))

    def test_escalates_to_cloud_and_extracts(self):
        def cloud(request):
            import httpx
            return httpx.Response(200, json={"model": "m", "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": '結果：{"city": "台北", "days": 2}'}}], "usage": {"total_tokens": 9}})
        r, _, recs = self.post({**self.body("幫我把「台北兩天」整理成參數"), "model": "jiezi"}, ["不是 JSON"], cloud=cloud, cloud_escalation=True,
                               cloud_base="http://cloud", escalation_models=["m"], consult_auto=False)
        meta = r.json()["jiezi"]
        self.assertEqual((meta["tier"], meta["verification"], meta["escalation"]), (3, "pass", "verification_failed"))
        self.assertEqual(r.json()["choices"][0]["message"]["content"], '{"city": "台北", "days": 2}')

    def test_streaming_is_verified_first(self):
        r, seen, _ = self.post(self.body(stream=True), ['{"city": "台北"}', '{"city": "台北", "days": 1}'])
        chunks = [json.loads(x[6:]) for x in r.text.splitlines() if x.startswith("data: {")]
        text = "".join((c["choices"][0]["delta"].get("content") or "") for c in chunks if c.get("choices"))
        self.assertEqual(json.loads(text), {"city": "台北", "days": 1})
        self.assertFalse(seen[0]["stream"])                               # 先驗證再送 / verified before sending

    def test_sampling_majority(self):
        r, seen, recs = self.post(self.body(), ['{"city":"台北","days":3}', '{"days": 3, "city": "台北"}', '{"city":"高雄","days":3}',
                                                '{"city": "台北", "days": 3}'], samples=4)
        self.assertEqual(r.json()["jiezi"]["confidence"], 0.75)
        self.assertEqual(json.loads(r.json()["choices"][0]["message"]["content"])["city"], "台北")

    def test_no_appendix_and_no_memory_shortcut(self):
        r, _, recs = self.post({**self.body("記住：我住台北"), "response_format": {"type": "json_object"}}, ['{"ok": true}'])
        self.assertEqual(r.json()["choices"][0]["message"]["content"], '{"ok": true}')   # 不走記憶的文字回覆
        r, _, _ = self.post({**self.body("12 * 34 等於多少"), "response_format": {"type": "json_object"}}, ['{"answer": 408}'])
        self.assertEqual(json.loads(r.json()["choices"][0]["message"]["content"]), {"answer": 408})  # 沒有附錄 / no appendix

    def test_malformed_response_format_is_400(self):
        r, seen, _ = self.post({**self.body(), "response_format": {"type": "xml"}}, ["x"])
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (400, "invalid_response_format"))
        self.assertEqual(seen, [])

    def test_text_mode_unchanged(self):
        r, seen, recs = self.post({"model": "jiezi-local", "messages": [{"role": "user", "content": "你好"}],
                                   "response_format": {"type": "text"}}, ["你好！"])
        self.assertEqual(r.json()["choices"][0]["message"]["content"], "你好！")
        self.assertNotIn("json_mode", recs[0])

    def test_consult_prompt_and_extraction(self):
        from jiezi.runtime.consult import render_prompt
        p = render_prompt(self.body())
        self.assertIn("JSON Schema", p)
        self.assertIn('"days"', p)
        self.assertNotIn("JSON Schema", render_prompt({"messages": [{"role": "user", "content": "嗨"}]}))

        class Fake:
            async def ask(self, body):
                return {"content": '```json\n{"city": "台北", "days": 5}\n```', "model": "claude",
                        "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
        r, _, recs = self.post({**self.body(), "model": "jiezi-ask-claude"}, ["x"], consultant=Fake())
        self.assertEqual(r.json()["choices"][0]["message"]["content"], '{"city": "台北", "days": 5}')
        self.assertEqual(r.json()["jiezi"]["verification"], "pass")
        self.assertIs(recs[0]["training_use"], False)


class TestAskSchema(unittest.TestCase):
    def run_ask(self, meta, **kw):
        import httpx
        from jiezi.cli import ask
        from jiezi.cli.client import Connection
        seen = []

        def handler(request):
            seen.append(json.loads(request.content))
            lines = ['data: ' + json.dumps({"choices": [{"delta": {"content": '{"a": 1}'}}]}),
                     'data: ' + json.dumps({"choices": [], "jiezi": meta}), "data: [DONE]"]
            return httpx.Response(200, text="\n\n".join(lines) + "\n\n")
        out, err = io.StringIO(), io.StringIO()
        rc = anyio.run(lambda: ask.run_ask("問", "jiezi", Connection("http://gw", "k" * 32), False, io.StringIO(), out, err,
                                           httpx.AsyncClient(transport=httpx.MockTransport(handler)), **kw))
        return rc, out.getvalue(), err.getvalue(), seen

    def test_schema_file_and_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "s.json"
            f.write_text(json.dumps(SCHEMA), encoding="utf-8")
            rc, out, _, seen = self.run_ask({"tier": 0, "verification": "pass"}, schema=str(f))
            self.assertEqual((rc, out), (0, '{"a": 1}\n'))
            self.assertEqual(seen[0]["response_format"]["json_schema"]["schema"], SCHEMA)
            rc, out, err, _ = self.run_ask({"tier": 0, "verification": "fail", "verification_error": "missing"}, schema=str(f))
            self.assertEqual(rc, 5)
            self.assertIn("missing", err)
            (Path(d) / "bad.json").write_text("{", encoding="utf-8")
            rc, _, err, seen = self.run_ask({}, schema=str(Path(d) / "bad.json"))
            self.assertEqual((rc, seen), (4, []))
        rc, _, _, seen = self.run_ask({"tier": 0, "verification": "pass"}, json_object=True)
        self.assertEqual(seen[0]["response_format"], {"type": "json_object"})
        rc, _, _, seen = self.run_ask({"tier": 0})
        self.assertNotIn("response_format", seen[0])


if __name__ == "__main__":
    unittest.main()
