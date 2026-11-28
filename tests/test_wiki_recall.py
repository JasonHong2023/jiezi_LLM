"""使用者 ~/wiki 的唯讀索引與回答時附上（add-wiki-recall）。 / The user's wiki index and grounding."""

import json
import tempfile
import types
import unittest
from pathlib import Path

import anyio
import httpx

from jiezi import wiki_recall as W

PAGE = """---
title: CUDA 執行模型
tags: [CUDA]
---

# CUDA 執行模型

## 執行緒階層

CUDA 把平行運算分成 thread、block、grid 三層，同一個 block 的執行緒共用共享記憶體，可以彼此同步。

## 相關概念

- [[gpu-basics]]
- [[cuda-guide]]
"""


class TestWikiRecall(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        t = Path(self._t.name)
        self.root, self.v = t / "jiezi", t / "wiki"
        for d in ("concepts", "social", "raw/articles", "boards"):
            (self.v / d).mkdir(parents=True)
        (self.v / "concepts" / "cuda-model.md").write_text(PAGE, encoding="utf-8")
        (self.v / "concepts" / "福山堂.md").write_text("---\ntitle: 福山堂\n---\n\n福山堂是一間老字號的中藥行，"
                                                    "在巷子裡開了五十年，店裡的藥材都是老闆自己挑選的。\n",
                                                    encoding="utf-8")
        (self.v / "concepts" / "jian.md").write_text("---\ntitle: 知识图谱\n---\n\n## 知识图谱概论\n\n"
                                                  "知识图谱用节点和边表示实体之间的关系，常用于搜索引擎与问答系统的检索。\n",
                                                  encoding="utf-8")
        (self.v / "social" / "friend.md").write_text("---\ntitle: CUDA 朋友\n---\n\nCUDA thread block grid 私事。",
                                                     encoding="utf-8")
        (self.v / "raw" / "articles" / "cuda.md").write_text("CUDA thread block grid 原文" * 20, encoding="utf-8")
        (self.v / "concepts" / "big.md").write_text("CUDA thread block grid。" * 20000, encoding="utf-8")
        (self.v / "concepts" / "mine.md").write_text("---\ntitle: CUDA 私密\nprivate: true\n---\n\n"
                                                  "CUDA thread block grid 的私人筆記，內容足夠長足夠長足夠長足夠長足夠長足夠長。",
                                                  encoding="utf-8")
        (self.v / "concepts" / "keys.md").write_text(
            "---\ntitle: 金鑰設定\n---\n\n## 設定 CUDA 服務\n\nCUDA thread block grid 服務的 api_key: "
            "sk-abcdefghijklmnopqrstuvwxyz123456 填在這裡，然後重新啟動服務就可以了。\n", encoding="utf-8")
        (self.v / "concepts" / "link.md").symlink_to(self.v / "social" / "friend.md")
        (self.v / "index.md").write_text("# Wiki Index\n- [[cuda-model]] CUDA thread block grid 索引\n",
                                         encoding="utf-8")

    def tearDown(self):
        self._t.cleanup()

    def build(self):
        return W.build(self.root, self.v, log=lambda *_: None)

    def test_build_skips_excluded_big_private_secret_and_links(self):
        r = self.build()
        w = W.WikiRecall(W.db_path(self.root))
        paths = {p for (p,) in w.con.execute("SELECT path FROM pages")}
        self.assertEqual(paths, {"concepts/cuda-model.md", "concepts/福山堂.md", "concepts/jian.md",
                                 "concepts/keys.md"})
        self.assertEqual([p for p, _ in r["big"]], ["concepts/big.md"])
        self.assertEqual(r["private"], ["concepts/mine.md"])
        self.assertEqual(r["secret"], ["concepts/keys.md#設定 CUDA 服務"])
        heads = {h for (h,) in w.con.execute("SELECT heading FROM sections")}
        self.assertNotIn("相關概念", heads)                      # 只有連結的段落不收 / link lists skipped
        report = (W.db_path(self.root).parent / "report.md").read_text(encoding="utf-8")
        self.assertIn("concepts/keys.md#設定 CUDA 服務", report)
        self.assertNotIn("sk-abc", report)                       # 報告不含金鑰內容 / no secret text in the report

    def test_rebuild_only_redoes_changed_pages_and_drops_removed(self):
        self.build()
        r = self.build()
        self.assertEqual((r["indexed"], r["unchanged"]), (0, 4))
        (self.v / "concepts" / "福山堂.md").unlink()
        p = self.v / "concepts" / "cuda-model.md"
        p.write_text(PAGE.replace("三層", "三個層級"), encoding="utf-8")
        r = self.build()
        self.assertEqual((r["indexed"], r["removed"], r["pages"]), (1, 1, 3))

    def test_exclude_list_from_env(self):
        self.assertIn("private-notes/", W.excludes({"JIEZI_WIKI_RECALL_EXCLUDE": "private-notes/, x.md"}))
        W.build(self.root, self.v, W.excludes({"JIEZI_WIKI_RECALL_EXCLUDE": "concepts/福山堂.md"}), log=lambda *_: None)
        w = W.WikiRecall(W.db_path(self.root))
        self.assertEqual(w.search("福山堂在哪裡"), [])

    def test_search_thresholds_named_pages_and_simplified_text(self):
        self.build()
        w = W.WikiRecall(W.db_path(self.root))
        hits = w.search("CUDA 的 thread、block、grid 執行緒階層是什麼？")
        self.assertEqual([(h["path"], h["heading"]) for h in hits][:1], [("concepts/cuda-model.md", "執行緒階層")])
        self.assertEqual(w.search("說一個笑話"), [])
        self.assertEqual(w.search("台灣最高的山是哪座"), [])
        self.assertEqual(w.search("福山堂在哪裡")[0]["path"], "concepts/福山堂.md")
        kg = w.search("知識圖譜的節點和邊是什麼關係")     # 簡體頁面轉繁體後才找得到 / Simplified indexed as Traditional
        self.assertEqual(kg[0]["path"], "concepts/jian.md")
        self.assertIn("節點", kg[0]["text"])

    def test_grounding_is_private_and_stripped_before_escalation(self):
        self.build()
        w = W.WikiRecall(W.db_path(self.root))
        content, sources, trainable, appendix = W.grounding(w, "CUDA 的 thread、block、grid 執行緒階層是什麼？")
        self.assertTrue(content.startswith(W.HEAD))
        self.assertFalse(trainable)
        self.assertEqual(sources[0]["source"], "wiki")
        self.assertIn("concepts/cuda-model.md", appendix)
        msgs = [{"role": "system", "content": content}, {"role": "system", "content": "別的資料"},
                {"role": "user", "content": "問題"}]
        self.assertEqual([m["content"] for m in W.strip_private(msgs)], ["別的資料", "問題"])
        self.assertIsNone(W.grounding(w, "說一個笑話"))


class TestGatewayWikiRecall(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        t = Path(self._t.name)
        self.root, v = t / "jiezi", t / "wiki"
        (v / "concepts").mkdir(parents=True)
        (v / "concepts" / "cuda-model.md").write_text(PAGE, encoding="utf-8")
        W.build(self.root, v, log=lambda *_: None)

    def tearDown(self):
        self._t.cleanup()

    def gateway(self):
        from jiezi.runtime.gateway import Gateway
        gw = Gateway.__new__(Gateway)
        gw.s = types.SimpleNamespace(tools=False, web_read=False, notebook_recall=False, root=self.root)
        gw.memory = gw.dictionary = gw.curriculum = gw.knowledge = gw.writing = gw.laws = None
        gw.notebooks = gw.experience = None
        gw.wiki = W.WikiRecall(W.db_path(self.root))
        gw.log = lambda *_: None
        marks = []
        gw._untrainable = lambda rec, reason, model=None: marks.append(reason)
        return gw, marks

    def test_ground_attaches_wiki_untrainable(self):
        gw, marks = self.gateway()
        body = {"messages": [{"role": "user", "content": "CUDA 的 thread、block、grid 執行緒階層是什麼？"}]}
        rec = {}
        gw._ground(body, rec, [])
        self.assertEqual(rec["wiki_recall"], ["concepts/cuda-model.md"])
        self.assertTrue(body["messages"][0]["content"].startswith(W.HEAD))
        self.assertEqual(marks, ["private"])
        self.assertIn("【我的 wiki】", rec["dict_appendix"])

    def test_ground_skips_creative_and_documents(self):
        gw, _ = self.gateway()
        for q in ("說一個 CUDA thread block grid 執行緒階層的笑話",
                  "【文件：a】\nCUDA thread block grid 執行緒階層\n【文件結束】\n\n摘要這份文件"):
            body, rec = {"messages": [{"role": "user", "content": q}]}, {}
            gw._ground(body, rec, [])
            self.assertNotIn("wiki_recall", rec, q)

    def test_cloud_never_sees_wiki_passages(self):
        from jiezi.runtime.gateway import Gateway
        sent = []

        def handler(request):
            sent.append(json.loads(request.content))
            return httpx.Response(200, json={"model": "m", "choices": [{"message": {"role": "assistant",
                                                                                   "content": "ok"}}]})
        gw = Gateway.__new__(Gateway)
        gw.s = types.SimpleNamespace(cloud_key="", cloud_base="http://cloud.invalid", escalation_models=["m"])
        gw.cloud = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        gw.log = lambda *_: None
        body = {"model": "jiezi", "messages": [{"role": "system", "content": W.HEAD + "，秘密筆記"},
                                               {"role": "user", "content": "問題"}]}
        anyio.run(gw._cloud_once, body)
        self.assertEqual(sent[0]["messages"], [{"role": "user", "content": "問題"}])
        self.assertEqual(len(body["messages"]), 2)           # 本機那份不動 / the local copy is untouched


if __name__ == "__main__":
    unittest.main()
