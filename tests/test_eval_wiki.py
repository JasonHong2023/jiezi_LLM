"""中文維基摘要題測試（本機樣本，不連網）。 / Chinese Wikipedia summary-item tests (local fixtures, no network)."""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jiezi.eval import EvalError, wiki  # noqa: E402
from jiezi.eval.bank import Source  # noqa: E402

LIST = """__NOTOC__
{{/header}}
[[Wikipedia:說明]]
== 藝術和建築 ==
=== 建築 ===
[[蒙山大佛]]－[[西夏陵|西夏-{zh-tw:陵}-]]－[[File:x.png]]
== 生物學 ==
[[玳瑁]]－[[蒙山大佛]]－[[代谢#歷史|代謝]]
"""

PARA = "玳瑁是一種海龜。" * 20  # 160 字
HTML = f"""<html><body><section>
<table class="infobox"><tr><td><p>資訊框不應出現</p></td></tr></table>
<p>{PARA}<sup class="mw-ref reference">[1]</sup></p>
<style>.x{{}}</style>
<p>  第二段   有多餘   空白。{PARA}</p>
<p>{PARA}</p>
</section></body></html>"""

SRC = Source(key="zw", license_key="zh-wikipedia", task="summary", group="reasoning", scorer="pending_verifier",
             format="wiki_featured", count=2, stratify="section",
             options={"site": "https://zh.example.invalid", "list_revid": 1, "variant": "zh-tw", "max_chars": 400})


class FakeGet:
    def __init__(self):
        self.urls = []

    def __call__(self, url, headers=None):
        self.urls.append((url, headers))
        if "prop=wikitext" in url:
            return json.dumps({"parse": {"wikitext": LIST}})
        if "prop=revisions" in url:
            return json.dumps({"query": {"normalized": [], "redirects": [{"from": "玳瑁", "to": "玳瑁 (動物)"}],
                                         "pages": [{"title": "玳瑁 (動物)", "revisions": [{"revid": 42}]},
                                                   {"title": "不存在", "missing": True}]}})
        return HTML


class FakeResp:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.body.encode()


def opener_with(outcomes, headers=None):
    """outcomes：依序為 HTTP 狀態碼（拋錯）或字串（成功）。 / HTTP codes (raise) or strings (succeed), in order."""
    import urllib.error
    seq = list(outcomes)

    def op(req, timeout=None):
        o = seq.pop(0)
        if isinstance(o, int):
            raise urllib.error.HTTPError(req.full_url, o, "x", headers or {}, None)
        return FakeResp(o)
    return op


class TestGet(unittest.TestCase):
    def test_retries_504_then_succeeds(self):
        sleeps = []
        text = wiki._get("https://x.invalid/a", sleep=sleeps.append, opener=opener_with([504, "ok"]))
        self.assertEqual(text, "ok")
        self.assertEqual(sleeps, [5, wiki.REQUEST_GAP_S])

    def test_gives_up_with_eval_error(self):
        with self.assertRaisesRegex(EvalError, "HTTP 504"):
            wiki._get("https://x.invalid/a", sleep=lambda _: None, opener=opener_with([504, 504, 504, 504]))

    def test_429_honors_retry_after_with_cap(self):
        sleeps = []
        text = wiki._get("https://x.invalid/a", sleep=sleeps.append,
                         opener=opener_with([429, 429, "ok"], headers={"Retry-After": "600"}))
        self.assertEqual(text, "ok")
        self.assertEqual(sleeps, [wiki.RETRY_AFTER_CAP_S, wiki.RETRY_AFTER_CAP_S, wiki.REQUEST_GAP_S])

    def test_404_not_retried(self):
        with self.assertRaisesRegex(EvalError, "HTTP 404"):
            wiki._get("https://x.invalid/a", sleep=lambda _: None, opener=opener_with([404]))


class TestWiki(unittest.TestCase):
    def test_list_titles_sections_and_filters(self):
        rows = wiki.list_titles(LIST)
        self.assertEqual(rows, [("藝術和建築", "蒙山大佛"), ("藝術和建築", "西夏陵"),
                                ("生物學", "玳瑁"), ("生物學", "代谢")])

    def test_article_text_strips_and_cuts(self):
        text = wiki.article_text(HTML, max_chars=400)
        self.assertNotIn("資訊框", text)
        self.assertNotIn("[1]", text)
        self.assertNotIn("  ", text)
        self.assertEqual(text.count("\n"), 1)  # 只放得下兩段 / only two paragraphs fit
        self.assertLessEqual(len(text), 400)

    def test_first_paragraph_too_long_cuts_at_full_stop(self):
        text = wiki.article_text(f"<p>{PARA}</p>", max_chars=50)
        self.assertTrue(text.endswith("。"))
        self.assertLessEqual(len(text), 50)

    def test_population_and_materialize(self):
        get = FakeGet()
        w = wiki.Wiki("https://zh.example.invalid", "zh-tw", get)
        pop = wiki.population(SRC, w)
        self.assertEqual(len(pop), 4)
        self.assertEqual(w.latest_revids(["玳瑁"]), {"玳瑁": 42})
        item = wiki.materialize(SRC, w, "玳瑁", 42, "生物學")
        self.assertEqual(item["data"]["revid"], 42)
        self.assertEqual(item["stratum"], "生物學")
        self.assertIn("oldid=42", item["data"]["url"])
        url, headers = get.urls[-1]
        self.assertTrue(url.endswith("/42"))
        self.assertEqual(headers, {"Accept-Language": "zh-tw"})

    def test_too_short_article_is_an_error(self):
        w = wiki.Wiki("https://zh.example.invalid", "zh-tw", lambda url, headers=None: "<p>短</p>")
        with self.assertRaisesRegex(EvalError, "only"):
            wiki.materialize(SRC, w, "x", 1)


if __name__ == "__main__":
    unittest.main()
